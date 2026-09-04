"""
Mass Unban Cog — Resumable bulk-unban with double confirmation and per-user audit.

Provides /massunban and !massunban commands for admin-only bulk unban operations
with date-range and moderator filters, persistent job tracking, rate-limit handling,
DM notifications, and detailed audit logging.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import nextcord
from nextcord.ext import commands

from src.config.config import LOGS_CHANNEL_ID, MASSUNBAN_LOG_CHANNEL_ID, OWNER_IDS
from src.core.runtime_state import runtime_state
from src.database.database import db
from src.utils.embeds import alert_embed, error_embed, info_embed, success_embed, veka_embed
from src.utils.safety import admin_only, safe_command, safe_send, safe_slash_command

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


class CancelJobView(nextcord.ui.View):
    """Cancel button shown while a job is running."""

    def __init__(self, job_id: int, runner_id: int):
        super().__init__(timeout=300)
        self.job_id = job_id
        self.runner_id = runner_id

    async def interaction_check(self, interaction: nextcord.Interaction) -> bool:
        if interaction.user.id != self.runner_id:
            await interaction.response.send_message('Only the command runner can cancel.', ephemeral=True)
            return False
        return True

    @nextcord.ui.button(label='Cancel Job', style=nextcord.ButtonStyle.danger, emoji='\u23f9\ufe0f')
    async def cancel_button(self, _button: nextcord.ui.Button, interaction: nextcord.Interaction):
        self.stop()
        await interaction.response.defer()
        # Signal cancellation through the cog
        cog = interaction.client.get_cog('MassUnban')
        if cog:
            await cog._cancel_job(self.job_id, self.runner_id)

    async def on_timeout(self):
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


class MassUnban(commands.Cog):
    """Resumable bulk-unban with double confirmation, rate limiting, and per-user audit."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._active_jobs: dict[int, bool] = {}  # job_id -> cancelled flag
        self._rate_limit_count: dict[int, int] = {}  # job_id -> consecutive 429 count
        self._unban_interval: dict[int, float] = {}  # job_id -> current interval

    async def cog_load(self) -> None:
        """Resume incomplete jobs on startup."""
        asyncio.create_task(self._resume_incomplete_jobs())

    async def _resume_incomplete_jobs(self) -> None:
        """Wait for bot to be ready, then scan for resumable jobs."""
        await self.bot.wait_until_ready()
        if not runtime_state.db_available:
            logger.warning('DB unavailable — skipping mass unban resume')
            return
        try:
            # Resume active jobs
            jobs = await db.fetch(
                """SELECT id, guild_id, requested_by, status
                   FROM massunban_jobs
                   WHERE status IN ('running', 'retry_wait', 'paused')"""
            )
            for job in jobs:
                try:
                    logger.info('Resuming mass unban job %s (was %s)', job['id'], job['status'])
                    await db.execute(
                        "UPDATE massunban_jobs SET status = 'running' WHERE id = $1",
                        job['id'],
                    )
                    self._active_jobs[job['id']] = False
                    asyncio.create_task(self._execute_job(job['id'], resumed=True))
                except Exception:
                    logger.error('Failed to resume job %s', job['id'], exc_info=True)

            # Cancel orphaned pending/confirming jobs (bot restarted during confirmation)
            orphaned = await db.fetch(
                """SELECT id, guild_id, requested_by
                   FROM massunban_jobs
                   WHERE status IN ('pending', 'confirming')"""
            )
            for job in orphaned:
                try:
                    await db.execute(
                        "UPDATE massunban_jobs SET status = 'cancelled', completed_at = NOW() WHERE id = $1",
                        job['id'],
                    )
                    logger.info('Cancelled orphaned mass unban job %s (was %s)', job['id'], job.get('status'))
                    # Notify the original runner
                    runner = self.bot.get_user(job['requested_by'])
                    if runner:
                        embed = await info_embed(
                            title=f'\U0001f504 Mass Unban Job #{job["id"]} Cancelled',
                            description='Job was cancelled because the bot restarted during the confirmation phase.',
                            contributor_source=__name__,
                        )
                        try:
                            await runner.send(embed=embed)
                        except Exception:
                            pass
                except Exception:
                    logger.error('Failed to cancel orphaned job %s', job['id'], exc_info=True)
        except Exception:
            logger.error('Failed to scan for resumable mass unban jobs', exc_info=True)

    # ============================================================
    # Slash Commands
    # ============================================================

    @nextcord.slash_command(
        name='massunban',
        description='Bulk unban users with date-range filters',
    )
    async def massunban_group(self, interaction: nextcord.Interaction) -> None:
        embed = await info_embed(
            title='Mass Unban Commands',
            description=(
                '**Available subcommands:**\n\n'
                '\u2022 `/massunban run` \u2014 Start a mass unban\n'
                '\u2022 `/massunban status` \u2014 Check job status\n'
                '\u2022 `/massunban cancel` \u2014 Cancel a job\n'
                '\u2022 `/massunban recent` \u2014 View recent jobs'
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
    ) -> None:
        await self._start_massunban(interaction, start_datetime, end_datetime, banned_by, reason)

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
                '**`!massunban run <start> <end> [@mod] [reason]`** — Start a mass unban\n'
                '**`!massunban status <job_id>`** — Check job status\n'
                '**`!massunban cancel <job_id>`** — Cancel a job\n'
                '**`!massunban recent`** — List recent jobs\n\n'
                'Dates must be ISO format (e.g. `2024-01-01` or `2024-01-01T00:00:00`).'
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
        await self._start_massunban(ctx, start_datetime, end_datetime, banned_by, reason)

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
    ) -> None:
        guild = getattr(target, 'guild', None)
        if not guild:
            embed = await error_embed('No Guild', 'This command must be used in a server.', contributor_source=__name__)
            await safe_send(target, embed=embed, ephemeral=True)
            return

        user = target.user if isinstance(target, nextcord.Interaction) else target.author

        # Guard against concurrent jobs per guild
        if runtime_state.db_available:
            try:
                active = await db.fetchval(
                    """SELECT EXISTS(
                        SELECT 1 FROM massunban_jobs
                        WHERE guild_id = $1 AND status IN ('running', 'paused', 'retry_wait', 'confirming')
                    )""",
                    guild.id,
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
            except Exception:
                logger.warning('Failed to check for active mass unban jobs in guild %s', guild.id, exc_info=True)

        # Parse datetimes
        try:
            start_dt = datetime.fromisoformat(start_str).replace(tzinfo=UTC)
        except ValueError:
            embed = await error_embed(
                'Invalid Date',
                f'Could not parse start date: `{start_str}`\nUse ISO format (e.g. `2024-01-01` or `2024-01-01T00:00:00`).',
                contributor_source=__name__,
            )
            await safe_send(target, embed=embed, ephemeral=True)
            return

        try:
            end_dt = datetime.fromisoformat(end_str).replace(tzinfo=UTC)
        except ValueError:
            embed = await error_embed(
                'Invalid Date',
                f'Could not parse end date: `{end_str}`\nUse ISO format (e.g. `2024-12-31` or `2024-12-31T23:59:59`).',
                contributor_source=__name__,
            )
            await safe_send(target, embed=embed, ephemeral=True)
            return

        if start_dt >= end_dt:
            embed = await error_embed(
                'Invalid Range',
                'Start date must be before end date.',
                contributor_source=__name__,
            )
            await safe_send(target, embed=embed, ephemeral=True)
            return

        # Fetch all bans from Discord
        try:
            bans = [ban async for ban in guild.bans()]
        except (nextcord.Forbidden, nextcord.HTTPException):
            embed = await error_embed(
                'Missing Permission',
                'I need the **Ban Members** permission to list bans.',
                contributor_source=__name__,
            )
            await safe_send(target, embed=embed, ephemeral=True)
            return

        if not bans:
            embed = await info_embed(
                'No Bans',
                'There are no banned users in this server.',
                contributor_source=__name__,
            )
            await safe_send(target, embed=embed, ephemeral=True)
            return

        # Try to match bans against bot's audit log for date/moderator filtering
        matched_bans = []
        no_audit_count = 0
        audit_matched = 0

        # Fetch bot audit logs for ban actions in this guild
        audit_records = await self._fetch_audit_records(guild.id)

        for ban in bans:
            user_id = str(ban.user.id)
            # Check if we have audit data for this ban
            audit_record = audit_records.get(user_id)

            if audit_record:
                # Apply date range filter
                ban_time = audit_record.get('created_at')
                if ban_time:
                    if ban_time < start_dt or ban_time > end_dt:
                        continue
                # Apply banned_by filter
                if banned_by and audit_record.get('moderator_id') != str(banned_by.id):
                    continue
                audit_matched += 1
            else:
                # No audit data — include only if no filters are active
                no_audit_count += 1
                # If banned_by filter is set and we have no audit data, skip
                if banned_by:
                    continue

            matched_bans.append((ban, audit_record))

        if not matched_bans:
            embed = await info_embed(
                'No Matches',
                'No bans match your filters.',
                contributor_source=__name__,
            )
            if no_audit_count > 0 and banned_by:
                embed.add_field(
                    name='Note',
                    value=f'{no_audit_count} ban(s) have no audit history and were excluded because a moderator filter was set.',
                    inline=False,
                )
            await safe_send(target, embed=embed, ephemeral=True)
            return

        # Create job in DB
        try:
            job_id = await db.fetchval(
                """INSERT INTO massunban_jobs
                   (guild_id, requested_by, status, start_datetime, end_datetime, banned_by, reason, total_matched)
                   VALUES ($1, $2, 'pending', $3, $4, $5, $6, $7)
                   RETURNING id""",
                guild.id,
                user.id,
                start_dt,
                end_dt,
                banned_by.id if banned_by else None,
                reason or None,
                len(matched_bans),
            )
        except Exception:
            logger.error('Failed to create mass unban job', exc_info=True)
            embed = await error_embed('DB Error', 'Failed to create job record.', contributor_source=__name__)
            await safe_send(target, embed=embed, ephemeral=True)
            return

        # Insert job items
        items_data = []
        for ban, audit_record in matched_bans:
            items_data.append(
                (
                    job_id,
                    str(ban.user.id),
                    str(ban.user),
                    ban.reason,
                    int(audit_record['moderator_id']) if audit_record and audit_record.get('moderator_id') else None,
                )
            )
        try:
            await db.execute_many(
                """INSERT INTO massunban_job_items
                   (job_id, target_user_id, target_username, ban_reason, banned_by)
                   VALUES ($1, $2, $3, $4, $5)""",
                items_data,
            )
        except Exception:
            logger.error('Failed to insert mass unban items for job %s', job_id, exc_info=True)
            embed = await error_embed('DB Error', 'Failed to create job items.', contributor_source=__name__)
            await safe_send(target, embed=embed, ephemeral=True)
            return

        # Build preview embed
        embed = await self._build_preview_embed(
            job_id, len(matched_bans), start_dt, end_dt, banned_by, reason, no_audit_count
        )

        # First confirmation
        view = ConfirmFirstView(job_id=job_id, runner_id=user.id)
        sent = await _safe_send_view(target, embed=embed, view=view, ephemeral=True)

        if not sent:
            # Send failed — clean up DB record
            try:
                await db.execute("UPDATE massunban_jobs SET status = 'failed' WHERE id = $1", job_id)
            except Exception:
                logger.error('Failed to clean up job %s after send failure', job_id, exc_info=True)
            embed = await error_embed(
                'Send Failed',
                'Could not deliver the confirmation message. Please try again.',
                contributor_source=__name__,
            )
            await safe_send(target, embed=embed, ephemeral=True)
            return

        try:
            await db.execute("UPDATE massunban_jobs SET status = 'confirming' WHERE id = $1", job_id)
        except Exception:
            logger.warning('Failed to update job %s status to confirming', job_id, exc_info=True)

        # Wait for first confirmation
        await view.wait()
        if view.result is not True:
            try:
                await db.execute("UPDATE massunban_jobs SET status = 'cancelled' WHERE id = $1", job_id)
            except Exception:
                logger.warning('Failed to cancel job %s after timeout/decline', job_id, exc_info=True)
            if view.result is None:
                embed = await info_embed(
                    'Cancelled',
                    'Confirmation timed out. Job cancelled.',
                    contributor_source=__name__,
                )
            else:
                embed = await info_embed(
                    'Cancelled',
                    'Job cancelled by operator.',
                    contributor_source=__name__,
                )
            await safe_send(target, embed=embed, ephemeral=True)
            return

        # Second confirmation
        embed2 = await veka_embed(
            title=f'\u26a1 Final Confirmation — Unban {len(matched_bans)} Users',
            description=(
                f'You are about to unban **{len(matched_bans)}** users.\n\n'
                f'This action is **resumable** if interrupted.\n'
                f'Results will be logged to the audit channel.\n\n'
                f'Click **Confirm Unban** to proceed.'
            ),
            contributor_source=__name__,
            user=user,
            guild=guild,
        )
        view2 = ConfirmSecondView(job_id=job_id, runner_id=user.id, count=len(matched_bans))
        await _safe_send_view(target, embed=embed2, view=view2, ephemeral=True)

        await view2.wait()
        if view2.result is not True:
            try:
                await db.execute("UPDATE massunban_jobs SET status = 'cancelled' WHERE id = $1", job_id)
            except Exception:
                logger.warning('Failed to cancel job %s after second timeout/decline', job_id, exc_info=True)
            if view2.result is None:
                embed = await info_embed(
                    'Cancelled', 'Confirmation timed out. Job cancelled.', contributor_source=__name__
                )
            else:
                embed = await info_embed('Cancelled', 'Job cancelled by operator.', contributor_source=__name__)
            await safe_send(target, embed=embed, ephemeral=True)
            return

        # Start execution
        try:
            await db.execute(
                "UPDATE massunban_jobs SET status = 'running', started_at = NOW() WHERE id = $1",
                job_id,
            )
        except Exception:
            logger.error('Failed to start job %s', job_id, exc_info=True)
            embed = await error_embed('DB Error', 'Failed to start job execution.', contributor_source=__name__)
            await safe_send(target, embed=embed, ephemeral=True)
            return

        # Notify log channel
        await self._log_job_event(
            guild, 'Job Started', f'Job #{job_id} started by {user.mention}', f'{len(matched_bans)} users to process'
        )

        # Execute
        self._active_jobs[job_id] = False
        self._rate_limit_count[job_id] = 0
        self._unban_interval[job_id] = BASE_UNBAN_INTERVAL
        await self._execute_job(job_id, resumed=False)

    # ============================================================
    # Core Logic — Execute Job
    # ============================================================

    async def _execute_job(self, job_id: int, *, resumed: bool = False) -> None:
        """Sequential unban worker with rate limiting."""
        try:
            job = await db.fetch_one('SELECT * FROM massunban_jobs WHERE id = $1', job_id)
            if not job:
                return

            guild = self.bot.get_guild(job['guild_id'])
            if not guild:
                await db.execute("UPDATE massunban_jobs SET status = 'failed' WHERE id = $1", job_id)
                return

            # Get pending items
            items = await db.fetch(
                """SELECT * FROM massunban_job_items
                   WHERE job_id = $1 AND status = 'pending'
                   ORDER BY id ASC""",
                job_id,
            )

            if not items:
                await self._complete_job(job_id, guild)
                return

            runner = self.bot.get_user(job['requested_by'])
            interval = self._unban_interval.get(job_id, BASE_UNBAN_INTERVAL)

            if resumed and runner:
                embed = await info_embed(
                    title=f'\U0001f504 Mass Unban Resumed — Job #{job_id}',
                    description=f'Resuming from where we left off. **{len(items)}** users remaining.',
                    contributor_source=__name__,
                )
                try:
                    await runner.send(embed=embed)
                except Exception:
                    pass

            for item in items:
                # Check cancellation
                if self._active_jobs.get(job_id, True):
                    try:
                        await db.execute("UPDATE massunban_jobs SET status = 'cancelled' WHERE id = $1", job_id)
                    except Exception:
                        logger.warning('Failed to mark job %s as cancelled', job_id, exc_info=True)
                    await self._log_job_event(guild, 'Job Cancelled', f'Job #{job_id} was cancelled by operator.', '')
                    return

                # Check DB availability before processing
                if not runtime_state.db_available:
                    logger.warning('DB unavailable — pausing job %s', job_id)
                    try:
                        await db.execute(
                            "UPDATE massunban_jobs SET status = 'paused' WHERE id = $1",
                            job_id,
                        )
                    except Exception:
                        logger.error('Failed to pause job %s due to DB outage', job_id, exc_info=True)
                    await self._log_job_event(guild, 'Job Paused', f'Job #{job_id} paused — DB unavailable.', '')
                    return

                result = await self._process_unban_item(guild, item, job)

                # Update job progress
                await self._update_job_progress(job_id, item, result)

                # Per-user audit log
                try:
                    await self._log_per_user(guild, job_id, result)
                except Exception:
                    logger.warning(
                        'Failed to log per-user result for job %s user %s', job_id, result.get('user_id'), exc_info=True
                    )

                # Throttle
                await asyncio.sleep(interval)

            # Complete
            await self._complete_job(job_id, guild)

        except Exception:
            logger.error('Fatal error in mass unban job %s', job_id, exc_info=True)
            try:
                await db.execute(
                    """UPDATE massunban_jobs
                       SET status = 'failed', completed_at = NOW(),
                           metadata = metadata || '{"fatal_error": true}'::jsonb
                       WHERE id = $1""",
                    job_id,
                )
            except Exception:
                logger.error('Failed to mark job %s as failed after fatal error', job_id, exc_info=True)
            # Clean up in-memory state
            self._active_jobs.pop(job_id, None)
            self._rate_limit_count.pop(job_id, None)
            self._unban_interval.pop(job_id, None)

    async def _process_unban_item(self, guild: nextcord.Guild, item: dict, job: dict) -> dict[str, Any]:
        """Process a single unban. Returns result dict."""
        user_id = int(item['target_user_id'])
        result: dict[str, Any] = {
            'user_id': user_id,
            'username': item['target_username'],
            'status': 'pending',
            'dm_status': 'skipped',
        }

        # Check if already unbanned
        try:
            await guild.fetch_ban(nextcord.Object(user_id))
        except nextcord.NotFound:
            # Already unbanned
            result['status'] = 'skipped'
            result['failure_reason'] = 'Already unbanned'
            return result
        except nextcord.Forbidden:
            result['status'] = 'failed'
            result['failure_reason'] = 'Missing Ban Members permission'
            return result

        # Attempt unban
        try:
            reason_parts = ['Mass unban']
            actor_id = job['requested_by']
            if actor_id:
                reason_parts.append(f'by {actor_id}')
            if job.get('reason'):
                reason_parts.append(f'— {job["reason"]}')
            unban_reason = ' '.join(reason_parts)

            await guild.unban(
                nextcord.Object(id=user_id),
                reason=unban_reason,
            )
            result['status'] = 'success'
            result['unbanned_at'] = datetime.now(UTC)
        except nextcord.HTTPException as exc:
            if exc.status == 429:
                # Rate limited — persist and pause
                retry_after: float = float(RATE_LIMIT_COOLDOWN)
                if exc.response and hasattr(exc.response, 'headers'):
                    ra_header = exc.response.headers.get('Retry-After')
                    if ra_header:
                        try:
                            retry_after = float(ra_header)
                        except ValueError:
                            pass
                result['status'] = 'failed'
                result['failure_reason'] = f'Rate limited (retry_after={retry_after}s)'
                result['retry_after'] = retry_after
                result['rate_limit'] = True
                return result
            result['status'] = 'failed'
            result['failure_reason'] = f'Discord API error: {exc}'
        except nextcord.Forbidden:
            result['status'] = 'failed'
            result['failure_reason'] = 'Missing Ban Members permission'
        except Exception as exc:
            result['status'] = 'failed'
            result['failure_reason'] = str(exc)

        # DM attempt (only on success)
        if result['status'] == 'success':
            dm_result = await self._send_dm(guild, user_id)
            result['dm_status'] = dm_result['status']
            result['dm_failure_reason'] = dm_result.get('reason')

        return result

    async def _send_dm(self, guild: nextcord.Guild, user_id: int) -> dict[str, str]:
        """Attempt to DM an unbanned user. Returns dm status."""
        try:
            user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
            dm_message = DM_APOLOGY_TEMPLATE.format(guild_name=guild.name)
            await user.send(dm_message)
            return {'status': 'sent'}
        except (nextcord.Forbidden, nextcord.NotFound):
            return {'status': 'failed', 'reason': 'User DMs disabled or user not found'}
        except Exception as exc:
            return {'status': 'failed', 'reason': str(exc)}

    async def _update_job_progress(self, job_id: int, item: dict, result: dict) -> None:
        """Persist progress after each unban."""
        # 1. Update item record
        try:
            await db.execute(
                """UPDATE massunban_job_items
                   SET status = $1, failure_reason = $2, unbanned_at = $3,
                       dm_status = $4, dm_failure_reason = $5
                   WHERE id = $6""",
                result['status'],
                result.get('failure_reason'),
                result.get('unbanned_at'),
                result.get('dm_status', 'skipped'),
                result.get('dm_failure_reason'),
                item['id'],
            )
        except Exception:
            logger.warning('Failed to update item %s for job %s', item['id'], job_id, exc_info=True)

        # 2. Update job counters
        _VALID_COUNTER_COLS = {'total_succeeded', 'total_failed', 'total_skipped'}
        counter_col = {
            'success': 'total_succeeded',
            'failed': 'total_failed',
            'skipped': 'total_skipped',
        }.get(result['status'])
        if counter_col and counter_col in _VALID_COUNTER_COLS:
            try:
                await db.execute(
                    f"""UPDATE massunban_jobs
                        SET {counter_col} = {counter_col} + 1,
                            total_attempted = total_attempted + 1,
                            last_processed_user_id = $1
                        WHERE id = $2""",
                    str(result['user_id']),
                    job_id,
                )
            except Exception:
                logger.warning('Failed to update counters for job %s', job_id, exc_info=True)

        # 3. Handle rate limit pause (separate block — includes scheduling)
        if result.get('rate_limit'):
            await self._handle_rate_limit_pause(job_id, result)

    async def _handle_rate_limit_pause(self, job_id: int, result: dict) -> None:
        """Handle rate limit: persist pause state, notify, and schedule resume."""
        retry_after_secs = max(1.0, float(result.get('retry_after', RATE_LIMIT_COOLDOWN)))

        # Persist pause state
        try:
            retry_at = datetime.now(UTC) + timedelta(seconds=retry_after_secs)
            await db.execute(
                "UPDATE massunban_jobs SET status = 'retry_wait', retry_after = $1 WHERE id = $2",
                retry_at,
                job_id,
            )
        except Exception:
            logger.error('Failed to persist rate limit pause for job %s', job_id, exc_info=True)

        # Update in-memory backoff
        self._rate_limit_count[job_id] = self._rate_limit_count.get(job_id, 0) + 1
        if self._rate_limit_count[job_id] >= PAUSE_THRESHOLD:
            self._unban_interval[job_id] = min(
                self._unban_interval.get(job_id, BASE_UNBAN_INTERVAL) * 2,
                BASE_UNBAN_INTERVAL * MAX_BACKOFF_MULTIPLIER,
            )

        # Notify log channel
        try:
            job = await db.fetch_one('SELECT * FROM massunban_jobs WHERE id = $1', job_id)
            guild = self.bot.get_guild(job['guild_id']) if job else None
            if guild:
                await self._log_job_event(
                    guild,
                    'Rate Limited',
                    f'Job #{job_id} paused due to rate limit.',
                    f'Retry after: {retry_after_secs:.0f}s',
                )
            runner = self.bot.get_user(job['requested_by']) if job else None
            if runner:
                embed = await alert_embed(
                    title=f'\u23f1\ufe0f Rate Limited — Job #{job_id}',
                    description=f'Job paused due to Discord rate limit.\nWill retry in **{retry_after_secs:.0f}** seconds.',
                    severity='WARN',
                )
                try:
                    await runner.send(embed=embed)
                except Exception:
                    pass
        except Exception:
            logger.warning('Failed to send rate limit notification for job %s', job_id, exc_info=True)

        # Schedule resume using asyncio task (not call_later)
        asyncio.create_task(self._scheduled_resume(job_id, retry_after_secs))

    async def _scheduled_resume(self, job_id: int, delay: float) -> None:
        """Wait then resume a rate-limited job, checking for cancellation first."""
        await asyncio.sleep(delay + 1)
        # Check if job was cancelled while waiting
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
            # asyncpg execute returns e.g. 'UPDATE 1' or 'UPDATE 0'
            if result == 'UPDATE 0':
                logger.info('Job %s no longer resumable — skipping', job_id)
                return
            # Only set active if not already cancelled
            if not self._active_jobs.get(job_id, True):
                self._active_jobs[job_id] = False
            self._rate_limit_count.setdefault(job_id, 0)
            self._unban_interval.setdefault(job_id, BASE_UNBAN_INTERVAL)
            await self._execute_job(job_id, resumed=True)
        except Exception:
            logger.error('Failed to resume mass unban job %s', job_id, exc_info=True)

    async def _complete_job(self, job_id: int, guild: nextcord.Guild) -> None:
        """Mark job as completed and send summary."""
        try:
            job = await db.fetch_one('SELECT * FROM massunban_jobs WHERE id = $1', job_id)
            if not job:
                return

            await db.execute(
                "UPDATE massunban_jobs SET status = 'completed', completed_at = NOW() WHERE id = $1",
                job_id,
            )

            duration = ''
            if job.get('started_at'):
                delta = datetime.now(UTC) - job['started_at']
                mins, secs = divmod(int(delta.total_seconds()), 60)
                duration = f'{mins}m {secs}s' if mins else f'{secs}s'

            runner = self.bot.get_user(job['requested_by'])

            # Summary embed
            embed = await success_embed(
                title=f'\u2705 Mass Unban Complete — Job #{job_id}',
                description=(
                    f'**Duration:** {duration}\n'
                    f'**Matched:** {job["total_matched"]}\n'
                    f'\u2705 **Succeeded:** {job["total_succeeded"]}\n'
                    f'\u23ed\ufe0f **Skipped:** {job["total_skipped"]} (already unbanned)\n'
                    f'\u274c **Failed:** {job["total_failed"]}\n'
                    f'**Rate limits encountered:** {"Yes" if self._rate_limit_count.get(job_id, 0) > 0 else "No"}'
                ),
                contributor_source=__name__,
            )

            if runner:
                try:
                    await runner.send(embed=embed)
                except Exception:
                    pass

            await self._log_job_event(guild, 'Job Completed', f'Job #{job_id} finished successfully.', '')

            # Cleanup
            self._active_jobs.pop(job_id, None)
            self._rate_limit_count.pop(job_id, None)
            self._unban_interval.pop(job_id, None)

        except Exception:
            logger.error('Failed to complete job %s', job_id, exc_info=True)

    async def _build_preview_embed(
        self,
        job_id: int,
        ban_count: int,
        start_dt: datetime,
        end_dt: datetime,
        banned_by: nextcord.Member | None,
        reason: str,
        no_audit_count: int,
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
            embed.add_field(name='Reason', value=reason, inline=False)
        if no_audit_count > 0:
            embed.add_field(
                name='Note',
                value=f'{no_audit_count} ban(s) have no audit history and will be included.',
                inline=False,
            )
        embed.add_field(
            name='Confirm',
            value='This action will unban all matched users. Double confirmation required.',
            inline=False,
        )
        return embed

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
        job = await db.fetch_one('SELECT * FROM massunban_jobs WHERE id = $1', job_id)
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
            await self._log_job_event(guild, 'Job Cancelled', f'Job #{job_id} cancelled by {user.mention}.', '')

    # ============================================================
    # Status / Recent
    # ============================================================

    async def _show_status(self, target: commands.Context | nextcord.Interaction, job_id: int) -> None:
        job = await db.fetch_one('SELECT * FROM massunban_jobs WHERE id = $1', job_id)
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
    # Logging Helpers
    # ============================================================

    async def _log_job_event(self, _guild: nextcord.Guild, title: str, description: str, detail: str) -> None:
        """Send a job event notice to the log channel."""
        log_channel = self.bot.get_channel(LOGS_CHANNEL_ID)
        if not log_channel:
            return
        try:
            embed = await veka_embed(
                title=f'\U0001f4cb Mass Unban — {title}',
                description=description + (f'\n{detail}' if detail else ''),
                contributor_source=__name__,
            )
            await log_channel.send(embed=embed)
        except Exception:
            logger.debug('Failed to send mass unban log to channel', exc_info=True)

    async def _log_per_user(self, guild: nextcord.Guild, job_id: int, result: dict) -> None:
        """Send per-user unban result to the log channel."""
        log_channel_id = MASSUNBAN_LOG_CHANNEL_ID or LOGS_CHANNEL_ID
        log_channel = self.bot.get_channel(log_channel_id)
        if not log_channel:
            return

        status_emoji = {'success': '\u2705', 'failed': '\u274c', 'skipped': '\u23ed\ufe0f'}.get(
            result['status'], '\u2753'
        )
        dm_emoji = {'sent': '\u2705', 'failed': '\u274c', 'skipped': '\u23ed\ufe0f'}.get(
            result.get('dm_status', 'skipped'), '\u2753'
        )

        lines = [
            f'**Target:** <@{result["user_id"]}> (`{result["user_id"]}`)',
            f'**Result:** {status_emoji} {result["status"].title()}',
        ]
        if result.get('failure_reason'):
            lines.append(f'**Reason:** {result["failure_reason"]}')
        if result.get('unbanned_at'):
            lines.append(f'**Unbanned at:** {_format_dt(result["unbanned_at"], "T")}')
        lines.append(f'**DM:** {dm_emoji} {result.get("dm_status", "skipped").title()}')
        if result.get('dm_failure_reason'):
            lines.append(f'**DM Note:** {result["dm_failure_reason"]}')
            lines.append(f'```{DM_APOLOGY_TEMPLATE.format(guild_name=guild.name)}```')

        try:
            embed = await veka_embed(
                title=f'\U0001f4cb Job #{job_id} — Unban Result',
                description='\n'.join(lines),
                contributor_source=__name__,
            )
            await log_channel.send(embed=embed)
        except Exception:
            pass


# ============================================================
# Setup
# ============================================================


def setup(bot: commands.Bot) -> None:
    bot.add_cog(MassUnban(bot))
    logger.info('Loaded cog: src.cogs.admin.massunban')
