"""Activity accounting: one atomic SQL statement per metric batch.

Each award adds a real quantity (messages, commands or minutes) to the global ``users`` total and to
the per-guild ``user_activity_daily`` rollup for the UTC date, and adds XP:
``max(1, floor(xp_base × role multiplier × streak multiplier))`` per input row (0 when ``xp_base`` is 0).

Correctness rules (Pi review, 2026-10-11):
- The users rows are locked first (``FOR UPDATE``, ordered) and every derived value — the effective
  streak, the streak multiplier, the new level — comes from that locked, current row.
- Effective streak: active today → unchanged; active yesterday → +1 if this award touches the streak,
  else unchanged; older → 1 if it touches, else 0 (an expired streak gives no bonus).
- Presence metrics (gaming/streaming/coding) are written only if the server enabled tracking
  (``guild_settings.presence_tracking_enabled``) and ``users.presence_opt_in`` ("tracking allowed",
  default true; false after ``/privacy optout``) is true on
  the locked row, so a batch collected before an opt-out or ``/privacy delete`` can't write afterwards
  (the privacy delete locks the same row first).
- Input rows keep their own guild and role multiplier; totals are summed per user, rollups per guild.

Replaces RPGManager._award_points, which ran ~7 separate queries per message outside a transaction
and derived the level from a stale read.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from src.database.database import db

logger = logging.getLogger('VEKA.activity')

# metric -> (users total column, user_activity_daily column). Interpolated into SQL: keep static.
METRICS: dict[str, tuple[str, str]] = {
    'message': ('total_messages', 'messages'),
    'command': ('total_commands', 'commands'),
    'voice': ('total_voice_minutes', 'voice_minutes'),
    'gaming': ('total_gaming_minutes', 'gaming_minutes'),
    'streaming': ('total_streaming_minutes', 'streaming_minutes'),
    'coding': ('total_coding_minutes', 'coding_minutes'),
}
PRESENCE_METRICS = frozenset({'gaming', 'streaming', 'coding'})


@dataclass(frozen=True)
class Award:
    user_id: int
    guild_id: int
    quantity: int  # real amount recorded in the totals (never capped)
    xp_base: int  # XP before multipliers (capped by the caller where needed); 0 = no XP
    role_multiplier: float = 1.0
    touch_streak: bool = False  # counts as "active today" for the daily streak
    # Presence awards: the users.presence_opt_in_changed_at observed when the batch was collected.
    # The write only happens if the locked row still has that exact consent (no resurrection after
    # opt-out → opt-in or delete → opt-in).
    consent_at: datetime | None = None


def _award_sql(metric: str) -> str:
    total_col, daily_col = METRICS[metric]
    presence = metric in PRESENCE_METRICS
    presence_guard = 'AND l.presence_opt_in' if presence else ''
    # Each input row must carry the consent generation of the locked row (checked per row, not per user).
    row_guard = (
        'JOIN guild_settings gs ON gs.guild_id = i.guild_id AND gs.presence_tracking_enabled '
        'WHERE i.consent_at IS NOT DISTINCT FROM p.consent_at'
        if presence
        else ''
    )
    return f"""
