"""Guild Settings Service — per-server channel and role configuration with caching."""

from __future__ import annotations

from dataclasses import dataclass, field

import nextcord

from src.database.database import db
from src.utils.logger import get_logger

logger = get_logger('VEKA.guild_settings')


@dataclass
class GuildSettings:
    """Strongly typed guild settings with helper property methods."""

    guild_id: int
    log_channel_id: int | None = None
    staff_channel_id: int | None = None
    alert_channel_id: int | None = None
    public_commands_channel_id: int | None = None
    welcome_channel_id: int | None = None
    radio_channel_id: int | None = None
    leaderboard_channel_id: int | None = None
    marketplace_channel_id: int | None = None
    leaderboard_message_id: int | None = None
    muted_role_id: int | None = None
    honeypot_channel_ids: list[int] = field(default_factory=list)
    warn_mute_threshold: int = 3
    warn_ban_threshold: int = 5
    honeypot_cooldown_seconds: int = 60
    welcome_message_template: str = 'Welcome {user} to {server}!'
    bump_reminder_enabled: bool = False
    welcome_card_enabled: bool = True
    inactivity_dm_enabled: bool = False
    presence_tracking_enabled: bool = False
    inactivity_alerts_enabled: bool = True
    created_at: object | None = None
    updated_at: object | None = None


_OPTIONAL_ID_FIELDS = (
    'log_channel_id',
    'staff_channel_id',
    'alert_channel_id',
    'public_commands_channel_id',
    'welcome_channel_id',
    'radio_channel_id',
    'leaderboard_channel_id',
    'marketplace_channel_id',
    'leaderboard_message_id',
    'muted_role_id',
)


def settings_from_row(row) -> GuildSettings:
    """Build typed settings from an asyncpg record or dictionary."""
    get = row.get
    welcome_card = get('welcome_card_enabled', True)
    return GuildSettings(
        guild_id=row['guild_id'],
        **{name: get(name) for name in _OPTIONAL_ID_FIELDS},
        honeypot_channel_ids=list(get('honeypot_channel_ids') or []),
        warn_mute_threshold=get('warn_mute_threshold') or 3,
        warn_ban_threshold=get('warn_ban_threshold') or 5,
        honeypot_cooldown_seconds=get('honeypot_cooldown_seconds') or 60,
        welcome_message_template=get('welcome_message_template') or 'Welcome {user} to {server}!',
        bump_reminder_enabled=bool(get('bump_reminder_enabled') or False),
        welcome_card_enabled=True if welcome_card is None else bool(welcome_card),
        inactivity_dm_enabled=bool(get('inactivity_dm_enabled') or False),
        presence_tracking_enabled=bool(get('presence_tracking_enabled') or False),
        inactivity_alerts_enabled=get('inactivity_alerts_enabled') is not False,
        created_at=get('created_at'),
        updated_at=get('updated_at'),
    )


# Column names that may be interpolated into UPDATE statements.
_WRITABLE_FIELDS = frozenset(
    {
        *_OPTIONAL_ID_FIELDS,
        'honeypot_channel_ids',
        'warn_mute_threshold',
        'warn_ban_threshold',
        'honeypot_cooldown_seconds',
        'welcome_message_template',
        'bump_reminder_enabled',
        'welcome_card_enabled',
        'inactivity_dm_enabled',
        'presence_tracking_enabled',
        'inactivity_alerts_enabled',
    }
)


class GuildSettingsService:
    """Singleton service for guild settings with in-memory caching."""

    def __init__(self) -> None:
        self._cache: dict[int, GuildSettings] = {}

    async def get_settings(self, guild_id: int) -> GuildSettings:
        """Get guild settings, checking cache first, then DB, then creating defaults."""
        if guild_id in self._cache:
            return self._cache[guild_id]

        row = await db.fetch_one(
            'SELECT * FROM guild_settings WHERE guild_id = $1',
            guild_id,
        )

        if row:
            settings = settings_from_row(row)
        else:
            # Insert and return defaults
            settings = GuildSettings(guild_id=guild_id)
            await db.execute(
                'INSERT INTO guild_settings (guild_id) VALUES ($1) ON CONFLICT (guild_id) DO NOTHING',
                guild_id,
            )

        self._cache[guild_id] = settings
        return settings

    async def update_settings(self, guild_id: int, **kwargs) -> GuildSettings:
        """Update specific fields for a guild and return the refreshed settings."""
        if not kwargs:
            return await self.get_settings(guild_id)

        # Build dynamic SET clause
        set_parts: list[str] = []
        values: list[object] = []
        idx = 1
        for key, value in kwargs.items():
            if key not in _WRITABLE_FIELDS:
                raise ValueError(f'Unknown guild setting: {key}')
            set_parts.append(f'{key} = ${idx}')
            values.append(value)
            idx += 1

        set_parts.append('updated_at = NOW()')
        values.append(guild_id)

        query = f'UPDATE guild_settings SET {", ".join(set_parts)} WHERE guild_id = ${idx}'
        await db.execute(query, *values)

        # Invalidate cache and re-fetch
        self._cache.pop(guild_id, None)
        return await self.get_settings(guild_id)

    def invalidate_cache(self, guild_id: int | None = None) -> None:
        """Clear cache for a single guild or all guilds."""
        if guild_id is not None:
            self._cache.pop(guild_id, None)
        else:
            self._cache.clear()

    async def resolve_channel(self, guild: nextcord.Guild, channel_type: str) -> nextcord.abc.GuildChannel | None:
        """Resolve a channel ID from settings to a Discord channel object."""
        settings = await self.get_settings(guild.id)
        channel_id = getattr(settings, channel_type, None)
        if channel_id is None:
            return None
        return guild.get_channel(channel_id)


# Global singleton
guild_settings_service = GuildSettingsService()
