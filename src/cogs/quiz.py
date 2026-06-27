import logging

import nextcord
from nextcord.ext import commands

logger = logging.getLogger('VEKA.quiz')


class Quiz(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info('Quiz cog is present but disabled in this configuration.')

    @commands.command(name='quiz_disabled')
    async def quiz_disabled(self, ctx):
        await ctx.send('Quiz features are currently disabled.')

    @nextcord.slash_command(name='quiz_status', description='Check quiz feature availability')
    async def quiz_status(self, interaction: nextcord.Interaction):
        await interaction.response.send_message('Quiz features are currently disabled.', ephemeral=True)


def setup(bot):
    bot.add_cog(Quiz(bot))
    logging.getLogger('VEKA').info('Loaded stub cog: src.cogs.quiz')