WITH input AS (
    SELECT t.discord_id, t.guild_id, t.quantity,
           CASE WHEN 'leveling' = ANY(COALESCE(gm.disabled, '{{}}'::text[])) THEN 0 ELSE t.xp_base END AS xp_base,
           t.role_mult, t.touch_streak, t.consent_at
    FROM unnest($1::text[], $2::bigint[], $3::int[], $4::int[], $5::float8[], $6::bool[], $7::timestamptz[])
        AS t(discord_id, guild_id, quantity, xp_base, role_mult, touch_streak, consent_at)
    LEFT JOIN guild_modules gm ON gm.guild_id = t.guild_id
    WHERE NOT ('activity' = ANY(COALESCE(gm.disabled, '{{}}'::text[])))
),
today AS (SELECT (NOW() AT TIME ZONE 'UTC')::date AS d),
locked AS (
    SELECT u.discord_id, COALESCE(u.current_streak, 0) AS cur, u.last_streak_date AS last_day,
           u.presence_opt_in, u.presence_opt_in_changed_at AS consent_at
    FROM users u
    WHERE u.discord_id IN (SELECT discord_id FROM input)
    ORDER BY u.discord_id
    FOR UPDATE
),
per_user AS (
    SELECT l.discord_id, t.touch, l.consent_at,
           CASE
               WHEN l.last_day = (SELECT d FROM today) THEN l.cur
               WHEN l.last_day = (SELECT d FROM today) - 1 THEN l.cur + CASE WHEN t.touch THEN 1 ELSE 0 END
               ELSE CASE WHEN t.touch THEN 1 ELSE 0 END
           END AS eff
    FROM locked l
    JOIN (SELECT discord_id, bool_or(touch_streak) AS touch FROM input GROUP BY discord_id) t
      ON t.discord_id = l.discord_id
    WHERE TRUE {presence_guard}
),
computed AS (
    SELECT i.discord_id, i.guild_id, i.quantity,
           CASE WHEN i.xp_base <= 0 THEN 0
                ELSE GREATEST(1, floor(i.xp_base * i.role_mult * CASE
                    WHEN p.eff >= 30 THEN 2.0 WHEN p.eff >= 7 THEN 1.5 WHEN p.eff >= 3 THEN 1.25 ELSE 1.0
                END))::int
           END AS xp
    FROM input i JOIN per_user p ON p.discord_id = i.discord_id
    {row_guard}
),
updated AS (
    UPDATE users u
    SET points = COALESCE(u.points, 0) + s.xp,
        experience = COALESCE(u.experience, 0) + s.xp,
        level = floor(sqrt(GREATEST(COALESCE(u.points, 0) + s.xp, 0) / 100.0))::int,
        {total_col} = COALESCE(u.{total_col}, 0) + s.qty,
        last_active = NOW(),
        inactive_week_notified = FALSE,
        inactive_month_notified = FALSE,
        current_streak = CASE WHEN p.touch THEN p.eff ELSE u.current_streak END,
        longest_streak = CASE WHEN p.touch THEN GREATEST(COALESCE(u.longest_streak, 0), p.eff)
                              ELSE u.longest_streak END,
        last_streak_date = CASE WHEN p.touch THEN (SELECT d FROM today) ELSE u.last_streak_date END
    FROM (SELECT discord_id, SUM(xp)::int AS xp, SUM(quantity)::int AS qty FROM computed GROUP BY discord_id) s
    JOIN per_user p ON p.discord_id = s.discord_id
    WHERE u.discord_id = s.discord_id
    RETURNING u.discord_id
)
INSERT INTO user_activity_daily (user_id, guild_id, activity_date, xp_earned, {daily_col})
SELECT c.discord_id::bigint, c.guild_id, (SELECT d FROM today), SUM(c.xp), SUM(c.quantity)
FROM computed c
WHERE c.guild_id <> 0 AND c.discord_id IN (SELECT discord_id FROM updated)
GROUP BY c.discord_id, c.guild_id
ON CONFLICT (user_id, guild_id, activity_date) DO UPDATE SET
    xp_earned = user_activity_daily.xp_earned + EXCLUDED.xp_earned,
    {daily_col} = user_activity_daily.{daily_col} + EXCLUDED.{daily_col},
    updated_at = NOW()
"""


_ENSURE_USERS_SQL = """
INSERT INTO users (discord_id)
SELECT DISTINCT unnest($1::text[])
ON CONFLICT (discord_id) DO NOTHING
"""

# Detail rows are written only for members still allowed (locked row) in servers that enabled tracking.
_DETAILS_SQL = """
INSERT INTO user_activity_details (user_id, activity_type, activity_name, duration_minutes, last_seen)
SELECT x.u, x.t, LEFT(x.n, 200), SUM(x.m), NOW()
FROM unnest($1::text[], $2::text[], $3::text[], $4::int[], $5::timestamptz[], $6::bigint[]) AS x(u, t, n, m, c, g)
JOIN users usr ON usr.discord_id = x.u AND usr.presence_opt_in
                AND usr.presence_opt_in_changed_at IS NOT DISTINCT FROM x.c
