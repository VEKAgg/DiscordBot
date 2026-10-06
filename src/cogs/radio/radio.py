"""
Radio Cog — plays podcasts and other spoken-word audio into a voice channel using FFmpeg.

There are no built-in stations: the bot only plays what an admin queues with `/radio play <url>` or
`/radio podcast <feed>`, and leaves the channel when it ends. Content must stay halal and religion-neutral
(no music) — see "Content policy" in AGENTS.md.

Requires: ffmpeg, opus, PyNaCl installed on the host system.
Sources are direct audio URLs (Icecast/SHOUTcast streams, MP3/M4A files, HLS) and podcast RSS feeds —
no yt-dlp, so YouTube/Spotify page links don't play.
"""

import asyncio
import logging
from datetime import UTC, datetime
from urllib.parse import urlsplit

import feedparser
import nextcord
from nextcord.ext import commands, tasks

from src.config.config import (
    RADIO_RECOVERY_PINGS_REQUIRED,
    RADIO_STABILITY_INTERVAL,
    RADIO_VOICE_CHANNEL_ID,
)
from src.core.lifecycle import has_running_loop, spawn
from src.core.runtime_state import runtime_state
from src.database.database import db
from src.services.guild_settings_service import guild_settings_service
from src.utils.embeds import error_embed, info_embed, success_embed, veka_embed
from src.utils.guild_gate import owner_in_external_only
from src.utils.http import PublicOnlyResolver, UnsafeURLError, fetch_public_url, validate_public_url
from src.utils.safety import admin_only, safe_send, safe_slash_command

logger = logging.getLogger('VEKA.radio')

FFMPEG_OPTIONS = {
    # Admins can play any URL: only network protocols, so a playlist can't make FFmpeg read local files.
    'before_options': (
        '-protocol_whitelist http,https,tcp,tls,crypto '
        '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin'
    ),
    # FFmpegPCMAudio already adds '-f s16le -ar 48000 -ac 2'; adding '-f opus' here overrode it and produced
    # an Ogg container that was played as raw PCM (noise). Only drop video (audit H-09).
    'options': '-vn',
}

# Podcast feeds can be large; still bounded so a hostile URL can't exhaust memory.
PODCAST_FEED_MAX_BYTES = 10 * 1024 * 1024


async def resolve_public_media_url(url: str) -> str:
    """Validate a user-supplied media URL (http/https, host resolves only to public addresses).

    FFmpeg fetches the URL itself, so this is a pre-flight check; the protocol whitelist in FFMPEG_OPTIONS keeps it
    to network protocols. Raises UnsafeURLError.
    """
    url = validate_public_url(url)
    host = urlsplit(url).hostname or ''
    resolver = PublicOnlyResolver()
    try:
        await resolver.resolve(host, 0)
    except OSError as exc:
        raise UnsafeURLError('That host does not resolve to a public address.') from exc
    finally:
        await resolver.close()
    return url


def parse_podcast_episodes(content: bytes) -> tuple[str, list[dict[str, str]]]:
    """Return (feed title, episodes newest-first) where each episode has an audio enclosure."""
    feed = feedparser.parse(content)
    episodes = []
    for entry in feed.entries:
        audio = next(
            (
                enc.get('href')
                for enc in entry.get('enclosures', [])
                if enc.get('href') and (enc.get('type', '').startswith(('audio/', 'video/')) or not enc.get('type'))
            ),
            None,
        )
        if audio:
            episodes.append({'title': entry.get('title') or 'Untitled episode', 'url': audio})
    return feed.feed.get('title') or 'Podcast', episodes


