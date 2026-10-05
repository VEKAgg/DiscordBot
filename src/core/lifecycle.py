"""Cog lifecycle helpers for nextcord.

nextcord (unlike discord.py) never calls ``Cog.cog_load`` and calls ``cog_unload`` synchronously,
so async setup placed there silently never ran (audit H-01). Instead, cogs define::

    async def cog_ready(self) -> None: ...

which ``run_cog_ready_hooks`` calls after the database is initialised in ``on_ready`` (and again for
a freshly reloaded cog). A hook that completes is never run again for that instance; a hook that
raises is retried with exponential backoff the next time ``run_cog_ready_hooks`` is called (the DB
health check calls it every tick while the database is up), so a hook that hit a DB outage at boot
still runs once the database recovers. Hooks must therefore raise — not just log — when they could
not do their job, and must be safe to re-run after a partial failure. ``spawn`` keeps a strong
reference to fire-and-forget tasks and logs their exceptions (audit M-22).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Coroutine, Iterable
from typing import Any

logger = logging.getLogger('VEKA.lifecycle')

_background_tasks: set[asyncio.Task] = set()


def _log_task_result(task: asyncio.Task) -> None:
    _background_tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error('Background task %s failed: %s', task.get_name(), exc, exc_info=exc)


def has_running_loop() -> bool:
    """True when called from inside a running event loop (sync hooks like cog_unload may not be)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def spawn(coro: Coroutine[Any, Any, Any], *, name: str | None = None) -> asyncio.Task:
    """Create a task that is kept alive until done and whose exception is logged."""
    task = asyncio.create_task(coro, name=name)
    _background_tasks.add(task)
    task.add_done_callback(_log_task_result)
    return task


COG_READY_RETRY_BASE = 30.0  # seconds before the first retry of a failed cog_ready
COG_READY_RETRY_MAX = 1800.0  # backoff cap


async def _run_cog_ready(cog: Any, hook: Any) -> None:
    name = type(cog).__name__
    try:
        await hook()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        failures = getattr(cog, '_veka_cog_ready_failures', 0) + 1
        delay = min(COG_READY_RETRY_BASE * 2 ** (failures - 1), COG_READY_RETRY_MAX)
        cog._veka_cog_ready_failures = failures
        cog._veka_cog_ready_retry_at = time.monotonic() + delay
        logger.error(
            'cog_ready failed for %s (attempt %d): %s — retrying in %.0fs', name, failures, exc, delay, exc_info=exc
        )
    else:
        cog._veka_cog_ready_done = True
        if getattr(cog, '_veka_cog_ready_failures', 0):
            logger.info('cog_ready succeeded for %s after %d failed attempt(s)', name, cog._veka_cog_ready_failures)


async def run_cog_ready_hooks(bot, cogs: Iterable[Any] | None = None) -> None:
    """Start ``cog_ready()`` on every cog that defines it and hasn't completed it yet.

    Each hook runs as its own task. Skips cogs whose hook succeeded, is still running, or failed
    recently (backoff), so it is cheap to call repeatedly.
    """
    now = time.monotonic()
    for cog in list(cogs if cogs is not None else bot.cogs.values()):
        hook = getattr(cog, 'cog_ready', None)
        if hook is None or getattr(cog, '_veka_cog_ready_done', False):
            continue
        running = getattr(cog, '_veka_cog_ready_task', None)
        if running is not None and not running.done():
            continue
        if now < getattr(cog, '_veka_cog_ready_retry_at', 0.0):
            continue
        cog._veka_cog_ready_task = spawn(_run_cog_ready(cog, hook), name=f'cog_ready:{type(cog).__name__}')
