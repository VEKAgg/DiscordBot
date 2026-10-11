"""Real PostgreSQL CAS, audit and strict module API validation."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.api import auth as auth_module
from src.api.app import create_app
from src.api.discord_client import BAN_MEMBERS, MANAGE_GUILD
from tests.test_api import GUILD, OTHER, api_db, identity  # noqa: F401 -- shared PostgreSQL fixture


@pytest.fixture
async def modules_client(api_db):  # noqa: F811 -- pytest resolves the imported fixture
    await api_db.execute('DELETE FROM guild_modules WHERE guild_id = ANY($1::bigint[])', [GUILD, OTHER])
    with patch.object(
        auth_module.discord_client, 'identify', AsyncMock(return_value=identity({GUILD: MANAGE_GUILD | BAN_MEMBERS}))
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app()),
            base_url='http://test',
            headers={'Authorization': 'Bearer modules-test'},
        ) as client:
            yield client


async def test_get_defaults_without_insert_and_atomic_cas(modules_client, api_db):  # noqa: F811
    url = f'/v1/guilds/{GUILD}/modules'
    response = await modules_client.get(url)
    assert response.status_code == 200
    assert response.json()['version'] == '0'
    assert not await api_db.fetchval('SELECT 1 FROM guild_modules WHERE guild_id = $1', GUILD)
    response = await modules_client.patch(
        url, json={'modules': {'feeds': False, 'welcome': False}}, headers={'If-Match': '"0"'}
    )
    assert response.status_code == 200
    data = response.json()
    assert data['version'] == '1'
    assert not next(m for m in data['modules'] if m['id'] == 'feeds')['enabled']
    response = await modules_client.patch(url, json={'modules': {'feeds': True}}, headers={'If-Match': '0'})
    assert response.status_code == 412
    assert response.json()['error']['details']['current']['version'] == '1'
    assert (
        await api_db.fetchval(
            "SELECT COUNT(*) FROM audit_logs WHERE guild_id = $1 AND action = 'dashboard_modules_changed'",
            str(GUILD),
        )
        >= 1
    )
    assert await api_db.fetchval('SELECT disabled FROM guild_modules WHERE guild_id = $1', GUILD) == [
        'feeds',
        'welcome',
    ]


@pytest.mark.parametrize(
    ('body', 'headers', 'status'),
    [
        ({'modules': {'feeds': False}}, {}, 428),
        ({'modules': {'privacy': False}}, {'If-Match': '0'}, 422),
        ({'modules': {'unknown': False}}, {'If-Match': '0'}, 422),
        ({'modules': {'feeds': 'false'}}, {'If-Match': '0'}, 422),
        ({'modules': {'feeds': 0}}, {'If-Match': '0'}, 422),
    ],
)
async def test_patch_validation(modules_client, body, headers, status):
    response = await modules_client.patch(f'/v1/guilds/{GUILD}/modules', json=body, headers=headers)
    assert response.status_code == status


async def test_cross_guild_access_is_denied(modules_client):
    response = await modules_client.get(f'/v1/guilds/{OTHER}/modules')
    assert response.status_code == 403


async def test_disabled_action_rejected_but_configuration_readable(modules_client):
    response = await modules_client.patch(
        f'/v1/guilds/{GUILD}/modules', json={'modules': {'massunban': False}}, headers={'If-Match': '0'}
    )
    assert response.status_code == 200
    response = await modules_client.post(
        f'/v1/guilds/{GUILD}/massunban/jobs',
        json={'start': '2026-01-01T00:00:00Z', 'end': '2026-02-01T00:00:00Z'},
    )
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'module_disabled'
    assert response.json()['error']['details']['module'] == 'massunban'
    assert (await modules_client.get(f'/v1/guilds/{GUILD}/massunban/jobs')).status_code == 200
