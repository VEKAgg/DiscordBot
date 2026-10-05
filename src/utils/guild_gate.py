"""
Guild-based access control.
Gates commands based on which server the bot is running in.

Both decorators go through ``permission_guard`` so they are enforced on slash commands too
(nextcord ignores ``commands.check`` on application commands).
"""

import logging

import nextcord

from src.config.config import MAIN_GUILD_ID, OWNER_DISCORD_ID
from src.utils.safety import _source_user_and_guild, permission_guard

logger = logging.getLogger('VEKA.guild_gate')


def is_main_guild(guild: nextcord.Guild | None) -> bool:
    """Check if a guild is the main VEKA server."""
    return guild is not None and guild.id == MAIN_GUILD_ID


def _main_server_predicate(source) -> bool:
    _, guild = _source_user_and_guild(source)
    return is_main_guild(guild)


def _owner_in_external_predicate(source) -> bool:
    user, guild = _source_user_and_guild(source)
    if user is None:
        return False
    # Main guild — everyone can use; external guild (or DM) — only the owner.
    return is_main_guild(guild) or user.id == OWNER_DISCORD_ID


def main_server_only():
    """Decorator: command only works in the main guild. Others see 'not available'."""
    return permission_guard(_main_server_predicate, 'This command is only available in the main VEKA server.')


def owner_in_external_only():
    """
    Decorator: In main guild = anyone can use.
    In external guild = only owner (OWNER_DISCORD_ID) can use.
    Others see 'not allowed'.
    """
    return permission_guard(_owner_in_external_predicate, 'This command is not available in this server.')
