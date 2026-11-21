"""DiscordClient: concurrent identity lookups share one Discord round trip, short 429s are retried."""

from __future__ import annotations

import asyncio

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from src.api.discord_client import DiscordClient
from src.api.errors import ApiError

Reply = tuple[int, dict | list, dict[str, str]]


async def _discord(responses: dict[str, list[Reply]], calls: dict[str, int]) -> TestServer:
    """A fake Discord API answering each path from a queue of (status, body, headers)."""

    async def handler(request: web.Request) -> web.Response:
        path = request.path
        calls[path] = calls.get(path, 0) + 1
        await asyncio.sleep(0.05)  # long enough for concurrent callers to overlap
        queue = responses[path]
        status, body, headers = queue.pop(0) if len(queue) > 1 else queue[0]
        return web.json_response(body, status=status, headers=headers)

    app = web.Application()
    app.router.add_get('/users/@me', handler)
    app.router.add_get('/users/@me/guilds', handler)
    server = TestServer(app)
    await server.start_server()
    return server


ME: Reply = (200, {'id': '1', 'username': 'ann'}, {})
GUILDS: Reply = (200, [{'id': '10', 'name': 'G', 'owner': True, 'permissions': '0'}], {})


async def test_concurrent_lookups_share_one_discord_call():
    calls: dict[str, int] = {}
    server = await _discord({'/users/@me': [ME], '/users/@me/guilds': [GUILDS]}, calls)
    client = DiscordClient(base=str(server.make_url('')))
    try:
        results = await asyncio.gather(*(client.identify('tok') for _ in range(5)), client.identify('tok', fresh=True))
        assert all(r.user.id == 1 and 10 in r.guilds for r in results)
        assert calls == {'/users/@me': 1, '/users/@me/guilds': 1}
        # Cached afterwards; a fresh lookup goes to Discord again.
        await client.identify('tok')
        await client.identify('tok', fresh=True)
        assert calls['/users/@me/guilds'] == 2
    finally:
        await client.close()
        await server.close()


async def test_short_rate_limit_is_waited_out_once():
    calls: dict[str, int] = {}
    limited: Reply = (429, {'message': 'You are being rate limited.'}, {'Retry-After': '0.1'})
    server = await _discord({'/users/@me': [ME], '/users/@me/guilds': [limited, GUILDS]}, calls)
    client = DiscordClient(base=str(server.make_url('')))
    try:
        ident = await client.identify('tok')
        assert 10 in ident.guilds and calls['/users/@me/guilds'] == 2
    finally:
        await client.close()
        await server.close()


async def test_long_or_repeated_rate_limit_fails_with_retry_after():
    cases: list[tuple[dict[str, str], int]] = [({'Retry-After': '30'}, 1), ({'Retry-After': '0.1'}, 2)]
    for headers, expected_calls in cases:
        calls: dict[str, int] = {}
        limited: Reply = (429, {'message': 'limited'}, headers)
        server = await _discord({'/users/@me': [ME], '/users/@me/guilds': [limited]}, calls)
        client = DiscordClient(base=str(server.make_url('')))
        try:
            with pytest.raises(ApiError) as err:
                await client.identify('tok')
            assert err.value.code == 'discord_rate_limited'
            assert int(err.value.headers['Retry-After']) >= 1
            assert calls['/users/@me/guilds'] == expected_calls
            # The failure is not cached and does not linger as an in-flight lookup.
            assert client._inflight == {}
        finally:
            await client.close()
            await server.close()


async def test_cancelled_caller_does_not_cancel_the_shared_lookup():
    calls: dict[str, int] = {}
    server = await _discord({'/users/@me': [ME], '/users/@me/guilds': [GUILDS]}, calls)
    client = DiscordClient(base=str(server.make_url('')))
    try:
        first = asyncio.ensure_future(client.identify('tok'))
        second = asyncio.ensure_future(client.identify('tok'))
        await asyncio.sleep(0.01)
        first.cancel()
        assert (await second).user.id == 1
        assert calls == {'/users/@me': 1, '/users/@me/guilds': 1}
    finally:
        await client.close()
        await server.close()
