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


# What /privacy export returns (GDPR Art. 15/20): every table keyed by the member's Discord ID,
# plus the rows tied to their internal users.id. $1 = Discord ID as text.
_EXPORT_QUERIES: tuple[tuple[str, str], ...] = (
    ('account', 'SELECT to_jsonb(t) FROM users t WHERE t.discord_id = $1'),
    (
        'daily_activity',
        'SELECT to_jsonb(t) FROM user_activity_daily t WHERE t.user_id = $1::text::bigint ORDER BY t.activity_date',
    ),
    ('activity_details', 'SELECT to_jsonb(t) FROM user_activity_details t WHERE t.user_id = $1'),
    ('active_activities', 'SELECT to_jsonb(t) FROM user_active_activities t WHERE t.user_id = $1'),
    ('activity_log', 'SELECT to_jsonb(t) FROM user_activity_log t WHERE t.user_id = $1'),
    ('season_placings', 'SELECT to_jsonb(t) FROM leaderboard_snapshots t WHERE t.user_id = $1::text::bigint'),
    ('activity_role', 'SELECT to_jsonb(t) FROM user_rpg_roles t WHERE t.user_id = $1'),
    ('inactivity_notices', 'SELECT to_jsonb(t) FROM inactivity_notices t WHERE t.user_id = $1::text::bigint'),
    ('warnings', 'SELECT to_jsonb(t) FROM warnings t WHERE t.user_id = $1::text::bigint'),
    ('security_events', 'SELECT to_jsonb(t) FROM security_events t WHERE t.user_id = $1'),
    ('security_state', 'SELECT to_jsonb(t) FROM user_security t WHERE t.user_id = $1'),
    ('spam_trap_events', 'SELECT to_jsonb(t) FROM honeypot_events t WHERE t.user_id = $1::text::bigint'),
    ('audit_log', 'SELECT to_jsonb(t) FROM audit_logs t WHERE t.user_id = $1 ORDER BY t.created_at'),
    (
        'profile',
        'SELECT to_jsonb(t) FROM profiles t JOIN users u ON u.id = t.user_id WHERE u.discord_id = $1',
    ),
    (
        'portfolio',
        'SELECT to_jsonb(t) FROM portfolios t JOIN users u ON u.id = t.user_id WHERE u.discord_id = $1',
    ),
    (
        'marketplace_listings',
        """SELECT to_jsonb(t) FROM marketplace_listings t
           WHERE t.seller_id IN (SELECT id FROM users WHERE discord_id = $1)""",
    ),
    (
        'marketplace_offers',
        """SELECT to_jsonb(t) FROM marketplace_offers t
           WHERE t.buyer_id IN (SELECT id FROM users WHERE discord_id = $1)""",
    ),
    (
        'marketplace_review_votes',
        """SELECT to_jsonb(t) FROM marketplace_review_votes t
           WHERE t.user_id IN (SELECT id FROM users WHERE discord_id = $1)""",
    ),
    (
        'marketplace_seller_stats',
        """SELECT to_jsonb(t) FROM marketplace_seller_stats t
           WHERE t.user_id IN (SELECT id FROM users WHERE discord_id = $1)""",
    ),
    (
        'marketplace_transactions',
        """SELECT to_jsonb(t) FROM marketplace_transactions t
           WHERE t.buyer_id IN (SELECT id FROM users WHERE discord_id = $1) OR t.seller_id IN (SELECT id FROM users WHERE discord_id = $1)""",
    ),
    (
        'marketplace_views',
        """SELECT to_jsonb(t) FROM marketplace_views t
           WHERE t.user_id IN (SELECT id FROM users WHERE discord_id = $1)""",
    ),
    (
        'marketplace_watchlist',
        """SELECT to_jsonb(t) FROM marketplace_watchlist t
           WHERE t.user_id IN (SELECT id FROM users WHERE discord_id = $1)""",
    ),
    (
        'marketplace_fraud_flags',
        """SELECT to_jsonb(t) - 'resolved_by' FROM marketplace_fraud_flags t
           WHERE t.user_id IN (SELECT id FROM users WHERE discord_id = $1)""",
    ),
    (
        'mentor_registrations',
        """SELECT to_jsonb(t) FROM mentor_registrations t
           WHERE t.user_id IN (SELECT id FROM users WHERE discord_id = $1)""",
    ),
    (
        'mentorship_awards',
        """SELECT to_jsonb(t) FROM mentorship_awards t
           WHERE t.user_id IN (SELECT id FROM users WHERE discord_id = $1)""",
    ),
    (
        'mentorship_notification_preferences',
        """SELECT to_jsonb(t) FROM mentorship_notification_preferences t
           WHERE t.user_id IN (SELECT id FROM users WHERE discord_id = $1)""",
    ),
    (
        'mentorships',
        """SELECT to_jsonb(t) FROM mentorships t
           WHERE t.mentor_id IN (SELECT id FROM users WHERE discord_id = $1) OR t.mentee_id IN (SELECT id FROM users WHERE discord_id = $1)""",
    ),
    (
        'mentorship_matches',
        """SELECT to_jsonb(t) FROM mentorship_matches t
           WHERE t.mentor_id = $1::text::bigint OR t.mentee_id = $1::text::bigint""",
    ),
    (
        'quiz_attempts',
        """SELECT to_jsonb(t) FROM quiz_attempts t
           WHERE t.user_id IN (SELECT id FROM users WHERE discord_id = $1)""",
    ),
    (
        'workshop_participants',
        """SELECT to_jsonb(t) FROM workshop_participants t
           WHERE t.user_id IN (SELECT id FROM users WHERE discord_id = $1)""",
    ),
    (
        'workshops',
        """SELECT to_jsonb(t) FROM workshops t
           WHERE t.created_by IN (SELECT id FROM users WHERE discord_id = $1)""",
    ),
    (
        'user_footer_state',
        """SELECT to_jsonb(t) FROM user_footer_state t
           WHERE t.user_id = $1::text::bigint""",
    ),
    (
        'honeypots',
        """SELECT to_jsonb(t) FROM honeypots t
           WHERE t.created_by = $1::text::bigint OR t.updated_by = $1::text::bigint""",
    ),
    (
        'honeypot_logging_config',
        """SELECT to_jsonb(t) FROM honeypot_logging_config t
           WHERE t.updated_by = $1::text::bigint""",
    ),
    (
        'guild_modules',
        """SELECT to_jsonb(t) FROM guild_modules t
           WHERE t.updated_by = $1::text::bigint""",
    ),
    (
        'massunban_job_items',
        """SELECT to_jsonb(t) - 'banned_by' FROM massunban_job_items t
           WHERE t.target_user_id = $1""",
    ),
    (
        'massunban_jobs',
        """SELECT to_jsonb(t) - 'confirm_token_hash' FROM massunban_jobs t
           WHERE t.requested_by = $1::text::bigint""",
    ),
    (
        'marketplace_reviews',
        """SELECT to_jsonb(t) FROM marketplace_reviews t
           WHERE t.reviewer_id IN (SELECT id FROM users WHERE discord_id = $1) OR t.reviewee_id IN (SELECT id FROM users WHERE discord_id = $1)""",
    ),
    (
        'connection_requests',
        """SELECT to_jsonb(t) FROM connection_requests t
           WHERE t.requester_id IN (SELECT id FROM users WHERE discord_id = $1) OR t.recipient_id IN (SELECT id FROM users WHERE discord_id = $1)""",
    ),
    (
        'connections',
        """SELECT to_jsonb(t) FROM connections t
           WHERE t.user1_id IN (SELECT id FROM users WHERE discord_id = $1) OR t.user2_id IN (SELECT id FROM users WHERE discord_id = $1)""",
    ),
    (
        'marketplace_listing_images',
        """SELECT to_jsonb(t) - 'bytes' FROM marketplace_listing_images t
           WHERE t.listing_id IN (SELECT id FROM marketplace_listings WHERE seller_id IN (SELECT id FROM users WHERE discord_id = $1))""",
    ),
    (
        'marketplace_publications',
        """SELECT to_jsonb(t) FROM marketplace_publications t
           WHERE t.listing_id IN (SELECT id FROM marketplace_listings WHERE seller_id IN (SELECT id FROM users WHERE discord_id = $1))""",
    ),
    (
        'servers_owned',
        'SELECT to_jsonb(x) FROM (SELECT guild_id, name FROM bot_guild_snapshot WHERE owner_id = $1::text::bigint) x',
    ),
    (
        'bot_settings_changed',
        'SELECT to_jsonb(x) FROM (SELECT key, updated_at FROM bot_settings WHERE updated_by = $1::text::bigint) x',
    ),
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


async def export_member_data(user_id: int, *, database: Database = db) -> dict:
    """Everything the bot database holds about one member, as JSON-ready data (GDPR Art. 15)."""
    uid = _id(user_id)
    data: dict = {'discord_id': uid}
    for label, sql in _EXPORT_QUERIES:
        rows = await database.fetch(sql, uid)
        data[label] = [json.loads(r[0]) if isinstance(r[0], str) else r[0] for r in rows]
    return data
