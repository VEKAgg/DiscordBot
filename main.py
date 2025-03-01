import os
import nextcord
from nextcord.ext import commands
import logging
from dotenv import load_dotenv
import motor.motor_asyncio
from datetime import datetime
import importlib.util
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

def load_cog_directly(bot, file_path):
    """Load a cog directly by importing its module and calling setup"""
    try:
        # Get the module name from the file path
        if file_path.startswith('./'):
            file_path = file_path[2:]
        
        # Convert path to module name
        module_name = file_path.replace('/', '.').replace('\\', '.').replace('.py', '')
        
        # Import the module
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None:
            logger.error(f"Could not find module spec for {file_path}")
            return False
        
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        
        # Call the setup function
        if hasattr(module, 'setup'):
            setup_func = getattr(module, 'setup')
            setup_func(bot)
            logger.info(f"Loaded cog from {file_path}")
            return True
        else:
            logger.error(f"No setup function found in {file_path}")
            return False
    except Exception as e:
        logger.error(f"Failed to load cog from {file_path}: {str(e)}")
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
    
    # Load all cogs directly
    cogs_loaded = 0
    
    # Load cogs from main directory
    for filename in os.listdir('./src/cogs'):
        if filename.endswith('.py') and not filename.startswith('__'):
            file_path = os.path.join('./src/cogs', filename)
            if load_cog_directly(bot, file_path):
                cogs_loaded += 1
    
    # Load cogs from subdirectories
    cog_subdirs = ['workshops', 'portfolio', 'gamification']
    for subdir in cog_subdirs:
        subdir_path = f'./src/cogs/{subdir}'
        if os.path.exists(subdir_path):
            for filename in os.listdir(subdir_path):
                if filename.endswith('.py') and not filename.startswith('__'):
                    file_path = os.path.join(subdir_path, filename)
                    if load_cog_directly(bot, file_path):
                        cogs_loaded += 1
    
    logger.info(f"Loaded {cogs_loaded} cogs")
    
    # Set bot status
    await bot.change_presence(
        activity=nextcord.Activity(
            type=nextcord.ActivityType.watching,
            name="your career growth! | !help"
        )
    )

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

# Basic utility commands
@bot.command(name="ping", description="Check bot's latency")
async def ping(ctx):
    """Check the bot's response time"""
    latency = round(bot.latency * 1000)
    await ctx.send(f"🏓 Pong! Latency: {latency}ms")

# Run the bot
if __name__ == '__main__':
    bot.run(os.getenv('DISCORD_TOKEN'))