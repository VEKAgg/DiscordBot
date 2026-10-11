"""
Notifications Cog
Daily bump reminder and broadcast commands
"""

import logging
from datetime import UTC, datetime, time, timedelta, timezone

import nextcord
from nextcord.ext import commands, tasks

from src.config.config import (
    DAILY_BUMP_HOUR,
    DAILY_BUMP_MINUTE,
    IST_UTC_OFFSET,
    NOTIFICATION_SQUAD_ROLE_NAME,
)
from src.services.guild_settings_service import guild_settings_service
from src.utils.embeds import error_embed, info_embed, success_embed
from src.utils.outbound import outbound
from src.utils.safety import DatabaseUnavailableError, safe_background_task, safe_send
from src.utils.security.rbac import require_founder, require_staff
from src.utils.ttlcache import TTLDict

logger = logging.getLogger('VEKA.admin.notifications')

_BUMP_TIME = time(
    hour=DAILY_BUMP_HOUR,
    minute=DAILY_BUMP_MINUTE,
    tzinfo=timezone(timedelta(hours=IST_UTC_OFFSET)),
)


async def _public_channel(guild: nextcord.Guild | None) -> nextcord.TextChannel | None:
    """Resolve the public bot-commands channel *inside this guild only* (no cross-guild fallback, audit H-07)."""
    if guild is None:
        return None
    try:
        channel = await guild_settings_service.resolve_channel(guild, 'public_commands_channel_id')
    except Exception:
        logger.debug('Could not resolve public commands channel for guild %s', guild.id, exc_info=True)
        return None
    return channel if isinstance(channel, nextcord.TextChannel) else None


def _squad_ping(guild: nextcord.Guild) -> tuple[str, nextcord.AllowedMentions]:
    """Role mention must be in message content (not an embed) to notify; only that role may be pinged."""
    role = nextcord.utils.get(guild.roles, name=NOTIFICATION_SQUAD_ROLE_NAME)
    if role is None:
        return f'@{NOTIFICATION_SQUAD_ROLE_NAME}', nextcord.AllowedMentions.none()
    return role.mention, nextcord.AllowedMentions(everyone=False, users=False, roles=[role])


SQUAD_PING_COOLDOWN_SECONDS = 600  # one notification-squad role ping per guild per 10 minutes


