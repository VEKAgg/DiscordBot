"""
Rotating Status Cog — cycles through different bot statuses.

Displays streaming, watching, listening, and playing statuses
with dynamic data (server count, uptime, user count).
"""

import logging
from datetime import UTC, datetime

import nextcord
from nextcord.ext import commands, tasks

from src.core.runtime_state import runtime_state

logger = logging.getLogger('VEKA.status')

STREAMING_URL = 'https://twitch.tv/whoisshafaat'

# Status definitions — type, text template, optional URL
# Dynamic placeholders: {guilds}, {users}, {uptime}
STATUSES: list[dict] = [
    {'type': 'streaming', 'text': 'VEKA Community', 'url': STREAMING_URL},
    {'type': 'watching', 'text': 'serving {guilds} servers'},
    {'type': 'listening', 'text': 'use /help'},
    {'type': 'watching', 'text': 'uptime {uptime}'},
    {'type': 'playing', 'text': 'VEKA Discord Bot'},
    {'type': 'listening', 'text': '/leaderboard for rankings'},
    {'type': 'watching', 'text': '{users} members across all servers'},
    {'type': 'watching', 'text': 'VEKA community and resources'},
    {'type': 'listening', 'text': '/level to check your XP'},
    {'type': 'streaming', 'text': 'Join VEKA on Twitch', 'url': 'https://twitch.tv/whoisshafaat'},
    {'type': 'watching', 'text': '{online} members online'},
    {'type': 'playing', 'text': 'with slash commands'},
    {'type': 'watching', 'text': '{boosts} server boosts'},
    {'type': 'listening', 'text': '{active_radio_station}'},
    {'type': 'watching', 'text': '{open_listings} marketplace listings'},
    {'type': 'playing', 'text': 'Season {season}'},
]

ROTATION_INTERVAL = 10  # seconds between status changes


def _format_uptime(start_time: datetime | None) -> str:
    """Format uptime as a human-readable string."""
    if start_time is None:
        return 'unknown'
    try:
        delta = datetime.now(UTC) - start_time
    except (TypeError, ValueError):
        return 'unknown'
    total_seconds = int(delta.total_seconds())
    if total_seconds < 0:
        return 'unknown'
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)

    if days > 0:
        return f'{days}d {hours}h {minutes}m'
    if hours > 0:
        return f'{hours}h {minutes}m'
    return f'{minutes}m'


def _get_total_users(bot: commands.Bot) -> int:
    """Count total members across all guilds."""
    total = 0
    try:
        for guild in bot.guilds:
            count = guild.member_count
            if count:
                total += count
    except Exception:
        pass
    return total


class StatusRotator(commands.Cog):
    """Rotates through different bot status messages."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._status_index = 0

    async def cog_load(self):
        """Start the rotation loop."""
        self.rotate_status.start()

    async def cog_unload(self):
        """Stop the rotation loop."""
        self.rotate_status.stop()

    async def _build_activity(self, status_def: dict) -> nextcord.Activity | nextcord.Streaming | nextcord.Game:
        """Build a nextcord activity from a status definition."""
        text = status_def.get('text', 'VEKA')
        status_type = status_def.get('type', 'watching')

        # Format dynamic placeholders with individual error handling
        try:
            if '{guilds}' in text:
                text = text.format(guilds=len(self.bot.guilds))
        except Exception:
            text = text.replace('{guilds}', '?')

        try:
            if '{users}' in text:
                text = text.format(users=f'{_get_total_users(self.bot):,}')
        except Exception:
            text = text.replace('{users}', '?')

        try:
            if '{uptime}' in text:
                text = text.format(uptime=_format_uptime(runtime_state.startup_time))
        except Exception:
            text = text.replace('{uptime}', '?')

        try:
            if '{online}' in text:
                online = sum(
                    1 for g in self.bot.guilds for m in g.members if m.status != nextcord.Status.offline and not m.bot
                )
                text = text.format(online=f'{online:,}')
        except Exception:
            text = text.replace('{online}', '?')

        try:
            if '{boosts}' in text:
                boosts = sum(g.premium_subscription_count or 0 for g in self.bot.guilds)
                text = text.format(boosts=f'{boosts:,}')
        except Exception:
            text = text.replace('{boosts}', '?')

        try:
            if '{active_radio_station}' in text:
                radio_cog = self.bot.get_cog('RadioManager')
                if radio_cog and hasattr(radio_cog, '_active_station') and radio_cog._active_station:
                    from src.cogs.radio.radio import RADIO_STATIONS

                    station = RADIO_STATIONS.get(radio_cog._active_station, {})
                    station_name = station.get('name', radio_cog._active_station)
                    station_emoji = station.get('emoji', '')
                    text = text.format(active_radio_station=f'{station_emoji} {station_name}')
                else:
                    text = text.replace('{active_radio_station}', 'Radio is offline')
        except Exception:
            text = text.replace('{active_radio_station}', 'Radio')

        try:
            if '{open_listings}' in text:
                from src.database.database import db

                count = await db.fetchval(
                    "SELECT COUNT(*) FROM marketplace_listings WHERE status = 'active' AND is_expired = FALSE"
                )
                text = text.format(open_listings=f'{count or 0}')
        except Exception:
            text = text.replace('{open_listings}', '?')

        try:
            if '{season}' in text:
                from datetime import UTC, datetime

                season = datetime.now(UTC).strftime('%Y-%m')
                text = text.format(season=season)
        except Exception:
            text = text.replace('{season}', '?')

        try:
            if status_type == 'streaming':
                url = status_def.get('url', STREAMING_URL)
                return nextcord.Streaming(name=text, url=url)
            if status_type == 'listening':
                return nextcord.Activity(type=nextcord.ActivityType.listening, name=text)
            if status_type == 'playing':
                return nextcord.Game(name=text)
            # Default: watching
            return nextcord.Activity(type=nextcord.ActivityType.watching, name=text)
        except Exception as exc:
            logger.warning('Failed to build activity for type=%s text=%r: %s', status_type, text, exc)
            # Fallback to a simple watching activity
            return nextcord.Activity(type=nextcord.ActivityType.watching, name='VEKA')

    @tasks.loop(seconds=ROTATION_INTERVAL)
    async def rotate_status(self):
        """Rotate to the next status."""
        status_def = STATUSES[self._status_index]
        try:
            activity = await self._build_activity(status_def)
            await self.bot.change_presence(activity=activity)
            logger.debug(
                'Status [%d/%d] set: %s',
                self._status_index + 1,
                len(STATUSES),
                status_def.get('text', '?'),
            )
        except Exception as exc:
            logger.warning(
                'Failed to update status [%d/%d] (%s): %s',
                self._status_index + 1,
                len(STATUSES),
                status_def.get('text', '?'),
                exc,
            )
        finally:
            self._status_index = (self._status_index + 1) % len(STATUSES)

    @rotate_status.before_loop
    async def before_rotate_status(self):
        await self.bot.wait_until_ready()
        # Set initial status immediately
        status_def = STATUSES[0]
        try:
            activity = await self._build_activity(status_def)
            await self.bot.change_presence(activity=activity)
        except Exception as exc:
            logger.warning('Failed to set initial status: %s', exc)
        finally:
            self._status_index = 1


def setup(bot: commands.Bot):
    bot.add_cog(StatusRotator(bot))
    logging.getLogger('VEKA').info('Loaded cog: src.cogs.status')
    return True
