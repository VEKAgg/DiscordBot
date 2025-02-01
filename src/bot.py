import os
import nextcord
from nextcord.ext import commands
import motor.motor_asyncio
import logging
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv
import sys
import asyncio

# Create logs directory if it doesn't exist
os.makedirs('logs', exist_ok=True)

# Configure root logger
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

# Set up nextcord logger
nextcord_logger = logging.getLogger('nextcord')
nextcord_logger.setLevel(logging.INFO)

# Set up bot logger
bot_logger = logging.getLogger('bot')
bot_logger.setLevel(logging.INFO)

# Create formatters
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# File handlers
file_handler = RotatingFileHandler(
    filename='logs/bot.log',
    maxBytes=32 * 1024 * 1024,  # 32 MiB
    backupCount=5,
    encoding='utf-8'
)
file_handler.setFormatter(formatter)

error_handler = RotatingFileHandler(
    filename='logs/error.log',
    maxBytes=32 * 1024 * 1024,
    backupCount=5,
    encoding='utf-8'
)
error_handler.setFormatter(formatter)
error_handler.setLevel(logging.ERROR)

# Add handlers to loggers
nextcord_logger.addHandler(file_handler)
nextcord_logger.addHandler(error_handler)
bot_logger.addHandler(file_handler)
bot_logger.addHandler(error_handler)

# Load environment variables
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
MONGODB_URI = os.getenv('MONGODB_URI')

if not all([TOKEN, MONGODB_URI]):
    raise ValueError("TOKEN and MONGODB_URI must be set in .env file")

logger = bot_logger  # Use bot logger as default

class VEKABot(commands.Bot):
    def __init__(self):
        logger.info("Initializing bot...")
        intents = nextcord.Intents.default()
        
        # Required intents based on our features
        intents.guilds = True          
        intents.members = True         
        intents.presences = True       
        intents.guild_messages = True  
        intents.message_content = True  
        intents.voice_states = True    
        
        super().__init__(
            command_prefix='/',
            intents=intents,
            help_command=None,
            description="VEKA Bot - A Discord bot for server management",
            activity=nextcord.Activity(
                type=nextcord.ActivityType.watching,
                name="/help | Starting up..."
            ),
            status=nextcord.Status.idle
        )
        
        self.db = None
        self._extensions_loaded = False
        self._command_sync_flags = {}

    async def setup_hook(self) -> None:
        """Initialize bot and load all cogs"""
        try:
            await self._init_database()
            await self._load_cogs()
            await self._verify_commands()
            await self._update_status()
        except Exception as e:
            logger.exception("Critical error during bot setup")
            await self._fallback_initialization()

    async def _init_database(self) -> None:
        """Initialize database connection with retry logic"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                logger.info(f"Connecting to database (attempt {attempt + 1}/{max_retries})...")
                self.db = motor.motor_asyncio.AsyncIOMotorClient(
                    MONGODB_URI,
                    serverSelectionTimeoutMS=5000,
                    connectTimeoutMS=5000,
                    retryWrites=True
                ).veka
                
                await self.db.command('ping')
                await self.db.test.insert_one({"test": "connection"})
                await self.db.test.delete_one({"test": "connection"})
                logger.info("Database connection established")
                return
            except Exception as e:
                if attempt == max_retries - 1:
                    raise RuntimeError(f"Database connection failed: {str(e)}")
                logger.warning(f"Database connection failed: {str(e)}")
                await asyncio.sleep(2)

    async def _load_cogs(self) -> None:
        """Load all cogs with verification"""
        cog_list = [
            "cogs.core.events",
            "cogs.core.commands",
            "cogs.core.roles",
            "cogs.core.leveling",
            "cogs.core.information",
            "cogs.management.server",
            "cogs.system.tasks"
        ]

        loaded_cogs = []
        for cog in cog_list:
            try:
                await self.load_extension(cog)
                loaded_cogs.append(cog)
                logger.info(f"Loaded cog: {cog}")
            except Exception as e:
                logger.error(f"Failed to load {cog}: {str(e)}")
                # Rollback loaded cogs on critical failure
                if cog in ["cogs.core.events", "cogs.core.commands"]:
                    for loaded_cog in loaded_cogs:
                        await self.unload_extension(loaded_cog)
                    raise RuntimeError(f"Critical cog {cog} failed to load")

    async def _verify_commands(self) -> None:
        """Verify and sync slash commands"""
        try:
            logger.info("Syncing application commands...")
            commands_before = len(self.application_commands)
            await self.tree.sync()
            commands_after = len(self.application_commands)
            
            if commands_after < commands_before:
                logger.warning(f"Command count decreased: {commands_before} -> {commands_after}")
            else:
                logger.info(f"Successfully synced {commands_after} commands")
                
            # Verify essential commands
            essential_commands = {"help", "info", "ping"}
            registered_commands = {cmd.name for cmd in self.application_commands}
            missing_commands = essential_commands - registered_commands
            
            if missing_commands:
                raise RuntimeError(f"Missing essential commands: {missing_commands}")
                
        except Exception as e:
            raise RuntimeError(f"Command sync failed: {str(e)}")

    async def _fallback_initialization(self) -> None:
        """Fallback initialization when critical errors occur"""
        logger.warning("Entering fallback initialization mode")
        try:
            # Load only essential cogs
            essential_cogs = ["cogs.core.events", "cogs.core.commands"]
            for cog in essential_cogs:
                await self.load_extension(cog)
            
            # Update status to indicate limited functionality
            await self.change_presence(
                activity=nextcord.Activity(
                    type=nextcord.ActivityType.watching,
                    name="⚠️ Limited functionality | /help"
                ),
                status=nextcord.Status.dnd
            )
            logger.info("Fallback initialization completed")
        except Exception as e:
            logger.critical(f"Fallback initialization failed: {str(e)}")
            raise SystemExit("Cannot continue with bot operation")

    async def _update_status(self) -> None:
        """Update bot status"""
        try:
            logger.info("Syncing application commands...")
            await self.tree.sync()
            logger.info("Application commands synced")

            self._extensions_loaded = True
            
            # Update status to online once everything is ready
            await self.change_presence(
                activity=nextcord.Activity(
                    type=nextcord.ActivityType.watching,
                    name=f"/help | {len(self.guilds)} servers"
                ),
                status=nextcord.Status.online
            )
            logger.info("Bot setup completed successfully")
        except Exception as e:
            logger.exception("Failed to update status")
            await self._fallback_initialization()

def run_bot():
    bot = VEKABot()
    try:
        logger.info("Starting bot...")
        bot.run(TOKEN)
    except Exception as e:
        logger.exception("Failed to start bot")
        raise

if __name__ == "__main__":
    try:
        run_bot()
    except KeyboardInterrupt:
        logger.info("Bot shutdown by user")
    except Exception as e:
        logger.exception("Unexpected error occurred") 