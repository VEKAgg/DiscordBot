import discord
from discord import app_commands
from discord.ext import commands
from utils.database import Database
from utils.logger import setup_logger
from typing import Optional

logger = setup_logger()

class CoreCommands(commands.Cog):
    """Core bot commands"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = Database.db

    @commands.hybrid_command(name="ping", description="Check bot latency")
    @commands.guild_only()
    async def ping(self, ctx):
        try:
            embed = discord.Embed(
                title="🏓 Pong!",
                description=f"Bot Latency: `{round(self.bot.latency * 1000)}ms`",
                color=discord.Color.green()
            )
            await ctx.send(embed=embed)
        except Exception as e:
            logger.error(f"Error in ping command: {str(e)}")
            await ctx.send("An error occurred while checking latency.")

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

    @commands.hybrid_command(name="help", description="View all commands")
    @commands.guild_only()
    async def help(self, ctx):
        try:
            embed = discord.Embed(
                title="📚 VEKA Bot Commands",
                description="Here are all available commands:",
                color=discord.Color.blue()
            )
            
            # Core Commands
            embed.add_field(
                name="🛠️ Core",
                value="• `v ping` - Check bot latency\n• `v help` - Show this message",
                inline=False
            )
            
            # Analytics Commands
            embed.add_field(
                name="📊 Analytics",
                value="• `/analytics` - View server analytics",
                inline=False
            )
            
            # System Commands
            embed.add_field(
                name="⚙️ System",
                value="• `/status` - Check system health\n• `/debug` - Run diagnostics",
                inline=False
            )
            
            await ctx.send(embed=embed)
        except Exception as e:
            logger.error(f"Error in help command: {str(e)}")
            await ctx.send("An error occurred while showing help.")

async def setup(bot: commands.Bot):
    await bot.add_cog(CoreCommands(bot)) 