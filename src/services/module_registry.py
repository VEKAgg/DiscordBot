"""Single source of truth for per-server feature switches (no Discord dependency)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Module:
    id: str
    label: str
    description: str
    category: str
    commands: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()
    locked: bool = False
    permissions: tuple[str, ...] = ()


MODULES = (
    Module('core', 'Core', 'Help, health, maintenance and bot connectivity.', 'utility', locked=True),
    Module('settings', 'Settings', 'Server configuration.', 'utility', ('setup',), locked=True),
    Module('privacy', 'Privacy', 'Member consent and data deletion.', 'utility', ('privacy',), locked=True),
    Module(
        'activity',
        'Activity',
        'Message, command and voice activity accounting. Presence requires separate consent.',
        'engagement',
        ('activity',),
    ),
    Module('leveling', 'Leveling', 'XP awards and member levels.', 'engagement', ('level', 'rank'), ('activity',)),
    Module(
        'leaderboards',
        'Leaderboards',
        'Server rankings, scheduled boards and seasons.',
        'engagement',
        ('leaderboard', 'setupleaderboard', 'most', 'stats', 'serverstats'),
        ('activity',),
    ),
    Module(
        'activity_roles',
        'Activity roles',
        'Assign roles based on server activity.',
        'engagement',
        requires=('activity', 'leveling'),
        permissions=('MANAGE_ROLES',),
    ),
    Module('welcome', 'Welcome', 'Welcome new members.', 'engagement', ('welcome',)),
    Module(
        'honeypot',
        'Honeypots',
        'Trap-channel protection.',
        'moderation',
        ('honeypot', 'logging'),
        permissions=('BAN_MEMBERS', 'MODERATE_MEMBERS', 'MANAGE_ROLES', 'MANAGE_MESSAGES'),
    ),
    Module(
        'moderation',
        'Moderation',
        'Warnings and moderation actions.',
        'moderation',
        ('warn', 'warnings', 'clearwarnings', 'modstats', 'admin panic', 'admin lockdown'),
        permissions=('BAN_MEMBERS', 'KICK_MEMBERS', 'MODERATE_MEMBERS'),
    ),
    Module(
        'massunban',
        'Mass unban',
        'Preview and run bulk unban jobs.',
        'moderation',
        ('massunban',),
        permissions=('BAN_MEMBERS',),
    ),
    Module('feeds', 'Feeds', 'RSS subscriptions and delivery.', 'community', ('feed', 'resource')),
    Module(
        'marketplace',
        'Marketplace',
        'Listings, reviews, offers and forum ingestion.',
        'community',
        ('marketplace', 'bump', 'featured', 'marketstats'),
    ),
    Module('mentorship', 'Mentorship', 'Mentor registrations and engagements.', 'community', ('mentor',)),
    Module(
        'networking',
        'Networking',
        'Profiles, directory and member connections.',
        'community',
        ('profile', 'connect', 'directory'),
    ),
    Module('portfolio', 'Portfolio', 'Member projects.', 'community', ('portfolio',)),
    Module(
        'notifications',
        'Notifications',
        'Staff broadcasts and squad pings.',
        'utility',
        ('admin broadcast', 'admin pingsquad'),
    ),
    Module(
        'export', 'Export', 'Export server messages.', 'utility', ('exportchat',), permissions=('READ_MESSAGE_HISTORY',)
    ),
)
REGISTRY = {m.id: m for m in MODULES}
COMMAND_MODULES = {command: m.id for m in MODULES for command in m.commands}
# Prefix aliases and delegated helpers use their feature cog's callback ownership.
COG_MODULES = {
    'src.cogs.admin.welcome': 'welcome',
    'src.cogs.admin.notifications': 'notifications',
    'src.cogs.admin.honeypot': 'honeypot',
    'src.cogs.admin.moderation': 'moderation',
    'src.cogs.admin.massunban': 'massunban',
    'src.cogs.resources.feeds': 'feeds',
    'src.cogs.marketplace.marketplace': 'marketplace',
    'src.cogs.marketplace.reviews': 'marketplace',
    'src.cogs.marketplace_enhanced': 'marketplace',
    'src.cogs.mentorship': 'mentorship',
    'src.cogs.networking.networking': 'networking',
    'src.cogs.portfolio.portfolio_manager': 'portfolio',
    'src.cogs.external.export': 'export',
    'src.cogs.stats': 'leaderboards',
}
PERMISSION_BITS = {
    'KICK_MEMBERS': 1 << 1,
    'BAN_MEMBERS': 1 << 2,
    'VIEW_CHANNEL': 1 << 10,
    'SEND_MESSAGES': 1 << 11,
    'MANAGE_MESSAGES': 1 << 13,
    'EMBED_LINKS': 1 << 14,
    'ATTACH_FILES': 1 << 15,
    'READ_MESSAGE_HISTORY': 1 << 16,
    'MANAGE_ROLES': 1 << 28,
    'MODERATE_MEMBERS': 1 << 40,
    'MANAGE_CHANNELS': 1 << 4,  # /admin panic and /admin lockdown edit channel permission overwrites.
    'CREATE_PUBLIC_THREADS': 1 << 35,
    'SEND_MESSAGES_IN_THREADS': 1 << 38,
}
# No Administrator: baseline replies plus permissions used by default-on feature modules.
_BASELINE_PERMISSIONS = (
    'VIEW_CHANNEL',
    'SEND_MESSAGES',
    'EMBED_LINKS',
    'ATTACH_FILES',
    'READ_MESSAGE_HISTORY',
    'CREATE_PUBLIC_THREADS',
    'SEND_MESSAGES_IN_THREADS',
    'MANAGE_CHANNELS',
)
INVITE_PERMISSIONS = sum(
    PERMISSION_BITS[p] for p in set(_BASELINE_PERMISSIONS) | {p for m in MODULES for p in m.permissions}
)


def serialize(guild_id: int, row) -> dict:
    disabled = set(row['disabled'] if row else [])
    return {
        'guild_id': str(guild_id),
        'version': str(row['version'] if row else 0),
        'modules': [
            {
                'id': m.id,
                'label': m.label,
                'description': m.description,
                'category': m.category,
                'commands': list(m.commands),
                'requires': list(m.requires),
                'locked': m.locked,
                'default_enabled': True,
                'stored_enabled': m.locked or m.id not in disabled,
                'enabled': m.locked
                or (m.id not in disabled and all(d in REGISTRY and d not in disabled for d in m.requires)),
                'effective_enabled': m.locked
                or (m.id not in disabled and all(d in REGISTRY and d not in disabled for d in m.requires)),
            }
            for m in MODULES
        ],
    }
