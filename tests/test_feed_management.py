"""Dynamic feed management, permissions, quotas, pagination, and scheduler regressions."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import nextcord
import pytest

from src.cogs.resources.feeds import Feeds
from src.core.runtime_state import runtime_state


@pytest.fixture
def management(monkeypatch, mock_db, mock_interaction):
    runtime_state.db_available = True
    mock_interaction.response.defer = AsyncMock()
    mock_interaction.user.guild_permissions.manage_guild = True
    guild = mock_interaction.guild
    channel = MagicMock(spec=nextcord.TextChannel)
    channel.id = 3
    channel.guild = guild
    channel.mention = '<#3>'
    channel.permissions_for.return_value = nextcord.Permissions(view_channel=True, send_messages=True, embed_links=True)
    guild.get_channel.return_value = channel
    bot = SimpleNamespace(get_guild=lambda _id: guild)
    cog = Feeds(bot)
    monkeypatch.setattr('src.cogs.resources.feeds.db', mock_db)
    monkeypatch.setattr(cog, '_management_reply', AsyncMock())
    monkeypatch.setattr(cog.rss_service, 'fetch_feed', AsyncMock(return_value={'title': 'Example', 'entries': []}))
    mock_db.fetchval.side_effect = [None, 0]
    return cog, mock_db, mock_interaction, channel


async def add(cog, interaction, channel):
    await Feeds.feed_add.callback(cog, interaction, ' https://example.com/feed ', channel, '', 10)


async def test_add_deferred_and_dynamic(management):
    cog, database, interaction, channel = management
    await add(cog, interaction, channel)
    interaction.response.defer.assert_awaited_once_with(ephemeral=True)
    assert database.execute.call_args.args[1:] == (interaction.guild.id, 3, 'https://example.com/feed', 'Example', 10)
    cog.rss_service.fetch_feed.assert_awaited_once_with('https://example.com/feed')


async def test_quota_blocks_new_feed(management, monkeypatch):
    cog, database, interaction, channel = management
    monkeypatch.setattr('src.cogs.resources.feeds.FEED_MAX_SUBSCRIPTIONS', 2)
    database.fetchval.side_effect = [None, 2]
    await add(cog, interaction, channel)
    database.execute.assert_not_awaited()
    assert cog._management_reply.call_args.args[1] == 'Feed Limit Reached'


async def test_quota_allows_existing_subscription_update(management, monkeypatch):
    cog, database, interaction, channel = management
    monkeypatch.setattr('src.cogs.resources.feeds.FEED_MAX_SUBSCRIPTIONS', 2)
    database.fetchval.side_effect = [7, 2]
    await add(cog, interaction, channel)
    database.execute.assert_awaited_once()
    sql = database.execute.call_args.args[0]
    assert 'consecutive_failures' not in sql and 'paused' not in sql


async def test_concurrent_adds_cannot_exceed_quota(management, monkeypatch):
    cog, database, interaction, channel = management
    monkeypatch.setattr('src.cogs.resources.feeds.FEED_MAX_SUBSCRIPTIONS', 1)
    count = 0

    async def fetchval(sql, *_args):
        await asyncio.sleep(0)
        return count if 'COUNT' in sql else None

    async def insert(*_args):
        nonlocal count
        await asyncio.sleep(0)
        count += 1

    database.fetchval.side_effect = fetchval
    database.execute.side_effect = insert
    await asyncio.gather(add(cog, interaction, channel), add(cog, interaction, channel))
    assert count == 1


@pytest.mark.parametrize('missing', ['view_channel', 'send_messages', 'embed_links'])
async def test_add_rejects_missing_channel_permissions(management, missing):
    cog, database, interaction, channel = management
    setattr(channel.permissions_for.return_value, missing, False)
    await add(cog, interaction, channel)
    cog.rss_service.fetch_feed.assert_not_awaited()
    database.execute.assert_not_awaited()
    assert cog._management_reply.call_args.args[1] == 'Invalid Channel'


async def test_add_rejects_other_guild(management):
    cog, database, interaction, channel = management
    channel.guild = SimpleNamespace(id=interaction.guild.id + 1)
    await add(cog, interaction, channel)
    database.execute.assert_not_awaited()


async def test_invalid_feed_not_saved(management):
    cog, database, interaction, channel = management
    cog.rss_service.fetch_feed.return_value = None
    await add(cog, interaction, channel)
    cog.rss_service.fetch_feed.assert_awaited_once()
    database.execute.assert_not_awaited()


async def test_edit_is_scoped_and_preserves_history(management):
    cog, database, interaction, channel = management
    database.fetch_one.return_value = {'id': 1}
    await Feeds.feed_edit.callback(cog, interaction, 'https://example.com/feed', channel, ' New Name ', 60)
    args = database.fetch_one.call_args.args
    assert args[1:] == (interaction.guild.id, 'https://example.com/feed', 3, 'New Name', 60)
    assert 'consecutive_failures' not in args[0] and 'paused' not in args[0]


async def test_edit_requires_changes(management):
    cog, database, interaction, _channel = management
    await Feeds.feed_edit.callback(cog, interaction, 'https://example.com', None, None, None)
    database.fetch_one.assert_not_awaited()


@pytest.mark.parametrize('paused', [True, False])
async def test_pause_resume_preserves_backoff_and_history(management, paused):
    cog, database, interaction, _channel = management
    database.fetch_one.return_value = {'channel_id': 3}
    await cog._set_paused(interaction, ' https://example.com/feed ', paused)
    assert database.execute.call_args.args[1:] == (interaction.guild.id, 'https://example.com/feed', paused)
    assert 'last_polled_at' not in database.execute.call_args.args[0]


async def test_resume_rejects_unwritable_channel(management):
    cog, database, interaction, channel = management
    database.fetch_one.return_value = {'channel_id': 3}
    channel.permissions_for.return_value.send_messages = False
    await cog._set_paused(interaction, 'https://example.com/feed', False)
    database.execute.assert_not_awaited()


async def test_pause_not_found(management):
    cog, database, interaction, _channel = management
    await cog._set_paused(interaction, 'https://example.com/feed', True)
    database.execute.assert_not_awaited()


@pytest.mark.parametrize('command', ['feed_add', 'feed_edit', 'feed_pause', 'feed_resume'])
async def test_management_rejects_regular_members(management, command):
    cog, database, interaction, channel = management
    interaction.user.guild_permissions.manage_guild = False
    interaction.user.guild_permissions.administrator = False
    interaction.guild.owner_id = 0
    args = {
        'feed_add': ('https://example.com', channel, '', 10),
        'feed_edit': ('https://example.com', None, 'name', None),
        'feed_pause': ('https://example.com',),
        'feed_resume': ('https://example.com',),
    }
    await getattr(Feeds, command).callback(cog, interaction, *args[command])
    database.execute.assert_not_awaited()
    database.fetch_one.assert_not_awaited()
    cog.rss_service.fetch_feed.assert_not_awaited()


async def test_list_paginates_and_shows_health(management, monkeypatch):
    cog, database, interaction, _channel = management
    now = datetime.now(UTC)
    database.fetch_many = AsyncMock(
        return_value=[
            {
                'feed_name': f'Feed {i}',
                'feed_url': f'https://example.com/{i}',
                'channel_id': 3,
                'poll_interval_minutes': 10,
                'last_polled_at': now,
                'paused': i == 10,
                'consecutive_failures': 4 if i == 11 else 0,
                'next_retry_at': now + timedelta(hours=1),
            }
            for i in range(26)
        ]
    )
    send = AsyncMock()
    monkeypatch.setattr('src.cogs.resources.feeds.safe_send', send)
    await Feeds.feed_list.callback(cog, interaction, 2)
    embed = send.call_args.kwargs['embed']
    assert 'Page 2/3' in embed.title
    assert len(embed.fields) == 10
    assert embed.fields[0].name == 'Feed 10'
    assert 'Paused' in embed.fields[0].value
    assert 'Failing (4 attempts)' in embed.fields[1].value
    assert 'Next attempt:' in embed.fields[1].value


async def test_list_rejects_out_of_range_page(management):
    cog, database, interaction, _channel = management
    database.fetch_many = AsyncMock(return_value=[{'feed_name': 'one'}])
    await Feeds.feed_list.callback(cog, interaction, 2)
    assert cog._management_reply.call_args.args[1] == 'Invalid Page'


async def test_scheduler_accepts_ten_minute_interval(management):
    cog, database, interaction, _channel = management
    assert cog.feed_update.minutes == 1
    database.fetch_many = AsyncMock(
        return_value=[
            {
                'id': 1,
                'guild_id': interaction.guild.id,
                'channel_id': 3,
                'feed_url': 'https://example.com/feed',
                'feed_name': 'Example',
                'poll_interval_minutes': 10,
                'last_polled_at': datetime.now(UTC) - timedelta(minutes=11),
                'next_retry_at': None,
                'consecutive_failures': 0,
            }
        ]
    )
    monkey_fetch = AsyncMock(return_value={'entries': []})
    cog.rss_service.fetch_feed.side_effect = monkey_fetch
    await cog.feed_update()
    monkey_fetch.assert_awaited_once()
    assert 'WHERE paused = FALSE' in database.fetch_many.call_args.args[0]


async def test_unwritable_channel_not_polled(management):
    cog, database, interaction, channel = management
    channel.permissions_for.return_value.embed_links = False
    database.fetch_many = AsyncMock(
        return_value=[
            {
                'id': 1,
                'guild_id': interaction.guild.id,
                'channel_id': 3,
                'last_polled_at': None,
                'next_retry_at': None,
            }
        ]
    )
    await cog.feed_update()
    cog.rss_service.fetch_feed.assert_not_awaited()


async def test_server_posting_budget(management, monkeypatch):
    cog, database, interaction, channel = management
    monkeypatch.setattr('src.cogs.resources.feeds.FEED_MAX_POSTS_PER_GUILD_PER_CYCLE', 2)
    database.fetch_many = AsyncMock(
        return_value=[
            {
                'id': i,
                'guild_id': interaction.guild.id,
                'channel_id': 3,
                'last_polled_at': None,
                'next_retry_at': None,
                'consecutive_failures': 0,
                'poll_interval_minutes': 10,
                'feed_url': f'https://example.com/{i}',
                'feed_name': 'Example',
            }
            for i in range(2)
        ]
    )
    entries = [{'entry_id': str(i)} for i in range(5)]
    cog.rss_service.fetch_feed.return_value = {'entries': entries}
    monkeypatch.setattr(cog.rss_service, 'process_and_dedupe', AsyncMock(return_value=entries))
    monkeypatch.setattr(cog, '_create_feed_embed', AsyncMock(return_value=nextcord.Embed()))
    channel.send = AsyncMock()
    await cog.feed_update()
    assert channel.send.await_count == 2
    assert cog.rss_service.fetch_feed.await_count == 1


async def test_autocomplete_suggests_guild_subscriptions(management):
    cog, database, interaction, _channel = management
    interaction.response.send_autocomplete = AsyncMock()
    long_url = 'https://example.com/' + 'x' * 100
    database.fetch_many = AsyncMock(
        return_value=[
            {'feed_url': 'https://example.com/feed', 'feed_name': 'Example', 'paused': True},
            {'feed_url': long_url, 'feed_name': 'Too long', 'paused': False},
        ]
    )
    await cog._autocomplete_subscription(interaction, ' exam ')
    assert database.fetch_many.call_args.args[1:] == (interaction.guild.id, '%exam%')
    interaction.response.send_autocomplete.assert_awaited_once_with(
        {'Example (paused) — https://example.com/feed': 'https://example.com/feed'}
    )
