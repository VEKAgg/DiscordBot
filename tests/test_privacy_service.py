"""Shared privacy transactions and self-only API route regressions (no database/network)."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from src.api import auth
from src.api.app import create_app
from src.api.discord_client import DiscordUser, Identity
from src.api.routes import privacy
from src.database.database import Database
from src.services import privacy_service as service


@pytest.fixture
def database():
    conn = MagicMock()
    conn.execute = AsyncMock()
    now = datetime.now(UTC)
    conn.fetchval = AsyncMock(side_effect=[False, now])
    database = MagicMock(spec=Database)
    database.fetch_one = AsyncMock(return_value=None)
    committed = []

    @asynccontextmanager
    async def transaction():
        try:
            yield conn
        except Exception:
            committed.append(False)
            raise
        else:
            committed.append(True)

    database.transaction = transaction
    return database, conn, committed, now


async def test_consent_audit_and_notify_share_transaction(database):
    db, conn, committed, now = database
    assert await service.set_presence_opt_in(123, True, source='dashboard', database=db) == now
    assert committed == [True]
    assert 'FOR UPDATE' in conn.fetchval.call_args_list[0].args[0]
    calls = conn.execute.call_args_list
    assert calls[-2].args[1:3] == ('123', 'dashboard_update_privacy')
    assert '"source": "dashboard"' in calls[-2].args[3]
    assert calls[-1].args == ("SELECT pg_notify('veka_cache', $1)", 'privacy:123')


async def test_delete_locks_before_child_rows_and_notifies_last(database):
    db, conn, committed, _ = database
    await service.delete_activity_data(123, source='dashboard', database=db)
    calls = conn.execute.call_args_list
    assert 'FOR UPDATE' in calls[1].args[0]
    assert calls[2].args[0] == 'DELETE FROM user_active_activities WHERE user_id = $1'
    assert any('clock_timestamp()' in c.args[0] for c in calls)
    assert calls[-2].args[2] == 'dashboard_delete_activity'
    assert calls[-1].args[1] == 'privacy:123'
    assert committed == [True]


async def test_audit_failure_rolls_back_and_never_notifies(database):
    db, conn, committed, _ = database

    async def execute(sql, *_args):
        if 'INSERT INTO audit_logs' in sql:
            raise RuntimeError('audit failed')

    conn.execute.side_effect = execute
    with pytest.raises(RuntimeError, match='audit failed'):
        await service.delete_activity_data(123, database=db)
    assert committed == [False]
    assert not any('pg_notify' in c.args[0] for c in conn.execute.call_args_list)


async def test_unknown_user_privacy_defaults_allowed(database):
    """Server opt-in + member opt-out (owner decision): a member who never chose is allowed."""
    db, _, _, _ = database
    assert await service.get_privacy(123, database=db) == {'presence_tracking': True, 'changed_at': None}


@pytest.fixture
def app(monkeypatch):
    app = create_app()
    app.include_router(privacy.router, prefix='/v1')
    monkeypatch.setattr(auth, 'settings', auth.settings.__class__(service_token='right'))
    monkeypatch.setattr(auth, 'preauth_limiter', auth.RateLimiter(10000))
    monkeypatch.setattr(auth, 'client_limiter', auth.RateLimiter(10000))
    return app


@pytest.mark.parametrize('method,path', [('GET', '/privacy'), ('PUT', '/privacy'), ('DELETE', '/activity')])
async def test_service_actor_cannot_access_privacy_routes(app, method, path):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.request(
            method,
            '/v1/me' + path,
            headers={'X-Service-Token': 'right', 'X-Acting-User': '123'},
            json={'presence_tracking': True} if method == 'PUT' else None,
        )
    assert response.status_code == 403
    assert response.json()['error']['code'] == 'service_not_allowed'


async def test_privacy_routes_use_authenticated_owner_and_strict_body(app, monkeypatch):
    identity = Identity(DiscordUser(123, 'owner', None, None), {})
    monkeypatch.setattr(auth.discord_client, 'identify', AsyncMock(return_value=identity))
    get = AsyncMock(return_value={'presence_tracking': False, 'changed_at': None})
    put = AsyncMock(return_value=datetime.now(UTC))
    delete = AsyncMock()
    monkeypatch.setattr(service, 'get_privacy', get)
    monkeypatch.setattr(service, 'set_presence_opt_in', put)
    monkeypatch.setattr(service, 'delete_activity_data', delete)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url='http://test', headers={'Authorization': 'Bearer test'}
    ) as client:
        assert (await client.get('/v1/me/privacy')).status_code == 200
        for body in ({'presence_tracking': 'true'}, {'presence_tracking': True, 'user_id': '456'}):
            assert (await client.put('/v1/me/privacy', json=body)).status_code == 422
        assert (await client.put('/v1/me/privacy', json={'presence_tracking': True})).status_code == 200
        assert (await client.delete('/v1/me/activity')).status_code == 204
    get.assert_awaited_once_with(123)
    put.assert_awaited_once_with(123, True, source='dashboard')
    delete.assert_awaited_once_with(123, source='dashboard')
