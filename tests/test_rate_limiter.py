"""Rate limiter (audit M-05 / H-11): works for slash Interactions and consumes the checked bucket."""

from __future__ import annotations

from unittest.mock import patch

from src.utils.security.rate_limiter import RateLimiter, rate_limit, rate_limiter


async def test_acquire_consumes_same_bucket_it_checks():
    limiter = RateLimiter()
    limiter.default_limits['marketplace'] = (2, 300)
    assert (await limiter.acquire('1', 'marketplace'))[0] is True
    assert (await limiter.acquire('1', 'marketplace'))[0] is True
    allowed, retry_after = await limiter.acquire('1', 'marketplace')
    assert allowed is False
    assert retry_after > 0
    # Another user is unaffected
    assert (await limiter.acquire('2', 'marketplace'))[0] is True


async def test_decorator_works_with_interaction(mock_interaction):
    calls = []

    @rate_limit('marketplace')
    async def cmd(_self, interaction):
        calls.append(interaction)

    await rate_limiter.reset()
    with patch.object(rate_limiter, '_has_bypass', return_value=False):
        for _ in range(3):
            await cmd(object(), mock_interaction)

    assert len(calls) == 2  # marketplace bucket = 2 per 5 minutes
    mock_interaction.response.send_message.assert_awaited()  # third call told the user
    await rate_limiter.reset()


async def test_stale_buckets_are_purged():
    limiter = RateLimiter()
    limiter.buckets['old:x'] = (0.0, 0.0)
    limiter._last_cleanup = 0.0
    await limiter.acquire('3', 'default')
    assert 'old:x' not in limiter.buckets
