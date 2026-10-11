"""Cross-process cache invalidation: the dashboard API writes, the bot listens.

The API sends ``NOTIFY veka_cache, '<kind>:<id>'`` in the same transaction as each write that the bot
caches. This listener holds one dedicated connection with ``LISTEN veka_cache`` and calls the handler
registered for ``kind``. NOTIFY is not durable, so on every (re)connect the listener **reconciles**:
every handler's ``reset`` runs (full cache clear / reload), which heals anything missed while the
connection was down.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import asyncpg

from src.config.config import DATABASE_URL
from src.database.database import clean_dsn

logger = logging.getLogger('VEKA.cache_listener')

CHANNEL = 'veka_cache'


@dataclass
class CacheHandler:
    on_notify: Callable[[str], Awaitable[None] | None]  # called with the id part ('' if none)
    reset: Callable[[], Awaitable[None] | None]  # full invalidation after (re)connect


class CacheListener:
    """Holds the LISTEN connection and applies invalidations **one at a time** from a queue, so a slow
    reload can't be overtaken by an older one. Repeated identical notifications are coalesced. Resets
    (after connect, after a failure, and every ``sweep_seconds``) go through the same queue and are
    retried with backoff until every handler succeeds."""

    RESET = '__reset__'
    MAX_PENDING = 1000  # beyond this, distinct notifications collapse into one full reset

    def __init__(self, dsn: str | None = None, *, retry_max: float = 60.0, sweep_seconds: float = 300.0) -> None:
        self._dsn = dsn
        self._handlers: dict[str, CacheHandler] = {}
        self._conn: asyncpg.Connection | None = None
        self._tasks: list[asyncio.Task] = []
        self._lost = asyncio.Event()
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._pending: set[str] = set()
        self._retry_max = retry_max
        self._sweep_seconds = sweep_seconds
        self.connected = False

    def register(self, kind: str, handler: CacheHandler) -> None:
        self._handlers[kind] = handler

    def enqueue(self, item: str) -> None:
        if item in self._pending:
            return  # coalesce: the queued copy will do the same work
        if len(self._pending) >= self.MAX_PENDING and item != self.RESET:
            item = self.RESET  # bounded memory; a reset covers everything the dropped hints would
            if item in self._pending:
                return
        self._pending.add(item)
        self._queue.put_nowait(item)

    async def _call(self, fn, *args) -> bool:
        try:
            result = fn(*args)
            if asyncio.iscoroutine(result):
                await result
            return True
        except Exception:
            logger.warning('Cache handler failed', exc_info=True)
            return False

    async def handle_payload(self, payload: str) -> bool:
        kind, _, ident = payload.partition(':')
        handler = self._handlers.get(kind)
        if handler is None:
            logger.debug('No cache handler for %r', kind)
            return True
        return await self._call(handler.on_notify, ident)

    async def reconcile(self) -> bool:
        ok = True
        for handler in self._handlers.values():
            ok = await self._call(handler.reset) and ok
        return ok

    async def _worker(self) -> None:
        delay = 1.0
        while True:
            item = await self._queue.get()
            self._pending.discard(item)
            ok = await (self.reconcile() if item == self.RESET else self.handle_payload(item))
            if ok:
                delay = 1.0
                continue
            # Couldn't apply it: the cache may be stale, so retry with a full reset after a backoff.
            await asyncio.sleep(delay)
            delay = min(delay * 2, self._retry_max)
            self.enqueue(self.RESET)

    async def _sweeper(self) -> None:
        while True:
            await asyncio.sleep(self._sweep_seconds)
            self.enqueue(self.RESET)  # heals anything a lost NOTIFY left behind

    def _on_notification(self, _conn, _pid, _channel, payload: str) -> None:
        self.enqueue(payload)

    def _on_termination(self, _conn) -> None:
        self.connected = False
        self._lost.set()

    async def _run(self) -> None:
        delay = 1.0
        while True:
            try:
                self._conn = await asyncpg.connect(clean_dsn(self._dsn or DATABASE_URL))
                self._conn.add_termination_listener(self._on_termination)
                await self._conn.add_listener(CHANNEL, self._on_notification)
                self.connected = True
                self._lost.clear()
                delay = 1.0
                logger.info('Listening for cache invalidations on %s', CHANNEL)
                self.enqueue(self.RESET)  # anything may have changed while disconnected
                await self._lost.wait()
                logger.warning('Cache listener connection lost; reconnecting')
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning('Cache listener connect failed (%s); retrying in %.0fs', type(exc).__name__, delay)
            finally:
                await self._close_conn()
            await asyncio.sleep(delay)
            delay = min(delay * 2, self._retry_max)

    async def _close_conn(self) -> None:
        conn, self._conn = self._conn, None
        self.connected = False
        if conn is not None and not conn.is_closed():
            try:
                await conn.close()
            except Exception:
                pass

    def start(self) -> None:
        if self._tasks and not all(t.done() for t in self._tasks):
            return
        from src.core.lifecycle import spawn

        self._tasks = [
            spawn(self._run(), name='cache_listener'),
            spawn(self._worker(), name='cache_listener:worker'),
            spawn(self._sweeper(), name='cache_listener:sweeper'),
        ]

    def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        self._tasks = []


cache_listener = CacheListener()
