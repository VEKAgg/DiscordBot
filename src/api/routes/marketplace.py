"""Guild-scoped marketplace moderation and authenticated durable image delivery.

An active listing is not proof its forum/channel is public. Anonymous image access is
intentionally disabled until public visibility has an authoritative persisted policy.
"""

from __future__ import annotations

import json
import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from src.api.auth import GuildAccess, Principal, bot_in_guild, current_user, guild_access
from src.api.discord_client import MANAGE_GUILD
from src.api.errors import ApiError
from src.api.pagination import decode_cursor, encode_cursor, limit_param
from src.database.database import db
from src.services.marketplace_images import image_store
from src.services.marketplace_service import validate_price

router = APIRouter(tags=['marketplace'])
ListingID = Annotated[str, StringConstraints(pattern=r'^[A-Za-z0-9_-]{1,64}$')]
_SCOPE = """(l.guild_id = $1 OR EXISTS (
    SELECT 1 FROM marketplace_publications p WHERE p.listing_id = l.id AND p.guild_id = $1))"""
_COLUMNS = (
    'l.id, l.title, l.description, l.price, l.condition, l.status, l.source, l.image_missing, l.created_at, l.updated_at, '
    '(SELECT COUNT(*) FROM marketplace_listing_images i WHERE i.listing_id = l.id) AS image_count'
)


class ListingPatch(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    status: Literal['active', 'removed'] | None = None
    price: str | None = Field(default=None, max_length=32)


def _out(row) -> dict:
    result = dict(row)
    result['price'] = format(row['price'], '.2f') if row['price'] is not None else None
    result['images'] = [image_store.url_for(row['id'], position) for position in range(row['image_count'])]
    return result


@router.get('/guilds/{guild_id}/marketplace/listings')
async def listings(
    status: Literal['active', 'pending_review', 'archived', 'withdrawn', 'removed', 'sold'] | None = None,
    source: Literal['command', 'forum'] | None = None,
    cursor: str | None = None,
    limit: int = Depends(limit_param),
    access: GuildAccess = guild_access(MANAGE_GUILD),
) -> dict:
    after = decode_cursor(cursor)
    after_id = after.get('id') if after else None
    if after is not None and (not isinstance(after_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', after_id)):
        raise ApiError(422, 'invalid_cursor', 'Invalid cursor.')
    rows = await db.fetch(
        f'SELECT {_COLUMNS} FROM marketplace_listings l WHERE {_SCOPE} '
        'AND ($2::text IS NULL OR l.status = $2) AND ($3::text IS NULL OR l.source = $3) '
        'AND ($4::text IS NULL OR l.id < $4) ORDER BY l.id DESC LIMIT $5',
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


@router.patch('/guilds/{guild_id}/marketplace/listings/{listing_id}')
async def update_listing(
    listing_id: ListingID, body: ListingPatch, access: GuildAccess = guild_access(MANAGE_GUILD, fresh=True)
) -> dict:
    if not body.model_fields_set or any(getattr(body, key) is None for key in body.model_fields_set):
        raise ApiError(422, 'invalid_patch', 'Specify a non-null price or status.')
    try:
        price = validate_price(body.price) if body.price is not None else None
    except ValueError as exc:
        raise ApiError(422, 'invalid_price', str(exc)) from None
    async with db.transaction() as conn:
        current = await conn.fetchrow(
            f'SELECT {_COLUMNS} FROM marketplace_listings l WHERE {_SCOPE} AND l.id = $2 FOR UPDATE',
            access.guild_id,
            listing_id,
        )
        if current is None:
            raise ApiError(404, 'not_found', 'Listing not found in this server.')
        if current['status'] in {'withdrawn', 'sold', 'removed'}:
            raise ApiError(409, 'listing_closed', 'Closed listings cannot be reactivated or edited here.')
        if body.status == 'active' and current['status'] != 'pending_review':
            raise ApiError(409, 'not_pending_review', 'Only pending-review listings can be approved.')
        if body.status == 'active' and price is None and current['price'] is None:
            raise ApiError(422, 'price_required', 'Set a price before approving this listing.')
        row = await conn.fetchrow(
            f'UPDATE marketplace_listings l SET price = COALESCE($2::numeric, l.price), '
            'status = COALESCE($3::text, l.status), updated_at = clock_timestamp(), '
            "price_override = l.price_override OR (l.source = 'forum' AND $2::numeric IS NOT NULL), "
            "forum_review_status = CASE WHEN l.source = 'forum' AND $3::text IS NOT NULL "
            'THEN $3::text ELSE l.forum_review_status END '
            f'WHERE l.id = $1 RETURNING {_COLUMNS}',
            listing_id,
            price,
            body.status,
        )
        await conn.execute(
            'INSERT INTO audit_logs (user_id, guild_id, action, details, severity) '
            "VALUES ($1, $2, 'dashboard_marketplace_changed', $3::jsonb, 'info')",
            access.principal.audit_actor,
            str(access.guild_id),
            json.dumps(
                {
                    'source': 'dashboard',
                    'listing_id': listing_id,
                    'before': {
                        'price': str(current['price']) if current['price'] is not None else None,
                        'status': current['status'],
                    },
                    'after': {
                        'price': str(row['price']) if row['price'] is not None else None,
                        'status': row['status'],
                    },
                }
            ),
        )
    return _out(row)


@router.get('/marketplace/listings/{listing_id}/images/{image_ref}')
async def listing_image(
    listing_id: ListingID,
    image_ref: str,
    request: Request,
    principal: Principal = Depends(current_user),
) -> Response:
    row = await db.fetch_one(
        'SELECT l.guild_id, u.discord_id FROM marketplace_listings l '
        'JOIN users u ON u.id = l.seller_id WHERE l.id = $1',
        listing_id,
    )
    if row is None:
        raise ApiError(404, 'not_found', 'Image not found.')
    if str(principal.user_id) != row['discord_id']:
        assert principal.identity is not None
        guilds = await db.fetch(
            'SELECT guild_id FROM marketplace_publications WHERE listing_id = $1 '
            'UNION SELECT guild_id FROM marketplace_listings WHERE id = $1 AND guild_id IS NOT NULL',
            listing_id,
        )
        authorized = False
        for guild in guilds:
            member = principal.identity.guilds.get(guild['guild_id'])
            if member is not None and member.has(MANAGE_GUILD):
                await bot_in_guild(guild['guild_id'])
                authorized = True
                break
        if not authorized:
            raise ApiError(404, 'not_found', 'Image not found.')
    if image_ref in {'0', '1', '2', '3'}:
        image = await image_store.get(listing_id, int(image_ref))
    elif re.fullmatch(r'[0-9a-f]{64}', image_ref):
        image = None
        for position in range(4):
            candidate = await image_store.get(listing_id, position)
            if candidate is not None and candidate.sha256 == image_ref:
                image = candidate
                break
    else:
        raise ApiError(422, 'invalid_image', 'Use image position 0–3 or a SHA-256 digest.')
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
