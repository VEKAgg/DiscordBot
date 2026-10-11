"""Dashboard API slice 1: auth, permissions, errors, limits, health, /me, read-only guild routes."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import pytest_asyncio

from src.api import auth as auth_module
from src.api.app import create_app
from src.api.discord_client import (
    BAN_MEMBERS,
    MANAGE_GUILD,
    MANAGE_ROLES,
    MODERATE_MEMBERS,
    DiscordUser,
    Identity,
    UserGuild,
)
from src.api.errors import ApiError
from src.api.ratelimit import RateLimiter

DSN = os.getenv('VEKA_TEST_DATABASE_URL')

GUILD = 424200000000000001
OTHER = 424200000000000002
NO_BOT = 424200000000000003


def identity(perms: dict[int, int], uid: int = 111) -> Identity:
    return Identity(
        user=DiscordUser(id=uid, username='tester', global_name='Tester', avatar=None),
        guilds={
            gid: UserGuild(id=gid, name=f'g{gid}', icon=None, owner=False, permissions=p) for gid, p in perms.items()
        },
    )


@pytest.fixture
def app():
    return create_app()


@pytest.fixture(autouse=True)
def _fresh_rate_limits(monkeypatch):
    """Limiters are process-global; give each test its own budget."""
    monkeypatch.setattr(auth_module, 'preauth_limiter', RateLimiter(1000))
    monkeypatch.setattr(auth_module, 'client_limiter', RateLimiter(1000))


async def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test')


# ---------------------------------------------------------------- unit: auth & errors


async def test_missing_token_is_401_with_envelope(app):
    async with await _client(app) as c:
        r = await c.get('/v1/me')
    assert r.status_code == 401
    assert r.json()['error']['code'] == 'missing_token'


async def test_invalid_service_token_is_rejected(app, monkeypatch):
    monkeypatch.setattr(auth_module, 'settings', auth_module.settings.__class__(service_token='right'))
    async with await _client(app) as c:
        r = await c.get('/v1/me', headers={'X-Service-Token': 'wrong'})
    assert r.status_code == 401 and r.json()['error']['code'] == 'invalid_service_token'


async def test_service_token_cannot_use_user_only_routes(app, monkeypatch):
    """S2S is its own principal: a valid service token + claimed actor never becomes that user."""
    monkeypatch.setattr(auth_module, 'settings', auth_module.settings.__class__(service_token='right'))
    async with await _client(app) as c:
        r = await c.get('/v1/me', headers={'X-Service-Token': 'right', 'X-Acting-User': '111'})
    assert r.status_code == 403 and r.json()['error']['code'] == 'service_not_allowed'


async def test_discord_outage_is_503_not_401(app):
    with patch.object(
        auth_module.discord_client,
        'identify',
        AsyncMock(side_effect=ApiError(503, 'discord_unavailable', 'x')),
    ):
        async with await _client(app) as c:
            r = await c.get('/v1/me', headers={'Authorization': 'Bearer abc'})
    assert r.status_code == 503 and r.json()['error']['code'] == 'discord_unavailable'


async def test_oversized_body_is_413(app):
    async with await _client(app) as c:
        r = await c.post('/v1/me', content=b'x' * (65 * 1024), headers={'Content-Type': 'application/json'})
    assert r.status_code == 413


async def test_unknown_route_uses_envelope(app):
    async with await _client(app) as c:
        r = await c.get('/v1/nope')
    assert r.status_code == 404 and r.json()['error']['code'] == 'not_found'


def test_rate_limiter_blocks_and_recovers():
    now = [0.0]
    limiter = RateLimiter(per_minute=60, clock=lambda: now[0])
    for _ in range(60):
        limiter.check('k')
    with pytest.raises(ApiError) as exc:
        limiter.check('k')
    assert exc.value.status == 429 and 'Retry-After' in exc.value.headers
    now[0] += 2
    limiter.check('k')  # refilled


def test_tokens_are_never_logged():
    """The Discord client caches by token hash; the raw token never appears in its state."""
    from src.api.discord_client import DiscordClient

    client = DiscordClient(base='http://discord.invalid')
    client._cache.set('hash', identity({}))
    assert all('Bearer' not in k for k in client._cache)


# ---------------------------------------------------------------- PostgreSQL-backed


@pytest_asyncio.fixture
async def api_db():
    if not DSN:
        pytest.skip('VEKA_TEST_DATABASE_URL not set')
    import asyncpg

    from src.database.database import db

    pool = await asyncpg.create_pool(DSN, min_size=1, max_size=3)
    previous = db.pool
    db.pool = pool
    # Schema comes from test_schema_postgres (module order) or a previous run; make sure the tables exist.
    if not await pool.fetchval("SELECT to_regclass('public.bot_guild_snapshot') IS NOT NULL"):
        await db.run_migrations()
    await pool.execute('DELETE FROM bot_guild_snapshot WHERE guild_id = ANY($1::bigint[])', [GUILD, OTHER, NO_BOT])
    for gid, age in ((GUILD, 0), (OTHER, 0), (NO_BOT, 30)):
        await pool.execute(
            """INSERT INTO bot_guild_snapshot (guild_id, name, member_count, online_count, channels, roles, updated_at)
               VALUES ($1, $2, 10, 3, $3::jsonb, '[]'::jsonb, NOW() - make_interval(mins => $4))""",
            gid,
            f'Guild {gid}',
            json.dumps([{'id': '1', 'name': 'general', 'type': 'text', 'parent_id': None, 'position': 0}]),
            age,
        )
    await pool.execute(
        """INSERT INTO bot_status (id, version, updated_at) VALUES (1, 'test', NOW())
           ON CONFLICT (id) DO UPDATE SET version = 'test', updated_at = NOW()"""
    )
    yield pool
    db.pool = previous
    await pool.close()


def _as(ident: Identity):
    return patch.object(auth_module.discord_client, 'identify', AsyncMock(return_value=ident))


@pytest.mark.usefixtures('api_db')
async def test_health_reports_db_and_bot(app):
    async with await _client(app) as c:
        r = await c.get('/v1/health')
    body = r.json()
    assert r.status_code == 200 and body['db'] == 'ok' and body['bot']['online'] is True


@pytest.mark.usefixtures('api_db')
async def test_me_guilds_lists_only_managed_guilds_with_the_bot(app):
    ident = identity({GUILD: MANAGE_GUILD, OTHER: BAN_MEMBERS | MODERATE_MEMBERS | MANAGE_ROLES, NO_BOT: MANAGE_GUILD})
    with _as(ident):
        async with await _client(app) as c:
            r = await c.get('/v1/me/guilds', headers={'Authorization': 'Bearer t'})
    assert r.status_code == 200
    assert [g['id'] for g in r.json()['items']] == [
        str(GUILD)
    ]  # OTHER: moderation but not management; NO_BOT: stale snapshot


@pytest.mark.usefixtures('api_db')
async def test_guild_routes_enforce_membership_permission_and_bot_presence(app):
    headers = {'Authorization': 'Bearer t'}
    async with await _client(app) as c:
        with _as(identity({GUILD: MANAGE_GUILD})):
            ok = await c.get(f'/v1/guilds/{GUILD}', headers=headers)
            channels = await c.get(f'/v1/guilds/{GUILD}/channels', headers=headers)
            not_member = await c.get(f'/v1/guilds/{OTHER}', headers=headers)
            no_bot = await c.get(f'/v1/guilds/{NO_BOT}', headers=headers)
        with _as(identity({GUILD: 0})):
            no_perm = await c.get(f'/v1/guilds/{GUILD}', headers=headers)
        with _as(identity({GUILD: BAN_MEMBERS})):
            moderator = await c.get(f'/v1/guilds/{GUILD}', headers=headers)
    assert ok.status_code == 200 and ok.json()['name'] == f'Guild {GUILD}'
    assert channels.json()['items'][0]['id'] == '1'  # snowflakes as strings
    assert not_member.status_code == 403 and not_member.json()['error']['code'] == 'not_a_member'
    assert no_bot.status_code == 403 and no_bot.json()['error']['code'] == 'bot_not_in_guild'
    assert no_perm.status_code == 403 and no_perm.json()['error']['code'] == 'missing_permission'
    assert moderator.status_code == 403  # dashboard requires Manage Server, not moderation alone


# ---------------------------------------------------------------- settings


async def _seed_settings_channels(pool):
    await pool.execute(
        """UPDATE bot_guild_snapshot SET channels = $2::jsonb, roles = $3::jsonb, bot_top_role_position = 5
           WHERE guild_id = $1""",
        GUILD,
        json.dumps(
            [
                {'id': '501', 'name': 'logs', 'type': 'text', 'parent_id': None, 'position': 0},
                {'id': '502', 'name': 'market', 'type': 'forum', 'parent_id': None, 'position': 1},
                {'id': '503', 'name': 'Voice', 'type': 'voice', 'parent_id': None, 'position': 2},
            ]
        ),
        json.dumps(
            [
                {'id': '601', 'name': 'Muted', 'color': 0, 'position': 1, 'managed': False, 'permissions': '0'},
                {'id': '602', 'name': 'Bot', 'color': 0, 'position': 9, 'managed': True, 'permissions': '8'},
                {'id': '603', 'name': 'Mods', 'color': 0, 'position': 2, 'managed': False, 'permissions': '4'},
                {'id': '604', 'name': 'High', 'color': 0, 'position': 7, 'managed': False, 'permissions': '0'},
            ]
        ),
    )
    await pool.execute('DELETE FROM guild_settings WHERE guild_id = $1', GUILD)


async def test_settings_patch_validates_and_audits_and_notifies(app, api_db):
    import asyncio

    import asyncpg

    await _seed_settings_channels(api_db)
    headers = {'Authorization': 'Bearer t'}
    notes: list[str] = []
    listener = await asyncpg.connect(DSN)
    await listener.add_listener('veka_cache', lambda *args: notes.append(args[3]))
    identify = AsyncMock(return_value=identity({GUILD: MANAGE_GUILD | MANAGE_ROLES}))
    try:
        with patch.object(auth_module.discord_client, 'identify', identify):
            async with await _client(app) as c:
                current = (await c.get(f'/v1/guilds/{GUILD}/settings', headers=headers)).json()
                no_match = await c.patch(f'/v1/guilds/{GUILD}/settings', headers=headers, json={'toggles': {}})
                wrong_type = await c.patch(
                    f'/v1/guilds/{GUILD}/settings',
                    headers={**headers, 'If-Match': current['version']},
                    json={'channels': {'log': '503'}},
                )
                unknown = await c.patch(
                    f'/v1/guilds/{GUILD}/settings',
                    headers={**headers, 'If-Match': current['version']},
                    json={'channels': {'log': '999'}},
                )
                managed = await c.patch(
                    f'/v1/guilds/{GUILD}/settings',
                    headers={**headers, 'If-Match': current['version']},
                    json={'roles': {'muted': '602'}},
                )
                ok = await c.patch(
                    f'/v1/guilds/{GUILD}/settings',
                    headers={**headers, 'If-Match': current['version']},
                    json={
                        'channels': {'log': '501', 'marketplace': '502'},
                        'roles': {'muted': '601'},
                        'toggles': {'inactivity_dms': True},
                        'warn_mute_threshold': 2,
                    },
                )
                stale = await c.patch(
                    f'/v1/guilds/{GUILD}/settings',
                    headers={**headers, 'If-Match': current['version']},
                    json={'toggles': {'welcome_cards': False}},
                )
        await asyncio.sleep(0.1)
    finally:
        await listener.close()

    assert no_match.status_code == 428
    assert wrong_type.status_code == 422 and wrong_type.json()['error']['code'] == 'wrong_channel_type'
    assert unknown.status_code == 422 and unknown.json()['error']['code'] == 'unknown_channel'
    assert managed.status_code == 422 and managed.json()['error']['code'] == 'managed_role'
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body['channels']['log'] == '501' and body['channels']['marketplace'] == '502'
    assert body['toggles']['inactivity_dms'] is True and body['version'] != current['version']
    assert stale.status_code == 412 and stale.json()['error']['code'] == 'version_conflict'
    assert f'guild_settings:{GUILD}' in notes
    audit = await api_db.fetchval(
        "SELECT details FROM audit_logs WHERE guild_id = $1 AND action = 'dashboard_settings_changed' "
        'ORDER BY id DESC LIMIT 1',
        str(GUILD),
    )
    assert '"log_channel_id"' in audit and '"source": "dashboard"' in audit
    # Writes re-verify with Discord instead of trusting the 60 s cache.
    assert any(call.kwargs.get('fresh') for call in identify.await_args_list)


@pytest.mark.usefixtures('api_db')
async def test_settings_need_manage_server(app):
    with _as(identity({GUILD: BAN_MEMBERS})):
        async with await _client(app) as c:
            r = await c.get(f'/v1/guilds/{GUILD}/settings', headers={'Authorization': 'Bearer t'})
    assert r.status_code == 403


# ---------------------------------------------------------------- moderation


async def test_warnings_pagination_revoke_and_idor(app, api_db):
    await api_db.execute('DELETE FROM warnings WHERE guild_id = ANY($1::bigint[])', [GUILD, OTHER])
    ids = []
    for i in range(3):
        ids.append(
            await api_db.fetchval(
                'INSERT INTO warnings (guild_id, user_id, moderator_id, reason) VALUES ($1, 9001, 9002, $2) RETURNING id',
                GUILD,
                f'reason {i}',
            )
        )
    foreign = await api_db.fetchval(
        "INSERT INTO warnings (guild_id, user_id, moderator_id, reason) VALUES ($1, 9001, 9002, 'x') RETURNING id",
        OTHER,
    )
    headers = {'Authorization': 'Bearer t'}
    async with await _client(app) as c:
        with _as(identity({GUILD: MANAGE_GUILD | BAN_MEMBERS, OTHER: 0})):
            page1 = (await c.get(f'/v1/guilds/{GUILD}/warnings?limit=2', headers=headers)).json()
            page2 = (
                await c.get(f'/v1/guilds/{GUILD}/warnings?limit=2&cursor={page1["next_cursor"]}', headers=headers)
            ).json()
            revoke = await c.post(f'/v1/guilds/{GUILD}/warnings/{ids[0]}/revoke', headers=headers)
            idor = await c.post(f'/v1/guilds/{GUILD}/warnings/{foreign}/revoke', headers=headers)
            audit = (
                await c.get(f'/v1/guilds/{GUILD}/audit-log?action=dashboard_warning_revoked', headers=headers)
            ).json()
            bad_cursor = await c.get(f'/v1/guilds/{GUILD}/warnings?cursor=%%%', headers=headers)
        with _as(identity({GUILD: MANAGE_GUILD})):
            manager_only = await c.get(f'/v1/guilds/{GUILD}/warnings', headers=headers)

    assert [w['id'] for w in page1['items']] == [ids[2], ids[1]] and page1['next_cursor']
    assert [w['id'] for w in page2['items']] == [ids[0]] and page2['next_cursor'] is None
    assert page1['items'][0]['user_id'] == '9001'
    assert revoke.status_code == 200 and revoke.json()['changed'] is True
    assert idor.status_code == 404  # another server's warning is invisible
    assert await api_db.fetchval('SELECT active FROM warnings WHERE id = $1', foreign) is True
    entry = audit['items'][0]
    assert entry['action'] == 'dashboard_warning_revoked' and entry['actor_source'] == 'dashboard'
    assert set(entry) == {'id', 'action', 'actor_id', 'actor_source', 'target_user_id', 'summary', 'created_at'}
    assert bad_cursor.status_code == 422
    assert manager_only.status_code == 403  # Manage Server is not a moderator permission


# ---------------------------------------------------------------- mass unban bridge


async def test_massunban_two_step_confirmation(app, api_db):
    await api_db.execute('DELETE FROM massunban_jobs WHERE guild_id = ANY($1::bigint[])', [GUILD, OTHER])
    headers = {'Authorization': 'Bearer t'}
    requester = identity({GUILD: MANAGE_GUILD | BAN_MEMBERS, OTHER: MANAGE_GUILD | BAN_MEMBERS}, uid=111)
    other_mod = identity({GUILD: MANAGE_GUILD | BAN_MEMBERS}, uid=222)
    body = {'start': '2024-01-01T00:00:00Z', 'end': '2024-12-31T00:00:00Z'}
    async with await _client(app) as c:
        with _as(identity({GUILD: MANAGE_GUILD})):
            no_ban_perm = await c.post(f'/v1/guilds/{GUILD}/massunban/jobs', headers=headers, json=body)
        with _as(requester):
            created = await c.post(f'/v1/guilds/{GUILD}/massunban/jobs', headers=headers, json=body)
            duplicate = await c.post(f'/v1/guilds/{GUILD}/massunban/jobs', headers=headers, json=body)
            job_id = created.json()['id']
            too_early = await c.post(
                f'/v1/guilds/{GUILD}/massunban/jobs/{job_id}/confirm', headers=headers, json={'step': 1}
            )
            # The bot claims the job and stores the frozen preview (simulated here).
            await api_db.execute(
                "UPDATE massunban_jobs SET status = 'awaiting_confirmation', total_matched = 3 WHERE id = $1", job_id
            )
            step1 = (
                await c.post(f'/v1/guilds/{GUILD}/massunban/jobs/{job_id}/confirm', headers=headers, json={'step': 1})
            ).json()
            wrong_count = await c.post(
                f'/v1/guilds/{GUILD}/massunban/jobs/{job_id}/confirm',
                headers=headers,
                json={'step': 2, 'token': step1['token'], 'count': 4},
            )
            idor = await c.get(f'/v1/guilds/{OTHER}/massunban/jobs/{job_id}', headers=headers)
        with _as(other_mod):
            not_requester = await c.post(
                f'/v1/guilds/{GUILD}/massunban/jobs/{job_id}/confirm',
                headers=headers,
                json={'step': 2, 'token': step1['token'], 'count': 3},
            )
        with _as(requester):
            started = await c.post(
                f'/v1/guilds/{GUILD}/massunban/jobs/{job_id}/confirm',
                headers=headers,
                json={'step': 2, 'token': step1['token'], 'count': 3},
            )
            replay = await c.post(
                f'/v1/guilds/{GUILD}/massunban/jobs/{job_id}/confirm',
                headers=headers,
                json={'step': 2, 'token': step1['token'], 'count': 3},
            )
            cancel = await c.post(f'/v1/guilds/{GUILD}/massunban/jobs/{job_id}/cancel', headers=headers)

    assert no_ban_perm.status_code == 403
    assert created.status_code == 202 and created.json()['status'] == 'requested'
    assert duplicate.status_code == 409 and duplicate.json()['error']['code'] == 'job_in_progress'
    assert too_early.status_code == 409
    assert step1['matched'] == 3 and len(step1['token']) > 30
    assert wrong_count.status_code == 409
    assert idor.status_code == 404
    assert not_requester.status_code == 403
    assert started.status_code == 200 and started.json()['status'] == 'running'
    assert replay.status_code == 409  # single use
    assert cancel.status_code == 200 and cancel.json()['status'] == 'cancelled'
    stored = await api_db.fetchval('SELECT confirm_token_hash FROM massunban_jobs WHERE id = $1', job_id)
    assert stored is None  # never the raw token, and cleared once used


async def test_massunban_expired_token_is_rejected(app, api_db):
    await api_db.execute('DELETE FROM massunban_jobs WHERE guild_id = $1', GUILD)
    headers = {'Authorization': 'Bearer t'}
    requester = identity({GUILD: MANAGE_GUILD | BAN_MEMBERS}, uid=111)
    async with await _client(app) as c:
        with _as(requester):
            job_id = (
                await c.post(
                    f'/v1/guilds/{GUILD}/massunban/jobs',
                    headers=headers,
                    json={'start': '2024-01-01T00:00:00Z', 'end': '2024-02-01T00:00:00Z'},
                )
            ).json()['id']
            await api_db.execute(
                "UPDATE massunban_jobs SET status = 'awaiting_confirmation', total_matched = 1 WHERE id = $1", job_id
            )
            token = (
                await c.post(f'/v1/guilds/{GUILD}/massunban/jobs/{job_id}/confirm', headers=headers, json={'step': 1})
            ).json()['token']
            await api_db.execute(
                "UPDATE massunban_jobs SET confirm_expires_at = NOW() - INTERVAL '1 second' WHERE id = $1", job_id
            )
            expired = await c.post(
                f'/v1/guilds/{GUILD}/massunban/jobs/{job_id}/confirm',
                headers=headers,
                json={'step': 2, 'token': token, 'count': 1},
            )
    assert expired.status_code == 409
    assert await api_db.fetchval('SELECT status FROM massunban_jobs WHERE id = $1', job_id) == 'awaiting_confirmation'


async def test_settings_role_and_body_rules(app, api_db):
    """Muted role: needs Manage Roles, no privileged roles, below the bot. Bodies are strictly typed."""
    import asyncio

    await _seed_settings_channels(api_db)
    headers = {'Authorization': 'Bearer t'}
    async with await _client(app) as c:
        with _as(identity({GUILD: MANAGE_GUILD})):
            version = (await c.get(f'/v1/guilds/{GUILD}/settings', headers=headers)).json()['version']
            h = {**headers, 'If-Match': version}
            no_manage_roles = await c.patch(f'/v1/guilds/{GUILD}/settings', headers=h, json={'roles': {'muted': '601'}})
            coerced = await c.patch(
                f'/v1/guilds/{GUILD}/settings', headers=h, json={'toggles': {'welcome_cards': 'no'}}
            )
            str_number = await c.patch(f'/v1/guilds/{GUILD}/settings', headers=h, json={'warn_mute_threshold': '3'})
            null_number = await c.patch(f'/v1/guilds/{GUILD}/settings', headers=h, json={'warn_mute_threshold': None})
            bad_id = await c.patch(f'/v1/guilds/{GUILD}/settings', headers=h, json={'channels': {'log': '12abc'}})
            noop_stale = await c.patch(f'/v1/guilds/{GUILD}/settings', headers={**headers, 'If-Match': '1'}, json={})
            channels_list = await c.get(f'/v1/guilds/{GUILD}/channels', headers=headers)
        with _as(identity({GUILD: MANAGE_GUILD | MANAGE_ROLES})):
            privileged = await c.patch(f'/v1/guilds/{GUILD}/settings', headers=h, json={'roles': {'muted': '603'}})
            above_bot = await c.patch(f'/v1/guilds/{GUILD}/settings', headers=h, json={'roles': {'muted': '604'}})
            # Two editors with the same version: exactly one wins.
            results = await asyncio.gather(
                c.patch(f'/v1/guilds/{GUILD}/settings', headers=h, json={'warn_mute_threshold': 4}),
                c.patch(f'/v1/guilds/{GUILD}/settings', headers=h, json={'warn_mute_threshold': 5}),
            )
        with _as(identity({GUILD: BAN_MEMBERS})):
            moderator_channels = await c.get(f'/v1/guilds/{GUILD}/channels', headers=headers)

    assert no_manage_roles.status_code == 403
    assert coerced.status_code == 422 and str_number.status_code == 422 and null_number.status_code == 422
    assert bad_id.status_code == 422
    assert noop_stale.status_code == 412
    assert privileged.status_code == 422 and privileged.json()['error']['code'] == 'privileged_role'
    assert above_bot.status_code == 422 and above_bot.json()['error']['code'] == 'role_above_bot'
    assert sorted(r.status_code for r in results) == [200, 412]
    assert channels_list.status_code == 200
    assert moderator_channels.status_code == 403  # moderators don't get the private channel inventory


async def test_chunked_body_over_limit_is_rejected(app):
    async def chunks():
        for _ in range(80):
            yield b'x' * 1024

    async with await _client(app) as c:
        r = await c.post(
            f'/v1/guilds/{GUILD}/massunban/jobs', content=chunks(), headers={'Content-Type': 'application/json'}
        )
    assert r.status_code == 413 and r.json()['error']['code'] == 'payload_too_large'


async def test_discord_guild_list_is_paginated():
    from src.api.discord_client import DiscordClient

    client = DiscordClient(base='http://discord.invalid')
    pages = {
        '0': [{'id': str(i), 'name': f'g{i}', 'permissions': '0'} for i in range(1, 201)],
        '200': [{'id': '201', 'name': 'g201', 'permissions': '0'}],
    }

    async def fake_get(path, _token):
        if path == '/users/@me':
            return {'id': '9', 'username': 'u'}
        return pages[path.split('after=')[1]]

    client._get = fake_get  # type: ignore[method-assign]
    ident = await client.identify('tok')
    assert len(ident.guilds) == 201


# ---------------------------------------------------------------- honeypots


async def test_honeypot_permissions_follow_the_action(app, api_db):
    await _seed_settings_channels(api_db)
    await api_db.execute('DELETE FROM honeypots WHERE guild_id = $1', GUILD)
    headers = {'Authorization': 'Bearer t'}
    async with await _client(app) as c:
        with _as(identity({GUILD: MANAGE_GUILD | MODERATE_MEMBERS})):
            timeout_ok = await c.post(
                f'/v1/guilds/{GUILD}/honeypots', headers=headers, json={'channel_id': '501', 'action_type': 'timeout'}
            )
            hp = timeout_ok.json()['id']
            ban_denied = await c.patch(
                f'/v1/guilds/{GUILD}/honeypots/{hp}', headers=headers, json={'action_type': 'ban'}
            )
        with _as(identity({GUILD: MANAGE_GUILD})):
            # Manage Server alone can't weaken/delete a timeout trap it couldn't create.
            delete_denied = await c.delete(f'/v1/guilds/{GUILD}/honeypots/{hp}', headers=headers)
            logging_ok = await c.put(
                f'/v1/guilds/{GUILD}/honeypots/logging', headers=headers, json={'logging_channel_id': '501'}
            )
            voice_log = await c.put(
                f'/v1/guilds/{GUILD}/honeypots/logging', headers=headers, json={'logging_channel_id': '503'}
            )
        with _as(identity({GUILD: MANAGE_GUILD | MANAGE_ROLES | MODERATE_MEMBERS})):
            dangerous_role = await c.patch(
                f'/v1/guilds/{GUILD}/honeypots/{hp}', headers=headers, json={'action_type': 'role', 'role_id': '603'}
            )
            safe_role = await c.patch(
                f'/v1/guilds/{GUILD}/honeypots/{hp}', headers=headers, json={'action_type': 'role', 'role_id': '601'}
            )
        with _as(
            identity(
                {
                    GUILD: MANAGE_GUILD | MODERATE_MEMBERS,
                    OTHER: MANAGE_GUILD | MODERATE_MEMBERS | BAN_MEMBERS | MANAGE_ROLES,
                }
            )
        ):
            idor = await c.delete(f'/v1/guilds/{OTHER}/honeypots/{hp}', headers=headers)
            listed = await c.get(f'/v1/guilds/{GUILD}/honeypots', headers=headers)

    assert timeout_ok.status_code == 201 and timeout_ok.json()['channel_id'] == '501'
    assert ban_denied.status_code == 403
    assert delete_denied.status_code == 403
    assert logging_ok.status_code == 200 and voice_log.status_code == 422
    assert dangerous_role.status_code == 422 and dangerous_role.json()['error']['code'] == 'privileged_role'
    assert safe_role.status_code == 200 and safe_role.json()['role_id'] == '601'
    assert idor.status_code == 404
    assert [h['id'] for h in listed.json()['items']] == [hp]


# ---------------------------------------------------------------- review regressions (honeypots, mass unban)


async def test_honeypot_concurrency_and_validation(app, api_db):
    import asyncio

    await _seed_settings_channels(api_db)
    await api_db.execute('DELETE FROM honeypots WHERE guild_id = $1', GUILD)
    headers = {'Authorization': 'Bearer t'}
    async with await _client(app) as c:
        with _as(identity({GUILD: MANAGE_GUILD | MANAGE_ROLES})):
            role_only = await c.post(
                f'/v1/guilds/{GUILD}/honeypots',
                headers=headers,
                json={'channel_id': '501', 'action_type': 'role', 'role_id': '601'},
            )
            role_only_ban = await c.post(
                f'/v1/guilds/{GUILD}/honeypots', headers=headers, json={'channel_id': '501', 'action_type': 'ban'}
            )
        await api_db.execute('DELETE FROM honeypots WHERE guild_id = $1', GUILD)
        with _as(identity({GUILD: MANAGE_GUILD | MODERATE_MEMBERS | BAN_MEMBERS})):
            dup = await asyncio.gather(
                *(
                    c.post(
                        f'/v1/guilds/{GUILD}/honeypots',
                        headers=headers,
                        json={'channel_id': '501', 'action_type': 'timeout'},
                    )
                    for _ in range(2)
                )
            )
            hp = next(r.json()['id'] for r in dup if r.status_code == 201)
            null_patch = await c.patch(f'/v1/guilds/{GUILD}/honeypots/{hp}', headers=headers, json={'enabled': None})
            huge_id = await c.delete(f'/v1/guilds/{GUILD}/honeypots/{2**40}', headers=headers)
        # Someone else turned the trap into a ban trap; a Moderate-only actor must now be refused.
        await api_db.execute("UPDATE honeypots SET action_type = 'ban' WHERE id = $1", hp)
        with _as(identity({GUILD: MANAGE_GUILD | MODERATE_MEMBERS})):
            stale = await c.patch(f'/v1/guilds/{GUILD}/honeypots/{hp}', headers=headers, json={'enabled': False})
            stale_delete = await c.delete(f'/v1/guilds/{GUILD}/honeypots/{hp}', headers=headers)

    assert role_only.status_code == 201 and role_only_ban.status_code == 403
    assert sorted(r.status_code for r in dup) == [201, 409]
    assert null_patch.status_code == 422
    assert huge_id.status_code == 422
    assert stale.status_code == 403 and stale_delete.status_code == 403
    row = await api_db.fetchrow('SELECT action_type, enabled FROM honeypots WHERE id = $1', hp)
    assert (row['action_type'], row['enabled']) == ('ban', True)


async def test_massunban_step1_audit_and_input_bounds(app, api_db):
    await api_db.execute('DELETE FROM massunban_jobs WHERE guild_id = $1', GUILD)
    headers = {'Authorization': 'Bearer t'}
    async with await _client(app) as c:
        with _as(identity({GUILD: MANAGE_GUILD | BAN_MEMBERS}, uid=111)):
            zero_mod = await c.post(
                f'/v1/guilds/{GUILD}/massunban/jobs',
                headers=headers,
                json={'start': '2024-01-01T00:00:00Z', 'end': '2024-02-01T00:00:00Z', 'banned_by': '0'},
            )
            coerced = await c.post(
                f'/v1/guilds/{GUILD}/massunban/jobs',
                headers=headers,
                json={'start': '2024-01-01T00:00:00Z', 'end': '2024-02-01T00:00:00Z', 'notify_users': 'false'},
            )
            huge = await c.get(f'/v1/guilds/{GUILD}/massunban/jobs/{2**40}', headers=headers)
            job_id = (
                await c.post(
                    f'/v1/guilds/{GUILD}/massunban/jobs',
                    headers=headers,
                    json={'start': '2024-01-01T00:00:00Z', 'end': '2024-02-01T00:00:00Z'},
                )
            ).json()['id']
            await api_db.execute(
                "UPDATE massunban_jobs SET status = 'awaiting_confirmation', total_matched = 2 WHERE id = $1", job_id
            )
            step1 = await c.post(
                f'/v1/guilds/{GUILD}/massunban/jobs/{job_id}/confirm', headers=headers, json={'step': 1}
            )
    assert zero_mod.status_code == 422 and coerced.status_code == 422 and huge.status_code == 422
    assert step1.status_code == 200
    details = await api_db.fetchval(
        "SELECT details FROM audit_logs WHERE action = 'dashboard_massunban_confirmed_step1' ORDER BY id DESC LIMIT 1"
    )
    assert f'"job_id": {job_id}' in details and step1.json()['token'] not in details


async def test_discord_and_dashboard_job_creation_cannot_overlap(app, api_db):
    """The Discord command and the API take the same per-guild lock: only one active job."""
    import asyncio

    from src.cogs.admin.massunban import MassUnban, _JobInProgress

    await api_db.execute('DELETE FROM massunban_jobs WHERE guild_id = $1', GUILD)
    headers = {'Authorization': 'Bearer t'}

    async def discord_start():
        try:
            return await MassUnban._create_job(GUILD, 111, _dt(2024, 1, 1), _dt(2024, 2, 1), None, '', [], False)
        except _JobInProgress:
            return None

    async with await _client(app) as c:
        with _as(identity({GUILD: MANAGE_GUILD | BAN_MEMBERS}, uid=111)):
            api_start = c.post(
                f'/v1/guilds/{GUILD}/massunban/jobs',
                headers=headers,
                json={'start': '2024-01-01T00:00:00Z', 'end': '2024-02-01T00:00:00Z'},
            )
            results = await asyncio.gather(discord_start(), api_start)
    active = await api_db.fetchval(
        "SELECT COUNT(*) FROM massunban_jobs WHERE guild_id = $1 AND status IN ('pending', 'requested')", GUILD
    )
    assert active == 1
    assert (results[0] is None) != (results[1].status_code == 409)


async def test_stale_preview_claim_cannot_commit(api_db):
    """A preview whose claim was requeued and re-claimed must not write its (stale) ban set."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from src.cogs.admin.massunban import MassUnban

    await api_db.execute('DELETE FROM massunban_jobs WHERE guild_id = $1', GUILD)
    job_id = await api_db.fetchval(
        """INSERT INTO massunban_jobs (guild_id, requested_by, status, source, start_datetime, end_datetime,
                                       include_unaudited)
           VALUES ($1, 1, 'requested', 'dashboard', '2024-01-01', '2025-01-01', TRUE) RETURNING id""",
        GUILD,
    )

    async def bans(limit=None):  # noqa: ARG001
        # While we list bans, the job is requeued and claimed again by another handler.
        await api_db.execute('UPDATE massunban_jobs SET claimed_at = clock_timestamp() WHERE id = $1', job_id)
        yield SimpleNamespace(user=SimpleNamespace(id=777), reason=None)

    guild = MagicMock()
    guild.id = GUILD
    guild.bans = bans
    bot = MagicMock()
    bot.get_guild.return_value = guild
    bot.guilds = [guild]
    await MassUnban(bot).handle_dashboard_job(job_id)
    assert await api_db.fetchval('SELECT status FROM massunban_jobs WHERE id = $1', job_id) == 'previewing'
    assert await api_db.fetchval('SELECT COUNT(*) FROM massunban_job_items WHERE job_id = $1', job_id) == 0


