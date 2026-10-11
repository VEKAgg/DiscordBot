"""Honeypot traps and their logging config.

Permissions follow what the trap does when it fires (re-checked on every mutation, including the
*current* action when editing or deleting): ban/softban → Ban Members; timeout → Moderate Members;
role → Manage Roles (role must be assignable, below the bot, and carry no privileged permissions);
log only and the logging config → Manage Server. Reads → any moderator. Writes notify the bot
(``honeypots:<gid>``) so its in-memory trap cache reloads.
"""

from __future__ import annotations

import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StringConstraints

from src.api.auth import GuildAccess, guild_access
from src.api.discord_client import (
    ADMINISTRATOR,
    BAN_MEMBERS,
    KICK_MEMBERS,
    MANAGE_CHANNELS,
    MANAGE_GUILD,
    MANAGE_ROLES,
    MODERATE_MEMBERS,
)
from src.api.errors import ApiError
from src.api.pagination import cursor_id, decode_cursor, encode_cursor, limit_param
from src.database.database import db

router = APIRouter(prefix='/guilds/{guild_id}/honeypots', tags=['honeypots'])

Snowflake = Annotated[str, StringConstraints(pattern=r'^[1-9]\d{0,18}$')]  # positive BIGINT
Action = Literal['softban', 'ban', 'timeout', 'role', 'log']
_MODERATOR = (MODERATE_MEMBERS, KICK_MEMBERS, BAN_MEMBERS)
_ACTION_PERMISSION = {
    'softban': BAN_MEMBERS,
    'ban': BAN_MEMBERS,
    'timeout': MODERATE_MEMBERS,
    'role': MANAGE_ROLES,
    'log': MANAGE_GUILD,
}
_PRIVILEGED_ROLE_BITS = (
    ADMINISTRATOR | MANAGE_GUILD | MANAGE_ROLES | MANAGE_CHANNELS | BAN_MEMBERS | KICK_MEMBERS | MODERATE_MEMBERS
)
_COLUMNS = 'id, channel_id, action_type, delete_message_days, timeout_hours, role_id, enabled, created_at, updated_at'


class HoneypotCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

    channel_id: Snowflake
    action_type: Action = 'softban'
    delete_message_days: StrictInt = Field(default=1, ge=0, le=7)
    timeout_hours: StrictInt = Field(default=24, ge=1, le=672)
    role_id: Snowflake | None = None
    enabled: StrictBool = True


