"""Dashboard access gate is independent of action-specific moderator capabilities."""

from unittest.mock import AsyncMock

import httpx
import pytest
from starlette.requests import Request

from src.api import auth
from src.api.app import create_app
from src.api.discord_client import (
    ADMINISTRATOR,
    BAN_MEMBERS,
    MANAGE_GUILD,
    MANAGE_ROLES,
    MODERATE_MEMBERS,
    DiscordUser,
    Identity,
    UserGuild,
)
from src.api.errors import ApiError


def _principal(bits=0, *, owner=False):
    return auth.Principal(
        'user', Identity(DiscordUser(123, 'user', None, None), {77: UserGuild(77, 'Server', None, owner, bits)})
    )


async def test_all_guild_endpoints_reject_moderator_without_manage_server(monkeypatch):
    monkeypatch.setattr(
        auth, '_principal', AsyncMock(return_value=_principal(BAN_MEMBERS | MANAGE_ROLES | MODERATE_MEMBERS))
    )
    monkeypatch.setattr(auth, 'bot_in_guild', AsyncMock(return_value={}))
    app = create_app()
    routes = [
        (path, operations.keys()) for path, operations in app.openapi()['paths'].items() if '/guilds/{guild_id}' in path
    ]
    assert len(routes) > 10
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        for path, methods in routes:
            path = path.replace('{guild_id}', '77')
            for param in ('warning_id', 'job_id', 'honeypot_id', 'listing_id', 'subscription_id', 'user_id'):
                path = path.replace('{' + param + '}', '1')
            for method in methods:
                response = await client.request(method, path)
                assert response.status_code == 403, (method, path, response.text)
                assert response.json()['error']['code'] == 'missing_permission'


@pytest.mark.parametrize('bits,owner', [(MANAGE_GUILD, False), (ADMINISTRATOR, False), (0, True)])
async def test_owner_administrator_and_manager_enter_dashboard(monkeypatch, bits, owner):
    identify = AsyncMock(return_value=_principal(bits, owner=owner))
    monkeypatch.setattr(auth, '_principal', identify)
    monkeypatch.setattr(auth, 'bot_in_guild', AsyncMock(return_value={}))
    dependency = auth.guild_access(fresh=True).dependency
    access = await dependency(Request({'type': 'http', 'headers': []}), guild_id=77)
    assert access.guild_id == 77
    assert identify.call_args.kwargs == {'allow_service': False, 'fresh': True}


async def test_manage_server_does_not_grant_ban_capability(monkeypatch):
    monkeypatch.setattr(auth, '_principal', AsyncMock(return_value=_principal(MANAGE_GUILD)))
    monkeypatch.setattr(auth, 'bot_in_guild', AsyncMock(return_value={}))
    with pytest.raises(ApiError):
        await auth.guild_access(BAN_MEMBERS).dependency(Request({'type': 'http', 'headers': []}), guild_id=77)
