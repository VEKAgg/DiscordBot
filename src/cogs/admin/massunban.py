"""
Mass Unban Cog — Resumable bulk-unban with double confirmation and per-user audit.

Provides /massunban and !massunban commands for admin-only bulk unban operations
with date-range and moderator filters, persistent job tracking and rate-limit handling.

Outbound safety (the bot was quarantined during a mass unban): apology DMs are OFF unless the job
sets ``notify_users``, and then capped, spaced, limited to users who still share a server with the
bot, and stopped after repeated failures. Progress is one edited message in the log channel plus a
single summary — never a message per user or per event.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import nextcord
from nextcord.ext import commands, tasks

from src.config.config import MASSUNBAN_LOG_CHANNEL_ID, OWNER_IDS
from src.core.lifecycle import spawn
from src.core.runtime_state import runtime_state
from src.database.database import db
from src.services.guild_settings_service import guild_settings_service
from src.utils.embeds import error_embed, info_embed, success_embed, veka_embed
from src.utils.outbound import SendStatus, outbound
from src.utils.safety import DatabaseUnavailableError, admin_only, safe_command, safe_send, safe_slash_command
from src.utils.security import audit_log

logger = logging.getLogger('VEKA.admin.massunban')


async def _safe_send_view(
    target: commands.Context | nextcord.Interaction,
    embed: nextcord.Embed,
    view: nextcord.ui.View,
    *,
    ephemeral: bool = False,
) -> bool:
    """Send an embed with a view, handling both Context and Interaction. Returns True on success."""
    try:
        if isinstance(target, commands.Context):
            await target.send(embed=embed, view=view)
            return True
        elif isinstance(target, nextcord.Interaction):
            if target.response.is_done():
                await target.followup.send(embed=embed, view=view, ephemeral=ephemeral)
            else:
                await target.response.send_message(embed=embed, view=view, ephemeral=ephemeral)
            return True
        return False
    except Exception as exc:
        logger.error('_safe_send_view failed: %s', exc, exc_info=True)
        return False


# --- Rate limiting constants ---
BASE_UNBAN_INTERVAL = 1.5  # seconds between unbans
MAX_BACKOFF_MULTIPLIER = 8  # progressive slowdown cap
RATE_LIMIT_COOLDOWN = 60  # default seconds on 429 without retry_after
PAUSE_THRESHOLD = 3  # consecutive 429s before progressive slowdown

# --- Apology DMs (opt-in per job; see AGENTS.md "Mass unban") ---
DM_CAP_PER_JOB = 50  # never DM more users than this in one job
DM_MIN_INTERVAL = 5.0  # seconds between apology DMs
DM_MAX_CONSECUTIVE_FAILURES = 5  # stop DMing for the rest of the job after this many failures in a row
PROGRESS_EDIT_INTERVAL = 20.0  # seconds between edits of the job's progress message


# Discord JSON error code for "Two factor is required for this operation".
MFA_REQUIRED_CODE = 60003


def _forbidden_result(result: dict[str, Any], exc: nextcord.Forbidden) -> dict[str, Any]:
    """Mark an unban result as a job-stopping 403; the item itself stays pending."""
    if exc.code == MFA_REQUIRED_CODE:
        reason = (
            "The server requires 2FA for moderator actions, and the bot owner's Discord account "
            'does not have 2FA enabled (error 60003). Enable 2FA on the account that owns the bot application.'
        )
    else:
        reason = f'Missing permission to unban (Ban Members or role hierarchy): {exc}'
    result['status'] = 'pending'
    result['failure_reason'] = reason
    result['forbidden'] = True
    return result


def _format_dt(dt: datetime | None, style: str = 'f') -> str:
    """Format a datetime as a Discord timestamp."""
    if dt is None:
        return 'N/A'
    return f'<t:{int(dt.timestamp())}:{style}>'


def _format_dt_short(dt: datetime | None) -> str:
    if dt is None:
        return 'N/A'
    return f'<t:{int(dt.timestamp())}:f>'


# ============================================================
# Confirmation Views
# ============================================================


class ConfirmFirstView(nextcord.ui.View):
    """First confirmation — shows preview, requires explicit click."""

    def __init__(self, job_id: int, runner_id: int, timeout: float = 120):
        super().__init__(timeout=timeout)
        self.job_id = job_id
        self.runner_id = runner_id
        self.result: bool | None = None

    async def interaction_check(self, interaction: nextcord.Interaction) -> bool:
        if interaction.user.id != self.runner_id:
            await interaction.response.send_message('Only the command runner can confirm.', ephemeral=True)
            return False
        return True

    @nextcord.ui.button(label='Confirm', style=nextcord.ButtonStyle.green, emoji='\u2705')
    async def confirm_button(self, _button: nextcord.ui.Button, interaction: nextcord.Interaction):
        self.result = True
        self.stop()
        await interaction.response.defer()

    @nextcord.ui.button(label='Cancel', style=nextcord.ButtonStyle.red, emoji='\u274c')
    async def cancel_button(self, _button: nextcord.ui.Button, interaction: nextcord.Interaction):
        self.result = False
        self.stop()
        await interaction.response.defer()

    async def on_timeout(self):
        self.result = None
        self.stop()


class ConfirmSecondView(nextcord.ui.View):
    """Second confirmation — final "are you sure" with count displayed."""

    def __init__(self, job_id: int, runner_id: int, count: int, timeout: float = 120):
        super().__init__(timeout=timeout)
        self.job_id = job_id
        self.runner_id = runner_id
        self.count = count
        self.result: bool | None = None

    async def interaction_check(self, interaction: nextcord.Interaction) -> bool:
        if interaction.user.id != self.runner_id:
            await interaction.response.send_message('Only the command runner can confirm.', ephemeral=True)
            return False
        return True

    @nextcord.ui.button(label='Confirm Unban', style=nextcord.ButtonStyle.green, emoji='\u26a1')
    async def confirm_button(self, _button: nextcord.ui.Button, interaction: nextcord.Interaction):
        self.result = True
        self.stop()
        await interaction.response.defer()

    @nextcord.ui.button(label='Cancel', style=nextcord.ButtonStyle.red, emoji='\u274c')
    async def cancel_button(self, _button: nextcord.ui.Button, interaction: nextcord.Interaction):
        self.result = False
        self.stop()
        await interaction.response.defer()

    async def on_timeout(self):
        self.result = None
        self.stop()


# ============================================================
# DM Apology Template
# ============================================================

DM_APOLOGY_TEMPLATE = """\
You have been unbanned from **{guild_name}**.

We apologize for any inconvenience. If you believe this was a mistake or would like to discuss further, please contact our staff team.

