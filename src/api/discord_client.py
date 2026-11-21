"""Verifies dashboard users against Discord itself (the client's guild list is never trusted).

Calls ``/users/@me`` and ``/users/@me/guilds`` with the user's OAuth bearer token (scopes
``identify guilds``). Results are cached for 60 s by SHA-256 of the token (the raw token is never
stored or logged). Privileged writes pass ``fresh=True`` to bypass the cache.

Discord allows only about one ``/users/@me/guilds`` call per second per user, and a dashboard page
makes several API requests at once. Concurrent lookups for one token therefore share a single
Discord round trip, and a short rate-limit wait is waited out once instead of failing the page.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
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
# A 429 asking to wait at most this long is retried once; longer waits fail fast with Retry-After.
MAX_RETRY_WAIT = 2.0


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
        self._member_cache: TTLDict[tuple[int, int], dict] = TTLDict(ttl=60, maxsize=10_000)
        # Identity lookups in flight, by token hash, so concurrent requests share one.
        self._inflight: dict[str, asyncio.Task[Identity]] = {}
        self._session: aiohttp.ClientSession | None = None

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def _get(self, path: str, token: str):
        for attempt in range(2):
            retry_in = 0.0
            try:
                async with (
                    self._sem,
                    self._get_session().get(f'{self.base}{path}', headers={'Authorization': f'Bearer {token}'}) as resp,
                ):
                    if resp.status == 401:
                        raise ApiError(401, 'invalid_token', 'The Discord token is invalid or expired.')
                    if resp.status == 429:
                        wait = _retry_after(resp.headers.get('Retry-After'))
                        if attempt == 0 and wait <= MAX_RETRY_WAIT:
                            retry_in = wait
                        else:
                            raise ApiError(
                                503,
                                'discord_rate_limited',
                                'Discord is rate limiting; retry shortly.',
                                headers={'Retry-After': str(max(1, round(wait)))},
                            )
                    elif resp.status >= 400:
                        raise ApiError(503, 'discord_unavailable', 'Could not verify the account with Discord.')
                    else:
                        return await resp.json()
            except ApiError:
                raise
            except (aiohttp.ClientError, TimeoutError):
                raise ApiError(503, 'discord_unavailable', 'Could not reach Discord to verify the account.') from None
            # Outside the semaphore, so other users are not held up while this one waits.
            await asyncio.sleep(retry_in)
        raise AssertionError('unreachable')

    async def guild_member(self, guild_id: int, user_id: int) -> dict:
        """Minimal current-guild member identity, never a global /users directory.

        The route must authorize Manage Server + bot presence before this call.
        Cached responses are keyed by guild AND member, never just a user ID.
        """
        key = (guild_id, user_id)
        cached = self._member_cache.get(key)
        if cached is not None:
            return dict(cached)
        token = settings.discord_bot_token
        if not token:
            raise ApiError(503, 'member_lookup_unconfigured', 'Member lookup is not configured.')
        missing = {'id': str(user_id), 'username': None, 'display_name': None, 'avatar_url': None, 'found': False}
        try:
            async with (
                self._sem,
                self._get_session().get(
                    f'{self.base}/guilds/{guild_id}/members/{user_id}',
                    headers={'Authorization': f'Bot {token}'},
                    allow_redirects=False,
                ) as response,
            ):
                if response.status == 404:
                    self._member_cache.set(key, missing)
                    return dict(missing)
                if response.status == 429:
                    raw = response.headers.get('Retry-After', '5')
                    retry = (
                        str(min(3600, max(1, int(float(raw)))))
                        if len(raw) < 10 and raw.replace('.', '', 1).isdigit()
                        else '5'
                    )
                    raise ApiError(
                        503,
                        'discord_rate_limited',
                        'Discord is rate limiting member lookup.',
                        headers={'Retry-After': retry},
                    )
                if response.status != 200:
                    raise ApiError(503, 'member_lookup_unavailable', 'Could not read this server’s members.')
                data = bytearray()
                async for chunk in response.content.iter_chunked(16384):
                    data.extend(chunk)
                    if len(data) > 65536:
                        raise ApiError(503, 'member_lookup_unavailable', 'Discord returned an invalid member response.')
                member = json.loads(data)
                user = member['user']
                if str(user['id']) != str(user_id):
                    raise ValueError('Unexpected member')
                username = str(user.get('username') or '')[:100]
                display = str(member.get('nick') or user.get('global_name') or username)[:100]
                avatar = member.get('avatar') or user.get('avatar')
                avatar_url = None
                if isinstance(avatar, str) and re.fullmatch(r'[A-Za-z0-9_]{1,100}', avatar):
                    suffix = 'gif' if avatar.startswith('a_') else 'png'
                    path = f'guilds/{guild_id}/users/{user_id}' if member.get('avatar') else f'avatars/{user_id}'
                    avatar_url = (
                        f'https://cdn.discordapp.com/{path}/avatars/{avatar}.{suffix}'
                        if member.get('avatar')
                        else f'https://cdn.discordapp.com/{path}/{avatar}.{suffix}'
                    )
                result = {
                    'id': str(user_id),
                    'username': username,
                    'display_name': display,
                    'avatar_url': avatar_url,
                    'found': True,
                }
                self._member_cache.set(key, result)
                return dict(result)
        except ApiError:
            raise
        except (aiohttp.ClientError, TimeoutError, ValueError, KeyError, TypeError):
            raise ApiError(503, 'member_lookup_unavailable', 'Could not read this server’s members.') from None

    async def identify(self, token: str, *, fresh: bool = False) -> Identity:
        key = hashlib.sha256(token.encode()).hexdigest()
        if not fresh:
            cached = self._cache.get(key)
            if cached is not None:
                return cached
        # A lookup already in flight started after any cached copy, so it is fresh enough for both.
        task = self._inflight.get(key)
        if task is None:
            task = asyncio.ensure_future(self._lookup(key, token))
            self._inflight[key] = task
            task.add_done_callback(lambda _t: self._inflight.pop(key, None))
        # shield: one caller being cancelled (client went away) must not cancel the others' lookup.
        return await asyncio.shield(task)

    async def _lookup(self, key: str, token: str) -> Identity:
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


def _retry_after(raw: str | None) -> float:
    """Discord's Retry-After in seconds, bounded; 5 when missing or malformed."""
    try:
        value = float(raw) if raw is not None and len(raw) < 10 else 5.0
    except ValueError:
        return 5.0
    return min(3600.0, max(0.0, value))


discord_client = DiscordClient()
