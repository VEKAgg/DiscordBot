from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import nextcord

from src.cogs.admin import notifications as module
from src.services.guild_settings_service import GuildSettings, settings_from_row


def _guild(gid, channel_id):
    guild = SimpleNamespace(id=gid, roles=[])
    channel = MagicMock(spec=nextcord.TextChannel)
    channel.id = channel_id
    channel.guild = guild
    guild.get_channel = lambda cid: channel if cid == channel_id else None
    return guild, channel


async def test_daily_bump_requires_explicit_opt_in_and_channel_for_each_guild(monkeypatch):
    guilds = [_guild(i, i * 100) for i in range(1, 5)]
    settings = {
        1: GuildSettings(1, public_commands_channel_id=100),  # off by default
        2: GuildSettings(2, bump_reminder_enabled=True),  # no config fallback
        3: GuildSettings(3, bump_reminder_enabled=True, public_commands_channel_id=300),
        4: GuildSettings(4, bump_reminder_enabled=True, public_commands_channel_id=400),
    }
    get = AsyncMock(side_effect=lambda gid: settings[gid])
    send = AsyncMock(return_value=SimpleNamespace(ok=True, status=SimpleNamespace(value='sent')))
    monkeypatch.setattr(module.guild_settings_service, 'get_settings', get)
    monkeypatch.setattr(module.outbound, 'send', send)
    cog = module.Notifications(SimpleNamespace(guilds=[g for g, _ in guilds]))
    await cog.daily_bump.coro(cog)
    assert get.await_count == 4
    assert [call.args[0] for call in send.await_args_list] == [guilds[2][1], guilds[3][1]]
    for call in send.await_args_list:
        assert f'bump-reminder:{call.args[0].guild.id}:' in call.kwargs['dedupe_key']
        assert not call.kwargs['allowed_mentions'].everyone


async def test_one_failed_guild_does_not_block_other_reminders(monkeypatch):
    a, _ = _guild(11, 1100)
    b, channel = _guild(12, 1200)
    get = AsyncMock(
        side_effect=[
            RuntimeError('failure'),
            GuildSettings(12, bump_reminder_enabled=True, public_commands_channel_id=1200),
        ]
    )
    send = AsyncMock(return_value=SimpleNamespace(ok=True, status=SimpleNamespace(value='sent')))
    monkeypatch.setattr(module.guild_settings_service, 'get_settings', get)
    monkeypatch.setattr(module.outbound, 'send', send)
    cog = module.Notifications(SimpleNamespace(guilds=[a, b]))
    await cog.daily_bump.coro(cog)
    send.assert_awaited_once()
    assert send.call_args.args[0] is channel


def test_old_rows_and_defaults_never_enable_bump():
    assert not GuildSettings(1).bump_reminder_enabled
    assert not settings_from_row({'guild_id': 1}).bump_reminder_enabled
    assert settings_from_row({'guild_id': 1, 'bump_reminder_enabled': True}).bump_reminder_enabled
