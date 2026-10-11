"""In-process token buckets keyed by client (single API replica; see AGENTS.md)."""

from __future__ import annotations

import time
from collections.abc import Callable

from src.api.errors import ApiError
from src.utils.ttlcache import TTLDict


class RateLimiter:
    def __init__(self, per_minute: int, clock: Callable[[], float] = time.monotonic) -> None:
        self.capacity = float(per_minute)
        self.rate = per_minute / 60.0
        self._clock = clock
        self._buckets: TTLDict[str, list[float]] = TTLDict(ttl=300, maxsize=50_000, clock=clock)

    def check(self, key: str) -> None:
        now = self._clock()
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = [self.capacity, now]
        tokens = min(self.capacity, bucket[0] + (now - bucket[1]) * self.rate)
        if tokens < 1:
            retry = max(1, int((1 - tokens) / self.rate) + 1)
            self._buckets.set(key, [tokens, now])
            raise ApiError(429, 'rate_limited', 'Too many requests.', headers={'Retry-After': str(retry)})
        self._buckets.set(key, [tokens - 1, now])
