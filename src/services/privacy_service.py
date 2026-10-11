"""Owner-controlled presence consent and activity deletion shared by bot and API.

Each mutation locks the user and commits its audit and cache invalidation with the write.
No Discord/cog imports; callers update local caches only after this transaction succeeds.
"""

from __future__ import annotations

import json
from datetime import datetime

from src.database.database import Database, db

_LOCK_USER = 'SELECT 1 FROM users WHERE discord_id = $1 FOR UPDATE'
_DELETE_STATEMENTS = (
    'DELETE FROM user_active_activities WHERE user_id = $1',
    'DELETE FROM user_activity_details WHERE user_id = $1',
    'DELETE FROM user_activity_log WHERE user_id = $1',
    'DELETE FROM user_activity_daily WHERE user_id = $1::text::bigint',
    'DELETE FROM leaderboard_snapshots WHERE user_id = $1::text::bigint',
    'DELETE FROM user_rpg_roles WHERE user_id = $1',
    """UPDATE users SET points = 0, experience = 0, level = 0,
           total_messages = 0, total_voice_minutes = 0, total_commands = 0,
           total_gaming_minutes = 0, total_streaming_minutes = 0, total_coding_minutes = 0,
           current_streak = 0, longest_streak = 0, last_streak_date = NULL,
           presence_opt_in = FALSE, presence_opt_in_changed_at = clock_timestamp()
       WHERE discord_id = $1""",
)


def _id(user_id: int) -> str:
    if isinstance(user_id, bool) or not 0 < user_id <= 2**63 - 1:
        raise ValueError('Invalid Discord user ID')
    return str(user_id)


async def get_privacy(user_id: int, *, database: Database = db) -> dict:
    row = await database.fetch_one(
        'SELECT presence_opt_in, presence_opt_in_changed_at FROM users WHERE discord_id = $1', _id(user_id)
    )
    return {
        'presence_tracking': row is None or bool(row['presence_opt_in']),  # default allowed; false = opted out
        'changed_at': row['presence_opt_in_changed_at'] if row else None,
    }


async def _audit_and_notify(conn, uid: str, action: str, source: str, details: dict) -> None:
    await conn.execute(
        "INSERT INTO audit_logs (user_id, action, details, severity) VALUES ($1, $2, $3::jsonb, 'info')",
        uid,
        action,
        json.dumps({'source': source, **details}),
    )
    await conn.execute("SELECT pg_notify('veka_cache', $1)", f'privacy:{uid}')


async def set_presence_opt_in(
    user_id: int, enabled: bool, *, source: str = 'discord', database: Database = db
) -> datetime:
    uid = _id(user_id)
    if not isinstance(enabled, bool) or source not in {'discord', 'dashboard'}:
        raise ValueError('Invalid privacy mutation')
    async with database.transaction() as conn:
        await conn.execute('INSERT INTO users (discord_id) VALUES ($1) ON CONFLICT DO NOTHING', uid)
        before = await conn.fetchval('SELECT presence_opt_in FROM users WHERE discord_id = $1 FOR UPDATE', uid)
        changed_at = await conn.fetchval(
            'UPDATE users SET presence_opt_in = $2, presence_opt_in_changed_at = clock_timestamp() '
            'WHERE discord_id = $1 RETURNING presence_opt_in_changed_at',
            uid,
            enabled,
        )
        await _audit_and_notify(
            conn,
            uid,
            'dashboard_update_privacy' if source == 'dashboard' else 'privacy_consent_changed',
            source,
            {'before': bool(before), 'after': enabled},
        )
    return changed_at


async def delete_activity_data(user_id: int, *, source: str = 'discord', database: Database = db) -> None:
    uid = _id(user_id)
    if source not in {'discord', 'dashboard'}:
        raise ValueError('Invalid privacy mutation')
    async with database.transaction() as conn:
        # A tombstone user also serializes deletion with a first-ever concurrent activity award.
        await conn.execute('INSERT INTO users (discord_id) VALUES ($1) ON CONFLICT DO NOTHING', uid)
        await conn.execute(_LOCK_USER, uid)
        for sql in _DELETE_STATEMENTS:
            await conn.execute(sql, uid)
        await _audit_and_notify(
            conn,
            uid,
            'dashboard_delete_activity' if source == 'dashboard' else 'privacy_data_deleted',
            source,
            {'scope': 'activity'},
        )
