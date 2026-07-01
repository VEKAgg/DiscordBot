from __future__ import annotations

import logging
from datetime import UTC, datetime

from src.database.database import db

log = logging.getLogger('VEKA.inactivity')


async def get_inactive_users(week_days: int, month_days: int) -> list[dict]:
    """Fetch users who are inactive past the week or month threshold, not yet notified."""
    rows = await db.fetch(
        """
        SELECT discord_id, last_active, joined_at,
               inactive_week_notified, inactive_month_notified
        FROM users
        WHERE last_active IS NOT NULL
           OR joined_at IS NOT NULL
        """,
    )

    results = []
    for row in rows:
        last_seen = row['last_active'] or row['joined_at']
        if last_seen is None:
            continue
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=UTC)

        days_inactive = (datetime.now(UTC) - last_seen).days

        week_notify = not row['inactive_week_notified'] and days_inactive >= week_days
        month_notify = not row['inactive_month_notified'] and days_inactive >= month_days

        if week_notify or month_notify:
            results.append(
                {
                    'discord_id': row['discord_id'],
                    'last_active': last_seen,
                    'days_inactive': days_inactive,
                    'notify_week': week_notify,
                    'notify_month': month_notify,
                }
            )

    return results


async def mark_week_notified(discord_id: str) -> None:
    await db.execute(
        'UPDATE users SET inactive_week_notified = TRUE WHERE discord_id = $1',
        discord_id,
    )


async def mark_month_notified(discord_id: str) -> None:
    await db.execute(
        'UPDATE users SET inactive_month_notified = TRUE WHERE discord_id = $1',
        discord_id,
    )


async def reset_inactivity_flags(discord_id: str) -> None:
    await db.execute(
        """UPDATE users
           SET inactive_week_notified = FALSE, inactive_month_notified = FALSE
           WHERE discord_id = $1""",
        discord_id,
    )