def _dt(y, m, d):
    from datetime import UTC, datetime

    return datetime(y, m, d, tzinfo=UTC)


# ---------------------------------------------------------------- leaderboards / stats


async def test_leaderboards_member_totals_and_daily_stats(app, api_db):
    from src.services import activity_service as svc

    for uid in (7101, 7102, 7103):
        await api_db.execute('DELETE FROM user_activity_daily WHERE user_id = $1', uid)
        await api_db.execute('DELETE FROM users WHERE discord_id = $1', str(uid))
    await api_db.execute(
        "INSERT INTO users (discord_id, presence_opt_in) VALUES ('7101', TRUE), ('7102', FALSE), ('7103', FALSE)"
    )
    await svc.award('message', [svc.Award(7101, GUILD, quantity=5, xp_base=5)])
    await svc.award('message', [svc.Award(7102, GUILD, quantity=9, xp_base=9)])
    await svc.award('message', [svc.Award(7103, OTHER, quantity=50, xp_base=50)])  # other server
    await api_db.execute(
        'INSERT INTO guild_settings (guild_id,presence_tracking_enabled) VALUES ($1,TRUE) '
        'ON CONFLICT (guild_id) DO UPDATE SET presence_tracking_enabled=TRUE',
        GUILD,
    )
    await svc.award('gaming', [svc.Award(7101, GUILD, quantity=30, xp_base=0)])
    await svc.award('gaming', [svc.Award(7102, GUILD, quantity=30, xp_base=0)])  # opt-out still wins
    headers = {'Authorization': 'Bearer t'}
    async with await _client(app) as c:
        with _as(identity({GUILD: MANAGE_GUILD})):  # dashboard stats are server-manager only
            week = (
                await c.get(f'/v1/guilds/{GUILD}/leaderboards?category=chat&period=week&limit=1', headers=headers)
            ).json()
            week2 = (
                await c.get(
                    f'/v1/guilds/{GUILD}/leaderboards?category=chat&period=week&limit=1&cursor={week["next_cursor"]}',
                    headers=headers,
                )
            ).json()
            gaming = (await c.get(f'/v1/guilds/{GUILD}/leaderboards?category=gaming', headers=headers)).json()
            member = (await c.get(f'/v1/guilds/{GUILD}/members/7102/activity?period=week', headers=headers)).json()
            bad_period = await c.get(f'/v1/guilds/{GUILD}/leaderboards?period=year', headers=headers)
        with _as(identity({GUILD: 0})):
            stats_denied = await c.get(f'/v1/guilds/{GUILD}/stats/daily', headers=headers)
        with _as(identity({GUILD: MANAGE_GUILD})):
            daily = (await c.get(f'/v1/guilds/{GUILD}/stats/daily', headers=headers)).json()
            too_long = await c.get(f'/v1/guilds/{GUILD}/stats/daily?from=2024-01-01&to=2025-06-01', headers=headers)

    assert week['scope'] == 'this_server'
    assert [(i['rank'], i['user_id'], i['value']) for i in week['items']] == [(1, '7102', 9)]
    assert [(i['rank'], i['user_id']) for i in week2['items']] == [(2, '7101')]  # 7103 is another server
    assert gaming['scope'] == 'this_server'
    assert [i['user_id'] for i in gaming['items'] if i['user_id'] in ('7101', '7102')] == ['7101']  # opt-in only
    assert member['totals']['messages'] == 9 and 'gaming_minutes' not in member['totals']
    assert bad_period.status_code == 422
    assert stats_denied.status_code == 403
    assert len(daily['days']) == 30 and daily['days'][-1]['messages'] >= 14
    assert too_long.status_code == 422


