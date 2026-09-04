"""
24/7 Radio Cog — streams audio from Icecast/SHOUTcast streams using FFmpeg.

Requires: ffmpeg, opus, PyNaCl installed on the host system.
Streams are direct Icecast/SHOUTcast URLs — no yt-dlp or YouTube extraction needed.
"""

import asyncio
import logging
from datetime import UTC, datetime

import nextcord
from nextcord.ext import commands, tasks

from src.config.config import (
    RADIO_RECOVERY_PINGS_REQUIRED,
    RADIO_STABILITY_INTERVAL,
    RADIO_VOICE_CHANNEL_ID,
)
from src.core.runtime_state import runtime_state
from src.database.database import db
from src.services.guild_settings_service import guild_settings_service
from src.utils.embeds import error_embed, info_embed, success_embed, veka_embed
from src.utils.guild_gate import owner_in_external_only
from src.utils.safety import admin_only, safe_send, safe_slash_command

logger = logging.getLogger('VEKA.radio')

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin',
    'options': '-vn -ar 48000 -ac 2 -f opus',
}

RADIO_STATIONS: dict[str, dict[str, str]] = {
    'lofi': {
        'name': 'Groove Salad (Lofi / Ambient)',
        'url': 'https://ice1.somafm.com/groovesalad-128-mp3',
        'description': 'Downtempo ambient groove and chillout beats',
        'emoji': '\u2615',
    },
    'ambient': {
        'name': 'Drone Zone',
        'url': 'https://ice6.somafm.com/dronezone-128-mp3',
        'description': 'Deep atmospheric ambient soundscapes',
        'emoji': '\U0001f30c',
    },
    'chill': {
        'name': 'Groove Salad Classic',
        'url': 'https://ice6.somafm.com/gsclassic-128-mp3',
        'description': 'Early 2000s nostalgic chillout and downtempo',
        'emoji': '\U0001f6cb\ufe0f',
    },
    'spy': {
        'name': 'Secret Agent',
        'url': 'https://ice4.somafm.com/secretagent-128-mp3',
        'description': 'Lounge, spy film themes, and vintage spy jazz',
        'emoji': '\U0001f378',
    },
    'trip': {
        'name': 'The Trip',
        'url': 'https://ice2.somafm.com/thetrip-128-mp3',
        'description': 'Progressive, psychedelic, and electronic vibes',
        'emoji': '\U0001f680',
    },
    'chillhop': {
        'name': 'Chillhop Music',
        'url': 'https://streams.fluxfm.de/Chillhop/mp3-128/streams.fluxfm.de/',
        'description': 'Relaxing lofi hip-hop beats to study and work to',
        'emoji': '\U0001f3a7',
    },
    'jazz': {
        'name': 'Smooth Jazz Global',
        'url': 'https://smoothjazz.cdnstream1.com/2585_128.mp3',
        'description': 'Modern and classic smooth jazz radio',
        'emoji': '\U0001f3b7',
    },
}

DEFAULT_STATION = 'lofi'


