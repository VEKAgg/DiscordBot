"""Durable marketplace image storage; no reliance on expiring foreign attachment URLs.

Only Discord CDN HTTPS images are fetched. Images are decoded/re-encoded in a worker
thread, removing EXIF/GPS and animation, bounding dimensions and stored byte size.
The API can serve get() with digest ETags; position URLs must revalidate (not immutable).
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import warnings
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

import nextcord
from PIL import Image, ImageOps

from src.database.database import db
from src.utils.http import get_session

logger = logging.getLogger('VEKA.marketplace.images')
MAX_DOWNLOAD_BYTES = 8 * 1024 * 1024
MAX_STORED_BYTES = 2 * 1024 * 1024
MAX_PIXELS = 20_000_000
MAX_IMAGES = 4
_ALLOWED_HOSTS = {'cdn.discordapp.com', 'media.discordapp.net'}


@dataclass(frozen=True)
class StoredImage:
    data: bytes
    sha256: str
    width: int
    height: int
    content_type: str = 'image/webp'

    def file(self) -> nextcord.File:
        return nextcord.File(io.BytesIO(self.data), filename='listing.webp')


class ImageStore(Protocol):
    async def put(
        self,
        listing_id: str,
        position: int,
        image: StoredImage,
        *,
        message_id: int | None = None,
        attachment_id: int | None = None,
    ) -> None: ...
    async def get(self, listing_id: str, position: int = 0) -> StoredImage | None: ...
    def url_for(self, listing_id: str, position: int = 0) -> str: ...


def normalize_image(data: bytes) -> StoredImage:
    if len(data) > MAX_DOWNLOAD_BYTES:
        raise ValueError('Image download exceeds size limit')
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(data)) as source:
            if source.format not in {'PNG', 'JPEG', 'GIF', 'WEBP'}:
                raise ValueError('Unsupported image format')
            if source.width * source.height > MAX_PIXELS:
                raise ValueError('Image dimensions exceed size limit')
            # New pixels/re-encoding strip all metadata; use the first animation frame.
            image = ImageOps.exif_transpose(source).convert('RGB')
            image.thumbnail((1600, 1600))
            output = io.BytesIO()
            image.save(output, format='WEBP', quality=80, method=4, exif=b'', icc_profile=b'')
            encoded = output.getvalue()
            if len(encoded) > MAX_STORED_BYTES:
                raise ValueError('Normalized image exceeds stored size limit')
            return StoredImage(encoded, hashlib.sha256(encoded).hexdigest(), image.width, image.height)


async def download_image(url: str) -> StoredImage | None:
    """Fetch an allowlisted CDN resource without following redirects; never log signed URLs."""
    try:
        parts = urlsplit(url)
        if (
            parts.scheme != 'https'
            or parts.hostname not in _ALLOWED_HOSTS
            or parts.username
            or parts.password
            or parts.port not in (None, 443)
        ):
            return None
        async with get_session().get(url, allow_redirects=False) as response:
            if response.status != 200:
                return None
            mime = response.headers.get('Content-Type', '').split(';')[0].strip().lower()
            if mime not in {'image/png', 'image/jpeg', 'image/gif', 'image/webp'}:
                return None
            if response.content_length is not None and response.content_length > MAX_DOWNLOAD_BYTES:
                return None
            chunks = []
            size = 0
            async for chunk in response.content.iter_chunked(64 * 1024):
                size += len(chunk)
                if size > MAX_DOWNLOAD_BYTES:
                    return None
                chunks.append(chunk)
        return await asyncio.to_thread(normalize_image, b''.join(chunks))
    except Exception as exc:
        logger.warning('Marketplace image could not be stored (%s)', type(exc).__name__)
        return None


class PostgresImageStore:
    async def put(
        self,
        listing_id: str,
        position: int,
        image: StoredImage,
        *,
        message_id: int | None = None,
        attachment_id: int | None = None,
    ) -> None:
        if not 0 <= position < MAX_IMAGES:
            raise ValueError('Invalid image position')
        await db.execute(
            """INSERT INTO marketplace_listing_images
                   (listing_id, position, content_type, sha256, width, height, bytes,
                    source_message_id, source_attachment_id)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
               ON CONFLICT (listing_id, position) DO UPDATE SET
                   content_type = EXCLUDED.content_type, sha256 = EXCLUDED.sha256,
                   width = EXCLUDED.width, height = EXCLUDED.height, bytes = EXCLUDED.bytes,
                   source_message_id = EXCLUDED.source_message_id,
                   source_attachment_id = EXCLUDED.source_attachment_id""",
            listing_id,
            position,
            image.content_type,
            image.sha256,
            image.width,
            image.height,
            image.data,
            message_id,
            attachment_id,
        )

    async def get(self, listing_id: str, position: int = 0) -> StoredImage | None:
        row = await db.fetch_one(
            'SELECT bytes, sha256, width, height, content_type FROM marketplace_listing_images '
            'WHERE listing_id = $1 AND position = $2',
            listing_id,
            position,
        )
        return (
            StoredImage(row['bytes'], row['sha256'], row['width'], row['height'], row['content_type']) if row else None
        )

    def url_for(self, listing_id: str, position: int = 0) -> str:
        # Generated listing IDs are alphanumeric; future callers must encode arbitrary IDs.
        from urllib.parse import quote

        return f'/v1/marketplace/listings/{quote(listing_id, safe="")}/images/{position}'

    async def capture_attachments(self, listing_id: str, attachments, *, message_id: int | None = None) -> int:
        images = [a for a in attachments if (a.content_type or '').startswith('image/')][:MAX_IMAGES]
        existing = await db.fetch(
            'SELECT source_attachment_id FROM marketplace_listing_images WHERE listing_id = $1 ORDER BY position',
            listing_id,
        )
        if images and [row['source_attachment_id'] for row in existing] == [a.id for a in images]:
            return len(images)  # Signed URL refreshes do not change attachment identity.
        captured = 0
        digests: set[str] = set()
        for attachment in images:
            current = await db.fetch_one(
                'SELECT sha256 FROM marketplace_listing_images WHERE listing_id = $1 AND source_attachment_id = $2',
                listing_id,
                attachment.id,
            )
            image = await self.get(listing_id, captured) if current else None
            if current is None or image is None or image.sha256 != current['sha256']:
                image = await download_image(attachment.url)
            if image is None:
                continue
            if image.sha256 in digests:
                continue
            digests.add(image.sha256)
            await self.put(listing_id, captured, image, message_id=message_id, attachment_id=attachment.id)
            captured += 1
        # Don't discard durable old images because a transient CDN failure occurred.
        if captured == len(images):
            await db.execute(
                'DELETE FROM marketplace_listing_images WHERE listing_id = $1 AND position >= $2', listing_id, captured
            )
        await db.execute(
            'UPDATE marketplace_listings SET image_missing = $2 WHERE id = $1',
            listing_id,
            bool(images) and captured == 0,
        )
        return captured


image_store = PostgresImageStore()
