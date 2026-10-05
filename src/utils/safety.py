"""
Safety Utilities for VEKA Bot
Provides error handling, admin checks, and safe message sending
"""

import inspect
import logging
from functools import wraps

import nextcord
from nextcord.application_command import BaseApplicationCommand, CallbackWrapper, SlashApplicationSubcommand
from nextcord.errors import ApplicationCheckFailure
from nextcord.ext import application_checks, commands

from src.config.config import ADMIN_IDS, OWNER_IDS
from src.core.runtime_state import runtime_state

logger = logging.getLogger('VEKA.safety')

# ============================================================
# Custom Exceptions
# ============================================================


class DatabaseUnavailableError(RuntimeError):
    """Raised when a command requires a database but it is unavailable."""


class DatabaseQueryError(DatabaseUnavailableError):
    """A query failed while the database itself is reachable (bad SQL, constraint, type error).

    Subclasses DatabaseUnavailableError so existing ``except DatabaseUnavailableError`` handlers still
    degrade gracefully, but users are told it's an error rather than "the database is offline" (M-01).
    """


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
    """Map an exception to a user-friendly message string with actionable suggestions."""
    if isinstance(error, DatabaseQueryError):
        return '\u274c An unexpected error occurred.\n\U0001f4a1 Try again later. If this persists, contact staff.'
    if isinstance(error, DatabaseUnavailableError):
        return (
            '\u274c The database is currently unavailable.\n'
            '\U0001f4a1 Try again in a few minutes. If this persists, contact staff.'
        )
    if isinstance(error, ValidationError):
        return f'\u274c Invalid input: {error}\n\U0001f4a1 Check the command description for valid options.'
    if isinstance(error, ExternalRequestError):
        return (
            '\u274c An external service is currently unavailable.\n'
            '\U0001f4a1 Try again later. If this persists, contact staff.'
        )
    if isinstance(error, commands.CommandNotFound):
        return '\u274c Command not found.\n\U0001f4a1 Use `/help` to see all available commands.'
    if isinstance(error, commands.MissingPermissions):
        return (
            '\u274c You do not have permission to use this command.\n'
            '\U0001f4a1 This command requires administrator or staff permissions.'
        )
    if isinstance(error, commands.CommandOnCooldown):
        minutes = int(error.retry_after // 60)
        seconds = int(error.retry_after % 60)
        time_str = f'{minutes}m {seconds}s' if minutes > 0 else f'{seconds}s'
        return f'\u23f3 This command is on cooldown. Try again in **{time_str}**.'
    return '\u274c An unexpected error occurred.\n\U0001f4a1 Try again later. If this persists, contact staff.'


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


class PermissionDenied(commands.CheckFailure):
    """Raised (prefix) or reported (slash) when a permission guard rejects the invoker."""


class AppPermissionDenied(ApplicationCheckFailure):
    """Application-command counterpart of ``PermissionDenied`` (message is user-facing)."""


_APP_COMMAND_TYPES = (BaseApplicationCommand, SlashApplicationSubcommand, CallbackWrapper)


def _source_user_and_guild(source):
    if isinstance(source, commands.Context):
        return source.author, source.guild
    if isinstance(source, nextcord.Interaction):
        return source.user, source.guild
    return None, None


def permission_guard(predicate, denial_message: str):
    """Build a decorator that enforces ``predicate(ctx_or_interaction) -> bool`` on prefix *and* slash commands.

    nextcord application commands ignore ``commands.check`` (it only sets ``__commands_checks__``,
    which prefix ``Command`` reads), so a plain ``commands.check`` silently does nothing on slash
    commands. This decorator works wherever it is placed:

    - on a prefix ``commands.Command`` → ``commands.check``
    - on an application command object → ``application_checks.check``
    - on a plain coroutine (the usual position, under ``@slash_command``/``@subcommand`` or
      ``@commands.command``) → the callback is wrapped so the predicate runs before the body,
      and ``commands.check`` is attached as well for prefix help/visibility.
    """

    async def _allowed(source) -> bool:
        result = predicate(source)
        if inspect.isawaitable(result):
            result = await result
        return bool(result)

    async def _check(source) -> bool:
        if await _allowed(source):
            return True
        raise PermissionDenied(denial_message)

    async def _app_check(interaction) -> bool:
        if await _allowed(interaction):
            return True
        raise AppPermissionDenied(denial_message)

    def decorator(target):
        if isinstance(target, commands.Command):
            return commands.check(_check)(target)
        if isinstance(target, _APP_COMMAND_TYPES):
            return application_checks.check(_app_check)(target)  # type: ignore[arg-type]

        @wraps(target)
        async def wrapper(self, source, *args, **kwargs):
            if not await _allowed(source):
                if isinstance(source, nextcord.Interaction):
                    logger.warning('Permission denied | %s', format_context(source))
                    embed = nextcord.Embed(
                        title='Permission denied', description=denial_message, color=nextcord.Color.red()
                    )
                    await safe_send(source, embed=embed, ephemeral=True)
                    return None
                raise PermissionDenied(denial_message)
            return await target(self, source, *args, **kwargs)

        guards = [*getattr(target, '__veka_guards__', []), denial_message]
        wrapper.__veka_guards__ = guards  # type: ignore[attr-defined]
        return commands.check(_check)(wrapper)

    return decorator


def _admin_predicate(source) -> bool:
    user, guild = _source_user_and_guild(source)
    return _is_admin_user(user, guild)


def _staff_predicate(source) -> bool:
    user, guild = _source_user_and_guild(source)
    return _is_staff_user(user, guild)


def admin_only():
    """Decorator: only allow admin/owner users (by ID or Discord permission). Works for prefix and slash."""
    return permission_guard(_admin_predicate, 'This command is restricted to server administrators.')


def staff_only():
    """Decorator: only allow staff or higher users (by ID, Discord role, or admin status). Works for prefix and slash."""
    return permission_guard(_staff_predicate, 'This command is restricted to staff.')


def _manage_guild_predicate(source) -> bool:
    user, guild = _source_user_and_guild(source)
    if _is_admin_user(user, guild):
        return True
    member = user if isinstance(user, nextcord.Member) else (guild.get_member(user.id) if guild and user else None)
    return bool(member and guild and member.guild_permissions.manage_guild)


def manage_guild_only():
    """Decorator: admins or members with Manage Server in the current guild. Works for prefix and slash."""
    return permission_guard(_manage_guild_predicate, 'This command requires the **Manage Server** permission.')


def _bot_operator_predicate(source) -> bool:
    """Bot-wide operations (reloading code, global settings): OWNER_IDS/ADMIN_IDS, or admins of the main guild."""
    from src.config.config import MAIN_GUILD_ID

    user, guild = _source_user_and_guild(source)
    if user is None:
        return False
    if user.id in OWNER_IDS or user.id in ADMIN_IDS:
        return True
    return guild is not None and guild.id == MAIN_GUILD_ID and _is_admin_user(user, guild)


def bot_operator_only():
    """Decorator for actions that affect the bot in every server. Works for prefix and slash."""
    return permission_guard(_bot_operator_predicate, 'This command is restricted to the bot operators.')


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
    """Decorator for prefix commands: catches exceptions and sends error embed.
    Must be used as the innermost decorator, paired with @commands.command() on the outside."""

    def decorator(func):
        @wraps(func)
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
    """Decorator for slash commands: catches exceptions and sends ephemeral error embed.
    Must be used as the innermost decorator, paired with @nextcord.slash_command() or
    @group.subcommand() on the outside."""

    def decorator(func):
        @wraps(func)
        async def wrapper(self, interaction, *args, **kwargs):
            if requires_db and not runtime_state.db_available:
                embed = nextcord.Embed(
                    title='Database Unavailable',
                    description=(
                        'This command requires the database, which is currently offline.\n'
                        '\U0001f4a1 Please try again later or contact staff.'
                    ),
                    color=nextcord.Color.red(),
                )
                await safe_send(interaction, embed=embed, ephemeral=True)
                return
            try:
                return await func(self, interaction, *args, **kwargs)
            except commands.CommandOnCooldown as error:
                minutes = int(error.retry_after // 60)
                seconds = int(error.retry_after % 60)
                time_str = f'{minutes}m {seconds}s' if minutes > 0 else f'{seconds}s'
                embed = nextcord.Embed(
                    title='\u23f3 Cooldown',
                    description=f'This command is on cooldown. Try again in **{time_str}**.',
                    color=nextcord.Color.orange(),
                )
                await safe_send(interaction, embed=embed, ephemeral=True)
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

        if count >= 3 and bot and hasattr(bot, 'notifier') and bot.notifier:
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
