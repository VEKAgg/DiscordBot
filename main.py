import os
import nextcord
from nextcord.ext import commands
import logging
from dotenv import load_dotenv
import motor.motor_asyncio
from datetime import datetime
import importlib
import sys
from src.database.mongodb import init_db

# Configure logging
if not os.path.exists('logs'):
    os.makedirs('logs')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('VEKA')

# Load environment variables
load_dotenv()

# Bot configuration
intents = nextcord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# Initialize MongoDB client
mongo_client = motor.motor_asyncio.AsyncIOMotorClient(os.getenv('MONGODB_URI'))
bot.mongo = mongo_client.veka_bot
bot.db = bot.mongo  # Add this line to make db accessible to cogs

def load_cog(cog_path):
    """Load a cog from a file path"""
    try:
        # Convert path to module name
        if cog_path.startswith('./'):
            cog_path = cog_path[2:]
        
        module_name = cog_path.replace('/', '.').replace('\\', '.').replace('.py', '')
        
        # Import the module
        if module_name in sys.modules:
            # Reload the module if it's already loaded
            module = importlib.reload(sys.modules[module_name])
        else:
            # Import the module for the first time
            module = importlib.import_module(module_name)
        
        # Try different class name formats
        class_names = [
            # Standard format: capitalize the last part of the module name
            module_name.split('.')[-1].capitalize(),
            
            # CamelCase format: capitalize each word in the last part
            ''.join(word.capitalize() for word in module_name.split('.')[-1].split('_')),
            
            # Specific names for known modules
            'WorkshopManager' if 'workshop_manager' in module_name else None,
            'PortfolioManager' if 'portfolio_manager' in module_name else None,
            'GamificationManager' if 'gamification_manager' in module_name else None
        ]
        
        # Filter out None values
        class_names = [name for name in class_names if name]
        
        # Try each class name
        for class_name in class_names:
            if hasattr(module, class_name):
                # Create an instance of the cog and add it to the bot
                cog_class = getattr(module, class_name)
                bot.add_cog(cog_class(bot))
                logger.info(f"Loaded cog: {module_name}")
                return True
        
        # If we get here, none of the class names worked
        logger.error(f"Could not find a valid cog class in {module_name}. Tried: {', '.join(class_names)}")
        return False
    except Exception as e:
        logger.error(f"Failed to load cog {cog_path}: {str(e)}")
        return False

@bot.event
async def on_ready():
    logger.info(f'{bot.user} has connected to Discord!')
    
    # Initialize database
    try:
        await init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {str(e)}")
    
    # Load cogs
    cogs_loaded = 0
    
    # Load cogs from main directory
    for filename in os.listdir('./src/cogs'):
        if filename.endswith('.py') and not filename.startswith('__'):
            cog_path = f'src.cogs.{filename[:-3]}'
            if load_cog(cog_path):
                cogs_loaded += 1
    
    # Load cogs from subdirectories
    cog_subdirs = ['workshops', 'portfolio', 'gamification']
    for subdir in cog_subdirs:
        subdir_path = f'./src/cogs/{subdir}'
        if os.path.exists(subdir_path):
            for filename in os.listdir(subdir_path):
                if filename.endswith('.py') and not filename.startswith('__'):
                    cog_path = f'src.cogs.{subdir}.{filename[:-3]}'
                    if load_cog(cog_path):
                        cogs_loaded += 1
    
    # Set bot status
    await bot.change_presence(
        activity=nextcord.Activity(
            type=nextcord.ActivityType.watching,
            name="your career growth! | !help"
        )
    )
    
    logger.info(f"Loaded {cogs_loaded} cogs")

@bot.event
async def on_member_join(member):
    """Send welcome message when a new member joins"""
    try:
        # Get the system channel (usually where Discord sends welcome messages)
        system_channel = member.guild.system_channel
        if not system_channel:
            # If no system channel, try to find a general channel
            system_channel = nextcord.utils.get(member.guild.text_channels, name='general')
        
        if system_channel:
            embed = nextcord.Embed(
                title=f"Welcome to {member.guild.name}! 🎉",
                description=f"Hey {member.mention}, welcome to our community! 🌟\n\n"
                          f"Here's how to get started:\n"
                          f"• Use `!help` to see all available commands\n"
                          f"• Check out our rules and guidelines\n"
                          f"• Introduce yourself in the community\n"
                          f"• Have fun and engage with others!\n\n"
                          f"Need help? Don't hesitate to ask the moderators!",
                color=nextcord.Color.green()
            )
            embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
            await system_channel.send(embed=embed)
            
            # Send a private welcome message
            try:
                await member.send(
                    f"Welcome to {member.guild.name}! 🎉\n\n"
                    f"We're excited to have you here! To help you get started:\n"
                    f"1. Read the server rules\n"
                    f"2. Set up your profile with `!setupprofile`\n"
                    f"3. Introduce yourself to the community\n\n"
                    f"If you need any help, feel free to ask the moderators!"
                )
            except nextcord.Forbidden:
                logger.warning(f"Couldn't send DM to {member.name}#{member.discriminator}")
                
    except Exception as e:
        logger.error(f"Error in welcome message: {str(e)}")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send("❌ Command not found. Use !help to see available commands.")
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You don't have permission to use this command.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Missing required argument: {error.param.name}")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ Invalid argument provided. Please check the command usage with !help.")
    else:
        logger.error(f'Error occurred: {str(error)}')
        await ctx.send("❌ An error occurred while processing your command.")

# Run the bot
if __name__ == '__main__':
    bot.run(os.getenv('DISCORD_TOKEN'))