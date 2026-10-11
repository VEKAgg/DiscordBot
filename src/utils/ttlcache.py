"""Bounded in-memory dict with per-entry expiry, for cooldowns and short-lived caches.

Plain dicts keyed by user/guild ID grow forever in a long-running bot. ``TTLDict`` drops entries
after their TTL and evicts the least recently set live entries beyond ``maxsize``.
"""

from __future__ import annotations

import heapq
import itertools
import time
from collections import OrderedDict
from collections.abc import Callable, Iterator


class TTLDict[K, V]:
    def __init__(self, ttl: float, maxsize: int = 10_000, clock: Callable[[], float] = time.monotonic) -> None:
        if ttl <= 0 or maxsize <= 0:
            raise ValueError('ttl and maxsize must be positive')
        self.ttl = ttl
        self.maxsize = maxsize
        self._clock = clock
        # key -> (expires, generation, value), in set order (oldest first) for size eviction.
        self._data: OrderedDict[K, tuple[float, int, V]] = OrderedDict()
        # Min-heap of (expires, generation, key); entries whose generation no longer matches are stale.
        # Per-entry TTLs mean set order is not expiry order, so expiry needs its own index.
        self._heap: list[tuple[float, int, K]] = []
        self._gen = itertools.count()

    def _purge(self, now: float) -> None:
        heap = self._heap
        while heap and heap[0][0] <= now:
            _expires, gen, key = heapq.heappop(heap)
            item = self._data.get(key)
            if item is not None and item[1] == gen:
                del self._data[key]
        # Stale heap entries (overwritten/popped keys) are dropped lazily; rebuild if they dominate.
        if len(heap) > 2 * len(self._data) + 64:
            self._heap = [(exp, gen, key) for key, (exp, gen, _) in self._data.items()]
            heapq.heapify(self._heap)

    def get(self, key: K, default: V | None = None) -> V | None:
        item = self._data.get(key)
        if item is None:
            return default
        if item[0] <= self._clock():
            del self._data[key]
            return default
        return item[2]

    def set(self, key: K, value: V, ttl: float | None = None) -> None:
        now = self._clock()
        self._purge(now)
        expires = now + (ttl if ttl is not None else self.ttl)
        gen = next(self._gen)
        self._data.pop(key, None)
        self._data[key] = (expires, gen, value)
        heapq.heappush(self._heap, (expires, gen, key))
        while len(self._data) > self.maxsize:
            self._data.popitem(last=False)

    def pop(self, key: K, default: V | None = None) -> V | None:
        item = self._data.pop(key, None)
        if item is None or item[0] <= self._clock():
            return default
        return item[2]

    def __contains__(self, key: object) -> bool:
        item = self._data.get(key)  # type: ignore[arg-type]
        return item is not None and item[0] > self._clock()

    def __setitem__(self, key: K, value: V) -> None:
        self.set(key, value)

    def __len__(self) -> int:
        self._purge(self._clock())
        return len(self._data)

    def __iter__(self) -> Iterator[K]:
        self._purge(self._clock())
        return iter(list(self._data))

    def clear(self) -> None:
        self._data.clear()
        self._heap.clear()
