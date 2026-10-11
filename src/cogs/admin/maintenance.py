"""Maintenance Cog — nightly data retention.

Deletes rows that have outlived their purpose (see AGENTS.md "Data retention"). Aggregates that
commands and leaderboards read (``users`` totals, ``user_activity_daily``) are never touched, and
``audit_logs`` and ``feed_seen_items`` are kept (feed dedupe IDs live as long as their subscription).
"""

from __future__ import annotations

import logging
from datetime import UTC
from datetime import time as dt_time

from nextcord.ext import commands, tasks

from src.config.config import (
    RETENTION_ACTIVITY_LOG_DAYS,
    RETENTION_HONEYPOT_EVENTS_DAYS,
    RETENTION_MASSUNBAN_ITEMS_DAYS,
    RETENTION_WITHDRAWN_LISTING_IMAGES_DAYS,
)
from src.core.runtime_state import runtime_state
from src.database.database import db
from src.utils.safety import safe_background_task

logger = logging.getLogger('VEKA.maintenance')

# (label, SQL with $1 = days). Each statement is bounded by its own WHERE clause and indexed column.
RETENTION_RULES: tuple[tuple[str, str, int], ...] = (
    (
        'user_activity_log',
        'DELETE FROM user_activity_log WHERE created_at < NOW() - make_interval(days => $1)',
        RETENTION_ACTIVITY_LOG_DAYS,
    ),
    (
        'honeypot_events',
        'DELETE FROM honeypot_events WHERE created_at < NOW() - make_interval(days => $1)',
        RETENTION_HONEYPOT_EVENTS_DAYS,
    ),
    (
        'massunban_job_items',
        """DELETE FROM massunban_job_items i USING massunban_jobs j
           WHERE i.job_id = j.id AND j.completed_at IS NOT NULL
             AND j.completed_at < NOW() - make_interval(days => $1)""",
        RETENTION_MASSUNBAN_ITEMS_DAYS,
    ),
    (
        'marketplace_listing_images',
        """DELETE FROM marketplace_listing_images i USING marketplace_listings l
           WHERE i.listing_id = l.id AND l.status = 'withdrawn'
             AND l.updated_at < NOW() - make_interval(days => $1)""",
        RETENTION_WITHDRAWN_LISTING_IMAGES_DAYS,
    ),
)


async def run_retention() -> dict[str, str]:
    """Apply every retention rule; one failing rule does not stop the others."""
    results: dict[str, str] = {}
    for label, sql, days in RETENTION_RULES:
        try:
            results[label] = str(await db.execute(sql, days))
        except Exception as exc:
            results[label] = f'error: {type(exc).__name__}'
            logger.warning('Retention rule %s failed', label, exc_info=True)
    logger.info('Retention run: %s', results)
    return results


class Maintenance(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_ready(self) -> None:
        if not self.nightly_retention.is_running():
            self.nightly_retention.start()

    def cog_unload(self) -> None:
        self.nightly_retention.cancel()

    @tasks.loop(time=dt_time(hour=3, minute=30, tzinfo=UTC))
    @safe_background_task(name='nightly_retention')
    async def nightly_retention(self) -> None:
        if not runtime_state.db_available:
            return
        await run_retention()

    @nightly_retention.before_loop
    async def before_nightly_retention(self) -> None:
        await self.bot.wait_until_ready()


def setup(bot: commands.Bot) -> None:
    bot.add_cog(Maintenance(bot))
    logger.info('Loaded cog: src.cogs.admin.maintenance')
