import nextcord
from nextcord.ext import commands
import logging
from src.services.networking_service import NetworkingService

logger = logging.getLogger('VEKA.networking')


class Networking(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.svc = NetworkingService()

    @commands.command(name='profile', description='View a professional profile')
    async def profile(self, ctx, member: nextcord.Member = None):
        target = member or ctx.author
        profile = await self.svc.get_profile(str(target.id))

        if not profile:
            msg = (
                'You haven\'t set up your profile yet! Use `!setupprofile` to create one.'
                if target == ctx.author
                else f'{target.display_name} hasn\'t set up their profile yet.'
            )
            embed = nextcord.Embed(title='Profile Not Found', description=msg,
                                   color=nextcord.Color.orange())
        else:
            embed = nextcord.Embed(
                title=f"{target.display_name}'s Professional Profile",
                color=nextcord.Color.blue()
            )
            embed.set_thumbnail(
                url=target.avatar.url if target.avatar else target.default_avatar.url
            )
            for field, label in [
                ('title', 'Title'), ('skills', 'Skills'),
                ('experience', 'Experience'), ('looking_for', 'Looking For'),
            ]:
                embed.add_field(name=label, value=profile.get(field, 'Not set'), inline=False)
            embed.set_footer(text=f"Profile last updated: {profile.get('last_updated', 'Never')}")

        await ctx.send(embed=embed)

    @commands.command(name='setupprofile', description='Set up your professional profile')
    async def setupprofile(self, ctx):
        try:
            def check(m):
                return m.author == ctx.author and m.channel == ctx.channel

            embed = nextcord.Embed(
                title='Professional Profile Setup',
                description=(
                    "Let's set up your professional profile! I'll ask you a few questions.\n"
                    "Type 'skip' to skip any question or 'cancel' to abort."
                ),
                color=nextcord.Color.blue()
            )
            await ctx.send(embed=embed)

            questions = [
                ("What is your professional title? (e.g., 'Software Engineer')", 'title'),
                ('What are your key skills? (comma-separated)', 'skills'),
                ('Briefly describe your experience:', 'experience'),
                ("What opportunities are you looking for?", 'looking_for'),
            ]

            profile_data = {}
            for question, field in questions:
                await ctx.send(question)
                try:
                    response = await self.bot.wait_for('message', check=check, timeout=300.0)
                    if response.content.lower() == 'cancel':
                        await ctx.send('Profile setup cancelled.')
                        return
                    if response.content.lower() != 'skip':
                        profile_data[field] = response.content
                except TimeoutError:
                    await ctx.send('Profile setup timed out. Please try again.')
                    return

            await self.svc.upsert_profile(str(ctx.author.id), profile_data)
            embed = nextcord.Embed(
                title='Profile Setup Complete!',
                description='Your profile has been saved. Use `!profile` to view it!',
                color=nextcord.Color.green()
            )
            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f'Error in setupprofile: {e}')
            await ctx.send('An error occurred while setting up your profile. Please try again later.')

    @commands.command(name='connect', description='Send a connection request to another member')
    async def connect(self, ctx, member: nextcord.Member, *, message: str = None):
        if member == ctx.author:
            await ctx.send("You can't connect with yourself!")
            return
        try:
            if await self.svc.connection_exists(str(ctx.author.id), str(member.id)):
                await ctx.send("You're already connected with this member!")
                return

            await self.svc.create_request(str(ctx.author.id), str(member.id), message or '')

            embed = nextcord.Embed(
                title='New Connection Request!',
                description=f'{ctx.author.mention} would like to connect with you!',
                color=nextcord.Color.blue()
            )
            if message:
                embed.add_field(name='Message', value=message)
            embed.add_field(
                name='How to respond',
                value='Use `!accept @user` to accept or `!decline @user` to decline',
                inline=False
            )
            try:
                await member.send(embed=embed)
            except nextcord.Forbidden:
                pass

            await ctx.send(f'Connection request sent to {member.mention}!')

        except Exception as e:
            logger.error(f'Error in connect: {e}')
            await ctx.send('An error occurred while sending the connection request. Please try again later.')

    @commands.command(name='accept', description='Accept a connection request')
    async def accept(self, ctx, member: nextcord.Member):
        try:
            request = await self.svc.get_pending_request(str(member.id), str(ctx.author.id))
            if not request:
                await ctx.send(f'No pending connection request from {member.mention}.')
                return

            await self.svc.update_request_status(request['_id'], 'accepted')
            await self.svc.create_connection(str(ctx.author.id), str(member.id))

            embed = nextcord.Embed(
                title='Connection Accepted!',
                description=f'You are now connected with {member.mention}!',
                color=nextcord.Color.green()
            )
            await ctx.send(embed=embed)

            try:
                notify = nextcord.Embed(
                    title='Connection Request Accepted!',
                    description=f'{ctx.author.mention} has accepted your connection request!',
                    color=nextcord.Color.green()
                )
                await member.send(embed=notify)
            except nextcord.Forbidden:
                pass

        except Exception as e:
            logger.error(f'Error in accept: {e}')
            await ctx.send('An error occurred while accepting the connection request.')

    @commands.command(name='decline', description='Decline a connection request')
    async def decline(self, ctx, member: nextcord.Member):
        try:
            request = await self.svc.get_pending_request(str(member.id), str(ctx.author.id))
            if not request:
                await ctx.send(f'No pending connection request from {member.mention}.')
                return

            await self.svc.update_request_status(request['_id'], 'declined')

            embed = nextcord.Embed(
                title='Connection Request Declined',
                description=f'You have declined the connection request from {member.mention}.',
                color=nextcord.Color.red()
            )
            await ctx.send(embed=embed)

            try:
                notify = nextcord.Embed(
                    title='Connection Request Declined',
                    description=f'{ctx.author.mention} has declined your connection request.',
                    color=nextcord.Color.red()
                )
                await member.send(embed=notify)
            except nextcord.Forbidden:
                pass

        except Exception as e:
            logger.error(f'Error in decline: {e}')
            await ctx.send('An error occurred while declining the connection request.')

    @commands.command(name='connections', description='View your connections')
    async def connections_cmd(self, ctx):
        try:
            user_connections = await self.svc.get_connections(str(ctx.author.id))
            if not user_connections:
                await ctx.send("You don't have any connections yet. Use `!connect @user` to connect with someone!")
                return

            embed = nextcord.Embed(
                title='Your Connections',
                description=f'You have {len(user_connections)} connection(s)',
                color=nextcord.Color.blue()
            )
            for conn in user_connections:
                other = ctx.guild.get_member(int(conn['other_discord_id']))
                if other:
                    embed.add_field(
                        name=other.display_name,
                        value=f"Connected since: {conn.get('connected_at', 'Unknown')}",
                        inline=False
                    )
            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f'Error in connections: {e}')
            await ctx.send('An error occurred while fetching your connections.')


def setup(bot):
    bot.add_cog(Networking(bot))
    logging.getLogger('VEKA').info('Networking cog loaded successfully')
