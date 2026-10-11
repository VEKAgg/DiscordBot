"""Verifies dashboard users against Discord itself (the client's guild list is never trusted).

Calls ``/users/@me`` and ``/users/@me/guilds`` with the user's OAuth bearer token (scopes
``identify guilds``). Results are cached for 60 s by SHA-256 of the token (the raw token is never
stored or logged). Privileged writes pass ``fresh=True`` to bypass the cache.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass

import aiohttp

from src.api.config import settings
from src.api.errors import ApiError
from src.utils.ttlcache import TTLDict

# Discord permission bits used by the API's permission matrix.
ADMINISTRATOR = 1 << 3
KICK_MEMBERS = 1 << 1
BAN_MEMBERS = 1 << 2
MANAGE_GUILD = 1 << 5
MANAGE_ROLES = 1 << 28
MODERATE_MEMBERS = 1 << 40
MANAGE_CHANNELS = 1 << 4

MAX_GUILD_PAGES = 5


@dataclass(frozen=True)
class DiscordUser:
    id: int
    username: str
    global_name: str | None
    avatar: str | None


@dataclass(frozen=True)
class UserGuild:
    id: int
    name: str
    icon: str | None
    owner: bool
    permissions: int

    def has(self, bit: int) -> bool:
        return self.owner or bool(self.permissions & ADMINISTRATOR) or bool(self.permissions & bit)


@dataclass(frozen=True)
class Identity:
    user: DiscordUser
    guilds: dict[int, UserGuild]


class DiscordClient:
    def __init__(self, base: str | None = None, timeout: float = 5.0, concurrency: int = 10) -> None:
        self.base = (base or settings.discord_api_base).rstrip('/')
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._sem = asyncio.Semaphore(concurrency)
        self._cache: TTLDict[str, Identity] = TTLDict(ttl=60, maxsize=10_000)
        self._session: aiohttp.ClientSession | None = None

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def _get(self, path: str, token: str):
        try:
            async with (
                self._sem,
                self._get_session().get(f'{self.base}{path}', headers={'Authorization': f'Bearer {token}'}) as resp,
            ):
                if resp.status == 401:
                    raise ApiError(401, 'invalid_token', 'The Discord token is invalid or expired.')
                if resp.status == 429:
                    retry = resp.headers.get('Retry-After', '5')
                    raise ApiError(
                        503,
                        'discord_rate_limited',
                        'Discord is rate limiting; retry shortly.',
                        headers={'Retry-After': retry},
                    )
                if resp.status >= 400:
                    raise ApiError(503, 'discord_unavailable', 'Could not verify the account with Discord.')
                return await resp.json()
        except ApiError:
            raise
        except (aiohttp.ClientError, TimeoutError):
            raise ApiError(503, 'discord_unavailable', 'Could not reach Discord to verify the account.') from None

    async def identify(self, token: str, *, fresh: bool = False) -> Identity:
        key = hashlib.sha256(token.encode()).hexdigest()
        if not fresh:
            cached = self._cache.get(key)
            if cached is not None:
                return cached
        me = await self._get('/users/@me', token)
        guilds: list[dict] = []
        after = '0'
        for _ in range(MAX_GUILD_PAGES):  # Discord returns at most 200 guilds per page
            page = await self._get(f'/users/@me/guilds?limit=200&after={after}', token)
            guilds.extend(page)
            if len(page) < 200:
                break
            after = page[-1]['id']
        identity = Identity(
            user=DiscordUser(
                id=int(me['id']),
                username=me.get('username', ''),
                global_name=me.get('global_name'),
                avatar=me.get('avatar'),
            ),
            guilds={
                int(g['id']): UserGuild(
                    id=int(g['id']),
                    name=g.get('name', ''),
                    icon=g.get('icon'),
                    owner=bool(g.get('owner')),
                    permissions=int(g.get('permissions', 0)),
                )
                for g in guilds
            },
        )
        self._cache.set(key, identity)
        return identity


discord_client = DiscordClient()