JOIN guild_settings gs ON gs.guild_id = x.g AND gs.presence_tracking_enabled
LEFT JOIN guild_modules gm ON gm.guild_id = x.g
WHERE NOT ('activity' = ANY(COALESCE(gm.disabled, '{}'::text[])))
GROUP BY x.u, x.t, LEFT(x.n, 200)
ON CONFLICT (user_id, activity_type, activity_name) DO UPDATE SET
    duration_minutes = user_activity_details.duration_minutes + EXCLUDED.duration_minutes,
    last_seen = NOW()
"""


def _rows(awards: list[Award]) -> list[Award]:
    return [a for a in awards if a.quantity > 0 or a.xp_base > 0]


def _award_args(rows: list[Award]) -> tuple[Any, ...]:
    return (
        [str(a.user_id) for a in rows],
        [a.guild_id for a in rows],
        [a.quantity for a in rows],
        [a.xp_base for a in rows],
        [float(a.role_multiplier) for a in rows],
        [a.touch_streak for a in rows],
        [a.consent_at for a in rows],
    )


# (user_id, type, name, minutes, consent_at, guild_id) — guild = the server the minutes were credited to
Detail = tuple[int, str, str, int, datetime | None, int]

_LOCK_USERS_SQL = 'SELECT 1 FROM users WHERE discord_id = ANY($1::text[]) ORDER BY discord_id FOR UPDATE'


def _details_args(rows: list[Detail]) -> tuple[Any, ...]:
    return (
        [str(r[0]) for r in rows],
        [r[1] for r in rows],
        [r[2] for r in rows],
        [r[3] for r in rows],
        [r[4] for r in rows],
        [r[5] for r in rows],
    )


async def award(metric: str, awards: list[Award]) -> int:
    """Apply one batch of awards for one metric (e.g. a message or command). Returns input rows used."""
    if metric not in METRICS:
        raise ValueError(f'Unknown activity metric: {metric}')
    rows = _rows(awards)
    if not rows:
        return 0
    # Creating missing users must be its own statement: rows inserted in a CTE are invisible to an
    # UPDATE in the same statement.
    await db.execute(_ENSURE_USERS_SQL, [str(a.user_id) for a in rows])
    await db.execute(_award_sql(metric), *_award_args(rows))
    return len(rows)


async def award_tick(batches: dict[str, list[Award]], details: list[Detail]) -> None:
    """Apply one activity tick (all metrics + named details) in a single transaction.

    Every user in the tick is locked once, in sorted order, before any metric statement, so two
    concurrent ticks with overlapping users can't deadlock."""
    pending = {m: _rows(b) for m, b in batches.items() if m in METRICS}
    pending = {m: r for m, r in pending.items() if r}
    if not pending and not details:
        return
    pool = db.pool
    if pool is None:
        raise RuntimeError('database unavailable')
    ids = sorted({str(a.user_id) for rows in pending.values() for a in rows} | {str(d[0]) for d in details})
    async with pool.acquire() as conn, conn.transaction():
        if ids:
            await conn.execute(_ENSURE_USERS_SQL, ids)
            await conn.execute(_LOCK_USERS_SQL, ids)
        for metric, rows in pending.items():
            await conn.execute(_award_sql(metric), *_award_args(rows))
        if details:
            await conn.execute(_DETAILS_SQL, *_details_args(details))


async def add_activity_details(rows: list[Detail]) -> None:
    """Upsert detail rows for users whose current consent matches (one transaction, sorted locks)."""
    if not rows:
        return
    pool = db.pool
    if pool is None:
        raise RuntimeError('database unavailable')
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(_LOCK_USERS_SQL, sorted({str(r[0]) for r in rows}))
        await conn.execute(_DETAILS_SQL, *_details_args(rows))


# ---------------------------------------------------------------------------------------------------
# Leaderboards and aggregates (shared by the RPG cog and the dashboard API)
# ---------------------------------------------------------------------------------------------------

