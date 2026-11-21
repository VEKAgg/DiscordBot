"""
Role-Based Access Control (RBAC) System
Resolves a member's access tier from the platform operator registry, guild permissions and
the per-guild access roles configured in ``guild_settings`` (admin/staff/perk role IDs).
"""

import logging
from enum import Enum
from functools import wraps
from typing import Any

import nextcord

from src.services.guild_settings_service import guild_settings_service
from src.services.operators import operators

logger = logging.getLogger('VEKA.security.rbac')


class Role(Enum):
    """Role hierarchy from lowest to highest"""

    USER = 'user'
    PERK = 'perk'
    STAFF = 'staff'
    ADMIN = 'admin'
    OPERATOR = 'operator'


# Role hierarchy (higher index = more permissions)
ROLE_HIERARCHY = [
    Role.USER,
    Role.PERK,
    Role.STAFF,
    Role.ADMIN,
    Role.OPERATOR,
]

# Community features every member can use, plus the paid/supporter set shared by PERK and above.
_BASE_PERMISSIONS = {'quiz', 'networking', 'profile', 'help', 'marketplace', 'portfolio', 'workshops'}
_SUPPORT_PERMISSIONS = {'staff', 'diagnostics'}

# Permission mapping
ROLE_PERMISSIONS = {
    Role.USER: {'quiz', 'networking', 'profile', 'help'},
    Role.PERK: _BASE_PERMISSIONS,
    Role.STAFF: {*_BASE_PERMISSIONS, *_SUPPORT_PERMISSIONS},
    Role.ADMIN: {
        *_BASE_PERMISSIONS,
        *_SUPPORT_PERMISSIONS,
        'admin',
        'config',
        'quiz_add',
        'quiz_delete',
    },
    Role.OPERATOR: {
        # Operators have all permissions
        '*'
    },
}

# Roles that bypass rate limits
COOLDOWN_BYPASS_ROLES = {Role.PERK, Role.STAFF, Role.ADMIN, Role.OPERATOR}


def _member_and_guild(ctx) -> tuple[Any, Any]:
    """Pull ``(member, guild)`` out of a Context, Interaction or SimpleNamespace stand-in."""
    member = getattr(ctx, 'author', None) or getattr(ctx, 'user', None)
    guild = getattr(ctx, 'guild', None)
    return member, guild


def _role_ids(member) -> frozenset[int]:
    try:
        return frozenset(role.id for role in member.roles)
    except Exception:
        return frozenset()


def _has_any_role(member, role_ids) -> bool:
    if not role_ids:
        return False
    return bool(_role_ids(member) & set(role_ids))


def _is_moderator(perms) -> bool:
    """Permission-only staff fallback: moderate/kick/ban members."""
    if perms is None:
        return False
    return bool(
        getattr(perms, 'moderate_members', False)
        or getattr(perms, 'kick_members', False)
        or getattr(perms, 'ban_members', False)
    )


