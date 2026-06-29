import logging

import nextcord
from nextcord.ext import commands

from src.config.config import MENTORSHIP_CATEGORIES, MENTORSHIP_ROLES, POINTS_CONFIG
from src.services.mentorship_service import MentorshipService
from src.utils.embeds import error_embed, info_embed, success_embed
from src.utils.safety import safe_send, safe_slash_command

logger = logging.getLogger('VEKA.mentorship')


class Mentorship(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.mentorship_service = MentorshipService(bot)

    # ==================== SLASH COMMANDS ====================

    @nextcord.slash_command(name='mentor', description='Mentorship commands')
    async def mentor(self, interaction: nextcord.Interaction):
        pass

    @mentor.subcommand(name='register', description='Register as a mentor or mentee')
    @safe_slash_command()
    async def mentor_register_slash(
        self,
        interaction: nextcord.Interaction,
        role: str = nextcord.SlashOption(
            name='role', description='Your role', choices={r.title(): r for r in MENTORSHIP_ROLES}
        ),
    ):
        role = role.lower()
        if role not in [r.lower() for r in MENTORSHIP_ROLES]:
            roles = ', '.join(MENTORSHIP_ROLES)
            embed = await error_embed(
                'Invalid Role', f'Available roles: {roles}', user=interaction.user, contributor_source=__name__
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        role_name = role.title()
        guild_role = nextcord.utils.get(interaction.guild.roles, name=role_name)
        if not guild_role:
            try:
                guild_role = await interaction.guild.create_role(
                    name=role_name,
                    color=nextcord.Color.blue() if role == 'mentor' else nextcord.Color.green(),
                    reason='Mentorship role creation',
                )
            except Exception as e:
                logger.error(f'Error creating role: {str(e)}')
                embed = await error_embed(
                    'Role Error',
                    'Failed to create role. Please check my permissions.',
                    user=interaction.user,
                    contributor_source=__name__,
                )
                await safe_send(interaction, embed=embed, ephemeral=True)
                return

        try:
            await interaction.user.add_roles(guild_role)
            embed = await success_embed(
                title='Role Added',
                description=f'You are now registered as a {role_name}!',
                user=interaction.user,
                contributor_source=__name__,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
        except Exception as e:
            logger.error(f'Error adding role: {str(e)}')
            embed = await error_embed(
                'Role Error',
                'Failed to add role. Please check my permissions.',
                user=interaction.user,
                contributor_source=__name__,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)

    @mentor.subcommand(name='list', description='List available mentors')
    @safe_slash_command()
    async def mentor_list_slash(
        self,
        interaction: nextcord.Interaction,
        category: str = nextcord.SlashOption(
            name='category',
            description='Filter by category',
            required=False,
            choices={c.replace('_', ' ').title(): c for c in MENTORSHIP_CATEGORIES},
        ),
    ):
        if category and category not in MENTORSHIP_CATEGORIES:
            categories = ', '.join(MENTORSHIP_CATEGORIES)
            embed = await error_embed(
                'Invalid Category',
                f'Available categories: {categories}',
                user=interaction.user,
                contributor_source=__name__,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        mentors = await self.mentorship_service.find_mentors(category or '')

        if not mentors:
            embed = await info_embed(
                title='No Mentors Found',
                description='No mentors found.' + (f' for category: {category}' if category else ''),
                user=interaction.user,
                contributor_source=__name__,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        embed = await info_embed(
            title=f'Available Mentors{f" - {category}" if category else ""}',
            description='Here are the available mentors:',
            user=interaction.user,
            contributor_source=__name__,
        )

        for mentor in mentors:
            user = self.bot.get_user(int(mentor['discord_id']))
            if user:
                embed.add_field(
                    name=user.display_name,
                    value=f'Completed: {mentor["completed_mentorships"]} | Points: {mentor["points"]}',
                    inline=False,
                )

        await safe_send(interaction, embed=embed, ephemeral=True)

    @mentor.subcommand(name='request', description='Request mentorship from a mentor')
    @safe_slash_command()
    async def mentor_request_slash(
        self,
        interaction: nextcord.Interaction,
        mentor: nextcord.Member,
        category: str = nextcord.SlashOption(
            name='category',
            description='Mentorship category',
            choices={c.replace('_', ' ').title(): c for c in MENTORSHIP_CATEGORIES},
        ),
    ):
        if category not in MENTORSHIP_CATEGORIES:
            categories = ', '.join(MENTORSHIP_CATEGORIES)
            embed = await error_embed(
                'Invalid Category',
                f'Available categories: {categories}',
                user=interaction.user,
                contributor_source=__name__,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        mentor_role = nextcord.utils.get(interaction.guild.roles, name='Mentor')
        if not mentor_role or mentor_role not in mentor.roles:
            embed = await error_embed(
                'Not a Mentor',
                'This user is not registered as a mentor.',
                user=interaction.user,
                contributor_source=__name__,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        try:
            await self.mentorship_service.create_mentorship_request(str(mentor.id), str(interaction.user.id), category)

            embed = await success_embed(
                title='Mentorship Request Sent',
                description=f'Request sent to {mentor.mention} for {category} mentorship!',
                user=interaction.user,
                contributor_source=__name__,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)

            mentor_embed = await info_embed(
                title='New Mentorship Request',
                description=f'{interaction.user.mention} has requested your mentorship in {category}!',
                user=interaction.user,
                contributor_source=__name__,
            )
            mentor_embed.add_field(
                name='How to Accept',
                value=f'Use `/mentor accept mentee:{interaction.user.mention}` to accept this request.',
                inline=False,
            )
            try:
                await mentor.send(embed=mentor_embed)
            except nextcord.Forbidden:
                pass

        except ValueError as e:
            embed = await error_embed('Request Failed', str(e), user=interaction.user, contributor_source=__name__)
            await safe_send(interaction, embed=embed, ephemeral=True)
        except Exception as e:
            logger.error(f'Error creating mentorship request: {str(e)}')
            embed = await error_embed(
                'Request Failed',
                'An error occurred while creating the mentorship request.',
                user=interaction.user,
                contributor_source=__name__,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)

    @mentor.subcommand(name='accept', description='Accept a mentorship request')
    @safe_slash_command()
    async def mentor_accept_slash(self, interaction: nextcord.Interaction, mentee: nextcord.Member):
        try:
            mentorships = await self.mentorship_service.get_user_mentorships(str(interaction.user.id))
            pending_mentorship = next(
                (m for m in mentorships if m['mentee_id'] == str(mentee.id) and m['status'] == 'pending'), None
            )

            if not pending_mentorship:
                embed = await error_embed(
                    'No Pending Request',
                    'No pending mentorship request found from this user.',
                    user=interaction.user,
                    contributor_source=__name__,
                )
                await safe_send(interaction, embed=embed, ephemeral=True)
                return

            mentorship = await self.mentorship_service.accept_mentorship(
                pending_mentorship['id'], str(interaction.user.id)
            )

            embed = await success_embed(
                title='Mentorship Started',
                description=f'Mentorship between {interaction.user.mention} and {mentee.mention} has begun!',
                user=interaction.user,
                contributor_source=__name__,
            )
            embed.add_field(name='Category', value=mentorship['category'])
            await safe_send(interaction, embed=embed, ephemeral=True)

            mentee_embed = await success_embed(
                title='Mentorship Request Accepted',
                description=f'{interaction.user.mention} has accepted your mentorship request!',
                user=interaction.user,
                contributor_source=__name__,
            )
            try:
                await mentee.send(embed=mentee_embed)
            except nextcord.Forbidden:
                pass

        except ValueError as e:
            embed = await error_embed('Accept Failed', str(e), user=interaction.user, contributor_source=__name__)
            await safe_send(interaction, embed=embed, ephemeral=True)
        except Exception as e:
            logger.error(f'Error accepting mentorship: {str(e)}')
            embed = await error_embed(
                'Accept Failed',
                'An error occurred while accepting the mentorship.',
                user=interaction.user,
                contributor_source=__name__,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)

    @mentor.subcommand(name='complete', description='Complete a mentorship')
    @safe_slash_command()
    async def mentor_complete_slash(self, interaction: nextcord.Interaction, mentee: nextcord.Member):
        try:
            mentorships = await self.mentorship_service.get_user_mentorships(str(interaction.user.id))
            active_mentorship = next(
                (m for m in mentorships if m['mentee_id'] == str(mentee.id) and m['status'] == 'active'), None
            )

            if not active_mentorship:
                embed = await error_embed(
                    'No Active Mentorship',
                    'No active mentorship found with this user.',
                    user=interaction.user,
                    contributor_source=__name__,
                )
                await safe_send(interaction, embed=embed, ephemeral=True)
                return

            mentorship = await self.mentorship_service.complete_mentorship(
                active_mentorship['id'], str(interaction.user.id)
            )

            embed = await success_embed(
                title='Mentorship Completed',
                description=f'Mentorship between {interaction.user.mention} and {mentee.mention} has been completed!',
                user=interaction.user,
                contributor_source=__name__,
            )
            embed.add_field(name='Category', value=mentorship['category'])
            embed.add_field(name='Points Earned', value=str(POINTS_CONFIG['mentor_session']))
            await safe_send(interaction, embed=embed, ephemeral=True)

            mentee_embed = await success_embed(
                title='Mentorship Completed',
                description=f'Your mentorship with {interaction.user.mention} has been completed!',
                user=interaction.user,
                contributor_source=__name__,
            )
            mentee_embed.add_field(name='Points Earned', value=str(POINTS_CONFIG['mentee_completion']))
            try:
                await mentee.send(embed=mentee_embed)
            except nextcord.Forbidden:
                pass

        except ValueError as e:
            embed = await error_embed('Complete Failed', str(e), user=interaction.user, contributor_source=__name__)
            await safe_send(interaction, embed=embed, ephemeral=True)
        except Exception as e:
            logger.error(f'Error completing mentorship: {str(e)}')
            embed = await error_embed(
                'Complete Failed',
                'An error occurred while completing the mentorship.',
                user=interaction.user,
                contributor_source=__name__,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)

    @mentor.subcommand(name='stats', description='View mentorship statistics')
    @safe_slash_command()
    async def mentor_stats_slash(self, interaction: nextcord.Interaction):
        try:
            user_stats = await self.mentorship_service.get_user_stats(str(interaction.user.id))
            overall_stats = await self.mentorship_service.get_mentorship_stats()

            embed = await info_embed(title='Mentorship Statistics', user=interaction.user, contributor_source=__name__)

            embed.add_field(
                name='Your Stats as Mentor',
                value=f'Total: {user_stats["as_mentor"]["total"]}\nActive: {user_stats["as_mentor"]["active"]}\nCompleted: {user_stats["as_mentor"]["completed"]}',
                inline=True,
            )

            embed.add_field(
                name='Your Stats as Mentee',
                value=f'Total: {user_stats["as_mentee"]["total"]}\nActive: {user_stats["as_mentee"]["active"]}\nCompleted: {user_stats["as_mentee"]["completed"]}',
                inline=True,
            )

            embed.add_field(
                name='Overall Platform Stats',
                value=f'Total: {overall_stats["total_mentorships"]}\nActive: {overall_stats["active_mentorships"]}\nCompleted: {overall_stats["completed_mentorships"]}',
                inline=False,
            )

            category_stats = ''
            for category, count in overall_stats['category_distribution'].items():
                category_stats += f'{category}: {count}\n'
            if category_stats:
                embed.add_field(name='Category Distribution', value=category_stats, inline=False)

            await safe_send(interaction, embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f'Error getting mentorship stats: {str(e)}')
            embed = await error_embed(
                'Stats Error',
                'An error occurred while fetching mentorship statistics.',
                user=interaction.user,
                contributor_source=__name__,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)

    # ==================== PREFIX COMMANDS ====================

    @commands.group(name='mentor', invoke_without_command=True)
    async def mentor_prefix(self, ctx):
        """Mentorship commands"""
        embed = await info_embed(
            title='Mentorship Commands',
            description='Connect with mentors and mentees! Use `/mentor` for the best experience.',
            user=ctx.author,
            contributor_source=__name__,
        )
        embed.add_field(
            name='Available Commands',
            value=(
                '`!mentor register <role>` - Register as a mentor or mentee\n'
                '`!mentor list [category]` - List available mentors\n'
                '`!mentor request @mentor <category>` - Request mentorship\n'
                '`!mentor accept @mentee` - Accept a mentorship request\n'
                '`!mentor complete @mentee` - Complete a mentorship\n'
                '`!mentor stats` - View mentorship statistics'
            ),
            inline=False,
        )
        await ctx.send(embed=embed)

    @mentor_prefix.command(name='register')
    async def mentor_register_prefix(self, ctx, role: str):
        """Register as a mentor or mentee"""
        role = role.lower()
        if role not in [r.lower() for r in MENTORSHIP_ROLES]:
            roles = ', '.join(MENTORSHIP_ROLES)
            await ctx.send(f'❌ Invalid role. Available roles: {roles}')
            return

        role_name = role.title()
        guild_role = nextcord.utils.get(ctx.guild.roles, name=role_name)
        if not guild_role:
            try:
                guild_role = await ctx.guild.create_role(
                    name=role_name,
                    color=nextcord.Color.blue() if role == 'mentor' else nextcord.Color.green(),
                    reason='Mentorship role creation',
                )
            except Exception as e:
                logger.error(f'Error creating role: {str(e)}')
                await ctx.send('❌ Failed to create role. Please check my permissions.')
                return

        try:
            await ctx.author.add_roles(guild_role)
            embed = nextcord.Embed(
                title='Role Added', description=f'You are now registered as a {role_name}!', color=guild_role.color
            )
            await ctx.send(embed=embed)
        except Exception as e:
            logger.error(f'Error adding role: {str(e)}')
            await ctx.send('❌ Failed to add role. Please check my permissions.')

    @mentor_prefix.command(name='list')
    async def mentor_list_prefix(self, ctx, category: str | None = None):
        """List available mentors"""
        if category and category not in MENTORSHIP_CATEGORIES:
            categories = ', '.join(MENTORSHIP_CATEGORIES)
            await ctx.send(f'❌ Invalid category. Available categories: {categories}')
            return

        mentors = await self.mentorship_service.find_mentors(category or '')

        if not mentors:
            await ctx.send('No mentors found.' + (f' for category: {category}' if category else ''))
            return

        embed = nextcord.Embed(
            title=f'Available Mentors{f" - {category}" if category else ""}', color=nextcord.Color.blue()
        )

        for mentor in mentors:
            user = self.bot.get_user(int(mentor['discord_id']))
            if user:
                embed.add_field(
                    name=user.display_name,
                    value=f'Completed: {mentor["completed_mentorships"]} | Points: {mentor["points"]}',
                    inline=False,
                )

        await ctx.send(embed=embed)

    @mentor_prefix.command(name='request')
    async def mentor_request_prefix(self, ctx, mentor: nextcord.Member, category: str):
        """Request mentorship from a mentor"""
        if category not in MENTORSHIP_CATEGORIES:
            categories = ', '.join(MENTORSHIP_CATEGORIES)
            await ctx.send(f'❌ Invalid category. Available categories: {categories}')
            return

        mentor_role = nextcord.utils.get(ctx.guild.roles, name='Mentor')
        if not mentor_role or mentor_role not in mentor.roles:
            await ctx.send('❌ This user is not registered as a mentor.')
            return

        try:
            await self.mentorship_service.create_mentorship_request(str(mentor.id), str(ctx.author.id), category)

            embed = nextcord.Embed(
                title='Mentorship Request Sent',
                description=f'Request sent to {mentor.mention} for {category} mentorship!',
                color=nextcord.Color.blue(),
            )
            await ctx.send(embed=embed)

            mentor_embed = nextcord.Embed(
                title='New Mentorship Request',
                description=f'{ctx.author.mention} has requested your mentorship in {category}!',
                color=nextcord.Color.blue(),
            )
            mentor_embed.add_field(
                name='How to Accept',
                value=f'Use `!mentor accept @{ctx.author.display_name}` to accept this request.',
                inline=False,
            )
            await mentor.send(embed=mentor_embed)

        except ValueError as e:
            await ctx.send(f'❌ {str(e)}')
        except Exception as e:
            logger.error(f'Error creating mentorship request: {str(e)}')
            await ctx.send('❌ An error occurred while creating the mentorship request.')

    @mentor_prefix.command(name='accept')
    async def mentor_accept_prefix(self, ctx, mentee: nextcord.Member):
        """Accept a mentorship request"""
        try:
            mentorships = await self.mentorship_service.get_user_mentorships(str(ctx.author.id))
            pending_mentorship = next(
                (m for m in mentorships if m['mentee_id'] == str(mentee.id) and m['status'] == 'pending'), None
            )

            if not pending_mentorship:
                await ctx.send('❌ No pending mentorship request found from this user.')
                return

            mentorship = await self.mentorship_service.accept_mentorship(pending_mentorship['id'], str(ctx.author.id))

            embed = nextcord.Embed(
                title='Mentorship Started',
                description=f'Mentorship between {ctx.author.mention} and {mentee.mention} has begun!',
                color=nextcord.Color.green(),
            )
            embed.add_field(name='Category', value=mentorship['category'])
            await ctx.send(embed=embed)

            mentee_embed = nextcord.Embed(
                title='Mentorship Request Accepted',
                description=f'{ctx.author.mention} has accepted your mentorship request!',
                color=nextcord.Color.green(),
            )
            await mentee.send(embed=mentee_embed)

        except ValueError as e:
            await ctx.send(f'❌ {str(e)}')
        except Exception as e:
            logger.error(f'Error accepting mentorship: {str(e)}')
            await ctx.send('❌ An error occurred while accepting the mentorship.')

    @mentor_prefix.command(name='complete')
    async def mentor_complete_prefix(self, ctx, mentee: nextcord.Member):
        """Complete a mentorship"""
        try:
            mentorships = await self.mentorship_service.get_user_mentorships(str(ctx.author.id))
            active_mentorship = next(
                (m for m in mentorships if m['mentee_id'] == str(mentee.id) and m['status'] == 'active'), None
            )

            if not active_mentorship:
                await ctx.send('❌ No active mentorship found with this user.')
                return

            mentorship = await self.mentorship_service.complete_mentorship(active_mentorship['id'], str(ctx.author.id))

            embed = nextcord.Embed(
                title='Mentorship Completed',
                description=f'Mentorship between {ctx.author.mention} and {mentee.mention} has been completed!',
                color=nextcord.Color.gold(),
            )
            embed.add_field(name='Category', value=mentorship['category'])
            embed.add_field(name='Points Earned', value=str(POINTS_CONFIG['mentor_session']))
            await ctx.send(embed=embed)

            mentee_embed = nextcord.Embed(
                title='Mentorship Completed',
                description=f'Your mentorship with {ctx.author.mention} has been completed!',
                color=nextcord.Color.gold(),
            )
            mentee_embed.add_field(name='Points Earned', value=str(POINTS_CONFIG['mentee_completion']))
            await mentee.send(embed=mentee_embed)

        except ValueError as e:
            await ctx.send(f'❌ {str(e)}')
        except Exception as e:
            logger.error(f'Error completing mentorship: {str(e)}')
            await ctx.send('❌ An error occurred while completing the mentorship.')

    @mentor_prefix.command(name='stats')
    async def mentor_stats_prefix(self, ctx):
        """View mentorship statistics"""
        try:
            user_stats = await self.mentorship_service.get_user_stats(str(ctx.author.id))
            overall_stats = await self.mentorship_service.get_mentorship_stats()

            embed = nextcord.Embed(title='Mentorship Statistics', color=nextcord.Color.blue())

            embed.add_field(
                name='Your Stats as Mentor',
                value=f'Total: {user_stats["as_mentor"]["total"]}\nActive: {user_stats["as_mentor"]["active"]}\nCompleted: {user_stats["as_mentor"]["completed"]}',
                inline=True,
            )

            embed.add_field(
                name='Your Stats as Mentee',
                value=f'Total: {user_stats["as_mentee"]["total"]}\nActive: {user_stats["as_mentee"]["active"]}\nCompleted: {user_stats["as_mentee"]["completed"]}',
                inline=True,
            )

            embed.add_field(
                name='Overall Platform Stats',
                value=f'Total: {overall_stats["total_mentorships"]}\nActive: {overall_stats["active_mentorships"]}\nCompleted: {overall_stats["completed_mentorships"]}',
                inline=False,
            )

            category_stats = ''
            for category, count in overall_stats['category_distribution'].items():
                category_stats += f'{category}: {count}\n'
            if category_stats:
                embed.add_field(name='Category Distribution', value=category_stats, inline=False)

            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f'Error getting mentorship stats: {str(e)}')
            await ctx.send('❌ An error occurred while fetching mentorship statistics.')


def setup(bot):
    """Setup the Mentorship cog"""
    if bot is not None:
        bot.add_cog(Mentorship(bot))
        logging.getLogger('VEKA').info('Loaded cog: src.cogs.mentorship')
    else:
        logging.getLogger('VEKA').error('Bot is None in Mentorship cog setup')
