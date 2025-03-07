import nextcord
from nextcord.ext import commands
import logging

logger = logging.getLogger('VEKA.basic')

class Basic(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        logger.info("Basic cog initialized")

    @commands.command(name="hello")
    async def hello(self, ctx):
        """Send a hello message"""
        embed = nextcord.Embed(
            title="👋 Hello!",
            description=f"Hello there, {ctx.author.mention}! How can I help you today?",
            color=nextcord.Color.orange()
        )
        await ctx.send(embed=embed)

    @commands.command(name="ping")
    async def ping(self, ctx):
        """Check the bot's response time"""
        latency = round(self.bot.latency * 1000)
        embed = nextcord.Embed(
            title="🏓 Pong!",
            description=f"Bot latency: **{latency}ms**",
            color=nextcord.Color.orange()
        )
        await ctx.send(embed=embed)

    @nextcord.slash_command(name="hello", description="Get a greeting from the bot")
    async def hello_slash(self, interaction: nextcord.Interaction):
        """Send a hello message using slash command"""
        embed = nextcord.Embed(
            title="👋 Hello!",
            description=f"Hello there, {interaction.user.mention}! How can I help you today?",
            color=nextcord.Color.orange()
        )
        await interaction.response.send_message(embed=embed)

def setup(bot):
    bot.add_cog(Basic(bot))
    logging.getLogger('VEKA').info("Loaded cog: src.cogs.basic")
    return True