import logging
import nextcord
from nextcord.ext import commands

logger = logging.getLogger('VEKA.gamification')


class GamificationManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info('Gamification cog is present but disabled in this configuration.')

    @commands.command(name='gamification_disabled')
    async def gamification_disabled(self, ctx):
        await ctx.send('Gamification features are currently disabled.')

    @nextcord.slash_command(name='gamification_status', description='Check gamification availability')
    async def gamification_status(self, interaction: nextcord.Interaction):
        await interaction.response.send_message('Gamification features are currently disabled.', ephemeral=True)


def setup(bot):
    bot.add_cog(GamificationManager(bot))
    logging.getLogger('VEKA').info('Loaded stub cog: src.cogs.gamification.gamification_manager')
