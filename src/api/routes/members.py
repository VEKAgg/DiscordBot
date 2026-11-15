"""Bounded name lookup for authorized guild dashboards, not a global member directory."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from src.api.auth import GuildAccess, guild_access
from src.api.discord_client import MANAGE_GUILD, discord_client
from src.api.errors import ApiError
from src.api.ratelimit import RateLimiter

router = APIRouter(tags=['members'])
lookup_limiter = RateLimiter(30)
Snowflake = Annotated[str, StringConstraints(pattern=r'^[1-9][0-9]{0,18}$')]


class MemberLookup(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    user_ids: list[Snowflake] = Field(min_length=1, max_length=25)

    @field_validator('user_ids')
    @classmethod
    def bounded_snowflakes(cls, values):
        if any(int(value) >= 2**63 for value in values):
            raise ValueError('Invalid member ID')
        return list(dict.fromkeys(values))


@router.post('/guilds/{guild_id}/members/lookup')
async def lookup_members(
    body: MemberLookup, response: Response, access: GuildAccess = guild_access(MANAGE_GUILD)
) -> dict:
    lookup_limiter.check('global')
    lookup_limiter.check(f'guild:{access.guild_id}')
    items = []
    try:
        async with asyncio.timeout(15):
            for user_id in body.user_ids:
                items.append(await discord_client.guild_member(access.guild_id, int(user_id)))
    except TimeoutError:
        raise ApiError(503, 'member_lookup_unavailable', 'Member lookup timed out. Retry shortly.') from None
    response.headers['Cache-Control'] = 'private, no-store'
    return {'items': items}
