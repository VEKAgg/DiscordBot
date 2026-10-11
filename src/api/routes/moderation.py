"""Warnings and the moderation audit log (moderators only).

Moderator = Moderate Members, Kick Members or Ban Members in that guild (owner/Administrator imply).
Issuing warnings stays in Discord (the bot DMs and escalates); the dashboard can list and revoke.
The audit log returns typed, redacted entries for a fixed set of moderation/admin actions.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Path, Query

from src.api.auth import GuildAccess, guild_access
from src.api.discord_client import BAN_MEMBERS, KICK_MEMBERS, MODERATE_MEMBERS
from src.api.errors import ApiError
from src.api.pagination import cursor_id, decode_cursor, encode_cursor, limit_param
from src.database.database import db

router = APIRouter(prefix='/guilds/{guild_id}', tags=['moderation'])

_MODERATOR = (MODERATE_MEMBERS, KICK_MEMBERS, BAN_MEMBERS)

AUDIT_ACTIONS = (
    'ban_executed',
    'moderation_warn',
    'moderation_mute',
    'moderation_ban',
    'moderation_kick',
    'honeypot_ban',
    'honeypot_timeout',
    'massunban_started',
    'dashboard_massunban_confirmed_step1',
    'dashboard_massunban_started',
    'guild_setting_changed',
    'dashboard_settings_changed',
    'dashboard_warning_revoked',
    'dashboard_massunban_requested',
    'dashboard_massunban_cancelled',
    'dashboard_honeypot_created',
    'dashboard_honeypot_updated',
    'dashboard_honeypot_deleted',
    'dashboard_honeypot_logging_changed',
    'dashboard_feed_saved',
    'dashboard_feed_updated',
    'dashboard_feed_removed',
)


def _id(value) -> str | None:
    return str(value) if value is not None else None


@router.get('/warnings')
async def list_warnings(
    user_id: str | None = Query(None, pattern=r'^\d{1,20}$'),
    active: bool | None = None,
    cursor: str | None = None,
    limit: int = Depends(limit_param),
    access: GuildAccess = guild_access(*_MODERATOR),
) -> dict:
    after = decode_cursor(cursor)
    rows = await db.fetch(
        """SELECT id, user_id, moderator_id, reason, active, created_at
           FROM warnings
           WHERE guild_id = $1
             AND ($2::bigint IS NULL OR user_id = $2)
             AND ($3::bool IS NULL OR active = $3)
             AND ($4::int IS NULL OR id < $4)
           ORDER BY id DESC
           LIMIT $5""",
        access.guild_id,
        int(user_id) if user_id else None,
        active,
        cursor_id(after),
        limit + 1,
    )
    items = [
        {
            'id': r['id'],
            'user_id': _id(r['user_id']),
            'moderator_id': _id(r['moderator_id']),
            'reason': (r['reason'] or '')[:500],
            'active': bool(r['active']),
            'created_at': r['created_at'].isoformat() if r['created_at'] else None,
        }
        for r in rows[:limit]
    ]
    next_cursor = encode_cursor({'id': rows[limit - 1]['id']}) if len(rows) > limit else None
    return {'items': items, 'next_cursor': next_cursor}


@router.post('/warnings/{warning_id}/revoke')
async def revoke_warning(
    warning_id: int = Path(gt=0, lt=2**31), access: GuildAccess = guild_access(*_MODERATOR, fresh=True)
) -> dict:
    async with db.transaction() as conn:
        # guild_id in the WHERE: a warning ID from another server is "not found" (no IDOR).
        row = await conn.fetchrow(
            """UPDATE warnings SET active = FALSE
               WHERE id = $1 AND guild_id = $2 AND active = TRUE
               RETURNING id, user_id""",
            warning_id,
            access.guild_id,
        )
        if row is None:
            exists = await conn.fetchval(
                'SELECT 1 FROM warnings WHERE id = $1 AND guild_id = $2', warning_id, access.guild_id
            )
            if not exists:
                raise ApiError(404, 'not_found', 'Warning not found.')
            return {'id': warning_id, 'active': False, 'changed': False}
        await conn.execute(
            """INSERT INTO audit_logs (user_id, action, details, guild_id, severity)
               VALUES ($1, 'dashboard_warning_revoked', $2::jsonb, $3, 'info')""",
            access.principal.audit_actor,
            json.dumps({'source': 'dashboard', 'warning_id': warning_id, 'target_user_id': _id(row['user_id'])}),
            str(access.guild_id),
        )
    return {'id': warning_id, 'active': False, 'changed': True}


def _audit_entry(row) -> dict:
    try:
        details = row['details'] if isinstance(row['details'], dict) else json.loads(row['details'] or '{}')
    except (TypeError, ValueError):
        details = {}
    target = details.get('target_user_id') or details.get('user_id')
    summary = details.get('reason') or details.get('field') or ''
    if details.get('job_id') is not None:
        summary = f'job #{details["job_id"]}'
    if row['action'] == 'dashboard_settings_changed':
        summary = ', '.join(sorted((details.get('changes') or {}).keys()))
    return {
        'id': row['id'],
        'action': row['action'],
        'actor_id': row['user_id'] if str(row['user_id']).isdigit() and row['user_id'] != '0' else None,
        'actor_source': details.get('source', 'discord'),
        'target_user_id': str(target) if target else None,
        'summary': str(summary)[:200],
        'created_at': row['created_at'].isoformat() if row['created_at'] else None,
    }


@router.get('/audit-log')
async def audit_log(
    action: str | None = Query(None, max_length=64),
    cursor: str | None = None,
    limit: int = Depends(limit_param),
    access: GuildAccess = guild_access(*_MODERATOR),
) -> dict:
    if action is not None and action not in AUDIT_ACTIONS:
        raise ApiError(422, 'unknown_action', 'Unknown audit action.', details={'allowed': list(AUDIT_ACTIONS)})
    after = decode_cursor(cursor)
    rows = await db.fetch(
        """SELECT id, user_id, action, details, created_at
           FROM audit_logs
           WHERE guild_id = $1
             AND action = ANY($2::text[])
             AND ($3::int IS NULL OR id < $3)
           ORDER BY id DESC
           LIMIT $4""",
        str(access.guild_id),
        [action] if action else list(AUDIT_ACTIONS),
        cursor_id(after),
        limit + 1,
    )
    items = [_audit_entry(r) for r in rows[:limit]]
    next_cursor = encode_cursor({'id': rows[limit - 1]['id']}) if len(rows) > limit else None
    return {'items': items, 'next_cursor': next_cursor}
