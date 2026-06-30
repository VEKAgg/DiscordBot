import logging

import nextcord
from nextcord.ext import commands

from src.utils.embeds import success_embed
from src.utils.safety import safe_command, safe_send, safe_slash_command

logger = logging.getLogger('VEKA.admin.basic')


class Basic(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        logger.info('Admin basic cog initialized')

    @commands.command(name='hello')
    @safe_command()
    async def hello(self, ctx):
        """Send a hello message"""
        embed = await success_embed(
            title='Hello!',
            description=f'Hello there, {ctx.author.mention}! How can I help you today?',
            contributor_source=__name__,
            user=ctx.author,
            guild=ctx.guild,
        )
        await ctx.send(embed=embed)

    @commands.command(name='ping')
    @safe_command()
    async def ping(self, ctx):
        """Check the bot's response time"""
        latency = round(self.bot.latency * 1000)
        embed = await success_embed(
            title='Pong!',
            description=f'Bot latency: **{latency}ms**',
            contributor_source=__name__,
            user=ctx.author,
            guild=ctx.guild,
        )
        await ctx.send(embed=embed)

    @nextcord.slash_command(name='hello', description='Get a greeting from the bot')
    @safe_slash_command()
    async def hello_slash(self, interaction: nextcord.Interaction):
        """Send a hello message using slash command"""
        embed = await success_embed(
            title='Hello!',
            description=f'Hello there, {interaction.user.mention}! How can I help you today?',
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        await safe_send(interaction, embed=embed, ephemeral=True)

    @nextcord.slash_command(name='ping', description="Check the bot's response time")
    @safe_slash_command()
    async def ping_slash(self, interaction: nextcord.Interaction):
        """Check the bot's response time using slash command"""
        latency = round(self.bot.latency * 1000)
        embed = await success_embed(
            title='Pong!',
            description=f'Bot latency: **{latency}ms**',
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        await safe_send(interaction, embed=embed, ephemeral=True)


def setup(bot):
    bot.add_cog(Basic(bot))
    logging.getLogger('VEKA').info('Loaded cog: src.cogs.admin.basic')
    return True
