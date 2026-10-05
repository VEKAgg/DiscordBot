"""
Notifications Cog
Daily bump reminder and broadcast commands
"""

import logging
from datetime import time, timedelta, timezone

import nextcord
from nextcord.ext import commands, tasks

from src.config.config import (
    DAILY_BUMP_HOUR,
    DAILY_BUMP_MINUTE,
    IST_UTC_OFFSET,
    MAIN_GUILD_ID,
    NOTIFICATION_SQUAD_ROLE_NAME,
)
from src.services.guild_settings_service import guild_settings_service
from src.utils.embeds import error_embed, info_embed, success_embed
from src.utils.safety import safe_send
from src.utils.security.rbac import require_founder, require_staff

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


class Notifications(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_ready(self):
        if not self.daily_bump.is_running():
            self.daily_bump.start()

    def cog_unload(self):
        self.daily_bump.cancel()

    # ==================== DAILY BUMP REMINDER ====================

    @tasks.loop(time=_BUMP_TIME)
    async def daily_bump(self):
        """Send the bump reminder in the main guild at DAILY_BUMP_HOUR:MINUTE IST."""
        channel = await _public_channel(self.bot.get_guild(MAIN_GUILD_ID))
        if not channel:
            logger.warning('Daily bump: public bot commands channel not configured for main guild %s', MAIN_GUILD_ID)
            return

        mention, allowed = _squad_ping(channel.guild)
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

        try:
            await channel.send(content=mention, embed=embed, allowed_mentions=allowed)
            logger.info('Daily bump reminder sent')
        except Exception as e:
            logger.error('Failed to send daily bump reminder: %s', e)

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
