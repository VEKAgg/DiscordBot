"""
24/7 Radio Cog — streams audio from a URL (e.g. Lofi Girl) using FFmpeg.

Requires: ffmpeg, opus, PyNaCl installed on the host system.
Stream URLs are extracted from YouTube via yt-dlp and refreshed periodically.
"""

import asyncio
import logging
import time
from datetime import datetime

import nextcord
from nextcord.ext import commands, tasks

from src.config.config import (
    RADIO_RECOVERY_PINGS_REQUIRED,
    RADIO_REFRESH_INTERVAL,
    RADIO_STABILITY_INTERVAL,
    RADIO_STREAM_URL,
    RADIO_VOICE_CHANNEL_ID,
)
from src.core.runtime_state import runtime_state
from src.database.database import db
from src.utils.embeds import error_embed, info_embed, success_embed
from src.utils.guild_gate import owner_in_external_only
from src.utils.safety import admin_only, safe_send, safe_slash_command

logger = logging.getLogger('VEKA.radio')

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin',
    'options': '-vn -ar 48000 -ac 2 -f opus',
}


def _extract_stream_url(youtube_url: str) -> str | None:
    """Extract a playable audio stream URL from a YouTube URL using yt-dlp."""
    try:
        import yt_dlp

        ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:  # type: ignore[attr-defined]
            info = ydl.extract_info(youtube_url, download=False)
            if info and 'url' in info:
                return info['url']
            # Some streams use a nested format
            if info and 'formats' in info:
                for fmt in info['formats']:
                    if fmt.get('acodec') != 'none':
                        return fmt['url']
            return None
    except ImportError:
        logger.error('yt-dlp is not installed. Install it with: pip install yt-dlp')
        return None
    except Exception as exc:
        logger.error('Failed to extract stream URL from %s: %s', youtube_url, exc, exc_info=True)
        return None


