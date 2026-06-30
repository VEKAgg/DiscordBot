"""
Role-Based Access Control (RBAC) System
Manages permissions based on Discord roles
"""

import logging
from enum import Enum
from functools import wraps

from src.config.config import (
    ACTIVE_PRO_IDS,
    ADMIN_IDS,
    DONATOR_IDS,
    FOUNDER_IDS,
    INTERN_IDS,
    OWNER_IDS,
    STAFF_IDS,
)

logger = logging.getLogger('VEKA.security.rbac')


class Role(Enum):
    """Role hierarchy from lowest to highest"""

    USER = 'user'
    VERIFIED = 'verified'
    INTERN = 'intern'
    DONATOR = 'donator'
    ACTIVE_PRO = 'active_pro'
    STAFF = 'staff'
    ADMIN = 'admin'
    FOUNDER = 'founder'


# Role hierarchy (higher index = more permissions)
ROLE_HIERARCHY = [
    Role.USER,
    Role.VERIFIED,
    Role.INTERN,
    Role.DONATOR,
    Role.ACTIVE_PRO,
    Role.STAFF,
    Role.ADMIN,
    Role.FOUNDER,
]

# Permission mapping
ROLE_PERMISSIONS = {
    Role.USER: {'quiz', 'networking', 'profile', 'help'},
    Role.VERIFIED: {'quiz', 'networking', 'profile', 'help', 'marketplace', 'portfolio', 'workshops'},
    Role.INTERN: {'quiz', 'networking', 'profile', 'help', 'marketplace', 'portfolio', 'workshops'},
    Role.DONATOR: {'quiz', 'networking', 'profile', 'help', 'marketplace', 'portfolio', 'workshops'},
    Role.ACTIVE_PRO: {'quiz', 'networking', 'profile', 'help', 'marketplace', 'portfolio', 'workshops'},
    Role.STAFF: {
        'quiz',
        'networking',
        'profile',
        'help',
        'marketplace',
        'portfolio',
        'workshops',
        'staff',
        'diagnostics',
    },
    Role.ADMIN: {
        'quiz',
        'networking',
        'profile',
        'help',
        'marketplace',
        'portfolio',
        'workshops',
        'staff',
        'diagnostics',
        'admin',
        'config',
        'quiz_add',
        'quiz_delete',
    },
    Role.FOUNDER: {
        # Founder has all permissions
        '*'
    },
}

# Roles that bypass rate limits
COOLDOWN_BYPASS_ROLES = {Role.INTERN, Role.DONATOR, Role.ACTIVE_PRO, Role.STAFF, Role.ADMIN, Role.FOUNDER}


class RBAC:
    """Role-Based Access Control manager"""

    def __init__(self):
        self.role_mappings = {
            'everyone': Role.USER,
            'verified': Role.VERIFIED,
            'intern': Role.INTERN,
            'donator': Role.DONATOR,
            'active pro': Role.ACTIVE_PRO,
            'active_pro': Role.ACTIVE_PRO,
            'staff': Role.STAFF,
            'mod': Role.STAFF,
            'moderator': Role.STAFF,
            'admin': Role.ADMIN,
            'administrator': Role.ADMIN,
            'founder': Role.FOUNDER,
            'owner': Role.FOUNDER,
        }

    def _check_id_lists(self, user_id: int) -> Role | None:
        """Check if user ID is in any of the env-based ID lists. Returns highest matching role."""
        if user_id in FOUNDER_IDS or user_id in OWNER_IDS:
            return Role.FOUNDER
        if user_id in ADMIN_IDS:
            return Role.ADMIN
        if user_id in STAFF_IDS:
            return Role.STAFF
        if user_id in ACTIVE_PRO_IDS:
            return Role.ACTIVE_PRO
        if user_id in DONATOR_IDS:
            return Role.DONATOR
        if user_id in INTERN_IDS:
            return Role.INTERN
        return None

    def get_user_role(self, ctx) -> Role:
        """
        Determine user's role from Discord context

        Priority:
        1. .env ID lists (FOUNDER_IDS, OWNER_IDS, etc.)
        2. Guild owner -> FOUNDER
        3. Administrator permission -> ADMIN
        4. Discord role name mapping -> highest matching role
        5. Default -> USER
        """
        if not ctx.guild:
            # For DMs, check ID lists only
            user = ctx.author if hasattr(ctx, 'author') else ctx.user
            id_role = self._check_id_lists(user.id)
            return id_role or Role.USER

        member = ctx.author if hasattr(ctx, 'author') else ctx.user

        # 1. Check .env ID lists first
        id_role = self._check_id_lists(member.id)
        if id_role:
            return id_role

        # 2. Check if guild owner
        if ctx.guild.owner_id == member.id:
            return Role.FOUNDER

        # 3. Check administrator permission
        if member.guild_permissions.administrator:
            return Role.ADMIN

        # 4. Check Discord role names
        user_role = Role.USER
        for discord_role in member.roles:
            role_name = discord_role.name.lower()
            if role_name in self.role_mappings:
                mapped_role = self.role_mappings[role_name]
                # Keep highest role
                if ROLE_HIERARCHY.index(mapped_role) > ROLE_HIERARCHY.index(user_role):
                    user_role = mapped_role

        return user_role

    def has_permission(self, user_role: Role, permission: str) -> bool:
        """Check if role has specific permission"""
        if user_role == Role.FOUNDER:
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
                    user_role = self.get_user_role(ctx)

                    if ROLE_HIERARCHY.index(user_role) < ROLE_HIERARCHY.index(min_role):
                        await ctx.send(f'❌ You need {min_role.value} role or higher to use this command.')
                        return

                return await func(*args, **kwargs)

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
                    user_role = self.get_user_role(ctx)

                    if not self.has_permission(user_role, permission):
                        await ctx.send("❌ You don't have permission to use this command.")
                        return

                return await func(*args, **kwargs)

            return wrapper

        return decorator


# Global RBAC instance
rbac = RBAC()


# Convenience decorators
def require_verified():
    """Require verified or higher"""
    return rbac.require_role(Role.VERIFIED)


def require_staff():
    """Require staff or higher"""
    return rbac.require_role(Role.STAFF)


def require_admin():
    """Require admin or higher"""
    return rbac.require_role(Role.ADMIN)


def require_founder():
    """Require founder role"""
    return rbac.require_role(Role.FOUNDER)


# Alias for backward compatibility
require_mod = require_staff
