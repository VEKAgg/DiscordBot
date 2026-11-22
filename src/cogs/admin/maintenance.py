"""Maintenance Cog — nightly data retention.

Deletes rows that have outlived their purpose (see AGENTS.md "Maintenance" and the VEKA "Bot Terms and
Privacy" page). Aggregates that commands and leaderboards read (``users`` totals, ``user_activity_daily``)
are not aged out, and ``feed_seen_items`` are kept (feed dedupe IDs live as long as their subscription).
Moderation records and the audit trail are kept two years. A server's data is deleted
``RETENTION_DEPARTED_GUILD_DAYS`` after the bot leaves it, unless the bot was added back.
"""

from __future__ import annotations

import logging
from datetime import UTC
from datetime import time as dt_time

from nextcord.ext import commands, tasks

from src.config.config import (
    RETENTION_ACTIVITY_LOG_DAYS,
    RETENTION_AUDIT_LOG_DAYS,
    RETENTION_DEPARTED_GUILD_DAYS,
    RETENTION_HONEYPOT_EVENTS_DAYS,
    RETENTION_INACTIVITY_NOTICE_DAYS,
    RETENTION_MASSUNBAN_ITEMS_DAYS,
    RETENTION_MODERATION_DAYS,
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
    (
        'warnings',
        'DELETE FROM warnings WHERE created_at < NOW() - make_interval(days => $1)',
        RETENTION_MODERATION_DAYS,
    ),
    (
        'security_events',
        'DELETE FROM security_events WHERE created_at < NOW() - make_interval(days => $1)',
        RETENTION_MODERATION_DAYS,
    ),
    (
        'audit_logs',
        'DELETE FROM audit_logs WHERE created_at < NOW() - make_interval(days => $1)',
        RETENTION_AUDIT_LOG_DAYS,
    ),
    (
        'inactivity_notices',
        'DELETE FROM inactivity_notices WHERE notified_at < NOW() - make_interval(days => $1)',
        RETENTION_INACTIVITY_NOTICE_DAYS,
    ),
)

# Per-server data deleted when the bot has been gone from a server long enough. $1 = guild ID.
# Marketplace sync state belongs to core's integration contract and is retired by core, not here.
GUILD_PURGE_STATEMENTS: tuple[str, ...] = (
    'DELETE FROM guild_settings WHERE guild_id = $1',
    'DELETE FROM guild_config WHERE guild_id = $1::bigint::text',
    'DELETE FROM guild_modules WHERE guild_id = $1',
    'DELETE FROM user_activity_daily WHERE guild_id = $1',
    'DELETE FROM user_activity_log WHERE guild_id = $1',
    'DELETE FROM leaderboard_snapshots WHERE guild_id = $1',
    'DELETE FROM inactivity_notices WHERE guild_id = $1',
    'DELETE FROM season_announcements WHERE guild_id = $1',
    'DELETE FROM server_stats_daily WHERE guild_id = $1',
    'DELETE FROM warnings WHERE guild_id = $1',
    'DELETE FROM honeypot_events WHERE guild_id = $1',
    'DELETE FROM honeypots WHERE guild_id = $1',
    'DELETE FROM honeypot_logging_config WHERE guild_id = $1',
    'DELETE FROM massunban_jobs WHERE guild_id = $1',
    'DELETE FROM feed_subscriptions WHERE guild_id = $1',
    'DELETE FROM mentorship_notification_preferences WHERE guild_id = $1',
    'DELETE FROM mentor_registrations WHERE guild_id = $1',
    'DELETE FROM mentorship_matches WHERE guild_id = $1',
    'DELETE FROM audit_logs WHERE guild_id = $1::bigint::text',
    'DELETE FROM bot_guild_snapshot WHERE guild_id = $1',
    'DELETE FROM bot_guild_departures WHERE guild_id = $1',
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


async def purge_departed_guilds(present_guild_ids: set[int] | None = None) -> dict[str, str]:
    """Delete the data of servers the bot left more than RETENTION_DEPARTED_GUILD_DAYS ago.

    Each server is purged in its own transaction. A server the bot is in again is only unmarked.
    """
    results: dict[str, str] = {}
    rows = await db.fetch(
        'SELECT guild_id FROM bot_guild_departures WHERE left_at < NOW() - make_interval(days => $1)',
        RETENTION_DEPARTED_GUILD_DAYS,
    )
    for row in rows:
        guild_id = int(row['guild_id'])
        try:
            if present_guild_ids is not None and guild_id in present_guild_ids:
                await db.execute('DELETE FROM bot_guild_departures WHERE guild_id = $1', guild_id)
                results[str(guild_id)] = 'present'
                continue
            async with db.transaction() as conn:
                for sql in GUILD_PURGE_STATEMENTS:
                    await conn.execute(sql, guild_id)
            results[str(guild_id)] = 'purged'
        except Exception as exc:
            results[str(guild_id)] = f'error: {type(exc).__name__}'
            logger.warning('Purge of departed guild %s failed', guild_id, exc_info=True)
    if results:
        logger.info('Departed guild purge: %s', results)
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
        await purge_departed_guilds({g.id for g in self.bot.guilds})

    @nightly_retention.before_loop
    async def before_nightly_retention(self) -> None:
        await self.bot.wait_until_ready()


def setup(bot: commands.Bot) -> None:
    bot.add_cog(Maintenance(bot))
    logger.info('Loaded cog: src.cogs.admin.maintenance')
