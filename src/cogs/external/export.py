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
import time
from datetime import UTC, datetime

import nextcord
from nextcord.ext import commands

from src.core.runtime_state import runtime_state
from src.utils.embeds import error_embed, info_embed, success_embed
from src.utils.guild_gate import owner_in_external_only
from src.utils.safety import safe_send, safe_slash_command

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


class ChatExport(commands.Cog):
    """Chat history export with rate limiting and stability safeguards."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._export_running = False
        self._cancel_export = False
        self._export_progress: dict = {}

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

            if psutil.cpu_percent(interval=0.1) > CPU_PAUSE_THRESHOLD:
                logger.warning('Export paused: CPU above %s%%', CPU_PAUSE_THRESHOLD)
                return False
        except ImportError:
            pass
        return True

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
        _owner: nextcord.Member,
        limit: int | None = None,
    ) -> tuple[str | None, int]:
        """
        Export a single channel's history to a .txt file.
        Returns (file_content_or_None, message_count).
        """
        messages = []
        delay = BASE_DELAY
        batch_count = 0
        batches_since_slowdown = 0
        pauses_since_random = 0

        try:
            async for msg in channel.history(limit=limit, oldest_first=True):
                messages.append(msg)

                # Process in batches
                if len(messages) >= BATCH_SIZE:
                    # Health check
                    if not self._is_healthy():
                        logger.info('Export paused for channel %s — waiting for health recovery')
                        while not self._is_healthy():
                            await asyncio.sleep(10)
                            if self._cancel_export:
                                return None, 0
                        logger.info('Health recovered — resuming export for channel %s')

                    # Rate limiting
                    batch_count += 1
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
                    batch_count += 1

                    # Yield to main server
                    await asyncio.sleep(0)

                    if self._cancel_export:
                        return None, 0

        except nextcord.Forbidden:
            logger.warning('No access to channel %s', channel.name)
            return None, 0
        except Exception as exc:
            logger.error('Error exporting channel %s: %s', channel.name, exc)
            return None, 0

        if not messages:
            return None, 0

        # Build file content
        first_msg = messages[0]
        last_msg = messages[-1]
        first_date = first_msg.created_at.strftime('%Y-%m-%d')
        last_date = last_msg.created_at.strftime('%Y-%m-%d')
        date_range = f'{first_date} to {last_date}' if first_date != last_date else first_date

        header = self._build_channel_header(channel, len(messages), date_range)
        body = '\n'.join(self._format_message(msg) for msg in messages)
        content = header + body

        return content, len(messages)

    async def _send_file_dm(self, owner: nextcord.Member, filename: str, content: str) -> bool:
        """Send a file to the owner via DM. Returns True on success."""
        try:
            # Check file size
            content_bytes = content.encode('utf-8')
            if len(content_bytes) > MAX_FILE_SIZE:
                # Split into parts
                part_num = 1
                chunk_size = MAX_FILE_SIZE - 1000  # Leave room for header
                lines = content.split('\n')
                current_chunk: list[str] = []
                current_size = 0

                for line in lines:
                    line_bytes = len(line.encode('utf-8')) + 1
                    if current_size + line_bytes > chunk_size and current_chunk:
                        part_content = '\n'.join(current_chunk)
                        part_file = nextcord.File(
                            io.BytesIO(part_content.encode('utf-8')),
                            filename=f'{filename}_part{part_num}.txt',
                        )
                        await owner.send(file=part_file)
                        part_num += 1
                        current_chunk = []
                        current_size = 0
                        await asyncio.sleep(1)
                    current_chunk.append(line)
                    current_size += line_bytes

                if current_chunk:
                    part_content = '\n'.join(current_chunk)
                    part_file = nextcord.File(
                        io.BytesIO(part_content.encode('utf-8')),
                        filename=f'{filename}_part{part_num}.txt',
                    )
                    await owner.send(file=part_file)
            else:
                file = nextcord.File(io.BytesIO(content_bytes), filename=filename)
                await owner.send(file=file)

            return True
        except Exception as exc:
            logger.error('Failed to send file %s via DM: %s', filename, exc)
            return False

    async def _run_export(
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

        # Send initial DM
        try:
            await owner.send(
                f'Starting export of {total_channels} channel(s). '
                f'Estimated time: ~{max(1, total_channels * 2)} minutes. '
                f"I'll DM you the files as they're ready. "
                f'Use `/exportstop` to cancel.'
            )
        except Exception:
            logger.warning('Could not DM owner about export start')

        for channel in channels:
            if self._cancel_export:
                break

            # Time check
            elapsed = time.monotonic() - start_time
            if elapsed > MAX_EXPORT_DURATION:
                logger.warning('Export max duration reached (%ds)', MAX_EXPORT_DURATION)
                try:
                    await owner.send(
                        f'Export stopped: max duration (30 minutes) reached. '
                        f'{completed}/{total_channels} channels exported, {total_messages:,} messages total.'
                    )
                except Exception:
                    pass
                break

            logger.info('Exporting channel: %s (%d/%d)', channel.name, completed + 1, total_channels)

            content, msg_count = await self._export_channel(channel, owner, limit)

            if content and msg_count > 0:
                filename = f'{channel.name}_{channel.id}.txt'
                success = await self._send_file_dm(owner, filename, content)

                if success:
                    exported_files.append(channel.name)
                    completed += 1
                    total_messages += msg_count

                    self._update_progress(
                        completed_channels=completed,
                        total_messages=total_messages,
                        current_channel=channel.name,
                    )

                    # Progress DM
                    remaining = total_channels - completed
                    if remaining > 0:
                        avg_time_per_channel = (time.monotonic() - start_time) / completed
                        eta_minutes = int((remaining * avg_time_per_channel) / 60)
                        try:
                            await owner.send(
                                f'Exported #{channel.name} ({msg_count:,} messages) - '
                                f'{completed}/{total_channels} complete. '
                                f'~{eta_minutes} min remaining.'
                            )
                        except Exception:
                            pass
                else:
                    logger.warning('Failed to send file for channel %s', channel.name)
            else:
                logger.info('Channel %s had no accessible messages', channel.name)

            # Yield between channels
            await asyncio.sleep(0)

        # Completion summary
        self._export_running = False
        self._update_progress()

        duration = time.monotonic() - start_time
        duration_text = f'{int(duration // 60)}m {int(duration % 60)}s'

        try:
            status = 'cancelled' if self._cancel_export else 'complete'
            await owner.send(
                f'Export {status}! {completed}/{total_channels} channels, '
                f'{total_messages:,} total messages. Duration: {duration_text}.'
            )
        except Exception:
            pass

        logger.info(
            'Export %s: %d/%d channels, %d messages, %s',
            status,
            completed,
            total_channels,
            total_messages,
            duration_text,
        )

        self._cancel_export = False

    # ============================================================
    # Commands
    # ============================================================

    @nextcord.slash_command(
        name='exportchat', description='Export chat history to .txt files (owner only in external servers)'
    )
    @owner_in_external_only()
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

        # Determine channels to export
        if channel:
            channels = [channel]
        else:
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

            channels = [c for c in guild.text_channels if c.permissions_for(guild.me).read_message_history]

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

        # Defer response — export may take a while
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

        # Start export in background
        self._export_running = True
        self._cancel_export = False
        asyncio.ensure_future(self._run_export(interaction, channels, limit))

    @nextcord.slash_command(name='exportstop', description='Stop the current chat export')
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
