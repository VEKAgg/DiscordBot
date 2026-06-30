import asyncio
from datetime import UTC, datetime

import aiohttp
import nextcord
from dotenv import load_dotenv
from nextcord.ext import commands

from src.config.config import BOT_PREFIX, DISCORD_TOKEN
from src.core.runtime_state import runtime_state
from src.database.database import db
from src.utils.logger import get_logger, setup_logging
from src.utils.safety import (
    DatabaseUnavailableError,
    ExternalRequestError,
    ValidationError,
    format_context,
    safe_send,
)

logger = get_logger('VEKA.core')

EXTENSIONS = [
    'src.cogs.admin.basic',
    'src.cogs.admin.help',
    'src.cogs.admin.health',
    'src.cogs.admin.moderation',
    'src.cogs.admin.notifications',
    'src.cogs.networking.networking',
    'src.cogs.marketplace.marketplace',
    'src.cogs.marketplace.reviews',
    'src.cogs.resources.feeds',
    'src.cogs.mentorship',
    'src.cogs.marketplace_enhanced',
    'src.cogs.portfolio.portfolio_manager',
    'src.cogs.radio.radio',
    'src.cogs.rpg.rpg_manager',
    'src.cogs.external.info',
    'src.cogs.external.export',
    'src.cogs.status',
]


def get_intents() -> nextcord.Intents:
    intents = nextcord.Intents.default()
    intents.message_content = True
    intents.members = True
    intents.guilds = True
    intents.voice_states = True
    return intents


def build_bot() -> commands.Bot:
    bot = commands.Bot(command_prefix=BOT_PREFIX, intents=get_intents(), help_command=None)
    bot.runtime_state = runtime_state  # type: ignore[attr-defined]
    return bot


async def initialize_database() -> None:
    try:
        await db.connect()
        runtime_state.db_available = True
        logger.info('PostgreSQL database connected')
    except Exception as exc:
        runtime_state.db_available = False
        runtime_state.degraded_features.append('database')
        logger.error('Database connection failed: %s', exc, exc_info=True)
        return

    try:
        await db.run_migrations()
        logger.info('Database migrations applied')
    except Exception as exc:
        logger.error('Database migrations failed (DB remains available): %s', exc, exc_info=True)
        runtime_state.degraded_features.append('migrations')


def load_extensions(bot: commands.Bot, extensions: list[str]) -> None:
    for extension in extensions:
        try:
            bot.load_extension(extension)
            runtime_state.loaded_cogs.append(extension)
            logger.info(f'Loaded extension: {extension}')
        except Exception as exc:
            runtime_state.failed_cogs.append(extension)
            runtime_state.degraded_features.append(extension)
            logger.error(f'Failed to load extension {extension}: {exc}', exc_info=True)


