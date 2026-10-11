"""
Chat Export Cog — exports Discord channel history to .txt files.

Owner-only in external servers. Designed with stability as top priority:
- Progressive rate limiting to avoid Discord API limits
- Health checks pause export if bot is degraded
- Cooperative yielding to let main server commands execute
- Max 30-minute duration
- Cancellable via /exportstop
"""

import asyncio
import io
import logging
import random
import tempfile
import time
from datetime import UTC, datetime
from typing import BinaryIO, cast

import nextcord
from nextcord.ext import commands

from src.core.lifecycle import spawn
from src.core.runtime_state import runtime_state
from src.services.export_stream import ExportContent, file_io, utf8_chunks
from src.utils.embeds import error_embed, info_embed, success_embed
from src.utils.guild_gate import owner_in_external_only
from src.utils.outbound import outbound
from src.utils.safety import _is_admin_user, admin_only, safe_send, safe_slash_command

logger = logging.getLogger('VEKA.external.export')

# ============================================================
# Rate limiting constants
# ============================================================
BASE_DELAY = 1.5  # seconds between batches
MAX_DELAY = 5.0
DELAY_INCREMENT = 0.5
BATCHES_BEFORE_SLOWDOWN = 5
RANDOM_PAUSE_EVERY_MIN = 3
RANDOM_PAUSE_EVERY_MAX = 5
RANDOM_PAUSE_DURATION_MIN = 5
RANDOM_PAUSE_DURATION_MAX = 15
MAX_EXPORT_DURATION = 1800  # 30 minutes
BATCH_SIZE = 100  # messages per fetch batch
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB (safe margin under Discord's 25MB limit)
CPU_PAUSE_THRESHOLD = 90.0  # pause if CPU above this %
MAX_CHANNEL_BYTES = 128 * 1024 * 1024  # bounded temp disk use; stop honestly on overflow
MAX_CHANNEL_DURATION = 300  # one channel may not monopolise the 30-minute run


class ChatExport(commands.Cog):
    """Chat history export with rate limiting and stability safeguards."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._export_running = False
        self._cancel_export = False
        self._export_progress: dict = {}
        self._export_owner_id: int | None = None
        self._export_guild_id: int | None = None
        self._export_task: asyncio.Task | None = None
        self._status_key = ''

    def _claim_export(self, owner_id: int, guild_id: int) -> bool:
        # No await between checking and reserving: concurrent commands cannot both win.
        if self._export_running:
            return False
        self._export_running = True
        self._cancel_export = False
        self._export_owner_id = owner_id
        self._export_guild_id = guild_id
        return True

    def cog_unload(self):
        if self._export_task is not None:
            self._export_task.cancel()

    # ============================================================
    # Health check
    # ============================================================

    def _is_healthy(self) -> bool:
        """Check if bot is healthy enough to continue export."""
        if not runtime_state.db_available:
            return False
        if runtime_state.failed_cogs:
            return False
        try:
            import psutil

            if psutil.cpu_percent(interval=None) > CPU_PAUSE_THRESHOLD:
                logger.warning('Export paused: CPU above %s%%', CPU_PAUSE_THRESHOLD)
                return False
        except ImportError:
            pass
        return True

    @staticmethod
    def _can_read(channel: nextcord.TextChannel, owner: nextcord.Member) -> bool:
        guild = channel.guild
        current = guild.get_member(owner.id)
        if current is None or guild.me is None:
            return False
        mine = channel.permissions_for(guild.me)
        theirs = channel.permissions_for(current)
        return mine.view_channel and mine.read_message_history and theirs.view_channel and theirs.read_message_history

    def _update_progress(self, **kwargs):
        """Update export progress in runtime_state for /botinfo visibility."""
        self._export_progress.update(kwargs)
        runtime_state.alert_state_cache['export_active'] = self._export_running
        if self._export_running:
            completed = self._export_progress.get('completed_channels', 0)
            total = self._export_progress.get('total_channels', 0)
            messages = self._export_progress.get('total_messages', 0)
            runtime_state.alert_state_cache['export_progress'] = f'{completed}/{total} channels, {messages:,} messages'
        else:
            runtime_state.alert_state_cache.pop('export_active', None)
            runtime_state.alert_state_cache.pop('export_progress', None)

    # ============================================================
    # Message formatting
    # ============================================================

    def _format_message(self, msg: nextcord.Message) -> str:
        """Format a single message for the .txt export."""
        timestamp = msg.created_at.strftime('%Y-%m-%d %H:%M:%S')
        author = f'{msg.author.name}#{msg.author.discriminator}'
        content = msg.content or ''

        # Handle attachments
        attachments = ''
        if msg.attachments:
            att_parts = [f'[Attachment: {a.filename}]' for a in msg.attachments]
            attachments = ' '.join(att_parts)

        # Handle embeds
        embeds = ''
        if msg.embeds:
            embed_parts = []
            for e in msg.embeds:
                title = e.title or 'Embed'
                desc = e.description or ''
                embed_parts.append(f'[Embed: {title} - {desc[:100]}]')
            embeds = ' '.join(embed_parts)

        parts = [f'[{timestamp}] {author}: {content}']
        if attachments:
            parts.append(f'  {attachments}')
        if embeds:
            parts.append(f'  {embeds}')

        return '\n'.join(parts)

    def _build_channel_header(self, channel: nextcord.TextChannel, msg_count: int, date_range: str) -> str:
        """Build the header for a channel export file."""
        return (
            f'=== Channel: #{channel.name} (ID: {channel.id}) ===\n'
            f'Messages: {msg_count:,} | Exported: {datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")}\n'
            f'Date range: {date_range}\n'
            f'===\n\n'
        )

    # ============================================================
    # Core export logic
    # ============================================================

    async def _export_channel(
        self,
        channel: nextcord.TextChannel,
        owner: nextcord.Member,
        limit: int | None = None,
    ) -> tuple[ExportContent | None, int]:
        """Stream history into bounded temporary storage; never retain Discord Message objects."""
        body = cast(BinaryIO, tempfile.SpooledTemporaryFile(max_size=1024 * 1024, mode='w+b'))
        pending: list[bytes] = []
        count = size = 0
        first_date = last_date = ''
        transferred = False
        delay = BASE_DELAY
        batches_since_slowdown = 0
        pauses_since_random = 0

        try:
            async for msg in channel.history(limit=limit, oldest_first=True):
                if self._cancel_export:
                    return None, 0
                formatted = (self._format_message(msg) + '\n').encode('utf-8')
                size += len(formatted)
                if size > MAX_CHANNEL_BYTES:
                    logger.warning('Channel %s exceeds the export storage limit; stopping', channel.id)
                    self._cancel_export = True
                    return None, 0
                pending.append(formatted)
                count += 1
                last_date = msg.created_at.strftime('%Y-%m-%d')
                first_date = first_date or last_date

                # Flush at most one message batch at a time; disk I/O runs off the event loop.
                if count % BATCH_SIZE == 0:
                    await file_io(body.write, b''.join(pending))
                    pending.clear()
                    if not self._can_read(channel, owner):
                        self._cancel_export = True
                        return None, 0
                    # Health check
                    if not self._is_healthy():
                        logger.info('Export paused for channel %s — waiting for health recovery', channel.id)
                        while not self._is_healthy():
                            await asyncio.sleep(10)
                            if self._cancel_export:
                                return None, 0
                        logger.info('Health recovered — resuming export for channel %s', channel.id)

                    # Rate limiting
                    batches_since_slowdown += 1
                    pauses_since_random += 1

                    # Progressive slowdown
                    if batches_since_slowdown >= BATCHES_BEFORE_SLOWDOWN:
                        delay = min(delay + DELAY_INCREMENT, MAX_DELAY)
                        batches_since_slowdown = 0

                    # Random pause
                    if pauses_since_random >= random.randint(RANDOM_PAUSE_EVERY_MIN, RANDOM_PAUSE_EVERY_MAX):
                        pause = random.uniform(RANDOM_PAUSE_DURATION_MIN, RANDOM_PAUSE_DURATION_MAX)
                        logger.info('Random pause: %.1fs in channel %s', pause, channel.name)
                        await asyncio.sleep(pause)
                        pauses_since_random = 0

                    await asyncio.sleep(delay)

                    # Yield to main server
                    await asyncio.sleep(0)

                    if self._cancel_export:
                        return None, 0

            if not count:
                return None, 0
            if pending:
                await file_io(body.write, b''.join(pending))
            await file_io(body.seek, 0)
            date_range = f'{first_date} to {last_date}' if first_date != last_date else first_date
            header = self._build_channel_header(channel, count, date_range).encode('utf-8')
            transferred = True
            return ExportContent(body, header, size), count
        except nextcord.Forbidden:
            logger.warning('No access to channel %s', channel.name)
            self._cancel_export = True
            return None, 0
        except Exception as exc:
            logger.error('Error exporting channel %s: %s', channel.name, type(exc).__name__)
            self._cancel_export = True
            return None, 0
        finally:
            if not transferred:
                body.close()

    async def _send_file_dm(
        self,
        owner: nextcord.Member,
        filename: str,
        content: str | ExportContent,
        *,
        channel: nextcord.TextChannel | None = None,
    ) -> bool:
        """Read at most one attachment's bytes at a time; abort on permission or delivery failure."""
        stream = io.BytesIO(content.encode('utf-8')) if isinstance(content, str) else content
        size = len(stream.getbuffer()) if isinstance(stream, io.BytesIO) else stream.size
        part_num = 0
        try:
            async for chunk in utf8_chunks(stream, MAX_FILE_SIZE):
                if self._cancel_export or (channel is not None and not self._can_read(channel, owner)):
                    return False
                part_num += 1
                name = filename if size <= MAX_FILE_SIZE else f'{filename.removesuffix(".txt")}_part{part_num}.txt'
                file = nextcord.File(io.BytesIO(chunk), filename=name)
                try:
                    outcome = await outbound.dm(
                        owner,
                        kind='export_file',
                        file=file,
                        essential=True,
                        dedupe_key=f'{self._status_key}:{filename}:{part_num}',
                    )
                finally:
                    file.close()
                if not outcome.ok:
                    return False
                if size > MAX_FILE_SIZE:
                    await asyncio.sleep(1)
            return part_num > 0
        except Exception as exc:
            logger.error('Failed to send file %s via DM: %s', filename, type(exc).__name__)
            return False
        finally:
            stream.close()

    async def _run_export(
        self,
        interaction: nextcord.Interaction,
        channels: list[nextcord.TextChannel],
        limit: int | None,
    ):
        """Always release export state, including on errors, cancellation, and reload."""
        try:
            await self._perform_export(interaction, channels, limit)
        finally:
            self._export_running = False
            self._cancel_export = False
            self._export_owner_id = None
            self._export_guild_id = None
            self._export_task = None
            self._update_progress()
            if self._status_key:
                outbound.forget_status(self._status_key)
                self._status_key = ''

    async def _perform_export(
        self,
        interaction: nextcord.Interaction,
        channels: list[nextcord.TextChannel],
        limit: int | None,
    ):
        """Background export task."""
        owner = interaction.user
        if not isinstance(owner, nextcord.Member):
            logger.warning('Export cancelled: owner is not a guild member')
            return
        total_channels = len(channels)
        completed = 0
        total_messages = 0
        start_time = time.monotonic()
        exported_files = []

        self._update_progress(
            total_channels=total_channels,
            completed_channels=0,
            total_messages=0,
            started_at=start_time,
        )

        self._status_key = f'export:{owner.id}:{time.monotonic_ns()}'
        initial = await outbound.upsert_status(
            self._status_key,
            owner,
            kind='export_progress',
            content=f'Starting export of {total_channels} channel(s). Files arrive here. Use `/exportstop` to cancel.',
        )
        if not initial.ok:
            logger.warning('Export stopped: unable to deliver requested export to owner')
            return

        for channel in channels:
            if self._cancel_export:
                break

            # Time check
            elapsed = time.monotonic() - start_time
            if elapsed > MAX_EXPORT_DURATION:
                logger.warning('Export max duration reached (%ds)', MAX_EXPORT_DURATION)
                self._cancel_export = True
                break

            if not self._can_read(channel, owner):
                self._cancel_export = True
                break
            logger.info('Exporting channel: %s (%d/%d)', channel.name, completed + 1, total_channels)

            try:
                content, msg_count = await asyncio.wait_for(
                    self._export_channel(channel, owner, limit),
                    timeout=min(MAX_CHANNEL_DURATION, MAX_EXPORT_DURATION - elapsed),
                )
            except TimeoutError:
                self._cancel_export = True
                break

            if content and msg_count > 0:
                filename = f'{channel.name}_{channel.id}.txt'
                try:
                    success = await asyncio.wait_for(
                        self._send_file_dm(owner, filename, content, channel=channel),
                        timeout=max(0, MAX_EXPORT_DURATION - (time.monotonic() - start_time)),
                    )
                except TimeoutError:
                    self._cancel_export = True
                    break
                finally:
                    if isinstance(content, ExportContent):
                        content.close()

                if success:
                    exported_files.append(channel.name)
                    completed += 1
                    total_messages += msg_count

                    self._update_progress(
                        completed_channels=completed,
                        total_messages=total_messages,
                        current_channel=channel.name,
                    )

                    progress = await outbound.upsert_status(
                        self._status_key,
                        owner,
                        kind='export_progress',
                        content=f'{completed}/{total_channels} channels exported; {total_messages:,} messages.',
                    )
                    if not progress.ok:
                        self._cancel_export = True
                        break
                else:
                    logger.warning('Failed to send file for channel %s; stopping export', channel.name)
                    self._cancel_export = True
                    break
            else:
                logger.info('Channel %s had no accessible messages', channel.name)

            # Yield between channels
            await asyncio.sleep(0)

        # Keep the export slot occupied until the completion summary is sent.
        self._update_progress()

        duration = time.monotonic() - start_time
        duration_text = f'{int(duration // 60)}m {int(duration % 60)}s'

        status = 'cancelled' if self._cancel_export else 'complete'
        await outbound.upsert_status(
            self._status_key,
            owner,
            kind='export_progress',
            content=f'Export {status}! {completed}/{total_channels} channels, '
            f'{total_messages:,} messages. Duration: {duration_text}.',
        )

        logger.info(
            'Export %s: %d/%d channels, %d messages, %s',
            status,
            completed,
            total_channels,
            total_messages,
            duration_text,
        )

    # ============================================================
    # Commands
    # ============================================================

    @nextcord.slash_command(
        name='exportchat',
        description='Export chat history to .txt files (admins; owner only in external servers)',
        contexts=[nextcord.InteractionContextType.guild],
        default_member_permissions=nextcord.Permissions(administrator=True),
    )
    @owner_in_external_only()
    @admin_only()
    @safe_slash_command()
    async def exportchat(
        self,
        interaction: nextcord.Interaction,
        channel: nextcord.TextChannel | None = nextcord.SlashOption(
            description='Specific channel to export (omit for all text channels)', required=False
        ),
        limit: int | None = nextcord.SlashOption(description='Max messages per channel (omit for all)', required=False),
    ):
        """Export Discord channel history to .txt files."""
        # Check if export already running
        if self._export_running:
            embed = await error_embed(
                title='Export Already Running',
                description='An export is already in progress. Use `/exportstop` to cancel it first.',
                contributor_source=__name__,
                user=interaction.user,
                guild=interaction.guild,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        # Health check
        if not self._is_healthy():
            embed = await error_embed(
                title='Bot Degraded',
                description='The bot is currently in degraded mode. Export cancelled for stability. Try again later.',
                contributor_source=__name__,
                user=interaction.user,
                guild=interaction.guild,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        guild = interaction.guild
        if not guild:
            embed = await error_embed(
                title='Error',
                description='This command can only be used in a server.',
                contributor_source=__name__,
                user=interaction.user,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        # Only export channels that BOTH the bot and the invoker can read (audit C-02).
        invoker = (
            interaction.user if isinstance(interaction.user, nextcord.Member) else guild.get_member(interaction.user.id)
        )

        def _readable(c: nextcord.TextChannel) -> bool:
            if invoker is None:
                return False
            mine = c.permissions_for(guild.me)
            theirs = c.permissions_for(invoker)
            return (
                mine.view_channel and mine.read_message_history and theirs.view_channel and theirs.read_message_history
            )

        candidates = [channel] if channel else list(guild.text_channels)
        channels = [c for c in candidates if c.guild.id == guild.id and _readable(c)]

        if not channels:
            embed = await error_embed(
                title='No Channels',
                description='No accessible text channels found to export.',
                contributor_source=__name__,
                user=interaction.user,
                guild=interaction.guild,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        if limit is not None and limit <= 0:
            await safe_send(interaction, content='Message limit must be positive.', ephemeral=True)
            return
        if not self._claim_export(interaction.user.id, guild.id):
            await safe_send(interaction, content='Another export has already started.', ephemeral=True)
            return
        try:
            # Reserve before this first await, not after the acknowledgement.
            await interaction.response.defer(ephemeral=True)
            embed = await success_embed(
                title='Export Starting',
                description=(
                    f'Exporting {len(channels)} channel(s). '
                    f'Check your DMs for progress updates and files.\n'
                    f'Use `/exportstop` to cancel.'
                ),
                contributor_source=__name__,
                user=interaction.user,
                guild=interaction.guild,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            self._export_task = spawn(self._run_export(interaction, channels, limit), name='exportchat')
        except BaseException:
            self._export_running = False
            self._cancel_export = False
            self._export_owner_id = None
            self._export_guild_id = None
            self._update_progress()
            raise

    @nextcord.slash_command(
        name='exportstop', description='Stop the current chat export', contexts=[nextcord.InteractionContextType.guild]
    )
    @safe_slash_command()
    async def exportstop(self, interaction: nextcord.Interaction):
        """Cancel an active export."""
        if not self._export_running:
            embed = await info_embed(
                title='No Export Running',
                description='There is no active export to stop.',
                contributor_source=__name__,
                user=interaction.user,
                guild=interaction.guild,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        same_guild_admin = (
            interaction.guild is not None
            and interaction.guild.id == self._export_guild_id
            and _is_admin_user(interaction.user, interaction.guild)
        )
        if interaction.user.id != self._export_owner_id and not same_guild_admin:
            embed = await error_embed(
                title='Not Your Export',
                description='Only the user who started the export or an administrator can stop it.',
                contributor_source=__name__,
                user=interaction.user,
                guild=interaction.guild,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        self._cancel_export = True
        embed = await success_embed(
            title='Export Cancelling',
            description='The export will stop after the current channel completes. Check your DMs for the final summary.',
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        await safe_send(interaction, embed=embed, ephemeral=True)


def setup(bot: commands.Bot):
    bot.add_cog(ChatExport(bot))
    logging.getLogger('VEKA').info('Loaded cog: src.cogs.external.export')
    return True
