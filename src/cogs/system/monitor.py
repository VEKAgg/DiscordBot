import discord
import psutil
from discord import app_commands
from discord.ext import commands
from utils.logger import setup_logger

logger = setup_logger()

class SystemMonitor(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="status", description="Check system health")
    async def status(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        try:
            # Gather system metrics
            cpu_usage = psutil.cpu_percent()
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            embed = discord.Embed(
                title="System Health Status",
                color=discord.Color.green()
            )
            
            embed.add_field(
                name="CPU Usage",
                value=f"{cpu_usage}%",
                inline=True
            )
            embed.add_field(
                name="Memory Usage",
                value=f"{memory.percent}%",
                inline=True
            )
            embed.add_field(
                name="Disk Usage",
                value=f"{disk.percent}%",
                inline=True
            )
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in status command: {str(e)}")
            await interaction.followup.send("An error occurred while checking system health.")

    @app_commands.command(name="debug", description="Run diagnostic tests")
    @app_commands.default_permissions(administrator=True)
    async def debug(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        try:
            # Run diagnostics
            diagnostics = await self.run_diagnostics()
            await interaction.followup.send(embed=diagnostics)
        except Exception as e:
            logger.error(f"Error in debug command: {str(e)}")
            await interaction.followup.send("An error occurred while running diagnostics.")

async def setup(bot: commands.Bot):
    await bot.add_cog(SystemMonitor(bot)) 