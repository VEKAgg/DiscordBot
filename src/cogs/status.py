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

STREAMING_URL = 'https://veka.gg'

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
    {'type': 'watching', 'text': 'over the marketplace'},
    {'type': 'playing', 'text': 'with slash commands'},
]

ROTATION_INTERVAL = 10  # seconds between status changes


def _format_uptime(start_time: datetime) -> str:
    """Format uptime as a human-readable string."""
    try:
        delta = datetime.now(UTC) - start_time
    except TypeError:
        return 'unknown'
    total_seconds = int(delta.total_seconds())
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
    for guild in bot.guilds:
        count = guild.member_count
        if count:
            total += count
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

    def _build_activity(self, status_def: dict) -> nextcord.Activity | nextcord.Streaming | nextcord.Game:
        """Build a nextcord activity from a status definition."""
        text = status_def['text']

        # Format dynamic placeholders
        if '{guilds}' in text:
            text = text.format(guilds=len(self.bot.guilds))
        if '{users}' in text:
            text = text.format(users=f'{_get_total_users(self.bot):,}')
        if '{uptime}' in text:
            text = text.format(uptime=_format_uptime(runtime_state.startup_time))

        status_type = status_def['type']

        if status_type == 'streaming':
            return nextcord.Streaming(name=text, url=status_def.get('url', STREAMING_URL))
        if status_type == 'listening':
            return nextcord.Activity(type=nextcord.ActivityType.listening, name=text)
        if status_type == 'playing':
            return nextcord.Game(name=text)
        # Default: watching
        return nextcord.Activity(type=nextcord.ActivityType.watching, name=text)

    @tasks.loop(seconds=ROTATION_INTERVAL)
    async def rotate_status(self):
        """Rotate to the next status."""
        status_def = STATUSES[self._status_index]
        try:
            activity = self._build_activity(status_def)
            await self.bot.change_presence(activity=activity)
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
            activity = self._build_activity(status_def)
            await self.bot.change_presence(activity=activity)
        except Exception as exc:
            logger.warning('Failed to set initial status: %s', exc)
        finally:
            self._status_index = 1


def setup(bot: commands.Bot):
    bot.add_cog(StatusRotator(bot))
    logging.getLogger('VEKA').info('Loaded cog: src.cogs.status')
    return True
