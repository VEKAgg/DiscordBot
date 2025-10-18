import nextcord
from nextcord.ext import commands, tasks
import logging
from datetime import datetime, timedelta
import asyncio
from typing import List, Dict, Optional
import re

logger = logging.getLogger('VEKA.moderation')

class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.mongo
        self.verification_queue = self.db.verification_queue
        self.server_settings = self.db.server_settings
        self.user_reports = self.db.user_reports
        self.check_verification_queue.start()
        
        # Default verification requirements
        self.verification_requirements = {
            "min_account_age_days": 30,
            "min_profile_completion": 0.6,
            "required_fields": [
                "title", "headline", "skills"
            ]
        }

        # Feature gates for different server tiers
        self.feature_gates = {
            "free": {
                "max_connections": 50,
                "max_events": 5,
                "max_job_alerts": 2,
                "advanced_analytics": False,
                "custom_branding": False
            },
            "premium": {
                "max_connections": 500,
                "max_events": 50,
                "max_job_alerts": 10,
                "advanced_analytics": True,
                "custom_branding": True
            }
        }

    def cog_unload(self):
        self.check_verification_queue.cancel()

    @tasks.loop(minutes=30)
    async def check_verification_queue(self):
        """Process verification queue periodically"""
        try:
            async for entry in self.verification_queue.find({"status": "pending"}):
                user_id = entry["user_id"]
                guild_id = entry["guild_id"]
                
                guild = self.bot.get_guild(int(guild_id))
                if not guild:
                    continue

                member = guild.get_member(int(user_id))
                if not member:
                    continue

                # Check auto-verification criteria
                meets_criteria = await self.check_verification_criteria(member)
                
                if meets_criteria:
                    await self.approve_verification(member, guild, auto=True)
                else:
                    # Notify admins if manual review needed
                    await self.notify_admins_verification(member, guild)

        except Exception as e:
            logger.error(f"Error processing verification queue: {str(e)}")

    async def check_verification_criteria(self, member: nextcord.Member) -> bool:
        """Check if a member meets auto-verification criteria"""
        try:
            # Check account age
            account_age = datetime.utcnow() - member.created_at
            if account_age.days < self.verification_requirements["min_account_age_days"]:
                return False

            # Check profile completion
            profile = await self.db.profiles.find_one({"user_id": str(member.id)})
            if not profile:
                return False

            # Calculate profile completion percentage
            total_fields = len(self.verification_requirements["required_fields"])
            filled_fields = sum(
                1 for field in self.verification_requirements["required_fields"]
                if profile.get(field)
            )
            completion = filled_fields / total_fields

            if completion < self.verification_requirements["min_profile_completion"]:
                return False

            return True

        except Exception as e:
            logger.error(f"Error checking verification criteria: {str(e)}")
            return False

    async def notify_admins_verification(self, member: nextcord.Member, guild: nextcord.Guild):
        """Notify admins about pending verification"""
        try:
            # Get admin channel
            admin_channel = await self.get_admin_channel(guild)
            if not admin_channel:
                return

            profile = await self.db.profiles.find_one({"user_id": str(member.id)})
            
            embed = nextcord.Embed(
                title="👥 Pending Verification",
                description=f"New member requires manual verification",
                color=nextcord.Color.gold()
            )
            
            embed.add_field(
                name="Member",
                value=f"{member.mention} ({member.name}#{member.discriminator})",
                inline=False
            )
            
            embed.add_field(
                name="Account Age",
                value=f"{(datetime.utcnow() - member.created_at).days} days",
                inline=True
            )

            if profile:
                embed.add_field(
                    name="Profile",
                    value=f"""
                    Title: {profile.get('title', 'Not set')}
                    Headline: {profile.get('headline', 'Not set')}
                    Skills: {', '.join(profile.get('skills', ['None']))}
                    """,
                    inline=False
                )

            # Add verification buttons
            view = VerificationView(self, member)
            await admin_channel.send(embed=embed, view=view)

        except Exception as e:
            logger.error(f"Error notifying admins: {str(e)}")

    async def get_admin_channel(self, guild: nextcord.Guild) -> Optional[nextcord.TextChannel]:
        """Get the admin channel for a guild"""
        settings = await self.server_settings.find_one({"guild_id": str(guild.id)})
        if settings and (channel_id := settings.get("admin_channel_id")):
            return guild.get_channel(int(channel_id))
        return None

    async def approve_verification(self, member: nextcord.Member, guild: nextcord.Guild, auto: bool = False):
        """Approve a member's verification"""
        try:
            # Get verified role
            settings = await self.server_settings.find_one({"guild_id": str(guild.id)})
            if not settings or not settings.get("verified_role_id"):
                return

            verified_role = guild.get_role(int(settings["verified_role_id"]))
            if not verified_role:
                return

            # Add role
            await member.add_roles(verified_role)

            # Update database
            await self.verification_queue.update_one(
                {
                    "user_id": str(member.id),
                    "guild_id": str(guild.id)
                },
                {
                    "$set": {
                        "status": "approved",
                        "approved_at": datetime.utcnow(),
                        "auto_approved": auto
                    }
                }
            )

            # Notify member
            embed = nextcord.Embed(
                title="✅ Verification Approved",
                description="Your account has been verified!",
                color=nextcord.Color.green()
            )
            try:
                await member.send(embed=embed)
            except nextcord.Forbidden:
                pass

        except Exception as e:
            logger.error(f"Error approving verification: {str(e)}")

    @commands.group(invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def moderation(self, ctx):
        """Moderation and verification commands"""
        if ctx.invoked_subcommand is None:
            embed = nextcord.Embed(
                title="🛡️ Moderation Commands",
                description="Server moderation and verification settings",
                color=nextcord.Color.blue()
            )
            embed.add_field(
                name="Available Commands",
                value="""
                `!moderation settings` - View/edit moderation settings
                `!moderation queue` - View verification queue
                `!moderation verify <@user>` - Manually verify a user
                `!moderation stats` - View moderation statistics
                `!moderation reports` - View reported content/users
                """,
                inline=False
            )
            await ctx.send(embed=embed)

    @moderation.command(name="settings")
    @commands.has_permissions(administrator=True)
    async def mod_settings(self, ctx):
        """View and edit moderation settings"""
        settings = await self.server_settings.find_one({"guild_id": str(ctx.guild.id)})
        if not settings:
            settings = {
                "guild_id": str(ctx.guild.id),
                "verified_role_id": None,
                "admin_channel_id": None,
                "auto_verification": True,
                "min_account_age_days": 30,
                "min_profile_completion": 0.6
            }
            await self.server_settings.insert_one(settings)

        embed = nextcord.Embed(
            title="⚙️ Moderation Settings",
            color=nextcord.Color.blue()
        )

        # Current settings
        verified_role = ctx.guild.get_role(int(settings["verified_role_id"])) if settings.get("verified_role_id") else None
        admin_channel = ctx.guild.get_channel(int(settings["admin_channel_id"])) if settings.get("admin_channel_id") else None

        embed.add_field(
            name="Current Settings",
            value=f"""
            Verified Role: {verified_role.mention if verified_role else 'Not set'}
            Admin Channel: {admin_channel.mention if admin_channel else 'Not set'}
            Auto-verification: {'Enabled' if settings.get('auto_verification', True) else 'Disabled'}
            Min Account Age: {settings.get('min_account_age_days', 30)} days
            Min Profile Completion: {settings.get('min_profile_completion', 0.6) * 100}%
            """,
            inline=False
        )

        # Server tier info
        server_tier = "premium" if await self.check_premium(ctx.guild) else "free"
        features = self.feature_gates[server_tier]
        
        embed.add_field(
            name="Server Tier",
            value=f"""
            Current Tier: {server_tier.title()}
            Max Connections: {features['max_connections']}
            Max Events: {features['max_events']}
            Max Job Alerts: {features['max_job_alerts']}
            Advanced Analytics: {'✅' if features['advanced_analytics'] else '❌'}
            Custom Branding: {'✅' if features['custom_branding'] else '❌'}
            """,
            inline=False
        )

        await ctx.send(embed=embed)

    @moderation.command(name="queue")
    @commands.has_permissions(administrator=True)
    async def mod_queue(self, ctx):
        """View the verification queue"""
        queue = await self.verification_queue.find({
            "guild_id": str(ctx.guild.id),
            "status": "pending"
        }).to_list(length=None)

        if not queue:
            await ctx.send("No pending verifications!")
            return

        embed = nextcord.Embed(
            title="👥 Verification Queue",
            description=f"{len(queue)} pending verifications",
            color=nextcord.Color.gold()
        )

        for entry in queue[:10]:  # Show first 10
            member = ctx.guild.get_member(int(entry["user_id"]))
            if member:
                profile = await self.db.profiles.find_one({"user_id": entry["user_id"]})
                embed.add_field(
                    name=f"{member.name}#{member.discriminator}",
                    value=f"""
                    Joined: {member.joined_at.strftime('%Y-%m-%d')}
                    Profile: {"Complete" if profile else "Incomplete"}
                    Queued: {entry['created_at'].strftime('%Y-%m-%d %H:%M')}
                    """,
                    inline=False
                )

        if len(queue) > 10:
            embed.set_footer(text=f"Showing 10 of {len(queue)} pending verifications")

        await ctx.send(embed=embed)

    @moderation.command(name="verify")
    @commands.has_permissions(administrator=True)
    async def mod_verify(self, ctx, member: nextcord.Member):
        """Manually verify a member"""
        await self.approve_verification(member, ctx.guild)
        await ctx.send(f"✅ Verified {member.mention}")

    async def check_premium(self, guild: nextcord.Guild) -> bool:
        """Check if a guild has premium features"""
        settings = await self.server_settings.find_one({"guild_id": str(guild.id)})
        return settings.get("premium", False)

    @commands.Cog.listener()
    async def on_member_join(self, member: nextcord.Member):
        """Handle new member verification"""
        if member.bot:
            return

        # Add to verification queue
        await self.verification_queue.insert_one({
            "user_id": str(member.id),
            "guild_id": str(member.guild.id),
            "status": "pending",
            "created_at": datetime.utcnow()
        })

        # Send welcome message with verification instructions
        embed = nextcord.Embed(
            title="👋 Welcome!",
            description=f"Welcome to {member.guild.name}!",
            color=nextcord.Color.blue()
        )
        
        embed.add_field(
            name="Getting Verified",
            value=f"""
            To get verified:
            1. Set up your profile using `!profile setup`
            2. Make sure your account is at least {self.verification_requirements['min_account_age_days']} days old
            3. Fill out at least {self.verification_requirements['min_profile_completion']*100}% of your profile
            
            Your verification will be processed automatically if you meet these criteria.
            Otherwise, a moderator will review your profile manually.
            """,
            inline=False
        )

        try:
            await member.send(embed=embed)
        except nextcord.Forbidden:
            pass

class VerificationView(nextcord.ui.View):
    def __init__(self, cog: Moderation, member: nextcord.Member):
        super().__init__(timeout=None)
        self.cog = cog
        self.member = member

    @nextcord.ui.button(label="Approve", style=nextcord.ButtonStyle.green)
    async def approve(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await self.cog.approve_verification(self.member, interaction.guild)
        await interaction.response.send_message(f"✅ Approved {self.member.mention}")
        self.stop()

    @nextcord.ui.button(label="Deny", style=nextcord.ButtonStyle.red)
    async def deny(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await self.cog.verification_queue.update_one(
            {
                "user_id": str(self.member.id),
                "guild_id": str(interaction.guild.id)
            },
            {
                "$set": {
                    "status": "denied",
                    "denied_at": datetime.utcnow(),
                    "denied_by": str(interaction.user.id)
                }
            }
        )
        await interaction.response.send_message(f"❌ Denied {self.member.mention}")
        self.stop()

def setup(bot):
    """Setup the Moderation cog"""
    bot.add_cog(Moderation(bot))
    logger.info("Moderation cog loaded successfully")