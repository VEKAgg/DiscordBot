"""
Panic / Lockdown Command
Founders can toggle server lockdown, which sends a critical alert to the staff channel with @everyone ping.
"""

import logging

import nextcord
from nextcord.ext import commands

from src.config.config import STAFF_CHANNEL_ID
from src.utils.embeds import alert_embed
from src.utils.safety import safe_send
from src.utils.security.rbac import require_founder

logger = logging.getLogger('VEKA.admin.moderation')


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.lockdown_active = False

    async def panic_slash(self, interaction: nextcord.Interaction):
        """Toggle server lockdown. Sends critical alert to staff channel with @everyone."""
        await self._toggle_lockdown(interaction)

    @commands.command(name='panic')
    @require_founder()
    async def panic_prefix(self, ctx):
        """Toggle server lockdown (Founder only)"""
        await self._toggle_lockdown(ctx)

    async def lockdown_slash(self, interaction: nextcord.Interaction):
        """Alias for /panic"""
        await self._toggle_lockdown(interaction)

    @commands.command(name='lockdown')
    @require_founder()
    async def lockdown_prefix(self, ctx):
        """Alias for !panic"""
        await self._toggle_lockdown(ctx)

    async def _toggle_lockdown(self, target):
        self.lockdown_active = not self.lockdown_active
        status = 'ACTIVATED' if self.lockdown_active else 'DEACTIVATED'

        # Send to staff channel with @everyone
        staff_channel = self.bot.get_channel(STAFF_CHANNEL_ID)
        if staff_channel:
            embed = await alert_embed(
                title=f'LOCKDOWN {status}',
                description=(
                    f'Server lockdown has been **{status.lower()}** by a Founder.\n\n'
                    f'**All non-essential operations are suspended.**'
                    if self.lockdown_active
                    else f'Server lockdown has been **{status.lower()}**.\n\nNormal operations have resumed.'
                ),
                severity='CRITICAL' if self.lockdown_active else 'INFO',
            )
            try:
                await staff_channel.send(content='@everyone', embed=embed)
            except Exception as e:
                logger.error('Failed to send lockdown alert: %s', e)

        # Respond to the command user
        embed = await alert_embed(
            title=f'Lockdown {status}',
            description=f'Server lockdown has been **{status.lower()}**.',
            severity='CRITICAL' if self.lockdown_active else 'INFO',
        )
        await safe_send(target, embed=embed, ephemeral=True)


def setup(bot):
    bot.add_cog(Moderation(bot))
    logging.getLogger('VEKA').info('Loaded cog: src.cogs.admin.moderation')
