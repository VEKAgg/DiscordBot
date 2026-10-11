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
from src.cogs.marketplace_enhanced import MarketplaceEnhanced
from src.cogs.mentorship import Mentorship
from src.cogs.resources.feeds import Feeds
from src.core.runtime_state import runtime_state
from src.services.directus_sync import _find_listing
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
        'marketplace_enhanced',
        'mentorship',
        'resources.feeds',
        'external.export',
    ):
        monkeypatch.setattr(f'src.cogs.{module}.outbound', messenger)
    return messenger


async def test_marketplace_publication_only_uses_invoking_guild(monkeypatch, mock_db, mock_guild, mock_user, sender):
    monkeypatch.setattr('src.cogs.marketplace.marketplace.db', mock_db)
    channel = MagicMock(spec=nextcord.TextChannel)
    channel.id = 20
    channel.guild = mock_guild
    resolver = AsyncMock(return_value=channel)
    monkeypatch.setattr('src.cogs.marketplace.marketplace.guild_settings_service.resolve_channel', resolver)
    bot = SimpleNamespace(get_channel=MagicMock())
    result = await Marketplace(bot)._post_listing_to_channel(
        guild=mock_guild, listing_id='one', title='One', price=10, condition='good', category='Other', seller=mock_user
    )
    assert result == 'sent'
    resolver.assert_awaited_once_with(mock_guild, 'marketplace_channel_id')
    bot.get_channel.assert_not_called()
    sender.send.assert_awaited_once()
    assert mock_db.execute.call_args.args[1:4] == (mock_guild.id, 'one', channel.id)


async def test_marketplace_repeated_sync_does_not_publish(monkeypatch, mock_db, mock_guild, mock_user, sender):
    monkeypatch.setattr('src.cogs.marketplace.marketplace.db', mock_db)
    mock_db.fetch_one.return_value = {'message_id': 90}
    result = await Marketplace(SimpleNamespace())._post_listing_to_channel(
        guild=mock_guild, listing_id='one', title='One', price=10, condition='good', category='Other', seller=mock_user
    )
    assert result == 'existing'
    sender.send.assert_not_awaited()
    sender.create_thread.assert_not_awaited()


async def test_marketplace_rejects_cross_guild_destination(monkeypatch, mock_db, mock_guild, mock_user, sender):
    monkeypatch.setattr('src.cogs.marketplace.marketplace.db', mock_db)
    channel = MagicMock(spec=nextcord.TextChannel)
    channel.guild = SimpleNamespace(id=mock_guild.id + 1)
    monkeypatch.setattr(
        'src.cogs.marketplace.marketplace.guild_settings_service.resolve_channel', AsyncMock(return_value=channel)
    )
    result = await Marketplace(SimpleNamespace())._post_listing_to_channel(
        guild=mock_guild, listing_id='one', title='One', price=10, condition='good', category='Other', seller=mock_user
    )
    assert result == 'failed'
    sender.send.assert_not_awaited()


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


async def test_forum_ingest_is_silent_and_keeps_unknown_price(monkeypatch, mock_db, mock_guild, sender):
    monkeypatch.setattr('src.cogs.marketplace.marketplace.db', mock_db)
    monkeypatch.setattr('src.cogs.marketplace.marketplace.get_or_create_user', AsyncMock(return_value={'id': 5}))
    forum = MagicMock(spec=nextcord.ForumChannel)
    forum.id = 30
    monkeypatch.setattr(
        'src.cogs.marketplace.marketplace.guild_settings_service.resolve_channel', AsyncMock(return_value=forum)
    )
    thread = MagicMock(spec=nextcord.Thread)
    thread.guild = mock_guild
    thread.id = 40
    thread.parent_id = forum.id
    thread.owner_id = 123
    thread.archived = thread.locked = False
    thread.name = 'My GPU'
    thread.applied_tags = []
    thread.fetch_message = AsyncMock(
        return_value=SimpleNamespace(
            id=40, author=SimpleNamespace(bot=False), webhook_id=None, content='Selling a GPU', attachments=[]
        )
    )
    await Marketplace(SimpleNamespace())._ingest_forum_thread(thread)
    args = mock_db.execute.call_args.args
    assert args[1] == 'FORUM40'
    assert args[2] == 5
    assert args[5] is None
    assert args[7] == 'pending_review'
    assert args[-2:] == (40, mock_guild.id)
    sender.send.assert_not_awaited()
    sender.dm.assert_not_awaited()


async def test_forum_bot_threads_are_not_reimported(monkeypatch, mock_db, mock_guild, sender):
    monkeypatch.setattr('src.cogs.marketplace.marketplace.db', mock_db)
    mock_db.fetchval.return_value = 1
    forum = MagicMock(spec=nextcord.ForumChannel)
    forum.id = 30
    monkeypatch.setattr(
        'src.cogs.marketplace.marketplace.guild_settings_service.resolve_channel', AsyncMock(return_value=forum)
    )
    thread = SimpleNamespace(
        guild=mock_guild, parent_id=30, id=40, archived=False, locked=False, fetch_message=AsyncMock()
    )
    await Marketplace(SimpleNamespace())._ingest_forum_thread(cast(Any, thread))
    thread.fetch_message.assert_not_awaited()
    mock_db.execute.assert_not_awaited()
    sender.send.assert_not_awaited()


async def test_directus_failed_lookup_is_not_absence():
    session = MagicMock()
    session.get.return_value.__aenter__ = AsyncMock(return_value=SimpleNamespace(status=503))
    session.get.return_value.__aexit__ = AsyncMock(return_value=False)
    with pytest.raises(RuntimeError, match='lookup failed'):
        await _find_listing(session, 'one')


async def test_expiry_digest_one_dm_per_seller(monkeypatch, mock_user, sender):
    monkeypatch.setattr('src.cogs.marketplace_enhanced.asyncio.sleep', AsyncMock())
    guild = SimpleNamespace(get_member=lambda uid: mock_user if uid == mock_user.id else None)
    guild.id = 77
    cog = MarketplaceEnhanced(SimpleNamespace(guilds=[guild]))
    rows = [{'discord_id': str(mock_user.id), 'title': f'Item {i}', 'id': str(i)} for i in range(500)]
    await cog._notify_sellers(rows, expired=True)
    sender.dm.assert_awaited_once()
    assert len(sender.dm.call_args.kwargs['embed'].fields) == 10


async def test_expiry_skips_users_without_shared_guild(sender):
    cog = MarketplaceEnhanced(SimpleNamespace(guilds=[]))
    await cog._notify_sellers([{'discord_id': '123', 'title': 'Item', 'id': 'one'}], expired=False)
    sender.dm.assert_not_awaited()


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


async def test_forum_archive_is_inactive_not_deleted(monkeypatch, mock_db, mock_guild, sender):
    monkeypatch.setattr('src.cogs.marketplace.marketplace.db', mock_db)
    forum = MagicMock(spec=nextcord.ForumChannel)
    forum.id = 30
    monkeypatch.setattr(
        'src.cogs.marketplace.marketplace.guild_settings_service.resolve_channel', AsyncMock(return_value=forum)
    )
    thread = SimpleNamespace(guild=mock_guild, parent_id=30, id=40, archived=True, locked=False)
    await Marketplace(SimpleNamespace())._ingest_forum_thread(cast(Any, thread))
    assert "status = 'archived'" in mock_db.execute.call_args.args[0]
    sender.send.assert_not_awaited()
