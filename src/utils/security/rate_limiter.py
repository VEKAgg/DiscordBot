"""
Rate Limiting System for VEKA Bot
Prevents command spam and abuse
"""

import asyncio
import logging
import time
from functools import wraps

logger = logging.getLogger('VEKA.security.rate_limiter')


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

    async def check(self, ctx) -> bool:
        """
        Check if user can execute command
        Returns True if allowed, False if rate limited
        """
        user_id = str(ctx.author.id)
        command = ctx.command.name if ctx.command else 'unknown'
        key = self._get_key(user_id, command)

        async with self.lock:
            max_requests, window = self._get_limit(command)
            now = time.time()

            if key in self.buckets:
                tokens, last_update = self.buckets[key]
                # Add tokens based on time passed
                time_passed = now - last_update
                tokens = min(max_requests, tokens + (time_passed / window) * max_requests)
            else:
                tokens = max_requests

            if tokens >= 1:
                # Consume token
                self.buckets[key] = (tokens - 1, now)
                return True
            else:
                # Rate limited
                retry_after = (1 - tokens) * (window / max_requests)
                logger.warning(f'Rate limit hit for user {user_id} on command {command}')
                await ctx.send(f'⏱️ Please wait {retry_after:.0f} seconds before using this command again.')
                return False

    async def is_rate_limited(self, user_id: str, command: str) -> tuple[bool, float]:
        """
        Check if user is rate limited without consuming token
        Returns (is_limited, retry_after_seconds)
        """
        key = self._get_key(user_id, command)

        async with self.lock:
            max_requests, window = self._get_limit(command)

            if key not in self.buckets:
                return False, 0

            tokens, last_update = self.buckets[key]
            now = time.time()
            time_passed = now - last_update
            tokens = min(max_requests, tokens + (time_passed / window) * max_requests)

            if tokens >= 1:
                return False, 0
            else:
                retry_after = (1 - tokens) * (window / max_requests)
                return True, retry_after

    def get_remaining(self, user_id: str, command: str) -> int:
        """Get remaining requests for user"""
        key = self._get_key(user_id, command)

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
        async def wrapper(*args, **kwargs):
            # Get context (first arg is usually self, second is ctx)
            ctx = args[1] if len(args) > 1 else kwargs.get('ctx')

            if ctx:
                user_id = str(ctx.author.id)
                is_limited, retry_after = await rate_limiter.is_rate_limited(user_id, command_type)

                if is_limited:
                    await ctx.send(f'⏱️ Rate limited! Try again in {retry_after:.0f} seconds.')
                    return

            return await func(*args, **kwargs)

        return wrapper

    return decorator
