import discord
import psutil
from discord import app_commands
from discord.ext import commands
from utils.logger import setup_logger
import traceback

logger = setup_logger()

class SystemMonitor(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="status", description="Check system health")
    async def status(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        try:
            logger.info(f"Status command executed by {interaction.user} in {interaction.guild.name}")
            
            # Gather system metrics
            cpu_usage = psutil.cpu_percent()
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            embed = discord.Embed(
                title="🖥️ System Health Status",
                description="Current system metrics:",
                color=discord.Color.green()
            )
            
            embed.add_field(
                name="CPU Usage",
                value=f"```{cpu_usage}%```",
                inline=True
            )
            embed.add_field(
                name="Memory Usage",
                value=f"```{memory.percent}%```",
                inline=True
            )
            embed.add_field(
                name="Disk Usage",
                value=f"```{disk.percent}%```",
                inline=True
            )
            
            logger.info(f"System metrics - CPU: {cpu_usage}%, Memory: {memory.percent}%, Disk: {disk.percent}%")
            await interaction.followup.send(embed=embed)
            
        except psutil.Error as e:
            error_msg = f"System monitoring error: {str(e)}\n{traceback.format_exc()}"
            logger.error(error_msg)
            await interaction.followup.send("❌ Failed to gather system metrics. Check logs for details.")
        except Exception as e:
            error_msg = f"Error in status command: {str(e)}\n{traceback.format_exc()}"
            logger.error(error_msg)
            await interaction.followup.send(f"❌ An unexpected error occurred: `{str(e)}`")

    @app_commands.command(name="debug", description="Run diagnostic tests")
    @app_commands.default_permissions(administrator=True)
    async def debug(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        try:
            logger.info(f"Debug command executed by {interaction.user} in {interaction.guild.name}")
            diagnostics = await self.run_diagnostics()
            await interaction.followup.send(embed=diagnostics)
            logger.info("Debug diagnostics completed successfully")
        except Exception as e:
            error_msg = f"Error in debug command: {str(e)}\n{traceback.format_exc()}"
            logger.error(error_msg)
            await interaction.followup.send(f"❌ Failed to run diagnostics: `{str(e)}`")

async def setup(bot: commands.Bot):
    await bot.add_cog(SystemMonitor(bot)) 