"""Guild settings read/write for the dashboard.

- Read: Manage Server (or Administrator/owner).
- Write: same permission, re-verified with Discord (no cached identity), optimistic concurrency via
  ``If-Match: <version>``, per-field validation against the bot's guild snapshot and the shared policy,
  an audit row and ``NOTIFY veka_cache 'guild_settings:<gid>'`` — all in one transaction.
"""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Header
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
from src.database.database import db
from src.services.guild_settings_policy import (
    CHANNEL_SETTINGS,
    NUMBER_SETTINGS,
    ROLE_SETTINGS,
    TOGGLE_SETTINGS,
    WELCOME_TEMPLATE_MAX,
    allowed_channel_types,
    settings_schema,
)

router = APIRouter(prefix='/guilds/{guild_id}/settings', tags=['settings'])

_COLUMNS = (
    [col for _, col, _ in CHANNEL_SETTINGS.values()]
    + [col for _, col, _ in ROLE_SETTINGS.values()]
    + [col for _, col, _ in TOGGLE_SETTINGS.values()]
    + list(NUMBER_SETTINGS)
    + ['welcome_message_template']
)


Snowflake = Annotated[str, StringConstraints(pattern=r'^[1-9]\d{0,18}$')]  # positive BIGINT
SettingKey = Annotated[str, StringConstraints(max_length=32)]

# A punitive (muted) role must not carry any of these.
_PRIVILEGED_ROLE_BITS = (
    ADMINISTRATOR | MANAGE_GUILD | MANAGE_ROLES | MANAGE_CHANNELS | BAN_MEMBERS | KICK_MEMBERS | MODERATE_MEMBERS
)


class SettingsPatch(BaseModel):
    """Partial update. Omitted = unchanged. ``null`` on a channel/role clears it; ``null`` template =
    back to the default; numbers and toggles can't be null."""

    model_config = ConfigDict(extra='forbid', strict=True)

    channels: dict[SettingKey, Snowflake | None] = Field(default_factory=dict, max_length=16)
    roles: dict[SettingKey, Snowflake | None] = Field(default_factory=dict, max_length=8)
    toggles: dict[SettingKey, StrictBool] = Field(default_factory=dict, max_length=8)
    warn_mute_threshold: StrictInt | None = None
    warn_ban_threshold: StrictInt | None = None
    honeypot_cooldown_seconds: StrictInt | None = None
    welcome_message_template: str | None = Field(default=None, max_length=WELCOME_TEMPLATE_MAX)


def _version(updated_at) -> str:
    return str(int(updated_at.timestamp() * 1_000_000)) if updated_at else '0'


def _as_list(value) -> list:
    return json.loads(value) if isinstance(value, str) else list(value or [])


def _serialize(row: dict) -> dict[str, Any]:
    def sid(value):
        return str(value) if value is not None else None

    return {
        'channels': {key: sid(row.get(col)) for key, (_, col, _) in CHANNEL_SETTINGS.items()},
        'roles': {key: sid(row.get(col)) for key, (_, col, _) in ROLE_SETTINGS.items()},
        'toggles': {key: bool(row.get(col)) for key, (_, col, _) in TOGGLE_SETTINGS.items()},
        'warn_mute_threshold': row.get('warn_mute_threshold') or 3,
        'warn_ban_threshold': row.get('warn_ban_threshold') or 5,
        'honeypot_cooldown_seconds': row.get('honeypot_cooldown_seconds')
        if row.get('honeypot_cooldown_seconds') is not None
        else 60,
        'welcome_message_template': row.get('welcome_message_template') or 'Welcome {user} to {server}!',
        'version': _version(row.get('updated_at')),
        'schema': settings_schema(),
    }


async def _load(guild_id: int) -> dict:
    await db.execute('INSERT INTO guild_settings (guild_id) VALUES ($1) ON CONFLICT (guild_id) DO NOTHING', guild_id)
    row = await db.fetch_one(
        f'SELECT {", ".join(_COLUMNS)}, updated_at FROM guild_settings WHERE guild_id = $1', guild_id
    )
    return dict(row) if row else {}


@router.get('')
async def get_settings(access: GuildAccess = guild_access(MANAGE_GUILD)) -> dict:
    return _serialize(await _load(access.guild_id))


def _snowflake(value: str, what: str) -> int:
    if not value.isdigit() or not (0 < int(value) < 2**63):
        raise ApiError(422, 'invalid_id', f'{what} must be a Discord ID (decimal string).')
    return int(value)


