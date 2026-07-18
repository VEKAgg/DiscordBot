"""Shared aiohttp session for the bot's lifetime.

A single session keeps its connection pool warm across calls instead of building
a new one per request. Created lazily inside the running loop (never at import)
and closed once on shutdown via aclose(). Per-request timeouts can still be
passed to individual .get()/.post() calls to override the default.
"""

import aiohttp

_DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=10)
_session: aiohttp.ClientSession | None = None


def get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(timeout=_DEFAULT_TIMEOUT)
    return _session


async def aclose() -> None:
    """Close the shared session. Call once on bot shutdown."""
    global _session
    if _session is not None and not _session.closed:
        await _session.close()
    _session = None
