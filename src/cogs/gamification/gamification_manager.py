import nextcord
from nextcord.ext import commands
import logging
import math
from datetime import datetime
from typing import Dict, Optional
from src.database.database import db, get_or_create_user
from src.config.config import POINTS_CONFIG

logger = logging.getLogger('VEKA.gamification')


class GamificationManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.point_actions = {
            'quiz_correct':        POINTS_CONFIG.get('quiz_correct', 10),
            'quiz_participation':  2,
            'workshop_host':       50,
            'workshop_attendance': 20,
            'mentorship_complete': POINTS_CONFIG.get('mentor_session', 30),
            'daily_activity':      POINTS_CONFIG.get('daily_streak', 20),
            'portfolio_update':    15,
            'helpful_response':    10,
        }

    async def award_points(self, discord_id: str, action: str, bonus: int = 0) -> Optional[Dict]:
        if action not in self.point_actions:
            return None
        points = self.point_actions[action] + bonus
        user = await get_or_create_user(discord_id)

        old_level = user['level']
        new_points = user['points'] + points
        new_exp = user['experience'] + points
        new_level = 1 + math.floor(math.sqrt(new_exp / 100))

        updated = await db.fetch_one(
            """
            UPDATE users
               SET points     = $1,
                   experience = $2,
                   level      = $3,
                   updated_at = NOW()
             WHERE discord_id = $4
             RETURNING *
            """,
            new_points, new_exp, new_level, discord_id
        )
        return {
            'points_earned': points,
            'new_points':    new_points,
            'new_level':     new_level,
            'leveled_up':    new_level > old_level,
            'levels_gained': max(0, new_level - old_level),
        }

    @commands.command(name='gameprofile', description='View your gamification profile')
    async def gameprofile(self, ctx, member: nextcord.Member = None):
        target = member or ctx.author
        user = await get_or_create_user(str(target.id))

        current_level = user['level']
        current_exp   = user['experience']
        exp_for_current = 100 * (current_level - 1) ** 2
        exp_for_next    = 100 * current_level ** 2
        exp_needed      = exp_for_next - exp_for_current
        exp_progress    = current_exp - exp_for_current
        progress_pct    = min(100, max(0, (exp_progress / exp_needed) * 100)) if exp_needed else 100

        created_at = user['created_at']
        member_since = created_at.strftime('%Y-%m-%d') if created_at else 'Unknown'

        embed = nextcord.Embed(title=f"🏆 {target.display_name}'s Profile", color=nextcord.Color.orange())
        embed.add_field(
            name='📊 Stats',
            value=(
                f"**Level:** {current_level}\n"
                f"**Experience:** {current_exp:,}\n"
                f"**Points:** {user['points']:,}\n"
                f"**Member Since:** {member_since}"
            ),
            inline=False
        )
        bar = self._progress_bar(progress_pct)
        embed.add_field(
            name=f"📈 Level Progress ({progress_pct:.1f}%)",
            value=f"`{bar}` {exp_progress:,}/{exp_needed:,} XP to Level {current_level + 1}",
            inline=False
        )
        embed.set_thumbnail(url=target.avatar.url if target.avatar else target.default_avatar.url)
        await ctx.send(embed=embed)

    @commands.command(name='leaderboard', description='View the points leaderboard')
    async def leaderboard(self, ctx):
        rows = await db.fetch_many(
            "SELECT discord_id, points, level FROM users ORDER BY points DESC LIMIT 10"
        )
        if not rows:
            await ctx.send('No users on the leaderboard yet!')
            return

        embed = nextcord.Embed(title='🏆 Server Leaderboard', description='Top members by points',
                               color=nextcord.Color.orange())
        text = ''
        for i, row in enumerate(rows):
            medal = '🥇' if i == 0 else '🥈' if i == 1 else '🥉' if i == 2 else f'{i + 1}.'
            member = ctx.guild.get_member(int(row['discord_id']))
            name = member.display_name if member else f"User {row['discord_id']}"
            text += f"{medal} **{name}** — Level {row['level']} | {row['points']:,} pts\n"

        embed.add_field(name='Top Members', value=text, inline=False)
        embed.set_footer(text='Keep participating to climb the ranks!')
        await ctx.send(embed=embed)

    def _progress_bar(self, percent: float, length: int = 20) -> str:
        filled = int(length * percent / 100)
        return '█' * filled + '░' * (length - filled)

    @commands.Cog.listener()
    async def on_message(self, message):
        """Award daily_activity points once per calendar day per user."""
        if message.author.bot:
            return
        try:
            today = datetime.utcnow().date().isoformat()
            result = await db.execute(
                """
                UPDATE users
                   SET last_daily_activity = $1
                 WHERE discord_id = $2
                   AND (last_daily_activity IS NULL OR last_daily_activity < $1::date)
                """,
                today, str(message.author.id)
            )
            if result == 'UPDATE 1':
                await self.award_points(str(message.author.id), 'daily_activity')
        except Exception as e:
            logger.error(f'Error in daily activity tracking: {e}')


def setup(bot):
    bot.add_cog(GamificationManager(bot))
    logging.getLogger('VEKA').info('Loaded cog: src.cogs.gamification.gamification_manager')
