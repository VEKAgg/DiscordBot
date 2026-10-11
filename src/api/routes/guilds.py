from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter

from src.api.auth import GuildAccess, guild_access
from src.api.discord_client import BAN_MEMBERS, KICK_MEMBERS, MANAGE_GUILD, MANAGE_ROLES, MODERATE_MEMBERS
from src.database.database import db
from src.services.module_diagnostics import diagnostics

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
    settings = await db.fetch_one('SELECT * FROM guild_settings WHERE guild_id = $1', access.guild_id)
    modules = await db.fetch_one('SELECT disabled FROM guild_modules WHERE guild_id = $1', access.guild_id)
    usage = await db.fetchval(
        'SELECT COALESCE(SUM(commands), 0) FROM user_activity_daily '
        "WHERE guild_id = $1 AND activity_date >= (NOW() AT TIME ZONE 'UTC')::date - 6",
        access.guild_id,
    )
    heartbeat = status['updated_at'] if status else None
    return {
        'id': str(access.guild_id),
        'name': snap['name'],
        'icon_url': snap['icon_url'],
        'member_count': snap['member_count'],
        'online_count': snap['online_count'],
        'snapshot_updated_at': snap['updated_at'].isoformat(),
        'bot_status': {
            'version': status['version'] if status else None,
            'degraded_features': _json_list(status['degraded_features']) if status else [],
            'online': heartbeat is not None and datetime.now(UTC) - heartbeat < timedelta(minutes=3),
            'latency_ms': status['latency_ms'] if status else None,
            'last_heartbeat_at': heartbeat.isoformat() if heartbeat else None,
            'last_snapshot_at': snap['updated_at'].isoformat(),
            'snapshot_stale': datetime.now(UTC) - snap['updated_at'] >= timedelta(minutes=10),
        },
        'diagnostics': diagnostics(snap, dict(settings or {}), set(modules['disabled'] if modules else [])),
        'command_usage_7d': int(usage or 0),
    }


@router.get('/channels')
async def guild_channels(access: GuildAccess = guild_access(MANAGE_GUILD)) -> dict:
    """Channels for configuration pickers (bot snapshot; IDs are strings). Manage Server only: moderation
    rights don't imply seeing every private channel's name."""
    return {'items': _json_list(access.snapshot['channels'])}


@router.get('/roles')
async def guild_roles(access: GuildAccess = guild_access(MANAGE_GUILD, MANAGE_ROLES)) -> dict:
    return {'items': _json_list(access.snapshot['roles'])}
