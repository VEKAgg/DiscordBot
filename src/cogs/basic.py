import nextcord
from nextcord.ext import commands
import logging

logger = logging.getLogger('VEKA.basic')

class Basic(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        logger.info("Basic cog initialized")



    @nextcord.slash_command(name="ping", description="Check the bot's response time")
    async def ping_slash(self, interaction: nextcord.Interaction):
        """Check the bot's response time using slash command"""
        latency = round(self.bot.latency * 1000)
        await interaction.response.send_message(f"🏓 Pong! Latency: {latency}ms")

    @nextcord.slash_command(name="hello", description="Get a greeting from the bot")
    async def hello_slash(self, interaction: nextcord.Interaction):
        """Send a hello message using slash command"""
        await interaction.response.send_message(f"👋 Hello, {interaction.user.mention}!")

def setup(bot):
    bot.add_cog(Basic(bot))
    return True 