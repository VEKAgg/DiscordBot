"""Read-only origin-scoped ingestion diagnostics and private image delivery.

Moderation belongs to core's admin API. This API cannot approve or edit a
canonical listing, and never grants public access to imported source images.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import StringConstraints

from src.api.auth import GuildAccess, Principal, bot_in_guild, current_user, guild_access
from src.api.discord_client import MANAGE_GUILD
from src.api.errors import ApiError
from src.api.pagination import decode_cursor, encode_cursor, limit_param
from src.database.database import db
from src.services.marketplace_images import image_store

router = APIRouter(tags=['marketplace'])
ListingID = Annotated[str, StringConstraints(pattern=r'^[A-Za-z0-9_-]{1,64}$')]


def _out(row) -> dict:
    result = dict(row)
    result['price'] = format(row['price'], '.2f') if row['price'] is not None else None
    result['images'] = [image_store.url_for(row['id'], position) for position in range(row['image_count'])]
    return result


@router.get('/guilds/{guild_id}/marketplace/listings')
async def listings(
    status: Literal[
        'draft', 'pending_review', 'active', 'reserved', 'archived', 'withdrawn', 'removed', 'sold', 'expired'
    ]
    | None = None,
    source: Literal['command', 'forum', 'text'] | None = None,
    cursor: str | None = None,
    limit: int = Depends(limit_param),
    access: GuildAccess = guild_access(MANAGE_GUILD),
) -> dict:
    after = decode_cursor(cursor)
    after_id = after.get('id') if after else None
    if after is not None and (not isinstance(after_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', after_id)):
        raise ApiError(422, 'invalid_cursor', 'Invalid cursor.')
    rows = await db.fetch(
        'SELECT l.id,l.title,l.description,l.price,l.currency,l.condition,l.status,l.source,l.image_missing,l.created_at,l.updated_at, '
        '(SELECT count(*) FROM marketplace_listing_images i WHERE i.listing_id=l.id) AS image_count '
        'FROM marketplace_listings l WHERE l.guild_id=$1 '
        'AND ($2::text IS NULL OR l.status=$2) AND ($3::text IS NULL OR l.source=$3) '
        'AND ($4::text IS NULL OR l.id<$4) ORDER BY l.id DESC LIMIT $5',
        access.guild_id,
        status,
        source,
        after_id,
        limit + 1,
    )
    return {
        'items': [_out(row) for row in rows[:limit]],
        'next_cursor': encode_cursor({'id': rows[limit - 1]['id']}) if len(rows) > limit else None,
    }


@router.get('/marketplace/listings/{listing_id}/images/{image_ref}')
async def listing_image(
    listing_id: ListingID, image_ref: str, request: Request, principal: Principal = Depends(current_user)
) -> Response:
    row = await db.fetch_one(
        'SELECT l.guild_id,u.discord_id FROM marketplace_listings l JOIN users u ON u.id=l.seller_id WHERE l.id=$1',
        listing_id,
    )
    if row is None:
        raise ApiError(404, 'not_found', 'Image not found.')
    if str(principal.user_id) != row['discord_id']:
        assert principal.identity is not None
        member = principal.identity.guilds.get(row['guild_id'])
        if member is None or not member.has(MANAGE_GUILD):
            raise ApiError(404, 'not_found', 'Image not found.')
        await bot_in_guild(row['guild_id'])
    if image_ref in {str(i) for i in range(8)}:
        image = await image_store.get(listing_id, int(image_ref))
    elif re.fullmatch(r'[0-9a-f]{64}', image_ref):
        image = None
        for position in range(8):
            candidate = await image_store.get(listing_id, position)
            if candidate is not None and candidate.sha256 == image_ref:
                image = candidate
                break
    else:
        raise ApiError(422, 'invalid_image', 'Use image position 0–7 or a SHA-256 digest.')
    if image is None:
        raise ApiError(404, 'not_found', 'Image not found.')
    etag = f'"{image.sha256}"'
    headers = {
        'ETag': etag,
        'Cache-Control': 'private, no-store',
        'X-Content-Type-Options': 'nosniff',
        'Vary': 'Authorization',
    }
    if request.headers.get('if-none-match') == etag:
        return Response(status_code=304, headers=headers)
    return Response(image.data, media_type=image.content_type, headers=headers)
