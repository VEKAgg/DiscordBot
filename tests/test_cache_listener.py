"""Bot-side cache invalidation from dashboard writes (LISTEN veka_cache)."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.cache_listener import CacheHandler, CacheListener


async def test_payload_dispatch_and_reconcile():
    listener = CacheListener(dsn='postgresql://unused')
    settings_notify, settings_reset = MagicMock(), AsyncMock()
    listener.register('guild_settings', CacheHandler(on_notify=settings_notify, reset=settings_reset))
    broken = CacheHandler(on_notify=MagicMock(side_effect=RuntimeError('x')), reset=MagicMock(side_effect=RuntimeError))
    listener.register('honeypots', broken)

    await listener.handle_payload('guild_settings:42')
    await listener.handle_payload('honeypots:42')  # handler error is logged, not raised
    await listener.handle_payload('unknown:1')
    await listener.reconcile()

    settings_notify.assert_called_once_with('42')
    settings_reset.assert_awaited_once()


@pytest.mark.skipif(not os.getenv('VEKA_TEST_DATABASE_URL'), reason='VEKA_TEST_DATABASE_URL not set')
async def test_listener_receives_notify_and_reconciles_on_connect():
    import asyncio

    import asyncpg

    dsn = os.environ['VEKA_TEST_DATABASE_URL']
    listener = CacheListener(dsn=dsn)
    seen: list[str] = []
    resets: list[int] = []
    listener.register('guild_settings', CacheHandler(on_notify=seen.append, reset=lambda: resets.append(1)))
    tasks = [asyncio.create_task(listener._run()), asyncio.create_task(listener._worker())]
    try:
        for _ in range(50):
            if listener.connected:
                break
            await asyncio.sleep(0.05)
        for _ in range(50):
            if resets:
                break
            await asyncio.sleep(0.05)
        assert listener.connected and resets == [1]  # reconcile ran on connect
        conn = await asyncpg.connect(dsn)
        await conn.execute("SELECT pg_notify('veka_cache', 'guild_settings:7')")
        await conn.close()
        for _ in range(50):
            if seen:
                break
            await asyncio.sleep(0.05)
        assert seen == ['7']
    finally:
        for task in tasks:
            task.cancel()


async def test_failed_reset_is_retried_without_reconnect():
    import asyncio

    listener = CacheListener(dsn='postgresql://unused', retry_max=0.01)
    calls = {'n': 0}

    def flaky_reset():
        calls['n'] += 1
        if calls['n'] == 1:
            raise RuntimeError('db blip')

    listener.register('guild_settings', CacheHandler(on_notify=lambda _i: None, reset=flaky_reset))
    worker = asyncio.create_task(listener._worker())
    try:
        listener.enqueue(CacheListener.RESET)
        for _ in range(100):
            if calls['n'] >= 2:
                break
            await asyncio.sleep(0.01)
        assert calls['n'] >= 2  # retried until it succeeded
    finally:
        worker.cancel()


async def test_notifications_are_sequential_and_coalesced():
    import asyncio

    listener = CacheListener(dsn='postgresql://unused')
    order: list[str] = []
    running = {'n': 0, 'max': 0}

    async def slow(ident):
        running['n'] += 1
        running['max'] = max(running['max'], running['n'])
        await asyncio.sleep(0.01)
        order.append(ident)
        running['n'] -= 1

    listener.register('privacy', CacheHandler(on_notify=slow, reset=lambda: None))
    for ident in ('1', '1', '1', '2'):
        listener.enqueue(f'privacy:{ident}')
    worker = asyncio.create_task(listener._worker())
    try:
        for _ in range(100):
            if len(order) >= 2:
                break
            await asyncio.sleep(0.01)
    finally:
        worker.cancel()
    assert order == ['1', '2']  # duplicates coalesced, applied in order
    assert running['max'] == 1  # never overlapping
