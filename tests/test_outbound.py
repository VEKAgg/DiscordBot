"""Shared outbound guard: budgets, de-duplication, status edits, 429 handling and the circuit breaker."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import nextcord
import pytest

from src.utils.outbound import OutboundConfig, OutboundMessenger, SendStatus
from src.utils.ttlcache import TTLDict


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        self.t += seconds


def _http_error(cls, status: int, code: int, headers: dict | None = None):
    response = MagicMock(status=status, reason='x', headers=headers or {})
    return cls(response, {'code': code, 'message': 'x'})


def _channel(cid: int = 1, guild_id: int = 10):
    channel = MagicMock()
    channel.id = cid
    channel.guild = SimpleNamespace(id=guild_id)
    channel.send = AsyncMock(side_effect=lambda **_kw: MagicMock(id=999, edit=AsyncMock()))
    return channel


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def messenger(clock):
    return OutboundMessenger(OutboundConfig(), clock=clock, sleep=clock.sleep)


async def test_identical_alerts_collapse_into_one(messenger):
    channel = _channel()
    embed = nextcord.Embed(title='Honeypot Triggered', description='same text')
    outcomes = [await messenger.send(channel, kind='alert', embed=embed, essential=True) for _ in range(10)]

    assert channel.send.await_count == 1
    assert outcomes[0].status == SendStatus.SENT
    assert all(o.status == SendStatus.DEDUPED for o in outcomes[1:])


async def test_dedupe_expires_after_window(messenger, clock):
    channel = _channel()
    await messenger.send(channel, kind='alert', content='x', dedupe_window=60)
    clock.t += 61
    await messenger.send(channel, kind='alert', content='x', dedupe_window=60)
    assert channel.send.await_count == 2


async def test_non_essential_sends_are_dropped_over_budget(messenger):
    channel = _channel()
    outcomes = [await messenger.send(channel, kind='spam', content=f'msg {i}') for i in range(20)]

    sent = [o for o in outcomes if o.status == SendStatus.SENT]
    assert len(sent) == OutboundConfig().channel_per_5s
    assert channel.send.await_count == len(sent)
    assert messenger.counters['spam:dropped_budget'] == 20 - len(sent)


async def test_essential_sends_wait_for_budget(messenger, clock):
    channel = _channel()
    start = clock.t
    for i in range(8):
        outcome = await messenger.send(channel, kind='summary', content=f'{i}', essential=True)
        assert outcome.status == SendStatus.SENT
    assert channel.send.await_count == 8
    assert clock.t > start  # had to wait for the channel bucket to refill


async def test_breaker_opens_once_pauses_and_recovers(clock):
    alert = AsyncMock()
    messenger = OutboundMessenger(
        OutboundConfig(breaker_threshold=3, breaker_cooldown=600), clock=clock, sleep=clock.sleep
    )
    messenger.bind(cast(Any, SimpleNamespace(guilds=[])), alert=alert)

    failing = _channel(cid=2)
    failing.send = AsyncMock(side_effect=_http_error(nextcord.Forbidden, 403, 50013))
    for i in range(3):
        assert (await messenger.send(failing, kind='log', content=str(i))).status == SendStatus.FORBIDDEN
        clock.t += 6  # stay inside budgets

    healthy = _channel(cid=3)
    paused = await messenger.send(healthy, kind='log', content='after')
    assert paused.status == SendStatus.BREAKER_OPEN
    healthy.send.assert_not_awaited()
    alert.assert_awaited_once()

    # Essential sends (e.g. the admin alert itself) still go through.
    assert (await messenger.send(healthy, kind='admin_alert', content='alert', essential=True)).ok

    clock.t += 601
    assert (await messenger.send(healthy, kind='log', content='recovered')).ok
    alert.assert_awaited_once()


async def test_dm_requires_a_shared_guild(messenger):
    messenger.bind(cast(Any, SimpleNamespace(guilds=[SimpleNamespace(get_member=lambda _uid: None)])))
    user = MagicMock(spec=nextcord.User)
    user.id = 5
    user.send = AsyncMock()

    outcome = await messenger.dm(user, kind='apology', content='hi')

    assert outcome.status == SendStatus.NO_SHARED_GUILD
    user.send.assert_not_awaited()


async def test_dm_budget_is_tight(messenger):
    messenger.bind(cast(Any, SimpleNamespace(guilds=[SimpleNamespace(get_member=lambda _uid: object())])))
    sent = 0
    for i in range(20):
        user = MagicMock(spec=nextcord.User)
        user.id = i
        user.send = AsyncMock(return_value=MagicMock())
        if (await messenger.dm(user, kind='apology', content='same')).ok:
            sent += 1
    assert sent == OutboundConfig().dm_per_minute


async def test_upsert_status_edits_instead_of_posting(messenger):
    channel = _channel()
    first = await messenger.upsert_status('job:1', channel, embed=nextcord.Embed(title='1/10'))
    assert first.status == SendStatus.SENT
    for i in range(2, 11):
        outcome = await messenger.upsert_status('job:1', channel, embed=nextcord.Embed(title=f'{i}/10'))
        assert outcome.status == SendStatus.EDITED
    assert channel.send.await_count == 1
    assert first.message.edit.await_count == 9


async def test_upsert_reposts_when_message_was_deleted(messenger):
    channel = _channel()
    await messenger.upsert_status('job:2', channel, content='a')
    stored = messenger._status_messages.get('job:2')
    stored.edit = AsyncMock(side_effect=_http_error(nextcord.NotFound, 404, 10008))
    outcome = await messenger.upsert_status('job:2', channel, content='b')
    assert outcome.status == SendStatus.SENT
    assert channel.send.await_count == 2


async def test_files_are_not_auto_deduplicated(messenger):
    channel = _channel()
    for i in range(3):
        file = nextcord.File(__file__, filename=f'part{i}.txt')
        assert (await messenger.send(channel, kind='export', file=file, essential=True)).ok
    assert channel.send.await_count == 3


async def test_long_retry_after_is_not_retried_early(messenger):
    channel = _channel()
    channel.send = AsyncMock(side_effect=_http_error(nextcord.HTTPException, 429, 0, {'Retry-After': '120'}))
    outcome = await messenger.send(channel, kind='summary', content='x', essential=True)
    assert outcome.status == SendStatus.FAILED
    assert channel.send.await_count == 1


async def test_short_retry_after_is_honoured_once(messenger, clock):
    channel = _channel()
    ok = MagicMock()
    channel.send = AsyncMock(side_effect=[_http_error(nextcord.HTTPException, 429, 0, {'Retry-After': '2'}), ok])
    before = clock.t
    outcome = await messenger.send(channel, kind='summary', content='x', essential=True)
    assert outcome.ok and outcome.message is ok
    assert clock.t - before >= 2


async def test_failed_send_releases_dedupe_reservation(messenger):
    channel = _channel()
    channel.send = AsyncMock(side_effect=[RuntimeError('network'), MagicMock()])
    assert (await messenger.send(channel, kind='x', content='same')).status == SendStatus.FAILED
    assert (await messenger.send(channel, kind='x', content='same')).ok


async def test_create_thread_routes_through_budget(messenger):
    forum = MagicMock()
    forum.id = 50
    forum.guild = SimpleNamespace(id=10)
    thread = MagicMock(spec=nextcord.Thread)
    forum.create_thread = AsyncMock(return_value=thread)

    outcome = await messenger.create_thread(forum, kind='listing', name='📦 kreo - $100.00', content='x')
    again = await messenger.create_thread(forum, kind='listing', name='📦 kreo - $100.00', content='x')

    assert outcome.ok and outcome.thread is thread
    assert again.status == SendStatus.DEDUPED
    forum.create_thread.assert_awaited_once()


def test_ttldict_expires_and_bounds(clock):
    d: TTLDict[int, str] = TTLDict(ttl=10, maxsize=3, clock=clock)
    for i in range(5):
        d[i] = str(i)
    assert len(d) == 3 and 0 not in d and 4 in d
    clock.t += 11
    assert len(d) == 0
    d.set(1, 'x')
    assert d.get(1) == 'x' and d.pop(1) == 'x' and d.get(1) is None


def test_ttldict_mixed_ttls_expire_independently(clock):
    """Set order isn't expiry order when TTLs differ (Pi review): a long-lived first entry must not
    keep later short-lived entries alive."""
    d: TTLDict[str, int] = TTLDict(ttl=100, maxsize=10, clock=clock)
    d.set('a', 1, ttl=100)
    d.set('b', 2, ttl=1)
    clock.t += 2
    assert len(d) == 1 and 'b' not in d and d.get('a') == 1


async def test_status_locks_are_pruned(messenger):
    channel = _channel()
    for i in range(600):
        await messenger.upsert_status(f'job:{i}', channel, content=str(i))
        messenger.forget_status(f'job:{i}') if i % 2 else messenger._status_messages.pop(f'job:{i}')
    await messenger.upsert_status('last', channel, content='x')
    assert len(messenger._status_locks) <= 501
