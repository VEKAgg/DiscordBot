"""Leaderboards, member period totals and daily server stats.

- Leaderboards and member totals: this server's own activity (all time = everything recorded here).
  Presence-derived figures (gaming/coding/streaming) are hidden for members who opted out.
- Daily stats: Manage Server or moderators.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, Path, Query

from src.api.auth import GuildAccess, guild_access
from src.api.discord_client import BAN_MEMBERS, KICK_MEMBERS, MANAGE_GUILD, MODERATE_MEMBERS
from src.api.errors import ApiError
from src.api.pagination import decode_cursor, encode_cursor, limit_param
from src.database.database import db
from src.services import activity_service

router = APIRouter(prefix='/guilds/{guild_id}', tags=['stats'])

MAX_OFFSET = 1000
MAX_SPAN_DAYS = 366


@router.get('/leaderboards')
async def leaderboard(
    category: str = Query('xp', pattern='^(xp|chat|voice|gaming|streaming|coding)$'),
    period: str = Query('alltime', pattern='^(alltime|season|month|week)$'),
    cursor: str | None = None,
    limit: int = Depends(limit_param),
    access: GuildAccess = guild_access(),
) -> dict:
    after = decode_cursor(cursor)
    offset = after.get('offset', 0) if after else 0
    if not isinstance(offset, int) or isinstance(offset, bool) or not 0 <= offset <= MAX_OFFSET:
        raise ApiError(422, 'invalid_cursor', 'Invalid cursor.')
    column = activity_service.LEADERBOARD_CATEGORIES[category]
    rows = await activity_service.leaderboard(column, period, guild_id=access.guild_id, limit=limit + 1, offset=offset)
    items = [
        {'rank': offset + i + 1, 'user_id': r['discord_id'], 'value': int(r['value'])}
        for i, r in enumerate(rows[:limit])
    ]
    more = len(rows) > limit and offset + limit <= MAX_OFFSET
    return {
        'category': category,
        'period': period,
        'scope': 'this_server',
        'items': items,
        'next_cursor': encode_cursor({'offset': offset + limit}) if more else None,
    }


@router.get('/members/{user_id}/activity')
async def member_activity(
    period: str = Query('month', pattern='^(alltime|season|month|week)$'),
    user_id: int = Path(gt=0, lt=2**63),
    access: GuildAccess = guild_access(),
) -> dict:
    """This server's public aggregates for one member (no details, timestamps or streaks)."""
    totals = await activity_service.member_period_totals(user_id, access.guild_id, period)
    return {'user_id': str(user_id), 'period': period, 'totals': totals}


@router.get('/stats/daily')
async def daily_stats(
    start: date | None = Query(None, alias='from'),
    end: date | None = Query(None, alias='to'),
    access: GuildAccess = guild_access(MANAGE_GUILD, MODERATE_MEMBERS, KICK_MEMBERS, BAN_MEMBERS),
) -> dict:
    today = datetime.now(UTC).date()
    end = end or today
    start = start or end - timedelta(days=29)
    if start > end or (end - start).days >= MAX_SPAN_DAYS:
        raise ApiError(422, 'invalid_range', f'Use a range of at most {MAX_SPAN_DAYS} days.')
    server = await db.fetch(
        """SELECT stat_date, total_members, joins, leaves, max_online
           FROM server_stats_daily WHERE guild_id = $1 AND stat_date BETWEEN $2 AND $3""",
        access.guild_id,
        start,
        end,
    )
    activity = await db.fetch(
        """SELECT activity_date, COUNT(DISTINCT user_id) AS active_users, SUM(messages) AS messages,
                  SUM(voice_minutes) AS voice_minutes, SUM(commands) AS commands
           FROM user_activity_daily WHERE guild_id = $1 AND activity_date BETWEEN $2 AND $3
           GROUP BY activity_date""",
        access.guild_id,
        start,
        end,
    )
    by_server = {r['stat_date']: r for r in server}
    by_activity = {r['activity_date']: r for r in activity}
    days = []
    day = start
    while day <= end:
        s, a = by_server.get(day), by_activity.get(day)
        days.append(
            {
                'date': day.isoformat(),
                'members': s['total_members'] if s else None,
                'joins': int(s['joins'] or 0) if s else 0,
                'leaves': int(s['leaves'] or 0) if s else 0,
                'max_online': int(s['max_online'] or 0) if s else 0,
                'active_users': int(a['active_users'] or 0) if a else 0,
                'messages': int(a['messages'] or 0) if a else 0,
                'voice_minutes': int(a['voice_minutes'] or 0) if a else 0,
                'commands': int(a['commands'] or 0) if a else 0,
            }
        )
        day += timedelta(days=1)
    return {'from': start.isoformat(), 'to': end.isoformat(), 'days': days}
