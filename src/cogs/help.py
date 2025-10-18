import nextcord
from nextcord.ext import commands
import logging

logger = logging.getLogger('VEKA.help')

class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @nextcord.slash_command(name="help", description="Shows help about commands and categories")
    async def help_slash(
        self,
        interaction: nextcord.Interaction,
        command: str = nextcord.SlashOption(
            name="command",
            description="The command to get help for",
            required=False
        )
    ):
        """Shows help about commands and categories"""
        if command is None:
            embed = nextcord.Embed(
                title="VEKA Bot Help",
                description="Here are all the available command categories. Use `/help <command>` for detailed information about a specific command.",
                color=nextcord.Color.blue()
            )

            # Moderation Commands
            moderation = """
            `/kick @user [reason]` - Kick a member
            `/ban @user [reason]` - Ban a member
            `/unban user_id` - Unban a member
            `/mute @user [duration] [reason]` - Mute a member
            `/unmute @user` - Unmute a member
            `/clear amount` - Clear messages
            """
            embed.add_field(name="🛡️ Moderation", value=moderation.strip(), inline=False)

            # Fun Commands
            fun = """
            `/roll [NdN]` - Roll dice (default: 1d6)
            `/flip` - Flip a coin
            `/8ball question` - Ask the magic 8-ball
            `/rps choice` - Play Rock, Paper, Scissors
            `/choose option1, option2, ...` - Choose between options
            """
            embed.add_field(name="🎮 Fun", value=fun.strip(), inline=False)

            # Professional Networking
            networking = """
            `/profile [@user]` - View your or someone else's profile
            `/setupprofile` - Set up your professional profile
            `/connect @user [message]` - Send a connection request
            """
            embed.add_field(name="🤝 Professional Networking", value=networking.strip(), inline=False)

            # Utility Commands
            utility = """
            `/help [command]` - Show this help message
            `/ping` - Check bot's response time
            """
            embed.add_field(name="🔧 Utility", value=utility.strip(), inline=False)

            embed.set_footer(text="Type /help <command> for more details about a specific command.")

        else:
            # Attempt to get a slash command
            cmd = self.bot.get_application_command(command)

            if cmd is None:
                await interaction.response.send_message(f"❌ Command `{command}` not found. Use `/help` to see all available commands.", ephemeral=True)
                return

            embed = nextcord.Embed(
                title=f"Help: {cmd.name}",
                description=cmd.description or "No description available.",
                color=nextcord.Color.blue()
            )

            # For slash commands, aliases are not directly applicable in the same way as prefix commands
            # We can list options instead of signature
            if cmd.options:
                options_str = []
                for option in cmd.options:
                    option_desc = f"`{option.name}`: {option.description}"
                    if option.required:
                        option_desc += " (Required)"
                    else:
                        option_desc += " (Optional)"
                    options_str.append(option_desc)
                embed.add_field(name="Options", value="\n".join(options_str), inline=False)

            # Add examples for specific commands (update to slash command examples)
            examples = {
                "roll": "`/roll` - Roll one six-sided die\n`/roll dice:3d6` - Roll three six-sided dice\n`/roll dice:1d20` - Roll one twenty-sided die",
                "8ball": "`/8ball question:Will I have a good day?` - Ask the magic 8-ball a question",
                "rps": "`/rps choice:rock` - Play rock\n`/rps choice:paper` - Play paper\n`/rps choice:scissors` - Play scissors",
                "choose": "`/choose options:pizza, burger, salad` - Choose between food options\n`/choose options:work, break` - Make a decision",
                "mute": "`/mute member:@user duration:1h` - Mute for 1 hour\n`/mute member:@user duration:30m reason:Bad behavior` - Mute for 30 minutes with reason",
                "clear": "`/clear amount:10` - Delete last 10 messages\n`/clear amount:50` - Delete last 50 messages"
            }
            
            if cmd.name in examples:
                embed.add_field(name="Examples", value=examples[cmd.name], inline=False)

        try:
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error(f"Error in help command: {str(e)}")
            await interaction.response.send_message("An error occurred while showing the help message. Please try again later.", ephemeral=True)

def setup(bot):
    """Setup the Help cog"""
    if bot is not None:
        bot.add_cog(Help(bot))
        logging.getLogger('VEKA').info("Help cog loaded successfully")
    else:
        logging.getLogger('VEKA').error("Bot is None in Help cog setup")
