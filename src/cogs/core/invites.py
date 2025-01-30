import discord
from discord.ext import commands
from utils.database import Database
from utils.logger import setup_logger
from typing import Dict, Optional

logger = setup_logger()

class InviteTracker(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = Database.db
        self.invite_cache: Dict[int, Dict[str, discord.Invite]] = {}

    async def cache_invites(self, guild: discord.Guild) -> None:
        """Cache all invites for a guild."""
        try:
            invites = await guild.invites()
            self.invite_cache[guild.id] = {
                invite.code: invite for invite in invites
            }
        except Exception as e:
            logger.error(f"Failed to cache invites for guild {guild.id}: {str(e)}")

    @commands.Cog.listener()
    async def on_ready(self):
        """Cache invites for all guilds when bot starts."""
        for guild in self.bot.guilds:
            await self.cache_invites(guild)

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        """Update cache when new invite is created."""
        if invite.guild.id not in self.invite_cache:
            self.invite_cache[invite.guild.id] = {}
        self.invite_cache[invite.guild.id][invite.code] = invite

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Track which invite was used when member joins."""
        try:
            # Get new invite list
            new_invites = await member.guild.invites()
            old_invites = self.invite_cache[member.guild.id]

            # Find used invite by comparing counts
            used_invite = None
            for invite in new_invites:
                if invite.code in old_invites:
                    if invite.uses > old_invites[invite.code].uses:
                        used_invite = invite
                        break

            # Update cache
            self.invite_cache[member.guild.id] = {
                invite.code: invite for invite in new_invites
            }

            # Store in database
            if used_invite:
                await self.db.invite_logs.insert_one({
                    "guild_id": member.guild.id,
                    "user_id": member.id,
                    "inviter_id": used_invite.inviter.id,
                    "invite_code": used_invite.code,
                    "timestamp": discord.utils.utcnow().timestamp()
                })

        except Exception as e:
            logger.error(f"Error tracking invite for {member.id}: {str(e)}")

    @commands.hybrid_command(name="invites", description="View invite statistics")
    async def invites(self, ctx: commands.Context, member: Optional[discord.Member] = None):
        """View invite statistics for a user or yourself."""
        member = member or ctx.author
        
        try:
            # Query database for invite stats
            stats = await self.db.invite_logs.count_documents({
                "guild_id": ctx.guild.id,
                "inviter_id": member.id
            })

            embed = discord.Embed(
                title="Invite Statistics",
                description=f"{member.mention} has invited {stats} members!",
                color=discord.Color.blue()
            )
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error fetching invite stats: {str(e)}")
            await ctx.send("Failed to fetch invite statistics.")

async def setup(bot: commands.Bot):
    await bot.add_cog(InviteTracker(bot)) 