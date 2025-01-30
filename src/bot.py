import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
from utils.logger import setup_logger
from utils.database import init_database
import asyncio
import random
import traceback

# Setup logging
logger = setup_logger()

# Load environment variables
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

class VEKABot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.presences = True
        intents.guild_messages = True
        intents.guilds = True
        intents.reactions = True
        
        super().__init__(
            command_prefix=commands.when_mentioned_or('v', 'v '),
            case_insensitive=True,
            intents=intents,
            help_command=None,
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="v help | VEKA Bot"
            )
        )
        
        self.status_task = None
        self.voice_client = None
        
        # Define initial extensions
        self.initial_extensions = [
            'cogs.core.commands',
            'cogs.core.information',
            'cogs.core.leveling',
            'cogs.core.welcome',
            'cogs.core.invites',
            'cogs.management.server',
            'cogs.analytics.stats',
            'cogs.system.monitor'
        ]
        
    async def setup_hook(self):
        """Initialize bot services and load cogs"""
        logger.info("Initializing bot services...")
        
        try:
            # Initialize database
            await init_database()
            logger.info("Database initialized successfully")
            
            # Load extensions
            loaded_cogs = 0
            for cog_name in self.initial_extensions:
                try:
                    await self.load_extension(cog_name)
                    loaded_cogs += 1
                    logger.info(f"Loaded extension: {cog_name}")
                except Exception as e:
                    logger.error(f"Failed to load extension {cog_name}: {str(e)}\n{traceback.format_exc()}")
            
            logger.info(f"Successfully loaded {loaded_cogs} cogs")
            
            # Clear existing commands and sync
            self.tree.clear_commands(guild=None)
            await self.tree.sync()
            logger.info("Successfully synced application commands")
            
        except Exception as e:
            logger.error(f"Error in setup_hook: {str(e)}\n{traceback.format_exc()}")

    async def change_status(self):
        """Rotate bot status messages"""
        statuses = [
            (discord.ActivityType.watching, "v help | VEKA Bot"),
            (discord.ActivityType.playing, f"{len(self.guilds)} servers"),
            (discord.ActivityType.listening, "your commands"),
            (discord.ActivityType.watching, f"{sum(g.member_count for g in self.guilds)} users")
        ]
        
        while not self.is_closed():
            status = random.choice(statuses)
            await self.change_presence(
                activity=discord.Activity(
                    type=status[0],
                    name=status[1]
                )
            )
            await asyncio.sleep(10)  # Change every 10 seconds
            
    async def on_ready(self):
        """Called when bot is ready and connected"""
        if not hasattr(self, 'uptime'):
            self.uptime = discord.utils.utcnow()
        
        logger.info(f'Logged in as {self.user.name} ({self.user.id})')
        
        # Start status rotation
        if self.status_task is None:
            self.status_task = self.loop.create_task(self.change_status())
        
        # Join voice channel
        try:
            channel = self.get_channel(1088553067554799809)
            if channel and isinstance(channel, discord.VoiceChannel):
                if not self.voice_clients:
                    vc = await channel.connect()
                    await vc.guild.change_voice_state(channel=channel, self_mute=True, self_deaf=True)
        except Exception as e:
            logger.error(f"Failed to join voice channel: {str(e)}")
        
        # Sync commands
        try:
            await self.tree.sync()
            logger.info("Successfully synced application commands")
        except Exception as e:
            logger.error(f"Failed to sync application commands: {str(e)}")

if __name__ == "__main__":
    bot = VEKABot()
    bot.run(TOKEN, log_handler=None) 