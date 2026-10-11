"""Offline durable image tests: bounded, sanitized images and no foreign CDN embeds."""

import io
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import nextcord
import pytest
from PIL import Image

from src.cogs.marketplace.marketplace import Marketplace
from src.services.marketplace_images import PostgresImageStore, download_image, normalize_image
from src.utils.outbound import SendOutcome, SendStatus


def png_bytes(size=(2000, 1000)):
    buffer = io.BytesIO()
    image = Image.new('RGB', size, 'red')
    image.save(buffer, format='PNG')
    return buffer.getvalue()


def test_normalization_is_webp_bounded_and_strips_metadata():
    stored = normalize_image(png_bytes())
    assert stored.width == 1600
    assert stored.height == 800
    assert len(stored.data) < 2 * 1024 * 1024
    with Image.open(io.BytesIO(stored.data)) as image:
        assert image.format == 'WEBP'
        assert not image.getexif()
        assert 'icc_profile' not in image.info


@pytest.mark.parametrize('data', [b'<svg><script>evil</script></svg>', b'not an image', b'x' * (8 * 1024 * 1024 + 1)])
def test_invalid_images_rejected(data):
    with pytest.raises((ValueError, OSError)):
        normalize_image(data)


@pytest.mark.parametrize(
    'url',
    [
        'http://cdn.discordapp.com/a',
        'https://evil.example/a',
        'https://cdn.discordapp.com:444/a',
        'https://user:pass@cdn.discordapp.com/a',
    ],
)
async def test_image_downloader_rejects_untrusted_urls(monkeypatch, url):
    session = MagicMock()
    monkeypatch.setattr('src.services.marketplace_images.get_session', lambda: session)
    assert await download_image(url) is None
    session.get.assert_not_called()


async def test_image_download_redirect_not_followed(monkeypatch):
    session = MagicMock()
    session.get.return_value.__aenter__ = AsyncMock(return_value=SimpleNamespace(status=302))
    session.get.return_value.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr('src.services.marketplace_images.get_session', lambda: session)
    assert await download_image('https://cdn.discordapp.com/a') is None
    assert session.get.call_args.kwargs['allow_redirects'] is False


async def test_store_caps_attachment_count(monkeypatch, mock_db):
    monkeypatch.setattr('src.services.marketplace_images.db', mock_db)
    image = normalize_image(png_bytes((10, 10)))
    downloader = AsyncMock(return_value=image)
    monkeypatch.setattr('src.services.marketplace_images.download_image', downloader)
    store = PostgresImageStore()
    attachments = [
        SimpleNamespace(id=i, url=f'https://cdn.discordapp.com/{i}', content_type='image/png') for i in range(10)
    ]
    assert await store.capture_attachments('one', attachments) == 1  # duplicate hashes coalesce
    assert downloader.await_count == 4
    inserts = [call for call in mock_db.execute.call_args_list if 'INSERT INTO' in call.args[0]]
    assert len(inserts) == 1


async def test_failed_download_preserves_previous_durable_image(monkeypatch, mock_db):
    monkeypatch.setattr('src.services.marketplace_images.db', mock_db)
    monkeypatch.setattr('src.services.marketplace_images.download_image', AsyncMock(return_value=None))
    attachment = SimpleNamespace(id=1, url='https://cdn.discordapp.com/one', content_type='image/png')
    assert await PostgresImageStore().capture_attachments('one', [attachment]) == 0
    assert all('DELETE FROM' not in call.args[0] for call in mock_db.execute.call_args_list)


async def test_publication_reuploads_stored_image_not_foreign_url(monkeypatch, mock_db, mock_guild, mock_user):
    monkeypatch.setattr('src.cogs.marketplace.marketplace.db', mock_db)
    channel = MagicMock(spec=nextcord.TextChannel)
    channel.id = 20
    channel.guild = mock_guild
    monkeypatch.setattr(
        'src.cogs.marketplace.marketplace.guild_settings_service.resolve_channel', AsyncMock(return_value=channel)
    )
    image = normalize_image(png_bytes((10, 10)))
    monkeypatch.setattr('src.cogs.marketplace.marketplace.image_store.get', AsyncMock(return_value=image))
    messenger = SimpleNamespace(
        send=AsyncMock(return_value=SendOutcome(SendStatus.SENT, message=cast(Any, SimpleNamespace(id=90))))
    )
    monkeypatch.setattr('src.cogs.marketplace.marketplace.outbound', messenger)
    await Marketplace(SimpleNamespace())._post_listing_to_channel(
        guild=mock_guild,
        listing_id='one',
        title='One',
        price=10,
        condition='good',
        category='Other',
        seller=mock_user,
        image_url='https://cdn.discordapp.com/expired?secret=signature',
    )
    kwargs = messenger.send.call_args.kwargs
    assert kwargs['embed'].image.url == 'attachment://listing.webp'
    assert kwargs['file'].filename == 'listing.webp'


def test_api_image_url_encodes_listing_id():
    assert PostgresImageStore().url_for('a/b', 1) == '/v1/marketplace/listings/a%2Fb/images/1'
