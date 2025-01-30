import discord
from discord.ext import commands
from utils.database import Database
from utils.logger import setup_logger
import traceback

logger = setup_logger()

class CoreEvents(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = Database.db

    @commands.Cog.listener()
    async def on_ready(self):
        """Set up bot presence and status when ready"""
        activity = discord.Activity(
            type=discord.ActivityType.watching,
            name="v help | VEKA Bot"
        )
        await self.bot.change_presence(activity=activity, status=discord.Status.online)
        logger.info("Bot presence updated")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Handle message events and bot mentions"""
        if message.author.bot:
            return

        # Respond to bot mentions without a command
        if self.bot.user in message.mentions and len(message.content.split()) == 1:
            embed = discord.Embed(
                title="👋 Hello!",
                description=(
                    f"Hi {message.author.mention}! I'm VEKA Bot.\n\n"
                    "• Use `v help` for a list of commands\n"
                    "• All commands work with `v`, `/` or by mentioning me\n"
                    "• For support, join our [Support Server](https://discord.gg/vekabot)"
                ),
                color=discord.Color.blue()
            )
            await message.channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        """Handle bot joining a new server"""
        logger.info(f"Joined new guild: {guild.name} (ID: {guild.id})")
        
        # Log new guild in database
        await self.db.guild_logs.insert_one({
            "guild_id": guild.id,
            "guild_name": guild.name,
            "joined_at": discord.utils.utcnow(),
            "member_count": guild.member_count
        })

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        """Global error handler for prefix commands"""
        if isinstance(error, commands.CommandNotFound):
            await ctx.send(f"Command not found. Use `v help` to see available commands.")
            return
        
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(f"You don't have the required permissions to use this command.")
            return
        
        if isinstance(error, commands.NoPrivateMessage):
            await ctx.send("This command can only be used in servers.")
            return
        
        # Log detailed error information
        error_details = f"""
        Command: {ctx.command}
        Author: {ctx.author} (ID: {ctx.author.id})
        Guild: {ctx.guild.name if ctx.guild else 'DM'} (ID: {ctx.guild.id if ctx.guild else 'N/A'})
        Error: {str(error)}
        Traceback: {traceback.format_exc()}
        """
        logger.error(error_details)
        
        await ctx.send("An error occurred while executing the command. The error has been logged.")

async def setup(bot: commands.Bot):
    await bot.add_cog(CoreEvents(bot)) 