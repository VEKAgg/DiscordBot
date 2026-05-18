import os
import nextcord
from nextcord.ext import commands
import logging
from dotenv import load_dotenv
from datetime import datetime
from src.database.database import db

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

# Cog extension paths — add new cogs here
EXTENSIONS = [
    'src.cogs.basic',
    'src.cogs.feeds',
    'src.cogs.fun',
    'src.cogs.help',
    'src.cogs.marketplace',
    'src.cogs.marketplace_enhanced',
    'src.cogs.marketplace_reviews',
    'src.cogs.mentorship',
    'src.cogs.networking',
    'src.cogs.quiz',
    'src.cogs.gamification.gamification_manager',
]


@bot.event
async def on_ready():
    logger.info(f'{bot.user} has connected to Discord!')

    # Initialize MongoDB
    try:
        await db.connect()
        logger.info('MongoDB initialized successfully')
    except Exception as e:
        logger.error(f'Failed to initialize MongoDB: {e}')

    # Load cog extensions with per-cog error logging
    cogs_loaded = 0
    for ext in EXTENSIONS:
        try:
            bot.load_extension(ext)
            logger.info(f'Loaded extension: {ext}')
            cogs_loaded += 1
        except Exception as e:
            logger.error(f'Failed to load extension {ext}: {e}')

    logger.info(f'{cogs_loaded}/{len(EXTENSIONS)} extensions loaded')

    # Set bot presence
    await bot.change_presence(
        activity=nextcord.Activity(
            type=nextcord.ActivityType.watching,
            name='your career growth! | !help'
        )
    )
    bot.sync_all_application_commands()


@bot.event
async def on_member_join(member):
    """Send welcome message when a new member joins."""
    try:
        system_channel = member.guild.system_channel or nextcord.utils.get(
            member.guild.text_channels, name='general'
        )
        if system_channel:
            embed = nextcord.Embed(
                title=f'Welcome to {member.guild.name}!',
                description=(
                    f'Hey {member.mention}, welcome to our community!\n\n'
                    'Here is how to get started:\n'
                    '- Use `!help` to see all available commands\n'
                    '- Review the server rules and guidelines\n'
                    '- Introduce yourself in the community\n'
                    '- Have fun and engage with others!\n\n'
                    'Need help? Reach out to a moderator.'
                ),
                color=nextcord.Color.green()
            )
            embed.set_thumbnail(
                url=member.avatar.url if member.avatar else member.default_avatar.url
            )
            await system_channel.send(embed=embed)

        try:
            await member.send(
                f'Welcome to {member.guild.name}!\n\n'
                'To get started:\n'
                '1. Read the server rules\n'
                '2. Set up your profile with `!setupprofile`\n'
                '3. Introduce yourself to the community\n\n'
                'If you need any help, feel free to ask a moderator!'
            )
        except nextcord.Forbidden:
            logger.warning(f"Couldn't send DM to {member.name}")

    except Exception as e:
        logger.error(f'Error in welcome message: {e}')


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send('Command not found. Use !help to see available commands.')
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send('You do not have permission to use this command.')
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f'Missing required argument: {error.param.name}')
    elif isinstance(error, commands.BadArgument):
        await ctx.send('Invalid argument provided. Check the command usage with !help.')
    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.send(
            f'This command is on cooldown. Try again in {error.retry_after:.1f}s.'
        )
    else:
        logger.error(f'Unhandled command error: {error}')
        await ctx.send('An error occurred while processing your command.')


@bot.event
async def on_application_command_error(interaction, error):
    if isinstance(error, commands.CommandOnCooldown):
        await interaction.response.send_message(
            f'This command is on cooldown. Try again in {error.retry_after:.1f}s.',
            ephemeral=True
        )
    elif isinstance(error, commands.MissingPermissions):
        await interaction.response.send_message(
            'You do not have permission to use this command.',
            ephemeral=True
        )
    else:
        logger.error(f'Unhandled application command error: {error}')
        await interaction.response.send_message(
            'An error occurred while processing your command.',
            ephemeral=True
        )


@bot.event
async def on_disconnect():
    """Close the database connection on shutdown."""
    try:
        await db.close()
        logger.info('Database connection closed')
    except Exception as e:
        logger.error(f'Error closing database: {e}')


if __name__ == '__main__':
    bot.run(os.getenv('DISCORD_TOKEN'))
