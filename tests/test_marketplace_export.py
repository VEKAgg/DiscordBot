"""Canonical stored media and opt-in Discord publication tests."""

import io
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import nextcord
import pytest
from aiohttp import web
from PIL import Image

from src.cogs.marketplace.marketplace import Marketplace
from src.services.marketplace_core import BASE, CoreClient, CoreError
from src.utils.outbound import SendOutcome, SendStatus


@pytest.mark.parametrize(
    ('format_name', 'mime', 'filename'), [('JPEG', 'image/jpeg', 'listing.jpg'), ('PNG', 'image/png', 'listing.png')]
)
async def test_core_binary_header_controls_validated_discord_attachment(format_name, mime, filename):
    buffer = io.BytesIO()
    Image.new('RGB', (20, 10), 'red').save(buffer, format=format_name)
    data = buffer.getvalue()

    async def handler(_request):
        return web.Response(body=data, content_type=mime)

    app = web.Application()
    app.router.add_get(BASE + '/media/test', handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    client = CoreClient(f'http://127.0.0.1:{port}', 'fake-key', 'installation')
    try:
        image = await client.request('GET', BASE + '/media/test', binary=True)
        assert image.data == data and image.content_type == mime
        assert image.file().filename == filename
    finally:
        await client.close()
        await runner.cleanup()


@pytest.fixture
def export_event():
    return {
        'event_id': '019a0000-0000-7000-8000-000000000001',
        'cursor': 'one',
        'type': 'listing.publish',
        'listing_id': '019a0000-0000-7000-8000-000000000002',
        'canonical_version': '2',
        'source_id': None,
        'source_key': None,
        'lifecycle': 'active',
        'moderation': 'approved',
        'audience': 'public',
        'public_state': 'public',
        'expires_at': '2099-01-01T00:00:00Z',
        'listing': {
            'title': 'Keyboard',
            'description_plaintext': 'Details',
            'category_id': '019a0000-0000-7000-8000-000000000003',
            'category_name': 'PC peripherals',
            'kind': 'goods',
            'price': {'kind': 'fixed', 'amount_minor': '1234', 'currency': 'AED'},
            'condition': 'unknown',
            'images': [],
            'seller_discord_id': '123',
        },
        'delivery': {'guild_id': '77', 'channel_id': '78', 'publication_key': 'destination-one'},
    }


async def test_publication_is_scoped_and_replayed_versions_do_not_send(monkeypatch, mock_db, export_event):
    monkeypatch.setattr('src.cogs.marketplace.marketplace.db', mock_db)
    guild = MagicMock(spec=nextcord.Guild)
    guild.id = 77
    channel = MagicMock(spec=nextcord.TextChannel)
    channel.guild = guild
    channel.id = 78
    guild.get_channel.return_value = channel
    bot = SimpleNamespace(get_guild=MagicMock(return_value=guild), user=SimpleNamespace(id=9))
    cog = Marketplace(bot)
    monkeypatch.setattr(
        cog.sync, 'binding', AsyncMock(return_value={'publication_enabled': True, 'public_syndication_enabled': True})
    )
    sender = SimpleNamespace(
        send=AsyncMock(return_value=SendOutcome(SendStatus.SENT, message=cast(Any, SimpleNamespace(id=90))))
    )
    monkeypatch.setattr('src.cogs.marketplace.marketplace.outbound', sender)
    await cog._deliver_event(export_event)
    bot.get_guild.assert_called_with(77)
    guild.get_channel.assert_called_with(78)
    assert sender.send.await_count == 1
    assert sender.send.call_args.kwargs['dedupe_key'] == 'destination-one'
    mock_db.fetch_one.return_value = {'guild_id': 77, 'channel_id': 78, 'canonical_version': 2, 'removed': False}
    await cog._deliver_event(export_event)
    assert sender.send.await_count == 1


async def test_publication_fails_closed_on_revoked_policy(monkeypatch, mock_db, export_event):
    monkeypatch.setattr('src.cogs.marketplace.marketplace.db', mock_db)
    guild = MagicMock(spec=nextcord.Guild)
    guild.id = 77
    channel = MagicMock(spec=nextcord.TextChannel)
    channel.guild = guild
    guild.get_channel.return_value = channel
    cog = Marketplace(SimpleNamespace(get_guild=lambda _id: guild))
    monkeypatch.setattr(cog.sync, 'binding', AsyncMock(return_value=None))
    sender = SimpleNamespace(send=AsyncMock())
    monkeypatch.setattr('src.cogs.marketplace.marketplace.outbound', sender)
    with pytest.raises(CoreError, match='publication_disabled'):
        await cog._deliver_event(export_event)
    sender.send.assert_not_awaited()
