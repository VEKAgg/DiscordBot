import asyncio
import functools
import logging
from typing import Any, Callable, Coroutine, Optional, Union

import aiohttp
import nextcord
from nextcord.ext import commands

from src.config.config import ADMIN_IDS, OWNER_IDS
from src.core.runtime_state import runtime_state

logger = logging.getLogger('VEKA.safety')


class DatabaseUnavailableError(RuntimeError):
    """Raised when the database is unavailable."""


class ValidationError(ValueError):
    """Raised for invalid user input."""


class ExternalRequestError(RuntimeError):
    """Raised for network or external service issues."""


def is_response_sent(interaction: nextcord.Interaction) -> bool:
    return interaction.response.is_done()


def format_context(source: Any) -> str:
    details = []
    if isinstance(source, commands.Context):
        details.append(f'command={source.command}')
        details.append(f'guild_id={getattr(source.guild, "id", None)}')
        details.append(f'channel_id={getattr(source.channel, "id", None)}')
        details.append(f'user_id={getattr(source.author, "id", None)}')
    elif isinstance(source, nextcord.Interaction):
        details.append(f'command={source.application_command.name if source.application_command else None}')
        details.append(f'guild_id={getattr(source.guild, "id", None)}')
        details.append(f'channel_id={getattr(source.channel, "id", None)}')
        details.append(f'user_id={getattr(source.user, "id", None)}')
    else:
        details.append(f'source={type(source).__name__}')
    return ' | '.join(str(item) for item in details if item is not None)


def map_exception_to_message(error: BaseException) -> str:
    if isinstance(error, DatabaseUnavailableError):
        return 'The database is temporarily unavailable. Please try again later.'
    if isinstance(error, ValidationError):
        return str(error) or 'Invalid input. Please check your command and try again.'
    if isinstance(error, (asyncio.TimeoutError, aiohttp.ClientError)):
        return 'External service unavailable or timed out. Please try again later.'
    if isinstance(error, commands.MissingPermissions):
        return 'You do not have permission to use this command.'
    if isinstance(error, commands.MissingRole):
        return 'You do not have the required role to use this command.'
    if isinstance(error, commands.CommandOnCooldown):
        return f'This command is on cooldown. Try again in {error.retry_after:.1f}s.'
    return 'An internal error occurred while processing your request.'


def _is_admin_user(user: nextcord.abc.User, guild: Optional[nextcord.Guild] = None) -> bool:
    if user is None:
        return False
    if getattr(user, 'id', None) in OWNER_IDS or getattr(user, 'id', None) in ADMIN_IDS:
        return True
    if isinstance(user, nextcord.Member):
        if user.guild_permissions.administrator:
            return True
    elif guild is not None and hasattr(user, 'id'):
        member = guild.get_member(user.id)
        if member and member.guild_permissions.administrator:
            return True
    return False


def admin_only():
    def predicate(ctx_or_interaction):
        if isinstance(ctx_or_interaction, commands.Context):
            return _is_admin_user(ctx_or_interaction.author, ctx_or_interaction.guild)
        if isinstance(ctx_or_interaction, nextcord.Interaction):
            return _is_admin_user(ctx_or_interaction.user, ctx_or_interaction.guild)
        return False

    return commands.check(predicate)


async def safe_send(
    target: Union[commands.Context, nextcord.Interaction],
    content: Optional[str] = None,
    embed: Optional[nextcord.Embed] = None,
    ephemeral: bool = False,
) -> None:
    if isinstance(target, nextcord.Interaction):
        try:
            if is_response_sent(target):
                await target.followup.send(content=content, embed=embed, ephemeral=ephemeral)
            else:
                await target.response.send_message(content=content, embed=embed, ephemeral=ephemeral)
        except Exception as exc:
            logger.error('Failed to send interaction response: %s | %s', exc, format_context(target), exc_info=True)
    elif isinstance(target, commands.Context):
        try:
            await target.send(content=content, embed=embed)
        except Exception as exc:
            logger.error('Failed to send context response: %s | %s', exc, format_context(target), exc_info=True)
    else:
        logger.warning('Safe send called with unsupported target type: %s', type(target).__name__)


def log_error(error: BaseException, source: Any, module: Optional[str] = None) -> None:
    context = format_context(source)
    module_name = f'{module} | ' if module else ''
    logger.error('%sError handling request: %s | %s', module_name, error, context, exc_info=True)


def safe_command(requires_db: bool = False) -> Callable[[Callable[..., Coroutine[Any, Any, Any]]], Callable[..., Coroutine[Any, Any, Any]]]:
    def decorator(func: Callable[..., Coroutine[Any, Any, Any]]):
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any):
            ctx = args[1] if len(args) > 1 else None
            try:
                if requires_db and not runtime_state.db_available:
                    raise DatabaseUnavailableError()
                return await func(*args, **kwargs)
            except commands.CommandError:
                raise
            except Exception as error:
                log_error(error, ctx, module=getattr(func, '__module__', None))
                message = map_exception_to_message(error)
                from src.utils.embeds import error_embed
                embed = error_embed(title="Command Error", description=message, contributor_source=getattr(func, '__module__', None))
                if isinstance(ctx, commands.Context):
                    await safe_send(ctx, embed=embed)
                return None
        return wrapper
    return decorator


def safe_slash_command(requires_db: bool = False) -> Callable[[Callable[..., Coroutine[Any, Any, Any]]], Callable[..., Coroutine[Any, Any, Any]]]:
    def decorator(func: Callable[..., Coroutine[Any, Any, Any]]):
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any):
            interaction = args[1] if len(args) > 1 else None
            try:
                if requires_db and not runtime_state.db_available:
                    raise DatabaseUnavailableError()
                return await func(*args, **kwargs)
            except commands.CommandError:
                raise
            except Exception as error:
                log_error(error, interaction, module=getattr(func, '__module__', None))
                message = map_exception_to_message(error)
                from src.utils.embeds import error_embed
                embed = error_embed(title="Command Error", description=message, contributor_source=getattr(func, '__module__', None))
                if isinstance(interaction, nextcord.Interaction):
                    await safe_send(interaction, embed=embed, ephemeral=True)
                return None
        return wrapper
    return decorator


async def run_safe_task(coro: Coroutine[Any, Any, Any], *, name: Optional[str] = None, logger_obj: Optional[logging.Logger] = None) -> Optional[Any]:
    if logger_obj is None:
        logger_obj = logger
    task_name = name or getattr(coro, '__name__', 'anonymous_task')
    try:
        return await coro
    except Exception as error:
        logger_obj.error('Background task failed: %s | %s', task_name, error, exc_info=True)
        return None


def safe_background_task(name: Optional[str] = None) -> Callable[[Callable[..., Coroutine[Any, Any, Any]]], Callable[..., Coroutine[Any, Any, Any]]]:
    def decorator(func: Callable[..., Coroutine[Any, Any, Any]]):
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any):
            return await run_safe_task(func(*args, **kwargs), name=name or func.__name__)
        return wrapper
    return decorator
