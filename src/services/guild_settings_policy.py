"""What each per-guild setting is and which values are valid — shared by /setup and the dashboard API.

Channel types are nextcord ``ChannelType`` names (as stored in ``bot_guild_snapshot.channels[].type``).
"""

from __future__ import annotations

# key -> (display name, guild_settings column, description)
CHANNEL_SETTINGS: dict[str, tuple[str, str, str]] = {
    'log': ('Log Channel', 'log_channel_id', 'Moderation and audit log channel'),
    'staff': ('Staff Channel', 'staff_channel_id', 'Staff discussion channel'),
    'alert': ('Alert Channel', 'alert_channel_id', 'Bot operational alerts channel'),
    'commands': ('Commands Channel', 'public_commands_channel_id', 'Public bot commands channel'),
    'welcome': ('Welcome Channel', 'welcome_channel_id', 'New member welcome channel'),
    'leaderboard': ('Leaderboard Channel', 'leaderboard_channel_id', 'Auto-updating leaderboard channel'),
    'marketplace': ('Marketplace Channel', 'marketplace_channel_id', 'Where new marketplace listings are posted'),
}

ROLE_SETTINGS: dict[str, tuple[str, str, str]] = {
    'muted': ('Muted Role', 'muted_role_id', 'Role assigned to muted users'),
}

TOGGLE_SETTINGS: dict[str, tuple[str, str, str]] = {
    'inactivity_alerts': (
        'Inactivity Alerts',
        'inactivity_alerts_enabled',
        'Daily digest of inactive members in the log channel (on by default)',
    ),
    'inactivity_dms': (
        'Inactivity DMs',
        'inactivity_dm_enabled',
        '"We miss you" DMs to members inactive for a month (off by default; max 25/day)',
    ),
    'bump_reminder': (
        'Daily Bump Reminder',
        'bump_reminder_enabled',
        'Daily reminder in the configured commands channel (off by default)',
    ),
    'welcome_cards': ('Welcome Cards', 'welcome_card_enabled', 'Render an image card for each new member'),
    'presence_tracking': (
        'Activity Tracking',
        'presence_tracking_enabled',
        'Track games, coding apps and streaming time for stats (members can /privacy optout; no music)',
    ),
}

TEXT_TYPES: tuple[str, ...] = ('text', 'news')
CHANNEL_TYPES: dict[str, tuple[str, ...]] = {
    'marketplace': (*TEXT_TYPES, 'forum'),
}

# Numeric settings: column -> (min, max)
NUMBER_SETTINGS: dict[str, tuple[int, int]] = {
    'warn_mute_threshold': (1, 20),
    'warn_ban_threshold': (1, 50),
    'honeypot_cooldown_seconds': (0, 3600),
}
NUMBER_LABELS = {
    'warn_mute_threshold': ('Warnings before mute', 'Active warning count that triggers a mute.'),
    'warn_ban_threshold': (
        'Warnings before ban',
        'Active warning count that triggers a ban; at least the mute threshold.',
    ),
    'honeypot_cooldown_seconds': ('Honeypot cooldown', 'Seconds between repeated triggers by the same member.'),
}
WELCOME_TEMPLATE_MAX = 1000


TOGGLE_MODULES = {
    'inactivity_alerts': 'activity',
    'inactivity_dms': 'activity',
    'bump_reminder': 'notifications',
    'welcome_cards': 'welcome',
    'presence_tracking': 'activity',
}


def settings_schema() -> dict:
    """Public UI metadata from the same policy used to validate writes."""
    return {
        'channels': [
            {'key': key, 'label': label, 'description': description, 'types': list(allowed_channel_types(key))}
            for key, (label, _column, description) in CHANNEL_SETTINGS.items()
        ],
        'roles': [
            {'key': key, 'label': label, 'description': description}
            for key, (label, _column, description) in ROLE_SETTINGS.items()
        ],
        'toggles': [
            {'key': key, 'label': label, 'description': description, 'module': TOGGLE_MODULES[key]}
            for key, (label, _column, description) in TOGGLE_SETTINGS.items()
        ],
        'numbers': [
            {
                'key': key,
                'label': NUMBER_LABELS[key][0],
                'description': NUMBER_LABELS[key][1],
                'min': bounds[0],
                'max': bounds[1],
            }
            for key, bounds in NUMBER_SETTINGS.items()
        ],
        'welcome_template_max': WELCOME_TEMPLATE_MAX,
    }


def allowed_channel_types(setting_key: str) -> tuple[str, ...]:
    return CHANNEL_TYPES.get(setting_key, TEXT_TYPES)


def channel_type_error(setting_key: str, channel_type: str) -> str | None:
    allowed = allowed_channel_types(setting_key)
    if channel_type in allowed:
        return None
    names = ', '.join(t.replace('_', ' ') for t in allowed)
    return f'**{CHANNEL_SETTINGS[setting_key][0]}** must be one of: {names}.'
