import discord
from discord import app_commands
from discord.ext import commands
from utils.database import Database
from utils.logger import setup_logger
from datetime import datetime, timezone

logger = setup_logger()

class ActivityTracker(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = Database.db

    @commands.Cog.listener()
    async def on_presence_update(self, before: discord.Member, after: discord.Member):
        try:
            # Track only if activity changed
            if before.activity != after.activity:
                await self.db.activity_logs.insert_one({
                    "guild_id": after.guild.id,
                    "user_id": after.id,
                    "timestamp": datetime.now(timezone.utc),
                    "activity_type": str(after.activity.type) if after.activity else None,
                    "activity_name": after.activity.name if after.activity else None,
                    "activity_details": after.activity.details if after.activity else None
                })
        except Exception as e:
            logger.error(f"Error tracking presence update: {str(e)}")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        try:
            # Track voice channel activity
            await self.db.voice_logs.insert_one({
                "guild_id": member.guild.id,
                "user_id": member.id,
                "timestamp": datetime.now(timezone.utc),
                "channel_before": before.channel.id if before.channel else None,
                "channel_after": after.channel.id if after.channel else None,
                "muted": after.mute,
                "deafened": after.deaf
            })
        except Exception as e:
            logger.error(f"Error tracking voice state: {str(e)}")

    @app_commands.command(name="activity", description="View user activity stats")
    async def activity(self, interaction: discord.Interaction, member: discord.Member = None):
        await interaction.response.defer()
        
        try:
            member = member or interaction.user
            
            # Get recent activity data
            activity_data = await self.db.activity_logs.find({
                "guild_id": interaction.guild_id,
                "user_id": member.id
            }).sort("timestamp", -1).limit(5).to_list(length=5)

            embed = discord.Embed(
                title=f"Activity Stats for {member.display_name}",
                color=discord.Color.blue()
            )

            if activity_data:
                for activity in activity_data:
                    embed.add_field(
                        name=activity["activity_name"] or "No activity",
                        value=f"Type: {activity['activity_type']}\n"
                              f"Time: <t:{int(activity['timestamp'].timestamp())}:R>",
                        inline=False
                    )
            else:
                embed.description = "No recent activity data found."

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in activity command: {str(e)}")
            await interaction.followup.send("An error occurred while fetching activity data.")

async def setup(bot: commands.Bot):
    await bot.add_cog(ActivityTracker(bot)) 