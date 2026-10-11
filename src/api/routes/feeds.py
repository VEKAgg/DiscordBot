"""RSS feed subscriptions for a server (Manage Server).

Feed URLs are validated by fetching them through the same SSRF-guarded, size-capped fetcher the bot
uses. ``/test`` returns a bounded preview and never posts to Discord; the bot remains the only poller.
The destination channel must be a text/announcement channel in the bot's snapshot; the bot re-checks
its own permissions in that channel at posting time.
"""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Path
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StringConstraints

from src.api.auth import GuildAccess, guild_access
from src.api.discord_client import MANAGE_GUILD
from src.api.errors import ApiError
from src.api.ratelimit import RateLimiter
from src.services import feed_service
from src.services.rss_service import RSSService

router = APIRouter(prefix='/guilds/{guild_id}/feeds', tags=['feeds'])

Snowflake = Annotated[str, StringConstraints(pattern=r'^[1-9]\d{0,18}$')]
SubscriptionId = Path(gt=0, lt=2**31)
_fetch_limiter = RateLimiter(per_minute=10)  # outbound feed fetches per guild
_rss = RSSService()


class FeedCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

    url: Annotated[str, StringConstraints(min_length=8, max_length=feed_service.MAX_URL_LENGTH)]
    channel_id: Snowflake
    name: Annotated[str, StringConstraints(max_length=feed_service.MAX_NAME_LENGTH)] = ''
    interval_minutes: StrictInt = Field(default=30, ge=feed_service.MIN_INTERVAL, le=feed_service.MAX_INTERVAL)


class FeedPatch(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

    channel_id: Snowflake | None = None
    name: Annotated[str, StringConstraints(min_length=1, max_length=feed_service.MAX_NAME_LENGTH)] | None = None
    interval_minutes: StrictInt | None = Field(default=None, ge=feed_service.MIN_INTERVAL, le=feed_service.MAX_INTERVAL)
    paused: StrictBool | None = None


def _out(row: dict) -> dict:
    def iso(value):
        return value.isoformat() if value else None

    return {
        'id': row['id'],
        'channel_id': str(row['channel_id']) if row['channel_id'] else None,
        'url': row['feed_url'],
        'name': row['feed_name'],
        'interval_minutes': row['poll_interval_minutes'],
        'paused': row['paused'],
        'healthy': (row['consecutive_failures'] or 0) == 0,
        'consecutive_failures': row['consecutive_failures'] or 0,
        'last_polled_at': iso(row['last_polled_at']),
        'next_retry_at': iso(row['next_retry_at']),
    }


def _check_channel(snapshot: dict, channel_id: str) -> None:
    channels = snapshot.get('channels')
    channels = json.loads(channels) if isinstance(channels, str) else (channels or [])
    channel = next((c for c in channels if c['id'] == channel_id), None)
    if channel is None:
        raise ApiError(422, 'unknown_channel', f'Channel {channel_id} is not in this server.')
    if channel.get('type') not in ('text', 'news'):
        raise ApiError(422, 'wrong_channel_type', 'Feeds post into text or announcement channels.')


async def _fetch(access: GuildAccess, url: str) -> dict:
    _fetch_limiter.check(f'guild:{access.guild_id}')
    try:
        data = await _rss.fetch_feed(url)
    except Exception:
        data = None
    if not data:
        raise ApiError(422, 'invalid_feed', 'Could not fetch or parse an RSS/Atom feed at that URL.')
    return data


@router.get('')
async def list_feeds(access: GuildAccess = guild_access(MANAGE_GUILD)) -> dict:
    rows = await feed_service.list_subscriptions(access.guild_id)
    return {'items': [_out(r) for r in rows], 'limit': feed_service.FEED_MAX_SUBSCRIPTIONS}


@router.post('', status_code=201)
async def add_feed(body: FeedCreate, access: GuildAccess = guild_access(MANAGE_GUILD, fresh=True)) -> dict:
    url = body.url.strip()
    if not url.lower().startswith(('http://', 'https://')):
        raise ApiError(422, 'invalid_url', 'Use an http(s) feed URL.')
    _check_channel(access.snapshot, body.channel_id)
    data = await _fetch(access, url)
    name = (body.name.strip() or str(data.get('title', '')).strip() or url)[: feed_service.MAX_NAME_LENGTH]
    try:
        row = await feed_service.upsert_subscription(
            access.guild_id, int(body.channel_id), url, name, body.interval_minutes, actor=access.principal.audit_actor
        )
    except feed_service.FeedLimitReached:
        raise ApiError(
            409, 'feed_limit_reached', f'This server allows {feed_service.FEED_MAX_SUBSCRIPTIONS} subscriptions.'
        ) from None
    return _out(row)


@router.patch('/{subscription_id}')
async def update_feed(
    body: FeedPatch,
    subscription_id: int = SubscriptionId,
    access: GuildAccess = guild_access(MANAGE_GUILD, fresh=True),
) -> dict:
    for field in body.model_fields_set:
        if getattr(body, field) is None:
            raise ApiError(422, 'invalid_value', f'{field} cannot be null.')
    if body.channel_id:
        _check_channel(access.snapshot, body.channel_id)
    row = await feed_service.update_subscription(
        access.guild_id,
        subscription_id,
        channel_id=int(body.channel_id) if body.channel_id else None,
        name=body.name.strip() if body.name else None,
        interval=body.interval_minutes,
        paused=body.paused,
        actor=access.principal.audit_actor,
    )
    if row is None:
        raise ApiError(404, 'not_found', 'Subscription not found.')
    return _out(row)


@router.delete('/{subscription_id}', status_code=204)
async def remove_feed(
    subscription_id: int = SubscriptionId, access: GuildAccess = guild_access(MANAGE_GUILD, fresh=True)
) -> None:
    if not await feed_service.remove_subscription(access.guild_id, subscription_id, actor=access.principal.audit_actor):
        raise ApiError(404, 'not_found', 'Subscription not found.')


@router.post('/{subscription_id}/test')
async def test_feed(subscription_id: int = SubscriptionId, access: GuildAccess = guild_access(MANAGE_GUILD)) -> dict:
    row = await feed_service.get_subscription(access.guild_id, subscription_id)
    if row is None:
        raise ApiError(404, 'not_found', 'Subscription not found.')
    data = await _fetch(access, row['feed_url'])
    entries = data.get('entries') or []
    preview = [
        {'title': str(e.get('title', ''))[:200], 'link': str(e.get('link', ''))[:500], 'published': e.get('published')}
        for e in entries[:3]
    ]
    return {'title': str(data.get('title', ''))[:200], 'entries': preview}
