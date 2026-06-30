"""
Guild-based access control.
Gates commands based on which server the bot is running in.
"""

import logging

import nextcord
from nextcord.ext import commands

from src.config.config import MAIN_GUILD_ID, OWNER_DISCORD_ID

logger = logging.getLogger('VEKA.guild_gate')


def is_main_guild(guild: nextcord.Guild | None) -> bool:
    """Check if a guild is the main VEKA server."""
    return guild is not None and guild.id == MAIN_GUILD_ID


def main_server_only():
    """Decorator: command only works in the main guild. Others see 'not available'."""

    def predicate(ctx_or_interaction):
        if isinstance(ctx_or_interaction, commands.Context):
            guild = ctx_or_interaction.guild
        elif isinstance(ctx_or_interaction, nextcord.Interaction):
            guild = ctx_or_interaction.guild
        else:
            return False

        if is_main_guild(guild):
            return True

        # Not in main guild — send denial
        msg = 'This command is only available in the main VEKA server.'
        try:
            if isinstance(ctx_or_interaction, commands.Context):
                import asyncio

                if asyncio.get_running_loop().is_running():
                    asyncio.ensure_future(ctx_or_interaction.send(msg))
            elif isinstance(ctx_or_interaction, nextcord.Interaction):
                if not ctx_or_interaction.response.is_done():
                    import asyncio

                    asyncio.ensure_future(ctx_or_interaction.response.send_message(msg, ephemeral=True))
        except Exception:
            pass
        return False

    return commands.check(predicate)


def owner_in_external_only():
    """
    Decorator: In main guild = anyone can use.
    In external guild = only owner (OWNER_DISCORD_ID) can use.
    Others see 'not allowed'.
    """

    def predicate(ctx_or_interaction):
        guild: nextcord.Guild | None = None
        user: nextcord.User | nextcord.Member | None = None
        if isinstance(ctx_or_interaction, commands.Context):
            guild = ctx_or_interaction.guild
            user = ctx_or_interaction.author
        elif isinstance(ctx_or_interaction, nextcord.Interaction):
            guild = ctx_or_interaction.guild
            user = ctx_or_interaction.user
        else:
            return False
        if user is None:
            return False

        # Main guild — everyone can use
        if is_main_guild(guild):
            return True

        # External guild — only owner
        if user.id == OWNER_DISCORD_ID:
            return True

        # Not owner in external guild — deny
        msg = 'This command is not available in this server.'
        try:
            if isinstance(ctx_or_interaction, commands.Context):
                import asyncio

                if asyncio.get_running_loop().is_running():
                    asyncio.ensure_future(ctx_or_interaction.send(msg))
            elif isinstance(ctx_or_interaction, nextcord.Interaction):
                if not ctx_or_interaction.response.is_done():
                    import asyncio

                    asyncio.ensure_future(ctx_or_interaction.response.send_message(msg, ephemeral=True))
        except Exception:
            pass
        return False

    return commands.check(predicate)
