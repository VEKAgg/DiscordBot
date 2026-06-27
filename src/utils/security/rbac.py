"""
Role-Based Access Control (RBAC) System
Manages permissions based on Discord roles
"""

import logging
from enum import Enum
from functools import wraps

logger = logging.getLogger('VEKA.security.rbac')


class Role(Enum):
    """Role hierarchy from lowest to highest"""

    USER = 'user'
    VERIFIED = 'verified'
    MODERATOR = 'moderator'
    ADMIN = 'admin'
    OWNER = 'owner'


# Role hierarchy (higher index = more permissions)
ROLE_HIERARCHY = [Role.USER, Role.VERIFIED, Role.MODERATOR, Role.ADMIN, Role.OWNER]

# Permission mapping
ROLE_PERMISSIONS = {
    Role.USER: {'quiz', 'networking', 'profile', 'help'},
    Role.VERIFIED: {'quiz', 'networking', 'profile', 'help', 'marketplace', 'portfolio', 'workshops'},
    Role.MODERATOR: {
        'quiz',
        'networking',
        'profile',
        'help',
        'marketplace',
        'portfolio',
        'workshops',
        'kick',
        'ban',
        'mute',
        'warn',
        'clear',
    },
    Role.ADMIN: {
        'quiz',
        'networking',
        'profile',
        'help',
        'marketplace',
        'portfolio',
        'workshops',
        'kick',
        'ban',
        'mute',
        'warn',
        'clear',
        'admin',
        'config',
        'quiz_add',
        'quiz_delete',
    },
    Role.OWNER: {
        # Owner has all permissions
        '*'
    },
}


class RBAC:
    """Role-Based Access Control manager"""

    def __init__(self):
        self.role_mappings = {
            # Discord role name -> Internal role
            'everyone': Role.USER,
            'verified': Role.VERIFIED,
            'mod': Role.MODERATOR,
            'moderator': Role.MODERATOR,
            'admin': Role.ADMIN,
            'administrator': Role.ADMIN,
            'owner': Role.OWNER,
        }

    def get_user_role(self, ctx) -> Role:
        """
        Determine user's role from Discord context

        Priority:
        1. Guild owner -> OWNER
        2. Administrator permission -> ADMIN
        3. Specific roles -> MODERATOR, VERIFIED, etc.
        4. Default -> USER
        """
        if not ctx.guild:
            return Role.USER

        member = ctx.author

        # Check if guild owner
        if ctx.guild.owner_id == member.id:
            return Role.OWNER

        # Check administrator permission
        if member.guild_permissions.administrator:
            return Role.ADMIN

        # Check roles
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
        if user_role == Role.OWNER:
            return True

        permissions = ROLE_PERMISSIONS.get(user_role, set())
        return permission in permissions or '*' in permissions

    def require_role(self, min_role: Role):
        """
        Decorator to require minimum role level

        Usage:
            @require_role(Role.MODERATOR)
            @commands.command()
            async def kick(self, ctx, member: nextcord.Member):
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
def require_mod():
    """Require moderator or higher"""
    return rbac.require_role(Role.MODERATOR)


def require_admin():
    """Require admin or higher"""
    return rbac.require_role(Role.ADMIN)


def require_verified():
    """Require verified or higher"""
    return rbac.require_role(Role.VERIFIED)
