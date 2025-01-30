import discord
from discord import app_commands
from discord.ext import commands
from utils.database import Database
from utils.logger import setup_logger
from typing import Optional
import traceback

logger = setup_logger()

class CoreCommands(commands.Cog):
    """Core bot commands"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = Database.db

    @commands.hybrid_command(
        name="ping",
        description="Check bot latency",
        with_app_command=True,
        fallback="both"
    )
    @commands.guild_only()
    async def ping(self, ctx):
        try:
            latency = round(self.bot.latency * 1000)
            embed = discord.Embed(
                title="🏓 Pong!",
                description=f"Bot Latency: `{latency}ms`",
                color=discord.Color.green()
            )
            logger.info(f"Ping command executed - Latency: {latency}ms")
            await ctx.send(embed=embed)
        except Exception as e:
            error_msg = f"Error in ping command: {str(e)}\n{traceback.format_exc()}"
            logger.error(error_msg)
            await ctx.send(f"❌ An error occurred while checking latency: `{str(e)}`")

    @commands.hybrid_command(name="info", description="View bot information")
    async def info(self, ctx):
        try:
            embed = discord.Embed(
                title="VEKA Bot",
                description="A versatile Discord bot for server management and analytics",
                color=discord.Color.blue()
            )
            
            if self.bot.user.avatar:
                embed.set_thumbnail(url=self.bot.user.avatar.url)
            
            embed.add_field(
                name="📊 Statistics",
                value=f"```py\nServers: {len(self.bot.guilds)}\n"
                      f"Users: {sum(g.member_count for g in self.bot.guilds)}\n"
                      f"Latency: {round(self.bot.latency * 1000)}ms\n```",
                inline=False
            )
            
            embed.add_field(
                name="🔧 System",
                value="```py\nPython: 3.10+\n"
                      "Discord.py: 2.3.2\n"
                      "Database: MongoDB```",
                inline=False
            )
            
            embed.add_field(
                name="🔗 Links",
                value="[Support Server](https://discord.gg/vekabot) | "
                      "[Documentation](https://docs.vekabot.com) | "
                      "[GitHub](https://github.com/vekabot)",
                inline=False
            )
            
            embed.set_footer(text="Use 'v help' or /help for commands")
            await ctx.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in info command: {str(e)}")
            await ctx.send("An error occurred while fetching bot information.")

    @commands.hybrid_command(name="help", description="View all bot commands")
    async def help(self, ctx, category: str = None):
        try:
            if category is None:
                embed = discord.Embed(
                    title="VEKA Bot Commands",
                    description="Here are all available commands. Use `v help <category>` for detailed information.",
                    color=discord.Color.blue()
                )

                command_groups = {
                    "🎮 Activity": {
                        "description": "Activity tracking and stats",
                        "commands": ["activity", "activitystats", "voice"]
                    },
                    "📊 Analytics": {
                        "description": "Server and user analytics",
                        "commands": ["analytics", "leaderboard", "stats"]
                    },
                    "🛠️ Core": {
                        "description": "Essential bot commands",
                        "commands": ["help", "info", "ping", "invite"]
                    },
                    "ℹ️ Information": {
                        "description": "Server and user information",
                        "commands": ["botinfo", "serverinfo", "userinfo", "avatar", "banner", 
                                   "servericon", "serverbanner", "roles", "userroles"]
                    },
                    "🎯 Leveling": {
                        "description": "XP and leveling system",
                        "commands": ["rank", "levels", "rewards"]
                    },
                    "⚙️ Settings": {
                        "description": "Server configuration",
                        "commands": ["welcome", "autorole", "prefix"]
                    },
                    "🔧 Utility": {
                        "description": "Useful utility commands",
                        "commands": ["afk", "poll", "nick"]
                    }
                }

                for category_name, data in command_groups.items():
                    commands_text = ", ".join(f"`{cmd}`" for cmd in data["commands"])
                    embed.add_field(
                        name=f"{category_name} - {data['description']}",
                        value=commands_text,
                        inline=False
                    )

                embed.set_footer(text="Use 'v help <category>' for detailed information about a category")
            else:
                # Category-specific help logic here
                pass

            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in help command: {str(e)}")
            await ctx.send("An error occurred while fetching help information.")

    @help.error
    async def help_error(self, ctx, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"Please wait {error.retry_after:.2f}s before using this command again.")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        # Check for prefix
        prefixes = ['v', 'v ']
        content = message.content.lower()
        
        if not any(content.startswith(prefix) for prefix in prefixes):
            return

        # Process the command
        ctx = await self.bot.get_context(message)
        if ctx.command is not None:
            await self.bot.invoke(ctx)

async def setup(bot: commands.Bot):
    await bot.add_cog(CoreCommands(bot)) 