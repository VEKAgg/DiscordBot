import discord
from discord import app_commands
from discord.ext import commands
from utils.database import Database
from utils.logger import setup_logger
from datetime import datetime, timedelta
import traceback
from typing import Optional

logger = setup_logger()

class Stats(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = Database.db

    async def get_overview_stats(self, guild_id: int):
        try:
            stats = {
                "total_members": 0,
                "online_members": 0,
                "messages_today": 0,
                "voice_minutes": 0,
                "active_users": 0,
                "commands_used": 0
            }
            
            # Get member stats
            guild = self.bot.get_guild(guild_id)
            stats["total_members"] = guild.member_count
            stats["online_members"] = len([m for m in guild.members if m.status != discord.Status.offline])
            
            # Get today's activity
            today = datetime.utcnow() - timedelta(days=1)
            
            # Message stats
            messages = await self.db.message_logs.count_documents({
                "guild_id": guild_id,
                "timestamp": {"$gte": today}
            })
            stats["messages_today"] = messages
            
            # Voice stats
            voice_stats = await self.db.voice_stats.aggregate([
                {"$match": {
                    "guild_id": guild_id,
                    "timestamp": {"$gte": today}
                }},
                {"$group": {
                    "_id": None,
                    "total_minutes": {"$sum": "$duration"}
                }}
            ]).to_list(length=1)
            
            if voice_stats:
                stats["voice_minutes"] = int(voice_stats[0]["total_minutes"])
            
            # Active users
            active_users = await self.db.user_stats.count_documents({
                "guild_id": guild_id,
                "last_active": {"$gte": today}
            })
            stats["active_users"] = active_users
            
            # Commands used
            commands = await self.db.command_logs.count_documents({
                "guild_id": guild_id,
                "timestamp": {"$gte": today}
            })
            stats["commands_used"] = commands
            
            return stats
            
        except Exception as e:
            logger.error(f"Error getting overview stats: {str(e)}\n{traceback.format_exc()}")
            return None

    def create_overview_embed(self, stats: dict) -> discord.Embed:
        embed = discord.Embed(
            title="📊 Server Overview",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        
        embed.add_field(
            name="Members",
            value=f"Total: {stats['total_members']:,}\n"
                  f"Online: {stats['online_members']:,}\n"
                  f"Active Today: {stats['active_users']:,}",
            inline=True
        )
        
        embed.add_field(
            name="Activity (24h)",
            value=f"Messages: {stats['messages_today']:,}\n"
                  f"Voice Time: {stats['voice_minutes']:,} minutes\n"
                  f"Commands: {stats['commands_used']:,}",
            inline=True
        )
        
        return embed

    @app_commands.command(name="analytics", description="View server analytics")
    @app_commands.describe(
        type="Type of analytics to view",
        timeframe="Time period to analyze",
        user="User to analyze (for member analytics)"
    )
    @app_commands.choices(
        type=[
            app_commands.Choice(name="Overview", value="overview"),
            app_commands.Choice(name="Members", value="members"),
            app_commands.Choice(name="Messages", value="messages"),
            app_commands.Choice(name="Voice", value="voice"),
            app_commands.Choice(name="Commands", value="commands")
        ],
        timeframe=[
            app_commands.Choice(name="24 Hours", value="day"),
            app_commands.Choice(name="7 Days", value="week"),
            app_commands.Choice(name="30 Days", value="month"),
            app_commands.Choice(name="All Time", value="all")
        ]
    )
    async def analytics(
        self, 
        interaction: discord.Interaction, 
        type: str,
        timeframe: str = "day",
        user: Optional[discord.Member] = None
    ):
        await interaction.response.defer()
        
        try:
            if type == "overview":
                stats = await self.get_overview_stats(interaction.guild_id)
                if not stats:
                    await interaction.followup.send("❌ Failed to fetch overview statistics.")
                    return
                    
                embed = self.create_overview_embed(stats)
                await interaction.followup.send(embed=embed)
                
            else:
                # Get time threshold
                threshold = datetime.utcnow()
                if timeframe == "week":
                    threshold -= timedelta(days=7)
                elif timeframe == "month":
                    threshold -= timedelta(days=30)
                elif timeframe == "all":
                    threshold = datetime.min
                else:  # day
                    threshold -= timedelta(days=1)
                
                # Build query
                query = {
                    "guild_id": interaction.guild_id,
                    "timestamp": {"$gte": threshold}
                }
                
                if user:
                    query["user_id"] = user.id
                
                # Get specific analytics
                if type == "messages":
                    data = await self.get_message_analytics(query)
                elif type == "voice":
                    data = await self.get_voice_analytics(query)
                elif type == "commands":
                    data = await self.get_command_analytics(query)
                elif type == "members":
                    data = await self.get_member_analytics(query)
                
                embed = await self.create_analytics_embed(type, timeframe, data, user)
                await interaction.followup.send(embed=embed)
                
        except Exception as e:
            logger.error(f"Error in analytics command: {str(e)}\n{traceback.format_exc()}")
            await interaction.followup.send("❌ An error occurred while fetching analytics.")

async def setup(bot: commands.Bot):
    await bot.add_cog(Stats(bot)) 