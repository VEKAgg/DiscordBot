import discord
from discord.ext import commands
from utils.database import Database
from utils.logger import setup_logger
from typing import Dict, Optional
from datetime import datetime, timedelta
import asyncio
from discord.ext import commands
from discord import app_commands

logger = setup_logger()

class InviteTracker(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = Database.db
        self.invite_cache: Dict[int, Dict[str, discord.Invite]] = {}
        self.leveling_cog = None
        
        # Anti-abuse settings
        self.invite_cooldown = commands.CooldownMapping.from_cooldown(5, 86400, commands.BucketType.member)  # 5 invites per day
        self.min_account_age = timedelta(days=7)  # Minimum account age for rewards
        self.min_member_stay = timedelta(days=3)  # How long invited member must stay
        self.pending_invites = {}  # Track pending invite rewards

        # Invite XP rewards
        self.invite_xp_rewards = {
            5: {"xp": 1000, "role_id": None, "message": "Recruiter"},
            10: {"xp": 2500, "role_id": None, "message": "Talent Scout"},
            25: {"xp": 5000, "role_id": None, "message": "Community Builder"},
            50: {"xp": 10000, "role_id": None, "message": "Growth Master"},
            100: {"xp": 25000, "role_id": None, "message": "Server Legend"}
        }

    async def get_leveling_cog(self):
        if not self.leveling_cog:
            self.leveling_cog = self.bot.get_cog("Leveling")
        return self.leveling_cog

    async def check_invite_validity(self, member: discord.Member, inviter: discord.Member) -> bool:
        """Check if an invite should be rewarded."""
        try:
            # Check inviter's cooldown
            bucket = self.invite_cooldown.get_bucket(inviter)
            if bucket.update_rate_limit():
                return False

            # Check if accounts are too new
            if datetime.utcnow() - member.created_at < self.min_account_age:
                return False

            # Check for self-invites or bot invites
            if member.bot or member.id == inviter.id:
                return False

            # Check for previous leaves/joins
            previous_joins = await self.db.invite_logs.count_documents({
                "guild_id": member.guild.id,
                "user_id": member.id
            })
            if previous_joins > 0:
                return False

            return True

        except Exception as e:
            logger.error(f"Error checking invite validity: {str(e)}")
            return False

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

        try:
            leveling_cog = await self.get_leveling_cog()
            if leveling_cog:
                # Add invite leaderboard type
                leveling_cog.leaderboard.choices.append(
                    app_commands.Choice(name="Invites", value="invites")
                )
        except Exception as e:
            logger.error(f"Error adding invite leaderboard: {str(e)}")

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        """Update cache when new invite is created."""
        if invite.guild.id not in self.invite_cache:
            self.invite_cache[invite.guild.id] = {}
        self.invite_cache[invite.guild.id][invite.code] = invite

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        try:
            new_invites = await member.guild.invites()
            old_invites = self.invite_cache[member.guild.id]
            used_invite = None

            for invite in new_invites:
                if invite.code in old_invites:
                    if invite.uses > old_invites[invite.code].uses:
                        used_invite = invite
                        break

            self.invite_cache[member.guild.id] = {
                invite.code: invite for invite in new_invites
            }

            if used_invite and used_invite.inviter:
                # Store invite data
                await self.db.invite_logs.insert_one({
                    "guild_id": member.guild.id,
                    "user_id": member.id,
                    "inviter_id": used_invite.inviter.id,
                    "invite_code": used_invite.code,
                    "timestamp": datetime.utcnow(),
                    "rewarded": False
                })

                # Track pending reward
                self.pending_invites[member.id] = {
                    "inviter_id": used_invite.inviter.id,
                    "join_time": datetime.utcnow()
                }

        except Exception as e:
            logger.error(f"Error tracking invite: {str(e)}")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """Remove pending invite rewards if member leaves too soon."""
        if member.id in self.pending_invites:
            del self.pending_invites[member.id]

    async def process_pending_invites(self):
        """Process pending invite rewards periodically."""
        while not self.bot.is_closed():
            try:
                current_time = datetime.utcnow()
                to_remove = []

                for member_id, data in self.pending_invites.items():
                    if current_time - data["join_time"] >= self.min_member_stay:
                        guild_id = data.get("guild_id")
                        inviter_id = data["inviter_id"]
                        
                        guild = self.bot.get_guild(guild_id)
                        if guild:
                            member = guild.get_member(member_id)
                            inviter = guild.get_member(inviter_id)
                            
                            if member and inviter and await self.check_invite_validity(member, inviter):
                                leveling_cog = await self.get_leveling_cog()
                                if leveling_cog:
                                    # Award XP for successful invite
                                    await leveling_cog.award_xp(inviter, 500, "invite")
                                    
                                    # Update invite log
                                    await self.db.invite_logs.update_one(
                                        {
                                            "guild_id": guild_id,
                                            "user_id": member_id,
                                            "inviter_id": inviter_id
                                        },
                                        {"$set": {"rewarded": True}}
                                    )
                        
                        to_remove.append(member_id)

                for member_id in to_remove:
                    del self.pending_invites[member_id]

                await asyncio.sleep(3600)  # Check every hour

            except Exception as e:
                logger.error(f"Error processing pending invites: {str(e)}")
                await asyncio.sleep(300)  # Wait 5 minutes on error

    @app_commands.command(name="invites", description="View invite statistics")
    async def invites(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        member = member or interaction.user
        await interaction.response.defer()
        
        try:
            # Get detailed invite stats
            total_invites = await self.db.invite_logs.count_documents({
                "guild_id": interaction.guild.id,
                "inviter_id": member.id
            })
            
            valid_invites = await self.db.invite_logs.count_documents({
                "guild_id": interaction.guild.id,
                "inviter_id": member.id,
                "rewarded": True
            })

            embed = discord.Embed(
                title="📊 Invite Statistics",
                color=member.color
            )
            embed.add_field(name="Total Invites", value=str(total_invites), inline=True)
            embed.add_field(name="Valid Invites", value=str(valid_invites), inline=True)
            embed.add_field(name="XP Earned", value=f"{valid_invites * 500:,} XP", inline=True)
            embed.set_footer(text="Valid invites: Members who stayed at least 3 days")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error fetching invite stats: {str(e)}")
            await interaction.followup.send("Failed to fetch invite statistics.")

    async def check_invite_milestone(self, member: discord.Member):
        try:
            valid_invites = await self.db.invite_logs.count_documents({
                "guild_id": member.guild.id,
                "inviter_id": member.id,
                "rewarded": True
            })

            # Check for new milestones
            for invite_count, reward in self.invite_xp_rewards.items():
                if valid_invites >= invite_count:
                    # Check if milestone was already awarded
                    milestone_check = await self.db.invite_milestones.find_one({
                        "guild_id": member.guild.id,
                        "user_id": member.id,
                        "milestone": invite_count
                    })

                    if not milestone_check:
                        # Award XP
                        leveling_cog = await self.get_leveling_cog()
                        if leveling_cog:
                            await leveling_cog.award_xp(member, reward["xp"], "invite_milestone")

                        # Assign role if configured
                        settings = await self.db.guild_settings.find_one({"guild_id": member.guild.id})
                        if settings and settings.get("invite_roles", {}).get(str(invite_count)):
                            role_id = settings["invite_roles"][str(invite_count)]
                            role = member.guild.get_role(role_id)
                            if role:
                                await member.add_roles(role)

                        # Send notification
                        embed = discord.Embed(
                            title="🎉 Invite Milestone Reached!",
                            description=f"{member.mention} has reached {invite_count} successful invites!\n"
                                      f"Reward: {reward['xp']:,} XP\n"
                                      f"Title: {reward['message']}",
                            color=discord.Color.gold()
                        )

                        # Find channel to send notification
                        if settings and settings.get("milestone_channel"):
                            channel = self.bot.get_channel(settings["milestone_channel"])
                            if channel:
                                await channel.send(embed=embed)

                        # Record milestone
                        await self.db.invite_milestones.insert_one({
                            "guild_id": member.guild.id,
                            "user_id": member.id,
                            "milestone": invite_count,
                            "timestamp": datetime.utcnow()
                        })

        except Exception as e:
            logger.error(f"Error checking invite milestone: {str(e)}")

    @app_commands.command(name="invitesettings", description="Configure invite settings")
    @app_commands.default_permissions(manage_guild=True)
    async def invite_settings(self, interaction: discord.Interaction):
        await interaction.response.defer()
        embed = discord.Embed(
            title="Invite Settings",
            description="Use the following commands to configure invite settings:",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="/invitesettings setrole",
            value="Set role rewards for invite milestones",
            inline=False
        )
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="setinviterole", description="Set role for invite milestone")
    @app_commands.default_permissions(manage_guild=True)
    async def set_invite_role(self, interaction: discord.Interaction, milestone: int, role: discord.Role):
        await interaction.response.defer()
        try:
            if milestone not in self.invite_xp_rewards:
                valid_milestones = ", ".join(str(m) for m in self.invite_xp_rewards.keys())
                await interaction.followup.send(f"Invalid milestone. Valid milestones: {valid_milestones}")
                return

            await self.db.guild_settings.update_one(
                {"guild_id": interaction.guild.id},
                {"$set": {f"invite_roles.{milestone}": role.id}},
                upsert=True
            )

            await interaction.followup.send(f"Set {role.mention} as the reward for {milestone} invites!")

        except Exception as e:
            logger.error(f"Error setting invite role: {str(e)}")
            await interaction.followup.send("Failed to set invite role.")

async def setup(bot: commands.Bot):
    cog = InviteTracker(bot)
    bot.loop.create_task(cog.process_pending_invites())
    await bot.add_cog(cog) 