def configure_bot_events(bot: commands.Bot) -> None:
    from nextcord.ext import tasks

    CONSECUTIVE_HEALTHY_REQUIRED = 3

    @tasks.loop(seconds=30)
    async def db_health_check():
        was_available = runtime_state.db_available
        try:
            if db.pool is None:
                await db.connect()
            await db.ping()

            # --- Ping succeeded ---
            if not was_available:
                # Recovering from outage — require N consecutive healthy pings
                healthy_count = runtime_state.alert_state_cache.get('healthy_count', 0) + 1
                runtime_state.alert_state_cache['healthy_count'] = healthy_count

                if healthy_count >= CONSECUTIVE_HEALTHY_REQUIRED:
                    runtime_state.db_available = True
                    runtime_state.last_recovery_time = datetime.now(UTC)
                    runtime_state.alert_state_cache.pop('healthy_count', None)
                    if hasattr(bot, 'notifier'):
                        bot.notifier.clear_cooldown('db_unavailable')
                        await bot.notifier.send_alert(
                            title='Database Reconnected',
                            description='The PostgreSQL database connection has been restored.',
                            severity='INFO',
                            dedupe_key='db_reconnected',
                            cooldown_minutes=10,
                        )
                    logger.info('Database connection restored.')
                else:
                    logger.info(
                        'Database ping succeeded (%d/%d consecutive healthy checks)',
                        healthy_count,
                        CONSECUTIVE_HEALTHY_REQUIRED,
                    )
            else:
                # Already healthy — reset counter
                runtime_state.alert_state_cache.pop('healthy_count', None)

        except DatabaseUnavailableError:
            # --- Ping failed ---
            runtime_state.alert_state_cache.pop('healthy_count', None)

            # Try to recover the pool immediately
            try:
                await db.reconnect()
                await db.ping()  # retry on fresh pool
                logger.info('Database recovered immediately via reconnect.')
                return  # transient blip, no alert
            except DatabaseUnavailableError:
                pass  # still down

            if was_available:
                runtime_state.db_available = False
                if hasattr(bot, 'notifier'):
                    await bot.notifier.send_alert(
                        title='Database Unavailable',
                        description='The PostgreSQL database connection was lost. Running in degraded mode.',
                        severity='CRITICAL',
                        dedupe_key='db_unavailable',
                        cooldown_minutes=60,
                    )
                logger.error('Database connection lost. Operating in degraded mode.')

    @bot.event
    async def on_ready():
        if getattr(bot, '_veka_ready', False):
            return
        bot._veka_ready = True  # type: ignore[attr-defined]

        from src.services.admin_notifier import AdminNotifier

        bot.notifier = AdminNotifier(bot)  # type: ignore[attr-defined]

        await initialize_database()

        from src.core.checks import StartupChecks

        await StartupChecks.run_all_checks()

        await bot.notifier.send_startup_summary()  # type: ignore[attr-defined]

        db_health_check.start()

        logger.info(f'{bot.user} is ready. DB available={runtime_state.db_available}')

        try:
            await bot.sync_all_application_commands()
        except Exception as exc:
            logger.warning(f'Application command sync failed: {exc}')

    @bot.event
    async def on_disconnect():
        try:
            await db.close()
            logger.info('Database connection closed on disconnect')
        except Exception as exc:
            logger.error(f'Error closing database on disconnect: {exc}')

    @bot.event
    async def on_command_error(ctx, error):
        original_error = error.original if isinstance(error, commands.CommandInvokeError) else error

        if isinstance(original_error, commands.CommandNotFound):
            await ctx.send('Command not found. Use /help or !help to see available commands.')
            return

        if isinstance(original_error, commands.MissingPermissions | commands.MissingRole | commands.NotOwner):
            await ctx.send('You do not have permission to use this command.')
            return

        if isinstance(original_error, commands.CommandOnCooldown):
            await ctx.send(f'This command is on cooldown. Try again in {original_error.retry_after:.1f}s.')
            return

        if isinstance(original_error, DatabaseUnavailableError):
            await ctx.send(
                'This feature is temporarily unavailable due to database connectivity issues. Please try again later.'
            )
            logger.warning('Database unavailable during command: %s | %s', original_error, format_context(ctx))
            return

        if isinstance(
            original_error,
            commands.BadArgument | commands.MissingRequiredArgument | commands.UserInputError | ValidationError,
        ):
            await ctx.send('Invalid command input. Please check your arguments and try again.')
            logger.warning('Validation error: %s | %s', original_error, format_context(ctx))
            return

        if isinstance(original_error, asyncio.TimeoutError | aiohttp.ClientError | ExternalRequestError):
            await ctx.send('A network or external service error occurred. Please try again later.')
            logger.warning('External request error: %s | %s', original_error, format_context(ctx))
            return

        logger.error('Unhandled command error: %s | %s', original_error, format_context(ctx), exc_info=True)
        await ctx.send('An internal error occurred while processing your command.')

    @bot.event
    async def on_application_command_error(interaction, error):
        original_error = error.original if isinstance(error, commands.CommandInvokeError) else error
        if isinstance(original_error, commands.CommandOnCooldown):
            await safe_send(
                interaction,
                content=f'This command is on cooldown. Try again in {original_error.retry_after:.1f}s.',
                ephemeral=True,
            )
            return

        if isinstance(original_error, commands.MissingPermissions | commands.MissingRole | commands.NotOwner):
            await safe_send(interaction, content='You do not have permission to use this command.', ephemeral=True)
            return

        if isinstance(original_error, DatabaseUnavailableError):
            await safe_send(
                interaction,
                content='This feature is temporarily unavailable due to database connectivity issues. Please try again later.',
                ephemeral=True,
            )
            logger.warning(
                'Database unavailable during slash command: %s | %s', original_error, format_context(interaction)
            )
            return

        if isinstance(
            original_error,
            commands.BadArgument | commands.MissingRequiredArgument | commands.UserInputError | ValidationError,
        ):
            await safe_send(
                interaction, content='Invalid command input. Please check your arguments and try again.', ephemeral=True
            )
            logger.warning('Validation error: %s | %s', original_error, format_context(interaction))
            return

        if isinstance(original_error, asyncio.TimeoutError | aiohttp.ClientError | ExternalRequestError):
            await safe_send(
                interaction,
                content='A network or external service error occurred. Please try again later.',
                ephemeral=True,
            )
            logger.warning('External request error: %s | %s', original_error, format_context(interaction))
            return

        logger.error(
            'Unhandled application command error: %s | %s', original_error, format_context(interaction), exc_info=True
        )
        await safe_send(
            interaction, content='An internal error occurred while processing your command.', ephemeral=True
        )


def run_bot() -> None:
    load_dotenv()
    setup_logging()
    bot = build_bot()
    configure_bot_events(bot)

    logger.info('Starting VEKA Discord bot bootstrap')

    try:
        load_extensions(bot, EXTENSIONS)
        assert DISCORD_TOKEN is not None
        bot.run(DISCORD_TOKEN)
    except Exception as exc:
        logger.error(f'Failed to start bot: {exc}')
