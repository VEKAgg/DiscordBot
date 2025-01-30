import discord
from discord import app_commands
from discord.ext import commands
from utils.database import Database
from utils.logger import setup_logger
import traceback
import random
import math
from datetime import datetime, timedelta

logger = setup_logger()

class Leveling(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = Database.db
        # Different cooldowns for different activities
        self.text_cooldown = commands.CooldownMapping.from_cooldown(1, 60, commands.BucketType.member)
        self.voice_cooldown = commands.CooldownMapping.from_cooldown(1, 300, commands.BucketType.member)
        self.presence_cooldown = commands.CooldownMapping.from_cooldown(1, 300, commands.BucketType.member)
        self.command_cooldown = commands.CooldownMapping.from_cooldown(1, 30, commands.BucketType.member)
        self.voice_users = {}  # Track users in voice channels
        self.presence_cache = {}  # Track presence duration
        self.activity_xp_rates = {
            discord.ActivityType.playing: 5,      # Gaming
            discord.ActivityType.streaming: 8,    # Streaming
            discord.ActivityType.listening: 3,    # Music
            discord.ActivityType.watching: 3,     # Watching
            discord.ActivityType.custom: 2,       # Custom status
            discord.ActivityType.competing: 5     # Competing
        }
        self.activity_bonuses = {
            # Gaming bonuses
            "minecraft": 8,
            "valorant": 7,
            "league of legends": 7,
            "genshin impact": 8,
            
            # Development bonuses
            "visual studio code": 12,
            "intellij idea": 12,
            "sublime text": 10,
            "github desktop": 10,
            "unity": 12,
            "unreal engine": 12,
            
            # Creative bonuses
            "photoshop": 10,
            "premiere pro": 10,
            "after effects": 10,
            "blender": 12,
            
            # Productivity bonuses
            "notion": 8,
            "discord": 5,
            "slack": 5,
            
            # Streaming bonuses
            "obs studio": 10,
            "streamlabs": 10,
            
            # Music bonuses
            "spotify": 5,
            "soundcloud": 5,
            "apple music": 5
        }
        
        self.milestone_rewards = {
            # Gaming milestones (minutes)
            "gaming": {
                60: {"xp": 100, "message": "1 Hour Gaming Session"},
                180: {"xp": 300, "message": "3 Hour Gaming Warrior"},
                360: {"xp": 700, "message": "6 Hour Gaming Master"}
            },
            # Development milestones
            "development": {
                120: {"xp": 200, "message": "2 Hour Coding Sprint"},
                240: {"xp": 500, "message": "4 Hour Code Warrior"},
                480: {"xp": 1000, "message": "8 Hour Code Master"}
            },
            # Streaming milestones
            "streaming": {
                60: {"xp": 150, "message": "1 Hour Stream"},
                180: {"xp": 450, "message": "3 Hour Entertainer"},
                300: {"xp": 800, "message": "5 Hour Stream Master"}
            }
        }

        self.streak_rewards = {
            "daily": {
                3: {"xp": 150, "message": "3 Day Streak!"},
                7: {"xp": 500, "message": "Weekly Warrior!"},
                30: {"xp": 2000, "message": "Monthly Master!"}
            },
            "activity": {
                5: {"xp": 200, "message": "5 Activity Streak!"},
                10: {"xp": 600, "message": "Activity Master!"},
                20: {"xp": 1500, "message": "Activity Legend!"}
            }
        }

    async def calculate_level(self, xp: int) -> int:
        return int(math.sqrt(xp) // 10)
        
    async def calculate_xp_for_level(self, level: int) -> int:
        return (level * 10) ** 2
        
    async def award_xp(self, member: discord.Member, amount: int, source: str = "message"):
        try:
            # Award XP logic remains the same
            current_xp = await self.get_xp(member)
            new_xp = current_xp + amount
            current_level = self.calculate_level(current_xp)
            new_level = self.calculate_level(new_xp)

            # Update XP in database
            await self.db.user_levels.update_one(
                {"guild_id": member.guild.id, "user_id": member.id},
                {"$inc": {"xp": amount}},
                upsert=True
            )

            # Level up notification
            if new_level > current_level:
                embed = discord.Embed(
                    title="🎉 Level Up!",
                    description=f"Congratulations {member.mention}! You've reached level **{new_level}**!",
                    color=discord.Color.green()
                )
                
                # Send notification in the same channel if source is message
                if source == "message" and hasattr(member, "last_message"):
                    await member.last_message.channel.send(embed=embed)
                else:
                    try:
                        await member.send(embed=embed)
                    except discord.Forbidden:
                        # If DM fails, try to find the last channel they were active in
                        for channel in member.guild.text_channels:
                            if channel.permissions_for(member).read_messages:
                                await channel.send(embed=embed)
                                break

            # Small XP gain notification (only for significant gains)
            elif amount >= 50:  # Only notify for larger XP gains
                embed = discord.Embed(
                    description=f"🌟 {member.mention} gained **{amount}** XP from {source.replace('_', ' ')}!",
                    color=discord.Color.blue()
                )
                
                if source == "message" and hasattr(member, "last_message"):
                    await member.last_message.channel.send(embed=embed, delete_after=5)
                else:
                    try:
                        await member.send(embed=embed)
                    except discord.Forbidden:
                        pass  # Skip notification if DM fails for regular XP gains

        except Exception as e:
            logger.error(f"Error awarding XP: {str(e)}")

    async def handle_level_up(self, member: discord.Member, new_level: int):
        try:
            settings = await self.db.guild_settings.find_one({"guild_id": member.guild.id})
            
            if settings and settings.get("level_up_channel"):
                channel = self.bot.get_channel(settings["level_up_channel"])
            else:
                # Find first channel bot can send messages in
                channel = next((ch for ch in member.guild.text_channels 
                              if ch.permissions_for(member.guild.me).send_messages), None)
            
            if channel:
                embed = discord.Embed(
                    title="🎉 Level Up!",
                    description=f"{member.mention} has reached level {new_level}!",
                    color=discord.Color.green()
                )
                await channel.send(embed=embed)

            # Handle level roles
            if settings and "level_roles" in settings:
                for level_role in settings["level_roles"]:
                    if new_level >= level_role["level"]:
                        role = member.guild.get_role(level_role["role_id"])
                        if role and role not in member.roles:
                            await member.add_roles(role)
                            if channel:
                                await channel.send(f"🎊 {member.mention} earned the {role.name} role!")

        except Exception as e:
            logger.error(f"Error in level up handler: {str(e)}\n{traceback.format_exc()}")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
            
        bucket = self.text_cooldown.get_bucket(message)
        if bucket.update_rate_limit():
            return
            
        try:
            # Base XP for messages (15-25)
            xp_gain = random.randint(15, 25)
            
            # Bonus XP for longer messages
            if len(message.content) > 100:
                xp_gain += 5
            
            # Bonus XP for media content
            if message.attachments or message.embeds:
                xp_gain += 3
                
            await self.award_xp(message.author, xp_gain, "message")
                
        except Exception as e:
            logger.error(f"Error in message XP: {str(e)}\n{traceback.format_exc()}")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        try:
            if member.bot:
                return

            # Handle joining voice
            if after.channel and not before.channel:
                self.voice_users[member.id] = {
                    "channel": after.channel.id,
                    "joined_at": datetime.utcnow(),
                    "streaming": after.self_stream,
                    "camera": after.self_video
                }

            # Handle leaving voice
            elif before.channel and not after.channel:
                if member.id in self.voice_users:
                    join_time = self.voice_users[member.id]["joined_at"]
                    duration = datetime.utcnow() - join_time
                    
                    # Award XP based on time spent (1 XP per minute, max 30)
                    minutes = min(duration.total_seconds() / 60, 30)
                    xp_gain = int(minutes)
                    
                    # Bonus XP for streaming/camera
                    if self.voice_users[member.id]["streaming"]:
                        xp_gain += 10
                    if self.voice_users[member.id]["camera"]:
                        xp_gain += 5
                        
                    await self.award_xp(member, xp_gain, "voice")
                    del self.voice_users[member.id]

        except Exception as e:
            logger.error(f"Error in voice XP: {str(e)}\n{traceback.format_exc()}")

    @commands.Cog.listener()
    async def on_presence_update(self, before: discord.Member, after: discord.Member):
        if before.bot:
            return
            
        try:
            current_time = datetime.utcnow()
            
            # Handle activity end
            if before.activity and before.id in self.presence_cache:
                start_time = self.presence_cache[before.id].get('time')
                if start_time:
                    duration = (current_time - start_time).total_seconds() / 60  # Convert to minutes
                    activity_type = self.presence_cache[before.id].get('type')
                    
                    if duration >= 5:  # Minimum 5 minutes for XP
                        base_xp = self.activity_xp_rates.get(activity_type, 2)
                        xp_gain = min(int(duration * base_xp), 100)  # Cap at 100 XP per activity
                        
                        # Bonus XP for specific activities
                        activity_name = self.presence_cache[before.id].get('name', '').lower()
                        if 'visual studio code' in activity_name or 'intellij' in activity_name:
                            xp_gain += 10  # Bonus for coding
                        elif 'spotify' in activity_name:
                            xp_gain += 5   # Bonus for music
                        
                        await self.award_xp(before, xp_gain, f"presence_{activity_type.name}")
                        
                        # Log activity for analytics
                        await self.db.activity_stats.update_one(
                            {
                                "guild_id": before.guild.id,
                                "user_id": before.id,
                                "activity_type": str(activity_type)
                            },
                            {
                                "$inc": {
                                    "total_duration": duration,
                                    "total_xp_earned": xp_gain
                                },
                                "$set": {
                                    "last_activity": before.activity.name,
                                    "last_seen": current_time
                                }
                            },
                            upsert=True
                        )
                
                del self.presence_cache[before.id]
            
            # Handle activity start
            if after.activity:
                self.presence_cache[after.id] = {
                    'time': current_time,
                    'type': after.activity.type,
                    'name': after.activity.name
                }
                
            # Modify XP calculation with new bonuses
            activity_name = after.activity.name.lower() if after.activity.name else ""
            
            # Apply specific activity bonuses
            bonus_xp = self.activity_bonuses.get(activity_name, 0)
            
            # Categorize activity for milestones
            activity_category = None
            if any(dev_app in activity_name for dev_app in ["visual studio", "intellij", "github"]):
                activity_category = "development"
            elif after.activity.type == discord.ActivityType.streaming:
                activity_category = "streaming"
            elif after.activity.type == discord.ActivityType.playing:
                activity_category = "gaming"
                
            if activity_category:
                await self.check_milestones(after, activity_category, duration)
                
            # Add streak check
            await self.check_streak(after, "activity")
                
        except Exception as e:
            logger.error(f"Error in presence XP: {str(e)}\n{traceback.format_exc()}")

    async def check_milestones(self, member: discord.Member, activity_type: str, duration: float):
        try:
            # Get user's milestone progress
            progress = await self.db.milestone_progress.find_one({
                "guild_id": member.guild.id,
                "user_id": member.id,
                "activity_type": activity_type
            }) or {"current_duration": 0, "completed_milestones": []}

            current_duration = progress["current_duration"] + duration
            completed_milestones = progress["completed_milestones"]

            if activity_type in self.milestone_rewards:
                for minutes, reward in self.milestone_rewards[activity_type].items():
                    if current_duration >= minutes and minutes not in completed_milestones:
                        # Award milestone reward
                        await self.award_xp(member, reward["xp"], f"milestone_{activity_type}")
                        completed_milestones.append(minutes)

                        # Send milestone notification
                        embed = discord.Embed(
                            title="🏆 Milestone Achieved!",
                            description=f"{member.mention} achieved: {reward['message']}\n+{reward['xp']} XP!",
                            color=discord.Color.gold()
                        )
                        
                        # Find channel to send notification
                        settings = await self.db.guild_settings.find_one({"guild_id": member.guild.id})
                        if settings and settings.get("milestone_channel"):
                            channel = self.bot.get_channel(settings["milestone_channel"])
                            if channel:
                                await channel.send(embed=embed)

            # Update milestone progress
            await self.db.milestone_progress.update_one(
                {
                    "guild_id": member.guild.id,
                    "user_id": member.id,
                    "activity_type": activity_type
                },
                {
                    "$set": {
                        "current_duration": current_duration,
                        "completed_milestones": completed_milestones,
                        "last_updated": datetime.utcnow()
                    }
                },
                upsert=True
            )

        except Exception as e:
            logger.error(f"Error checking milestones: {str(e)}\n{traceback.format_exc()}")

    async def check_streak(self, member: discord.Member, activity_type: str):
        try:
            current_time = datetime.utcnow()
            streak_data = await self.db.streak_data.find_one({
                "guild_id": member.guild.id,
                "user_id": member.id,
                "type": activity_type
            }) or {
                "current_streak": 0,
                "last_activity": None,
                "highest_streak": 0,
                "completed_streaks": []
            }

            # Check if streak is still valid (within 24 hours)
            if streak_data["last_activity"]:
                time_diff = current_time - streak_data["last_activity"]
                if time_diff.total_seconds() > 86400:  # 24 hours
                    streak_data["current_streak"] = 1
                else:
                    streak_data["current_streak"] += 1
            else:
                streak_data["current_streak"] = 1

            # Update highest streak
            if streak_data["current_streak"] > streak_data["highest_streak"]:
                streak_data["highest_streak"] = streak_data["current_streak"]

            # Check for streak rewards
            if activity_type in self.streak_rewards:
                for streak_count, reward in self.streak_rewards[activity_type].items():
                    if (streak_data["current_streak"] >= streak_count and 
                        streak_count not in streak_data["completed_streaks"]):
                        # Award streak bonus
                        await self.award_xp(member, reward["xp"], f"streak_{activity_type}")
                        streak_data["completed_streaks"].append(streak_count)

                        # Send streak notification
                        embed = discord.Embed(
                            title="🔥 Streak Reward!",
                            description=f"{member.mention} {reward['message']}\n+{reward['xp']} XP!",
                            color=discord.Color.orange()
                        )
                        embed.add_field(
                            name="Current Streak",
                            value=f"{streak_data['current_streak']} days",
                            inline=True
                        )
                        embed.add_field(
                            name="Highest Streak",
                            value=f"{streak_data['highest_streak']} days",
                            inline=True
                        )

                        # Send notification
                        settings = await self.db.guild_settings.find_one({"guild_id": member.guild.id})
                        if settings and settings.get("streak_channel"):
                            channel = self.bot.get_channel(settings["streak_channel"])
                            if channel:
                                await channel.send(embed=embed)

            # Update streak data
            await self.db.streak_data.update_one(
                {
                    "guild_id": member.guild.id,
                    "user_id": member.id,
                    "type": activity_type
                },
                {
                    "$set": {
                        "current_streak": streak_data["current_streak"],
                        "last_activity": current_time,
                        "highest_streak": streak_data["highest_streak"],
                        "completed_streaks": streak_data["completed_streaks"]
                    }
                },
                upsert=True
            )

        except Exception as e:
            logger.error(f"Error checking streak: {str(e)}\n{traceback.format_exc()}")

    @app_commands.command(name="rank", description="View your or another user's rank")
    async def rank(self, interaction: discord.Interaction, member: discord.Member = None):
        await interaction.response.defer()
        
        try:
            target = member or interaction.user
            
            stats = await self.db.user_stats.find_one({
                "guild_id": interaction.guild_id,
                "user_id": target.id
            })
            
            if not stats:
                await interaction.followup.send("No rank data found for this user.")
                return
                
            # Get user's rank position
            higher_users = await self.db.user_stats.count_documents({
                "guild_id": interaction.guild_id,
                "xp": {"$gt": stats["xp"]}
            })
            rank = higher_users + 1
            
            # Calculate progress to next level
            current_level = stats["level"]
            current_xp = stats["xp"]
            next_level_xp = await self.calculate_xp_for_level(current_level + 1)
            current_level_xp = await self.calculate_xp_for_level(current_level)
            progress = (current_xp - current_level_xp) / (next_level_xp - current_level_xp) * 100
            
            embed = discord.Embed(
                title=f"Rank for {target.display_name}",
                color=target.color
            )
            embed.add_field(name="Rank", value=f"#{rank}", inline=True)
            embed.add_field(name="Level", value=str(current_level), inline=True)
            embed.add_field(name="XP", value=f"{current_xp:,}/{next_level_xp:,}", inline=True)
            embed.add_field(name="Progress to Next Level", value=f"{progress:.1f}%", inline=False)
            embed.set_thumbnail(url=target.display_avatar.url)
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            error_msg = f"Error in rank command: {str(e)}\n{traceback.format_exc()}"
            logger.error(error_msg)
            await interaction.followup.send("❌ An error occurred while fetching rank data.")

    async def on_app_command_completion(self, interaction: discord.Interaction, command: app_commands.Command):
        if interaction.user.bot:
            return
            
        bucket = self.command_cooldown.get_bucket(interaction)
        if bucket.update_rate_limit():
            return
            
        try:
            # Base XP for using commands (10-20)
            xp_gain = random.randint(10, 20)
            
            # Bonus XP for admin/mod commands
            if command.default_permissions and (
                command.default_permissions.administrator or 
                command.default_permissions.manage_guild or 
                command.default_permissions.manage_messages
            ):
                xp_gain += 10
                
            await self.award_xp(interaction.user, xp_gain, "commands")
                
        except Exception as e:
            logger.error(f"Error in command XP: {str(e)}\n{traceback.format_exc()}")

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        try:
            # Check for boost changes
            if before.premium_since != after.premium_since and after.premium_since is not None:
                # Award XP for boosting (500 XP)
                boost_xp = 500
                
                # Create boost embed
                embed = discord.Embed(
                    title="🚀 Server Boost!",
                    description=f"Thanks {after.mention} for boosting the server!\n+{boost_xp} XP awarded!",
                    color=discord.Color.pink()
                )
                
                # Find announcement channel
                settings = await self.db.guild_settings.find_one({"guild_id": after.guild.id})
                if settings and settings.get("boost_channel"):
                    channel = self.bot.get_channel(settings["boost_channel"])
                else:
                    channel = next((ch for ch in after.guild.text_channels 
                                if ch.permissions_for(after.guild.me).send_messages), None)
                
                if channel:
                    await channel.send(embed=embed)
                
                await self.award_xp(after, boost_xp, "boost")
                
                # Update boost stats
                await self.db.user_stats.update_one(
                    {
                        "guild_id": after.guild.id,
                        "user_id": after.id
                    },
                    {
                        "$inc": {"total_boosts": 1},
                        "$set": {"last_boost": datetime.utcnow()}
                    },
                    upsert=True
                )
                
        except Exception as e:
            logger.error(f"Error in boost XP: {str(e)}\n{traceback.format_exc()}")

    @app_commands.command(name="activitystats", description="View detailed activity statistics")
    async def activity_stats(self, interaction: discord.Interaction, member: discord.Member = None):
        await interaction.response.defer()
        
        try:
            target = member or interaction.user
            
            # Get activity stats
            stats = await self.db.activity_stats.find({
                "guild_id": interaction.guild_id,
                "user_id": target.id
            }).to_list(length=None)
            
            if not stats:
                await interaction.followup.send("No activity statistics found for this user.")
                return
            
            embed = discord.Embed(
                title=f"Activity Statistics for {target.display_name}",
                color=target.color
            )
            
            total_duration = 0
            total_xp = 0
            
            for stat in stats:
                activity_type = stat["activity_type"]
                duration = stat["total_duration"]
                xp = stat["total_xp_earned"]
                
                total_duration += duration
                total_xp += xp
                
                embed.add_field(
                    name=f"{activity_type.title()}",
                    value=f"Duration: {int(duration)} minutes\nXP Earned: {xp}",
                    inline=True
                )
            
            embed.description = f"Total Time: {int(total_duration)} minutes\nTotal XP: {total_xp}"
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in activity stats command: {str(e)}\n{traceback.format_exc()}")
            await interaction.followup.send("❌ An error occurred while fetching activity statistics.")

    @app_commands.command(name="leaderboard", description="View various leaderboards")
    @app_commands.describe(
        type="Type of leaderboard to view",
        scope="Scope of the leaderboard",
        timeframe="Timeframe for the leaderboard"
    )
    @app_commands.choices(
        type=[
            app_commands.Choice(name="XP", value="xp"),
            app_commands.Choice(name="Activity", value="activity"),
            app_commands.Choice(name="Voice", value="voice"),
            app_commands.Choice(name="Streaks", value="streaks"),
            app_commands.Choice(name="Milestones", value="milestones")
        ],
        scope=[
            app_commands.Choice(name="Server", value="server"),
            app_commands.Choice(name="Global", value="global")
        ],
        timeframe=[
            app_commands.Choice(name="All Time", value="all"),
            app_commands.Choice(name="Monthly", value="month"),
            app_commands.Choice(name="Weekly", value="week"),
            app_commands.Choice(name="Daily", value="day")
        ]
    )
    async def leaderboard(
        self, 
        interaction: discord.Interaction, 
        type: str = "xp",
        scope: str = "server",
        timeframe: str = "all"
    ):
        await interaction.response.defer()
        
        try:
            # Get time threshold based on timeframe
            time_threshold = datetime.utcnow()
            if timeframe == "month":
                time_threshold -= timedelta(days=30)
            elif timeframe == "week":
                time_threshold -= timedelta(days=7)
            elif timeframe == "day":
                time_threshold -= timedelta(days=1)

            # Build query based on type and scope
            query = {}
            if scope == "server":
                query["guild_id"] = interaction.guild_id
            if timeframe != "all":
                query["last_updated"] = {"$gte": time_threshold}

            # Get sorted data based on leaderboard type
            if type == "xp":
                cursor = self.db.user_stats.find(query).sort("xp", -1).limit(10)
                title = "🏆 XP Leaderboard"
                field_name = "Total XP"
                value_key = "xp"
            elif type == "activity":
                cursor = self.db.activity_stats.aggregate([
                    {"$match": query},
                    {"$group": {
                        "_id": "$user_id",
                        "total_duration": {"$sum": "$total_duration"},
                        "username": {"$first": "$username"}
                    }},
                    {"$sort": {"total_duration": -1}},
                    {"$limit": 10}
                ])
                title = "⚡ Activity Leaderboard"
                field_name = "Total Activity Time"
                value_key = "total_duration"
            elif type == "voice":
                cursor = self.db.user_stats.find(query).sort("activity_xp.voice", -1).limit(10)
                title = "�� Voice Leaderboard"
                field_name = "Voice XP"
                value_key = "activity_xp.voice"
            elif type == "streaks":
                cursor = self.db.streak_data.find(query).sort("highest_streak", -1).limit(10)
                title = "🔥 Streak Leaderboard"
                field_name = "Highest Streak"
                value_key = "highest_streak"
            else:  # milestones
                cursor = self.db.milestone_progress.aggregate([
                    {"$match": query},
                    {"$group": {
                        "_id": "$user_id",
                        "milestones": {"$sum": {"$size": "$completed_milestones"}},
                        "username": {"$first": "$username"}
                    }},
                    {"$sort": {"milestones": -1}},
                    {"$limit": 10}
                ])
                title = "🎯 Milestone Leaderboard"
                field_name = "Completed Milestones"
                value_key = "milestones"

            # Create embed
            embed = discord.Embed(
                title=f"{title} - {scope.title()} ({timeframe.title()})",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )

            # Add leaderboard entries
            entries = await cursor.to_list(length=10)
            for i, entry in enumerate(entries, 1):
                user_id = entry.get("user_id") or entry.get("_id")
                user = interaction.guild.get_member(user_id) if scope == "server" else self.bot.get_user(user_id)
                username = user.name if user else entry.get("username", "Unknown User")
                
                value = entry.get(value_key, 0)
                if type == "activity":
                    value = f"{int(value)} minutes"
                elif type == "streaks":
                    value = f"{value} days"
                elif type == "xp":
                    value = f"{value:,} XP (Level {await self.calculate_level(value)})"
                
                embed.add_field(
                    name=f"{i}. {username}",
                    value=f"{field_name}: {value}",
                    inline=False
                )

            embed.set_footer(text=f"Requested by {interaction.user.name}")
            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in leaderboard command: {str(e)}\n{traceback.format_exc()}")
            await interaction.followup.send("❌ An error occurred while fetching the leaderboard.")

async def setup(bot: commands.Bot):
    await bot.add_cog(Leveling(bot)) 