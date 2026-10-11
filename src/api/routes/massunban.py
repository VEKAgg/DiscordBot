"""Mass unban from the dashboard — the same safety as the Discord command.

Flow (state lives in ``massunban_jobs``; NOTIFY only wakes the bot, which also reconciles every 5 min):
1. ``POST /jobs`` → ``requested``. The bot claims it, lists the real bans, matches the filters and
   stores the frozen item set → ``awaiting_confirmation`` (or ``completed`` if nothing matched).
2. ``POST /jobs/{id}/confirm`` (step 1) → returns a single-use token (32 random bytes; only its SHA-256
   is stored), valid 5 minutes, plus the matched count.
3. ``POST /jobs/{id}/confirm`` (step 2) with that token **and** the exact count → ``running``; the bot
   starts the worker. Bans lifted meanwhile become "skipped"; new bans are never added.
Every step requires Ban Members, re-verified with Discord, by the user who requested the job.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from src.api.auth import GuildAccess, guild_access
from src.api.discord_client import BAN_MEMBERS
from src.api.errors import ApiError
from src.api.pagination import cursor_id, decode_cursor, encode_cursor, limit_param
from src.database.database import db

router = APIRouter(prefix='/guilds/{guild_id}/massunban', tags=['massunban'])

ACTIVE_STATUSES = (
    'pending',
    'confirming',
    'requested',
    'previewing',
    'awaiting_confirmation',
    'running',
    'paused',
    'retry_wait',
)
TOKEN_TTL_SECONDS = 300
JobId = Path(gt=0, lt=2**31)
DM_CAP_PER_JOB = 50  # mirrors src/cogs/admin/massunban.py


class JobRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    start: datetime
    end: datetime
    banned_by: str | None = Field(default=None, pattern=r'^[1-9]\d{0,18}$')  # positive BIGINT
    include_unaudited: StrictBool = False
    notify_users: StrictBool = False
    reason: str = Field(default='', max_length=300)


class ConfirmRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    step: StrictInt = Field(ge=1, le=2)
    token: str | None = Field(default=None, max_length=128)
    count: StrictInt | None = Field(default=None, ge=0, le=1_000_000)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _job(row) -> dict:
    meta = row['metadata'] if isinstance(row['metadata'], dict) else json.loads(row['metadata'] or '{}')
    return {
        'id': row['id'],
        'status': row['status'],
        'source': row['source'],
        'requested_by': str(row['requested_by']),
        'start': row['start_datetime'].isoformat(),
        'end': row['end_datetime'].isoformat(),
        'banned_by': str(row['banned_by']) if row['banned_by'] else None,
        'include_unaudited': row['include_unaudited'],
        'notify_users': row['notify_users'],
        'matched': row['total_matched'],
        'attempted': row['total_attempted'],
        'succeeded': row['total_succeeded'],
        'skipped': row['total_skipped'],
        'failed': row['total_failed'],
        'dm_sent': row['dm_sent'],
        'dm_reachable': meta.get('dm_reachable'),
        'total_bans': meta.get('total_bans'),
        'unaudited': meta.get('unaudited'),
        'error': meta.get('error') or meta.get('forbidden'),
        'created_at': row['created_at'].isoformat() if row['created_at'] else None,
        'completed_at': row['completed_at'].isoformat() if row['completed_at'] else None,
    }


_JOB_COLUMNS = """id, status, source, requested_by, start_datetime, end_datetime, banned_by, include_unaudited,
    notify_users, total_matched, total_attempted, total_succeeded, total_skipped, total_failed, dm_sent,
    metadata, created_at, completed_at"""


async def _get_job(guild_id: int, job_id: int):
    row = await db.fetch_one(
        f'SELECT {_JOB_COLUMNS} FROM massunban_jobs WHERE id = $1 AND guild_id = $2', job_id, guild_id
    )
    if row is None:
        raise ApiError(404, 'not_found', 'Job not found.')
    return row


async def _audit(conn, access: GuildAccess, action: str, details: dict) -> None:
    await conn.execute(
        """INSERT INTO audit_logs (user_id, action, details, guild_id, severity)
           VALUES ($1, $2, $3::jsonb, $4, 'warning')""",
        access.principal.audit_actor,
        action,
        json.dumps({'source': 'dashboard', **details}),
        str(access.guild_id),
    )


@router.get('/jobs')
async def list_jobs(
    cursor: str | None = None,
    limit: int = Depends(limit_param),
    access: GuildAccess = guild_access(BAN_MEMBERS),
) -> dict:
    after = decode_cursor(cursor)
    rows = await db.fetch(
        f"""SELECT {_JOB_COLUMNS} FROM massunban_jobs
            WHERE guild_id = $1 AND ($2::int IS NULL OR id < $2)
            ORDER BY id DESC LIMIT $3""",
        access.guild_id,
        cursor_id(after),
        limit + 1,
    )
    return {
        'items': [_job(r) for r in rows[:limit]],
        'next_cursor': encode_cursor({'id': rows[limit - 1]['id']}) if len(rows) > limit else None,
    }


@router.get('/jobs/{job_id}')
async def get_job(job_id: int = JobId, access: GuildAccess = guild_access(BAN_MEMBERS)) -> dict:
    return _job(await _get_job(access.guild_id, job_id))


@router.post('/jobs', status_code=202)
async def request_job(body: JobRequest, access: GuildAccess = guild_access(BAN_MEMBERS, fresh=True)) -> dict:
    from src.api.routes.modules import require_enabled

    start, end = _utc(body.start), _utc(body.end)
    if start >= end:
        raise ApiError(422, 'invalid_range', 'start must be before end.')
    if body.include_unaudited and body.banned_by:
        raise ApiError(422, 'invalid_filters', 'include_unaudited cannot be combined with a moderator filter.')
    actor = access.principal.user_id
    async with db.transaction() as conn:
        await require_enabled(conn, access.guild_id, 'massunban')
        # Serialise job creation per guild, then refuse if one is already in flight.
        await conn.execute(
            'SELECT pg_advisory_xact_lock(hashtextextended($1::text, 0))', f'massunban:{access.guild_id}'
        )
        busy = await conn.fetchval(
            'SELECT id FROM massunban_jobs WHERE guild_id = $1 AND status = ANY($2::text[]) LIMIT 1',
            access.guild_id,
            list(ACTIVE_STATUSES),
        )
        if busy:
            raise ApiError(
                409, 'job_in_progress', 'A mass unban is already in progress in this server.', {'job_id': busy}
            )
        job_id = await conn.fetchval(
            """INSERT INTO massunban_jobs
               (guild_id, requested_by, status, source, start_datetime, end_datetime, banned_by, reason,
                include_unaudited, notify_users)
               VALUES ($1, $2, 'requested', 'dashboard', $3, $4, $5, $6, $7, $8)
               RETURNING id""",
            access.guild_id,
            actor,
            start,
            end,
            int(body.banned_by) if body.banned_by else None,
            body.reason.strip() or None,
            body.include_unaudited,
            body.notify_users,
        )
        await _audit(conn, access, 'dashboard_massunban_requested', {'job_id': job_id})
        await conn.execute("SELECT pg_notify('veka_cache', $1)", f'massunban:{job_id}')
    return _job(await _get_job(access.guild_id, job_id))


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@router.post('/jobs/{job_id}/confirm')
async def confirm_job(
    body: ConfirmRequest, job_id: int = JobId, access: GuildAccess = guild_access(BAN_MEMBERS, fresh=True)
) -> dict:
    job = await _get_job(access.guild_id, job_id)
    if job['requested_by'] != access.principal.user_id:
        raise ApiError(403, 'not_requester', 'Only the person who requested this job can confirm it.')
    if job['status'] != 'awaiting_confirmation':
        raise ApiError(409, 'not_awaiting_confirmation', f'Job is {job["status"]}.', {'status': job['status']})

    if body.step == 1:
        token = secrets.token_urlsafe(32)
        async with db.transaction() as conn:
            updated = await conn.fetchval(
                """UPDATE massunban_jobs
                   SET confirm_token_hash = $3, confirm_step = 1,
                       confirm_expires_at = NOW() + make_interval(secs => $4)
                   WHERE id = $1 AND guild_id = $2 AND status = 'awaiting_confirmation' AND requested_by = $5
                   RETURNING id""",
                job_id,
                access.guild_id,
                _hash(token),
                TOKEN_TTL_SECONDS,
                access.principal.user_id,
            )
            if updated is None:
                raise ApiError(409, 'not_awaiting_confirmation', 'Job changed; reload it.')
            # The token and its hash never go into the audit row.
            await _audit(conn, access, 'dashboard_massunban_confirmed_step1', {'job_id': job_id})
        return {
            'step': 1,
            'token': token,
            'expires_in': TOKEN_TTL_SECONDS,
            'matched': job['total_matched'],
            'notify_users': job['notify_users'],
            'dm_cap': DM_CAP_PER_JOB if job['notify_users'] else 0,
            'message': f'Confirm again with this token and count={job["total_matched"]} to unban those users.',
        }

    if not body.token or body.count is None:
        raise ApiError(422, 'missing_token', 'Step 2 needs the token from step 1 and the exact count.')
    async with db.transaction() as conn:
        # Consumed atomically: right job, guild, step, unexpired token, and the count the user saw.
        started = await conn.fetchval(
            """UPDATE massunban_jobs
               SET status = 'running', started_at = NOW(), confirm_token_hash = NULL, confirm_step = 2,
                   confirm_expires_at = NULL
               WHERE id = $1 AND guild_id = $2 AND status = 'awaiting_confirmation' AND confirm_step = 1
                 AND confirm_token_hash = $3 AND confirm_expires_at > NOW() AND total_matched = $4
                 AND requested_by = $5
               RETURNING id""",
            job_id,
            access.guild_id,
            _hash(body.token),
            body.count,
            access.principal.user_id,
        )
        if started is None:
            raise ApiError(409, 'confirmation_failed', 'Token invalid, expired or already used, or count mismatch.')
        await _audit(conn, access, 'dashboard_massunban_started', {'job_id': job_id, 'matched': body.count})
        await conn.execute("SELECT pg_notify('veka_cache', $1)", f'massunban:{job_id}')
    return _job(await _get_job(access.guild_id, job_id))


@router.post('/jobs/{job_id}/cancel')
async def cancel_job(job_id: int = JobId, access: GuildAccess = guild_access(BAN_MEMBERS, fresh=True)) -> dict:
    await _get_job(access.guild_id, job_id)
    async with db.transaction() as conn:
        cancelled = await conn.fetchval(
            """UPDATE massunban_jobs SET status = 'cancelled', completed_at = NOW(), confirm_token_hash = NULL
               WHERE id = $1 AND guild_id = $2 AND status = ANY($3::text[])
               RETURNING id""",
            job_id,
            access.guild_id,
            list(ACTIVE_STATUSES),
        )
        if cancelled is None:
            raise ApiError(409, 'not_cancellable', 'Job already finished.')
        await _audit(conn, access, 'dashboard_massunban_cancelled', {'job_id': job_id})
        await conn.execute("SELECT pg_notify('veka_cache', $1)", f'massunban:{job_id}')
    return _job(await _get_job(access.guild_id, job_id))
