import logging
from nextcord.ext import commands

logger = logging.getLogger('VEKA.workshops')


class WorkshopManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info('Workshops cog is present but disabled in this configuration.')

    @commands.command(name='workshop_disabled')
    async def workshop_disabled(self, ctx):
        await ctx.send('Workshop management is currently disabled.')

    @nextcord.slash_command(name='workshop_status', description='Check workshop feature availability')
    async def workshop_status(self, interaction: nextcord.Interaction):
        await interaction.response.send_message('Workshops are currently disabled.', ephemeral=True)


def setup(bot):
    bot.add_cog(WorkshopManager(bot))
    logging.getLogger('VEKA').info('Loaded stub cog: src.cogs.workshops.workshop_manager')