class RadioManager(commands.Cog):
    """24/7 Radio — streams audio to a voice channel using FFmpeg."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._active_station: str = DEFAULT_STATION
        self._stream_url: str = RADIO_STATIONS[DEFAULT_STATION]['url']
        self._voice_client: nextcord.VoiceClient | None = None
        self._target_channel_id: int | None = RADIO_VOICE_CHANNEL_ID
        self._auto_started: bool = False
        self._started_at: datetime | None = None
        self._manual_stop: bool = False

    async def _get_target_channel_id(self) -> int | None:
        """Resolve target voice channel from guild settings, falling back to config."""
        if self._target_channel_id:
            return self._target_channel_id
        try:
            from src.config.config import MAIN_GUILD_ID

            settings = await guild_settings_service.get_settings(MAIN_GUILD_ID)
            if settings.radio_channel_id:
                return settings.radio_channel_id
        except Exception:
            pass
        return RADIO_VOICE_CHANNEL_ID

    async def cog_load(self):
        """Auto-join on bot startup if channel is configured."""
        if self._target_channel_id:
            self.monitor_stability.start()
            self.track_radio_listeners.start()
            await asyncio.sleep(5)
            if not self._manual_stop:
                await self._auto_join()

    async def cog_unload(self):
        """Disconnect and stop tasks when cog is unloaded."""
        self.monitor_stability.stop()
        self.track_radio_listeners.stop()
        await self._disconnect()

    # ============================================================
    # Internal helpers
    # ============================================================

    def _get_station_url(self) -> str:
        """Get the URL for the currently active station."""
        return RADIO_STATIONS[self._active_station]['url']

    async def _auto_join(self):
        """Join the configured voice channel and start playing."""
        if self._voice_client and self._voice_client.is_connected():
            return

        target_id = await self._get_target_channel_id()
        if not target_id:
            return

        channel = self.bot.get_channel(target_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(target_id)
            except Exception as exc:
                logger.error('Failed to fetch voice channel %s: %s', target_id, exc)
                return

        if not isinstance(channel, nextcord.VoiceChannel):
            logger.error('Channel %s is not a voice channel', target_id)
            return

        try:
            self._stream_url = self._get_station_url()
            self._voice_client = await channel.connect(self_deaf=True)  # type: ignore[call-arg]
            self._play_stream()
            self._started_at = datetime.now(UTC)
            self._auto_started = True
            self._manual_stop = False
            logger.info('Radio started in channel %s (station: %s)', channel.name, self._active_station)

            if hasattr(self.bot, 'notifier'):
                station = RADIO_STATIONS[self._active_station]
                await self.bot.notifier.send_alert(
                    title='Radio Started',
                    description=f'{station["emoji"]} Now streaming **{station["name"]}** in **{channel.name}**',
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
            if self._voice_client and self._voice_client.is_connected() and not self._manual_stop:
                asyncio.ensure_future(self._restart_playback())

    async def _restart_playback(self):
        """Restart playback after stream ends."""
        try:
            self._stream_url = self._get_station_url()
            if self._voice_client and self._voice_client.is_connected():
                await asyncio.sleep(2)
                self._play_stream()
        except Exception as exc:
            logger.error('Failed to restart radio playback: %s', exc, exc_info=True)

    async def _disconnect(self):
        """Disconnect from voice channel and clear uptime."""
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
        self._started_at = None

    def _is_connected(self) -> bool:
        """Check if the bot is currently connected to a voice channel."""
        return self._voice_client is not None and self._voice_client.is_connected()

    def _get_uptime(self) -> str:
        """Format uptime since radio started."""
        if not self._started_at:
            return 'Not started'
        delta = datetime.now(UTC) - self._started_at
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

        channel = self._voice_client.channel
        if not isinstance(channel, nextcord.VoiceChannel):
            return
        listeners = [m for m in channel.members if not m.bot]

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

    @nextcord.slash_command(
        name='radio',
        description='Control the 24/7 radio stream',
    )
    async def radio_group(self, interaction: nextcord.Interaction):
        station = RADIO_STATIONS[self._active_station]
        embed = await veka_embed(
            title='Radio Commands',
            description=(
                f'**Current station:** {station["emoji"]} {station["name"]}\n\n'
                '**Subcommands:**\n\n'
                '\u2022 `/radio status` \u2014 Show stream status\n'
                '\u2022 `/radio station <name>` \u2014 Switch station\n'
                '\u2022 `/radio list` \u2014 Browse all stations\n'
                '\u2022 `/radio start` \u2014 Start radio (admin)\n'
                '\u2022 `/radio stop` \u2014 Stop radio (admin)\n'
                '\u2022 `/radio move` \u2014 Move to another channel (admin)'
            ),
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        await safe_send(interaction, embed=embed, ephemeral=True)

    @radio_group.subcommand(name='status', description='Show radio status')
    @safe_slash_command()
    async def radio_status(self, interaction: nextcord.Interaction):
        """Show current radio status."""
        connected = self._is_connected()
        channel_name = 'None'
        if connected and self._voice_client and self._voice_client.channel:
            channel_name = self._voice_client.channel.name  # type: ignore[attr-defined]

        station = RADIO_STATIONS[self._active_station]
        description = (
            f'**Status**: {"Streaming" if connected else "Stopped"}\n'
            f'**Channel**: {channel_name}\n'
            f'**Station**: {station["emoji"]} {station["name"]}\n'
            f'**Description**: {station["description"]}\n'
            f'**Uptime**: {self._get_uptime()}\n'
            f'**Stream URL**: {"Active" if connected else "Idle"}'
        )
        embed = await info_embed(
            title='Radio Status',
            description=description,
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        await safe_send(interaction, embed=embed, ephemeral=True)

    @radio_group.subcommand(name='station', description='Switch the radio station')
    @safe_slash_command()
    @admin_only()
    @owner_in_external_only()
    async def radio_station(
        self,
        interaction: nextcord.Interaction,
        name: str = nextcord.SlashOption(
            description='Station to play',
            choices={f'{s["emoji"]} {s["name"]}': k for k, s in RADIO_STATIONS.items()},
        ),
    ):
        """Switch to a different radio station."""
        if name not in RADIO_STATIONS:
            embed = await error_embed(
                title='Unknown Station',
                description=f'Station `{name}` not found. Use `/radio list` to see available stations.',
                contributor_source=__name__,
                user=interaction.user,
                guild=interaction.guild,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        old_station = self._active_station
        self._active_station = name
        self._stream_url = RADIO_STATIONS[name]['url']

        if self._is_connected() and self._voice_client:
            self._voice_client.stop()
            await asyncio.sleep(1)
            self._play_stream()

        station = RADIO_STATIONS[name]
        embed = await success_embed(
            title='Station Changed',
            description=f'{station["emoji"]} Now playing **{station["name"]}**\n{station["description"]}',
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        await safe_send(interaction, embed=embed, ephemeral=True)
        logger.info('Station changed from %s to %s', old_station, name)

    @radio_group.subcommand(name='list', description='List all available radio stations')
    @safe_slash_command()
    async def radio_list(self, interaction: nextcord.Interaction):
        """Show all available radio stations."""
        lines = []
        for key, station in RADIO_STATIONS.items():
            badge = ' \u25b6 Active' if key == self._active_station else ''
            lines.append(f'{station["emoji"]} **{station["name"]}** (`{key}`){badge}\n{station["description"]}')

        embed = await veka_embed(
            title='Radio Stations',
            description='\n\n'.join(lines),
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
            station = RADIO_STATIONS[self._active_station]
            embed = await success_embed(
                title='Radio Started',
                description=f'{station["emoji"]} Now streaming **{station["name"]}**',
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
            station = RADIO_STATIONS[self._active_station]
            embed = await success_embed(
                title='Radio Moved',
                description=f'{station["emoji"]} Now streaming **{station["name"]}** in **{channel.name}**',
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

    # ============================================================
    # Prefix commands
    # ============================================================

    @commands.command(name='radiostation')
    @admin_only()
    async def prefix_radio_station(self, ctx: commands.Context, name: str):
        """Switch the radio station. Usage: !radiostation <name>"""
        if name not in RADIO_STATIONS:
            await safe_send(ctx, f'\u274c Station `{name}` not found. Use `!radiolist` to see available stations.')
            return

        self._active_station = name
        self._stream_url = RADIO_STATIONS[name]['url']

        if self._is_connected() and self._voice_client:
            self._voice_client.stop()
            await asyncio.sleep(1)
            self._play_stream()

        station = RADIO_STATIONS[name]
        await safe_send(ctx, f'{station["emoji"]} Now playing **{station["name"]}** — {station["description"]}')

    @commands.command(name='radiolist')
    async def prefix_radio_list(self, ctx: commands.Context):
        """List all available radio stations."""
        lines = ['**Radio Stations:**\n']
        for key, station in RADIO_STATIONS.items():
            badge = ' \u25b6 Active' if key == self._active_station else ''
            lines.append(f'{station["emoji"]} **{station["name"]}** (`{key}`){badge}\n{station["description"]}')

        await safe_send(ctx, '\n'.join(lines))


def setup(bot: commands.Bot):
    bot.add_cog(RadioManager(bot))
    logging.getLogger('VEKA').info('Loaded cog: src.cogs.radio')
    return True
