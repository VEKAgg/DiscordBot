from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.auth import Principal, current_user
from src.api.config import settings
from src.api.discord_client import BAN_MEMBERS, KICK_MEMBERS, MANAGE_GUILD, MODERATE_MEMBERS
from src.database.database import db

router = APIRouter(prefix='/me', tags=['me'])


@router.get('')
async def get_me(principal: Principal = Depends(current_user)) -> dict:
    assert principal.identity is not None
    user = principal.identity.user
    row = await db.fetch_one('SELECT presence_opt_in FROM users WHERE discord_id = $1', str(user.id))
    return {
        'id': str(user.id),
        'username': user.username,
        'global_name': user.global_name,
        'avatar': user.avatar,
        'presence_tracking': row is None or bool(row['presence_opt_in']),  # default allowed; false = opted out
    }


@router.get('/guilds')
async def my_guilds(principal: Principal = Depends(current_user)) -> dict:
    """Manage Server guilds in which the bot has a fresh presence snapshot."""
    assert principal.identity is not None
    candidates = [g for g in principal.identity.guilds.values() if g.has(MANAGE_GUILD)]
    if not candidates:
        return {'items': []}
    rows = await db.fetch(
        """SELECT guild_id, name, icon_url, member_count FROM bot_guild_snapshot
           WHERE guild_id = ANY($1::bigint[]) AND updated_at > NOW() - make_interval(secs => $2)""",
        [g.id for g in candidates],
        settings.snapshot_max_age_seconds,
    )
    present = {r['guild_id']: r for r in rows}
    items = []
    for g in sorted(candidates, key=lambda g: g.name.lower()):
        snap = present.get(g.id)
        if snap is None:
            continue
        items.append(
            {
                'id': str(g.id),
                'name': snap['name'],
                'icon_url': snap['icon_url'],
                'member_count': snap['member_count'],
                'permissions': {
                    'manage': g.has(MANAGE_GUILD),
                    'ban': g.has(BAN_MEMBERS),
                    'moderate': g.has(MODERATE_MEMBERS) or g.has(KICK_MEMBERS) or g.has(BAN_MEMBERS),
                },
            }
        )
    return {'items': items}
