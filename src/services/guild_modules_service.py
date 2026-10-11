"""Bot-side bounded module cache. Unknown states fail closed; known states survive outages."""

import time

from src.database.database import db
from src.services.module_registry import REGISTRY
from src.utils.safety import DatabaseUnavailableError


class GuildModulesService:
    def __init__(self) -> None:
        self._cache: dict[int, tuple[float, frozenset[str]]] = {}
        self._invalid: set[int] = set()

    def invalidate_cache(self, guild_id: int | None = None) -> None:
        # Retain last-known switches for outages, but force a refresh on next use.
        if guild_id is None:
            self._invalid.update(self._cache)
        elif guild_id in self._cache:
            self._invalid.add(guild_id)

    async def enabled(self, guild_id: int, module: str, *, dependencies: bool = True) -> bool | None:
        """True/False is known policy; None is unavailable policy (automation must fail closed)."""
        spec = REGISTRY[module]
        if spec.locked:
            return True
        cached = self._cache.get(guild_id)
        if cached is None or guild_id in self._invalid or time.monotonic() - cached[0] >= 60:
            try:
                row = await db.fetch_one('SELECT disabled FROM guild_modules WHERE guild_id = $1', guild_id)
            except DatabaseUnavailableError:
                if cached is None:
                    return None
            else:
                cached = (time.monotonic(), frozenset(row['disabled'] if row else []))
                if len(self._cache) >= 10000 and guild_id not in self._cache:
                    oldest = min(self._cache, key=lambda k: self._cache[k][0])
                    del self._cache[oldest]
                    self._invalid.discard(oldest)
                self._cache[guild_id] = cached
                self._invalid.discard(guild_id)
        if cached is None or module in cached[1]:
            return False
        if dependencies:
            for dep in spec.requires:
                if not await self.enabled(guild_id, dep):
                    return False
        return True


guild_modules_service = GuildModulesService()
