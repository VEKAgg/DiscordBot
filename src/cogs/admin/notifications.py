"""
Notifications Cog
Daily bump reminder and broadcast commands
"""

import logging
from datetime import datetime, timedelta, timezone

import nextcord
from nextcord.ext import commands, tasks

from src.config.config import (
    DAILY_BUMP_HOUR,
    DAILY_BUMP_MINUTE,
    IST_UTC_OFFSET,
    NOTIFICATION_SQUAD_ROLE_NAME,
    PUBLIC_BOT_COMMANDS_CHANNEL_ID,
)
from src.utils.embeds import error_embed, info_embed, success_embed
from src.utils.safety import safe_send, safe_slash_command
from src.utils.security.rbac import require_founder, require_staff

logger = logging.getLogger('VEKA.admin.notifications')


class Notifications(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.daily_bump.start()

    def cog_unload(self):
        self.daily_bump.cancel()

    # ==================== DAILY BUMP REMINDER ====================

    @tasks.loop(minutes=1)
    async def daily_bump(self):
        """Check if it's 6pm IST and send bump reminder"""
        now = datetime.now(timezone(timedelta(hours=IST_UTC_OFFSET)))
        if now.hour == DAILY_BUMP_HOUR and now.minute == DAILY_BUMP_MINUTE:
            channel = self.bot.get_channel(PUBLIC_BOT_COMMANDS_CHANNEL_ID)
            if not channel:
                logger.warning('Public bot commands channel not found: %s', PUBLIC_BOT_COMMANDS_CHANNEL_ID)
                return

            # Find the notification squad role
            guild = channel.guild
            squad_role = nextcord.utils.get(guild.roles, name=NOTIFICATION_SQUAD_ROLE_NAME)

            role_mention = squad_role.mention if squad_role else f'@{NOTIFICATION_SQUAD_ROLE_NAME}'

            embed = await info_embed(
                title='Daily Bump Reminder',
                description=(
                    f'{role_mention}\n\n'
                    "It's time to bump the server! Use `/bump` to keep our community growing.\n\n"
                    'Every bump helps new members discover us. Thank you for your support!'
                ),
                contributor_source=__name__,
            )
            embed.set_footer(text=f'Daily reminder at {DAILY_BUMP_HOUR}:00 IST')

            try:
                await channel.send(embed=embed)
                logger.info('Daily bump reminder sent')
            except Exception as e:
                logger.error('Failed to send daily bump reminder: %s', e)

    @daily_bump.before_loop
    async def before_daily_bump(self):
        await self.bot.wait_until_ready()

    # ==================== STAFF COMMANDS ====================

    @nextcord.slash_command(name='ping_squad', description='Ping notification squad (Staff+)')
    @require_staff()
    @safe_slash_command()
    async def ping_squad_slash(self, interaction: nextcord.Interaction, message: str = 'Time to bump the server!'):
        """Ping notification squad in public bot commands channel"""
        channel = self.bot.get_channel(PUBLIC_BOT_COMMANDS_CHANNEL_ID)
        if not channel:
            embed = await error_embed(
                'Channel Not Found', 'Public bot commands channel not found.', contributor_source=__name__
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        guild = interaction.guild
        squad_role = nextcord.utils.get(guild.roles, name=NOTIFICATION_SQUAD_ROLE_NAME)
        role_mention = squad_role.mention if squad_role else f'@{NOTIFICATION_SQUAD_ROLE_NAME}'

        embed = await info_embed(
            title='Squad Ping',
            description=f'{role_mention}\n\n{message}',
            contributor_source=__name__,
        )

        try:
            await channel.send(embed=embed)
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
    @require_staff()
    async def ping_squad_prefix(self, ctx, *, message: str = 'Time to bump the server!'):
        """Ping notification squad (Staff+)"""
        channel = self.bot.get_channel(PUBLIC_BOT_COMMANDS_CHANNEL_ID)
        if not channel:
            await ctx.send('Public bot commands channel not found.')
            return

        guild = ctx.guild
        squad_role = nextcord.utils.get(guild.roles, name=NOTIFICATION_SQUAD_ROLE_NAME)
        role_mention = squad_role.mention if squad_role else f'@{NOTIFICATION_SQUAD_ROLE_NAME}'

        embed = await info_embed(
            title='Squad Ping',
            description=f'{role_mention}\n\n{message}',
            contributor_source=__name__,
        )

        try:
            await channel.send(embed=embed)
            await ctx.send(f'Notification squad pinged in {channel.mention}.')
        except Exception as e:
            logger.error('Failed to ping squad: %s', e)
            await ctx.send('Could not send the ping.')

    # ==================== FOUNDER COMMANDS ====================

    @nextcord.slash_command(name='broadcast', description='Send announcement to a channel (Founder only)')
    @require_founder()
    @safe_slash_command()
    async def broadcast_slash(
        self,
        interaction: nextcord.Interaction,
        channel: nextcord.TextChannel,
        message: str,
    ):
        """Send an announcement to any channel"""
        embed = await info_embed(
            title='Announcement',
            description=message,
            contributor_source=__name__,
        )
        embed.set_author(name='VEKA Bot Broadcast', icon_url=self.bot.user.avatar.url if self.bot.user.avatar else None)

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
        embed = await info_embed(
            title='Announcement',
            description=message,
            contributor_source=__name__,
        )
        embed.set_author(name='VEKA Bot Broadcast', icon_url=self.bot.user.avatar.url if self.bot.user.avatar else None)

        try:
            await channel.send(embed=embed)
            await ctx.send(f'Announcement sent to {channel.mention}.')
        except Exception as e:
            logger.error('Failed to broadcast: %s', e)
            await ctx.send('Could not send the announcement.')


def setup(bot):
    bot.add_cog(Notifications(bot))
    logging.getLogger('VEKA').info('Loaded cog: src.cogs.admin.notifications')
