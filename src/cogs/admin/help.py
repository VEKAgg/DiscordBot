import logging

import nextcord
from nextcord.ext import commands

from src.utils.embeds import info_embed
from src.utils.safety import safe_send, safe_slash_command

logger = logging.getLogger('VEKA.admin.help')


class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _build_help_embed(self, command: str | None = None) -> nextcord.Embed:
        if command is None:
            embed = info_embed(
                title='🌟 VEKA Bot Help',
                description='Here are all the available command categories. Use `/help command:<command>` for detailed information about a specific command.',
                contributor_source=__name__,
                include_repo_link=True,
            )

            networking = """
            `/profile setup` - Create your professional profile
            `/profile edit` - Edit your profile
            `/profile view [member]` - View a profile
            `/connect request @member [message]` - Send a connection request
            `/connect accept @member` - Accept a connection
            `/connect decline @member` - Decline a connection
            `/connect list` - View your connections
            """
            embed.add_field(name='🤝 Professional Networking', value=networking.strip(), inline=False)

            marketplace = """
            `/marketplace post` - Create a new listing
            `/marketplace browse [category]` - Browse active listings
            `/marketplace view <id>` - View listing details
            `/marketplace mylistings` - View your listings
            `/marketplace withdraw <id>` - Withdraw a listing
            `/search <query>` - Advanced search with filters
            `/watch <id>` - Add listing to watchlist
            `/unwatch <id>` - Remove from watchlist
            `/watchlist` - View your watchlist
            `/offer <id> <price> [message]` - Make an offer
            `/myoffers` - View your offers
            `/featured` - View featured listings
            `/marketstats` - Marketplace statistics
            `/review <id> <rating> [comment]` - Leave a review
            `/seller [member]` - View seller profile
            `/reviews` - View your reviews
            `/bump <listing_id>` - Bump listing to top
            """
            embed.add_field(name='🏪 Marketplace', value=marketplace.strip(), inline=False)

            resources = """
            `/resource sources` - List available feed categories
            `/resource latest <category>` - Show latest entries from a category
            """
            embed.add_field(name='📰 RSS / Resources', value=resources.strip(), inline=False)

            mentorship = """
            `/mentor register <role>` - Register as mentor or mentee
            `/mentor list [category]` - List available mentors
            `/mentor request @mentor <category>` - Request mentorship
            `/mentor accept @mentee` - Accept a mentorship request
            `/mentor complete @mentee` - Complete a mentorship
            `/mentor stats` - View mentorship statistics
            """
            embed.add_field(name='🎓 Mentorship', value=mentorship.strip(), inline=False)

            portfolio = """
            `/portfolio add` - Add a new project
            `/portfolio list [@user]` - List projects
            `/portfolio view <id>` - View project details
            `/portfolio delete <id>` - Delete your project
            `/portfolio search <query>` - Search projects
            """
            embed.add_field(name='💼 Portfolio', value=portfolio.strip(), inline=False)

            fun = """
            `/roll [NdN]` - Roll dice (default 1d6)
            `/flip` - Coin flip
            `/8ball <question>` - Magic 8-ball
            `/rps <choice>` - Rock, Paper, Scissors
            `/choose <a>, <b>, ...` - Random choice from list
            """
            embed.add_field(name='🎲 Fun', value=fun.strip(), inline=False)

            utility = """
            `/help [command]` - Show this help message
            `/ping` - Check bot's response time
            `/health` - Show bot health status
            `/botinfo` - Show bot info
            """
            embed.add_field(name='🔧 Utility', value=utility.strip(), inline=False)

        else:
            command = command.lower().strip('!')
            cmd = self.bot.get_command(command)

            if cmd is None:
                embed = info_embed(
                    title='Help: Command Not Found',
                    description=f'Command `{command}` not found. Use `/help` to see all available commands.',
                    contributor_source=__name__,
                )
                return embed

            embed = info_embed(
                title=f'📖 Help: {cmd.name}',
                description=cmd.help or 'No description available.',
                contributor_source=__name__,
                include_repo_link=True,
            )

            if cmd.aliases:
                embed.add_field(name='Aliases', value=', '.join(cmd.aliases), inline=False)

            usage = f'!{cmd.name}'
            if cmd.signature:
                usage += f' {cmd.signature}'
            embed.add_field(name='Usage', value=f'`{usage}`', inline=False)

            examples = {
                'ping': "`!ping` - Check the bot's response time",
                'help': '`!help` - Show the help command overview\n`!help ping` - Show usage for ping',
                'profile': '`!profile` - View your professional profile\n`!setupprofile` - Set up your profile',
                'connect': '`!connect @user` - Send a connection request',
                'marketplace': '`!marketplace post` - Create a new listing\n`!marketplace browse` - Browse active listings',
                'review': '`!review 123 5 Great seller` - Leave a marketplace review',
            }

            if cmd.name in examples:
                embed.add_field(name='Examples', value=examples[cmd.name], inline=False)

        return embed

    @commands.command(name='help')
    async def help(self, ctx, command: str = None):
        """Shows help about commands and categories"""
        embed = self._build_help_embed(command)
        try:
            await ctx.send(embed=embed)
        except Exception as e:
            logger.error(f'Error in help command: {str(e)}')
            await ctx.send('An error occurred while showing the help message. Please try again later.')

    @nextcord.slash_command(name='help', description='Shows help about commands and categories')
    @safe_slash_command()
    async def help_slash(self, interaction: nextcord.Interaction, command: str = None):
        """Shows help about commands and categories"""
        embed = self._build_help_embed(command)
        await safe_send(interaction, embed=embed, ephemeral=True)


def setup(bot):
    """Setup the Help cog"""
    if bot is not None:
        bot.add_cog(Help(bot))
        logging.getLogger('VEKA').info('Help cog loaded successfully')
    else:
        logging.getLogger('VEKA').error('Bot is None in Help cog setup')
