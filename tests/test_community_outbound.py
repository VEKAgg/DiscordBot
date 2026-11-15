"""Regression tests for guild-scoped publication and bounded community notifications."""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import nextcord
import pytest

from src.cogs.external.export import ChatExport
from src.cogs.marketplace.marketplace import Marketplace
from src.cogs.mentorship import Mentorship
from src.cogs.resources.feeds import Feeds
from src.core.runtime_state import runtime_state
from src.utils.outbound import SendOutcome, SendStatus


@pytest.fixture
def sender(monkeypatch):
    messenger = SimpleNamespace(
        send=AsyncMock(return_value=SendOutcome(SendStatus.SENT, message=cast(Any, SimpleNamespace(id=90)))),
        dm=AsyncMock(return_value=SendOutcome(SendStatus.SENT)),
        create_thread=AsyncMock(return_value=SendOutcome(SendStatus.SENT, thread=cast(Any, SimpleNamespace(id=91)))),
        upsert_status=AsyncMock(return_value=SendOutcome(SendStatus.EDITED)),
        forget_status=MagicMock(),
    )
    monkeypatch.setattr('src.cogs.marketplace.marketplace.image_store.get', AsyncMock(return_value=None))
    monkeypatch.setattr('src.cogs.marketplace.marketplace.image_store.capture_attachments', AsyncMock(return_value=0))
    for module in (
        'marketplace.marketplace',
        'mentorship',
        'resources.feeds',
        'external.export',
    ):
        monkeypatch.setattr(f'src.cogs.{module}.outbound', messenger)
    return messenger


@pytest.mark.parametrize(
    ('title', 'body', 'price'),
    [
        ('GPU - $100.00', '', Decimal('100')),
        ('GPU', 'Price $1,000.50', Decimal('1000.50')),
        ('RTX 4090', '', None),
        ('GPU $0', '', None),
        ('GPU $1000000', '', None),
    ],
)
def test_forum_price_requires_explicit_valid_amount(title, body, price):
    assert Marketplace._forum_price(title, body) == price


async def test_checkin_digest_uses_joined_users_and_is_bounded(monkeypatch, mock_user, sender):
    rows = [
        {
            'id': i,
            'category': 'programming',
            'guild_id': 77,
            'user_id': 5,
            'revision': 1,
            'discord_id': str(mock_user.id),
        }
        for i in range(12)
    ]
    guild = SimpleNamespace(get_member=lambda uid: mock_user if uid == mock_user.id else None)
    cog = Mentorship(SimpleNamespace(get_guild=lambda gid: guild if gid == 77 else None))
    monkeypatch.setattr(cog.mentorship_service, 'due_reminders', AsyncMock(return_value=rows))
    monkeypatch.setattr(cog.mentorship_service, 'claim_reminder', AsyncMock(return_value=True))
    monkeypatch.setattr(cog.mentorship_service, 'current_reminder_matches', AsyncMock(return_value=rows))
    finished = AsyncMock()
    monkeypatch.setattr(cog.mentorship_service, 'finish_reminder', finished)
    await cog.check_in_loop.coro(cog)
    sender.dm.assert_awaited_once()
    assert len(sender.dm.call_args.kwargs['embed'].fields) == 10
    finished.assert_awaited_once_with(77, 5, 1, True)


async def test_latest_cooldown_collapses_repeated_requests(monkeypatch, mock_interaction, sender):
    cog = Feeds(SimpleNamespace())
    mock_interaction.response.defer = AsyncMock()
    fetch = AsyncMock(return_value={'title': 'Feed', 'entries': [{'title': 'One'}, {'title': 'Two'}]})
    monkeypatch.setattr(cog.rss_service, 'fetch_feed', fetch)
    monkeypatch.setattr(cog, '_create_feed_embed', AsyncMock(return_value=nextcord.Embed(title='One')))
    await Feeds.feed_latest.callback(cog, mock_interaction, 'https://example.com/rss')
    await Feeds.feed_latest.callback(cog, mock_interaction, 'https://example.com/rss')
    fetch.assert_awaited_once()
    mock_interaction.followup.send.assert_awaited_once()
    sender.send.assert_not_awaited()


async def test_export_uses_unique_file_keys_and_stops_on_delivery_failure(mock_bot, mock_user, sender):
    cog = ChatExport(mock_bot)
    cog._status_key = 'run-1'
    assert await cog._send_file_dm(mock_user, 'one.txt', 'One')
    assert await cog._send_file_dm(mock_user, 'two.txt', 'Two')
    keys = [call.kwargs['dedupe_key'] for call in sender.dm.call_args_list]
    assert keys == ['run-1:one.txt:1', 'run-1:two.txt:1']
    sender.dm.return_value = SendOutcome(SendStatus.FORBIDDEN)
    assert not await cog._send_file_dm(mock_user, 'three.txt', 'Three')


async def test_export_clears_runtime_progress_even_on_failure(monkeypatch, mock_bot, mock_interaction, sender):
    cog = ChatExport(mock_bot)
    cog._export_running = True
    runtime_state.alert_state_cache['export_active'] = True
    monkeypatch.setattr(cog, '_perform_export', AsyncMock(side_effect=RuntimeError('failed')))
    with pytest.raises(RuntimeError):
        await cog._run_export(mock_interaction, [], None)
    assert 'export_active' not in runtime_state.alert_state_cache
    sender.forget_status.assert_not_called()


async def test_export_throttles_per_batch_not_per_message(monkeypatch, mock_bot, mock_user):
    cog = ChatExport(mock_bot)
    monkeypatch.setattr(cog, '_is_healthy', lambda: True)
    monkeypatch.setattr(cog, '_can_read', lambda *_args: True)
    sleep = AsyncMock()
    monkeypatch.setattr('src.cogs.external.export.asyncio.sleep', sleep)
    message = SimpleNamespace(created_at=datetime.now(UTC), author=mock_user, content='test', attachments=[], embeds=[])

    async def history(**_kwargs):
        for _ in range(250):
            yield message

    channel = SimpleNamespace(name='test', id=1, history=history)
    content, count = await cog._export_channel(cast(Any, channel), mock_user)
    assert count == 250
    assert content
    assert sleep.await_count == 4  # two batch delays plus two cooperative yields
    content.close()


async def test_export_stops_after_first_failed_file(monkeypatch, mock_bot, mock_interaction, sender):
    cog = ChatExport(mock_bot)
    export = AsyncMock(return_value=('One', 1))
    monkeypatch.setattr(cog, '_can_read', lambda *_args: True)
    monkeypatch.setattr(cog, '_export_channel', export)
    monkeypatch.setattr(cog, '_send_file_dm', AsyncMock(return_value=False))
    channels = [SimpleNamespace(name=str(i), id=i) for i in range(10)]
    await cog._perform_export(mock_interaction, cast(Any, channels), None)
    export.assert_awaited_once()
    assert cog._cancel_export
    assert sender.upsert_status.await_count == 2  # start + final edit, no per-channel DMs
    sender.dm.assert_not_awaited()
