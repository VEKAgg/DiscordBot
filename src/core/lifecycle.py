"""Cog lifecycle helpers for nextcord.

nextcord (unlike discord.py) never calls ``Cog.cog_load`` and calls ``cog_unload`` synchronously,
so async setup placed there silently never ran (audit H-01). Instead, cogs define::

    async def cog_ready(self) -> None: ...

which ``run_cog_ready_hooks`` calls once per cog instance after the database is initialised in
``on_ready`` (and again for a freshly reloaded cog). ``spawn`` keeps a strong reference to
fire-and-forget tasks and logs their exceptions (audit M-22).
"""

from __future__ import annotations

import asyncio
import logging
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


async def run_cog_ready_hooks(bot, cogs: Iterable[Any] | None = None) -> None:
    """Call ``cog_ready()`` once on every cog that defines it (each runs as its own task)."""
    for cog in list(cogs if cogs is not None else bot.cogs.values()):
        hook = getattr(cog, 'cog_ready', None)
        if hook is None or getattr(cog, '_veka_cog_ready_started', False):
            continue
        cog._veka_cog_ready_started = True
        spawn(hook(), name=f'cog_ready:{type(cog).__name__}')
