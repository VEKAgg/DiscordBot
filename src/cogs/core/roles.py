import discord
from discord import app_commands
from discord.ext import commands
from utils.database import Database
from utils.logger import setup_logger
from datetime import datetime, timedelta

logger = setup_logger()

class Roles(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = Database.db
        self.stream_sessions = {}
        self.stream_xp_rate = 5
        self.stream_xp_cap = 300
        self.leveling_cog = None
        self.dev_applications = [
            "Visual Studio Code",
            "IntelliJ IDEA",
            "PyCharm",
            "WebStorm",
            "Android Studio",
            "Sublime Text",
            "Atom",
            "Eclipse",
            "Unity",
            "Unreal Engine"
        ]
        self.activity_roles = {
            "games": {
                "Rocket League": {"name": "Rocket League", "color": discord.Color.blue()},
                "Minecraft": {"name": "Minecraft", "color": discord.Color.green()},
                "Elite Dangerous": {"name": "Elite", "color": discord.Color.orange()},
                "Forza Horizon": {"name": "Forza", "color": discord.Color.brand_red()},
                "Assetto Corsa": {"name": "Racing", "color": discord.Color.dark_red()}
            },
            "music": {
                "Spotify": {"name": "Music", "color": discord.Color.green()},
                "YouTube Music": {"name": "Music", "color": discord.Color.red()}
            },
            "anime": {
                "Crunchyroll": {"name": "Anime Watcher", "color": discord.Color.orange()}
            },
            "creative": {
                "Photoshop": {"name": "Artist", "color": discord.Color.blue()},
                "Illustrator": {"name": "Artist", "color": discord.Color.orange()},
                "Premiere Pro": {"name": "Artist", "color": discord.Color.purple()},
                "After Effects": {"name": "Artist", "color": discord.Color.gold()}
            }
        }

    async def get_leveling_cog(self):
        if not self.leveling_cog:
            self.leveling_cog = self.bot.get_cog("Leveling")
        return self.leveling_cog

    @commands.hybrid_group(name="roleconfig", description="Configure role settings")
    @commands.has_permissions(manage_guild=True)
    async def role_config(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send("Please specify a subcommand: setrole, viewroles")

    @role_config.command(name="setrole", description="Set role for specific activities")
    async def set_role(self, ctx, type: str, role: discord.Role):
        try:
            valid_types = ["stream", "boost", "level"]
            if type.lower() not in valid_types:
                await ctx.send(f"Invalid type. Valid types: {', '.join(valid_types)}")
                return

            await self.db.guild_settings.update_one(
                {"guild_id": ctx.guild.id},
                {"$set": {f"{type.lower()}_role_id": role.id}},
                upsert=True
            )
            await ctx.send(f"✅ Set {role.mention} as the {type} role!")
        except Exception as e:
            logger.error(f"Error setting role: {str(e)}")
            await ctx.send("❌ Failed to set role.")

    @commands.Cog.listener()
    async def on_presence_update(self, before: discord.Member, after: discord.Member):
        if before.bot:
            return
            
        try:
            # Check for streaming status
            was_streaming = any(activity.type == discord.ActivityType.streaming 
                              for activity in before.activities if activity)
            is_streaming = any(activity.type == discord.ActivityType.streaming 
                             for activity in after.activities if activity)
            
            if was_streaming == is_streaming:
                await self.handle_streaming_role(before, after)
                return

            # Get stream role from settings
            settings = await self.db.guild_settings.find_one({"guild_id": after.guild.id})
            stream_role_id = settings.get("stream_role_id") if settings else None
            stream_role = after.guild.get_role(stream_role_id) if stream_role_id else None
            
            if not stream_role:
                stream_role = discord.utils.get(after.guild.roles, name="Live")
                if not stream_role:
                    stream_role = await after.guild.create_role(
                        name="Live",
                        color=discord.Color.purple(),
                        reason="Auto-created role for streamers"
                    )

            if is_streaming:
                await after.add_roles(stream_role)
                self.stream_sessions[after.id] = datetime.utcnow()
                
                # Get stream details
                stream = next(activity for activity in after.activities 
                            if activity and activity.type == discord.ActivityType.streaming)
                
                # Send notification
                channel = after.guild.system_channel or next(
                    (ch for ch in after.guild.text_channels 
                     if ch.permissions_for(after.guild.me).send_messages),
                    None
                )
                if channel:
                    embed = discord.Embed(
                        title="🎥 Stream Started!",
                        description=f"{after.mention} is now live!",
                        color=discord.Color.purple()
                    )
                    if stream.name:
                        embed.add_field(name="Streaming", value=stream.name)
                    if stream.url:
                        embed.add_field(name="Watch", value=f"[Click here]({stream.url})")
                    await channel.send(embed=embed)
            else:
                await after.remove_roles(stream_role)
                if after.id in self.stream_sessions:
                    start_time = self.stream_sessions.pop(after.id)
                    duration = datetime.utcnow() - start_time
                    
                    # Award XP through leveling cog
                    leveling_cog = await self.get_leveling_cog()
                    if leveling_cog:
                        minutes = duration.total_seconds() / 60
                        xp_gain = min(int(minutes * self.stream_xp_rate), self.stream_xp_cap)
                        await leveling_cog.award_xp(after, xp_gain, "streaming")

            # Check for developer activity
            was_developing = any(activity.name in self.dev_applications 
                               for activity in before.activities if activity)
            is_developing = any(activity.name in self.dev_applications 
                              for activity in after.activities if activity)
            
            if was_developing != is_developing:
                await self.handle_dev_role(after, is_developing)

            # Handle activity-based roles
            await self.handle_activity_roles(before, after)
            
            # Handle cake day
            await self.handle_cake_day(after)

        except Exception as e:
            logger.error(f"Error in stream role handling: {str(e)}")

    async def handle_dev_role(self, member: discord.Member, is_developing: bool):
        try:
            # Get or create Dev role
            dev_role = discord.utils.get(member.guild.roles, name="Dev")
            if not dev_role:
                dev_role = await member.guild.create_role(
                    name="Dev",
                    color=discord.Color.blue(),
                    reason="Auto-created role for developers"
                )

            if is_developing and dev_role not in member.roles:
                await member.add_roles(dev_role)
                # Update developer stats
                await self.db.dev_stats.update_one(
                    {"guild_id": member.guild.id, "user_id": member.id},
                    {"$inc": {"dev_sessions": 1},
                     "$set": {"last_dev_activity": datetime.utcnow()}},
                    upsert=True
                )
            elif not is_developing and dev_role in member.roles:
                # Only remove if user hasn't earned permanent Dev role
                has_permanent = await self.db.dev_stats.find_one(
                    {"guild_id": member.guild.id, 
                     "user_id": member.id,
                     "dev_sessions": {"$gte": 10}}  # Keep role after 10 sessions
                )
                if not has_permanent:
                    await member.remove_roles(dev_role)

        except Exception as e:
            logger.error(f"Error handling dev role: {str(e)}")

    async def handle_activity_roles(self, before: discord.Member, after: discord.Member):
        try:
            # Get current activities
            current_activities = {activity.name: activity for activity in after.activities if activity and activity.name}
            previous_activities = {activity.name: activity for activity in before.activities if activity and activity.name}

            # Check each activity type
            for category, games in self.activity_roles.items():
                for game_name, role_info in games.items():
                    was_active = game_name in previous_activities
                    is_active = game_name in current_activities

                    if was_active != is_active:
                        role = discord.utils.get(after.guild.roles, name=role_info["name"])
                        if not role:
                            role = await after.guild.create_role(
                                name=role_info["name"],
                                color=role_info["color"],
                                reason=f"Auto-created role for {game_name}"
                            )

                        if is_active and role not in after.roles:
                            await after.add_roles(role)
                        elif not is_active and role in after.roles:
                            await after.remove_roles(role)

        except Exception as e:
            logger.error(f"Error handling activity roles: {str(e)}")

    async def handle_cake_day(self, member: discord.Member):
        try:
            today = datetime.utcnow().date()
            account_created = member.created_at.date()
            
            if today.month == account_created.month and today.day == account_created.day:
                cake_role = discord.utils.get(member.guild.roles, name="Cake Day")
                if not cake_role:
                    cake_role = await member.guild.create_role(
                        name="Cake Day",
                        color=discord.Color.lighter_grey(),
                        reason="Auto-created role for account anniversaries"
                    )

                if cake_role not in member.roles:
                    await member.add_roles(cake_role)
                    # Send celebration message
                    years = today.year - account_created.year
                    channel = member.guild.system_channel
                    if channel:
                        await channel.send(
                            f"🎂 Happy {years} Year{'s' if years != 1 else ''} on Discord, {member.mention}!"
                        )
            else:
                # Remove cake day role if it's not their cake day
                cake_role = discord.utils.get(member.guild.roles, name="Cake Day")
                if cake_role and cake_role in member.roles:
                    await member.remove_roles(cake_role)

        except Exception as e:
            logger.error(f"Error handling cake day: {str(e)}")

async def setup(bot: commands.Bot):
    await bot.add_cog(Roles(bot)) 