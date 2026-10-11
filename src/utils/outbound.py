"""Shared outbound-messaging guard: budgets, de-duplication, status edits and a circuit breaker.

Discord's anti-spam looks at *patterns*: bursts of identical messages, unsolicited DMs, and many
failed requests (403/50007). Every bot-initiated message that is not a direct reply to the invoking
user should go through ``outbound`` (also attached as ``bot.outbound``):

    from src.utils.outbound import outbound

    await outbound.send(channel, embed=embed, kind='honeypot_alert', guild_id=guild.id)
    await outbound.dm(user, embed=embed, kind='massunban_apology')
    await outbound.upsert_status(f'massunban:{job_id}', channel, embed=progress_embed)

Rules:
- Token buckets per channel, per guild, globally, and a much tighter one for DMs. ``essential`` sends
  wait (bounded) for a token; non-essential sends are dropped and counted when the budget is spent.
- Identical messages to the same destination inside ``dedupe_window`` seconds are sent once.
- ``upsert_status`` edits one stored message per key instead of posting a new one each time.
- HTTP 429 that reaches us (nextcord retries most internally) is honoured once for essential sends.
- Repeated 429/403/50007 failures open a circuit breaker that pauses non-essential sends (and DMs
  separately) for a cool-off period; admins are alerted once per opening.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections import Counter, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import nextcord

from src.utils.ttlcache import TTLDict

logger = logging.getLogger('VEKA.outbound')

CANNOT_DM_CODE = 50007  # "Cannot send messages to this user"


class SendStatus(StrEnum):
    SENT = 'sent'
    EDITED = 'edited'
    DEDUPED = 'deduped'
    DROPPED_BUDGET = 'dropped_budget'
    BREAKER_OPEN = 'breaker_open'
    NO_SHARED_GUILD = 'no_shared_guild'
    FORBIDDEN = 'forbidden'
    FAILED = 'failed'


@dataclass
class SendOutcome:
    status: SendStatus
    message: nextcord.Message | None = None
    error: str | None = None
    thread: nextcord.Thread | None = None

    @property
    def ok(self) -> bool:
        return self.status in (SendStatus.SENT, SendStatus.EDITED)


class TokenBucket:
    """Classic token bucket: ``capacity`` tokens, refilled at ``capacity / period`` per second."""

    def __init__(self, capacity: int, period: float, clock: Callable[[], float]) -> None:
        self.capacity = float(capacity)
        self.rate = capacity / period
        self._clock = clock
        self.tokens = float(capacity)
        self.updated = clock()

    def _refill(self) -> None:
        now = self._clock()
        self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
        self.updated = now

    # Tolerance for float rounding: after sleeping exactly ``wait_time()`` the bucket can sit at
    # 0.9999999 tokens, which would otherwise spin on ever-smaller waits.
    _EPS = 1e-6

    def try_take(self) -> bool:
        self._refill()
        if self.tokens >= 1 - self._EPS:
            self.tokens = max(0.0, self.tokens - 1)
            return True
        return False

    def wait_time(self) -> float:
        self._refill()
        if self.tokens >= 1 - self._EPS:
            return 0.0
        return (1 - self.tokens) / self.rate + self._EPS


@dataclass
class Breaker:
    """Opens after ``threshold`` failures within ``window`` seconds; stays open for ``cooldown``."""

    name: str
    threshold: int
    window: float
    cooldown: float
    failures: deque = field(default_factory=deque)
    open_until: float = 0.0
    openings: int = 0

    def is_open(self, now: float) -> bool:
        return now < self.open_until

    def record_failure(self, now: float) -> bool:
        """Record a failure; return True if this failure opened the breaker."""
        self.failures.append(now)
        while self.failures and now - self.failures[0] > self.window:
            self.failures.popleft()
        if not self.is_open(now) and len(self.failures) >= self.threshold:
            self.open_until = now + self.cooldown
            self.openings += 1
            self.failures.clear()
            return True
        return False

    def record_success(self) -> None:
        self.failures.clear()


@dataclass
class OutboundConfig:
    global_per_10s: int = 30
    guild_per_10s: int = 10
    channel_per_5s: int = 4
    dm_per_minute: int = 5
    dedupe_window: float = 300.0
    essential_max_wait: float = 30.0
    breaker_threshold: int = 8
    breaker_window: float = 60.0
    breaker_cooldown: float = 600.0
    dm_breaker_threshold: int = 5
    dm_breaker_window: float = 600.0
    dm_breaker_cooldown: float = 3600.0


def _fingerprint(dest_id: int, content: str | None, embed: nextcord.Embed | None) -> str:
    payload: dict[str, Any] = {'d': dest_id, 'c': content}
    if embed is not None:
        data = embed.to_dict()
        data.pop('timestamp', None)
        data.pop('footer', None)  # footers carry rotating attribution text
        payload['e'] = data
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def _is_dm_target(dest: Any) -> bool:
    return isinstance(dest, nextcord.User | nextcord.Member | nextcord.DMChannel)


class OutboundMessenger:
    def __init__(
        self,
        config: OutboundConfig | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    ) -> None:
        self.config = config or OutboundConfig()
        self._clock = clock
        self._sleep = sleep
        cfg = self.config
        self._global = TokenBucket(cfg.global_per_10s, 10, clock)
        self._dm = TokenBucket(cfg.dm_per_minute, 60, clock)
        self._guilds: TTLDict[int, TokenBucket] = TTLDict(ttl=600, maxsize=5000, clock=clock)
        self._channels: TTLDict[int, TokenBucket] = TTLDict(ttl=600, maxsize=20000, clock=clock)
        self._recent: TTLDict[str, bool] = TTLDict(ttl=cfg.dedupe_window, maxsize=20000, clock=clock)
        self._status_messages: TTLDict[str, nextcord.Message] = TTLDict(ttl=7 * 86400, maxsize=2000, clock=clock)
        self._status_locks: dict[str, asyncio.Lock] = {}
        self._status_posts = 0
        self.breaker = Breaker('send', cfg.breaker_threshold, cfg.breaker_window, cfg.breaker_cooldown)
        self.dm_breaker = Breaker('dm', cfg.dm_breaker_threshold, cfg.dm_breaker_window, cfg.dm_breaker_cooldown)
        self.counters: Counter[str] = Counter()
        self._alert: Callable[[str, str], Awaitable[Any]] | None = None
        self._bot: nextcord.Client | None = None

    # ------------------------------------------------------------------ wiring

    def bind(self, bot: nextcord.Client, alert: Callable[[str, str], Awaitable[Any]] | None = None) -> None:
        """Attach to the bot (``bot.outbound``) and set the admin alert used when a breaker opens."""
        self._bot = bot
        self._alert = alert
        bot.outbound = self  # type: ignore[attr-defined]

    def snapshot(self) -> dict[str, Any]:
        now = self._clock()
        return {
            'counters': dict(self.counters),
            'breaker_open': self.breaker.is_open(now),
            'breaker_open_for_s': max(0, int(self.breaker.open_until - now)),
            'dm_breaker_open': self.dm_breaker.is_open(now),
            'dm_breaker_open_for_s': max(0, int(self.dm_breaker.open_until - now)),
            'breaker_openings': self.breaker.openings + self.dm_breaker.openings,
        }

    # ------------------------------------------------------------------ budget

    def _buckets_for(self, dest_id: int, guild_id: int | None, is_dm: bool) -> list[TokenBucket]:
        buckets = [self._global]
        if is_dm:
            buckets.append(self._dm)
        else:
            ch = self._channels.get(dest_id)
            if ch is None:
                ch = TokenBucket(self.config.channel_per_5s, 5, self._clock)
                self._channels.set(dest_id, ch)
            buckets.append(ch)
        if guild_id:
            gb = self._guilds.get(guild_id)
            if gb is None:
                gb = TokenBucket(self.config.guild_per_10s, 10, self._clock)
                self._guilds.set(guild_id, gb)
            buckets.append(gb)
        return buckets

    async def _acquire(self, buckets: list[TokenBucket], essential: bool) -> bool:
        deadline = self._clock() + (self.config.essential_max_wait if essential else 0)
        while True:
            wait = max(b.wait_time() for b in buckets)
            if wait <= 0:
                for b in buckets:
                    b.try_take()
                return True
            if self._clock() + wait > deadline:
                return False
            await self._sleep(wait)

    # ------------------------------------------------------------------ failures

    async def _on_failure(self, breaker: Breaker, kind: str, reason: str) -> None:
        if breaker.record_failure(self._clock()):
            self.counters['breaker_opened'] += 1
            logger.warning(
                'Outbound %s breaker opened after repeated failures (last: %s, kind=%s); '
                'non-essential sends paused for %ss',
                breaker.name,
                reason,
                kind,
                int(breaker.cooldown),
            )
            if self._alert is not None:
                try:
                    await self._alert(
                        f'Outbound {breaker.name} sends paused',
                        f'Repeated Discord errors ({reason}, last kind `{kind}`). Non-essential '
                        f'{"DMs" if breaker.name == "dm" else "messages"} are paused for '
                        f'{int(breaker.cooldown // 60)} minutes to protect the bot from anti-spam action.',
                    )
                except Exception:
                    logger.warning('Outbound breaker alert failed', exc_info=True)

    # ------------------------------------------------------------------ core

    async def _deliver(
        self,
        dest: Any,
        *,
        kind: str,
        guild_id: int | None,
        essential: bool,
        dedupe_key: str | None,
        dedupe_window: float | None,
        is_dm: bool,
        payload: dict[str, Any],
        transport: Callable[..., Awaitable[Any]] | None = None,
    ) -> SendOutcome:
        now = self._clock()
        breaker = self.dm_breaker if is_dm else self.breaker
        if breaker.is_open(now) and not essential:
            self.counters[f'{kind}:breaker_open'] += 1
            return SendOutcome(SendStatus.BREAKER_OPEN)

        dest_id = int(getattr(dest, 'id', 0) or 0)
        key: str | None = None
        # Attachments have no stable fingerprint here; only dedupe them when the caller names a key.
        if dedupe_key is not None or payload.get('file') is None:
            fp = dedupe_key or _fingerprint(dest_id, payload.get('content'), payload.get('embed'))
            key = f'{dest_id}:{fp}'
            if key in self._recent:
                self.counters[f'{kind}:deduped'] += 1
                return SendOutcome(SendStatus.DEDUPED)
            # Reserve before awaiting so a concurrent identical send is deduped too.
            self._recent.set(key, True, ttl=dedupe_window or self.config.dedupe_window)

        def _release() -> None:
            if key is not None:
                self._recent.pop(key)

        if not await self._acquire(self._buckets_for(dest_id, guild_id, is_dm), essential):
            _release()
            self.counters[f'{kind}:dropped_budget'] += 1
            logger.info('Outbound budget exhausted; dropped %s message to %s', kind, dest_id)
            return SendOutcome(SendStatus.DROPPED_BUDGET)

        kwargs = {k: v for k, v in payload.items() if v is not None}
        call = transport or dest.send
        for attempt in (1, 2):
            try:
                result = await call(**kwargs)
            except nextcord.Forbidden as exc:
                _release()
                self.counters[f'{kind}:forbidden'] += 1
                await self._on_failure(breaker, kind, f'403/{exc.code}')
                return SendOutcome(SendStatus.FORBIDDEN, error=f'{exc.code}')
            except nextcord.HTTPException as exc:
                if exc.status == 429:
                    await self._on_failure(breaker, kind, '429')
                    retry_after = _retry_after(exc)
                    # Retry once, only for essential sends and only if Discord's wait fits our bound.
                    if essential and attempt == 1 and retry_after <= self.config.essential_max_wait:
                        await self._sleep(retry_after)
                        continue
                _release()
                self.counters[f'{kind}:failed'] += 1
                return SendOutcome(SendStatus.FAILED, error=f'{exc.status}/{exc.code}')
            except Exception as exc:  # network errors etc.
                _release()
                self.counters[f'{kind}:failed'] += 1
                logger.warning('Outbound %s send failed: %s', kind, type(exc).__name__)
                return SendOutcome(SendStatus.FAILED, error=type(exc).__name__)
            else:
                breaker.record_success()
                self.counters[f'{kind}:sent'] += 1
                if isinstance(result, nextcord.Thread):
                    return SendOutcome(SendStatus.SENT, thread=result, message=getattr(result, 'last_message', None))
                return SendOutcome(SendStatus.SENT, message=result)
        _release()
        return SendOutcome(SendStatus.FAILED, error='429')

    async def send(
        self,
        channel: nextcord.abc.Messageable,
        *,
        kind: str,
        guild_id: int | None = None,
        content: str | None = None,
        embed: nextcord.Embed | None = None,
        file: nextcord.File | None = None,
        view: nextcord.ui.View | None = None,
        allowed_mentions: nextcord.AllowedMentions | None = None,
        essential: bool = False,
        dedupe_key: str | None = None,
        dedupe_window: float | None = None,
    ) -> SendOutcome:
        """Send a bot-initiated message to a channel under the shared budgets."""
        if guild_id is None:
            guild = getattr(channel, 'guild', None)
            guild_id = getattr(guild, 'id', None)
        return await self._deliver(
            channel,
            kind=kind,
            guild_id=guild_id,
            essential=essential,
            dedupe_key=dedupe_key,
            dedupe_window=dedupe_window,
            is_dm=_is_dm_target(channel),
            payload={
                'content': content,
                'embed': embed,
                'file': file,
                'view': view,
                'allowed_mentions': allowed_mentions,
            },
        )

    async def dm(
        self,
        user: nextcord.User | nextcord.Member,
        *,
        kind: str,
        content: str | None = None,
        embed: nextcord.Embed | None = None,
        file: nextcord.File | None = None,
        view: nextcord.ui.View | None = None,
        essential: bool = False,
        require_shared_guild: bool = True,
        dedupe_key: str | None = None,
        dedupe_window: float | None = None,
    ) -> SendOutcome:
        """DM a user. By default only users who share a server with the bot are contacted:
        a DM to anyone else almost always fails (50007) and counts against the bot."""
        if require_shared_guild and not self._shares_guild(user):
            self.counters[f'{kind}:no_shared_guild'] += 1
            return SendOutcome(SendStatus.NO_SHARED_GUILD)
        return await self._deliver(
            user,
            kind=kind,
            guild_id=None,
            essential=essential,
            dedupe_key=dedupe_key,
            dedupe_window=dedupe_window,
            is_dm=True,
            payload={'content': content, 'embed': embed, 'file': file, 'view': view},
        )

    async def create_thread(
        self,
        forum: nextcord.ForumChannel,
        *,
        kind: str,
        name: str,
        content: str | None = None,
        embed: nextcord.Embed | None = None,
        file: nextcord.File | None = None,
        applied_tags: list[nextcord.ForumTag] | None = None,
        essential: bool = False,
        dedupe_key: str | None = None,
        dedupe_window: float | None = None,
    ) -> SendOutcome:
        """Create a forum post (thread + starter message) under the same budgets/breaker as ``send``.
        ``outcome.thread`` is the new thread."""
        return await self._deliver(
            forum,
            kind=kind,
            guild_id=getattr(getattr(forum, 'guild', None), 'id', None),
            essential=essential,
            dedupe_key=dedupe_key or f'thread:{name}',
            dedupe_window=dedupe_window,
            is_dm=False,
            payload={
                'name': name[:100],
                'content': content,
                'embed': embed,
                'file': file,
                'applied_tags': applied_tags,
            },
            transport=forum.create_thread,
        )

    async def upsert_status(
        self,
        key: str,
        channel: nextcord.abc.Messageable,
        *,
        kind: str = 'status',
        content: str | None = None,
        embed: nextcord.Embed | None = None,
        message: nextcord.Message | nextcord.PartialMessage | None = None,
    ) -> SendOutcome:
        """Edit the status message stored under ``key`` (or ``message``); post one only if none exists.

        Edits don't add messages to a channel, so progress updates should always use this. They still
        count failures toward the breaker and are skipped while it is open.
        """
        self._prune_status_locks()
        lock = self._status_locks.setdefault(key, asyncio.Lock())
        async with lock:
            if self.breaker.is_open(self._clock()):
                self.counters[f'{kind}:breaker_open'] += 1
                return SendOutcome(SendStatus.BREAKER_OPEN)
            existing = message or self._status_messages.get(key)
            if existing is not None:
                try:
                    edited = await existing.edit(content=content, embed=embed)
                except nextcord.NotFound:
                    self._status_messages.pop(key)
                except nextcord.Forbidden as exc:
                    self.counters[f'{kind}:forbidden'] += 1
                    await self._on_failure(self.breaker, kind, f'403/{exc.code}')
                    return SendOutcome(SendStatus.FORBIDDEN, error=f'{exc.code}')
                except nextcord.HTTPException as exc:
                    self.counters[f'{kind}:failed'] += 1
                    if exc.status == 429:
                        await self._on_failure(self.breaker, kind, '429')
                    return SendOutcome(SendStatus.FAILED, error=f'{exc.status}/{exc.code}')
                else:
                    current = edited if isinstance(edited, nextcord.Message) else existing
                    self._status_messages.set(key, current)  # type: ignore[arg-type]
                    self.counters[f'{kind}:edited'] += 1
                    return SendOutcome(SendStatus.EDITED, message=current)  # type: ignore[arg-type]
            # The per-key lock prevents concurrent first posts; each post gets its own dedupe key so a
            # status message deleted by staff can be re-posted.
            self._status_posts += 1
            outcome = await self.send(
                channel,
                kind=kind,
                content=content,
                embed=embed,
                essential=True,
                dedupe_key=f'status:{key}:{self._status_posts}',
            )
            if outcome.message is not None:
                self._status_messages.set(key, outcome.message)
            return outcome

    def _prune_status_locks(self, limit: int = 500) -> None:
        """Drop idle locks (no holder or waiter) whose status message is gone, so keys don't accumulate."""
        if len(self._status_locks) <= limit:
            return
        for key, lock in list(self._status_locks.items()):
            if not lock.locked() and not getattr(lock, '_waiters', None) and key not in self._status_messages:
                del self._status_locks[key]

    def remember_status(self, key: str, message: nextcord.Message) -> None:
        self._status_messages.set(key, message)

    def forget_status(self, key: str) -> None:
        self._status_messages.pop(key)
        self._status_locks.pop(key, None)

    def _shares_guild(self, user: nextcord.User | nextcord.Member) -> bool:
        """True if the user is currently a member of any guild the bot is in (live cache, not a stale
        Member object — e.g. a just-unbanned user's old Member)."""
        bot = self._bot
        if bot is not None:
            return any(g.get_member(user.id) is not None for g in bot.guilds)
        try:
            return bool(user.mutual_guilds)
        except Exception:
            return False


@dataclass
class DigestBuffer:
    """Collects events for a digest message: an exact count plus a bounded sample of lines."""

    limit: int
    count: int = 0
    sample: list[str] = field(default_factory=list)

    def add(self, line: str) -> None:
        self.count += 1
        if len(self.sample) < self.limit:
            self.sample.append(line)


def _retry_after(exc: nextcord.HTTPException) -> float:
    response = getattr(exc, 'response', None)
    headers = getattr(response, 'headers', None) or {}
    try:
        return max(1.0, float(headers.get('Retry-After', 5)))
    except (TypeError, ValueError):
        return 5.0


outbound = OutboundMessenger()
