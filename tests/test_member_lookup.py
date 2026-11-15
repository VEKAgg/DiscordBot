"""Member-name lookup never crosses a guild/service identity boundary."""

from unittest.mock import AsyncMock

import httpx
import pytest
from aiohttp import web

from src.api import auth
from src.api.app import create_app
from src.api.config import ApiSettings
from src.api.discord_client import MANAGE_GUILD, DiscordClient, DiscordUser, Identity, UserGuild
from src.api.errors import ApiError
from src.api.routes import members


@pytest.fixture
def lookup_app(monkeypatch):
    monkeypatch.setattr(auth, 'preauth_limiter', auth.RateLimiter(10000))
    monkeypatch.setattr(auth, 'client_limiter', auth.RateLimiter(10000))
    monkeypatch.setattr(auth, 'settings', ApiSettings(service_token='fake-service'))
    monkeypatch.setattr(members, 'lookup_limiter', auth.RateLimiter(10000))
    identity = Identity(
        DiscordUser(123, 'manager', None, None), {77: UserGuild(77, 'Guild', None, False, MANAGE_GUILD)}
    )
    monkeypatch.setattr(auth.discord_client, 'identify', AsyncMock(return_value=identity))
    monkeypatch.setattr(auth, 'bot_in_guild', AsyncMock(return_value={'guild_id': 77}))
    lookup = AsyncMock(
        side_effect=lambda _guild, uid: {
            'id': str(uid),
            'username': 'member',
            'display_name': 'Member',
            'avatar_url': None,
            'found': True,
        }
    )
    monkeypatch.setattr(members.discord_client, 'guild_member', lookup)
    return create_app(), lookup


async def test_names_are_bounded_private_and_preserve_string_ids(lookup_app):
    app, lookup = lookup_app
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url='http://test', headers={'Authorization': 'Bearer user'}
    ) as client:
        response = await client.post('/v1/guilds/77/members/lookup', json={'user_ids': ['90001', '90002', '90001']})
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'private, no-store'
    assert [item['id'] for item in response.json()['items']] == ['90001', '90002']
    assert [call.args for call in lookup.call_args_list] == [(77, 90001), (77, 90002)]


async def test_foreign_guild_and_service_actor_do_not_lookup_members(lookup_app):
    app, lookup = lookup_app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        foreign = await client.post(
            '/v1/guilds/88/members/lookup', json={'user_ids': ['90001']}, headers={'Authorization': 'Bearer user'}
        )
        service = await client.post(
            '/v1/guilds/77/members/lookup',
            json={'user_ids': ['90001']},
            headers={'X-Service-Token': 'fake-service', 'X-Acting-User': '123'},
        )
    assert foreign.status_code == 403 and service.status_code == 403
    lookup.assert_not_awaited()


@pytest.mark.parametrize(
    'body',
    [
        {'user_ids': []},
        {'user_ids': ['1'] * 26},
        {'user_ids': [123]},
        {'user_ids': ['0']},
        {'user_ids': ['-1']},
        {'user_ids': ['9999999999999999999']},
        {'user_ids': ['1'], 'guild_id': '88'},
    ],
)
async def test_lookup_rejects_unbounded_or_spoofed_ids(lookup_app, body):
    app, lookup = lookup_app
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url='http://test', headers={'Authorization': 'Bearer user'}
    ) as client:
        response = await client.post('/v1/guilds/77/members/lookup', json=body)
    assert response.status_code == 422
    lookup.assert_not_awaited()


async def test_member_provider_cache_is_guild_scoped_and_never_falls_back_to_global(monkeypatch):
    calls = []

    async def handler(request):
        calls.append(request.path)
        assert request.headers['Authorization'] == 'Bot fake-bot-token'
        guild = request.match_info['guild']
        user_id = request.match_info['user']
        if user_id == '999':
            return web.Response(status=404)
        return web.json_response(
            {
                'user': {'id': user_id, 'username': 'sameuser', 'global_name': 'Global', 'avatar': 'hash'},
                'nick': 'Guild ' + guild,
            }
        )

    app = web.Application()
    app.router.add_get('/guilds/{guild}/members/{user}', handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    monkeypatch.setattr('src.api.discord_client.settings', ApiSettings(discord_bot_token='fake-bot-token'))
    client = DiscordClient(base=f'http://127.0.0.1:{port}')
    try:
        assert (await client.guild_member(77, 123))['display_name'] == 'Guild 77'
        assert (await client.guild_member(77, 123))['display_name'] == 'Guild 77'
        assert (await client.guild_member(88, 123))['display_name'] == 'Guild 88'
        missing = await client.guild_member(77, 999)
        assert missing == {'id': '999', 'username': None, 'display_name': None, 'avatar_url': None, 'found': False}
        assert calls == ['/guilds/77/members/123', '/guilds/88/members/123', '/guilds/77/members/999']
    finally:
        await client.close()
        await runner.cleanup()


async def test_member_lookup_requires_manage_server_and_bot_presence(lookup_app, monkeypatch):
    app, lookup = lookup_app
    identity = Identity(DiscordUser(123, 'regular', None, None), {77: UserGuild(77, 'Guild', None, False, 0)})
    monkeypatch.setattr(auth.discord_client, 'identify', AsyncMock(return_value=identity))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url='http://test', headers={'Authorization': 'Bearer user'}
    ) as client:
        response = await client.post('/v1/guilds/77/members/lookup', json={'user_ids': ['90001']})
        assert response.status_code == 403
        monkeypatch.setattr(
            auth, 'bot_in_guild', AsyncMock(side_effect=ApiError(403, 'bot_not_present', 'Not present'))
        )
        response = await client.post('/v1/guilds/77/members/lookup', json={'user_ids': ['90001']})
        assert response.status_code == 403
    lookup.assert_not_awaited()


async def test_lookup_without_bot_credentials_fails_closed(monkeypatch):
    monkeypatch.setattr('src.api.discord_client.settings', ApiSettings(discord_bot_token=None))
    client = DiscordClient()
    with pytest.raises(ApiError) as failure:
        await client.guild_member(77, 123)
    assert failure.value.status == 503
    assert failure.value.code == 'member_lookup_unconfigured'