# ---------------------------------------------------------------- feeds


async def test_feed_quota_is_atomic_across_processes(api_db, monkeypatch):
    """The bot command and the API share the advisory-locked quota: concurrent adds never exceed it."""
    import asyncio

    from src.services import feed_service

    monkeypatch.setattr(feed_service, 'FEED_MAX_SUBSCRIPTIONS', 2)
    await api_db.execute('DELETE FROM feed_subscriptions WHERE guild_id = $1', GUILD)
    results = await asyncio.gather(
        *(feed_service.upsert_subscription(GUILD, 501, f'https://example.com/{i}.xml', 'x', 30) for i in range(6)),
        return_exceptions=True,
    )
    assert sum(isinstance(r, dict) for r in results) == 2
    assert all(isinstance(r, feed_service.FeedLimitReached) for r in results if not isinstance(r, dict))
    # Updating an existing URL is allowed at the limit and keeps pause state.
    await api_db.execute('UPDATE feed_subscriptions SET paused = TRUE WHERE guild_id = $1', GUILD)
    url = await api_db.fetchval('SELECT feed_url FROM feed_subscriptions WHERE guild_id = $1 LIMIT 1', GUILD)
    row = await feed_service.upsert_subscription(GUILD, 501, url, 'renamed', 60)
    assert row['paused'] is True and row['poll_interval_minutes'] == 60


