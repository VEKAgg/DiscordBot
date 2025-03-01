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
        await ctx.send(f"👋 Hello, {ctx.author.mention}!")

    @commands.command(name="ping")
    async def ping(self, ctx):
        """Check the bot's response time"""
        latency = round(self.bot.latency * 1000)
        await ctx.send(f"🏓 Pong! Latency: {latency}ms")

    @nextcord.slash_command(name="hello", description="Get a greeting from the bot")
    async def hello_slash(self, interaction: nextcord.Interaction):
        """Send a hello message using slash command"""
        await interaction.response.send_message(f"👋 Hello, {interaction.user.mention}!")

def setup(bot):
    bot.add_cog(Basic(bot))
    return True 