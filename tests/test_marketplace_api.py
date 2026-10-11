"""Marketplace API image authorization and scoped listing regressions."""

from contextlib import asynccontextmanager
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from src.api import auth
from src.api.app import create_app
from src.api.discord_client import MANAGE_GUILD, DiscordUser, Identity, UserGuild
from src.api.routes import marketplace
from src.services.marketplace_images import StoredImage


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(auth, 'preauth_limiter', auth.RateLimiter(10000))
    monkeypatch.setattr(auth, 'client_limiter', auth.RateLimiter(10000))
    monkeypatch.setattr(auth, 'settings', auth.settings.__class__(service_token='right'))
    return create_app()


@pytest.fixture
def owner(monkeypatch):
    identity = Identity(DiscordUser(123, 'seller', None, None), {})
    monkeypatch.setattr(auth.discord_client, 'identify', AsyncMock(return_value=identity))
    monkeypatch.setattr(marketplace.db, 'fetch_one', AsyncMock(return_value={'guild_id': 77, 'discord_id': '123'}))
    image = StoredImage(b'image', 'a' * 64, 10, 20)
    monkeypatch.setattr(marketplace.image_store, 'get', AsyncMock(return_value=image))
    return image


async def test_owner_image_etag_and_private_cache(app, owner):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url='http://test', headers={'Authorization': 'Bearer owner'}
    ) as client:
        response = await client.get('/v1/marketplace/listings/one/images/0')
        assert response.status_code == 200 and response.content == owner.data
        assert response.headers['cache-control'] == 'private, no-store'
        assert response.headers['etag'] == f'"{owner.sha256}"'
        response = await client.get(
            '/v1/marketplace/listings/one/images/' + owner.sha256, headers={'If-None-Match': f'"{owner.sha256}"'}
        )
        assert response.status_code == 304
        assert response.headers['cache-control'] == 'private, no-store'


async def test_image_authorization_precedes_etag_check(app, owner, monkeypatch):
    monkeypatch.setattr(marketplace.db, 'fetch_one', AsyncMock(return_value={'guild_id': 77, 'discord_id': '456'}))
    monkeypatch.setattr(marketplace.db, 'fetch', AsyncMock(return_value=[{'guild_id': 77}]))
    get_image = AsyncMock()
    monkeypatch.setattr(marketplace.image_store, 'get', get_image)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url='http://test', headers={'Authorization': 'Bearer stranger'}
    ) as client:
        response = await client.get(
            '/v1/marketplace/listings/one/images/0', headers={'If-None-Match': f'"{owner.sha256}"'}
        )
    assert response.status_code == 404
    get_image.assert_not_awaited()


async def test_anonymous_and_service_image_access_are_rejected(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.get('/v1/marketplace/listings/one/images/0')).status_code == 401
        response = await client.get(
            '/v1/marketplace/listings/one/images/0', headers={'X-Service-Token': 'right', 'X-Acting-User': '123'}
        )
        assert response.status_code == 403


def test_listing_output_keeps_price_cents_and_only_stored_image_urls():
    row = {'id': 'one', 'price': Decimal('12.34'), 'image_count': 2}
    output = marketplace._out(row)
    assert output['price'] == '12.34'
    assert output['images'] == ['/v1/marketplace/listings/one/images/0', '/v1/marketplace/listings/one/images/1']


async def test_guild_listing_query_is_scoped_and_bounded(app, monkeypatch):
    identity = Identity(
        DiscordUser(123, 'manager', None, None), {77: UserGuild(77, 'Guild', None, False, MANAGE_GUILD)}
    )
    monkeypatch.setattr(auth.discord_client, 'identify', AsyncMock(return_value=identity))
    monkeypatch.setattr(auth, 'bot_in_guild', AsyncMock(return_value={'guild_id': 77}))
    fetch = AsyncMock(return_value=[])
    monkeypatch.setattr(marketplace.db, 'fetch', fetch)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url='http://test', headers={'Authorization': 'Bearer manager'}
    ) as client:
        response = await client.get('/v1/guilds/77/marketplace/listings?limit=10')
        assert response.status_code == 200
        assert response.json() == {'items': [], 'next_cursor': None}
        assert (await client.get('/v1/guilds/88/marketplace/listings')).status_code == 403
        assert (await client.get('/v1/guilds/77/marketplace/listings?cursor=e30')).status_code == 422
    sql, guild_id, status, source, after, limit = fetch.call_args.args
    assert (guild_id, status, source, after, limit) == (77, None, None, None, 11)
    assert 'l.guild_id = $1' in sql and 'p.guild_id = $1' in sql


