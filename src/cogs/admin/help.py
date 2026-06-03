import nextcord
from nextcord.ext import commands
import logging

from src.utils.embeds import info_embed

logger = logging.getLogger('VEKA.admin.help')

class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="help")
    async def help(self, ctx, command: str = None):
        """Shows help about commands and categories"""
        if command is None:
            embed = info_embed(
                title="🌟 VEKA Bot Help",
                description="Here are all the available command categories. Use `!help <command>` for detailed information about a specific command.",
                contributor_source=__name__,
                include_repo_link=True,
            )

            # Professional Networking
            networking = """
            `!profile [@user]` - View your or someone else's profile
            `!setupprofile` - Set up your professional profile
            `!connect @user [message]` - Send a connection request
            `!connections` - View your connections
            """
            embed.add_field(name="🤝 Professional Networking", value=networking.strip(), inline=False)

            # Marketplace Commands
            marketplace = """
            `!marketplace post` - Create a new listing
            `!marketplace browse [category]` - Browse active listings
            `!marketplace view <id>` - View listing details
            `!review <transaction_id> <rating> [comment]` - Leave a review
            """
            embed.add_field(name="🏪 Marketplace", value=marketplace.strip(), inline=False)

            # RSS & Resources
            resources = """
            `!feed list` - List available RSS feed categories
            `!feed show <category>` - Show latest entries from a category
            `!feed search <query>` - Search across feeds
            """
            embed.add_field(name="📰 RSS / Resources", value=resources.strip(), inline=False)

            # Professional Networking
            networking = """
            `!profile [@user]` - View your or someone else's profile
            `!setupprofile` - Set up your professional profile
            `!connect @user [message]` - Send a connection request
            """
            embed.add_field(name="🤝 Professional Networking", value=networking.strip(), inline=False)

            # Utility Commands
            utility = """
            `!help [command]` - Show this help message
            `!ping` - Check bot's response time
            """
            embed.add_field(name="🔧 Utility", value=utility.strip(), inline=False)

            embed.set_footer(text="Type !help <command> for more details about a specific command.")

        else:
            # Remove the prefix if user included it
            command = command.lower().strip('!')
            cmd = self.bot.get_command(command)

            if cmd is None:
                await ctx.send(f"❌ Command `{command}` not found. Use `!help` to see all available commands.")
                return

            embed = info_embed(
                title=f"📖 Help: {cmd.name}",
                description=cmd.help or "No description available.",
                contributor_source=__name__,
                include_repo_link=True,
            )

            if cmd.aliases:
                embed.add_field(name="Aliases", value=", ".join(cmd.aliases), inline=False)

            usage = f"!{cmd.name}"
            if cmd.signature:
                usage += f" {cmd.signature}"
            embed.add_field(name="Usage", value=f"`{usage}`", inline=False)

            # Add examples for specific commands
            examples = {
                "ping": "`!ping` - Check the bot's response time",
                "help": "`!help` - Show the help command overview\n`!help ping` - Show usage for ping",
                "profile": "`!profile` - View your professional profile\n`!setupprofile` - Set up your profile interactively",
                "connect": "`!connect @user` - Send a connection request",
                "marketplace": "`!marketplace post` - Create a new listing\n`!marketplace browse` - Browse active listings",
                "review": "`!review 123 5 Great seller` - Leave a marketplace review",
                "feed": "`!feed list` - List RSS categories\n`!feed show tech_news` - Show the latest tech news feeds",
            }
            
            if cmd.name in examples:
                embed.add_field(name="Examples", value=examples[cmd.name], inline=False)

        try:
            await ctx.send(embed=embed)
        except Exception as e:
            logger.error(f"Error in help command: {str(e)}")
            await ctx.send("An error occurred while showing the help message. Please try again later.")

def setup(bot):
    """Setup the Help cog"""
    if bot is not None:
        bot.add_cog(Help(bot))
        logging.getLogger('VEKA').info("Help cog loaded successfully")
    else:
        logging.getLogger('VEKA').error("Bot is None in Help cog setup")
