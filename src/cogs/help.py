import nextcord
from nextcord.ext import commands
import logging

logger = logging.getLogger('VEKA.help')

class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="help")
    async def help(self, ctx, command: str = None):
        """Shows help about commands and categories"""
        if command is None:
            embed = nextcord.Embed(
                title="VEKA Bot Help",
                description="Here are all the available command categories. Use `!help <command>` for detailed information about a specific command.",
                color=nextcord.Color.blue()
            )

            # Moderation Commands
            moderation = """
            `!kick @user [reason]` - Kick a member
            `!ban @user [reason]` - Ban a member
            `!unban user_id` - Unban a member
            `!mute @user [duration] [reason]` - Mute a member
            `!unmute @user` - Unmute a member
            `!clear amount` - Clear messages
            """
            embed.add_field(name="🛡️ Moderation", value=moderation.strip(), inline=False)

            # Fun Commands
            fun = """
            `!roll [NdN]` - Roll dice (default: 1d6)
            `!flip` - Flip a coin
            `!8ball question` - Ask the magic 8-ball
            `!rps choice` - Play Rock, Paper, Scissors
            `!choose option1, option2, ...` - Choose between options
            """
            embed.add_field(name="🎮 Fun", value=fun.strip(), inline=False)

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

            embed = nextcord.Embed(
                title=f"Help: {cmd.name}",
                description=cmd.help or "No description available.",
                color=nextcord.Color.blue()
            )

            if cmd.aliases:
                embed.add_field(name="Aliases", value=", ".join(cmd.aliases), inline=False)

            usage = f"!{cmd.name}"
            if cmd.signature:
                usage += f" {cmd.signature}"
            embed.add_field(name="Usage", value=f"`{usage}`", inline=False)

            # Add examples for specific commands
            examples = {
                "roll": "`!roll` - Roll one six-sided die\n`!roll 3d6` - Roll three six-sided dice\n`!roll 1d20` - Roll one twenty-sided die",
                "8ball": "`!8ball Will I have a good day?` - Ask the magic 8-ball a question",
                "rps": "`!rps rock` - Play rock\n`!rps paper` - Play paper\n`!rps scissors` - Play scissors",
                "choose": "`!choose pizza, burger, salad` - Choose between food options\n`!choose work, break` - Make a decision",
                "mute": "`!mute @user 1h` - Mute for 1 hour\n`!mute @user 30m Bad behavior` - Mute for 30 minutes with reason",
                "clear": "`!clear 10` - Delete last 10 messages\n`!clear 50` - Delete last 50 messages"
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