class HoneypotPatch(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

    action_type: Action | None = None
    delete_message_days: StrictInt | None = Field(default=None, ge=0, le=7)
    timeout_hours: StrictInt | None = Field(default=None, ge=1, le=672)
    role_id: Snowflake | None = None
    enabled: StrictBool | None = None


class LoggingConfig(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

    logging_channel_id: Snowflake | None = None
    notification_role_id: Snowflake | None = None


def _as_list(value) -> list:
    return json.loads(value) if isinstance(value, str) else list(value or [])


def _sid(value) -> str | None:
    return str(value) if value is not None else None


def _out(row) -> dict:
    return {
        'id': row['id'],
        'channel_id': _sid(row['channel_id']),
        'action_type': row['action_type'],
        'delete_message_days': row['delete_message_days'],
        'timeout_hours': row['timeout_hours'],
        'role_id': _sid(row['role_id']),
        'enabled': row['enabled'],
        'created_at': row['created_at'].isoformat() if row['created_at'] else None,
        'updated_at': row['updated_at'].isoformat() if row['updated_at'] else None,
    }


def _check_text_channel(snapshot: dict, channel_id: str) -> None:
    channel = next((c for c in _as_list(snapshot.get('channels')) if c['id'] == channel_id), None)
    if channel is None:
        raise ApiError(422, 'unknown_channel', f'Channel {channel_id} is not in this server.')
    if channel.get('type') not in ('text', 'news'):
        raise ApiError(422, 'wrong_channel_type', 'Honeypots and logs must be text channels.')


def _check_punitive_role(snapshot: dict, role_id: str) -> None:
    role = next((r for r in _as_list(snapshot.get('roles')) if r['id'] == role_id), None)
    if role is None:
        raise ApiError(422, 'unknown_role', f'Role {role_id} is not in this server.')
    if role.get('managed'):
        raise ApiError(422, 'managed_role', 'Integration-managed roles cannot be assigned by the bot.')
    if int(role.get('permissions') or 0) & _PRIVILEGED_ROLE_BITS:
        raise ApiError(422, 'privileged_role', 'A role with moderation or admin permissions cannot be used here.')
    bot_top = snapshot.get('bot_top_role_position')
    if bot_top is None or int(role.get('position', 0)) >= int(bot_top):
        raise ApiError(422, 'role_above_bot', 'The bot can only assign roles below its own highest role.')


async def _audit_notify(conn, access: GuildAccess, action: str, details: dict) -> None:
    await conn.execute(
        """INSERT INTO audit_logs (user_id, action, details, guild_id, severity)
           VALUES ($1, $2, $3::jsonb, $4, 'info')""",
        access.principal.audit_actor,
        action,
        json.dumps({'source': 'dashboard', **details}),
        str(access.guild_id),
    )
    await conn.execute("SELECT pg_notify('veka_cache', $1)", f'honeypots:{access.guild_id}')


async def _get(guild_id: int, honeypot_id: int):
    row = await db.fetch_one(f'SELECT {_COLUMNS} FROM honeypots WHERE id = $1 AND guild_id = $2', honeypot_id, guild_id)
    if row is None:
        raise ApiError(404, 'not_found', 'Honeypot not found.')
    return row


@router.get('')
async def list_honeypots(access: GuildAccess = guild_access(*_MODERATOR, MANAGE_GUILD, MANAGE_ROLES)) -> dict:
    rows = await db.fetch(f'SELECT {_COLUMNS} FROM honeypots WHERE guild_id = $1 ORDER BY id', access.guild_id)
    return {'items': [_out(r) for r in rows]}


@router.post('', status_code=201)
async def create_honeypot(
    body: HoneypotCreate, access: GuildAccess = guild_access(*_MODERATOR, MANAGE_GUILD, MANAGE_ROLES, fresh=True)
) -> dict:
    access.require(_ACTION_PERMISSION[body.action_type])
    _check_text_channel(access.snapshot, body.channel_id)
    if body.action_type == 'role':
        if not body.role_id:
            raise ApiError(422, 'role_required', 'A role action needs role_id.')
        _check_punitive_role(access.snapshot, body.role_id)
    async with db.transaction() as conn:
        row = await conn.fetchrow(
            f"""INSERT INTO honeypots (guild_id, channel_id, action_type, delete_message_days, timeout_hours, role_id,
                                       enabled, created_by, updated_by)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $8)
                ON CONFLICT (guild_id, channel_id) DO NOTHING
                RETURNING {_COLUMNS}""",
            access.guild_id,
            int(body.channel_id),
            body.action_type,
            body.delete_message_days,
            body.timeout_hours,
            int(body.role_id) if body.role_id and body.action_type == 'role' else None,
            body.enabled,
            access.principal.user_id,
        )
        if row is None:
            raise ApiError(409, 'already_exists', 'That channel already has a honeypot.')
        await _audit_notify(conn, access, 'dashboard_honeypot_created', {'honeypot_id': row['id']})
    return _out(row)


@router.patch('/{honeypot_id}')
async def update_honeypot(
    body: HoneypotPatch,
    honeypot_id: int = Path(gt=0, lt=2**31),
    access: GuildAccess = guild_access(*_MODERATOR, MANAGE_GUILD, MANAGE_ROLES, fresh=True),
) -> dict:
    for field in ('action_type', 'enabled', 'delete_message_days', 'timeout_hours'):
        if field in body.model_fields_set and getattr(body, field) is None:
            raise ApiError(422, 'invalid_value', f'{field} cannot be null.')
    if not body.model_fields_set:
        return _out(await _get(access.guild_id, honeypot_id))
    async with db.transaction() as conn:
        # Authorise against the row as it is now (locked), not a pre-transaction read.
        current = await conn.fetchrow(
            f'SELECT {_COLUMNS} FROM honeypots WHERE id = $1 AND guild_id = $2 FOR UPDATE', honeypot_id, access.guild_id
        )
        if current is None:
            raise ApiError(404, 'not_found', 'Honeypot not found.')
        new_action = body.action_type or current['action_type']
        access.require(_ACTION_PERMISSION[current['action_type']])
        access.require(_ACTION_PERMISSION[new_action])
        # role_id: omitted = keep; null = clear (only valid when the action isn't 'role').
        role_id = _sid(current['role_id']) if 'role_id' not in body.model_fields_set else body.role_id
        if new_action == 'role':
            if not role_id:
                raise ApiError(422, 'role_required', 'A role action needs role_id.')
            _check_punitive_role(access.snapshot, role_id)
        fields = body.model_dump(exclude_unset=True, exclude_none=True)
        fields.pop('role_id', None)
        fields['role_id'] = int(role_id) if new_action == 'role' and role_id else None
        columns = list(fields)  # model fields only — safe to interpolate
        assignments = ', '.join(f'{c} = ${i + 3}' for i, c in enumerate(columns))
        row = await conn.fetchrow(
            f"""UPDATE honeypots SET {assignments}, updated_by = ${len(columns) + 3}, updated_at = NOW()
                WHERE id = $1 AND guild_id = $2 RETURNING {_COLUMNS}""",
            honeypot_id,
            access.guild_id,
            *[fields[c] for c in columns],
            access.principal.user_id,
        )
        await _audit_notify(
            conn, access, 'dashboard_honeypot_updated', {'honeypot_id': honeypot_id, 'fields': sorted(columns)}
        )
    return _out(row)


@router.delete('/{honeypot_id}', status_code=204)
async def delete_honeypot(
    honeypot_id: int = Path(gt=0, lt=2**31),
    access: GuildAccess = guild_access(*_MODERATOR, MANAGE_GUILD, MANAGE_ROLES, fresh=True),
) -> None:
    async with db.transaction() as conn:
        current = await conn.fetchrow(
            'SELECT action_type FROM honeypots WHERE id = $1 AND guild_id = $2 FOR UPDATE', honeypot_id, access.guild_id
        )
        if current is None:
            raise ApiError(404, 'not_found', 'Honeypot not found.')
        access.require(_ACTION_PERMISSION[current['action_type']])
        await conn.execute('DELETE FROM honeypots WHERE id = $1 AND guild_id = $2', honeypot_id, access.guild_id)
        await _audit_notify(conn, access, 'dashboard_honeypot_deleted', {'honeypot_id': honeypot_id})


@router.get('/events')
async def honeypot_events(
    cursor: str | None = None,
    limit: int = Depends(limit_param),
    access: GuildAccess = guild_access(*_MODERATOR),
) -> dict:
    after = decode_cursor(cursor)
    rows = await db.fetch(
        """SELECT id, channel_id, user_id, action_type, action_result,
                  created_at
           FROM honeypot_events
           WHERE guild_id = $1 AND ($2::bigint IS NULL OR id < $2)
           ORDER BY id DESC LIMIT $3""",
        access.guild_id,
        cursor_id(after),
        limit + 1,
    )
    items = [
        {
            'id': r['id'],
            'channel_id': _sid(r['channel_id']),
            'user_id': _sid(r['user_id']),
            'action_type': r['action_type'],
            'result': r['action_result'],
            'created_at': r['created_at'].isoformat() if r['created_at'] else None,
        }
        for r in rows[:limit]
    ]
    return {'items': items, 'next_cursor': encode_cursor({'id': rows[limit - 1]['id']}) if len(rows) > limit else None}


@router.get('/logging')
async def get_logging(access: GuildAccess = guild_access(MANAGE_GUILD)) -> dict:
    row = await db.fetch_one(
        'SELECT logging_channel_id, notification_role_id FROM honeypot_logging_config WHERE guild_id = $1',
        access.guild_id,
    )
    return {
        'logging_channel_id': _sid(row['logging_channel_id']) if row else None,
        'notification_role_id': _sid(row['notification_role_id']) if row else None,
    }


@router.put('/logging')
async def put_logging(body: LoggingConfig, access: GuildAccess = guild_access(MANAGE_GUILD, fresh=True)) -> dict:
    if body.logging_channel_id:
        _check_text_channel(access.snapshot, body.logging_channel_id)
    if body.notification_role_id and not any(
        r['id'] == body.notification_role_id for r in _as_list(access.snapshot.get('roles'))
    ):
        raise ApiError(422, 'unknown_role', 'Role is not in this server.')
    async with db.transaction() as conn:
        await conn.execute(
            """INSERT INTO honeypot_logging_config (guild_id, logging_channel_id, notification_role_id, enabled,
                                                    updated_by, updated_at)
               VALUES ($1, $2, $3, TRUE, $4, NOW())
               ON CONFLICT (guild_id) DO UPDATE SET logging_channel_id = $2, notification_role_id = $3,
                   updated_by = $4, updated_at = NOW()""",
            access.guild_id,
            int(body.logging_channel_id) if body.logging_channel_id else None,
            int(body.notification_role_id) if body.notification_role_id else None,
            access.principal.user_id,
        )
        await _audit_notify(conn, access, 'dashboard_honeypot_logging_changed', {})
    return body.model_dump()
