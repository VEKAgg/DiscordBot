"""
Safety Utilities for VEKA Bot
Provides error handling, admin checks, and safe message sending
"""

import logging
from functools import wraps

import nextcord
from nextcord.ext import commands

from src.config.config import ADMIN_IDS, OWNER_IDS
from src.core.runtime_state import runtime_state

logger = logging.getLogger('VEKA.safety')

# ============================================================
# Custom Exceptions
# ============================================================


class DatabaseUnavailableError(RuntimeError):
    """Raised when a command requires a database but it is unavailable."""


class ValidationError(ValueError):
    """Raised for invalid user input."""


class ExternalRequestError(RuntimeError):
    """Raised when an external service (RSS, API) fails."""


# ============================================================
# Formatting / context helpers
# ============================================================


def format_context(source) -> str:
    """Extract command, guild, channel, user from a Context or Interaction."""
    if isinstance(source, commands.Context):
        return (
            f'command={source.command} '
            f'guild_id={source.guild.id if source.guild else None} '
            f'channel_id={source.channel.id} '
            f'user_id={source.author.id}'
        )
    if isinstance(source, nextcord.Interaction):
        return (
            f'command={source.application_command.name if source.application_command else None} '
            f'guild_id={source.guild.id if source.guild else None} '
            f'channel_id={source.channel.id if source.channel else None} '
            f'user_id={source.user.id}'
        )
    return str(source)


def map_exception_to_message(error: Exception) -> str:
    """Map an exception to a user-friendly message string."""
    if isinstance(error, DatabaseUnavailableError):
        return 'The database is currently unavailable. Please try again later.'
    if isinstance(error, ValidationError):
        return f'Invalid input: {error}'
    if isinstance(error, ExternalRequestError):
        return 'An external service is currently unavailable. Please try again later.'
    if isinstance(error, commands.CommandNotFound):
        return 'Command not found. Use `/help` to see available commands.'
    if isinstance(error, commands.MissingPermissions):
        return 'You do not have permission to use this command.'
    if isinstance(error, commands.CommandOnCooldown):
        return f'This command is on cooldown. Try again in {error.retry_after:.0f} seconds.'
    return 'An unexpected error occurred. Please try again later.'


# ============================================================
# Admin / permission checks
# ============================================================


def _is_admin_user(user, guild=None) -> bool:
    """Check if a user has admin privileges via ID lists or Discord permissions."""
    if user is None:
        return False
    if user.id in OWNER_IDS or user.id in ADMIN_IDS:
        return True
    if isinstance(user, nextcord.Member):
        if user.guild_permissions.administrator:
            return True
    elif guild is not None:
        member = guild.get_member(user.id)
        if member and member.guild_permissions.administrator:
            return True
    return False


def _is_staff_user(user, guild=None) -> bool:
    """Check if a user has staff privileges via ID lists or RBAC role."""
    if user is None:
        return False
    # Admin/owner implies staff
    if _is_admin_user(user, guild):
        return True
    try:
        from types import SimpleNamespace

        from src.utils.security.rbac import ROLE_HIERARCHY, Role, rbac

        ctx = SimpleNamespace(author=user, guild=guild)
        role = rbac.get_user_role(ctx)
        return ROLE_HIERARCHY.index(role) >= ROLE_HIERARCHY.index(Role.STAFF)
    except Exception:
        return False


def admin_only():
    """Decorator: only allow admin/owner users (by ID or Discord permission)."""

    def predicate(ctx_or_interaction):
        if isinstance(ctx_or_interaction, commands.Context):
            return _is_admin_user(ctx_or_interaction.author, ctx_or_interaction.guild)
        if isinstance(ctx_or_interaction, nextcord.Interaction):
            return _is_admin_user(ctx_or_interaction.user, ctx_or_interaction.guild)
        return False

    return commands.check(predicate)


def staff_only():
    """Decorator: only allow staff or higher users (by ID, Discord role, or admin status)."""

    def predicate(ctx_or_interaction):
        if isinstance(ctx_or_interaction, commands.Context):
            return _is_staff_user(ctx_or_interaction.author, ctx_or_interaction.guild)
        if isinstance(ctx_or_interaction, nextcord.Interaction):
            return _is_staff_user(ctx_or_interaction.user, ctx_or_interaction.guild)
        return False

    return commands.check(predicate)


# ============================================================
# Safe sending
# ============================================================


