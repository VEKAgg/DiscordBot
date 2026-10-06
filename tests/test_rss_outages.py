"""Persistent RSS outage suppression and polling backoff regressions."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.cogs.resources.feeds import Feeds
from src.services.rss_service import RSSService


def subscription(failures=0, interval=30):
    return {
        'id': 1,
        'guild_id': 2,
        'channel_id': 3,
        'feed_url': 'https://example.com/feed',
        'feed_name': 'Example',
        'poll_interval_minutes': interval,
        'last_polled_at': None,
        'consecutive_failures': failures,
        'next_retry_at': None,
    }


@pytest.mark.parametrize(
    'previous,expected_delay,alert',
    [(0, 30, False), (1, 60, False), (2, 120, True), (3, 240, False), (1234, 1440, False)],
)
async def test_failure_backoff_and_one_warning(monkeypatch, previous, expected_delay, alert):
    database = SimpleNamespace(execute=AsyncMock())
    monkeypatch.setattr('src.cogs.resources.feeds.db', database)
    notifier = SimpleNamespace(send_alert=AsyncMock())
    # A fresh cog simulates a restart; persisted failure count still suppresses alerts.
    cog = Feeds(SimpleNamespace(notifier=notifier))
    before = datetime.now(UTC)
    await cog._record_poll_result(subscription(previous), succeeded=False)
    args = database.execute.call_args.args
    assert args[1:3] == (1, previous + 1)
    assert (
        before + timedelta(minutes=expected_delay) <= args[3] <= datetime.now(UTC) + timedelta(minutes=expected_delay)
    )
    assert notifier.send_alert.await_count == int(alert)
    if alert:
        assert notifier.send_alert.call_args.kwargs['guild_id'] == 2


@pytest.mark.parametrize('previous,alerts', [(0, 0), (1, 0), (2, 0), (3, 1), (1235, 1)])
async def test_recovery_resets_persistent_state(monkeypatch, previous, alerts):
    database = SimpleNamespace(execute=AsyncMock())
    monkeypatch.setattr('src.cogs.resources.feeds.db', database)
    notifier = SimpleNamespace(send_alert=AsyncMock())
    await Feeds(SimpleNamespace(notifier=notifier))._record_poll_result(subscription(previous), succeeded=True)
    assert database.execute.call_args.args[1:] == (1, 0, None)
    assert notifier.send_alert.await_count == alerts


async def test_state_persisted_before_warning(monkeypatch):
    notifier = SimpleNamespace(send_alert=AsyncMock())

    async def persist(*_args):
        notifier.send_alert.assert_not_awaited()

    monkeypatch.setattr('src.cogs.resources.feeds.db', SimpleNamespace(execute=AsyncMock(side_effect=persist)))
    await Feeds(SimpleNamespace(notifier=notifier))._record_poll_result(subscription(2), succeeded=False)
    notifier.send_alert.assert_awaited_once()


async def test_db_failure_does_not_send_warning(monkeypatch):
    monkeypatch.setattr(
        'src.cogs.resources.feeds.db', SimpleNamespace(execute=AsyncMock(side_effect=RuntimeError('DB')))
    )
    notifier = SimpleNamespace(send_alert=AsyncMock())
    with pytest.raises(RuntimeError):
        await Feeds(SimpleNamespace(notifier=notifier))._record_poll_result(subscription(2), succeeded=False)
    notifier.send_alert.assert_not_awaited()


@pytest.mark.parametrize('skip', ['backoff', 'interval', 'unconfigured'])
async def test_poller_respects_retry_and_interval(monkeypatch, skip):
    sub = subscription(4)
    if skip == 'backoff':
        sub['next_retry_at'] = datetime.now(UTC) + timedelta(hours=1)
    elif skip == 'interval':
        sub['last_polled_at'] = datetime.now(UTC)
    else:
        sub['channel_id'] = 0
    database = SimpleNamespace(fetch_many=AsyncMock(return_value=[sub]), execute=AsyncMock())
    monkeypatch.setattr('src.cogs.resources.feeds.db', database)
    cog = Feeds(SimpleNamespace())
    fetch = AsyncMock()
    monkeypatch.setattr(cog.rss_service, 'fetch_feed', fetch)
    await cog.feed_update()
    fetch.assert_not_awaited()
    database.execute.assert_not_awaited()


async def test_failed_poll_records_attempt(monkeypatch):
    database = SimpleNamespace(fetch_many=AsyncMock(return_value=[subscription()]), execute=AsyncMock())
    monkeypatch.setattr('src.cogs.resources.feeds.db', database)
    cog = Feeds(SimpleNamespace())
    monkeypatch.setattr(cog.rss_service, 'fetch_feed', AsyncMock(return_value=None))
    await cog.feed_update()
    assert database.execute.call_args.args[2] == 1
    assert 'last_polled_at = NOW()' in database.execute.call_args.args[0]


@pytest.mark.parametrize('status,content', [(403, b''), (410, b''), (200, b'<html>blocked</html>')])
async def test_fetch_failure_never_sends_untracked_alert(monkeypatch, status, content):
    monkeypatch.setattr('src.services.rss_service.fetch_public_url', AsyncMock(return_value=(status, content)))
    notifier = SimpleNamespace(send_alert=AsyncMock())
    assert await RSSService(SimpleNamespace(notifier=notifier)).fetch_feed('https://example.com') is None
    notifier.send_alert.assert_not_awaited()


async def test_valid_empty_feed_is_healthy(monkeypatch):
    xml = b'<?xml version="1.0"?><rss version="2.0"><channel><title>Empty</title></channel></rss>'
    monkeypatch.setattr('src.services.rss_service.fetch_public_url', AsyncMock(return_value=(200, xml)))
    result = await RSSService().fetch_feed('https://example.com')
    assert result == {'title': 'Empty', 'entries': []}


async def test_configured_long_interval_not_shortened(monkeypatch):
    database = SimpleNamespace(execute=AsyncMock())
    monkeypatch.setattr('src.cogs.resources.feeds.db', database)
    before = datetime.now(UTC)
    await Feeds(SimpleNamespace())._record_poll_result(subscription(20, 2880), succeeded=False)
    assert database.execute.call_args.args[3] >= before + timedelta(minutes=2880)
