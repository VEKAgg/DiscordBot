"""Radio voice connection uses nextcord's API, not discord.py's."""

from unittest.mock import MagicMock, create_autospec

import nextcord

from src.cogs.radio.radio import RadioManager


async def test_auto_join_connects_with_nextcord_signature_and_self_deafens(mock_bot, monkeypatch):
    # create_autospec enforces the real signatures: connect(self_deaf=True) raises TypeError here,
    # exactly as it did in production.
    channel = create_autospec(nextcord.VoiceChannel, instance=True)
    channel.name = 'radio'
    channel.guild = create_autospec(nextcord.Guild, instance=True)
    monkeypatch.setattr(mock_bot, 'get_channel', lambda _id: channel)

    cog = RadioManager(mock_bot)
    cog._target_channel_id = 1
    play_stream = MagicMock()
    monkeypatch.setattr(cog, '_play_stream', play_stream)
    mock_bot.notifier = None
    del mock_bot.notifier  # skip the startup alert

    await cog._auto_join()

    channel.connect.assert_awaited_once_with()
    channel.guild.change_voice_state.assert_awaited_once_with(channel=channel, self_deaf=True)
    play_stream.assert_called_once()
    assert cog._started_at is not None
