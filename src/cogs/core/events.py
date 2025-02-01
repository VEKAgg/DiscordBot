import nextcord
from nextcord.ext import commands
import logging
from datetime import datetime, timezone
from nextcord import Interaction
import asyncio

# Get logger for this module
logger = logging.getLogger('nextcord.core.events')

class CoreEvents(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db
        self._ready = asyncio.Event()
        self.task_status = {}
        self.task_monitor = None
        logger.info("CoreEvents cog initialized")

    async def cog_error(self, ctx: commands.Context, error: Exception):
        """Global error handler for the cog"""
        if isinstance(error, commands.CommandError):
            logger.error(f"Command error in {ctx.command}: {str(error)}")
        else:
            logger.exception("Unhandled error in Events cog", exc_info=error)

    async def cog_load(self):
        """Start task monitoring when cog loads"""
        self.task_monitor = asyncio.create_task(self.monitor_tasks())
        logger.info("Task monitoring started")

    async def cog_unload(self):
        """Clean up task monitor"""
        if self.task_monitor:
            self.task_monitor.cancel()
            logger.info("Task monitoring stopped")

    async def monitor_tasks(self):
        """Monitor background tasks and attempt recovery"""
        while True:
            try:
                await asyncio.sleep(60)  # Check every minute
                
                # Get CoreCommands cog for task checking
                core_commands = self.bot.get_cog("CoreCommands")
                if not core_commands:
                    logger.warning("CoreCommands cog not found for task monitoring")
                    continue

                # Check scheduler status
                if not core_commands.scheduler.running:
                    logger.error("Scheduler stopped - attempting restart")
                    try:
                        core_commands.scheduler.start()
                        logger.info("Scheduler successfully restarted")
                    except Exception as e:
                        logger.exception("Failed to restart scheduler")

                # Check individual tasks
                for job in core_commands.scheduler.get_jobs():
                    last_run = job.next_run_time - job.trigger.interval
                    if last_run:
                        self.task_status[job.id] = {
                            "last_run": last_run,
                            "next_run": job.next_run_time,
                            "status": "running" if not job.pending else "pending"
                        }
                        
                        # Alert if task is stuck
                        if job.pending and (datetime.now(timezone.utc) - last_run).total_seconds() > 300:
                            logger.warning(f"Task {job.id} appears stuck - attempting recovery")
                            try:
                                job.reschedule()
                                logger.info(f"Successfully rescheduled {job.id}")
                            except Exception as e:
                                logger.exception(f"Failed to reschedule {job.id}")

                # Monitor price alerts task
                if hasattr(core_commands, "check_price_alerts"):
                    if core_commands.check_price_alerts.is_running():
                        self.task_status["price_alerts"] = {
                            "status": "running",
                            "last_iteration": core_commands.check_price_alerts.current_loop
                        }
                    else:
                        logger.warning("Price alerts task stopped - attempting restart")
                        try:
                            core_commands.check_price_alerts.restart()
                            logger.info("Price alerts task restarted")
                        except Exception as e:
                            logger.exception("Failed to restart price alerts task")

                # Log task status summary
                logger.info(f"Task status update: {self.task_status}")

            except asyncio.CancelledError:
                logger.info("Task monitoring cancelled")
                break
            except Exception as e:
                logger.exception("Error in task monitoring")
                await asyncio.sleep(30)  # Wait before retrying

    @commands.Cog.listener()
    async def on_ready(self):
        """Set up bot presence and status when ready"""
        try:
            # Update initial presence
            activity = nextcord.Activity(
                type=nextcord.ActivityType.watching,
                name=f"/help | {len(self.bot.guilds)} servers"
            )
            await self.bot.change_presence(
                activity=activity,
                status=nextcord.Status.online
            )
            logger.info("Bot presence updated successfully")

            # Log connection info
            logger.info(f"Connected to Discord as {self.bot.user} (ID: {self.bot.user.id})")
            logger.info(f"Connected to {len(self.bot.guilds)} guilds")
            logger.info(f"Serving {sum(g.member_count for g in self.bot.guilds)} users")
            logger.info(f"Loaded {len(self.bot.cogs)} cogs")
            logger.info(f"Registered {len(self.bot.commands)} commands")

            # Signal ready state
            self._ready.set()
            logger.info("Bot is fully ready!")

        except Exception as e:
            logger.exception("Failed to complete ready sequence")
            self._ready.set()  # Set ready even on failure to prevent hanging

    async def wait_until_ready(self):
        """Wait until the bot is fully ready"""
        await self._ready.wait()

    @commands.Cog.listener()
    async def on_message(self, message: nextcord.Message):
        """Handle message events and bot mentions"""
        if message.author.bot:
            return

        try:
            # Respond to bot mentions without a command
            if self.bot.user in message.mentions and len(message.content.split()) == 1:
                embed = nextcord.Embed(
                    title="👋 Hello!",
                    description=(
                        f"Hi {message.author.mention}! I'm VEKA Bot.\n\n"
                        "• Use `v help` for a list of commands\n"
                        "• All commands work with `v`, `/` or by mentioning me\n"
                        "• For support, join our [Support Server](https://discord.gg/vekabot)"
                    ),
                    color=nextcord.Color.blue()
                )
                await message.channel.send(embed=embed)
            logger.debug(f"Responded to mention from {message.author} in {message.guild}")
        except Exception as e:
            logger.exception(f"Error handling message in {message.guild}")

    @commands.Cog.listener()
    async def on_guild_join(self, guild: nextcord.Guild):
        """Handle bot joining a new server"""
        try:
            logger.info(f"Joined new guild: {guild.name} (ID: {guild.id})")
            
            # Initialize guild settings
            await self.db.guild_settings.update_one(
                {"guild_id": guild.id},
                {"$setOnInsert": {
                    "prefix": "!",
                    "locale": "en",
                    "disabled_commands": [],
                    "log_channel": None
                }},
                upsert=True
            )
            logger.info(f"Initialized settings for new guild: {guild.id}")
        except Exception as e:
            logger.exception(f"Failed to initialize settings for guild {guild.id}")

    @commands.Cog.listener()
    async def on_application_command_error(self, interaction: Interaction, error: Exception):
        """Global error handler for slash commands"""
        try:
            error_data = {
                "command": interaction.application_command.name,
                "user": f"{interaction.user} (ID: {interaction.user.id})",
                "guild": f"{interaction.guild.name} (ID: {interaction.guild.id})",
                "error": str(error)
            }
            
            logger.error("Slash command error occurred", extra={"error_data": error_data})
            
            await interaction.send(
                "An error occurred while executing the command.", 
                ephemeral=True
            )
        except Exception as e:
            logger.exception("Error in slash command error handler")

async def setup(bot: commands.Bot):
    if not isinstance(bot, commands.Bot):
        raise TypeError("This cog requires a commands.Bot instance")
    
    try:
        await bot.add_cog(CoreEvents(bot))
        logger.info("CoreEvents cog loaded successfully")
    except Exception as e:
        logger.exception("Failed to load CoreEvents cog")
        raise 