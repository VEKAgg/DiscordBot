"""
Rate Limiting System for VEKA Bot
Prevents command spam and abuse
"""

import asyncio
import logging
import time
from functools import wraps
from typing import Any

from src.utils.safety import safe_send

logger = logging.getLogger('VEKA.security.rate_limiter')

CLEANUP_INTERVAL = 300.0  # seconds between inline purges of idle buckets


class RateLimiter:
    """
    Token bucket rate limiter for Discord commands

    Usage:
        @commands.check(rate_limiter.check)
        async def my_command(self, ctx):
            pass
    """

    def __init__(self):
        # user_id:command -> (tokens, last_update)
        self.buckets: dict[str, tuple[float, float]] = {}
        self.lock = asyncio.Lock()
        self._last_cleanup = time.time()

        # Default limits per command type
        self.default_limits = {
            'default': (5, 60),  # 5 commands per 60 seconds
            'quiz': (3, 60),  # 3 quiz attempts per minute
            'marketplace': (2, 300),  # 2 marketplace posts per 5 minutes
            'mentorship': (5, 300),  # 5 mentorship actions per 5 minutes
            'admin': (10, 60),  # 10 admin commands per minute
        }

    def _get_key(self, user_id: str, command: str) -> str:
        """Generate unique key for user-command combination"""
        return f'{user_id}:{command}'

    def _get_limit(self, command: str) -> tuple[int, int]:
        """Get rate limit for command (requests, window_seconds)"""
        # Check for specific command limit
        for cmd_type, limit in self.default_limits.items():
            if cmd_type in command.lower():
                return limit
        return self.default_limits['default']

    def _has_bypass(self, member) -> bool:
        """Check if a member has cooldown bypass via their role"""
        if member is None:
            return False
        try:
            from src.utils.security.rbac import rbac

            ctx_like = type('Ctx', (), {'author': member, 'guild': getattr(member, 'guild', None)})()
            role = rbac.get_user_role(ctx_like)
            return rbac.has_cooldown_bypass(role)
        except Exception:
            return False

    def _refill(self, key: str, bucket: str, now: float) -> float:
        max_requests, window = self._get_limit(bucket)
        if key not in self.buckets:
            return float(max_requests)
        tokens, last_update = self.buckets[key]
        return min(max_requests, tokens + ((now - last_update) / window) * max_requests)

    async def acquire(self, user_id: str, bucket: str, member=None) -> tuple[bool, float]:
        """Atomically check and consume one token. Returns (allowed, retry_after_seconds)."""
        if self._has_bypass(member):
            return True, 0.0

        key = self._get_key(user_id, bucket)
        async with self.lock:
            now = time.time()
            if now - self._last_cleanup > CLEANUP_INTERVAL:
                self._purge_stale(now)
            tokens = self._refill(key, bucket, now)
            if tokens >= 1:
                self.buckets[key] = (tokens - 1, now)
                return True, 0.0
            self.buckets[key] = (tokens, now)
            max_requests, window = self._get_limit(bucket)
            return False, (1 - tokens) * (window / max_requests)

    async def check(self, ctx, member=None) -> bool:
        """``commands.check``-style predicate for prefix commands (bucket = command name)."""
        user = getattr(ctx, 'author', None) or getattr(ctx, 'user', None)
        if user is None:
            return True
        command = ctx.command.name if getattr(ctx, 'command', None) else 'unknown'
        allowed, retry_after = await self.acquire(str(user.id), command, member=member or user)
        if not allowed:
            logger.warning('Rate limit hit for user %s on %s', user.id, command)
            await safe_send(
                ctx, f'⏱️ Please wait {retry_after:.0f} seconds before using this command again.', ephemeral=True
            )
        return allowed

    async def is_rate_limited(self, user_id: str, command: str, member=None) -> tuple[bool, float]:
        """Check without consuming a token. Returns (is_limited, retry_after_seconds)."""
        if self._has_bypass(member):
            return False, 0
        key = self._get_key(user_id, command)
        async with self.lock:
            tokens = self._refill(key, command, time.time())
            if tokens >= 1:
                return False, 0
            max_requests, window = self._get_limit(command)
            return True, (1 - tokens) * (window / max_requests)

    def get_remaining(self, user_id: str, command: str) -> int:
        """Get remaining requests for user"""
        key = self._get_key(user_id, command)

        # Best-effort value without the lock (safe for int reads on CPython)
        if key not in self.buckets:
            max_requests, _ = self._get_limit(command)
            return max_requests
        tokens, _ = self.buckets[key]
        return max(0, int(tokens))

    async def reset(self, user_id: str | None = None, command: str | None = None):
        """Reset rate limits for user or globally"""
        async with self.lock:
            if user_id and command:
                key = self._get_key(user_id, command)
                self.buckets.pop(key, None)
            elif user_id:
                # Reset all commands for user
                keys_to_remove = [k for k in self.buckets.keys() if k.startswith(f'{user_id}:')]
                for key in keys_to_remove:
                    self.buckets.pop(key, None)
            else:
                # Reset all
                self.buckets.clear()

    def _purge_stale(self, now: float, max_age: float = 600.0) -> None:
        """Drop buckets idle for longer than max_age. Caller holds the lock."""
        stale_keys = [key for key, (_, last_update) in self.buckets.items() if now - last_update > max_age]
        for key in stale_keys:
            del self.buckets[key]
        self._last_cleanup = now
        if stale_keys:
            logger.debug('Cleaned up %d stale rate-limit buckets', len(stale_keys))

    async def cleanup_stale_buckets(self, max_age: float = 600.0):
        """Remove bucket entries older than max_age seconds (default 10 min)."""
        async with self.lock:
            self._purge_stale(time.time(), max_age)


# Global rate limiter instance
rate_limiter = RateLimiter()

# Convenience decorator


def rate_limit(command_type: str = 'default'):
    """
    Decorator to apply rate limiting to commands

    Usage:
        @rate_limit('quiz')
        @commands.command()
        async def quiz(self, ctx):
            pass
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any):
            # (self, ctx_or_interaction, ...) — works for prefix Context and slash Interaction.
            source = args[1] if len(args) > 1 else kwargs.get('ctx') or kwargs.get('interaction')
            user = getattr(source, 'author', None) or getattr(source, 'user', None)

            if user is not None:
                allowed, retry_after = await rate_limiter.acquire(str(user.id), command_type, member=user)
                if not allowed:
                    logger.info('Rate limit hit for user %s on bucket %s', user.id, command_type)
                    await safe_send(source, f'⏱️ Rate limited! Try again in {retry_after:.0f} seconds.', ephemeral=True)
                    return None

            return await func(*args, **kwargs)

        return wrapper

    return decorator
