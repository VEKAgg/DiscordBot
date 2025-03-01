import nextcord
from nextcord.ext import commands
import logging
from datetime import datetime
import math
from src.database.mongodb import users

logger = logging.getLogger('VEKA.gamification')

class GamificationManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.point_actions = {
            'quiz_correct': 10,
            'quiz_participation': 2,
            'workshop_host': 50,
            'workshop_attendance': 20,
            'mentorship_complete': 100,
            'daily_activity': 5,
            'portfolio_update': 15,
            'helpful_response': 10
        }

    async def get_or_create_user(self, user_id: str):
        """Get or create a user record"""
        user = await users.find_one({"discord_id": str(user_id)})
        if not user:
            user = {
                "discord_id": str(user_id),
                "points": 0,
                "experience": 0,
                "level": 1,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
            await users.insert_one(user)
        return user

    async def award_points(self, user_id: str, action: str, bonus: int = 0):
        """Award points to a user for a specific action"""
        if action not in self.point_actions:
            return
        
        points = self.point_actions[action] + bonus
        user = await self.get_or_create_user(user_id)
        
        # Update points and check for level up
        old_level = user.get('level', 1)
        new_points = user.get('points', 0) + points
        new_exp = user.get('experience', 0) + points
        
        # Calculate new level (using a logarithmic progression)
        new_level = math.floor(1 + math.log(new_exp / 100 + 1, 2))
        
        # Update user in database
        await users.update_one(
            {"discord_id": str(user_id)},
            {
                "$set": {
                    "points": new_points,
                    "experience": new_exp,
                    "level": new_level,
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        if new_level > old_level:
            # Notify user of level up
            discord_user = self.bot.get_user(int(user_id))
            if discord_user:
                embed = nextcord.Embed(
                    title="🎉 Level Up!",
                    description=f"Congratulations! You've reached level {new_level}!",
                    color=nextcord.Color.gold()
                )
                embed.add_field(name="Points Earned", value=str(points))
                embed.add_field(name="Total Points", value=str(new_points))
                await discord_user.send(embed=embed)
        
        return points, new_level > old_level

    @commands.command(
        name="gameprofile",
        description="View your gamification profile"
    )
    async def gameprofile(self, ctx, member: nextcord.Member = None):
        """View your or someone else's gamification profile"""
        target = member or ctx.author
        user = await self.get_or_create_user(str(target.id))
        
        # Calculate progress to next level
        current_level = user.get('level', 1)
        current_level_exp = 100 * (pow(2, current_level - 1) - 1)
        next_level_exp = 100 * (pow(2, current_level) - 1)
        exp_progress = user.get('experience', 0) - current_level_exp
        exp_needed = next_level_exp - current_level_exp
        progress_percent = (exp_progress / exp_needed) * 100
        
        embed = nextcord.Embed(
            title=f"{target.display_name}'s Profile",
            color=nextcord.Color.blue()
        )
        embed.set_thumbnail(url=target.avatar.url if target.avatar else target.default_avatar.url)
        
        # Add profile fields
        embed.add_field(name="Level", value=str(current_level), inline=True)
        embed.add_field(name="Total Points", value=str(user.get('points', 0)), inline=True)
        embed.add_field(name="Experience", value=f"{user.get('experience', 0):,}", inline=True)
        
        # Add progress bar
        progress_bar = self.create_progress_bar(progress_percent)
        embed.add_field(
            name="Progress to Next Level",
            value=f"{progress_bar} {progress_percent:.1f}%",
            inline=False
        )
        
        await ctx.send(embed=embed)

    @commands.command(
        name="leaderboard",
        description="View the points leaderboard"
    )
    async def leaderboard(self, ctx):
        """Display the points leaderboard"""
        # Get top 10 users by points
        cursor = users.find().sort("points", -1).limit(10)
        top_users = await cursor.to_list(length=10)
        
        embed = nextcord.Embed(
            title="🏆 Points Leaderboard",
            color=nextcord.Color.gold()
        )
        
        for i, user in enumerate(top_users, 1):
            discord_user = self.bot.get_user(int(user['discord_id']))
            name = discord_user.display_name if discord_user else f"User {user['discord_id']}"
            
            embed.add_field(
                name=f"{i}. {name}",
                value=f"Level {user.get('level', 1)} | {user.get('points', 0):,} points",
                inline=False
            )
        
        await ctx.send(embed=embed)

    def create_progress_bar(self, percent: float, length: int = 20) -> str:
        """Create a text-based progress bar"""
        filled = int((percent / 100.0) * length)
        return '█' * filled + '░' * (length - filled)

    @commands.Cog.listener()
    async def on_message(self, message):
        """Award points for daily activity"""
        if message.author.bot:
            return
        
        # Award points for daily activity (implement cooldown if needed)
        await self.award_points(str(message.author.id), 'daily_activity')

async def setup(bot):
    """Setup the GamificationManager cog"""
    if bot is not None:
        await bot.add_cog(GamificationManager(bot))
        logging.getLogger('VEKA').info("GamificationManager cog loaded successfully")
    else:
        logging.getLogger('VEKA').error("Bot is None in GamificationManager cog setup")
