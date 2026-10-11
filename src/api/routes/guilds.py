from __future__ import annotations

import json

from fastapi import APIRouter

from src.api.auth import GuildAccess, guild_access
from src.api.discord_client import BAN_MEMBERS, KICK_MEMBERS, MANAGE_GUILD, MANAGE_ROLES, MODERATE_MEMBERS
from src.database.database import db

router = APIRouter(prefix='/guilds/{guild_id}', tags=['guilds'])

_ANY_STAFF = (MANAGE_GUILD, BAN_MEMBERS, KICK_MEMBERS, MODERATE_MEMBERS)


def _json_list(value) -> list:
    if isinstance(value, str):
        return json.loads(value)
    return list(value or [])


@router.get('')
async def guild_overview(access: GuildAccess = guild_access(*_ANY_STAFF)) -> dict:
    snap = access.snapshot
    status = await db.fetch_one(
        'SELECT version, latency_ms, degraded_features, updated_at FROM bot_status WHERE id = 1'
    )
    return {
        'id': str(access.guild_id),
        'name': snap['name'],
        'icon_url': snap['icon_url'],
        'member_count': snap['member_count'],
        'online_count': snap['online_count'],
        'snapshot_updated_at': snap['updated_at'].isoformat(),
        'bot': {
            'version': status['version'] if status else None,
            'latency_ms': status['latency_ms'] if status else None,
            'degraded_features': _json_list(status['degraded_features']) if status else [],
            'updated_at': status['updated_at'].isoformat() if status else None,
        },
    }


@router.get('/channels')
async def guild_channels(access: GuildAccess = guild_access(MANAGE_GUILD)) -> dict:
    """Channels for configuration pickers (bot snapshot; IDs are strings). Manage Server only: moderation
    rights don't imply seeing every private channel's name."""
    return {'items': _json_list(access.snapshot['channels'])}


@router.get('/roles')
async def guild_roles(access: GuildAccess = guild_access(MANAGE_GUILD, MANAGE_ROLES)) -> dict:
    return {'items': _json_list(access.snapshot['roles'])}
