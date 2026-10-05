"""One-way publish of Discord marketplace listings to the VEKA web CMS (Directus).

The bot keeps its own PostgreSQL as the source of truth and best-effort mirrors
listings into a Directus `marketplace_listings` collection so the web frontend
can display them. Every call here is best-effort: failures are logged and
swallowed so marketplace commands — and the never-crash contract — are never
affected by a Directus outage. No-op until DIRECTUS_URL + DIRECTUS_SERVICE_TOKEN
are configured.
"""

import logging
from typing import Any

import aiohttp

from src.config.config import DIRECTUS_SERVICE_TOKEN, DIRECTUS_SYNC_ENABLED, DIRECTUS_URL
from src.utils.http import get_session

logger = logging.getLogger('VEKA.directus_sync')

_LISTINGS = 'marketplace_listings'


def _headers() -> dict[str, str]:
    return {'Authorization': f'Bearer {DIRECTUS_SERVICE_TOKEN}', 'Content-Type': 'application/json'}


async def _resolve_profile_id(session: aiohttp.ClientSession, discord_id: str) -> str | None:
    """Best-effort map a Discord id to a VEKA profile id. Returns None if unlinked."""
    params = {'filter[discord_id][_eq]': discord_id, 'fields': 'id', 'limit': '1'}
    async with session.get(f'{DIRECTUS_URL}/items/profiles', params=params, headers=_headers()) as resp:
        if resp.status != 200:
            return None
        rows = (await resp.json()).get('data') or []
        return rows[0]['id'] if rows else None


async def _find_listing(session: aiohttp.ClientSession, external_ref: str) -> dict | None:
    params = {'filter[external_ref][_eq]': external_ref, 'fields': 'id,image_url', 'limit': '1'}
    async with session.get(f'{DIRECTUS_URL}/items/{_LISTINGS}', params=params, headers=_headers()) as resp:
        if resp.status != 200:
            return None
        rows = (await resp.json()).get('data') or []
        return rows[0] if rows else None


def _is_hosted(url: str | None) -> bool:
    """True if the URL already points at our Directus asset store (re-hosted)."""
    return bool(url) and url.startswith(f'{DIRECTUS_URL}/assets/')


async def _rehost_image(session: aiohttp.ClientSession, url: str) -> str | None:
    """Download an image (e.g. an ephemeral Discord CDN URL) and re-upload it to
    Directus files so it stays available after the source link expires. Returns a
    persistent asset URL, or None if the source can't be fetched (dead link)."""
    try:
        async with session.head(url) as head_resp:
            content_length = head_resp.headers.get('Content-Length')
            if content_length and int(content_length) > 8 * 1024 * 1024:  # 8 MB limit
                logger.warning('Image too large (%s bytes), skipping re-host: %s', content_length, url)
                return None

        async with session.get(url) as resp:
            if resp.status != 200:
                return None
            content_type = resp.headers.get('Content-Type', 'image/png')
            data = await resp.read()
        form = aiohttp.FormData()
        form.add_field('file', data, filename='listing', content_type=content_type)
        # Multipart: let aiohttp set Content-Type (with boundary), only pass auth.
        async with session.post(
            f'{DIRECTUS_URL}/files', data=form, headers={'Authorization': f'Bearer {DIRECTUS_SERVICE_TOKEN}'}
        ) as resp:
            if resp.status >= 400:
                logger.warning('Directus file upload failed (%s): %s', resp.status, await resp.text())
                return None
            file_id = (await resp.json()).get('data', {}).get('id')
            return f'{DIRECTUS_URL}/assets/{file_id}' if file_id else None
    except Exception as exc:
        logger.warning('Image re-host failed for %s: %s', url, exc)
        return None


async def upsert_listing(listing: dict[str, Any]) -> None:
    """Create or update the Directus mirror of a bot listing, keyed by external_ref.

    Expected keys: external_ref, seller_discord_id, title, description, price,
    condition, category, status, image_url, listing_created_at. Never raises.
    """
    if not DIRECTUS_SYNC_ENABLED:
        return
    try:
        session = get_session()
        payload = {k: v for k, v in listing.items() if v is not None}

        profile_id = await _resolve_profile_id(session, str(listing['seller_discord_id']))
        if profile_id:
            payload['seller_profile'] = profile_id

        existing = await _find_listing(session, listing['external_ref'])

        # Image: keep an already re-hosted asset; otherwise re-host the source URL
        # to Directus files so it survives Discord's link expiry. A dead source
        # (expired link on an old listing) resolves to no image, not a broken one.
        img = payload.get('image_url')
        if img and not _is_hosted(img):
            if existing and _is_hosted(existing.get('image_url')):
                payload['image_url'] = existing['image_url']
            else:
                payload['image_url'] = await _rehost_image(session, img)

        if existing:
            url = f'{DIRECTUS_URL}/items/{_LISTINGS}/{existing["id"]}'
            async with session.patch(url, json=payload, headers=_headers()) as resp:
                if resp.status >= 400:
                    logger.warning('Directus listing update failed (%s): %s', resp.status, await resp.text())
        else:
            url = f'{DIRECTUS_URL}/items/{_LISTINGS}'
            async with session.post(url, json=payload, headers=_headers()) as resp:
                if resp.status >= 400:
                    logger.warning('Directus listing create failed (%s): %s', resp.status, await resp.text())
    except Exception as exc:
        logger.warning('Directus marketplace sync failed for %s: %s', listing.get('external_ref'), exc)


async def set_listing_status(external_ref: str, status: str) -> None:
    """Best-effort status change on the mirror (e.g. withdrawn, sold). Never raises."""
    if not DIRECTUS_SYNC_ENABLED:
        return
    try:
        session = get_session()
        existing = await _find_listing(session, external_ref)
        if not existing:
            return
        url = f'{DIRECTUS_URL}/items/{_LISTINGS}/{existing["id"]}'
        async with session.patch(url, json={'status': status}, headers=_headers()) as resp:
            if resp.status >= 400:
                logger.warning('Directus status update failed (%s): %s', resp.status, await resp.text())
    except Exception as exc:
        logger.warning('Directus status sync failed for %s: %s', external_ref, exc)