class RBAC:
    """Role-Based Access Control manager"""

    def get_user_role(self, ctx) -> Role:
        """Resolve a role synchronously from the warm guild-settings cache (no I/O).

        A cache miss means the configured roles are unknown, so only permissions decide —
        never more than Discord permissions allow.
        """
        member, guild = _member_and_guild(ctx)
        settings = guild_settings_service.peek(guild.id) if guild is not None else None
        return self._resolve(member, guild, settings)

    async def get_user_role_async(self, ctx) -> Role:
        """Resolve a role with guild settings loaded from the database (preferred from async code)."""
        member, guild = _member_and_guild(ctx)
        settings = None
        if guild is not None:
            try:
                settings = await guild_settings_service.get_settings(guild.id)
            except Exception:
                settings = guild_settings_service.peek(guild.id)
        return self._resolve(member, guild, settings)

    def _resolve(self, member, guild, settings) -> Role:
        """Resolution order: operator → admin → staff → perk → user.

        ``settings`` is None when the guild's configured roles are unknown; then only the
        permission-based rules apply (never a wider grant than permissions allow).
        """
        if member is None:
            return Role.USER

        # 1. Platform operators (Developer Portal team) — the only tier that survives DMs.
        if operators.is_operator(member.id):
            return Role.OPERATOR

        if guild is None:
            return Role.USER

        # 2. Guild owner, Administrator permission or a configured admin role.
        if getattr(guild, 'owner_id', None) == member.id:
            return Role.ADMIN
        perms = getattr(member, 'guild_permissions', None)
        if getattr(perms, 'administrator', False):
            return Role.ADMIN
        if settings is not None and _has_any_role(member, settings.admin_role_ids):
            return Role.ADMIN

        # 3. Configured staff roles; the permission fallback only applies while none are set.
        if settings is not None and settings.staff_role_ids:
            if _has_any_role(member, settings.staff_role_ids):
                return Role.STAFF
        elif _is_moderator(perms):
            return Role.STAFF

        # 4. Configured perk roles (supporter tier: cooldown bypass, supporter footer).
        if settings is not None and _has_any_role(member, settings.perk_role_ids):
            return Role.PERK

        # 5. Everyone else.
        return Role.USER

    def has_permission(self, user_role: Role, permission: str) -> bool:
        """Check if role has specific permission"""
        if user_role == Role.OPERATOR:
            return True

        permissions = ROLE_PERMISSIONS.get(user_role, set())
        return permission in permissions or '*' in permissions

    def has_cooldown_bypass(self, user_role: Role) -> bool:
        """Check if role bypasses rate limits"""
        return user_role in COOLDOWN_BYPASS_ROLES

    def require_role(self, min_role: Role):
        """
        Decorator to require minimum role level

        Usage:
            @require_role(Role.STAFF)
            @commands.command()
            async def warn(self, ctx, member: nextcord.Member):
                pass
        """

        def decorator(func):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                ctx = args[1] if len(args) > 1 else kwargs.get('ctx')

                if ctx:
                    user_role = await self.get_user_role_async(ctx)

                    if ROLE_HIERARCHY.index(user_role) < ROLE_HIERARCHY.index(min_role):
                        msg = f'❌ You need {min_role.value} role or higher to use this command.'
                        if isinstance(ctx, nextcord.Interaction):
                            if ctx.response.is_done():
                                await ctx.followup.send(msg, ephemeral=True)
                            else:
                                await ctx.response.send_message(msg, ephemeral=True)
                        else:
                            await ctx.send(msg)
                        return

                return await func(*args, **kwargs)

            # Marker read by tests/test_permissions.py to prove slash commands are guarded.
            wrapper.__veka_guards__ = [*getattr(func, '__veka_guards__', []), f'role>={min_role.value}']  # type: ignore[attr-defined]
            return wrapper

        return decorator

    def require_permission(self, permission: str):
        """
        Decorator to require specific permission

        Usage:
            @require_permission('marketplace')
            @commands.command()
            async def sell(self, ctx):
                pass
        """

        def decorator(func):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                ctx = args[1] if len(args) > 1 else kwargs.get('ctx')

                if ctx:
                    user_role = await self.get_user_role_async(ctx)

                    if not self.has_permission(user_role, permission):
                        msg = "❌ You don't have permission to use this command."
                        if isinstance(ctx, nextcord.Interaction):
                            if ctx.response.is_done():
                                await ctx.followup.send(msg, ephemeral=True)
                            else:
                                await ctx.response.send_message(msg, ephemeral=True)
                        else:
                            await ctx.send(msg)
                        return

                return await func(*args, **kwargs)

            return wrapper

        return decorator


# Global RBAC instance
rbac = RBAC()


# Convenience decorators
def require_staff():
    """Require staff or higher"""
    return rbac.require_role(Role.STAFF)


def require_admin():
    """Require admin or higher"""
    return rbac.require_role(Role.ADMIN)


def require_operator():
    """Require platform operator (Developer Portal team)"""
    return rbac.require_role(Role.OPERATOR)


# Alias for backward compatibility
require_mod = require_staff