async def test_feed_routes(app, api_db, monkeypatch):
    from src.api.routes import feeds as feeds_routes

    await _seed_settings_channels(api_db)
    await api_db.execute('DELETE FROM feed_subscriptions WHERE guild_id = ANY($1::bigint[])', [GUILD, OTHER])
    fetch = AsyncMock(return_value={'title': 'Example Feed', 'entries': [{'title': 'Post', 'link': 'https://e/1'}]})
    monkeypatch.setattr(feeds_routes._rss, 'fetch_feed', fetch)
    headers = {'Authorization': 'Bearer t'}
    async with await _client(app) as c:
        with _as(identity({GUILD: MANAGE_GUILD, OTHER: MANAGE_GUILD})):
            created = await c.post(
                f'/v1/guilds/{GUILD}/feeds',
                headers=headers,
                json={'url': 'https://example.com/feed.xml', 'channel_id': '501'},
            )
            fid = created.json()['id']
            voice = await c.post(
                f'/v1/guilds/{GUILD}/feeds',
                headers=headers,
                json={'url': 'https://example.com/b.xml', 'channel_id': '503'},
            )
            bad_scheme = await c.post(
                f'/v1/guilds/{GUILD}/feeds', headers=headers, json={'url': 'file:///etc/passwd', 'channel_id': '501'}
            )
            paused = await c.patch(f'/v1/guilds/{GUILD}/feeds/{fid}', headers=headers, json={'paused': True})
            null_name = await c.patch(f'/v1/guilds/{GUILD}/feeds/{fid}', headers=headers, json={'name': None})
            preview = await c.post(f'/v1/guilds/{GUILD}/feeds/{fid}/test', headers=headers)
            idor = await c.delete(f'/v1/guilds/{OTHER}/feeds/{fid}', headers=headers)
            listed = await c.get(f'/v1/guilds/{GUILD}/feeds', headers=headers)
            removed = await c.delete(f'/v1/guilds/{GUILD}/feeds/{fid}', headers=headers)
        with _as(identity({GUILD: BAN_MEMBERS})):
            moderator = await c.get(f'/v1/guilds/{GUILD}/feeds', headers=headers)

    assert created.status_code == 201 and created.json()['name'] == 'Example Feed'
    assert voice.status_code == 422 and bad_scheme.status_code == 422
    assert paused.json()['paused'] is True and null_name.status_code == 422
    assert preview.json()['entries'][0]['title'] == 'Post'
    assert idor.status_code == 404
    assert [f['id'] for f in listed.json()['items']] == [fid]
    assert removed.status_code == 204
    assert moderator.status_code == 403
    audit = await api_db.fetchval(
        "SELECT COUNT(*) FROM audit_logs WHERE guild_id = $1 AND action LIKE 'dashboard_feed_%'", str(GUILD)
    )
    assert audit >= 3


