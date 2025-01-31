import discord
from discord.ext import commands
from utils.database import Database
from utils.logger import setup_logger
import traceback
from datetime import datetime, timezone
from typing import Optional, Literal
import psutil

logger = setup_logger()

class AlertSystem(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = Database.db
        self.alert_channels = {}  # Cache for alert channels
        self.alert_thresholds = {
            "cpu": 80,  # CPU usage above 80%
            "memory": 85,  # Memory usage above 85%
            "disk": 90,  # Disk usage above 90%
            "error_rate": 10,  # More than 10 errors in 5 minutes
            "latency": 500,  # Latency above 500ms
        }

    async def send_alert(self, guild_id: int, alert_type: str, severity: str, details: str):
        try:
            # Get alert channel
            if guild_id not in self.alert_channels:
                settings = await self.db.guild_settings.find_one({"guild_id": guild_id})
                self.alert_channels[guild_id] = settings.get("alert_channel_id") if settings else None

            channel_id = self.alert_channels[guild_id]
            if not channel_id:
                return

            channel = self.bot.get_channel(channel_id)
            if not channel:
                return

            # Create alert embed
            color_map = {
                "LOW": discord.Color.green(),
                "MEDIUM": discord.Color.yellow(),
                "HIGH": discord.Color.red(),
                "CRITICAL": discord.Color.dark_red()
            }

            embed = discord.Embed(
                title=f"🚨 {alert_type.upper()} ALERT",
                description=f"**Severity:** {severity}\n\n{details}",
                color=color_map.get(severity, discord.Color.blue()),
                timestamp=discord.utils.utcnow()
            )

            # Add system metrics
            cpu = psutil.cpu_percent()
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')

            embed.add_field(
                name="System Status",
                value=f"CPU: {cpu}%\nMemory: {memory.percent}%\nDisk: {disk.percent}%",
                inline=False
            )

            # Add to database
            await self.db.alerts.insert_one({
                "guild_id": guild_id,
                "type": alert_type,
                "severity": severity,
                "details": details,
                "timestamp": datetime.now(timezone.utc),
                "metrics": {
                    "cpu": cpu,
                    "memory": memory.percent,
                    "disk": disk.percent
                }
            })

            await channel.send(embed=embed)
            logger.warning(f"Alert sent to guild {guild_id}: {alert_type} - {severity}")

        except Exception as e:
            logger.error(f"Error sending alert: {str(e)}\n{traceback.format_exc()}")

    @app_commands.command(name="alerts", description="Configure alert settings")
    @app_commands.describe(
        channel="Channel for alert notifications",
        cpu_threshold="CPU usage threshold (percentage)",
        memory_threshold="Memory usage threshold (percentage)",
        disk_threshold="Disk usage threshold (percentage)"
    )
    @app_commands.default_permissions(administrator=True)
    async def configure_alerts(
        self,
        interaction: discord.Interaction,
        channel: Optional[discord.TextChannel] = None,
        cpu_threshold: Optional[int] = None,
        memory_threshold: Optional[int] = None,
        disk_threshold: Optional[int] = None
    ):
        await interaction.response.defer()

        try:
            # Update settings
            update_data = {}
            if channel:
                update_data["alert_channel_id"] = channel.id
                self.alert_channels[interaction.guild_id] = channel.id

            if cpu_threshold is not None:
                update_data["alert_thresholds.cpu"] = cpu_threshold
                self.alert_thresholds["cpu"] = cpu_threshold

            if memory_threshold is not None:
                update_data["alert_thresholds.memory"] = memory_threshold
                self.alert_thresholds["memory"] = memory_threshold

            if disk_threshold is not None:
                update_data["alert_thresholds.disk"] = disk_threshold
                self.alert_thresholds["disk"] = disk_threshold

            if update_data:
                await self.db.guild_settings.update_one(
                    {"guild_id": interaction.guild_id},
                    {"$set": update_data},
                    upsert=True
                )

            await interaction.followup.send("✅ Alert settings updated successfully!")

        except Exception as e:
            logger.error(f"Error configuring alerts: {str(e)}\n{traceback.format_exc()}")
            await interaction.followup.send("❌ Failed to update alert settings.")

async def setup(bot: commands.Bot):
    await bot.add_cog(AlertSystem(bot)) 