async def safe_send(target, content=None, *, embed=None, ephemeral=False):
    """Send a message safely, handling both Context and Interaction."""
    try:
        if isinstance(target, commands.Context):
            await target.send(content=content, embed=embed)
        elif isinstance(target, nextcord.Interaction):
            if target.response.is_done():
                await target.followup.send(content=content, embed=embed, ephemeral=ephemeral)
            else:
                await target.response.send_message(content=content, embed=embed, ephemeral=ephemeral)
    except Exception as exc:
        logger.error('safe_send failed: %s', exc, exc_info=True)


# ============================================================
# Error logging
# ============================================================


def log_error(error: Exception, source, module: str = 'unknown') -> None:
    """Structured error logging."""
    ctx_str = format_context(source)
    logger.error(
        'Unhandled error in %s | %s | %s: %s',
        module,
        ctx_str,
        type(error).__name__,
        error,
        exc_info=True,
    )


# ============================================================
# Command wrappers
# ============================================================


def safe_command(requires_db: bool = False):
    """Decorator for prefix commands: catches exceptions and sends error embed."""

    def decorator(func):
        @commands.command()
        async def wrapper(self, ctx, *args, **kwargs):
            if requires_db and not runtime_state.db_available:
                embed = nextcord.Embed(
                    title='Database Unavailable',
                    description='This command requires the database, which is currently offline. Please try again later.',
                    color=nextcord.Color.red(),
                )
                await safe_send(ctx, embed=embed)
                return
            try:
                return await func(self, ctx, *args, **kwargs)
            except commands.CommandError:
                raise
            except Exception as error:
                log_error(error, ctx, module=func.__module__)
                msg = map_exception_to_message(error)
                embed = nextcord.Embed(title='Error', description=msg, color=nextcord.Color.red())
                await safe_send(ctx, embed=embed)

        return wrapper

    return decorator


def safe_slash_command(requires_db: bool = False):
    """Decorator for slash commands: catches exceptions and sends ephemeral error embed."""

    def decorator(func):
        @nextcord.slash_command()
        async def wrapper(self, interaction, *args, **kwargs):
            if requires_db and not runtime_state.db_available:
                embed = nextcord.Embed(
                    title='Database Unavailable',
                    description='This command requires the database, which is currently offline. Please try again later.',
                    color=nextcord.Color.red(),
                )
                await safe_send(interaction, embed=embed, ephemeral=True)
                return
            try:
                return await func(self, interaction, *args, **kwargs)
            except commands.CommandError:
                raise
            except Exception as error:
                log_error(error, interaction, module=func.__module__)
                msg = map_exception_to_message(error)
                embed = nextcord.Embed(title='Error', description=msg, color=nextcord.Color.red())
                await safe_send(interaction, embed=embed, ephemeral=True)

        return wrapper

    return decorator


# ============================================================
# Background task wrapper
# ============================================================


async def run_safe_task(coro, name: str, logger_obj, bot=None):
    """Run a coroutine with failure tracking and alerting."""
    try:
        await coro
    except Exception as exc:
        cache = runtime_state.alert_state_cache
        key = f'task_fail:{name}'
        count = cache.get(key, 0) + 1
        cache[key] = count

        logger_obj.error('Task %s failed (consecutive failures: %d): %s', name, count, exc, exc_info=True)

        if count == 3 and bot and hasattr(bot, 'notifier') and bot.notifier:
            await bot.notifier.send_alert(
                title=f'Background Task Failing: {name}',
                description=f'Task `{name}` has failed {count} consecutive times.\nLast error: `{exc}`',
                severity='ERROR',
                dedupe_key=key,
                cooldown_minutes=30,
            )
        return

    # On success, clear failure count and send recovery if needed
    cache = runtime_state.alert_state_cache
    key = f'task_fail:{name}'
    prev_failures = cache.pop(key, 0)

    if prev_failures >= 3 and bot and hasattr(bot, 'notifier') and bot.notifier:
        bot.notifier.clear_cooldown(key)
        await bot.notifier.send_alert(
            title=f'Task Recovered: {name}',
            description=f'Task `{name}` has recovered after {prev_failures} failures.',
            severity='INFO',
            dedupe_key=f'task_recovered:{name}',
            cooldown_minutes=60,
        )


def safe_background_task(name: str):
    """Decorator for background tasks: wraps with run_safe_task."""

    def decorator(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            bot = self.bot if hasattr(self, 'bot') else None
            logger_obj = logging.getLogger(f'VEKA.task.{name}')
            await run_safe_task(func(self, *args, **kwargs), name, logger_obj, bot)

        return wrapper

    return decorator
