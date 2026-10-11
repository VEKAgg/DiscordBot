"""Versioned, atomic module configuration; reads/config remain available when disabled."""

import json

from fastapi import APIRouter, Header
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from src.api.auth import GuildAccess, guild_access
from src.api.discord_client import MANAGE_GUILD
from src.api.errors import ApiError
from src.database.database import db
from src.services.module_registry import INVITE_PERMISSIONS, REGISTRY, serialize

router = APIRouter(tags=['modules'])


class ModulesPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    modules: dict[str, StrictBool] = Field(min_length=1, max_length=len(REGISTRY))


@router.get('/meta')
async def meta() -> dict:
    return {'invite_permissions': str(INVITE_PERMISSIONS)}


@router.get('/guilds/{guild_id}/modules')
async def get_modules(access: GuildAccess = guild_access(MANAGE_GUILD)) -> dict:
    row = await db.fetch_one('SELECT disabled, version FROM guild_modules WHERE guild_id = $1', access.guild_id)
    return serialize(access.guild_id, row)


@router.patch('/guilds/{guild_id}/modules')
async def patch_modules(
    patch: ModulesPatch,
    if_match: str | None = Header(default=None, alias='If-Match'),
    access: GuildAccess = guild_access(MANAGE_GUILD, fresh=True),
) -> dict:
    if not if_match:
        raise ApiError(428, 'precondition_required', 'Send the modules version as If-Match.')
    for name, enabled in patch.modules.items():
        if name not in REGISTRY:
            raise ApiError(422, 'unknown_module', 'Unknown module.', details={'module': name})
        if REGISTRY[name].locked and not enabled:
            raise ApiError(422, 'module_locked', 'This module cannot be turned off.', details={'module': name})
    async with db.transaction() as conn:
        await conn.execute(
            'INSERT INTO guild_modules (guild_id) VALUES ($1) ON CONFLICT (guild_id) DO NOTHING', access.guild_id
        )
        row = await conn.fetchrow(
            'SELECT disabled, version FROM guild_modules WHERE guild_id = $1 FOR UPDATE', access.guild_id
        )
        if str(row['version']) != if_match.strip('"'):
            raise ApiError(
                412,
                'version_conflict',
                'Modules changed; reload and retry.',
                details={'current': serialize(access.guild_id, row)},
            )
        disabled = set(row['disabled'])
        diff = {}
        for name, enabled in patch.modules.items():
            if enabled != (name not in disabled):
                diff[name] = {'from': name not in disabled, 'to': enabled}
            if enabled:
                disabled.discard(name)
            else:
                disabled.add(name)
        if diff:
            row = await conn.fetchrow(
                'UPDATE guild_modules SET disabled = $2, version = version + 1, updated_by = $3, '
                'updated_at = clock_timestamp() WHERE guild_id = $1 RETURNING disabled, version',
                access.guild_id,
                sorted(disabled),
                int(access.principal.audit_actor),
            )
            await conn.execute(
                'INSERT INTO audit_logs (user_id, action, details, guild_id, severity) '
                "VALUES ($1, 'dashboard_modules_changed', $2::jsonb, $3, 'info')",
                access.principal.audit_actor,
                json.dumps({'source': 'dashboard', 'changes': diff}),
                str(access.guild_id),
            )
            await conn.execute("SELECT pg_notify('veka_cache', $1)", f'modules:{access.guild_id}')
    return serialize(access.guild_id, row)


async def require_enabled(conn, guild_id: int, module: str) -> None:
    # Fence action admission against a concurrent module switch for the whole action transaction.
    await conn.execute('INSERT INTO guild_modules (guild_id) VALUES ($1) ON CONFLICT (guild_id) DO NOTHING', guild_id)
    row = await conn.fetchrow('SELECT disabled FROM guild_modules WHERE guild_id = $1 FOR SHARE', guild_id)
    if row and module in row['disabled']:
        raise ApiError(409, 'module_disabled', 'This feature is turned off in this server.', details={'module': module})