def _validate(patch: SettingsPatch, snapshot: dict, access: GuildAccess) -> dict[str, Any]:
    """Turn a patch into column → value, validating against the bot's view of the guild."""
    channels = {c['id']: c for c in _as_list(snapshot.get('channels'))}
    roles = {r['id']: r for r in _as_list(snapshot.get('roles'))}
    changes: dict[str, Any] = {}

    for key, value in patch.channels.items():
        if key not in CHANNEL_SETTINGS:
            raise ApiError(422, 'unknown_setting', f'Unknown channel setting: {key}')
        column = CHANNEL_SETTINGS[key][1]
        if value is None:
            changes[column] = None
            continue
        _snowflake(value, 'Channel')
        channel = channels.get(value)
        if channel is None:
            raise ApiError(422, 'unknown_channel', f'Channel {value} is not in this server.')
        if channel.get('type') not in allowed_channel_types(key):
            allowed = ', '.join(allowed_channel_types(key))
            raise ApiError(422, 'wrong_channel_type', f'{CHANNEL_SETTINGS[key][0]} must be one of: {allowed}.')
        changes[column] = int(value)

    if patch.roles:
        access.require(MANAGE_ROLES)  # assigning roles (e.g. auto-mute) is a Manage Roles decision
    for key, value in patch.roles.items():
        if key not in ROLE_SETTINGS:
            raise ApiError(422, 'unknown_setting', f'Unknown role setting: {key}')
        column = ROLE_SETTINGS[key][1]
        if value is None:
            changes[column] = None
            continue
        _snowflake(value, 'Role')
        role = roles.get(value)
        if role is None:
            raise ApiError(422, 'unknown_role', f'Role {value} is not in this server.')
        if role.get('managed'):
            raise ApiError(422, 'managed_role', 'Integration-managed roles cannot be assigned by the bot.')
        if int(role.get('permissions') or 0) & _PRIVILEGED_ROLE_BITS:
            raise ApiError(422, 'privileged_role', 'A role with moderation or admin permissions cannot be used here.')
        bot_top = snapshot.get('bot_top_role_position')
        if bot_top is None or int(role.get('position', 0)) >= int(bot_top):
            raise ApiError(422, 'role_above_bot', 'The bot can only assign roles below its own highest role.')
        changes[column] = int(value)

    for key, enabled in patch.toggles.items():
        if key not in TOGGLE_SETTINGS:
            raise ApiError(422, 'unknown_setting', f'Unknown option: {key}')
        changes[TOGGLE_SETTINGS[key][1]] = bool(enabled)

    for column, (low, high) in NUMBER_SETTINGS.items():
        value = getattr(patch, column)
        if value is None:
            if column in patch.model_fields_set:
                raise ApiError(422, 'invalid_value', f'{column} cannot be null.')
            continue
        if not low <= value <= high:
            raise ApiError(422, 'out_of_range', f'{column} must be between {low} and {high}.')
        changes[column] = value

    if 'welcome_message_template' in patch.model_fields_set:
        template = patch.welcome_message_template
        changes['welcome_message_template'] = (template or '').strip() or None  # null/empty → default
    return changes


@router.patch('')
async def patch_settings(
    patch: SettingsPatch,
    if_match: str | None = Header(default=None, alias='If-Match'),
    access: GuildAccess = guild_access(MANAGE_GUILD, fresh=True),
) -> dict:
    if not if_match:
        raise ApiError(428, 'precondition_required', 'Send the settings version as If-Match.')
    changes = _validate(patch, access.snapshot, access)
    if not changes:
        current = await _load(access.guild_id)
        if _version(current.get('updated_at')) != if_match.strip('"'):
            raise ApiError(412, 'version_conflict', 'Settings changed since you loaded them; reload and retry.')
        return _serialize(current)

    await db.execute(
        'INSERT INTO guild_settings (guild_id) VALUES ($1) ON CONFLICT (guild_id) DO NOTHING', access.guild_id
    )
    async with db.transaction() as conn:
        current = await conn.fetchrow(
            f'SELECT {", ".join(_COLUMNS)}, updated_at FROM guild_settings WHERE guild_id = $1 FOR UPDATE',
            access.guild_id,
        )
        current = dict(current) if current else {}
        if _version(current.get('updated_at')) != if_match.strip('"'):
            raise ApiError(
                412,
                'version_conflict',
                'Settings changed since you loaded them; reload and retry.',
                details={'current': _serialize(current)},
            )
        mute = int(changes.get('warn_mute_threshold') or current.get('warn_mute_threshold') or 3)
        ban = int(changes.get('warn_ban_threshold') or current.get('warn_ban_threshold') or 5)
        if ban < mute:
            raise ApiError(422, 'out_of_range', 'warn_ban_threshold must be at least warn_mute_threshold.')

        columns = list(changes)  # validated against the policy above, safe to interpolate
        assignments = ', '.join(f'{col} = ${i + 2}' for i, col in enumerate(columns))
        row = await conn.fetchrow(
            f'UPDATE guild_settings SET {assignments}, updated_at = clock_timestamp() WHERE guild_id = $1 '
            f'RETURNING {", ".join(_COLUMNS)}, updated_at',
            access.guild_id,
            *[changes[c] for c in columns],
        )
        diff = {
            col: {'from': _jsonable(current.get(col)), 'to': _jsonable(changes[col])}
            for col in columns
            if current.get(col) != changes[col]
        }
        await conn.execute(
            """INSERT INTO audit_logs (user_id, action, details, guild_id, severity)
               VALUES ($1, 'dashboard_settings_changed', $2::jsonb, $3, 'info')""",
            access.principal.audit_actor,
            json.dumps({'source': 'dashboard', 'changes': diff}),
            str(access.guild_id),
        )
        await conn.execute("SELECT pg_notify('veka_cache', $1)", f'guild_settings:{access.guild_id}')
    return _serialize(dict(row) if row else {})


def _jsonable(value):
    if isinstance(value, int) and value > 2**53:
        return str(value)
    if isinstance(value, str):
        return value[:200]
    return value
