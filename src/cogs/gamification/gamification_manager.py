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
        
        # Calculate new level (logarithmic progression)
        # Level formula: level = 1 + sqrt(experience / 100)
        new_level = 1 + math.floor(math.sqrt(new_exp / 100))
        
        # Update user record
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
        
        # Return level up information if level changed
        return {
            "points_earned": points,
            "new_points": new_points,
            "new_level": new_level,
            "leveled_up": new_level > old_level,
            "levels_gained": new_level - old_level if new_level > old_level else 0
        }

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
        current_exp = user.get('experience', 0)
        exp_for_current = 100 * (current_level - 1) ** 2
        exp_for_next = 100 * current_level ** 2
        exp_needed = exp_for_next - exp_for_current
        exp_progress = current_exp - exp_for_current
        progress_percent = min(100, max(0, (exp_progress / exp_needed) * 100))
        
        # Create progress bar
        progress_bar = self.create_progress_bar(progress_percent)
        
        embed = nextcord.Embed(
            title=f"🏆 {target.display_name}'s Profile",
            color=nextcord.Color.orange()
        )
        
        embed.add_field(
            name="📊 Stats",
            value=f"**Level:** {current_level}\n"
                  f"**Experience:** {current_exp:,}\n"
                  f"**Points:** {user.get('points', 0):,}\n"
                  f"**Member Since:** {user.get('created_at').strftime('%Y-%m-%d')}",
            inline=False
        )
        
        embed.add_field(
            name=f"📈 Level Progress ({progress_percent:.1f}%)",
            value=f"`{progress_bar}` {exp_progress:,}/{exp_needed:,} XP to Level {current_level+1}",
            inline=False
        )
        
        # Add achievements if any
        if user.get('achievements'):
            achievements = "\n".join([f"• {a}" for a in user.get('achievements', [])])
            embed.add_field(name="🏅 Achievements", value=achievements, inline=False)
        
        embed.set_thumbnail(url=target.avatar.url if target.avatar else target.default_avatar.url)
        await ctx.send(embed=embed)

    @commands.command(
        name="leaderboard",
        description="View the points leaderboard"
    )
    async def leaderboard(self, ctx):
        """View the server's points leaderboard"""
        # Get top 10 users by points
        top_users = await users.find().sort("points", -1).limit(10).to_list(length=None)
        
        if not top_users:
            await ctx.send("No users found in the leaderboard yet!")
            return
        
        embed = nextcord.Embed(
            title="🏆 Server Leaderboard",
            description="Top members by points",
            color=nextcord.Color.orange()
        )
        
        leaderboard_text = ""
        for i, user_data in enumerate(top_users):
            # Get medal emoji based on position
            medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else f"{i+1}."
            
            # Get Discord user
            discord_id = user_data.get('discord_id')
            member = ctx.guild.get_member(int(discord_id)) if discord_id else None
            name = member.display_name if member else f"User {discord_id}"
            
            # Add to leaderboard text
            leaderboard_text += f"{medal} **{name}** - Level {user_data.get('level', 1)} | {user_data.get('points', 0):,} points\n"
        
        embed.add_field(name="Top Members", value=leaderboard_text, inline=False)
        embed.set_footer(text="Keep participating to climb the ranks!")
        
        await ctx.send(embed=embed)

    def create_progress_bar(self, percent: float, length: int = 20) -> str:
        """Create a text-based progress bar"""
        filled = int(length * percent / 100)
        return "█" * filled + "░" * (length - filled)

    @commands.Cog.listener()
    async def on_message(self, message):
        """Award points for daily activity"""
        if message.author.bot:
            return
            
        # Award points for daily activity (once per day)
        # Implementation would track last activity date and award points accordingly
        # This is a simplified version
        await self.award_points(str(message.author.id), 'daily_activity')

def setup(bot):
    """Setup the GamificationManager cog"""
    if bot is not None:
        bot.add_cog(GamificationManager(bot))
        logging.getLogger('VEKA').info("Loaded cog: src.cogs.gamification.gamification_manager")
    else:
        logging.getLogger('VEKA').error("Bot is None in GamificationManager cog setup")