@pytest.fixture
def manager(monkeypatch):
    identity = Identity(
        DiscordUser(123, 'manager', None, None), {77: UserGuild(77, 'Guild', None, False, MANAGE_GUILD)}
    )
    identify = AsyncMock(return_value=identity)
    monkeypatch.setattr(auth.discord_client, 'identify', identify)
    monkeypatch.setattr(auth, 'bot_in_guild', AsyncMock(return_value={'guild_id': 77}))
    return identify


@pytest.fixture
def mutation(monkeypatch):
    conn = MagicMock()
    current = {'id': 'one', 'source': 'forum', 'status': 'pending_review', 'price': None, 'image_count': 0}
    updated = current | {'status': 'active', 'price': Decimal('12.34')}
    conn.fetchrow = AsyncMock(side_effect=[current, updated])
    conn.execute = AsyncMock()

    @asynccontextmanager
    async def transaction():
        yield conn

    monkeypatch.setattr(marketplace.db, 'transaction', transaction)
    return conn, current


@pytest.mark.parametrize(
    'body',
    [
        {},
        {'price': None},
        {'status': None},
        {'price': 12.34},
        {'price': True},
        {'price': '0'},
        {'price': '-1'},
        {'price': 'NaN'},
        {'price': '1.001'},
        {'status': 'sold'},
        {'price': '12', 'extra': 'ignored'},
    ],
)
@pytest.mark.usefixtures('manager')
async def test_patch_strict_validation_precedes_mutations(app, mutation, body):
    conn, _ = mutation
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url='http://test', headers={'Authorization': 'Bearer manager'}
    ) as client:
        assert (await client.patch('/v1/guilds/77/marketplace/listings/one', json=body)).status_code == 422
    conn.fetchrow.assert_not_awaited()
    conn.execute.assert_not_awaited()


async def test_patch_combines_price_and_approval_with_fresh_permissions_and_audit(app, manager, mutation):
    conn, _ = mutation
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url='http://test', headers={'Authorization': 'Bearer manager'}
    ) as client:
        response = await client.patch(
            '/v1/guilds/77/marketplace/listings/one', json={'price': '12.34', 'status': 'active'}
        )
    assert response.status_code == 200 and response.json()['price'] == '12.34'
    manager.assert_awaited_with('manager', fresh=True)
    select, guild, listing = conn.fetchrow.call_args_list[0].args
    assert (guild, listing) == (77, 'one') and 'FOR UPDATE' in select
    assert 'p.guild_id = $1' in select
    update = conn.fetchrow.call_args_list[1].args
    assert update[1:] == ('one', Decimal('12.34'), 'active')
    assert 'price_override' in update[0] and 'forum_review_status' in update[0]
    assert 'dashboard_marketplace_changed' in conn.execute.call_args.args[0]


@pytest.mark.parametrize(
    'status,price,body,code',
    [
        ('pending_review', None, {'status': 'active'}, 422),
        ('active', Decimal('10'), {'status': 'active'}, 409),
        ('sold', Decimal('10'), {'price': '12'}, 409),
        ('withdrawn', Decimal('10'), {'price': '12'}, 409),
        ('removed', Decimal('10'), {'status': 'active'}, 409),
    ],
)
@pytest.mark.usefixtures('manager')
async def test_patch_lifecycle_conflicts_do_not_write(app, mutation, status, price, body, code):
    conn, current = mutation
    current.update(status=status, price=price)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url='http://test', headers={'Authorization': 'Bearer manager'}
    ) as client:
        assert (await client.patch('/v1/guilds/77/marketplace/listings/one', json=body)).status_code == code
    assert conn.fetchrow.await_count == 1
    conn.execute.assert_not_awaited()


@pytest.mark.usefixtures('manager')
async def test_patch_cross_guild_scope_and_service_impersonation_fail_closed(app, mutation):
    conn, _ = mutation
    conn.fetchrow.side_effect = [None]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url='http://test', headers={'Authorization': 'Bearer manager'}
    ) as client:
        assert (await client.patch('/v1/guilds/88/marketplace/listings/one', json={'price': '12'})).status_code == 403
        assert (await client.patch('/v1/guilds/77/marketplace/listings/one', json={'price': '12'})).status_code == 404
        assert (
            await client.patch(
                '/v1/guilds/77/marketplace/listings/one',
                json={'price': '12'},
                headers={'X-Service-Token': 'right', 'X-Acting-User': '123'},
            )
        ).status_code == 403
    assert conn.fetchrow.await_count == 1
    conn.execute.assert_not_awaited()
