import nextcord
from nextcord.ext import commands, tasks
from utils.database import Database
from utils.logger import setup_logger
from typing import Optional, Dict, Any, Literal
import traceback
import datetime
from datetime import datetime, timezone, timedelta
import psutil
import platform
import os
from dotenv import load_dotenv
import motor.motor_asyncio
import redis
import aioredis
import aiohttp
import requests
from bs4 import BeautifulSoup
import pandas as pd
from tabulate import tabulate
from deep_translator import GoogleTranslator
import pytz
from fuzzywuzzy import process
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import openai
from utils.web_scraper import WebScraper
from nextcord.ext import app_commands
from loguru import logger
from nextcord import Interaction, SlashOption
import logging

# Get logger for this module
logger = logging.getLogger('nextcord.core.commands')

class CoreCommands(commands.Cog):
    """Core bot commands and functionality"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot_app_info = None
        self.tree = bot.tree
        logger.info("Initializing CoreCommands cog")
        
        try:
            # Validate environment variables
            required_vars = {
                'MONGODB_URI': os.getenv('MONGODB_URI'),
                'REDIS_URI': os.getenv('REDIS_URI'),
                'OPENAI_API_KEY': os.getenv('OPENAI_API_KEY')
            }
            
            missing_vars = [key for key, value in required_vars.items() if not value]
            if missing_vars:
                raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
            
            # Initialize services
            self.db = motor.motor_asyncio.AsyncIOMotorClient(required_vars['MONGODB_URI']).veka
            self.redis = aioredis.from_url(required_vars['REDIS_URI'])
            self.web_scraper = None  # Will initialize after DB connection
            
            self.translator = GoogleTranslator(source='auto', target='en')
            self.start_time = datetime.now(timezone.utc)
            self.afk_users = {}
            self.command_groups = {
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
                    "commands": ["botinfo", "serverinfo", "userinfo", "avatar", "banner"]
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
            
            self.cache = {}
            self.cache_ttl = {
                "stats": 300,  # 5 minutes
                "guild": 600,  # 10 minutes
                "user": 300,   # 5 minutes
                "analytics": 900  # 15 minutes
            }

            # Initialize chat history
            self.chat_history = {}

        except Exception as e:
            logger.exception("Failed to initialize CoreCommands cog")
            raise

    async def cog_load(self):
        """Initialize tasks and services when cog is loaded"""
        try:
            # Initialize web scraper first
            self.web_scraper = WebScraper(self.db)
            logger.info("WebScraper initialized successfully")

            # Initialize scheduler
            self.scheduler = AsyncIOScheduler()
            
            # Wait for bot to be ready before scheduling tasks
            await self.bot.wait_until_ready()
            
            # Schedule background tasks
            self.scheduler.add_job(
                self.update_status_task,
                CronTrigger(minute="*/5"),  # Every 5 minutes
                id="status_updater",
                replace_existing=True
            )
            
            self.scheduler.add_job(
                self.cleanup_cache_task,
                CronTrigger(hour="*/1"),  # Every hour
                id="cache_cleanup",
                replace_existing=True
            )
            
            self.scheduler.add_job(
                self.backup_stats_task,
                CronTrigger(hour="0"),  # Daily at midnight
                id="stats_backup",
                replace_existing=True
            )
            
            # Start the scheduler
            self.scheduler.start()
            logger.info("Background tasks scheduler started")

            # Start price alerts task
            self.check_price_alerts.start()
            logger.info("Price alerts task started")

            # Get application info once during load
            self.bot_app_info = await self.bot.application_info()
            
            # Register app command error handler
            self.tree.on_error = self.on_app_command_error

        except Exception as e:
            logger.exception("Failed to initialize CoreCommands tasks")
            raise

    async def cog_unload(self):
        try:
            self.scheduler.shutdown()
            self.check_price_alerts.cancel()
            logger.info("CoreCommands cog unloaded successfully")
        except Exception as e:
            logger.exception("Error during cog unload")

    async def update_status_task(self):
        try:
            total_members = sum(guild.member_count for guild in self.bot.guilds)
            status_text = f"with {total_members:,} users | /help"
            
            activity = nextcord.Activity(
                type=nextcord.ActivityType.playing,
                name=status_text
            )
            await self.bot.change_presence(activity=activity)
            logger.debug("Bot status updated successfully")
            
        except Exception as e:
            logger.exception("Failed to update bot status")

    async def cleanup_cache_task(self):
        try:
            cleaned = 0
            async for key in self.redis.scan_iter("*"):
                if await self.redis.ttl(key) < 0:
                    await self.redis.delete(key)
                    cleaned += 1
            logger.debug(f"Cache cleanup completed: {cleaned} keys removed")
        except Exception as e:
            logger.exception("Failed to cleanup cache")

    async def backup_stats_task(self):
        """Backup daily statistics to database"""
        try:
            stats = {
                "date": datetime.now(timezone.utc),
                "total_guilds": len(self.bot.guilds),
                "total_members": sum(guild.member_count for guild in self.bot.guilds),
                "commands_used": await self.db.bot_stats.find_one({"_id": "global"}) or {},
                "system_stats": {
                    "cpu_usage": psutil.cpu_percent(),
                    "memory_usage": psutil.virtual_memory().percent
                }
            }
            
            # Store in database
            await self.db.daily_stats.insert_one(stats)
            logger.info("Daily statistics backup completed")
            
        except Exception as e:
            logger.error(f"Error in stats backup task: {str(e)}\n{traceback.format_exc()}")

    def get_uptime(self) -> str:
        """Calculate bot uptime"""
        delta = datetime.now(timezone.utc) - self.start_time
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        days, hours = divmod(hours, 24)
        return f"{days}d {hours}h {minutes}m {seconds}s"

    async def on_app_command_error(self, interaction: Interaction, error: Exception):
        if isinstance(error, app_commands.CommandOnCooldown):
            await interaction.response.send_message(
                f"This command is on cooldown. Try again in {error.retry_after:.2f}s",
                ephemeral=True
            )
        elif isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "You don't have permission to use this command.",
                ephemeral=True
            )
        else:
            logger.exception("Unhandled application command error", exc_info=error)
            await interaction.response.send_message(
                "An error occurred while executing this command.",
                ephemeral=True
            )

    @nextcord.slash_command(name="ping", description="Check bot latency")
    async def ping(self, interaction: Interaction):
        await interaction.response.send_message(
            f"🏓 Pong! Latency: {round(self.bot.latency * 1000)}ms"
        )

    @nextcord.slash_command(name="info", description="Get bot information")
    async def info(self, interaction: Interaction):
        embed = nextcord.Embed(
            title="VEKA Bot Info",
            color=nextcord.Color.blue()
        )
        embed.add_field(
            name="Version",
            value="1.0.0",
            inline=True
        )
        embed.add_field(
            name="Library",
            value=f"Nextcord {nextcord.__version__}",
            inline=True
        )
        await interaction.response.send_message(embed=embed)

    @nextcord.slash_command(name="translate", description="Translate text to another language")
    async def translate(self, 
                       interaction: nextcord.Interaction, 
                       text: str, 
                       target_lang: str = "en"):
        await interaction.response.defer()
        
        try:
            self.translator.target = target_lang
            translated = self.translator.translate(text)
            
            embed = nextcord.Embed(
                title="Translation",
                color=nextcord.Color.blue(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.add_field(name="Original", value=text, inline=False)
            embed.add_field(name=f"Translated ({target_lang})", value=translated, inline=False)
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in translate command: {str(e)}\n{traceback.format_exc()}")
            await interaction.followup.send("❌ An error occurred during translation.", ephemeral=True)

    async def get_cached_data(self, key: str, category: str) -> Optional[Dict[str, Any]]:
        """Get data from cache with TTL check"""
        cache_key = f"{category}:{key}"
        try:
            # Try Redis first
            data = await self.redis.get(cache_key)
            if data:
                return data

            # Fall back to memory cache
            if cache_key in self.cache:
                cached_time, cached_data = self.cache[cache_key]
                if datetime.now(timezone.utc) - cached_time < timedelta(seconds=self.cache_ttl[category]):
                    return cached_data
        except Exception as e:
            logger.error(f"Cache retrieval error: {str(e)}")
        return None

    async def set_cached_data(self, key: str, category: str, data: Dict[str, Any]) -> None:
        """Set data in cache with TTL"""
        cache_key = f"{category}:{key}"
        try:
            # Store in Redis
            await self.redis.set(cache_key, data, ex=self.cache_ttl[category])
            
            # Store in memory cache
            self.cache[cache_key] = (datetime.now(timezone.utc), data)
        except Exception as e:
            logger.error(f"Cache storage error: {str(e)}")

    @nextcord.slash_command(name="stats", description="View detailed statistics")
    async def stats(self, interaction: nextcord.Interaction, 
                   type: str = "overview",
                   timeframe: str = "day",
                   target: Optional[nextcord.Member] = None):
        await interaction.response.defer()
        
        try:
            # Check cache first
            cache_key = f"{interaction.guild_id}:{type}:{timeframe}:{target.id if target else 'global'}"
            cached_data = await self.get_cached_data(cache_key, "stats")
            
            if cached_data:
                await interaction.followup.send(embed=nextcord.Embed.from_dict(cached_data))
                return

            # Calculate time threshold
            thresholds = {
                "day": timedelta(days=1),
                "week": timedelta(days=7),
                "month": timedelta(days=30),
                "all": timedelta(days=365*10)  # Arbitrary large number
            }
            threshold = datetime.now(timezone.utc) - thresholds[timeframe]

            # Build query
            query = {
                "guild_id": interaction.guild_id,
                "timestamp": {"$gte": threshold}
            }
            
            if target:
                query["user_id"] = target.id

            # Get data based on type
            data = await self.get_stats_data(type, query)
            
            # Create embed
            embed = await self.create_stats_embed(type, timeframe, data, target)
            
            # Cache the result
            await self.set_cached_data(cache_key, "stats", embed.to_dict())
            
            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in stats command: {str(e)}\n{traceback.format_exc()}")
            await interaction.followup.send("❌ An error occurred while fetching statistics.", ephemeral=True)

    async def get_stats_data(self, type: str, query: Dict[str, Any]) -> Dict[str, Any]:
        """Get statistics data based on type"""
        if type == "overview":
            return {
                "messages": await self.db.messages.count_documents(query),
                "commands": await self.db.commands.count_documents(query),
                "voice_time": await self.db.voice_activity.aggregate([
                    {"$match": query},
                    {"$group": {"_id": None, "total": {"$sum": "$duration"}}}
                ]).next(),
                "members": len([m for m in self.bot.get_guild(query["guild_id"]).members 
                              if not m.bot])
            }
        # Add other type handlers as needed
        return {}

    async def create_stats_embed(self, type: str, timeframe: str, data: Dict[str, Any], 
                               target: Optional[nextcord.Member]) -> nextcord.Embed:
        """Create statistics embed"""
        embed = nextcord.Embed(
            title=f"{'Server' if not target else f'{target.display_name}'} Statistics",
            color=target.color if target else nextcord.Color.blue(),
            timestamp=datetime.now(timezone.utc)
        )
        
        if type == "overview":
            stats_table = tabulate([
                ["Messages", f"{data['messages']:,}"],
                ["Commands", f"{data['commands']:,}"],
                ["Voice Time", f"{data['voice_time']:,} minutes"],
                ["Members", f"{data['members']:,}"]
            ], tablefmt="plain")
            embed.add_field(name="📊 Overview", value=f"```\n{stats_table}\n```", inline=False)
        
        embed.set_footer(text=f"Timeframe: {timeframe.title()}")
        return embed

    @nextcord.slash_command(name="botinfo", description="View detailed bot information")
    async def botinfo(self, interaction: nextcord.Interaction):
        await interaction.response.defer()
        try:
            # Fetch stats from database
            stats = await self.db.bot_stats.find_one({"_id": "global"}) or {}
            
            embed = nextcord.Embed(
                title=f"{self.bot.user.name} Information",
                color=nextcord.Color.blue(),
                timestamp=datetime.now(timezone.utc)
            )
            
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
            
            # Bot Stats
            total_members = sum(guild.member_count for guild in self.bot.guilds)
            embed.add_field(name="Servers", value=f"```{len(self.bot.guilds):,}```", inline=True)
            embed.add_field(name="Users", value=f"```{total_members:,}```", inline=True)
            embed.add_field(name="Commands", value=f"```{len(self.bot.application_commands):,}```", inline=True)
            
            # System Stats
            cpu_usage = psutil.cpu_percent()
            memory = psutil.virtual_memory()
            embed.add_field(name="CPU Usage", value=f"```{cpu_usage}%```", inline=True)
            embed.add_field(name="Memory", value=f"```{memory.percent}%```", inline=True)
            embed.add_field(name="Uptime", value=f"```{self.get_uptime()}```", inline=True)
            
            # Version Info
            embed.add_field(name="Python", value=f"```{platform.python_version()}```", inline=True)
            embed.add_field(name="Nextcord", value=f"```{nextcord.__version__}```", inline=True)
            embed.add_field(name="Created", value=f"```{nextcord.utils.format_dt(self.bot.user.created_at, 'D')}```", inline=True)
            
            # Usage Stats
            if stats:
                embed.add_field(name="Commands Used", value=f"```{stats.get('commands_used', 0):,}```", inline=True)
                embed.add_field(name="Messages Seen", value=f"```{stats.get('messages_seen', 0):,}```", inline=True)
            
            await interaction.followup.send(embed=embed)
            
            logger.info(f"Botinfo command used by {interaction.user} in {interaction.guild}")
            
        except Exception as e:
            logger.exception("Error in botinfo command")
            await interaction.followup.send("An error occurred while fetching bot information.")

    @nextcord.slash_command(name="help", description="View all available commands")
    async def help(self, interaction: nextcord.Interaction, category: Optional[str] = None):
        await interaction.response.defer()
        
        try:
            if category is None:
                embed = nextcord.Embed(
                    title="VEKA Bot Commands",
                    description=(
                        "Here are all command categories. Use `/help <category>` for detailed information.\n"
                        "• For more info, join our [Support Server](https://discord.gg/vekabot)"
                    ),
                    color=nextcord.Color.blue(),
                    timestamp=datetime.now(timezone.utc)
                )

                for group_name, group_info in self.command_groups.items():
                    embed.add_field(
                        name=group_name,
                        value=f"{group_info['description']}\nCommands: `{', '.join(group_info['commands'])}`",
                        inline=False
                    )
            else:
                # Find matching category
                category_match = next(
                    (name for name in self.command_groups.keys() 
                     if name.lower().replace("️", "").strip().startswith(category.lower())),
                    None
                )

                if not category_match:
                    await interaction.followup.send("❌ Invalid category. Use `/help` to see all categories.", ephemeral=True)
                    return

                group_info = self.command_groups[category_match]
                embed = nextcord.Embed(
                    title=f"{category_match} Commands",
                    description=group_info['description'],
                    color=nextcord.Color.blue(),
                    timestamp=datetime.now(timezone.utc)
                )

                # Get detailed command info
                for cmd_name in group_info['commands']:
                    cmd = self.bot.get_application_command(cmd_name)
                    if cmd:
                        embed.add_field(
                            name=f"/{cmd_name}",
                            value=cmd.description or "No description available",
                            inline=False
                        )

            embed.set_footer(text=f"Use /help <category> for more details • {len(self.bot.application_commands)} total commands")
            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in help command: {str(e)}\n{traceback.format_exc()}")
            await interaction.followup.send(
                "❌ An error occurred while fetching help information.",
                ephemeral=True
            )

    @nextcord.slash_command(name="poll", description="Create a poll")
    @nextcord.slash_command(name="nick", description="Change your nickname")
    async def nick(self, interaction: nextcord.Interaction, nickname: str = None):
        await interaction.response.defer()
        
        try:
            if not nickname:
                await interaction.user.edit(nick=None)
                await interaction.followup.send("✅ Reset your nickname.")
                return

            if len(nickname) > 32:
                await interaction.followup.send("❌ Nickname must be 32 characters or less.")
                return

            await interaction.user.edit(nick=nickname)
            await interaction.followup.send(f"✅ Changed your nickname to: {nickname}")

        except nextcord.Forbidden:
            await interaction.followup.send("❌ I don't have permission to change your nickname.")
        except Exception as e:
            logger.error(f"Error in nick command: {str(e)}\n{traceback.format_exc()}")
            await interaction.followup.send("❌ Failed to change nickname.")

    @commands.hybrid_command(name="help", description="View all bot commands")
    async def help(self, ctx, category: str = None):
        try:
            if category is None:
                embed = nextcord.Embed(
                    title="VEKA Bot Commands",
                    description="Here are all available commands. Use `v help <category>` for detailed information.",
                    color=nextcord.Color.blue()
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
    async def on_message(self, message: nextcord.Message):
        if message.author.bot:
            return

        try:
            # Check if user was AFK
            afk_status = await self.db.afk_status.find_one({
                "guild_id": message.guild.id,
                "user_id": message.author.id
            })

            if afk_status:
                # Remove AFK status
                await self.db.afk_status.delete_one({
                    "guild_id": message.guild.id,
                    "user_id": message.author.id
                })

                # Remove [AFK] from nickname
                try:
                    if message.author.display_name.startswith("[AFK]"):
                        await message.author.edit(
                            nick=message.author.display_name[6:]
                        )
                except nextcord.Forbidden:
                    pass

                duration = datetime.now(timezone.utc) - afk_status["timestamp"]
                await message.channel.send(
                    f"Welcome back {message.author.mention}! You were AFK for {int(duration.total_seconds() / 60)} minutes."
                )

            # Check for mentions of AFK users
            for mention in message.mentions:
                afk_status = await self.db.afk_status.find_one({
                    "guild_id": message.guild.id,
                    "user_id": mention.id
                })

                if afk_status:
                    await message.reply(
                        f"{mention.display_name} is AFK: {afk_status['reason']} "
                        f"(<t:{int(afk_status['timestamp'].timestamp())}:R>)"
                    )

        except Exception as e:
            logger.error(f"Error handling AFK message: {str(e)}\n{traceback.format_exc()}")

    @nextcord.slash_command(name="serverinfo", description="View detailed server information")
    async def serverinfo(self, interaction: nextcord.Interaction):
        await interaction.response.defer()
        
        try:
            guild = interaction.guild
            
            # Try to get cached data first
            cache_key = f"serverinfo:{guild.id}"
            cached_data = await self.redis.get(cache_key)
            
            if cached_data:
                await interaction.followup.send(embed=nextcord.Embed.from_dict(cached_data))
                return
            
            # Create new embed if no cache
            embed = nextcord.Embed(
                title=f"{guild.name} Information",
                color=nextcord.Color.blue(),
                timestamp=datetime.now(timezone.utc)
            )
            
            if guild.icon:
                embed.set_thumbnail(url=guild.icon.url)
            
            # Basic Info
            embed.add_field(name="Owner", value=guild.owner.mention, inline=True)
            embed.add_field(name="Created", value=nextcord.utils.format_dt(guild.created_at, 'R'), inline=True)
            embed.add_field(name="Region", value=str(guild.preferred_locale), inline=True)
            
            # Member Stats
            member_stats = {
                "Total Members": len(guild.members),
                "Humans": len([m for m in guild.members if not m.bot]),
                "Bots": len([m for m in guild.members if m.bot])
            }
            
            stats_table = tabulate(
                [[k, v] for k, v in member_stats.items()],
                tablefmt="plain"
            )
            embed.add_field(name="📊 Member Statistics", value=f"```\n{stats_table}\n```", inline=False)
            
            # Cache the embed for 5 minutes
            await self.redis.set(cache_key, embed.to_dict(), ex=300)
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in serverinfo command: {str(e)}\n{traceback.format_exc()}")
            await interaction.followup.send("❌ An error occurred while fetching server information.", ephemeral=True)

    @nextcord.slash_command(name="tasks", description="View background tasks status")
    async def tasks(self, interaction: nextcord.Interaction):
        await interaction.response.defer()
        
        try:
            jobs = self.scheduler.get_jobs()
            
            embed = nextcord.Embed(
                title="Background Tasks Status",
                color=nextcord.Color.blue(),
                timestamp=datetime.now(timezone.utc)
            )
            
            for job in jobs:
                next_run = job.next_run_time.strftime("%Y-%m-%d %H:%M:%S UTC")
                embed.add_field(
                    name=f"📋 {job.id}",
                    value=f"Next Run: `{next_run}`\nStatus: `{'Running' if job.pending else 'Idle'}`",
                    inline=False
                )
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in tasks command: {str(e)}\n{traceback.format_exc()}")
            await interaction.followup.send("❌ An error occurred while fetching tasks status.", ephemeral=True)

    @nextcord.slash_command(name="ask", description="Ask the AI assistant a question")
    async def ask(self, interaction: nextcord.Interaction, question: str):
        await interaction.response.defer()
        
        try:
            if interaction.user.id not in self.chat_history:
                self.chat_history[interaction.user.id] = []
            
            self.chat_history[interaction.user.id].append({
                "role": "user",
                "content": question
            })
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "gpt-3.5-turbo",
                        "messages": self.chat_history[interaction.user.id][-5:],
                        "max_tokens": 500
                    }
                ) as response:
                    if response.status != 200:
                        await interaction.followup.send("❌ Failed to get AI response.", ephemeral=True)
                        return
                    
                    data = await response.json()
                    answer = data['choices'][0]['message']['content']
            
            self.chat_history[interaction.user.id].append({
                "role": "assistant",
                "content": answer
            })
            
            embed = nextcord.Embed(
                title="AI Assistant",
                description=answer,
                color=nextcord.Color.blue(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.set_footer(text=f"Asked by {interaction.user.name}")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in ask command: {str(e)}\n{traceback.format_exc()}")
            await interaction.followup.send("❌ An error occurred while processing your question.", ephemeral=True)

    @nextcord.slash_command(name="search", description="Search and summarize a webpage")
    async def search(
        self, 
        interaction: nextcord.Interaction, 
        url: str,
        extract_links: bool = False,
        extract_images: bool = False
    ):
        await interaction.response.defer()
        
        try:
            await interaction.followup.send("🔍 Analyzing webpage... This may take a moment.", ephemeral=True)
            
            result = await self.web_scraper.scrape_and_summarize(
                url, 
                extract_links=extract_links,
                extract_images=extract_images
            )
            
            if result.get("error"):
                await interaction.followup.send(f"❌ {result['error']}", ephemeral=True)
                return
                
            # Create main embed
            embed = nextcord.Embed(
                title=result["title"],
                url=result["url"],
                description=result["summary"],
                color=nextcord.Color.blue(),
                timestamp=datetime.now(timezone.utc)
            )
            
            # Add text statistics
            stats = result["text_stats"]
            stats_text = (
                f"Words: {stats['word_count']:,}\n"
                f"Characters: {stats['character_count']:,}\n"
                f"Paragraphs: {stats['paragraph_count']:,}\n"
                f"Headings: {stats['heading_count']:,}"
            )
            embed.add_field(name="📊 Text Statistics", value=f"```\n{stats_text}\n```", inline=False)
            
            # Add metadata if available
            if result["metadata"]:
                for name, value in result["metadata"].items():
                    embed.add_field(name=name, value=value, inline=True)
            
            # Add links if requested
            if extract_links and result.get("links"):
                links_text = "\n".join(
                    f"• [{link['text']}]({link['url']})" 
                    for link in result["links"][:5]
                )
                embed.add_field(name="🔗 Related Links", value=links_text or "No links found", inline=False)
            
            # Add images if requested
            if extract_images and result.get("images"):
                embed.set_image(url=result["images"][0]["url"])  # Set first image as embed image
                images_text = "\n".join(
                    f"• [{img.get('title') or img.get('alt') or 'Image'}]({img['url']})" 
                    for img in result["images"][1:3]  # Show 2 more image links
                )
                if images_text:
                    embed.add_field(name="🖼️ More Images", value=images_text, inline=False)
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in search command: {str(e)}\n{traceback.format_exc()}")
            await interaction.followup.send("❌ An error occurred while processing the webpage.", ephemeral=True)

    @nextcord.slash_command(name="track", description="Track price of a product")
    @app_commands.describe(
        url="Product URL to track",
        timeframe="Historical data timeframe"
    )
    @app_commands.choices(
        timeframe=[
            app_commands.Choice(name="24 Hours", value="day"),
            app_commands.Choice(name="7 Days", value="week"),
            app_commands.Choice(name="30 Days", value="month"),
            app_commands.Choice(name="All Time", value="all")
        ]
    )
    async def track(
        self,
        interaction: nextcord.Interaction,
        url: str,
        timeframe: str = "day"
    ):
        await interaction.response.defer()
        
        try:
            await interaction.followup.send("🔍 Tracking price... This may take a moment.", ephemeral=True)
            
            result = await self.web_scraper.track_price(url, interaction.user.id)
            
            if result.get("error"):
                await interaction.followup.send(f"❌ {result['error']}", ephemeral=True)
                return
                
            embed = nextcord.Embed(
                title=result["title"],
                url=result["url"],
                color=nextcord.Color.green() if result["stock_status"] == "In Stock" else nextcord.Color.red(),
                timestamp=result["timestamp"]
            )
            
            # Current price and status
            embed.add_field(
                name="💰 Current Price",
                value=f"₹{result['current_price']:,.2f}" if result['current_price'] else "Not available",
                inline=True
            )
            
            embed.add_field(
                name="📦 Stock Status",
                value=result["stock_status"],
                inline=True
            )
            
            # Price statistics if available
            if stats := result.get("price_stats"):
                stats_text = (
                    f"Lowest: ₹{stats['lowest']:,.2f}\n"
                    f"Average: ₹{stats['average']:,.2f}\n"
                    f"Highest: ₹{stats['highest']:,.2f}\n"
                    f"Times Tracked: {stats['total_tracked']}"
                )
                embed.add_field(
                    name="📊 Price Statistics",
                    value=f"```\n{stats_text}\n```",
                    inline=False
                )
            
            embed.set_footer(text=f"Tracked by {interaction.user.name}")
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in track command: {str(e)}\n{traceback.format_exc()}")
            await interaction.followup.send("❌ An error occurred while tracking the price.", ephemeral=True)

    @nextcord.slash_command(name="alert", description="Set a price alert for a product")
    @app_commands.describe(
        url="Product URL to track",
        target_price="Alert when price drops below this amount",
        channel="Channel to receive alert notifications (default: current channel)"
    )
    async def price_alert(
        self,
        interaction: nextcord.Interaction,
        url: str,
        target_price: float,
        channel: Optional[nextcord.TextChannel] = None
    ):
        await interaction.response.defer()
        
        try:
            alert_channel = channel or interaction.channel
            result = await self.web_scraper.set_price_alert(
                url, 
                interaction.user.id,
                target_price,
                alert_channel.id
            )
            
            if result.get("error"):
                await interaction.followup.send(f"❌ {result['error']}", ephemeral=True)
                return

            alert_data = result["data"]
            embed = nextcord.Embed(
                title="⏰ Price Alert Set",
                description=f"You will be notified in {alert_channel.mention} when the price drops below ₹{target_price:,.2f}",
                color=nextcord.Color.blue(),
                timestamp=datetime.now(timezone.utc)
            )
            
            embed.add_field(
                name="Product",
                value=alert_data["title"],
                inline=False
            )
            
            embed.add_field(
                name="Current Price",
                value=f"₹{alert_data['current_price']:,.2f}",
                inline=True
            )
            
            embed.add_field(
                name="Target Price",
                value=f"₹{target_price:,.2f}",
                inline=True
            )
            
            embed.add_field(
                name="Price Drop Needed",
                value=f"₹{(alert_data['current_price'] - target_price):,.2f}",
                inline=True
            )
            
            embed.set_footer(text=f"Alert set by {interaction.user.name}")
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in price alert command: {str(e)}\n{traceback.format_exc()}")
            await interaction.followup.send("❌ An error occurred while setting the price alert.", ephemeral=True)

    @tasks.loop(minutes=30)
    async def check_price_alerts(self):
        try:
            triggered_alerts = await self.web_scraper.check_price_alerts()
            
            for alert in triggered_alerts:
                channel = self.bot.get_channel(alert["alert"]["channel_id"])
                if not channel:
                    continue
                    
                user = self.bot.get_user(alert["alert"]["user_id"])
                if not user:
                    continue
                    
                embed = nextcord.Embed(
                    title="🎯 Price Alert Triggered!",
                    description=f"{user.mention}, your target price has been reached!",
                    color=nextcord.Color.green(),
                    timestamp=datetime.now(timezone.utc)
                )
                
                embed.add_field(
                    name="Product",
                    value=alert["alert"]["title"],
                    inline=False
                )
                
                embed.add_field(
                    name="Current Price",
                    value=f"₹{alert['current_price']:,.2f}",
                    inline=True
                )
                
                embed.add_field(
                    name="Target Price",
                    value=f"₹{alert['alert']['target_price']:,.2f}",
                    inline=True
                )
                
                embed.add_field(
                    name="Price Drop",
                    value=f"₹{alert['price_diff']:,.2f}",
                    inline=True
                )
                
                embed.add_field(
                    name="Product Link",
                    value=f"[Click here]({alert['alert']['url']})",
                    inline=False
                )
                
                await channel.send(embed=embed)
                
        except Exception as e:
            logger.error(f"Error checking price alerts: {str(e)}\n{traceback.format_exc()}")

    @nextcord.slash_command(name="analyze", description="Analyze price trends for a product")
    @app_commands.describe(
        url="Product URL to analyze",
        timeframe="Analysis timeframe"
    )
    @app_commands.choices(
        timeframe=[
            app_commands.Choice(name="24 Hours", value="day"),
            app_commands.Choice(name="7 Days", value="week"),
            app_commands.Choice(name="30 Days", value="month"),
            app_commands.Choice(name="1 Year", value="year")
        ]
    )
    async def analyze(
        self,
        interaction: nextcord.Interaction,
        url: str,
        timeframe: str = "week"
    ):
        await interaction.response.defer()
        
        try:
            await interaction.followup.send("📊 Analyzing price trends... This may take a moment.", ephemeral=True)
            
            # Get current product data
            current = await self.web_scraper.track_price(url, interaction.user.id)
            if current.get("error"):
                await interaction.followup.send(f"❌ {current['error']}", ephemeral=True)
                return

            # Get trend analysis
            analysis = await self.web_scraper.analyze_price_trends(url, timeframe)
            if analysis.get("error"):
                await interaction.followup.send(f"❌ {analysis['error']}", ephemeral=True)
                return

            embed = nextcord.Embed(
                title=f"📈 Price Analysis: {current['title']}",
                url=url,
                color=nextcord.Color.blue(),
                timestamp=datetime.now(timezone.utc)
            )

            # Current price and status
            embed.add_field(
                name="Current Price",
                value=f"₹{current['current_price']:,.2f}",
                inline=True
            )

            embed.add_field(
                name="Stock Status",
                value=current["stock_status"],
                inline=True
            )

            # Price statistics
            stats_text = (
                f"Average: ₹{analysis['avg_price']:,.2f}\n"
                f"Lowest: ₹{analysis['min_price']:,.2f}\n"
                f"Highest: ₹{analysis['max_price']:,.2f}\n"
                f"Volatility: ₹{analysis['price_volatility']:,.2f}\n"
                f"Trend: {analysis['trend']}"
            )
            embed.add_field(
                name="📊 Price Statistics",
                value=f"```\n{stats_text}\n```",
                inline=False
            )

            # Add trend visualization
            file = nextcord.File(analysis['plot'], filename="trend.png")
            embed.set_image(url="attachment://trend.png")
            
            await interaction.followup.send(embed=embed, file=file)
            
        except Exception as e:
            logger.error(f"Error in analyze command: {str(e)}\n{traceback.format_exc()}")
            await interaction.followup.send("❌ An error occurred while analyzing the price trends.", ephemeral=True)

async def setup(bot: commands.Bot):
    try:
        await bot.add_cog(CoreCommands(bot))
        logger.info("CoreCommands cog loaded successfully")
    except Exception as e:
        logger.exception("Failed to load CoreCommands cog")
        raise 