class RadioManager(commands.Cog):
    """Radio — plays an admin-chosen podcast episode or audio URL into a voice channel using FFmpeg."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # What is playing (or queued to play): {'name', 'url', 'emoji'}. None = idle.
        self._source: dict[str, str] | None = None
        # Bumped on every play; an `after=` callback from an older play is ignored (intentional stop/switch).
        self._play_generation: int = 0
        self._voice_client: nextcord.VoiceClient | None = None
        self._target_channel_id: int | None = RADIO_VOICE_CHANNEL_ID
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

    async def cog_ready(self):
        """Start background tasks (called from on_ready). Nothing auto-plays: there are no built-in stations."""
        if not self.monitor_stability.is_running():
            self.monitor_stability.start()
        if not self.track_radio_listeners.is_running():
            self.track_radio_listeners.start()

    def cog_unload(self):
        """Disconnect and stop tasks when cog is unloaded (nextcord calls this synchronously)."""
        self.monitor_stability.cancel()
        self.track_radio_listeners.cancel()
        if has_running_loop():
            spawn(self._disconnect(), name='radio:disconnect')

    # ============================================================
    # Internal helpers
    # ============================================================

    def _now_playing(self) -> dict[str, str] | None:
        """Name/url/emoji of what is playing now, or None when idle."""
        return self._source

    def _now_playing_label(self) -> str:
        source = self._now_playing()
        return f'{source["emoji"]} {source["name"]}' if source else 'Nothing'

    async def _start(self, source: dict[str, str]) -> bool:
        """Play `source`, joining the radio channel first if needed. Returns True if it is playing."""
        self._source = source
        self._manual_stop = False
        if self._is_connected() and self._voice_client:
            self._play_generation += 1  # the stop() below must not end the session
            self._voice_client.stop()
            await asyncio.sleep(1)
            self._play_stream()
            return True
        await self._join_and_play()
        return self._is_connected()

    async def _join_and_play(self):
        """Join the configured voice channel and play the current source."""
        if not self._source or (self._voice_client and self._voice_client.is_connected()):
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
            # nextcord's connect() has no self_deaf (that's discord.py); deafen via the voice state instead.
            self._voice_client = await channel.connect()
            try:
                await channel.guild.change_voice_state(channel=channel, self_deaf=True)
            except Exception as exc:
                logger.warning('Could not self-deafen in %s: %s', channel.name, exc)
            self._play_stream()
            self._started_at = datetime.now(UTC)
            logger.info('Radio started in channel %s (source: %s)', channel.name, self._source['name'])
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
        """Play the current source through FFmpeg."""
        if not self._voice_client or not self._source:
            return

        source = nextcord.FFmpegPCMAudio(
            self._source['url'],
            before_options=FFMPEG_OPTIONS['before_options'],
            **{k: v for k, v in FFMPEG_OPTIONS.items() if k != 'before_options'},  # type: ignore[arg-type]
        )
        self._play_generation += 1
        generation = self._play_generation
        self._voice_client.play(source, after=lambda error: self._on_play_end(error, generation))

    def _on_play_end(self, error, generation: int | None = None):
        """Callback when FFmpeg finishes or fails: the session is over, so leave the channel.

        nextcord invokes ``after=`` from the audio player thread, so the coroutine must be handed to the
        bot's event loop thread-safely (``ensure_future`` here had no running loop in that thread).
        """
        if generation is not None and generation != self._play_generation:
            return  # stopped on purpose to switch sources or disconnect
        if error:
            logger.error('Radio playback error: %s', error)
        else:
            logger.info('Radio source finished')
        self._source = None
        asyncio.run_coroutine_threadsafe(self._disconnect(), self.bot.loop)

    async def _disconnect(self):
        """Disconnect from voice channel and clear uptime."""
        if self._voice_client and self._voice_client.is_connected():
            self._play_generation += 1  # this stop() must not re-trigger _on_play_end handling
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

    async def _play_url(self, url: str, title: str | None = None, *, emoji: str = '\U0001f517') -> tuple[bool, str]:
        """Validate a URL and play it. Returns (ok, user-facing message)."""
        try:
            url = await resolve_public_media_url(url)
        except UnsafeURLError as exc:
            return False, str(exc)
        if not await self._get_target_channel_id():
            return False, 'No radio voice channel is configured. Set one with `/setup` or `/radio move`.'
        name = nextcord.utils.escape_markdown((title or urlsplit(url).hostname or 'Custom stream')[:100])
        if not await self._start({'name': name, 'url': url, 'emoji': emoji}):
            return False, 'Could not connect to the voice channel. Check logs for details.'
        logger.info('Radio playing custom source from %s', urlsplit(url).hostname)
        return True, f'{emoji} **{name}**\nThe radio leaves the channel when it ends.'

    async def _play_podcast(self, feed_url: str, episode: int = 1) -> tuple[bool, str]:
        """Fetch a podcast feed and play episode N (1 = newest). Returns (ok, user-facing message)."""
        try:
            status, body = await fetch_public_url(feed_url, max_bytes=PODCAST_FEED_MAX_BYTES)
        except UnsafeURLError as exc:
            return False, str(exc)
        except Exception as exc:
            logger.info('Podcast feed fetch failed: %s', type(exc).__name__)
            return False, 'Could not fetch that feed.'
        if status != 200:
            return False, f'The feed returned HTTP {status}.'
        feed_title, episodes = await asyncio.to_thread(parse_podcast_episodes, body)
        if not episodes:
            return False, 'That URL is not a podcast feed with audio episodes.'
        if episode > len(episodes):
            return False, f'That feed only has {len(episodes)} episode(s).'
        chosen = episodes[episode - 1]
        return await self._play_url(chosen['url'], f'{feed_title} — {chosen["title"]}', emoji='\U0001f399️')

    # ============================================================
    # Background tasks
    # ============================================================

    @tasks.loop(seconds=RADIO_STABILITY_INTERVAL)
    async def monitor_stability(self):
        """Monitor radio health. Disconnect on degraded, reconnect on recovery if something was playing."""
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

        # Recovery: resume the interrupted source if not connected and not manually stopped
        if not self._is_connected() and self._source:
            cache = runtime_state.alert_state_cache
            key = 'radio_healthy_count'
            count = cache.get(key, 0) + 1
            cache[key] = count

            if count >= RADIO_RECOVERY_PINGS_REQUIRED:
                cache.pop(key, None)
                logger.info('Health recovered — rejoining voice channel')
                await self._join_and_play()
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
        description='Play podcasts and other audio in the radio voice channel',
        contexts=[nextcord.InteractionContextType.guild],
    )
    async def radio_group(self, interaction: nextcord.Interaction):
        embed = await veka_embed(
            title='Radio Commands',
            description=(
                f'**Now playing:** {self._now_playing_label()}\n\n'
                '**Subcommands:**\n\n'
                '• `/radio status` — Show radio status\n'
                '• `/radio podcast <feed>` — Play a podcast episode (admin)\n'
                '• `/radio play <url>` — Play an audio URL (admin)\n'
                '• `/radio stop` — Stop and leave the channel (admin)\n'
                '• `/radio move` — Move to another channel (admin)'
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

        description = (
            f'**Status**: {"Playing" if connected else "Idle"}\n'
            f'**Channel**: {channel_name}\n'
            f'**Now playing**: {self._now_playing_label()}\n'
            f'**Uptime**: {self._get_uptime()}'
        )
        embed = await info_embed(
            title='Radio Status',
            description=description,
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        await safe_send(interaction, embed=embed, ephemeral=True)

    @radio_group.subcommand(name='play', description='Play a public audio URL (admin only)')
    @safe_slash_command()
    @admin_only()
    @owner_in_external_only()
    async def radio_play(
        self,
        interaction: nextcord.Interaction,
        url: str = nextcord.SlashOption(description='Direct audio URL (stream, MP3/M4A file, HLS .m3u8)'),
        title: str | None = nextcord.SlashOption(description='Name to show in status', required=False, default=None),
    ):
        """Play an audio URL; the radio leaves the channel when it ends."""
        await interaction.response.defer(ephemeral=True)
        ok, message = await self._play_url(url, title)
        embed_factory = success_embed if ok else error_embed
        embed = await embed_factory(
            title='Now Playing' if ok else 'Cannot Play That URL',
            description=message,
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        await safe_send(interaction, embed=embed, ephemeral=True)

    @radio_group.subcommand(name='podcast', description='Play an episode from a podcast RSS feed (admin only)')
    @safe_slash_command()
    @admin_only()
    @owner_in_external_only()
    async def radio_podcast(
        self,
        interaction: nextcord.Interaction,
        feed: str = nextcord.SlashOption(description='Podcast RSS feed URL'),
        episode: int = nextcord.SlashOption(
            description='Episode number, newest first (1 = latest)', required=False, default=1, min_value=1
        ),
    ):
        """Play a podcast episode; the radio leaves the channel when it ends."""
        await interaction.response.defer(ephemeral=True)
        ok, message = await self._play_podcast(feed, episode)
        embed_factory = success_embed if ok else error_embed
        embed = await embed_factory(
            title='Now Playing' if ok else 'Cannot Play That Podcast',
            description=message,
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        await safe_send(interaction, embed=embed, ephemeral=True)

    @radio_group.subcommand(name='stop', description='Stop the radio and leave the channel (admin only)')
    @safe_slash_command()
    @admin_only()
    @owner_in_external_only()
    async def radio_stop(self, interaction: nextcord.Interaction):
        """Manually stop the radio."""
        if not self._is_connected():
            embed = await info_embed(
                title='Radio Not Active',
                description='The radio is not currently playing.',
                contributor_source=__name__,
                user=interaction.user,
                guild=interaction.guild,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        self._manual_stop = True
        self._source = None
        await self._disconnect()

        embed = await success_embed(
            title='Radio Stopped',
            description='The radio has stopped and left the channel.',
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
        """Set the radio's voice channel, moving there now if something is playing."""
        self._target_channel_id = channel.id
        if self._is_connected():
            await self._disconnect()
            await self._join_and_play()
            ok = self._is_connected()
        else:
            ok = True

        if ok:
            embed = await success_embed(
                title='Radio Channel Set',
                description=f'The radio will play in **{channel.name}**.',
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

    @commands.command(name='radioplay')
    @admin_only()
    @owner_in_external_only()
    async def prefix_radio_play(self, ctx: commands.Context, url: str, *, title: str | None = None):
        """Play a public audio URL. Usage: !radioplay <url> [title]"""
        ok, message = await self._play_url(url, title)
        await safe_send(ctx, message if ok else f'❌ {message}')

    @commands.command(name='radiopodcast')
    @admin_only()
    @owner_in_external_only()
    async def prefix_radio_podcast(self, ctx: commands.Context, feed: str, episode: int = 1):
        """Play a podcast episode (1 = latest). Usage: !radiopodcast <feed url> [episode]"""
        if episode < 1:
            await safe_send(ctx, '❌ Episode must be 1 or higher.')
            return
        ok, message = await self._play_podcast(feed, episode)
        await safe_send(ctx, message if ok else f'❌ {message}')


def setup(bot: commands.Bot):
    bot.add_cog(RadioManager(bot))
    logging.getLogger('VEKA').info('Loaded cog: src.cogs.radio')
    return True
