"""Global guards for both nextcord command surfaces."""

from src.services.guild_modules_service import guild_modules_service
from src.services.module_registry import COG_MODULES, COMMAND_MODULES
from src.utils.safety import AppPermissionDenied, DatabaseUnavailableError, PermissionDenied

MESSAGE = 'This feature is turned off in this server by its admins.'


def command_module(command) -> str | None:
    callback = getattr(command, 'callback', None)
    root = command
    parent = getattr(root, 'parent_cmd', None) or getattr(root, 'parent', None)
    while parent is not None:
        root = parent
        parent = getattr(root, 'parent_cmd', None) or getattr(root, 'parent', None)
    name = getattr(root, 'name', '')
    return (
        COMMAND_MODULES.get(getattr(command, 'qualified_name', ''))
        or COMMAND_MODULES.get(name)
        or COG_MODULES.get(getattr(callback, '__module__', ''))
    )


async def module_check(target) -> bool:
    guild = getattr(target, 'guild', None)
    command = getattr(target, 'application_command', None) or getattr(target, 'command', None)
    module = command_module(command)
    if guild is None or module is None:
        return True
    enabled = await guild_modules_service.enabled(guild.id, module)
    if enabled is None:
        raise DatabaseUnavailableError('Module configuration is temporarily unavailable.')
    if enabled:
        return True
    if getattr(target, 'application_command', None) is not None:
        raise AppPermissionDenied(MESSAGE)
    raise PermissionDenied(MESSAGE)


def register_module_checks(bot) -> None:
    bot.add_check(module_check)
    bot.add_application_command_check(module_check)
