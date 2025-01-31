import os
import nextcord
from nextcord.ext import commands
from dotenv import load_dotenv
from utils.logger import setup_logger
import motor.motor_asyncio
from loguru import logger

# Setup logging
logger = setup_logger()

# Load environment variables
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
MONGODB_URI = os.getenv('MONGODB_URI')

class VEKABot(commands.Bot):
    def __init__(self):
        intents = nextcord.Intents.default()
        intents.message_content = True
        intents.members = True
        
        super().__init__(
            command_prefix="!",  # Fallback prefix for message commands
            intents=intents,
            help_command=None  # Disable default help command
        )
        
        self.db = None  # Will be initialized in setup_hook

    async def setup_hook(self):
        # Initialize database connection
        try:
            self.db = motor.motor_asyncio.AsyncIOMotorClient(MONGODB_URI).veka
            logger.info("Database connection established")
        except Exception as e:
            logger.error(f"Database connection failed: {e}")
            raise

        # Load all cogs
        for folder in ['core', 'system', 'analytics']:
            cog_dir = f"cogs/{folder}"
            for filename in os.listdir(cog_dir):
                if filename.endswith('.py'):
                    try:
                        await self.load_extension(f"cogs.{folder}.{filename[:-3]}")
                        logger.info(f"Loaded extension: {folder}.{filename[:-3]}")
                    except Exception as e:
                        logger.error(f"Failed to load extension {filename}: {e}")

    async def on_ready(self):
        logger.info(f"Logged in as {self.user.name}")
        await self.change_presence(activity=nextcord.Game(name="/help"))

def main():
    bot = VEKABot()
    
    try:
        logger.info("Starting bot...")
        bot.run(TOKEN)
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        raise

if __name__ == "__main__":
    main() 