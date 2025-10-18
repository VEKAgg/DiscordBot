import nextcord
from nextcord.ext import commands
import logging
from datetime import datetime
from typing import Optional
from src.services.mentorship_service import MentorshipService
from src.config.config import MENTORSHIP_CATEGORIES, MENTORSHIP_ROLES, POINTS_CONFIG

logger = logging.getLogger('VEKA.mentorship')

class Mentorship(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.mentorship_service = MentorshipService(bot)

    @nextcord.slash_command(name="mentor", description="Mentorship commands")
    async def mentor(self, interaction: nextcord.Interaction):
        """Mentorship commands"""
        embed = nextcord.Embed(
            title="Mentorship Commands",
            description="Connect with mentors and mentees!",
            color=nextcord.Color.blue()
        )
        embed.add_field(
            name="Available Commands",
            value="""
            `/mentor register <role>` - Register as a mentor or mentee
            `/mentor list [category]` - List available mentors
            `/mentor request @mentor <category>` - Request mentorship
            `/mentor accept @mentee` - Accept a mentorship request
            `/mentor complete @mentee` - Complete a mentorship
            `/mentor stats` - View mentorship statistics
            """,
            inline=False
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @mentor.subcommand(name="register", description="Register as a mentor or mentee")
    async def mentor_register(
        self,
        interaction: nextcord.Interaction,
        role: str = nextcord.SlashOption(
            name="role",
            description="The role to register as (mentor or mentee)",
            required=True,
            choices=[{"name": r.title(), "value": r.lower()} for r in MENTORSHIP_ROLES]
        )
    ):
        """Register as a mentor or mentee"""
        role = role.lower()
        if role not in [r.lower() for r in MENTORSHIP_ROLES]:
            roles = ", ".join(MENTORSHIP_ROLES)
            await interaction.response.send_message(f"❌ Invalid role. Available roles: {roles}", ephemeral=True)
            return

        # Create or get the role
        role_name = role.title()
        guild_role = nextcord.utils.get(interaction.guild.roles, name=role_name)
        if not guild_role:
            try:
                guild_role = await interaction.guild.create_role(
                    name=role_name,
                    color=nextcord.Color.blue() if role == "mentor" else nextcord.Color.green(),
                    reason="Mentorship role creation"
                )
            except Exception as e:
                logger.error(f"Error creating role: {str(e)}")
                await interaction.response.send_message("❌ Failed to create role. Please check my permissions.", ephemeral=True)
                return

        # Add role to user
        try:
            await interaction.user.add_roles(guild_role)
            embed = nextcord.Embed(
                title="Role Added",
                description=f"You are now registered as a {role_name}!",
                color=guild_role.color
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error(f"Error adding role: {str(e)}")
            await interaction.response.send_message("❌ Failed to add role. Please check my permissions.", ephemeral=True)

    @mentor.subcommand(name="list", description="List available mentors")
    async def mentor_list(
        self,
        interaction: nextcord.Interaction,
        category: Optional[str] = nextcord.SlashOption(
            name="category",
            description="Filter mentors by category",
            required=False,
            choices=[{"name": cat.title(), "value": cat} for cat in MENTORSHIP_CATEGORIES]
        )
    ):
        """List available mentors"""
        if category and category not in MENTORSHIP_CATEGORIES:
            categories = ", ".join(MENTORSHIP_CATEGORIES)
            await interaction.response.send_message(f"❌ Invalid category. Available categories: {categories}", ephemeral=True)
            return

        mentors = await self.mentorship_service.find_mentors(category if category else None)
        
        if not mentors:
            await interaction.response.send_message("No mentors found." + (f" for category: {category}" if category else ""), ephemeral=True)
            return

        embed = nextcord.Embed(
            title=f"Available Mentors{f' - {category}' if category else ''}",
            color=nextcord.Color.blue()
        )

        for mentor in mentors:
            user = self.bot.get_user(int(mentor['discord_id']))
            if user:
                embed.add_field(
                    name=user.display_name,
                    value=f"""
                    Completed Mentorships: {mentor['completed_mentorships']}
                    Points: {mentor['points']}
                    """,
                    inline=False
                )

        await interaction.response.send_message(embed=embed)

    @mentor.subcommand(name="request", description="Request mentorship from a mentor")
    async def mentor_request(
        self,
        interaction: nextcord.Interaction,
        mentor_member: nextcord.Member = nextcord.SlashOption(
            name="mentor",
            description="The mentor you want to request mentorship from",
            required=True
        ),
        category: str = nextcord.SlashOption(
            name="category",
            description="The category of mentorship you are requesting",
            required=True,
            choices=[{"name": cat.title(), "value": cat} for cat in MENTORSHIP_CATEGORIES]
        )
    ):
        """Request mentorship from a mentor"""
        if category not in MENTORSHIP_CATEGORIES:
            categories = ", ".join(MENTORSHIP_CATEGORIES)
            await interaction.response.send_message(f"❌ Invalid category. Available categories: {categories}", ephemeral=True)
            return

        mentor_role = nextcord.utils.get(interaction.guild.roles, name="Mentor")
        if not mentor_role or mentor_role not in mentor_member.roles:
            await interaction.response.send_message("❌ This user is not registered as a mentor.", ephemeral=True)
            return

        try:
            mentorship = await self.mentorship_service.create_mentorship_request(
                str(mentor_member.id),
                str(interaction.user.id),
                category
            )

            embed = nextcord.Embed(
                title="Mentorship Request Sent",
                description=f"Request sent to {mentor_member.mention} for {category} mentorship!",
                color=nextcord.Color.blue()
            )
            await interaction.response.send_message(embed=embed)

            # Notify mentor
            mentor_embed = nextcord.Embed(
                title="New Mentorship Request",
                description=f"{interaction.user.mention} has requested your mentorship in {category}!",
                color=nextcord.Color.blue()
            )
            mentor_embed.add_field(
                name="How to Accept",
                value=f"Use `/mentor accept mentee:{interaction.user.display_name}` to accept this request.",
                inline=False
            )
            await mentor_member.send(embed=mentor_embed)

        except ValueError as e:
            await interaction.response.send_message(f"❌ {str(e)}", ephemeral=True)
        except Exception as e:
            logger.error(f"Error creating mentorship request: {str(e)}")
            await interaction.response.send_message("❌ An error occurred while creating the mentorship request.", ephemeral=True)

    @mentor.subcommand(name="accept", description="Accept a mentorship request")
    async def mentor_accept(
        self,
        interaction: nextcord.Interaction,
        mentee_member: nextcord.Member = nextcord.SlashOption(
            name="mentee",
            description="The mentee whose request you want to accept",
            required=True
        )
    ):
        """Accept a mentorship request"""
        try:
            # Find pending mentorship
            mentorships = await self.mentorship_service.get_user_mentorships(str(interaction.user.id))
            pending_mentorship = next(
                (m for m in mentorships if m['mentee_id'] == str(mentee_member.id) and m['status'] == "pending"),
                None
            )

            if not pending_mentorship:
                await interaction.response.send_message("❌ No pending mentorship request found from this user.", ephemeral=True)
                return

            mentorship = await self.mentorship_service.accept_mentorship(
                str(pending_mentorship['_id']),
                str(interaction.user.id)
            )

            embed = nextcord.Embed(
                title="Mentorship Started",
                description=f"Mentorship between {interaction.user.mention} and {mentee_member.mention} has begun!",
                color=nextcord.Color.green()
            )
            embed.add_field(name="Category", value=mentorship['category'])
            await interaction.response.send_message(embed=embed)

            # Notify mentee
            mentee_embed = nextcord.Embed(
                title="Mentorship Request Accepted",
                description=f"{interaction.user.mention} has accepted your mentorship request!",
                color=nextcord.Color.green()
            )
            await mentee_member.send(embed=mentee_embed)

        except ValueError as e:
            await interaction.response.send_message(f"❌ {str(e)}", ephemeral=True)
        except Exception as e:
            logger.error(f"Error accepting mentorship: {str(e)}")
            await interaction.response.send_message("❌ An error occurred while accepting the mentorship.", ephemeral=True)

    @mentor.subcommand(name="complete", description="Complete a mentorship")
    async def mentor_complete(
        self,
        interaction: nextcord.Interaction,
        mentee_member: nextcord.Member = nextcord.SlashOption(
            name="mentee",
            description="The mentee with whom you completed the mentorship",
            required=True
        )
    ):
        """Complete a mentorship"""
        try:
            # Find active mentorship
            mentorships = await self.mentorship_service.get_user_mentorships(str(interaction.user.id))
            active_mentorship = next(
                (m for m in mentorships if m['mentee_id'] == str(mentee_member.id) and m['status'] == "active"),
                None
            )

            if not active_mentorship:
                await interaction.response.send_message("❌ No active mentorship found with this user.", ephemeral=True)
                return

            mentorship = await self.mentorship_service.complete_mentorship(
                str(active_mentorship['_id']),
                str(interaction.user.id)
            )

            embed = nextcord.Embed(
                title="Mentorship Completed",
                description=f"Mentorship between {interaction.user.mention} and {mentee_member.mention} has been completed!",
                color=nextcord.Color.gold()
            )
            embed.add_field(name="Category", value=mentorship['category'])
            embed.add_field(name="Points Earned", value=str(POINTS_CONFIG['mentor_session']))
            await interaction.response.send_message(embed=embed)

            # Notify mentee
            mentee_embed = nextcord.Embed(
                title="Mentorship Completed",
                description=f"Your mentorship with {interaction.user.mention} has been completed!",
                color=nextcord.Color.gold()
            )
            mentee_embed.add_field(name="Points Earned", value=str(POINTS_CONFIG['mentor_session']))
            await mentee_member.send(embed=mentee_embed)

        except ValueError as e:
            await interaction.response.send_message(f"❌ {str(e)}", ephemeral=True)
        except Exception as e:
            logger.error(f"Error completing mentorship: {str(e)}")
            await interaction.response.send_message("❌ An error occurred while completing the mentorship.", ephemeral=True)

    @mentor.subcommand(name="stats", description="View mentorship statistics")
    async def mentor_stats(self, interaction: nextcord.Interaction):
        """View mentorship statistics"""
        try:
            user_stats = await self.mentorship_service.get_user_stats(str(interaction.user.id))
            overall_stats = await self.mentorship_service.get_mentorship_stats()

            embed = nextcord.Embed(
                title="Mentorship Statistics",
                color=nextcord.Color.blue()
            )

            # User stats
            embed.add_field(
                name="Your Stats as Mentor",
                value=f"""
                Total: {user_stats['as_mentor']['total']}
                Active: {user_stats['as_mentor']['active']}
                Completed: {user_stats['as_mentor']['completed']}
                """,
                inline=True
            )

            embed.add_field(
                name="Your Stats as Mentee",
                value=f"""
                Total: {user_stats['as_mentee']['total']}
                Active: {user_stats['as_mentee']['active']}
                Completed: {user_stats['as_mentee']['completed']}
                """,
                inline=True
            )

            # Overall stats
            embed.add_field(
                name="Overall Platform Stats",
                value=f"""
                Total Mentorships: {overall_stats['total_mentorships']}
                Active Mentorships: {overall_stats['active_mentorships']}
                Completed Mentorships: {overall_stats['completed_mentorships']}
                """,
                inline=False
            )

            # Category distribution
            category_stats = ""
            for category, count in overall_stats['category_distribution'].items():
                category_stats += f"{category}: {count}\n"
            embed.add_field(name="Category Distribution", value=category_stats, inline=False)

            await interaction.response.send_message(embed=embed)

        except Exception as e:
            logger.error(f"Error getting mentorship stats: {str(e)}")
            await interaction.response.send_message("❌ An error occurred while fetching mentorship statistics.", ephemeral=True)

def setup(bot):
    """Setup the Mentorship cog"""
    if bot is not None:
        bot.add_cog(Mentorship(bot))
        logging.getLogger('VEKA').info("Mentorship cog loaded successfully")
    else:
        logging.getLogger('VEKA').error("Bot is None in Mentorship cog setup")
