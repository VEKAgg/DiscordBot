"""Offline durable image tests: bounded, sanitized images and no foreign CDN embeds."""

import io
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image

from src.services.marketplace_images import PostgresImageStore, download_image, normalize_image


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
    downloader = AsyncMock()
    monkeypatch.setattr('src.services.marketplace_images.download_image', downloader)
    attachments = [
        SimpleNamespace(id=i, url='https://cdn.discordapp.com/x', content_type='image/png') for i in range(9)
    ]
    with pytest.raises(ValueError, match='at most 8'):
        await PostgresImageStore().prepare_attachments('one', attachments)
    downloader.assert_not_awaited()


async def test_failed_download_does_not_replace_any_image(monkeypatch, mock_db):
    monkeypatch.setattr('src.services.marketplace_images.db', mock_db)
    monkeypatch.setattr('src.services.marketplace_images.download_image', AsyncMock(return_value=None))
    attachment = SimpleNamespace(id=1, url='https://cdn.discordapp.com/one', content_type='image/png')
    with pytest.raises(ValueError, match='No replacement'):
        await PostgresImageStore().capture_attachments('one', [attachment])
    mock_db.execute.assert_not_awaited()


async def test_reordering_uses_attachment_identity_not_old_position(monkeypatch, mock_db):
    monkeypatch.setattr('src.services.marketplace_images.db', mock_db)
    one = normalize_image(png_bytes((10, 10)))
    two = normalize_image(png_bytes((20, 20)))
    mock_db.fetch.return_value = [
        dict(source_attachment_id=1, bytes=one.data, sha256=one.sha256, width=10, height=10),
        dict(source_attachment_id=2, bytes=two.data, sha256=two.sha256, width=20, height=20),
    ]
    downloader = AsyncMock()
    monkeypatch.setattr('src.services.marketplace_images.download_image', downloader)
    attachments = [SimpleNamespace(id=i, content_type='image/png') for i in (2, 1)]
    ready = await PostgresImageStore().prepare_attachments('one', attachments)
    assert [image.sha256 for _, image in ready] == [two.sha256, one.sha256]
    downloader.assert_not_awaited()


async def test_empty_set_is_explicit_removal():
    conn = AsyncMock()
    await PostgresImageStore().replace(conn, 'one', [])
    assert 'DELETE FROM marketplace_listing_images' in conn.execute.call_args_list[0].args[0]


def test_api_image_url_encodes_listing_id():
    assert PostgresImageStore().url_for('a/b', 1) == '/v1/marketplace/listings/a%2Fb/images/1'
