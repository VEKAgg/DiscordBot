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

    @commands.group(name="mentor", invoke_without_command=True)
    async def mentor(self, ctx):
        """Mentorship commands"""
        if ctx.invoked_subcommand is None:
            embed = nextcord.Embed(
                title="Mentorship Commands",
                description="Connect with mentors and mentees!",
                color=nextcord.Color.blue()
            )
            embed.add_field(
                name="Available Commands",
                value="""
                `!mentor register <role>` - Register as a mentor or mentee
                `!mentor list [category]` - List available mentors
                `!mentor request @mentor <category>` - Request mentorship
                `!mentor accept @mentee` - Accept a mentorship request
                `!mentor complete @mentee` - Complete a mentorship
                `!mentor stats` - View mentorship statistics
                """,
                inline=False
            )
            await ctx.send(embed=embed)

    @mentor.command(name="register")
    async def mentor_register(self, ctx, role: str):
        """Register as a mentor or mentee"""
        role = role.lower()
        if role not in [r.lower() for r in MENTORSHIP_ROLES]:
            roles = ", ".join(MENTORSHIP_ROLES)
            await ctx.send(f"❌ Invalid role. Available roles: {roles}")
            return

        # Create or get the role
        role_name = role.title()
        guild_role = nextcord.utils.get(ctx.guild.roles, name=role_name)
        if not guild_role:
            try:
                guild_role = await ctx.guild.create_role(
                    name=role_name,
                    color=nextcord.Color.blue() if role == "mentor" else nextcord.Color.green(),
                    reason="Mentorship role creation"
                )
            except Exception as e:
                logger.error(f"Error creating role: {str(e)}")
                await ctx.send("❌ Failed to create role. Please check my permissions.")
                return

        # Add role to user
        try:
            await ctx.author.add_roles(guild_role)
            embed = nextcord.Embed(
                title="Role Added",
                description=f"You are now registered as a {role_name}!",
                color=guild_role.color
            )
            await ctx.send(embed=embed)
        except Exception as e:
            logger.error(f"Error adding role: {str(e)}")
            await ctx.send("❌ Failed to add role. Please check my permissions.")

    @mentor.command(name="list")
    async def mentor_list(self, ctx, category: Optional[str] = None):
        """List available mentors"""
        if category and category not in MENTORSHIP_CATEGORIES:
            categories = ", ".join(MENTORSHIP_CATEGORIES)
            await ctx.send(f"❌ Invalid category. Available categories: {categories}")
            return

        mentors = await self.mentorship_service.find_mentors(category if category else None)
        
        if not mentors:
            await ctx.send("No mentors found." + (f" for category: {category}" if category else ""))
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

        await ctx.send(embed=embed)

    @mentor.command(name="request")
    async def mentor_request(self, ctx, mentor: nextcord.Member, category: str):
        """Request mentorship from a mentor"""
        if category not in MENTORSHIP_CATEGORIES:
            categories = ", ".join(MENTORSHIP_CATEGORIES)
            await ctx.send(f"❌ Invalid category. Available categories: {categories}")
            return

        mentor_role = nextcord.utils.get(ctx.guild.roles, name="Mentor")
        if not mentor_role or mentor_role not in mentor.roles:
            await ctx.send("❌ This user is not registered as a mentor.")
            return

        try:
            mentorship = await self.mentorship_service.create_mentorship_request(
                str(mentor.id),
                str(ctx.author.id),
                category
            )

            embed = nextcord.Embed(
                title="Mentorship Request Sent",
                description=f"Request sent to {mentor.mention} for {category} mentorship!",
                color=nextcord.Color.blue()
            )
            await ctx.send(embed=embed)

            # Notify mentor
            mentor_embed = nextcord.Embed(
                title="New Mentorship Request",
                description=f"{ctx.author.mention} has requested your mentorship in {category}!",
                color=nextcord.Color.blue()
            )
            mentor_embed.add_field(
                name="How to Accept",
                value=f"Use `!mentor accept @{ctx.author.display_name}` to accept this request.",
                inline=False
            )
            await mentor.send(embed=mentor_embed)

        except ValueError as e:
            await ctx.send(f"❌ {str(e)}")
        except Exception as e:
            logger.error(f"Error creating mentorship request: {str(e)}")
            await ctx.send("❌ An error occurred while creating the mentorship request.")

    @mentor.command(name="accept")
    async def mentor_accept(self, ctx, mentee: nextcord.Member):
        """Accept a mentorship request"""
        try:
            # Find pending mentorship
            mentorships = await self.mentorship_service.get_user_mentorships(str(ctx.author.id))
            pending_mentorship = next(
                (m for m in mentorships if m['mentee_id'] == str(mentee.id) and m['status'] == "pending"),
                None
            )

            if not pending_mentorship:
                await ctx.send("❌ No pending mentorship request found from this user.")
                return

            mentorship = await self.mentorship_service.accept_mentorship(
                str(pending_mentorship['_id']),
                str(ctx.author.id)
            )

            embed = nextcord.Embed(
                title="Mentorship Started",
                description=f"Mentorship between {ctx.author.mention} and {mentee.mention} has begun!",
                color=nextcord.Color.green()
            )
            embed.add_field(name="Category", value=mentorship['category'])
            await ctx.send(embed=embed)

            # Notify mentee
            mentee_embed = nextcord.Embed(
                title="Mentorship Request Accepted",
                description=f"{ctx.author.mention} has accepted your mentorship request!",
                color=nextcord.Color.green()
            )
            await mentee.send(embed=mentee_embed)

        except ValueError as e:
            await ctx.send(f"❌ {str(e)}")
        except Exception as e:
            logger.error(f"Error accepting mentorship: {str(e)}")
            await ctx.send("❌ An error occurred while accepting the mentorship.")

    @mentor.command(name="complete")
    async def mentor_complete(self, ctx, mentee: nextcord.Member):
        """Complete a mentorship"""
        try:
            # Find active mentorship
            mentorships = await self.mentorship_service.get_user_mentorships(str(ctx.author.id))
            active_mentorship = next(
                (m for m in mentorships if m['mentee_id'] == str(mentee.id) and m['status'] == "active"),
                None
            )

            if not active_mentorship:
                await ctx.send("❌ No active mentorship found with this user.")
                return

            mentorship = await self.mentorship_service.complete_mentorship(
                str(active_mentorship['_id']),
                str(ctx.author.id)
            )

            embed = nextcord.Embed(
                title="Mentorship Completed",
                description=f"Mentorship between {ctx.author.mention} and {mentee.mention} has been completed!",
                color=nextcord.Color.gold()
            )
            embed.add_field(name="Category", value=mentorship['category'])
            embed.add_field(name="Points Earned", value=str(POINTS_CONFIG['mentor_session']))
            await ctx.send(embed=embed)

            # Notify mentee
            mentee_embed = nextcord.Embed(
                title="Mentorship Completed",
                description=f"Your mentorship with {ctx.author.mention} has been completed!",
                color=nextcord.Color.gold()
            )
            mentee_embed.add_field(name="Points Earned", value=str(POINTS_CONFIG['mentor_session']))
            await mentee.send(embed=mentee_embed)

        except ValueError as e:
            await ctx.send(f"❌ {str(e)}")
        except Exception as e:
            logger.error(f"Error completing mentorship: {str(e)}")
            await ctx.send("❌ An error occurred while completing the mentorship.")

    @mentor.command(name="stats")
    async def mentor_stats(self, ctx):
        """View mentorship statistics"""
        try:
            user_stats = await self.mentorship_service.get_user_stats(str(ctx.author.id))
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

            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"Error getting mentorship stats: {str(e)}")
            await ctx.send("❌ An error occurred while fetching mentorship statistics.")

async def setup(bot):
    """Setup the Mentorship cog"""
    if bot is not None:
        await bot.add_cog(Mentorship(bot))
        logging.getLogger('VEKA').info("Mentorship cog loaded successfully")
    else:
        logging.getLogger('VEKA').error("Bot is None in Mentorship cog setup")
