"""Regression coverage for the modernization diff review."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import nextcord
import pytest

from src.cogs.admin.honeypot import Honeypot
from src.cogs.admin.massunban import MassUnban
from src.cogs.external.export import ChatExport
from src.cogs.resources.feeds import Feeds
from src.services.directus_sync import _rehost_image
from src.services.rss_service import RSSService


async def test_honeypot_zero_deletion_days_preserved(monkeypatch, mock_bot, mock_guild, mock_user, mock_db):
    monkeypatch.setattr('src.cogs.admin.honeypot.db', mock_db)
    monkeypatch.setattr('src.cogs.admin.honeypot._is_exempt', lambda *_: False)
    cog = Honeypot(mock_bot)
    monkeypatch.setattr(cog, '_load_cache', AsyncMock())
    cog._honeypot_cache[3] = {'id': 1, 'enabled': True, 'action_type': 'ban', 'delete_message_days': 0}
    execute_ban = AsyncMock(return_value='success')
    monkeypatch.setattr(cog, '_execute_ban', execute_ban)
    monkeypatch.setattr(cog, '_send_alert', AsyncMock())
    mock_guild.get_member.return_value = mock_user
    message = MagicMock(spec=nextcord.Message)
    message.author = mock_user
    message.webhook_id = None
    message.guild = mock_guild
    message.channel = SimpleNamespace(id=3)
    message.id = 4
    message.content = 'test'
    await cog.on_message(message)
    execute_ban.assert_awaited_once_with(mock_guild, mock_user, 0)


@pytest.mark.parametrize('url', ['http://cdn.discordapp.com/x', 'https://evil.example/x'])
async def test_rehost_rejects_non_https_or_untrusted_host(url):
    session = MagicMock()
    assert await _rehost_image(session, url) is None
    session.get.assert_not_called()


async def test_honeypot_first_trigger_fires_on_fresh_host(monkeypatch, mock_bot, mock_guild, mock_user, mock_db):
    """monotonic() counts from boot; a fresh CI VM has uptime below the cooldown (the original CI failure)."""
    monkeypatch.setattr('src.cogs.admin.honeypot.time.monotonic', lambda: 5.0)
    monkeypatch.setattr('src.cogs.admin.honeypot.db', mock_db)
    monkeypatch.setattr('src.cogs.admin.honeypot._is_exempt', lambda *_: False)
    cog = Honeypot(mock_bot)
    monkeypatch.setattr(cog, '_load_cache', AsyncMock())
    cog._honeypot_cache[3] = {'id': 1, 'enabled': True, 'action_type': 'ban', 'delete_message_days': 1}
    execute_ban = AsyncMock(return_value='success')
    monkeypatch.setattr(cog, '_execute_ban', execute_ban)
    monkeypatch.setattr(cog, '_send_alert', AsyncMock())
    mock_guild.get_member.return_value = mock_user
    message = MagicMock(spec=nextcord.Message)
    message.author = mock_user
    message.webhook_id = None
    message.guild = mock_guild
    message.channel = SimpleNamespace(id=3)
    message.id = 4
    message.content = 'test'
    await cog.on_message(message)
    await cog.on_message(message)  # second hit inside the cooldown is still suppressed
    execute_ban.assert_awaited_once_with(mock_guild, mock_user, 1)


async def test_rehost_does_not_follow_redirects():
    session = MagicMock()
    session.get.return_value.__aenter__ = AsyncMock(return_value=SimpleNamespace(status=302))
    session.get.return_value.__aexit__ = AsyncMock()
    assert await _rehost_image(session, 'https://cdn.discordapp.com/x') is None
    session.get.assert_called_once_with('https://cdn.discordapp.com/x', allow_redirects=False)


async def test_export_state_released_on_failure(monkeypatch, mock_bot, mock_interaction):
    cog = ChatExport(mock_bot)
    cog._export_running = True
    cog._export_owner_id = 1
    cog._export_guild_id = 2
    monkeypatch.setattr(cog, '_perform_export', AsyncMock(side_effect=RuntimeError('export failed')))
    with pytest.raises(RuntimeError, match='export failed'):
        await cog._run_export(mock_interaction, [], None)
    assert not cog._export_running
    assert cog._export_owner_id is None
    assert cog._export_guild_id is None


async def test_export_stop_rejects_admin_of_other_guild(mock_bot, mock_interaction, admin_member):
    cog = ChatExport(mock_bot)
    cog._export_running = True
    cog._export_owner_id = 123
    cog._export_guild_id = mock_interaction.guild.id + 1
    mock_interaction.user = admin_member
    await ChatExport.exportstop.callback(cog, mock_interaction)
    assert not cog._cancel_export
    assert mock_interaction.response.send_message.call_args.kwargs['embed'].title == 'Not Your Export'


async def test_massunban_unload_cancels_workers(monkeypatch, mock_bot):
    cog = MassUnban(mock_bot)
    started = asyncio.Event()

    async def worker():
        started.set()
        await asyncio.Event().wait()

    task = cog._spawn_worker(worker(), name='test:massunban')
    await started.wait()
    cog.cog_unload()
    await asyncio.gather(task, return_exceptions=True)
    assert task.cancelled()
    run_job = AsyncMock()
    monkeypatch.setattr(cog, '_run_job', run_job)
    await cog._execute_job(1)
    run_job.assert_not_awaited()


async def test_subscription_preview_does_not_mark_seen(monkeypatch, mock_db):
    monkeypatch.setattr('src.services.rss_service.db', mock_db)
    entries = [{'entry_id': 'guid'}]
    assert await RSSService().process_and_dedupe('https://example.com', entries, 1, mark_seen=False) == entries
    assert mock_db.fetchval.call_args.args[0].startswith('SELECT 1')
    mock_db.execute.assert_not_awaited()


@pytest.mark.parametrize('send_fails', [False, True])
async def test_feed_acknowledges_only_delivered_entries(monkeypatch, mock_db, send_fails):
    monkeypatch.setattr('src.cogs.resources.feeds.db', mock_db)
    sub = {
        'id': 1,
        'guild_id': 2,
        'channel_id': 3,
        'feed_url': 'https://example.com',
        'feed_name': 'test',
        'last_polled_at': None,
    }
    mock_db.fetch_many = AsyncMock(return_value=[sub])
    entries = [{'entry_id': str(i)} for i in range(5)]
    channel = MagicMock(spec=nextcord.TextChannel)
    channel.send = AsyncMock(side_effect=RuntimeError('send failed') if send_fails else None)
    guild = SimpleNamespace(get_channel=lambda _id: channel)
    bot = SimpleNamespace(get_guild=lambda _id: guild)
    cog = Feeds(bot)
    dedupe = AsyncMock(return_value=entries)
    monkeypatch.setattr(cog.rss_service, 'fetch_feed', AsyncMock(return_value={'entries': entries}))
    monkeypatch.setattr(cog.rss_service, 'process_and_dedupe', dedupe)
    monkeypatch.setattr(cog, '_create_feed_embed', AsyncMock(return_value=nextcord.Embed()))
    await cog.feed_update()
    calls = dedupe.call_args_list
    assert calls[0].kwargs['mark_seen'] is False
    assert len(calls) == (1 if send_fails else 4)
    if not send_fails:
        assert [call.args[1] for call in calls[1:]] == [[entry] for entry in entries[:3]]