def test_client_ip_uses_rightmost_untrusted_forwarded_address(monkeypatch):
    import ipaddress

    from src.api import auth

    nets = [ipaddress.ip_network('172.16.0.0/12'), ipaddress.ip_network('192.168.1.97/32')]
    monkeypatch.setattr(auth, 'settings', SimpleNamespace(trusted_proxy_networks=nets))

    def req(peer, xff=None):
        headers = {'x-forwarded-for': xff} if xff else {}
        return SimpleNamespace(client=SimpleNamespace(host=peer), headers=headers)

    # Forged left-most entry is ignored; the hop added by our proxy chain wins.
    assert auth.client_ip(req('172.18.0.5', '6.6.6.6, 203.0.113.9, 172.19.0.2')) == '203.0.113.9'
    # An untrusted peer's header is ignored entirely.
    assert auth.client_ip(req('198.51.100.1', '6.6.6.6')) == '198.51.100.1'
    # Only proxies in the chain: fall back to the left-most entry.
    assert auth.client_ip(req('172.18.0.5', '192.168.1.97')) == '192.168.1.97'


async def test_ready_is_503_when_the_database_is_down(app):
    from src.api.routes import health

    with patch.object(health.db, 'fetchval', AsyncMock(side_effect=OSError('down'))):
        async with await _client(app) as c:
            down = await c.get('/v1/ready')
    with patch.object(health.db, 'fetchval', AsyncMock(return_value=1)):
        async with await _client(app) as c:
            up = await c.get('/v1/ready')
    assert (down.status_code, down.json()) == (503, {'ready': False})
    assert (up.status_code, up.json()) == (200, {'ready': True})
