import discord
from discord.ext import commands, tasks
from utils.database import Database
from utils.logger import setup_logger
import psutil
from datetime import datetime, timezone, timedelta
import traceback
from .alerts import AlertSystem

logger = setup_logger()

class BackgroundTasks(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = Database.db
        self.last_command_time = datetime.now(timezone.utc)
        self.alert_system = None
        self.background_check.start()

    def cog_unload(self):
        self.background_check.cancel()

    @commands.Cog.listener()
    async def on_command(self, ctx):
        self.last_command_time = datetime.now(timezone.utc)

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type == discord.InteractionType.application_command:
            self.last_command_time = datetime.now(timezone.utc)

    async def get_alert_system(self):
        if not self.alert_system:
            self.alert_system = self.bot.get_cog("AlertSystem")
        return self.alert_system

    @tasks.loop(minutes=5)
    async def background_check(self):
        try:
            alert_system = await self.get_alert_system()
            if not alert_system:
                logger.error("AlertSystem cog not found!")
                return

            # System health check
            cpu_usage = psutil.cpu_percent()
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')

            # Check CPU usage
            if cpu_usage > alert_system.alert_thresholds["cpu"]:
                for guild in self.bot.guilds:
                    await alert_system.send_alert(
                        guild.id,
                        "System Load",
                        "HIGH" if cpu_usage > 90 else "MEDIUM",
                        f"High CPU usage detected: {cpu_usage}%\nThis may impact bot performance."
                    )

            # Check memory usage
            if memory.percent > alert_system.alert_thresholds["memory"]:
                for guild in self.bot.guilds:
                    await alert_system.send_alert(
                        guild.id,
                        "Memory Usage",
                        "HIGH" if memory.percent > 95 else "MEDIUM",
                        f"High memory usage detected: {memory.percent}%\nConsider restarting the bot."
                    )

            # Check error rate
            recent_errors = await self.db.error_logs.count_documents({
                "timestamp": {"$gte": datetime.now(timezone.utc) - timedelta(minutes=5)}
            })

            if recent_errors > alert_system.alert_thresholds["error_rate"]:
                for guild in self.bot.guilds:
                    await alert_system.send_alert(
                        guild.id,
                        "Error Rate",
                        "CRITICAL",
                        f"High error rate detected: {recent_errors} errors in last 5 minutes\nCheck logs for details."
                    )

            # Add more checks as needed...

        except Exception as e:
            logger.error(f"Critical error in background check: {str(e)}\n{traceback.format_exc()}")

    @background_check.before_loop
    async def before_background_check(self):
        await self.bot.wait_until_ready()

async def setup(bot: commands.Bot):
    await bot.add_cog(BackgroundTasks(bot)) 