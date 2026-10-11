"""Checks the bot applies at the moment it assigns a punitive role (honeypot role action, auto-mute).

Configuration-time validation (``/setup``, dashboard) can go stale: a role that was safe when chosen may
later gain Administrator or be moved above the bot. So the bot re-validates on every assignment and
refuses instead of escalating someone's permissions.
"""

from __future__ import annotations

import nextcord


def punitive_role_problem(role: nextcord.Role | None, guild: nextcord.Guild) -> str | None:
    """Why ``role`` must not be assigned as a punishment right now, or None if it's safe."""
    if role is None:
        return 'role not found'
    if role.is_default() or role.managed:
        return 'role is @everyone or integration-managed'
    p = role.permissions
    if (
        p.administrator
        or p.manage_guild
        or p.manage_roles
        or p.manage_channels
        or p.ban_members
        or p.kick_members
        or p.moderate_members
    ):
        return 'role has moderation or admin permissions'
    me = guild.me
    if me is None or role >= me.top_role:
        return "role is not below the bot's highest role"
    return None
