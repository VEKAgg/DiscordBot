"""Feed subscription writes shared by the ``/feed`` commands and the dashboard API.

The per-server subscription limit is enforced under a PostgreSQL advisory lock (``feeds:<guild_id>``),
so the bot and the API process can't both pass the check. Polling stays in the bot (one poller);
nothing here posts to Discord.
"""

from __future__ import annotations

import json
from typing import Any

from src.config.config import FEED_MAX_SUBSCRIPTIONS
from src.database.database import db

MIN_INTERVAL, MAX_INTERVAL = 10, 1440
MAX_URL_LENGTH = 2000
MAX_NAME_LENGTH = 64

_COLUMNS = """id, guild_id, channel_id, feed_url, feed_name, poll_interval_minutes, paused, last_polled_at,
    consecutive_failures, next_retry_at, created_at"""


class FeedLimitReached(Exception):
    pass


async def _audit(conn, actor: str | None, guild_id: int, action: str, details: dict) -> None:
    if actor is None:
        return  # Discord commands are not audited individually (unchanged behaviour)
    await conn.execute(
        """INSERT INTO audit_logs (user_id, action, details, guild_id, severity)
           VALUES ($1, $2, $3::jsonb, $4, 'info')""",
        actor,
        action,
        json.dumps({'source': 'dashboard', **details}),
        str(guild_id),
    )


async def upsert_subscription(
    guild_id: int, channel_id: int, url: str, name: str, interval: int, *, actor: str | None = None
) -> dict[str, Any]:
    """Add a subscription, or update channel/name/interval if the URL is already subscribed (pause and
    outage state preserved). Raises FeedLimitReached when a new one would exceed the server limit."""
    async with db.transaction() as conn:
        await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1::text, 0))', f'feeds:{guild_id}')
        existing = await conn.fetchval(
            'SELECT id FROM feed_subscriptions WHERE guild_id = $1 AND feed_url = $2', guild_id, url
        )
        if existing is None:
            count = await conn.fetchval('SELECT COUNT(*) FROM feed_subscriptions WHERE guild_id = $1', guild_id)
            if count >= FEED_MAX_SUBSCRIPTIONS:
                raise FeedLimitReached
        row = await conn.fetchrow(
            f"""INSERT INTO feed_subscriptions (guild_id, channel_id, feed_url, feed_name, poll_interval_minutes)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (guild_id, feed_url) DO UPDATE SET
                    channel_id = $2, feed_name = $4, poll_interval_minutes = $5
                RETURNING {_COLUMNS}""",
            guild_id,
            channel_id,
            url,
            name[:MAX_NAME_LENGTH],
            interval,
        )
        await _audit(conn, actor, guild_id, 'dashboard_feed_saved', {'subscription_id': row['id']})
    return dict(row)


async def list_subscriptions(guild_id: int) -> list[dict]:
    rows = await db.fetch(f'SELECT {_COLUMNS} FROM feed_subscriptions WHERE guild_id = $1 ORDER BY id', guild_id)
    return [dict(r) for r in rows]


async def get_subscription(guild_id: int, subscription_id: int) -> dict | None:
    row = await db.fetch_one(
        f'SELECT {_COLUMNS} FROM feed_subscriptions WHERE id = $1 AND guild_id = $2', subscription_id, guild_id
    )
    return dict(row) if row else None


async def update_subscription(
    guild_id: int,
    subscription_id: int,
    *,
    channel_id: int | None = None,
    name: str | None = None,
    interval: int | None = None,
    paused: bool | None = None,
    actor: str | None = None,
) -> dict | None:
    """Partial update by ID within the guild (None = unchanged). Returns the row, or None if not found."""
    async with db.transaction() as conn:
        row = await conn.fetchrow(
            f"""UPDATE feed_subscriptions
                SET channel_id = COALESCE($3, channel_id), feed_name = COALESCE($4, feed_name),
                    poll_interval_minutes = COALESCE($5, poll_interval_minutes), paused = COALESCE($6, paused)
                WHERE id = $1 AND guild_id = $2
                RETURNING {_COLUMNS}""",
            subscription_id,
            guild_id,
            channel_id,
            name[:MAX_NAME_LENGTH] if name is not None else None,
            interval,
            paused,
        )
        if row is not None:
            await _audit(conn, actor, guild_id, 'dashboard_feed_updated', {'subscription_id': subscription_id})
    return dict(row) if row else None


async def remove_subscription(guild_id: int, subscription_id: int, *, actor: str | None = None) -> bool:
    """Delete a subscription (its dedupe history goes with it via the FK cascade)."""
    async with db.transaction() as conn:
        deleted = await conn.fetchval(
            'DELETE FROM feed_subscriptions WHERE id = $1 AND guild_id = $2 RETURNING id', subscription_id, guild_id
        )
        if deleted is not None:
            await _audit(conn, actor, guild_id, 'dashboard_feed_removed', {'subscription_id': subscription_id})
    return deleted is not None
