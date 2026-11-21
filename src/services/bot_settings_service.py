"""Bot-wide (platform scope) settings stored in the ``bot_settings`` table.

Only the operator alert channel lives here today; per-server feature channels stay in
``guild_settings``. Reads are cached for five minutes and the cache entry is dropped on write,
so a ``/operator alerts`` change is visible immediately.
"""

from __future__ import annotations

import json
import time

from src.database.database import db
from src.utils.logger import get_logger

logger = get_logger('VEKA.bot_settings')

OPERATOR_ALERT_CHANNEL_KEY = 'operator_alert_channel_id'
_CACHE_TTL_SECONDS = 300.0


class BotSettingsService:
    """Singleton service for bot-wide settings with a short-lived in-memory cache."""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, object]] = {}

    async def _get(self, key: str):
        cached = self._cache.get(key)
        if cached is not None and time.monotonic() - cached[0] < _CACHE_TTL_SECONDS:
            return cached[1]
        try:
            row = await db.fetch_one('SELECT value FROM bot_settings WHERE key = $1', key)
        except Exception as exc:
            # Degraded: keep serving the last value we managed to read.
            logger.warning('Failed to read bot setting %s: %s', key, exc)
            return cached[1] if cached is not None else None
        value = row['value'] if row else None
        self._cache[key] = (time.monotonic(), value)
        return value

    async def _put(self, key: str, value, updated_by: int | None) -> None:
        await db.execute(
            'INSERT INTO bot_settings (key, value, updated_by) VALUES ($1, $2::jsonb, $3) '
            'ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now(), '
            'updated_by = EXCLUDED.updated_by',
            key,
            json.dumps(value),
            updated_by,
        )
        self.invalidate(key)

    async def get_operator_alert_channel_id(self) -> int | None:
        """Channel the bot posts platform-wide operational alerts to (None = not configured)."""
        value = await self._get(OPERATOR_ALERT_CHANNEL_KEY)
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            logger.warning('Ignoring malformed operator alert channel value: %r', value)
            return None

    async def set_operator_alert_channel_id(self, channel_id: int, updated_by: int | None = None) -> None:
        await self._put(OPERATOR_ALERT_CHANNEL_KEY, channel_id, updated_by)

    async def clear_operator_alert_channel_id(self) -> None:
        try:
            await db.execute('DELETE FROM bot_settings WHERE key = $1', OPERATOR_ALERT_CHANNEL_KEY)
        except Exception as exc:
            logger.warning('Failed to clear operator alert channel: %s', exc)
            raise
        self.invalidate(OPERATOR_ALERT_CHANNEL_KEY)

    def invalidate(self, key: str | None = None) -> None:
        """Drop one cached setting, or the whole cache."""
        if key is not None:
            self._cache.pop(key, None)
        else:
            self._cache.clear()


# Global singleton
bot_settings_service = BotSettingsService()
