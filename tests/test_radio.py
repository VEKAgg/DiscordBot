"""Radio voice connection uses nextcord's API, not discord.py's."""

from unittest.mock import MagicMock, create_autospec

import nextcord

from src.cogs.radio.radio import RadioManager


async def test_join_connects_with_nextcord_signature_and_self_deafens(mock_bot, monkeypatch):
    # create_autospec enforces the real signatures: connect(self_deaf=True) raises TypeError here,
    # exactly as it did in production.
    channel = create_autospec(nextcord.VoiceChannel, instance=True)
    channel.name = 'radio'
    channel.guild = create_autospec(nextcord.Guild, instance=True)
    monkeypatch.setattr(mock_bot, 'get_channel', lambda _id: channel)

    cog = RadioManager(mock_bot)
    cog._target_channel_id = 1
    cog._source = {'name': 'ep', 'url': 'https://x/ep.mp3', 'emoji': ''}
    play_stream = MagicMock()
    monkeypatch.setattr(cog, '_play_stream', play_stream)
    mock_bot.notifier = None
    del mock_bot.notifier  # skip alerts

    await cog._join_and_play()

    channel.connect.assert_awaited_once_with()
    channel.guild.change_voice_state.assert_awaited_once_with(channel=channel, self_deaf=True)
    play_stream.assert_called_once()
    assert cog._started_at is not None


PODCAST_FEED = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Test Cast</title>
<item><title>Newest</title><enclosure url="https://cdn.example.com/2.mp3" type="audio/mpeg" length="1"/></item>
<item><title>No audio</title></item>
<item><title>Older</title><enclosure url="https://cdn.example.com/1.mp3" type="audio/mpeg" length="1"/></item>
</channel></rss>"""


def test_parse_podcast_episodes_skips_entries_without_audio():
    from src.cogs.radio.radio import parse_podcast_episodes

    title, episodes = parse_podcast_episodes(PODCAST_FEED)

    assert title == 'Test Cast'
    assert [e['title'] for e in episodes] == ['Newest', 'Older']
    assert episodes[0]['url'] == 'https://cdn.example.com/2.mp3'


async def test_play_url_rejects_non_public_urls(mock_bot):
    cog = RadioManager(mock_bot)
    for url in ('file:///etc/passwd', 'http://127.0.0.1/x.mp3', 'http://localhost/x.mp3', 'ftp://example.com/a'):
        ok, _ = await cog._play_url(url)
        assert ok is False, url
    assert cog._source is None


async def test_play_url_plays_and_escapes_title(mock_bot, monkeypatch):
    async def fake_resolve(url):
        return url

    # Patch the globals the class actually uses (test_cog_loading may have reloaded the module).
    monkeypatch.setitem(RadioManager._play_url.__globals__, 'resolve_public_media_url', fake_resolve)
    cog = RadioManager(mock_bot)
    cog._target_channel_id = 1
    started = []

    async def fake_start(source):
        started.append(source)
        return True

    monkeypatch.setattr(cog, '_start', fake_start)

    ok, _ = await cog._play_url('https://cdn.example.com/talk.mp3', 'My *Talk*')

    assert ok is True
    assert started[0]['url'] == 'https://cdn.example.com/talk.mp3'
    assert started[0]['name'] == 'My \\*Talk\\*'  # markdown escaped


async def test_play_url_needs_a_radio_channel(mock_bot, monkeypatch):
    async def fake_resolve(url):
        return url

    monkeypatch.setitem(RadioManager._play_url.__globals__, 'resolve_public_media_url', fake_resolve)
    cog = RadioManager(mock_bot)
    cog._target_channel_id = None

    async def no_channel():
        return None

    monkeypatch.setattr(cog, '_get_target_channel_id', no_channel)

    ok, message = await cog._play_url('https://cdn.example.com/talk.mp3')

    assert ok is False
    assert 'channel' in message


def _connected_cog(mock_bot, monkeypatch):
    cog = RadioManager(mock_bot)
    voice = MagicMock()
    voice.is_connected.return_value = True
    cog._voice_client = voice
    cog._source = {'name': 'ep', 'url': 'https://x/ep.mp3', 'emoji': ''}
    scheduled: list[str] = []

    def fake_run_coroutine_threadsafe(coro, _loop):
        scheduled.append(coro.__qualname__)
        coro.close()

    monkeypatch.setattr(
        RadioManager._on_play_end.__globals__['asyncio'], 'run_coroutine_threadsafe', fake_run_coroutine_threadsafe
    )
    return cog, scheduled


def test_source_end_leaves_the_channel(mock_bot, monkeypatch):
    cog, scheduled = _connected_cog(mock_bot, monkeypatch)

    cog._on_play_end(None, cog._play_generation)

    assert scheduled == ['RadioManager._disconnect']
    assert cog._source is None


def test_intentional_stop_is_ignored(mock_bot, monkeypatch):
    cog, scheduled = _connected_cog(mock_bot, monkeypatch)
    stale = cog._play_generation
    cog._play_generation += 1  # what _start/_disconnect do before stop()

    cog._on_play_end(None, stale)

    assert scheduled == []
    assert cog._source is not None