class RadioManager(commands.Cog):
    """24/7 Radio — streams audio to a voice channel using FFmpeg."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._stream_url: str | None = None
        self._stream_url_fetched_at: float = 0.0
        self._voice_client: nextcord.VoiceClient | None = None
        self._target_channel_id: int | None = RADIO_VOICE_CHANNEL_ID
        self._auto_started: bool = False
        self._started_at: datetime | None = None
        self._manual_stop: bool = False

    async def cog_load(self):
        """Auto-join on bot startup if channel is configured."""
        if self._target_channel_id:
            self.monitor_stability.start()
            self.refresh_stream_url.start()
            self.track_radio_listeners.start()
            # Delay auto-join slightly to let bot finish connecting
            await asyncio.sleep(5)
            if not self._manual_stop:
                await self._auto_join()

    async def cog_unload(self):
        """Disconnect and stop tasks when cog is unloaded."""
        self.monitor_stability.stop()
        self.refresh_stream_url.stop()
        self.track_radio_listeners.stop()
        await self._disconnect()

    # ============================================================
    # Internal helpers
    # ============================================================

    async def _auto_join(self):
        """Join the configured voice channel and start playing."""
        if self._voice_client and self._voice_client.is_connected():
            return

        if not self._target_channel_id:
            return

        channel = self.bot.get_channel(self._target_channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(self._target_channel_id)
            except Exception as exc:
                logger.error('Failed to fetch voice channel %s: %s', self._target_channel_id, exc)
                return

        if not isinstance(channel, nextcord.VoiceChannel):
            logger.error('Channel %s is not a voice channel', self._target_channel_id)
            return

        try:
            # Extract stream URL if not cached
            if not self._stream_url or self._is_stream_url_expired():
                await self._fetch_stream_url()

            if not self._stream_url:
                logger.error('No stream URL available, cannot start radio')
                if hasattr(self.bot, 'notifier'):
                    await self.bot.notifier.send_alert(
                        title='Radio: Stream URL Unavailable',
                        description='Could not extract a stream URL. Radio will not start.',
                        severity='ERROR',
                        dedupe_key='radio_no_stream_url',
                        cooldown_minutes=30,
                    )
                return

            self._voice_client = await channel.connect(self_deaf=True)  # type: ignore[call-arg]
            self._play_stream()
            self._started_at = datetime.utcnow()
            self._auto_started = True
            self._manual_stop = False
            logger.info('Radio started in channel %s', channel.name)

            if hasattr(self.bot, 'notifier'):
                await self.bot.notifier.send_alert(
                    title='Radio Started',
                    description=f'Now streaming in **{channel.name}**',
                    severity='INFO',
                    dedupe_key='radio_status',
                    cooldown_minutes=60,
                )
        except Exception as exc:
            logger.error('Failed to join voice channel: %s', exc, exc_info=True)
            if hasattr(self.bot, 'notifier'):
                await self.bot.notifier.send_alert(
                    title='Radio: Connection Failed',
                    description=f'Failed to join voice channel: `{exc}`',
                    severity='ERROR',
                    dedupe_key='radio_connection_failed',
                    cooldown_minutes=30,
                )

    def _play_stream(self):
        """Play the cached stream URL through FFmpeg."""
        if not self._voice_client or not self._stream_url:
            return

        source = nextcord.FFmpegPCMAudio(
            self._stream_url,
            before_options=FFMPEG_OPTIONS['before_options'],
            **{k: v for k, v in FFMPEG_OPTIONS.items() if k != 'before_options'},  # type: ignore[arg-type]
        )
        self._voice_client.play(source, after=self._on_play_end)

    def _on_play_end(self, error):
        """Callback when FFmpeg stream ends or encounters an error."""
        if error:
            logger.error('Radio playback error: %s', error)
        else:
            logger.info('Radio stream ended normally, attempting restart')
            # Stream ended — schedule restart
            if self._voice_client and self._voice_client.is_connected() and not self._manual_stop:
                asyncio.ensure_future(self._restart_playback())

    async def _restart_playback(self):
        """Restart playback after stream ends (re-extract URL if expired)."""
        try:
            if self._is_stream_url_expired():
                await self._fetch_stream_url()
            if self._stream_url and self._voice_client and self._voice_client.is_connected():
                await asyncio.sleep(2)  # Brief pause before restart
                self._play_stream()
        except Exception as exc:
            logger.error('Failed to restart radio playback: %s', exc, exc_info=True)

    async def _disconnect(self):
        """Disconnect from voice channel."""
        if self._voice_client and self._voice_client.is_connected():
            try:
                self._voice_client.stop()
            except Exception:
                pass
            try:
                await self._voice_client.disconnect()
            except Exception:
                pass
        self._voice_client = None

    async def _fetch_stream_url(self):
        """Extract and cache a fresh stream URL."""
        url = await asyncio.to_thread(_extract_stream_url, RADIO_STREAM_URL)
        if url:
            self._stream_url = url
            self._stream_url_fetched_at = time.monotonic()
            logger.info('Stream URL refreshed successfully')
        else:
            logger.warning('Stream URL extraction returned None')

    def _is_stream_url_expired(self) -> bool:
        """Check if the cached stream URL has expired."""
        if self._stream_url_fetched_at == 0.0:
            return True
        return (time.monotonic() - self._stream_url_fetched_at) > RADIO_REFRESH_INTERVAL

    def _is_connected(self) -> bool:
        """Check if the bot is currently connected to a voice channel."""
        return self._voice_client is not None and self._voice_client.is_connected()

    def _get_uptime(self) -> str:
        """Format uptime since radio started."""
        if not self._started_at:
            return 'Not started'
        delta = datetime.utcnow() - self._started_at
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f'{hours}h {minutes}m'
        return f'{minutes}m {seconds}s'

    # ============================================================
    # Background tasks
    # ============================================================

    @tasks.loop(seconds=RADIO_STABILITY_INTERVAL)
    async def monitor_stability(self):
        """Monitor radio health. Disconnect on degraded, reconnect on recovery."""
        if self._manual_stop:
            return

        is_healthy = runtime_state.db_available and not runtime_state.failed_cogs

        if not is_healthy:
            if self._is_connected():
                logger.warning('Degraded mode detected — disconnecting radio')
                await self._disconnect()
                if hasattr(self.bot, 'notifier'):
                    await self.bot.notifier.send_alert(
                        title='Radio Disconnected (Degraded Mode)',
                        description='Bot entered degraded mode. Radio disconnected to save resources.',
                        severity='WARN',
                        dedupe_key='radio_degraded_disconnect',
                        cooldown_minutes=30,
                    )
            return

        # Recovery: rejoin if not connected and not manually stopped
        if not self._is_connected() and self._target_channel_id:
            cache = runtime_state.alert_state_cache
            key = 'radio_healthy_count'
            count = cache.get(key, 0) + 1
            cache[key] = count

            if count >= RADIO_RECOVERY_PINGS_REQUIRED:
                cache.pop(key, None)
                logger.info('Health recovered — rejoining voice channel')
                await self._auto_join()
        else:
            runtime_state.alert_state_cache.pop('radio_healthy_count', None)

    @monitor_stability.before_loop
    async def before_monitor_stability(self):
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=RADIO_REFRESH_INTERVAL)
    async def refresh_stream_url(self):
        """Periodically refresh the stream URL before it expires."""
        if self._is_connected() and not self._is_stream_url_expired():
            return

        old_url = self._stream_url
        await self._fetch_stream_url()

        if self._stream_url and self._stream_url != old_url and self._is_connected():
            # Restart playback with new URL
            try:
                self._voice_client.stop()  # type: ignore[union-attr]
                await asyncio.sleep(1)
                self._play_stream()
            except Exception as exc:
                logger.error('Failed to restart playback after URL refresh: %s', exc)

    @refresh_stream_url.before_loop
    async def before_refresh_stream_url(self):
        await self.bot.wait_until_ready()

    # ============================================================
    # Radio listener tracking — every 5 minutes
    # ============================================================

    @tasks.loop(minutes=5)
    async def track_radio_listeners(self):
        """Track who is listening to the radio and record their time."""
        if not self._is_connected() or not runtime_state.db_available:
            return

        if not self._voice_client or not self._voice_client.channel:
            return

        # Get all non-bot members in the radio voice channel
        listeners = [
            m for m in self._voice_client.channel.members
            if not m.bot
        ]

        for member in listeners:
            try:
                await db.execute(
                    """
                    INSERT INTO user_activity_details (user_id, activity_type, activity_name, duration_minutes, last_seen)
                    VALUES ($1, 'radio', 'Radio Stream', 5, NOW())
                    ON CONFLICT (user_id, activity_type, activity_name)
                    DO UPDATE SET
                        duration_minutes = user_activity_details.duration_minutes + 5,
                        last_seen = NOW()
                    """,
                    str(member.id),
                )
            except Exception as exc:
                logger.debug('Failed to track radio listener %s: %s', member, exc)

    @track_radio_listeners.before_loop
    async def before_track_radio_listeners(self):
        await self.bot.wait_until_ready()

    # ============================================================
    # Commands
    # ============================================================

    @nextcord.slash_command(name='radio', description='Control the 24/7 radio stream')
    async def radio_group(self, interaction: nextcord.Interaction):
        pass

    @radio_group.subcommand(name='status', description='Show radio status')
    @safe_slash_command()
    async def radio_status(self, interaction: nextcord.Interaction):
        """Show current radio status."""
        connected = self._is_connected()
        channel_name = 'None'
        if connected and self._voice_client and self._voice_client.channel:
            channel_name = self._voice_client.channel.name  # type: ignore[attr-defined]

        description = (
            f'**Status**: {"Streaming" if connected else "Stopped"}\n'
            f'**Channel**: {channel_name}\n'
            f'**Uptime**: {self._get_uptime()}\n'
            f'**Stream URL**: {"Cached" if self._stream_url and not self._is_stream_url_expired() else "Expired/Missing"}\n'
            f'**Source**: {RADIO_STREAM_URL}'
        )
        embed = await info_embed(
            title='Radio Status',
            description=description,
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        await safe_send(interaction, embed=embed, ephemeral=True)

    @radio_group.subcommand(name='start', description='Start the radio stream (admin only)')
    @safe_slash_command()
    @admin_only()
    @owner_in_external_only()
    async def radio_start(self, interaction: nextcord.Interaction):
        """Manually start the radio in the configured channel."""
        if self._is_connected():
            embed = await info_embed(
                title='Radio Already Active',
                description='The radio is already streaming. Use `/radio stop` first.',
                contributor_source=__name__,
                user=interaction.user,
                guild=interaction.guild,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        if not self._target_channel_id:
            embed = await error_embed(
                title='No Channel Configured',
                description='Set `RADIO_VOICE_CHANNEL_ID` in your `.env` file to use the radio.',
                contributor_source=__name__,
                user=interaction.user,
                guild=interaction.guild,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        self._manual_stop = False
        await self._auto_join()

        if self._is_connected():
            embed = await success_embed(
                title='Radio Started',
                description='The radio is now streaming.',
                contributor_source=__name__,
                user=interaction.user,
                guild=interaction.guild,
            )
        else:
            embed = await error_embed(
                title='Radio Start Failed',
                description='Could not connect to the voice channel. Check logs for details.',
                contributor_source=__name__,
                user=interaction.user,
                guild=interaction.guild,
            )
        await safe_send(interaction, embed=embed, ephemeral=True)

    @radio_group.subcommand(name='stop', description='Stop the radio stream (admin only)')
    @safe_slash_command()
    @admin_only()
    @owner_in_external_only()
    async def radio_stop(self, interaction: nextcord.Interaction):
        """Manually stop the radio."""
        if not self._is_connected():
            embed = await info_embed(
                title='Radio Not Active',
                description='The radio is not currently streaming.',
                contributor_source=__name__,
                user=interaction.user,
                guild=interaction.guild,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        self._manual_stop = True
        await self._disconnect()
        self._started_at = None

        embed = await success_embed(
            title='Radio Stopped',
            description='The radio stream has been stopped.',
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        await safe_send(interaction, embed=embed, ephemeral=True)

    @radio_group.subcommand(name='move', description='Move the radio to a different voice channel (admin only)')
    @safe_slash_command()
    @admin_only()
    @owner_in_external_only()
    async def radio_move(
        self,
        interaction: nextcord.Interaction,
        channel: nextcord.VoiceChannel = nextcord.SlashOption(description='Voice channel to move to'),
    ):
        """Move the radio to a different voice channel."""
        was_playing = self._is_connected()

        if was_playing:
            await self._disconnect()

        self._target_channel_id = channel.id
        self._manual_stop = False
        await self._auto_join()

        if self._is_connected():
            embed = await success_embed(
                title='Radio Moved',
                description=f'Now streaming in **{channel.name}**',
                contributor_source=__name__,
                user=interaction.user,
                guild=interaction.guild,
            )
        else:
            embed = await error_embed(
                title='Move Failed',
                description=f'Could not connect to **{channel.name}**. Check logs for details.',
                contributor_source=__name__,
                user=interaction.user,
                guild=interaction.guild,
            )
        await safe_send(interaction, embed=embed, ephemeral=True)


def setup(bot: commands.Bot):
    bot.add_cog(RadioManager(bot))
    logging.getLogger('VEKA').info('Loaded cog: src.cogs.radio')
    return True