LEADERBOARD_CATEGORIES: dict[str, str] = {
    'xp': 'points',
    'chat': 'total_messages',
    'voice': 'total_voice_minutes',
    'gaming': 'total_gaming_minutes',
    'streaming': 'total_streaming_minutes',
    'coding': 'total_coding_minutes',
}
# users total column -> user_activity_daily column (per-server periods)
DAILY_COLUMNS: dict[str, str] = {
    'points': 'xp_earned',
    'total_messages': 'messages',
    'total_voice_minutes': 'voice_minutes',
    'total_gaming_minutes': 'gaming_minutes',
    'total_streaming_minutes': 'streaming_minutes',
    'total_coding_minutes': 'coding_minutes',
}
# Presence-derived stats: hidden for members who opted out.
PRESENCE_COLUMNS = frozenset({'total_gaming_minutes', 'total_streaming_minutes', 'total_coding_minutes'})
PERIODS = ('alltime', 'season', 'month', 'week')


def period_start(period: str) -> date:
    """First UTC day of a per-server period: last 7 days, last 30 days, or this calendar month."""
    today = datetime.now(UTC).date()
    if period == 'week':
        return today - timedelta(days=6)
    if period == 'month':
        return today - timedelta(days=29)
    return today.replace(day=1)


async def leaderboard(
    column: str, period: str | None, *, guild_id: int | None = None, limit: int = 10, offset: int = 0
) -> list[dict]:
    """Rows ``{discord_id, value}``. With ``guild_id`` the board is that server's own activity (period
    None/'alltime' = everything recorded there); without it, all-time totals across all servers.
    Presence columns exclude members who opted out."""
    if column not in DAILY_COLUMNS:
        raise ValueError(column)
    presence = column in PRESENCE_COLUMNS
    if guild_id is None:
        rows = await db.fetch(
            f"""
            SELECT discord_id, {column}::bigint AS value
            FROM users
            WHERE {column} > 0 {'AND presence_opt_in' if presence else ''}
            ORDER BY {column} DESC, discord_id
            LIMIT $1 OFFSET $2
            """,
            limit,
            offset,
        )
    else:
        daily_col = DAILY_COLUMNS[column]
        rows = await db.fetch(
            f"""
            SELECT d.user_id::text AS discord_id, SUM(d.{daily_col})::bigint AS value
            FROM user_activity_daily d
            {'JOIN users u ON u.discord_id = d.user_id::text AND u.presence_opt_in' if presence else ''}
            WHERE d.guild_id = $1 AND d.activity_date >= $2
            GROUP BY d.user_id
            HAVING SUM(d.{daily_col}) > 0
            ORDER BY value DESC, d.user_id
            LIMIT $3 OFFSET $4
            """,
            guild_id,
            date(2000, 1, 1) if period is None or period == 'alltime' else period_start(period),
            limit,
            offset,
        )
    return [dict(row) for row in rows]


async def member_period_totals(user_id: int, guild_id: int, period: str) -> dict:
    """One member's sums for a per-server period (messages, voice, XP, commands; presence minutes only
    if the member hasn't opted out). Same figures the period leaderboards use."""
    row = await db.fetch_one(
        """
        SELECT COALESCE(SUM(d.messages), 0) AS messages, COALESCE(SUM(d.voice_minutes), 0) AS voice_minutes,
               COALESCE(SUM(d.xp_earned), 0) AS xp, COALESCE(SUM(d.commands), 0) AS commands,
               COALESCE(SUM(d.gaming_minutes), 0) AS gaming_minutes,
               COALESCE(SUM(d.coding_minutes), 0) AS coding_minutes,
               COALESCE(SUM(d.streaming_minutes), 0) AS streaming_minutes,
               COALESCE(BOOL_OR(u.presence_opt_in), FALSE) AS opted_in
        FROM user_activity_daily d
        LEFT JOIN users u ON u.discord_id = d.user_id::text
        WHERE d.user_id = $1 AND d.guild_id = $2 AND d.activity_date >= $3
        """,
        user_id,
        guild_id,
        period_start(period) if period != 'alltime' else date(2000, 1, 1),
    )
    data = dict(row) if row else {}
    totals = {k: int(data.get(k) or 0) for k in ('messages', 'voice_minutes', 'xp', 'commands')}
    if data.get('opted_in'):
        totals.update({k: int(data.get(k) or 0) for k in ('gaming_minutes', 'coding_minutes', 'streaming_minutes')})
    return totals
