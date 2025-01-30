import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
from utils.logger import setup_logger
from utils.database import init_database
import asyncio
import random

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
        
    async def setup_hook(self):
        """Initialize bot services and load cogs"""
        logger.info("Initializing bot...")
        
        # Initialize database
        await init_database()
        
        # Load cogs by category
        cog_categories = ['core', 'analytics', 'management', 'system']
        
        for folder in cog_categories:
            path = f'cogs/{folder}'
            if not os.path.exists(path):
                os.makedirs(path)
                continue
                
            for file in os.listdir(path):
                if file.endswith('.py'):
                    try:
                        await self.load_extension(f'cogs.{folder}.{file[:-3]}')
                        logger.info(f"Loaded extension: {folder}.{file[:-3]}")
                    except Exception as e:
                        logger.error(f"Failed to load extension {folder}.{file[:-3]}: {str(e)}")
        
        # Sync commands once after all cogs are loaded
        try:
            await self.tree.sync()
            logger.info("Successfully synced all commands")
        except Exception as e:
            logger.error(f"Failed to sync commands: {str(e)}")

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