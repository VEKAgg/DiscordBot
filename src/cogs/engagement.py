import nextcord
from nextcord.ext import commands, tasks
import logging
from datetime import datetime, timedelta
import asyncio
from typing import List, Dict, Optional

logger = logging.getLogger('VEKA.engagement')

class Engagement(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.mongo
        self.user_activity = self.db.user_activity
        self.engagement_metrics = self.db.engagement_metrics
        self.achievements = self.db.achievements
        self.track_activity.start()
        self.check_inactive_users.start()
        self.update_leaderboards.start()

        # Activity point values
        self.point_values = {
            "message": 1,
            "reaction": 0.5,
            "connection_made": 5,
            "profile_update": 2,
            "event_attendance": 10,
            "skill_endorsement": 3,
            "job_referral": 15
        }

    def cog_unload(self):
        self.track_activity.cancel()
        self.check_inactive_users.cancel()
        self.update_leaderboards.cancel()

    @tasks.loop(minutes=15)
    async def track_activity(self):
        """Track and update user activity metrics"""
        try:
            now = datetime.utcnow()
            for guild in self.bot.guilds:
                for member in guild.members:
                    # Skip bots
                    if member.bot:
                        continue

                    # Update last seen status
                    status_update = {
                        "user_id": str(member.id),
                        f"last_status.{member.status}": now
                    }

                    if member.status != nextcord.Status.offline:
                        status_update["last_active"] = now

                    await self.user_activity.update_one(
                        {"user_id": str(member.id)},
                        {"$set": status_update},
                        upsert=True
                    )

        except Exception as e:
            logger.error(f"Error tracking activity: {str(e)}")

    @tasks.loop(hours=24)
    async def check_inactive_users(self):
        """Check for inactive users and send reminders"""
        try:
            week_ago = datetime.utcnow() - timedelta(days=7)
            async for user in self.user_activity.find({"last_active": {"$lt": week_ago}}):
                discord_user = self.bot.get_user(int(user["user_id"]))
                if discord_user:
                    await self.send_inactivity_reminder(discord_user)

        except Exception as e:
            logger.error(f"Error checking inactive users: {str(e)}")

    @tasks.loop(hours=1)
    async def update_leaderboards(self):
        """Update engagement leaderboards"""
        try:
            # Calculate engagement scores for the past week
            week_ago = datetime.utcnow() - timedelta(days=7)
            
            pipeline = [
                {
                    "$match": {
                        "timestamp": {"$gte": week_ago}
                    }
                },
                {
                    "$group": {
                        "_id": "$user_id",
                        "total_points": {"$sum": "$points"},
                        "activities": {"$push": "$activity_type"}
                    }
                },
                {
                    "$sort": {"total_points": -1}
                },
                {
                    "$limit": 10
                }
            ]

            leaderboard = await self.engagement_metrics.aggregate(pipeline).to_list(length=None)
            
            # Update leaderboard channel if configured
            if leaderboard_channel := await self.get_leaderboard_channel():
                await self.update_leaderboard_message(leaderboard_channel, leaderboard)

        except Exception as e:
            logger.error(f"Error updating leaderboards: {str(e)}")

    async def get_leaderboard_channel(self) -> Optional[nextcord.TextChannel]:
        """Get the configured leaderboard channel"""
        # Add your channel configuration logic here
        return None

    async def update_leaderboard_message(self, channel: nextcord.TextChannel, leaderboard: List[Dict]):
        """Update the leaderboard message in the specified channel"""
        embed = nextcord.Embed(
            title="🏆 Weekly Engagement Leaderboard",
            description="Top contributors this week:",
            color=nextcord.Color.gold()
        )

        for i, entry in enumerate(leaderboard, 1):
            user = self.bot.get_user(int(entry["_id"]))
            if user:
                activity_counts = {}
                for activity in entry["activities"]:
                    activity_counts[activity] = activity_counts.get(activity, 0) + 1

                activities = ", ".join(f"{count} {activity}s" for activity, count in activity_counts.items())
                
                embed.add_field(
                    name=f"{i}. {user.display_name}",
                    value=f"Points: {entry['total_points']:.1f}\nActivities: {activities}",
                    inline=False
                )

        # Find and update existing leaderboard message, or send new one
        async for message in channel.history(limit=50):
            if message.author == self.bot.user and "Weekly Engagement Leaderboard" in message.content:
                await message.edit(embed=embed)
                return

        await channel.send(embed=embed)

    async def send_inactivity_reminder(self, user: nextcord.User):
        """Send an inactivity reminder to a user"""
        try:
            # Get user's recent activity summary
            activity = await self.user_activity.find_one({"user_id": str(user.id)})
            if not activity:
                return

            embed = nextcord.Embed(
                title="👋 We Miss You!",
                description="It's been a while since we've seen you active in the community.",
                color=nextcord.Color.blue()
            )

            # Get pending items
            pending_connections = await self.bot.get_cog("Connections").get_pending_requests(str(user.id))
            unread_messages = await self.get_unread_message_count(str(user.id))
            upcoming_events = await self.bot.get_cog("Events").get_upcoming_user_events(str(user.id))

            if pending_connections:
                embed.add_field(
                    name="📫 Pending Connections",
                    value=f"You have {len(pending_connections)} pending connection requests",
                    inline=False
                )

            if unread_messages:
                embed.add_field(
                    name="💬 Unread Messages",
                    value=f"You have {unread_messages} unread messages",
                    inline=False
                )

            if upcoming_events:
                events_text = "\n".join([
                    f"• {event['title']} on {event['date'].strftime('%Y-%m-%d')}"
                    for event in upcoming_events[:3]
                ])
                embed.add_field(
                    name="📅 Upcoming Events",
                    value=events_text,
                    inline=False
                )

            embed.add_field(
                name="🔄 Ready to Return?",
                value="Update your profile, connect with peers, or join an upcoming event!",
                inline=False
            )

            await user.send(embed=embed)

        except nextcord.Forbidden:
            logger.warning(f"Could not send inactivity reminder to user {user.id}")
        except Exception as e:
            logger.error(f"Error sending inactivity reminder: {str(e)}")

    async def get_unread_message_count(self, user_id: str) -> int:
        """Get count of unread messages for a user"""
        # Add your unread message tracking logic here
        return 0

    @commands.Cog.listener()
    async def on_message(self, message: nextcord.Message):
        """Track message activity"""
        if message.author.bot:
            return

        await self.log_activity(
            user_id=str(message.author.id),
            activity_type="message",
            points=self.point_values["message"],
            details={"channel_id": str(message.channel.id)}
        )

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: nextcord.Reaction, user: nextcord.User):
        """Track reaction activity"""
        if user.bot:
            return

        await self.log_activity(
            user_id=str(user.id),
            activity_type="reaction",
            points=self.point_values["reaction"],
            details={"message_id": str(reaction.message.id)}
        )

    async def log_activity(self, user_id: str, activity_type: str, points: float, details: Dict = None):
        """Log user activity with points"""
        try:
            activity = {
                "user_id": user_id,
                "activity_type": activity_type,
                "points": points,
                "timestamp": datetime.utcnow()
            }

            if details:
                activity["details"] = details

            await self.engagement_metrics.insert_one(activity)

            # Update user's total points
            await self.user_activity.update_one(
                {"user_id": user_id},
                {
                    "$inc": {"total_points": points},
                    "$set": {"last_active": datetime.utcnow()}
                },
                upsert=True
            )

            # Check for achievements
            await self.check_achievements(user_id)

        except Exception as e:
            logger.error(f"Error logging activity: {str(e)}")

    async def check_achievements(self, user_id: str):
        """Check and award achievements based on activity"""
        try:
            # Get user's current stats
            stats = await self.user_activity.find_one({"user_id": user_id})
            if not stats:
                return

            # Define achievement criteria
            achievements = {
                "networker": {
                    "name": "Master Networker",
                    "description": "Made 50+ connections",
                    "condition": lambda s: s.get("connection_count", 0) >= 50
                },
                "contributor": {
                    "name": "Active Contributor",
                    "description": "Earned 1000+ engagement points",
                    "condition": lambda s: s.get("total_points", 0) >= 1000
                },
                "mentor": {
                    "name": "Community Mentor",
                    "description": "Endorsed 20+ skills",
                    "condition": lambda s: s.get("endorsements_given", 0) >= 20
                }
            }

            # Check each achievement
            for achievement_id, achievement in achievements.items():
                if achievement["condition"](stats):
                    # Check if already awarded
                    existing = await self.achievements.find_one({
                        "user_id": user_id,
                        "achievement_id": achievement_id
                    })

                    if not existing:
                        # Award new achievement
                        await self.achievements.insert_one({
                            "user_id": user_id,
                            "achievement_id": achievement_id,
                            "name": achievement["name"],
                            "awarded_at": datetime.utcnow()
                        })

                        # Notify user
                        user = self.bot.get_user(int(user_id))
                        if user:
                            embed = nextcord.Embed(
                                title="🏅 Achievement Unlocked!",
                                description=f"Congratulations! You've earned: {achievement['name']}",
                                color=nextcord.Color.gold()
                            )
                            embed.add_field(
                                name="Description",
                                value=achievement["description"],
                                inline=False
                            )
                            try:
                                await user.send(embed=embed)
                            except nextcord.Forbidden:
                                pass

        except Exception as e:
            logger.error(f"Error checking achievements: {str(e)}")

    @commands.group(invoke_without_command=True)
    async def stats(self, ctx):
        """View your engagement statistics"""
        if ctx.invoked_subcommand is None:
            stats = await self.user_activity.find_one({"user_id": str(ctx.author.id)})
            if not stats:
                await ctx.send("No activity recorded yet!")
                return

            embed = nextcord.Embed(
                title="📊 Your Engagement Statistics",
                color=nextcord.Color.blue()
            )

            # General stats
            embed.add_field(
                name="Overall",
                value=f"""
                Total Points: {stats.get('total_points', 0):.1f}
                Connections: {stats.get('connection_count', 0)}
                Skills Endorsed: {stats.get('endorsements_given', 0)}
                Events Attended: {stats.get('events_attended', 0)}
                """,
                inline=False
            )

            # Recent activity
            week_ago = datetime.utcnow() - timedelta(days=7)
            recent_activities = await self.engagement_metrics.find({
                "user_id": str(ctx.author.id),
                "timestamp": {"$gte": week_ago}
            }).to_list(length=None)

            if recent_activities:
                activity_counts = {}
                for activity in recent_activities:
                    activity_type = activity["activity_type"]
                    activity_counts[activity_type] = activity_counts.get(activity_type, 0) + 1

                activities_text = "\n".join([
                    f"{count} {activity_type}s"
                    for activity_type, count in activity_counts.items()
                ])

                embed.add_field(
                    name="This Week",
                    value=activities_text,
                    inline=False
                )

            # Achievements
            achievements = await self.achievements.find({
                "user_id": str(ctx.author.id)
            }).to_list(length=None)

            if achievements:
                achievements_text = "\n".join([
                    f"🏅 {a['name']}"
                    for a in achievements
                ])
                embed.add_field(
                    name="Achievements",
                    value=achievements_text,
                    inline=False
                )

            await ctx.send(embed=embed)

def setup(bot):
    """Setup the Engagement cog"""
    bot.add_cog(Engagement(bot))
    logger.info("Engagement cog loaded successfully")