class Notifications(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._squad_pings: TTLDict[int, bool] = TTLDict(ttl=SQUAD_PING_COOLDOWN_SECONDS, maxsize=5000)

    def _claim_squad_ping(self, guild_id: int) -> bool:
        """True if this guild may ping the squad now (and starts its cooldown)."""
        if guild_id in self._squad_pings:
            return False
        self._squad_pings.set(guild_id, True)
        return True

    async def cog_ready(self):
        if not self.daily_bump.is_running():
            self.daily_bump.start()

    def cog_unload(self):
        self.daily_bump.cancel()

    # ==================== DAILY BUMP REMINDER ====================

    @tasks.loop(time=_BUMP_TIME)
    @safe_background_task(name='daily_bump')
    async def daily_bump(self):
        """Visit each guild; only explicitly opted-in, configured guilds may send."""
        for guild in tuple(self.bot.guilds):
            try:
                await self._daily_bump_for_guild(guild)
            except DatabaseUnavailableError:
                raise  # shared DB outage: do not query every remaining guild or hide task health failures
            except Exception as exc:
                logger.warning('Daily bump failed for guild %s: %s', guild.id, type(exc).__name__)

    async def _daily_bump_for_guild(self, guild):
        settings = await guild_settings_service.get_settings(guild.id)
        if not settings.bump_reminder_enabled or settings.public_commands_channel_id is None:
            return
        # Explicit channel only: deprecated main-server fallbacks must not enable reminders.
        channel = guild.get_channel(settings.public_commands_channel_id)
        if not isinstance(channel, nextcord.TextChannel) or channel.guild.id != guild.id:
            return
        mention, allowed = _squad_ping(guild)
        embed = await info_embed(
            title='Daily Bump Reminder',
            description=(
                "It's time to bump the server!\n\n"
                'Use `/bump` with these bots to keep our community growing:\n'
                '\u2022 <@302050872383242240> — Discord Bump Bot\n'
                '\u2022 <@1222548162741538938> — Discadia Bot\n\n'
                'Every bump helps new members discover us. Thank you for your support!'
            ),
            contributor_source=__name__,
        )
        embed.set_footer(text=f'Daily reminder at {DAILY_BUMP_HOUR}:{DAILY_BUMP_MINUTE:02d} IST')

        outcome = await outbound.send(
            channel,
            kind='bump_reminder',
            content=mention,
            embed=embed,
            allowed_mentions=allowed,
            dedupe_key=f'bump-reminder:{guild.id}:{datetime.now(UTC).date().isoformat()}',
        )
        if outcome.ok:
            logger.info('Daily bump reminder sent for guild %s', guild.id)
        else:
            logger.info('Daily bump reminder not sent for guild %s: %s', guild.id, outcome.status.value)

    @daily_bump.before_loop
    async def before_daily_bump(self):
        await self.bot.wait_until_ready()

    # ==================== STAFF COMMANDS (delegated via /admin group) ====================

    async def ping_squad_slash(self, interaction: nextcord.Interaction, message: str = 'Time to bump the server!'):
        """Ping notification squad in this server's public bot commands channel"""
        channel = await _public_channel(interaction.guild)
        if not channel:
            embed = await error_embed(
                'Channel Not Configured',
                'No public bot commands channel is configured for this server. Use `/setup set` first.',
                contributor_source=__name__,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        if not self._claim_squad_ping(channel.guild.id):
            embed = await error_embed(
                'Cooldown',
                f'The notification squad can be pinged once every {SQUAD_PING_COOLDOWN_SECONDS // 60} minutes.',
                contributor_source=__name__,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        mention, allowed = _squad_ping(channel.guild)
        embed = await info_embed(title='Squad Ping', description=message[:4000], contributor_source=__name__)

        try:
            await channel.send(content=mention, embed=embed, allowed_mentions=allowed)
            embed = await success_embed(
                title='Sent',
                description=f'Notification squad pinged in {channel.mention}.',
                contributor_source=__name__,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
        except Exception as e:
            logger.error('Failed to ping squad: %s', e)
            embed = await error_embed('Send Failed', 'Could not send the ping.', contributor_source=__name__)
            await safe_send(interaction, embed=embed, ephemeral=True)

    @commands.command(name='pingsquad')
    @commands.guild_only()
    @require_staff()
    async def ping_squad_prefix(self, ctx, *, message: str = 'Time to bump the server!'):
        """Ping notification squad (Staff+)"""
        channel = await _public_channel(ctx.guild)
        if not channel:
            await ctx.send('No public bot commands channel is configured for this server. Use `!setup` first.')
            return

        if not self._claim_squad_ping(channel.guild.id):
            await ctx.send(
                f'The notification squad can be pinged once every {SQUAD_PING_COOLDOWN_SECONDS // 60} minutes.'
            )
            return

        mention, allowed = _squad_ping(channel.guild)
        embed = await info_embed(title='Squad Ping', description=message[:4000], contributor_source=__name__)

        try:
            await channel.send(content=mention, embed=embed, allowed_mentions=allowed)
            await ctx.send(f'Notification squad pinged in {channel.mention}.')
        except Exception as e:
            logger.error('Failed to ping squad: %s', e)
            await ctx.send('Could not send the ping.')

    # ==================== FOUNDER COMMANDS (delegated via /admin group) ====================

    async def broadcast_slash(
        self,
        interaction: nextcord.Interaction,
        channel: nextcord.TextChannel,
        message: str,
    ):
        """Send an announcement to any channel"""
        embed = nextcord.Embed(description=message, color=nextcord.Color.orange())

        try:
            await channel.send(embed=embed)
            embed = await success_embed(
                title='Broadcast Sent',
                description=f'Announcement sent to {channel.mention}.',
                contributor_source=__name__,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
        except Exception as e:
            logger.error('Failed to broadcast: %s', e)
            embed = await error_embed(
                'Broadcast Failed', 'Could not send the announcement.', contributor_source=__name__
            )
            await safe_send(interaction, embed=embed, ephemeral=True)

    @commands.command(name='broadcast')
    @require_founder()
    async def broadcast_prefix(self, ctx, channel: nextcord.TextChannel, *, message: str):
        """Send announcement to a channel (Founder only)"""
        embed = nextcord.Embed(description=message, color=nextcord.Color.orange())

        try:
            await channel.send(embed=embed)
            await ctx.send(f'Announcement sent to {channel.mention}.')
        except Exception as e:
            logger.error('Failed to broadcast: %s', e)
            await ctx.send('Could not send the announcement.')


def setup(bot):
    bot.add_cog(Notifications(bot))
    logging.getLogger('VEKA').info('Loaded cog: src.cogs.admin.notifications')
