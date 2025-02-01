import nextcord
from nextcord.ext import commands, tasks
import psutil
from datetime import datetime, timezone, timedelta
import logging

# Get logger for this module
logger = logging.getLogger('nextcord.system.tasks')

class BackgroundTasks(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db
        self.last_command_time = datetime.now(timezone.utc)
        self.alert_system = None
        logger.info("Initializing background tasks")
        self.background_check.start()

    def cog_unload(self):
        try:
            self.background_check.cancel()
            logger.info("Background tasks stopped")
        except Exception as e:
            logger.exception("Error stopping background tasks")

    @commands.Cog.listener()
    async def on_command(self, ctx):
        try:
            self.last_command_time = datetime.now(timezone.utc)
            logger.debug(f"Command usage tracked: {ctx.command}")
        except Exception as e:
            logger.exception("Error tracking command usage")

    @commands.Cog.listener()
    async def on_interaction(self, interaction: nextcord.Interaction):
        try:
            if interaction.type == nextcord.InteractionType.application_command:
                self.last_command_time = datetime.now(timezone.utc)
                logger.debug(f"Slash command usage tracked: {interaction.command.name}")
        except Exception as e:
            logger.exception("Error tracking interaction")

    async def get_alert_system(self):
        try:
            if not self.alert_system:
                self.alert_system = self.bot.get_cog("AlertSystem")
                if self.alert_system:
                    logger.debug("AlertSystem cog loaded")
                else:
                    logger.warning("AlertSystem cog not found")
            return self.alert_system
        except Exception as e:
            logger.exception("Error getting alert system")
            return None

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

            logger.debug(f"System health check - CPU: {cpu_usage}%, Memory: {memory.percent}%")
            logger.debug(f"Memory check completed")
            logger.info(f"Error rate check - Found {recent_errors} errors in last 5 minutes")

        except Exception as e:
            logger.exception("Critical error in background check")

    @background_check.before_loop
    async def before_background_check(self):
        try:
            await self.bot.wait_until_ready()
            logger.info("Background check loop ready to start")
        except Exception as e:
            logger.exception("Error in background check setup")

async def setup(bot: commands.Bot):
    try:
        await bot.add_cog(BackgroundTasks(bot))
        logger.info("BackgroundTasks cog loaded successfully")
    except Exception as e:
        logger.exception("Failed to load BackgroundTasks cog")
        raise 