Thank you for your understanding."""


# ============================================================
# Main Cog
# ============================================================


def match_bans(
    bans: list,
    audit_records: dict[str, dict],
    start_dt: datetime,
    end_dt: datetime,
    banned_by_id: int | None,
    include_unaudited: bool,
) -> tuple[list[tuple[Any, dict | None]], int]:
    """Select the bans a job should lift. Returns (matched [(ban, audit_record)], unaudited_count).

    Discord's ban list has no timestamp or moderator, so only bans the bot recorded in audit_logs
    can be matched against the date range / moderator. Unaudited bans are EXCLUDED unless
    ``include_unaudited`` is set explicitly (and never with a moderator filter) — previously they
    were always included, so a "date-ranged" run unbanned essentially everyone (audit H-02).
    """
    matched: list[tuple[Any, dict | None]] = []
    unaudited = 0
    for ban in bans:
        record = audit_records.get(str(ban.user.id))
        if record is None:
            unaudited += 1
            if include_unaudited and banned_by_id is None:
                matched.append((ban, None))
            continue
        ban_time = record.get('created_at')
        if ban_time is not None:
            if ban_time.tzinfo is None:
                ban_time = ban_time.replace(tzinfo=UTC)
            if ban_time < start_dt or ban_time > end_dt:
                continue
        if banned_by_id is not None and record.get('moderator_id') != str(banned_by_id):
            continue
        matched.append((ban, record))
    return matched, unaudited


_AUDIT_LIMITATION = (
    "Discord's API does not store ban timestamps or the moderator who placed the ban. "
    "Date and moderator filters only match bans logged in the bot's audit database "
    'while the bot was active. Bans placed externally or before the bot was running '
    'cannot be filtered by date or moderator.'
)


# Any of these means "a job is in flight" — at most one per guild, enforced under one advisory lock
# shared by the Discord command and the dashboard API (src/api/routes/massunban.py).
ACTIVE_JOB_STATUSES = (
    'pending',
    'confirming',
    'requested',
    'previewing',
    'awaiting_confirmation',
    'running',
    'paused',
    'retry_wait',
)


class _JobInProgress(Exception):
    pass


def _pop_flag(text: str, flag: str) -> tuple[bool, str]:
    """Remove a ``--flag`` token from free text (prefix commands). Returns (present, remaining text)."""
    tokens = (text or '').split()
    present = flag in tokens
    return present, ' '.join(t for t in tokens if t != flag)


def _summary_text(job: dict) -> str:
    """Counters for the progress message and the final summary."""
    duration = ''
    if job.get('started_at'):
        end = job.get('completed_at') or datetime.now(UTC)
        mins, secs = divmod(int((end - job['started_at']).total_seconds()), 60)
        duration = f'**Duration:** {mins}m {secs}s\n' if mins else f'**Duration:** {secs}s\n'
    lines = (
        f'**Processed:** {job.get("total_attempted") or 0} / {job.get("total_matched") or 0}\n'
        f'\u2705 **Unbanned:** {job.get("total_succeeded") or 0}\n'
        f'\u23ed\ufe0f **Skipped (already unbanned):** {job.get("total_skipped") or 0}\n'
        f'\u274c **Failed:** {job.get("total_failed") or 0}\n'
        f'{duration}'
        f'**Rate limits hit:** {job.get("rate_limit_hits") or 0}'
    )
    if job.get('notify_users'):
        lines += f'\n**Apology DMs:** {job.get("dm_sent") or 0} sent, {job.get("dm_failed") or 0} failed'
    return lines


def _dm_summary(notify_users: bool, matched: list, guild_id: int, cog: MassUnban) -> str:
    if not notify_users:
        return 'Off (default). Add `notify_users:true` / `--notify` to DM users who still share a server with the bot.'
    reachable = cog._dm_reachable([ban.user.id for ban, _ in matched], guild_id)
    return (
        f'On — {min(DM_CAP_PER_JOB, reachable)} of {len(matched)} users can be DMed '
        f'(only users who still share a server with the bot, max {DM_CAP_PER_JOB} per job).'
    )


class MassUnban(commands.Cog):
    """Resumable bulk-unban with double confirmation, rate limiting, and per-user audit."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._active_jobs: dict[int, bool] = {}  # job_id -> cancelled flag
        self._rate_limit_count: dict[int, int] = {}  # job_id -> consecutive 429 count
        self._unban_interval: dict[int, float] = {}  # job_id -> current interval
        self._job_locks: dict[int, asyncio.Lock] = {}  # job_id -> lock (one worker per job, audit H-03)
        self._dm_state: dict[int, dict[str, Any]] = {}  # job_id -> {'failures_in_row', 'last_dm', 'disabled'}
        self._last_progress: dict[int, float] = {}  # job_id -> monotonic time of the last progress edit
        self._workers: set[asyncio.Task] = set()
        self._unloaded = False

    def cog_unload(self):
        self._unloaded = True
        self.dashboard_reconcile.cancel()
        for task in tuple(self._workers):
            task.cancel()

    @tasks.loop(minutes=5)
    async def dashboard_reconcile(self) -> None:
        """Safety net: NOTIFY from the API is only a hint, so pick up dashboard jobs periodically too."""
        try:
            await self.process_dashboard_jobs()
        except Exception:
            logger.warning('Dashboard mass-unban reconcile failed', exc_info=True)

    @dashboard_reconcile.before_loop
    async def before_dashboard_reconcile(self) -> None:
        await self.bot.wait_until_ready()

    def _spawn_worker(self, coro, *, name: str):
        task = spawn(coro, name=name)
        self._workers.add(task)
        task.add_done_callback(self._workers.discard)
        return task

    def _forget_job(self, job_id: int) -> None:
        for state in (self._active_jobs, self._rate_limit_count, self._unban_interval, self._dm_state):
            state.pop(job_id, None)
        self._last_progress.pop(job_id, None)
        outbound.forget_status(f'massunban:{job_id}')

    @commands.Cog.listener()
    async def on_member_ban(self, guild: nextcord.Guild, user: nextcord.User | nextcord.Member) -> None:
        """Record every ban in audit_logs so date/moderator filters have data to match (audit H-02)."""
        if not runtime_state.db_available:
            return
        moderator_id: int | None = None
        reason: str | None = None
        me = guild.me
        if me is not None and me.guild_permissions.view_audit_log:
            try:
                async for entry in guild.audit_logs(limit=5, action=nextcord.AuditLogAction.ban):
                    if entry.target is not None and entry.target.id == user.id:
                        moderator_id = entry.user.id if entry.user else None
                        reason = entry.reason
                        break
            except (nextcord.Forbidden, nextcord.HTTPException):
                pass
        try:
            await audit_log.record(
                user_id=str(moderator_id or 0),
                action='ban_executed',
                details={
                    'target_user_id': str(user.id),
                    'moderator_id': str(moderator_id) if moderator_id else None,
                    'reason': (reason or '')[:200],
                },
                guild_id=str(guild.id),
                severity='warning',
            )
        except Exception:
            logger.warning('Failed to record ban of %s in %s', user.id, guild.id, exc_info=True)

    async def cog_ready(self) -> None:
        """Resume incomplete jobs on startup (called from on_ready via run_cog_ready_hooks)."""
        await self._resume_incomplete_jobs()
        if not self.dashboard_reconcile.is_running():
            self.dashboard_reconcile.start()

    async def _resume_incomplete_jobs(self) -> None:
        """Resume running/paused jobs and cancel ones interrupted during confirmation. No DMs are sent:
        the job's progress message in the log channel shows the resume."""
        await self.bot.wait_until_ready()
        if not runtime_state.db_available:
            # Raise so run_cog_ready_hooks retries once the DB health check sees the database again.
            raise DatabaseUnavailableError('DB unavailable — mass unban resume deferred')
        failed = False
        jobs = await db.fetch("""SELECT id FROM massunban_jobs WHERE status IN ('running', 'retry_wait', 'paused')""")
        for job in jobs:
            if job['id'] in self._active_jobs:
                continue  # already resumed by an earlier (partially failed) attempt
            try:
                logger.info('Resuming mass unban job %s', job['id'])
                await db.execute("UPDATE massunban_jobs SET status = 'running' WHERE id = $1", job['id'])
                self._active_jobs[job['id']] = False
                self._spawn_worker(self._execute_job(job['id'], resumed=True), name=f'massunban:{job["id"]}')
            except Exception:
                failed = True
                logger.error('Failed to resume job %s', job['id'], exc_info=True)

        # Jobs interrupted while waiting for confirmation are cancelled; the runner sees it in /massunban recent.
        try:
            await db.execute(
                """UPDATE massunban_jobs SET status = 'cancelled', completed_at = NOW(),
                       metadata = COALESCE(metadata, '{}'::jsonb) || '{"cancelled_by_restart": true}'::jsonb
                   WHERE status IN ('pending', 'confirming')
                      OR (status IN ('requested', 'previewing', 'awaiting_confirmation')
                          AND created_at < NOW() - INTERVAL '1 hour')"""
            )
        except Exception:
            failed = True
            logger.error('Failed to cancel orphaned mass unban jobs', exc_info=True)
        if failed:
            raise RuntimeError('Some mass unban jobs could not be recovered; retry required')

    # ============================================================
    # Dashboard-started jobs (see API-DESIGN / src/api)
    # ============================================================

    async def process_dashboard_jobs(self) -> None:
        """Handle every dashboard job waiting for the bot (called after the cache listener reconnects)."""
        if not runtime_state.db_available:
            return
        # Abandoned dashboard confirmations would block the guild (one job at a time): expire them.
        await db.execute(
            """UPDATE massunban_jobs SET status = 'cancelled', completed_at = NOW(), confirm_token_hash = NULL,
                   metadata = COALESCE(metadata, '{}'::jsonb) || '{"expired": true}'::jsonb
               WHERE source = 'dashboard' AND status IN ('requested', 'awaiting_confirmation')
                 AND created_at < NOW() - INTERVAL '1 hour'"""
        )
        # A preview interrupted by a crash/restart goes back to the queue.
        await db.execute(
            """UPDATE massunban_jobs SET status = 'requested', claimed_at = NULL
               WHERE source = 'dashboard' AND status = 'previewing' AND claimed_at < NOW() - INTERVAL '10 minutes'"""
        )
        rows = await db.fetch(
            """SELECT id FROM massunban_jobs
               WHERE source = 'dashboard' AND status IN ('requested', 'running', 'cancelled')
                 AND (completed_at IS NULL OR completed_at > NOW() - INTERVAL '1 hour')"""
        )
        for row in rows:
            await self.handle_dashboard_job(row['id'])

    async def handle_dashboard_job(self, job_id: int) -> None:
        """'requested' → list bans, match the job's filters, store items → 'awaiting_confirmation'.
        'running' (confirmed twice through the API) → start the worker if it isn't running."""
        job = await db.fetch_one('SELECT * FROM massunban_jobs WHERE id = $1', job_id)
        if not job:
            return
        if job['status'] == 'cancelled':
            # Any job (Discord- or dashboard-started) cancelled from the dashboard: stop the worker.
            if job_id in self._active_jobs:
                self._active_jobs[job_id] = True  # the running worker stops at its next item
            return
        if job['source'] != 'dashboard':
            return
        guild = self.bot.get_guild(job['guild_id'])
        if guild is None:
            await self._set_status(job_id, 'failed')
            return
        if job['status'] == 'running':
            if job_id not in self._active_jobs:
                self._active_jobs[job_id] = False
                self._rate_limit_count[job_id] = 0
                self._unban_interval[job_id] = BASE_UNBAN_INTERVAL
                self._spawn_worker(self._execute_job(job_id, resumed=False), name=f'massunban:{job_id}')
            return
        if job['status'] != 'requested':
            return
        # Claim it (compare-and-set) so two listeners/reconciles never preview the same job twice.
        # The claim timestamp is a fencing token: a handler whose claim was requeued can't commit.
        claim = await db.fetchval(
            """UPDATE massunban_jobs SET status = 'previewing', claimed_at = clock_timestamp()
               WHERE id = $1 AND status = 'requested' RETURNING claimed_at""",
            job_id,
        )
        if claim is None:
            return
        try:
            bans = [ban async for ban in guild.bans(limit=None)]
        except (nextcord.Forbidden, nextcord.HTTPException):
            await db.execute(
                """UPDATE massunban_jobs SET status = 'failed', completed_at = NOW(),
                       metadata = COALESCE(metadata, '{}'::jsonb) || '{"error": "cannot_list_bans"}'::jsonb
                   WHERE id = $1 AND status = 'previewing' AND claimed_at = $2""",
                job_id,
                claim,
            )
            return
        audit_records = await self._fetch_audit_records(guild.id)
        matched, no_audit = match_bans(
            bans, audit_records, job['start_datetime'], job['end_datetime'], job['banned_by'], job['include_unaudited']
        )
        reachable = self._dm_reachable([ban.user.id for ban, _ in matched], guild.id) if job['notify_users'] else 0
        async with db.transaction() as conn:
            # Items and the status move together; if the job was cancelled meanwhile nothing is kept.
            still_ours = await conn.fetchval(
                """SELECT 1 FROM massunban_jobs
                   WHERE id = $1 AND status = 'previewing' AND claimed_at = $2 FOR UPDATE""",
                job_id,
                claim,
            )
            if not still_ours:
                return
            await self._store_preview(conn, job_id, matched, len(bans), no_audit, min(DM_CAP_PER_JOB, reachable))

    @staticmethod
    async def _store_preview(conn, job_id: int, matched: list, total_bans: int, no_audit: int, dm_reachable: int):
        await conn.executemany(
            """INSERT INTO massunban_job_items
               (job_id, target_user_id, target_username, ban_reason, banned_by, dm_status)
               VALUES ($1, $2, $3, $4, $5, 'skipped')""",
            [
                (
                    job_id,
                    str(ban.user.id),
                    str(ban.user)[:100],
                    (ban.reason or '')[:500] or None,
                    int(record['moderator_id']) if record and record.get('moderator_id') else None,
                )
                for ban, record in matched
            ],
        )
        await conn.execute(
            """UPDATE massunban_jobs
               SET status = CASE WHEN $2 > 0 THEN 'awaiting_confirmation' ELSE 'completed' END,
                   total_matched = $2,
                   completed_at = CASE WHEN $2 > 0 THEN NULL ELSE NOW() END,
                   metadata = COALESCE(metadata, '{}'::jsonb)
                       || jsonb_build_object('total_bans', $3::int, 'unaudited', $4::int, 'dm_reachable', $5::int)
               WHERE id = $1 AND status = 'previewing'""",
            job_id,
            len(matched),
            total_bans,
            no_audit,
            dm_reachable,
        )

    # ============================================================
    # Slash Commands
    # ============================================================

    @nextcord.slash_command(
        name='massunban',
        description='Bulk unban users with date-range filters',
        contexts=[nextcord.InteractionContextType.guild],
        default_member_permissions=nextcord.Permissions(ban_members=True),
    )
    async def massunban_group(self, interaction: nextcord.Interaction) -> None:
        embed = await info_embed(
            title='Mass Unban Commands',
            description=(
                '**Available subcommands:**\n\n'
                '• `/massunban run` — Start a mass unban\n'
                '• `/massunban preview` — Preview matching bans without executing\n'
                '• `/massunban status` — Check job status\n'
                '• `/massunban cancel` — Cancel a job\n'
                '• `/massunban recent` — View recent jobs'
            ),
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        await safe_send(interaction, embed=embed, ephemeral=True)

    @massunban_group.subcommand(
        name='run',
        description='Start a mass unban with date-range and optional moderator filter',
    )
    @admin_only()
    @safe_slash_command(requires_db=True)
    async def massunban_run_slash(
        self,
        interaction: nextcord.Interaction,
        start_datetime: str = nextcord.SlashOption(
            description='Start of ban date range (ISO format, e.g. 2024-01-01 or 2024-01-01T00:00:00)',
            required=True,
        ),
        end_datetime: str = nextcord.SlashOption(
            description='End of ban date range (ISO format, e.g. 2024-12-31)',
            required=True,
        ),
        banned_by: nextcord.Member | None = nextcord.SlashOption(
            description='Only unbans placed by this moderator (limited audit history)',
            required=False,
        ),
        reason: str = nextcord.SlashOption(
            description='Reason for audit log',
            required=False,
            default='',
        ),
        include_unaudited: bool = nextcord.SlashOption(
            description='Also unban bans with no recorded date/moderator (ignores the date range for them)',
            required=False,
            default=False,
        ),
        notify_users: bool = nextcord.SlashOption(
            description=f'DM an apology to unbanned users who share a server with the bot (max {DM_CAP_PER_JOB})',
            required=False,
            default=False,
        ),
    ) -> None:
        await self._start_massunban(
            interaction, start_datetime, end_datetime, banned_by, reason, include_unaudited, notify_users
        )

    @massunban_group.subcommand(name='status', description='Check status of a mass unban job')
    @admin_only()
    @safe_slash_command(requires_db=True)
    async def massunban_status_slash(
        self,
        interaction: nextcord.Interaction,
        job_id: int = nextcord.SlashOption(description='Job ID to check', required=True),
    ) -> None:
        await self._show_status(interaction, job_id)

    @massunban_group.subcommand(name='cancel', description='Cancel a pending or running mass unban job')
    @admin_only()
    @safe_slash_command(requires_db=True)
    async def massunban_cancel_slash(
        self,
        interaction: nextcord.Interaction,
        job_id: int = nextcord.SlashOption(description='Job ID to cancel', required=True),
    ) -> None:
        await self._cancel_job_interactive(interaction, job_id)

    @massunban_group.subcommand(name='recent', description='List recent mass unban jobs')
    @admin_only()
    @safe_slash_command(requires_db=True)
    async def massunban_recent_slash(self, interaction: nextcord.Interaction) -> None:
        await self._show_recent(interaction)

    @massunban_group.subcommand(
        name='preview',
        description='Preview how many bans match your filters without executing',
    )
    @admin_only()
    @safe_slash_command(requires_db=True)
    async def massunban_preview_slash(
        self,
        interaction: nextcord.Interaction,
        start_datetime: str = nextcord.SlashOption(
            description='Start of ban date range (ISO format, e.g. 2024-01-01)',
            required=True,
        ),
        end_datetime: str = nextcord.SlashOption(
            description='End of ban date range (ISO format, e.g. 2024-12-31)',
            required=True,
        ),
        banned_by: nextcord.Member | None = nextcord.SlashOption(
            description='Only count bans placed by this moderator (limited audit history)',
            required=False,
        ),
        include_unaudited: bool = nextcord.SlashOption(
            description='Also count bans with no recorded date/moderator',
            required=False,
            default=False,
        ),
        notify_users: bool = nextcord.SlashOption(
            description='Show how many users could be sent an apology DM',
            required=False,
            default=False,
        ),
    ) -> None:
        await self._preview_massunban(
            interaction, start_datetime, end_datetime, banned_by, include_unaudited, notify_users
        )

    # ============================================================
    # Prefix Commands
    # ============================================================

    @commands.group(name='massunban', invoke_without_command=True)
    @admin_only()
    @safe_command(requires_db=True)
    async def massunban_prefix(self, ctx: commands.Context) -> None:
        embed = await info_embed(
            title='Mass Unban Commands',
            description=(
                '**`!massunban run <start> <end> [@mod] [--notify] [reason]`** — Start a mass unban\n'
                '**`!massunban preview <start> <end> [@mod] [--notify]`** — Preview matching bans without executing\n'
                '**`!massunban status <job_id>`** — Check job status\n'
                '**`!massunban cancel <job_id>`** — Cancel a job\n'
                '**`!massunban recent`** — List recent jobs\n\n'
                'Dates must be ISO format (e.g. `2024-01-01` or `2024-01-01T00:00:00`).\n'
                f'`--notify` DMs an apology to unbanned users who share a server with the bot (max {DM_CAP_PER_JOB}); '
                'off by default. `include_unaudited` is slash-only.'
            ),
            contributor_source=__name__,
            user=ctx.author,
            guild=ctx.guild,
        )
        await safe_send(ctx, embed=embed)

    @massunban_prefix.command(name='run')
    @admin_only()
    @safe_command(requires_db=True)
    async def massunban_run_prefix(
        self,
        ctx: commands.Context,
        start_datetime: str,
        end_datetime: str,
        banned_by: nextcord.Member | None = None,
        *,
        reason: str = '',
    ) -> None:
        notify, reason = _pop_flag(reason, '--notify')
        await self._start_massunban(ctx, start_datetime, end_datetime, banned_by, reason, False, notify)

    @massunban_prefix.command(name='status')
    @admin_only()
    @safe_command(requires_db=True)
    async def massunban_status_prefix(self, ctx: commands.Context, job_id: int) -> None:
        await self._show_status(ctx, job_id)

    @massunban_prefix.command(name='cancel')
    @admin_only()
    @safe_command(requires_db=True)
    async def massunban_cancel_prefix(self, ctx: commands.Context, job_id: int) -> None:
        await self._cancel_job_interactive(ctx, job_id)

    @massunban_prefix.command(name='recent')
    @admin_only()
    @safe_command(requires_db=True)
    async def massunban_recent_prefix(self, ctx: commands.Context) -> None:
        await self._show_recent(ctx)

    @massunban_prefix.command(name='preview')
    @admin_only()
    @safe_command(requires_db=True)
    async def massunban_preview_prefix(
        self,
        ctx: commands.Context,
        start_datetime: str,
        end_datetime: str,
        banned_by: nextcord.Member | None = None,
        *,
        flags: str = '',
    ) -> None:
        """Preview how many bans match your filters without executing"""
        notify, _ = _pop_flag(flags, '--notify')
        await self._preview_massunban(ctx, start_datetime, end_datetime, banned_by, False, notify)

    # ============================================================
    # Shared: parse filters and match bans
    # ============================================================

    async def _match_from_filters(
        self,
        target: commands.Context | nextcord.Interaction,
        start_str: str,
        end_str: str,
        banned_by: nextcord.Member | None,
        include_unaudited: bool,
    ) -> tuple[nextcord.Guild, datetime, datetime, list, list, int] | None:
        """Validate input, list bans and match them. Sends the error and returns None on failure."""
        guild = getattr(target, 'guild', None)
        if not guild:
            embed = await error_embed('No Guild', 'This command must be used in a server.', contributor_source=__name__)
            await safe_send(target, embed=embed, ephemeral=True)
            return None

        parsed: list[datetime] = []
        for label, raw, example in (('start', start_str, '2024-01-01'), ('end', end_str, '2024-12-31')):
            try:
                value = datetime.fromisoformat(raw)
            except ValueError:
                embed = await error_embed(
                    'Invalid Date',
                    f'Could not parse {label} date: `{raw[:40]}`\nUse ISO format (e.g. `{example}` or `{example}T00:00:00`).',
                    contributor_source=__name__,
                )
                await safe_send(target, embed=embed, ephemeral=True)
                return None
            parsed.append(value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC))
        start_dt, end_dt = parsed

        if start_dt >= end_dt:
            embed = await error_embed(
                'Invalid Range', 'Start date must be before end date.', contributor_source=__name__
            )
            await safe_send(target, embed=embed, ephemeral=True)
            return None

        try:
            bans = [ban async for ban in guild.bans(limit=None)]
        except (nextcord.Forbidden, nextcord.HTTPException):
            embed = await error_embed(
                'Missing Permission', 'I need the **Ban Members** permission to list bans.', contributor_source=__name__
            )
            await safe_send(target, embed=embed, ephemeral=True)
            return None

        if not bans:
            embed = await info_embed(
                'No Bans', 'There are no banned users in this server.', contributor_source=__name__
            )
            await safe_send(target, embed=embed, ephemeral=True)
            return None

        audit_records = await self._fetch_audit_records(guild.id)
        matched, no_audit_count = match_bans(
            bans, audit_records, start_dt, end_dt, banned_by.id if banned_by else None, include_unaudited
        )
        return guild, start_dt, end_dt, bans, matched, no_audit_count

    def _dm_reachable(self, user_ids: list[int], guild_id: int) -> int:
        """How many of these users currently share a server with the bot (other than the unbanning one)."""
        others = [g for g in self.bot.guilds if g.id != guild_id]
        return sum(1 for uid in user_ids if any(g.get_member(uid) is not None for g in others))

    # ============================================================
    # Core Logic — Start Mass Unban
    # ============================================================

    async def _start_massunban(
        self,
        target: commands.Context | nextcord.Interaction,
        start_str: str,
        end_str: str,
        banned_by: nextcord.Member | None,
        reason: str,
        include_unaudited: bool = False,
        notify_users: bool = False,
    ) -> None:
        # Listing bans can take longer than the 3 s interaction deadline.
        if isinstance(target, nextcord.Interaction) and not target.response.is_done():
            await target.response.defer(ephemeral=True)

        guild = getattr(target, 'guild', None)
        user = target.user if isinstance(target, nextcord.Interaction) else target.author

        # Guard against concurrent jobs per guild
        if guild is not None:
            active = await db.fetchval(
                """SELECT EXISTS(
                    SELECT 1 FROM massunban_jobs
                    WHERE guild_id = $1 AND status = ANY($2::text[])
                )""",
                guild.id,
                list(ACTIVE_JOB_STATUSES),
            )
            if active:
                embed = await error_embed(
                    'Job Already Running',
                    'There is already a mass unban job in progress for this server. '
                    'Please wait for it to finish or cancel it first.',
                    contributor_source=__name__,
                )
                await safe_send(target, embed=embed, ephemeral=True)
                return

        matched_result = await self._match_from_filters(target, start_str, end_str, banned_by, include_unaudited)
        if matched_result is None:
            return
        guild, start_dt, end_dt, _bans, matched_bans, no_audit_count = matched_result

        if not matched_bans:
            embed = await info_embed('No Matches', 'No bans match your filters.', contributor_source=__name__)
            if no_audit_count > 0:
                embed.add_field(
                    name='Note',
                    value=(
                        f'{no_audit_count} ban(s) have no audit history (no recorded date/moderator) and were '
                        'excluded. Use `include_unaudited:true` to include them (not possible with a moderator filter).'
                    ),
                    inline=False,
                )
            await safe_send(target, embed=embed, ephemeral=True)
            return

        reason = (reason or '').strip()[:300]
        try:
            job_id = await self._create_job(
                guild.id, user.id, start_dt, end_dt, banned_by, reason, matched_bans, notify_users
            )
        except _JobInProgress:
            embed = await error_embed(
                'Job Already Running',
                'There is already a mass unban job in progress for this server.',
                contributor_source=__name__,
            )
            await safe_send(target, embed=embed, ephemeral=True)
            return
        except Exception:
            logger.error('Failed to create mass unban job', exc_info=True)
            embed = await error_embed('DB Error', 'Failed to create the job record.', contributor_source=__name__)
            await safe_send(target, embed=embed, ephemeral=True)
            return

        reachable = self._dm_reachable([ban.user.id for ban, _ in matched_bans], guild.id) if notify_users else 0
        embed = await self._build_preview_embed(
            job_id,
            len(matched_bans),
            start_dt,
            end_dt,
            banned_by,
            reason,
            no_audit_count,
            include_unaudited,
            notify_users=notify_users,
            dm_reachable=reachable,
        )

        view = ConfirmFirstView(job_id=job_id, runner_id=user.id)
        if not await _safe_send_view(target, embed=embed, view=view, ephemeral=True):
            await self._set_status(job_id, 'failed')
            return
        await self._set_status(job_id, 'confirming')

        await view.wait()
        if view.result is not True:
            await self._set_status(job_id, 'cancelled')
            text = 'Confirmation timed out. Job cancelled.' if view.result is None else 'Job cancelled by operator.'
            await safe_send(
                target, embed=await info_embed('Cancelled', text, contributor_source=__name__), ephemeral=True
            )
            return

        dm_line = (
            f'Apology DMs: **on** — at most {min(DM_CAP_PER_JOB, reachable)} user(s) who still share a server '
            'with the bot.\n'
            if notify_users
            else 'Apology DMs: **off**.\n'
        )
        embed2 = await veka_embed(
            title=f'⚡ Final Confirmation — Unban {len(matched_bans)} Users',
            description=(
                f'You are about to unban **{len(matched_bans)}** users.\n\n'
                f'{dm_line}'
                'The job is **resumable** if interrupted. Progress is shown in one message in the log channel.\n\n'
                'Click **Confirm Unban** to proceed.'
            ),
            contributor_source=__name__,
            user=user,
            guild=guild,
        )
        view2 = ConfirmSecondView(job_id=job_id, runner_id=user.id, count=len(matched_bans))
        if not await _safe_send_view(target, embed=embed2, view=view2, ephemeral=True):
            await self._set_status(job_id, 'cancelled')
            return

        await view2.wait()
        if view2.result is not True:
            await self._set_status(job_id, 'cancelled')
            text = 'Confirmation timed out. Job cancelled.' if view2.result is None else 'Job cancelled by operator.'
            await safe_send(
                target, embed=await info_embed('Cancelled', text, contributor_source=__name__), ephemeral=True
            )
            return

        await db.execute("UPDATE massunban_jobs SET status = 'running', started_at = NOW() WHERE id = $1", job_id)
        try:
            await audit_log.record(
                user_id=str(user.id),
                action='massunban_started',
                details={'job_id': job_id, 'matched': len(matched_bans), 'notify_users': notify_users},
                guild_id=str(guild.id),
                severity='warning',
            )
        except Exception:
            logger.warning('Failed to audit start of mass unban job %s', job_id, exc_info=True)

        self._active_jobs[job_id] = False
        self._rate_limit_count[job_id] = 0
        self._unban_interval[job_id] = BASE_UNBAN_INTERVAL
        # Run in the background: a job can take hours, far beyond the command's lifetime.
        self._spawn_worker(self._execute_job(job_id, resumed=False), name=f'massunban:{job_id}')

        log_channel = await self._log_channel(guild)
        where = f'in {log_channel.mention}' if log_channel else 'with `/massunban status`'
        embed3 = await info_embed(
            'Mass Unban Started',
            f'Job **#{job_id}** is running ({len(matched_bans)} users). Follow its progress {where}.',
            contributor_source=__name__,
        )
        await safe_send(target, embed=embed3, ephemeral=True)

    @staticmethod
    async def _create_job(guild_id, user_id, start_dt, end_dt, banned_by, reason, matched_bans, notify_users) -> int:
        """Check-and-insert under the per-guild advisory lock (same key as the API), job + items atomically."""
        async with db.transaction() as conn:
            await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1::text, 0))', f'massunban:{guild_id}')
            busy = await conn.fetchval(
                'SELECT 1 FROM massunban_jobs WHERE guild_id = $1 AND status = ANY($2::text[]) LIMIT 1',
                guild_id,
                list(ACTIVE_JOB_STATUSES),
            )
            if busy:
                raise _JobInProgress
            job_id = await conn.fetchval(
                """INSERT INTO massunban_jobs
                   (guild_id, requested_by, status, start_datetime, end_datetime, banned_by, reason,
                    total_matched, notify_users)
                   VALUES ($1, $2, 'pending', $3, $4, $5, $6, $7, $8)
                   RETURNING id""",
                guild_id,
                user_id,
                start_dt,
                end_dt,
                banned_by.id if banned_by else None,
                reason or None,
                len(matched_bans),
                notify_users,
            )
            await conn.executemany(
                """INSERT INTO massunban_job_items
                   (job_id, target_user_id, target_username, ban_reason, banned_by, dm_status)
                   VALUES ($1, $2, $3, $4, $5, 'skipped')""",
                [
                    (
                        job_id,
                        str(ban.user.id),
                        str(ban.user)[:100],
                        (ban.reason or '')[:500] or None,
                        int(record['moderator_id']) if record and record.get('moderator_id') else None,
                    )
                    for ban, record in matched_bans
                ],
            )
        return job_id

    async def _set_status(self, job_id: int, status: str) -> None:
        try:
            completed = ', completed_at = NOW()' if status in ('cancelled', 'failed', 'completed') else ''
            # A cancellation is final: nothing else may overwrite it.
            await db.execute(
                f"UPDATE massunban_jobs SET status = $1{completed} WHERE id = $2 AND status <> 'cancelled'",
                status,
                job_id,
            )
        except Exception:
            logger.warning('Failed to set job %s to %s', job_id, status, exc_info=True)

    # ============================================================
    # Core Logic — Preview Mass Unban
    # ============================================================

    async def _preview_massunban(
        self,
        target: commands.Context | nextcord.Interaction,
        start_str: str,
        end_str: str,
        banned_by: nextcord.Member | None,
        include_unaudited: bool = False,
        notify_users: bool = False,
    ) -> None:
        """Preview how many bans match filters without executing any unbans."""
        if isinstance(target, nextcord.Interaction) and not target.response.is_done():
            await target.response.defer(ephemeral=True)
        matched_result = await self._match_from_filters(target, start_str, end_str, banned_by, include_unaudited)
        if matched_result is None:
            return
        guild, start_dt, end_dt, bans, matched, no_audit_count = matched_result
        matched_count = len(matched)
        estimated_minutes = matched_count * BASE_UNBAN_INTERVAL / 60

        embed = await veka_embed(
            title='Mass Unban — Preview',
            description=(
                f'**{len(bans)}** total ban(s) in this server.\n'
                f'**{matched_count}** ban(s) match your filters.\n\n'
                f'**Estimated duration:** ~{estimated_minutes:.1f} minutes'
            ),
            contributor_source=__name__,
        )
        embed.add_field(
            name='Date Range',
            value=f'{start_dt.strftime("%Y-%m-%d %H:%M:%S UTC")} → {end_dt.strftime("%Y-%m-%d %H:%M:%S UTC")}',
            inline=False,
        )
        if banned_by:
            embed.add_field(name='Moderator Filter', value=banned_by.mention, inline=False)
        if no_audit_count > 0:
            embed.add_field(
                name='Audit Limitation',
                value=(
                    f'{no_audit_count} ban(s) have no audit history and will be '
                    f'{"included" if include_unaudited and not banned_by else "excluded"}.'
                ),
                inline=False,
            )
        embed.add_field(name='Apology DMs', value=_dm_summary(notify_users, matched, guild.id, self), inline=False)
        embed.add_field(name='Important Note', value=_AUDIT_LIMITATION, inline=False)
        await safe_send(target, embed=embed, ephemeral=True)

    # ============================================================
    # Core Logic — Execute Job
    # ============================================================

    async def _execute_job(self, job_id: int, *, resumed: bool = False) -> None:
        """Sequential unban worker with rate limiting. At most one worker runs per job."""
        if self._unloaded:
            return
        lock = self._job_locks.setdefault(job_id, asyncio.Lock())
        if lock.locked():
            logger.info('Job %s already has a running worker; not starting another', job_id)
            return
        task = asyncio.current_task()
        if task is not None:
            self._workers.add(task)
        try:
            async with lock:
                await self._run_job(job_id, resumed=resumed)
        finally:
            if task is not None:
                self._workers.discard(task)
            self._job_locks.pop(job_id, None)

    async def _run_job(self, job_id: int, *, resumed: bool) -> None:
        guild: nextcord.Guild | None = None
        try:
            job = await db.fetch_one('SELECT * FROM massunban_jobs WHERE id = $1', job_id)
            if not job:
                return

            guild = self.bot.get_guild(job['guild_id'])
            if not guild:
                await self._set_status(job_id, 'failed')
                return

            items = await db.fetch(
                """SELECT * FROM massunban_job_items
                   WHERE job_id = $1 AND status = 'pending'
                   ORDER BY id ASC""",
                job_id,
            )
            if not items:
                await self._complete_job(job_id, guild)
                return

            interval = self._unban_interval.get(job_id, BASE_UNBAN_INTERVAL)
            await self._update_progress(job_id, guild, note='Resumed.' if resumed else 'Started.', force=True)

            for item in items:
                if self._active_jobs.get(job_id, True):
                    await self._set_status(job_id, 'cancelled')
                    await self._update_progress(job_id, guild, note='Cancelled by operator.', force=True)
                    self._forget_job(job_id)
                    return

                # The persisted status is authoritative (a dashboard cancel may not have reached us as a
                # NOTIFY). Checked before every unban; if it can't be read, stop rather than act blind.
                try:
                    persisted = await db.fetchval('SELECT status FROM massunban_jobs WHERE id = $1', job_id)
                except Exception:
                    persisted = None
                if persisted is None or not runtime_state.db_available:
                    logger.warning('Cannot confirm status of job %s — pausing', job_id)
                    try:
                        await db.execute(
                            "UPDATE massunban_jobs SET status = 'paused' WHERE id = $1 AND status = 'running'", job_id
                        )
                    except Exception:
                        pass
                    await self._update_progress(job_id, guild, note='Paused: database unavailable.', force=True)
                    return
                if persisted != 'running':
                    await self._update_progress(job_id, guild, note=f'Stopped: job is {persisted}.', force=True)
                    self._forget_job(job_id)
                    return

                result = await self._process_unban_item(guild, item, job)

                if result.get('rate_limit'):
                    # Leave this item pending, stop this worker, and let one scheduled resume pick it up.
                    await self._handle_rate_limit_pause(job_id, guild, result)
                    return

                if result.get('forbidden'):
                    # Leave this item pending and stop: retrying the rest would only repeat the 403.
                    await self._abort_job_forbidden(job_id, guild, job, result['failure_reason'])
                    return

                if result['status'] == 'success' and job.get('notify_users'):
                    dm_status, dm_reason = await self._maybe_send_dm(job_id, guild, result['user_id'])
                    result['dm_status'] = dm_status
                    result['dm_failure_reason'] = dm_reason

                await self._update_job_progress(job_id, item, result)
                await self._update_progress(job_id, guild)
                await asyncio.sleep(interval)

            await self._complete_job(job_id, guild)

        except Exception:
            logger.error('Fatal error in mass unban job %s', job_id, exc_info=True)
            try:
                await db.execute(
                    """UPDATE massunban_jobs
                       SET status = 'failed', completed_at = NOW(),
                           metadata = COALESCE(metadata, '{}'::jsonb) || '{"fatal_error": true}'::jsonb
                       WHERE id = $1 AND status <> 'cancelled'""",
                    job_id,
                )
            except Exception:
                logger.error('Failed to mark job %s as failed after fatal error', job_id, exc_info=True)
            if guild is not None:
                await self._update_progress(job_id, guild, note='Stopped by an internal error.', force=True)
            self._forget_job(job_id)

    async def _process_unban_item(self, guild: nextcord.Guild, item: dict, job: dict) -> dict[str, Any]:
        """Unban one user with a single API call. A 404 means the user is no longer banned."""
        user_id = int(item['target_user_id'])
        result: dict[str, Any] = {
            'user_id': user_id,
            'username': item['target_username'],
            'status': 'pending',
            'dm_status': 'skipped',
        }
        reason_parts = ['Mass unban']
        if job.get('requested_by'):
            reason_parts.append(f'by {job["requested_by"]}')
        if job.get('reason'):
            reason_parts.append(f'— {job["reason"]}')
        try:
            await guild.unban(nextcord.Object(id=user_id), reason=' '.join(reason_parts)[:512])
            result['status'] = 'success'
            result['unbanned_at'] = datetime.now(UTC)
        except nextcord.NotFound:
            result['status'] = 'skipped'
            result['failure_reason'] = 'Already unbanned'
        except nextcord.Forbidden as exc:
            # Must precede HTTPException (its parent class). Every remaining unban would fail the same way.
            return _forbidden_result(result, exc)
        except nextcord.HTTPException as exc:
            if exc.status == 429:
                retry_after: float = float(RATE_LIMIT_COOLDOWN)
                headers = getattr(getattr(exc, 'response', None), 'headers', None) or {}
                try:
                    retry_after = float(headers.get('Retry-After', retry_after))
                except (TypeError, ValueError):
                    pass
                result['failure_reason'] = f'Rate limited (retry_after={retry_after}s)'
                result['retry_after'] = retry_after
                result['rate_limit'] = True
                return result
            result['status'] = 'failed'
            result['failure_reason'] = f'Discord API error {exc.status}/{exc.code}'
        except Exception as exc:
            result['status'] = 'failed'
            result['failure_reason'] = type(exc).__name__
        return result

    async def _maybe_send_dm(self, job_id: int, guild: nextcord.Guild, user_id: int) -> tuple[str, str | None]:
        """Apology DM for an opted-in job, within the per-job cap, spacing and failure limits."""
        state = self._dm_state.setdefault(job_id, {'failures_in_row': 0, 'last_dm': None, 'disabled': False})
        if state['disabled']:
            return 'skipped', 'DMs stopped after repeated failures'
        sent = await db.fetchval('SELECT dm_sent FROM massunban_jobs WHERE id = $1', job_id) or 0
        if sent >= DM_CAP_PER_JOB:
            return 'skipped', f'Per-job DM cap ({DM_CAP_PER_JOB}) reached'

        user = self.bot.get_user(user_id)
        if user is None or not any(g.get_member(user_id) is not None for g in self.bot.guilds if g.id != guild.id):
            return 'skipped', 'Shares no server with the bot'

        if state['last_dm'] is not None:
            wait = DM_MIN_INTERVAL - (time.monotonic() - state['last_dm'])
            if wait > 0:
                await asyncio.sleep(wait)
        state['last_dm'] = time.monotonic()

        outcome = await outbound.dm(
            user,
            kind='massunban_apology',
            content=DM_APOLOGY_TEMPLATE.format(guild_name=guild.name),
            dedupe_key=f'massunban:{guild.id}:{user_id}',
            dedupe_window=86400,
        )
        if outcome.ok:
            state['failures_in_row'] = 0
            return 'sent', None
        if outcome.status in (SendStatus.FORBIDDEN, SendStatus.FAILED):
            state['failures_in_row'] += 1
            if state['failures_in_row'] >= DM_MAX_CONSECUTIVE_FAILURES:
                state['disabled'] = True
                logger.info('Mass unban job %s: apology DMs stopped after repeated failures', job_id)
            return 'failed', outcome.error or outcome.status.value
        return 'skipped', outcome.status.value

    async def _update_job_progress(self, job_id: int, item: dict, result: dict) -> None:
        """Persist one item's result and the job counters."""
        try:
            await db.execute(
                """UPDATE massunban_job_items
                   SET status = $1, failure_reason = $2, unbanned_at = $3,
                       dm_status = $4, dm_failure_reason = $5
                   WHERE id = $6""",
                result['status'],
                (result.get('failure_reason') or '')[:500] or None,
                result.get('unbanned_at'),
                result.get('dm_status', 'skipped'),
                (result.get('dm_failure_reason') or '')[:200] or None,
                item['id'],
            )
        except Exception:
            logger.warning('Failed to update item %s for job %s', item['id'], job_id, exc_info=True)

        counter_col = {
            'success': 'total_succeeded',
            'failed': 'total_failed',
            'skipped': 'total_skipped',
        }.get(result['status'])
        if counter_col is None:
            return
        dm_sent = 1 if result.get('dm_status') == 'sent' else 0
        dm_failed = 1 if result.get('dm_status') == 'failed' else 0
        try:
            await db.execute(
                f"""UPDATE massunban_jobs
                    SET {counter_col} = {counter_col} + 1,
                        total_attempted = total_attempted + 1,
                        dm_sent = dm_sent + $3,
                        dm_failed = dm_failed + $4,
                        last_processed_user_id = $1
                    WHERE id = $2""",
                str(result['user_id']),
                job_id,
                dm_sent,
                dm_failed,
            )
        except Exception:
            logger.warning('Failed to update counters for job %s', job_id, exc_info=True)

    async def _abort_job_forbidden(self, job_id: int, guild: nextcord.Guild, job: dict, reason: str) -> None:
        """Stop a job whose unbans Discord refuses (403). Remaining items stay pending."""
        logger.warning('Mass unban job %s stopped: %s', job_id, reason)
        try:
            await db.execute(
                """UPDATE massunban_jobs
                   SET status = 'failed', completed_at = NOW(),
                       metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object('forbidden', $2::text)
                   WHERE id = $1 AND status <> 'cancelled'""",
                job_id,
                reason,
            )
        except Exception:
            logger.error('Failed to mark job %s as failed after 403', job_id, exc_info=True)

        note = (
            f'Discord refused the unban, so the job was stopped.\n**Reason:** {reason}\n'
            'Users not yet processed are still banned. Fix the cause, then run a new mass unban with the same filters.'
        )
        await self._update_progress(job_id, guild, note=note, force=True)
        await self._notify_runner_once(job, guild, f'⛔ Mass Unban #{job_id} stopped', note)
        self._forget_job(job_id)

    async def _handle_rate_limit_pause(self, job_id: int, guild: nextcord.Guild, result: dict) -> None:
        """Persist the pause, show it on the progress message, and schedule exactly one resume."""
        retry_after_secs = max(1.0, float(result.get('retry_after', RATE_LIMIT_COOLDOWN)))
        try:
            await db.execute(
                """UPDATE massunban_jobs
                   SET status = 'retry_wait', retry_after = $1, rate_limit_hits = rate_limit_hits + 1
                   WHERE id = $2 AND status = 'running'""",
                datetime.now(UTC) + timedelta(seconds=retry_after_secs),
                job_id,
            )
        except Exception:
            logger.error('Failed to persist rate limit pause for job %s', job_id, exc_info=True)

        self._rate_limit_count[job_id] = self._rate_limit_count.get(job_id, 0) + 1
        if self._rate_limit_count[job_id] >= PAUSE_THRESHOLD:
            self._unban_interval[job_id] = min(
                self._unban_interval.get(job_id, BASE_UNBAN_INTERVAL) * 2,
                BASE_UNBAN_INTERVAL * MAX_BACKOFF_MULTIPLIER,
            )
        await self._update_progress(
            job_id, guild, note=f'Rate limited by Discord; resuming in {retry_after_secs:.0f}s.', force=True
        )
        self._spawn_worker(self._scheduled_resume(job_id, retry_after_secs), name=f'massunban:resume:{job_id}')

    async def _scheduled_resume(self, job_id: int, delay: float) -> None:
        """Wait then resume a rate-limited job, checking for cancellation first."""
        await asyncio.sleep(delay + 1)
        if self._active_jobs.get(job_id, True):
            return
        await self._resume_job(job_id)

    async def _resume_job(self, job_id: int) -> None:
        """Resume a paused/retry_wait job."""
        try:
            if not runtime_state.db_available:
                return
            result = await db.execute(
                "UPDATE massunban_jobs SET status = 'running' WHERE id = $1 AND status IN ('retry_wait', 'paused')",
                job_id,
            )
            if result == 'UPDATE 0':
                logger.info('Job %s no longer resumable — skipping', job_id)
                return
            if not self._active_jobs.get(job_id, True):
                self._active_jobs[job_id] = False
            self._rate_limit_count.setdefault(job_id, 0)
            self._unban_interval.setdefault(job_id, BASE_UNBAN_INTERVAL)
            await self._execute_job(job_id, resumed=True)
        except Exception:
            logger.error('Failed to resume mass unban job %s', job_id, exc_info=True)

    async def _complete_job(self, job_id: int, guild: nextcord.Guild) -> None:
        """Mark the job completed, finalise the progress message and send one summary to the runner."""
        try:
            # Never turn a cancelled/failed job into "completed".
            finished = await db.fetchval(
                """UPDATE massunban_jobs SET status = 'completed', completed_at = NOW()
                   WHERE id = $1 AND status = 'running' RETURNING id""",
                job_id,
            )
            job = await db.fetch_one('SELECT * FROM massunban_jobs WHERE id = $1', job_id)
            if not job or finished is None:
                return
            await self._update_progress(job_id, guild, note='Finished.', force=True)
            summary = _summary_text(job)
            failures = await db.fetch(
                """SELECT target_user_id, target_username, failure_reason FROM massunban_job_items
                   WHERE job_id = $1 AND status = 'failed' ORDER BY id""",
                job_id,
            )
            file = None
            if failures:
                lines = [
                    f'{r["target_user_id"]}\t{r["target_username"]}\t{r["failure_reason"] or ""}' for r in failures
                ]
                file = nextcord.File(io.BytesIO('\n'.join(lines).encode()), filename=f'massunban-{job_id}-failures.txt')
            log_channel = await self._log_channel(guild)
            if log_channel is not None and file is not None:
                await outbound.send(
                    log_channel,
                    kind='massunban_summary',
                    content=f'Mass unban #{job_id}: {len(failures)} failed unban(s).',
                    file=file,
                    essential=True,
                    dedupe_key=f'massunban:{job_id}:failures',
                )
            await self._notify_runner_once(job, guild, f'✅ Mass Unban #{job_id} complete', summary)
        except Exception:
            logger.error('Failed to complete job %s', job_id, exc_info=True)
        finally:
            self._forget_job(job_id)

    async def _notify_runner_once(self, job: dict, guild: nextcord.Guild, title: str, description: str) -> None:
        """One final DM to the operator who started the job (a current member of the guild)."""
        member = guild.get_member(job['requested_by'])
        if member is None:
            return
        embed = await veka_embed(title=title, description=description[:4000], contributor_source=__name__)
        await outbound.dm(
            member,
            kind='massunban_runner',
            embed=embed,
            essential=True,
            dedupe_key=f'massunban:{job["id"]}:final',
            dedupe_window=86400,
        )

    async def _build_preview_embed(
        self,
        job_id: int,
        ban_count: int,
        start_dt: datetime,
        end_dt: datetime,
        banned_by: nextcord.Member | None,
        reason: str,
        no_audit_count: int,
        include_unaudited: bool = False,
        *,
        notify_users: bool = False,
        dm_reachable: int = 0,
    ) -> nextcord.Embed:
        embed = await veka_embed(
            title='Mass Unban — Confirm',
            description=f'**{ban_count} ban(s)** match your filters.',
            contributor_source=__name__,
        )
        embed.add_field(name='Job ID', value=str(job_id), inline=False)
        embed.add_field(
            name='Date Range',
            value=f'{start_dt.strftime("%Y-%m-%d %H:%M:%S UTC")} → {end_dt.strftime("%Y-%m-%d %H:%M:%S UTC")}',
            inline=False,
        )
        if banned_by:
            embed.add_field(name='Moderator Filter', value=banned_by.mention, inline=False)
        if reason:
            embed.add_field(name='Reason', value=reason[:1000], inline=False)
        if no_audit_count > 0:
            embed.add_field(
                name='Note',
                value=(
                    f'{no_audit_count} ban(s) have no audit history and will be '
                    + (
                        '**included regardless of the date range** (include_unaudited).'
                        if include_unaudited and not banned_by
                        else 'excluded.'
                    )
                ),
                inline=False,
            )
        embed.add_field(
            name='Apology DMs',
            value=(
                f'On — at most **{min(DM_CAP_PER_JOB, dm_reachable)}** of {ban_count} users can be DMed '
                f'(only users who still share a server with the bot; max {DM_CAP_PER_JOB}, '
                f'{DM_MIN_INTERVAL:.0f}s apart, stops after {DM_MAX_CONSECUTIVE_FAILURES} failures in a row).'
                if notify_users
                else 'Off. Use `notify_users:true` to DM an apology to users who still share a server with the bot.'
            ),
            inline=False,
        )
        embed.add_field(name='Audit Limitation', value=_AUDIT_LIMITATION, inline=False)
        embed.add_field(
            name='Confirm',
            value='This action will unban all matched users. Double confirmation required.',
            inline=False,
        )
        return embed

    # ============================================================
    # Progress message
    # ============================================================

    async def _update_progress(
        self, job_id: int, guild: nextcord.Guild, *, note: str = '', force: bool = False
    ) -> None:
        """Edit the job's single progress message in the log channel (throttled unless ``force``)."""
        now = time.monotonic()
        last = self._last_progress.get(job_id)
        if not force and last is not None and now - last < PROGRESS_EDIT_INTERVAL:
            return
        self._last_progress[job_id] = now
        log_channel = await self._log_channel(guild)
        if log_channel is None:
            return
        try:
            job = await db.fetch_one('SELECT * FROM massunban_jobs WHERE id = $1', job_id)
            if not job:
                return
            embed = await veka_embed(
                title=f'\U0001f4cb Mass Unban #{job_id} — {job["status"].replace("_", " ").title()}',
                description=_summary_text(job) + (f'\n\n{note}' if note else ''),
                contributor_source=__name__,
            )
            existing = None
            if job.get('progress_message_id') and job.get('progress_channel_id') == log_channel.id:
                existing = log_channel.get_partial_message(job['progress_message_id'])
            outcome = await outbound.upsert_status(
                f'massunban:{job_id}', log_channel, kind='massunban_progress', embed=embed, message=existing
            )
            if outcome.status == SendStatus.SENT and outcome.message is not None:
                await db.execute(
                    'UPDATE massunban_jobs SET progress_channel_id = $1, progress_message_id = $2 WHERE id = $3',
                    log_channel.id,
                    outcome.message.id,
                    job_id,
                )
        except Exception:
            logger.debug('Failed to update progress for mass unban job %s', job_id, exc_info=True)

    async def _cancel_job(self, job_id: int, _runner_id: int) -> None:
        """Cancel a running job."""
        self._active_jobs[job_id] = True
        try:
            await db.execute(
                "UPDATE massunban_jobs SET status = 'cancelled', completed_at = NOW() WHERE id = $1 AND status NOT IN ('completed', 'cancelled')",
                job_id,
            )
        except Exception:
            logger.warning('Failed to update job %s to cancelled in DB', job_id, exc_info=True)

    async def _cancel_job_interactive(
        self,
        target: commands.Context | nextcord.Interaction,
        job_id: int,
    ) -> None:
        """Cancel a job via command."""
        guild_id = target.guild.id if target.guild else 0
        job = await db.fetch_one('SELECT * FROM massunban_jobs WHERE id = $1 AND guild_id = $2', job_id, guild_id)
        if not job:
            embed = await error_embed('Not Found', f'Job #{job_id} not found.', contributor_source=__name__)
            await safe_send(target, embed=embed, ephemeral=True)
            return

        user = target.user if isinstance(target, nextcord.Interaction) else target.author
        if job['requested_by'] != user.id and user.id not in OWNER_IDS:
            embed = await error_embed(
                'Not Allowed', 'Only the job runner or owners can cancel.', contributor_source=__name__
            )
            await safe_send(target, embed=embed, ephemeral=True)
            return

        if job['status'] in ('completed', 'cancelled'):
            embed = await info_embed(
                'Already Done',
                f'Job #{job_id} is already **{job["status"]}**.',
                contributor_source=__name__,
            )
            await safe_send(target, embed=embed, ephemeral=True)
            return

        await self._cancel_job(job_id, user.id)
        embed = await success_embed(
            'Job Cancelled',
            f'Job #{job_id} has been cancelled.',
            contributor_source=__name__,
        )
        await safe_send(target, embed=embed, ephemeral=True)

        guild = self.bot.get_guild(job['guild_id'])
        if guild:
            # A running worker notices the flag and finalises the progress message itself.
            if job_id not in self._active_jobs:
                await self._update_progress(job_id, guild, note=f'Cancelled by {user.mention}.', force=True)

    # ============================================================
    # Status / Recent
    # ============================================================

    async def _show_status(self, target: commands.Context | nextcord.Interaction, job_id: int) -> None:
        guild_id = target.guild.id if target.guild else 0
        job = await db.fetch_one('SELECT * FROM massunban_jobs WHERE id = $1 AND guild_id = $2', job_id, guild_id)
        if not job:
            embed = await error_embed('Not Found', f'Job #{job_id} not found.', contributor_source=__name__)
            await safe_send(target, embed=embed, ephemeral=True)
            return

        status_emoji = {
            'pending': '\u23f3',
            'confirming': '\u2753',
            'running': '\u26a1',
            'paused': '\u23f8\ufe0f',
            'retry_wait': '\u23f1\ufe0f',
            'completed': '\u2705',
            'failed': '\u274c',
            'cancelled': '\U0001f6ab',
        }.get(job['status'], '\u2753')

        duration = ''
        if job.get('started_at'):
            end = job.get('completed_at') or datetime.now(UTC)
            delta = end - job['started_at']
            mins, secs = divmod(int(delta.total_seconds()), 60)
            duration = f'{mins}m {secs}s' if mins else f'{secs}s'

        embed = await veka_embed(
            title=f'{status_emoji} Mass Unban Job #{job_id}',
            description=(
                f'**Status:** {job["status"].title()}\n'
                f'**Requested by:** <@{job["requested_by"]}>\n'
                f'**Date range:** {_format_dt_short(job["start_datetime"])} → {_format_dt_short(job["end_datetime"])}\n'
                + (f'**Banned by:** <@{job["banned_by"]}>\n' if job.get('banned_by') else '')
                + (f'**Reason:** {job["reason"]}\n' if job.get('reason') else '')
                + f'\n**Matched:** {job["total_matched"]}\n'
                f'**Attempted:** {job["total_attempted"]}\n'
                f'\u2705 **Succeeded:** {job["total_succeeded"]}\n'
                f'\u23ed\ufe0f **Skipped:** {job["total_skipped"]}\n'
                f'\u274c **Failed:** {job["total_failed"]}\n'
                + (f'**Duration:** {duration}\n' if duration else '')
                + (f'**Retry after:** {_format_dt(job["retry_after"])}\n' if job.get('retry_after') else '')
            ),
            contributor_source=__name__,
        )
        await safe_send(target, embed=embed, ephemeral=True)

    async def _show_recent(self, target: commands.Context | nextcord.Interaction) -> None:
        guild = getattr(target, 'guild', None)
        if not guild:
            embed = await error_embed('No Guild', 'This command must be used in a server.', contributor_source=__name__)
            await safe_send(target, embed=embed, ephemeral=True)
            return

        jobs = await db.fetch(
            """SELECT id, status, total_matched, total_succeeded, total_failed, total_skipped, created_at, completed_at
               FROM massunban_jobs
               WHERE guild_id = $1
               ORDER BY created_at DESC
               LIMIT 10""",
            guild.id,
        )

        if not jobs:
            embed = await info_embed(
                'No Jobs',
                'No mass unban jobs found for this server.',
                contributor_source=__name__,
            )
            await safe_send(target, embed=embed, ephemeral=True)
            return

        lines = []
        for j in jobs:
            status_emoji = {
                'completed': '\u2705',
                'running': '\u26a1',
                'cancelled': '\U0001f6ab',
                'failed': '\u274c',
            }.get(j['status'], '\u23f3')
            lines.append(
                f'{status_emoji} **#{j["id"]}** — {j["total_matched"]} matched, '
                f'{j["total_succeeded"]} unbanned — {_format_dt(j["created_at"], "R")}'
            )

        embed = await veka_embed(
            title='Recent Mass Unban Jobs',
            description='\n'.join(lines),
            contributor_source=__name__,
        )
        await safe_send(target, embed=embed, ephemeral=True)

    # ============================================================
    # Audit Helpers
    # ============================================================

    async def _fetch_audit_records(self, guild_id: int) -> dict[str, dict]:
        """Fetch bot-recorded ban actions from audit_logs for date/moderator matching."""
        try:
            rows = await db.fetch(
                """SELECT details, created_at
                   FROM audit_logs
                   WHERE guild_id = $1
                     AND action IN ('ban_executed', 'honeypot_ban', 'moderation_ban')
                   ORDER BY created_at DESC""",
                str(guild_id),
            )
            records: dict[str, dict] = {}
            for row in rows:
                try:
                    details = json.loads(row['details']) if row['details'] else {}
                except (json.JSONDecodeError, TypeError):
                    continue
                user_id = details.get('user_id') or details.get('target_user_id')
                if user_id and user_id not in records:
                    records[str(user_id)] = {
                        'created_at': row['created_at'],
                        'moderator_id': str(details.get('moderator_id') or details.get('actor_id') or ''),
                    }
            return records
        except Exception:
            logger.warning('Failed to fetch audit records for guild %s', guild_id, exc_info=True)
            return {}

    # ============================================================
    # Log channel
    # ============================================================

    async def _log_channel(self, guild: nextcord.Guild) -> nextcord.TextChannel | None:
        """Log channel for this guild only — never another server's channel (cross-guild fallback removed)."""
        channel: nextcord.abc.GuildChannel | None = (
            guild.get_channel(MASSUNBAN_LOG_CHANNEL_ID) if MASSUNBAN_LOG_CHANNEL_ID else None
        )
        if channel is None:
            try:
                channel = await guild_settings_service.resolve_channel(guild, 'log_channel_id')
            except Exception:
                channel = None
        return channel if isinstance(channel, nextcord.TextChannel) else None


# ============================================================
# Setup
# ============================================================


def setup(bot: commands.Bot) -> None:
    bot.add_cog(MassUnban(bot))
    logger.info('Loaded cog: src.cogs.admin.massunban')
