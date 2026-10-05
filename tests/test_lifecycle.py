"""nextcord lifecycle rules (audit H-01): no cog_load, no async cog_unload; cog_ready hooks run once."""

from __future__ import annotations

import ast
import asyncio
import pathlib
from unittest.mock import AsyncMock, MagicMock

from src.core.lifecycle import run_cog_ready_hooks


def _cog_methods():
    for path in sorted(pathlib.Path('src/cogs').rglob('*.py')):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                        yield path, node.name, item


def test_no_cog_load_methods():
    offenders = [f'{p}:{c}.{m.name}' for p, c, m in _cog_methods() if m.name == 'cog_load']
    assert not offenders, f'nextcord never calls cog_load; use cog_ready instead: {offenders}'


def test_cog_constructors_do_not_start_background_loops():
    offenders = []
    for path, cls, method in _cog_methods():
        if method.name != '__init__':
            continue
        for node in ast.walk(method):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'start':
                offenders.append(f'{path}:{cls}:{node.lineno}')
    assert not offenders, f'Background loops must start after DB initialization in cog_ready: {offenders}'


def test_cog_unload_is_sync():
    offenders = [
        f'{p}:{c}.cog_unload'
        for p, c, m in _cog_methods()
        if m.name == 'cog_unload' and isinstance(m, ast.AsyncFunctionDef)
    ]
    assert not offenders, f'nextcord calls cog_unload synchronously: {offenders}'


async def test_cog_ready_runs_once_per_instance():
    calls = []

    class Cog:
        async def cog_ready(self):
            calls.append(self)

    class Bot:
        cogs = {'a': Cog()}

    bot = Bot()
    await run_cog_ready_hooks(bot)
    await run_cog_ready_hooks(bot)
    await asyncio.sleep(0)
    assert len(calls) == 1


async def test_failed_cog_ready_is_retried_after_backoff(monkeypatch):
    attempts = []

    class Cog:
        async def cog_ready(self):
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError('db down')

    class Bot:
        cogs = {'a': Cog()}

    clock = [100.0]
    monkeypatch.setattr('src.core.lifecycle.time.monotonic', lambda: clock[0])
    bot = Bot()
    await run_cog_ready_hooks(bot)
    await asyncio.sleep(0)
    await run_cog_ready_hooks(bot)  # inside the backoff window: not retried yet
    await asyncio.sleep(0)
    assert len(attempts) == 1

    clock[0] += 31
    await run_cog_ready_hooks(bot)
    await asyncio.sleep(0)
    assert len(attempts) == 2

    clock[0] += 3600
    await run_cog_ready_hooks(bot)  # succeeded — never run again
    await asyncio.sleep(0)
    assert len(attempts) == 2


async def test_recovery_reruns_deferred_migrations_and_hooks(monkeypatch):
    from src.core import app
    from src.core.runtime_state import runtime_state

    run_migrations = AsyncMock()
    hooks = AsyncMock()
    monkeypatch.setattr(app.db, 'run_migrations', run_migrations)
    monkeypatch.setattr(app, 'run_cog_ready_hooks', hooks)
    monkeypatch.setattr(app, '_migration_retry', {'at': 0.0, 'delay': 15.0})
    monkeypatch.setattr(runtime_state, 'db_available', True)
    monkeypatch.setattr(runtime_state, 'degraded_features', ['database', 'src.cogs.x'])

    await app.recover_after_db_available(MagicMock())
    await app.recover_after_db_available(MagicMock())

    run_migrations.assert_awaited_once()
    assert runtime_state.degraded_features == ['src.cogs.x']
    assert hooks.await_count == 2


async def test_health_check_restores_state_after_immediate_reconnect(monkeypatch):
    import inspect

    from src.core import app
    from src.core.runtime_state import runtime_state
    from src.utils.safety import DatabaseUnavailableError

    bot = app.build_bot()
    app.configure_bot_events(bot)
    loop = inspect.getclosurevars(bot.__dict__['on_ready']).nonlocals['db_health_check']
    monkeypatch.setattr(app.db, 'pool', MagicMock())
    monkeypatch.setattr(runtime_state, 'db_available', True)

    async def failed_ping():
        runtime_state.db_available = False
        raise DatabaseUnavailableError('down')

    attempts = 0

    async def ping_with_state():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            await failed_ping()
        return True

    monkeypatch.setattr(app.db, 'ping', ping_with_state)
    monkeypatch.setattr(app.db, 'reconnect', AsyncMock())
    recovery = AsyncMock()
    monkeypatch.setattr(app, 'recover_after_db_available', recovery)
    await loop()
    assert runtime_state.db_available is True
    recovery.assert_awaited_once_with(bot)
    await bot.close()


async def test_massunban_partial_resume_failure_requests_retry(monkeypatch):
    import pytest

    from src.cogs.admin import massunban
    from src.core.runtime_state import runtime_state

    bot = MagicMock()
    bot.wait_until_ready = AsyncMock()
    cog = massunban.MassUnban(bot)
    monkeypatch.setattr(runtime_state, 'db_available', True)
    monkeypatch.setattr(
        massunban.db,
        'fetch',
        AsyncMock(
            side_effect=[
                [{'id': 1, 'status': 'running'}],
                [],
            ]
        ),
    )
    monkeypatch.setattr(massunban.db, 'execute', AsyncMock(side_effect=RuntimeError('down')))
    with pytest.raises(RuntimeError, match='retry required'):
        await cog.cog_ready()
    assert not cog._active_jobs
