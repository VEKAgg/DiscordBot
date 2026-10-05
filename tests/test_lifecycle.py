"""nextcord lifecycle rules (audit H-01): no cog_load, no async cog_unload; cog_ready hooks run once."""

from __future__ import annotations

import ast
import asyncio
import pathlib

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
