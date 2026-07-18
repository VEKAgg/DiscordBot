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


async def _find_listing_id(session: aiohttp.ClientSession, external_ref: str) -> str | None:
    params = {'filter[external_ref][_eq]': external_ref, 'fields': 'id', 'limit': '1'}
    async with session.get(f'{DIRECTUS_URL}/items/{_LISTINGS}', params=params, headers=_headers()) as resp:
        if resp.status != 200:
            return None
        rows = (await resp.json()).get('data') or []
        return rows[0]['id'] if rows else None


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

        existing_id = await _find_listing_id(session, listing['external_ref'])
        if existing_id:
            url = f'{DIRECTUS_URL}/items/{_LISTINGS}/{existing_id}'
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
        item_id = await _find_listing_id(session, external_ref)
        if not item_id:
            return
        url = f'{DIRECTUS_URL}/items/{_LISTINGS}/{item_id}'
        async with session.patch(url, json={'status': status}, headers=_headers()) as resp:
            if resp.status >= 400:
                logger.warning('Directus status update failed (%s): %s', resp.status, await resp.text())
    except Exception as exc:
        logger.warning('Directus status sync failed for %s: %s', external_ref, exc)
