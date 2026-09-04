"""Guild Settings Service — per-server channel and role configuration with caching."""

from __future__ import annotations

from dataclasses import dataclass, field

import nextcord

from src.database.database import db
from src.utils.logger import get_logger

logger = get_logger('VEKA.guild_settings')

# Default values for fallback when no guild-specific setting exists.
# These mirror the hardcoded constants in config.py and will be used as
# fallbacks until a guild configures its own channels via /setup.
_DEFAULTS: dict[str, int | None] = {}


def _load_defaults() -> dict[str, int | None]:
    """Lazy-load defaults from config to avoid circular imports at module level."""
    if _DEFAULTS:
        return _DEFAULTS
    from src.config.config import (
        LEADERBOARD_CHANNEL_ID,
        LOGS_CHANNEL_ID,
        PUBLIC_BOT_COMMANDS_CHANNEL_ID,
        STAFF_CHANNEL_ID,
    )

    _DEFAULTS.update(
        {
            'log_channel_id': LOGS_CHANNEL_ID,
            'staff_channel_id': STAFF_CHANNEL_ID,
            'public_commands_channel_id': PUBLIC_BOT_COMMANDS_CHANNEL_ID,
            'leaderboard_channel_id': LEADERBOARD_CHANNEL_ID,
        }
    )
    return _DEFAULTS


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
    muted_role_id: int | None = None
    honeypot_channel_ids: list[int] = field(default_factory=list)
    created_at: object | None = None
    updated_at: object | None = None

    def get_resolved(self, field_name: str) -> int | None:
        """Get a field value, falling back to config defaults if not set."""
        val = getattr(self, field_name, None)
        if val is not None:
            return val
        defaults = _load_defaults()
        return defaults.get(field_name)


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
            settings = GuildSettings(
                guild_id=row['guild_id'],
                log_channel_id=row['log_channel_id'],
                staff_channel_id=row['staff_channel_id'],
                alert_channel_id=row['alert_channel_id'],
                public_commands_channel_id=row['public_commands_channel_id'],
                welcome_channel_id=row['welcome_channel_id'],
                radio_channel_id=row['radio_channel_id'],
                leaderboard_channel_id=row['leaderboard_channel_id'],
                muted_role_id=row['muted_role_id'],
                honeypot_channel_ids=list(row['honeypot_channel_ids']) if row['honeypot_channel_ids'] else [],
                created_at=row['created_at'],
                updated_at=row['updated_at'],
            )
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
            if key == 'honeypot_channel_ids':
                set_parts.append(f'{key} = ${idx}')
                values.append(value)
            else:
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
        channel_id = settings.get_resolved(channel_type)
        if channel_id is None:
            return None
        return guild.get_channel(channel_id)


# Global singleton
guild_settings_service = GuildSettingsService()
