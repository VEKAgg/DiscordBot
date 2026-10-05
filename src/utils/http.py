"""Shared aiohttp sessions for the bot's lifetime.

A single session keeps its connection pool warm across calls instead of building
a new one per request. Created lazily inside the running loop (never at import)
and closed once on shutdown via aclose(). Per-request timeouts can still be
passed to individual .get()/.post() calls to override the default.

``fetch_public_url`` is for URLs supplied by users (RSS feeds): it refuses anything
that resolves to a private, loopback, link-local or otherwise non-public address
(SSRF guard, audit H-04), follows redirects manually so every hop is re-checked,
and caps the response size.
"""

import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import aiohttp
from aiohttp.abc import AbstractResolver, ResolveResult

_DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=10)
_session: aiohttp.ClientSession | None = None
_public_session: aiohttp.ClientSession | None = None

MAX_PUBLIC_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 3


class UnsafeURLError(ValueError):
    """Raised when a user-supplied URL is not an allowed public http(s) URL."""


def _is_public_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value.split('%', 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


class PublicOnlyResolver(AbstractResolver):
    """Resolver that drops non-public addresses, so DNS rebinding can't reach internal hosts."""

    def __init__(self) -> None:
        self._inner = aiohttp.ThreadedResolver()

    async def resolve(
        self, host: str, port: int = 0, family: socket.AddressFamily = socket.AF_INET
    ) -> list[ResolveResult]:
        results = await self._inner.resolve(host, port, family)
        public = [r for r in results if _is_public_ip(r['host'])]
        if not public:
            raise OSError(f'{host} does not resolve to a public address')
        return public

    async def close(self) -> None:
        await self._inner.close()


def validate_public_url(url: str) -> str:
    """Check scheme/host syntactically. Hostnames are checked at connect time by PublicOnlyResolver."""
    parts = urlsplit(url.strip())
    if parts.scheme not in ('http', 'https'):
        raise UnsafeURLError('Only http:// and https:// URLs are allowed.')
    host = parts.hostname
    if not host:
        raise UnsafeURLError('The URL has no host.')
    if host.lower() in ('localhost', 'localhost.localdomain') or host.lower().endswith('.localhost'):
        raise UnsafeURLError('That host is not allowed.')
    try:
        ipaddress.ip_address(host.split('%', 1)[0])
    except ValueError:
        return url.strip()  # hostname — resolver enforces public addresses
    if not _is_public_ip(host):
        raise UnsafeURLError('That address is not allowed.')
    return url.strip()


def get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(timeout=_DEFAULT_TIMEOUT)
    return _session


def _get_public_session() -> aiohttp.ClientSession:
    global _public_session
    if _public_session is None or _public_session.closed:
        connector = aiohttp.TCPConnector(resolver=PublicOnlyResolver(), limit=20)
        _public_session = aiohttp.ClientSession(timeout=_DEFAULT_TIMEOUT, connector=connector)
    return _public_session


async def fetch_public_url(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    max_bytes: int = MAX_PUBLIC_RESPONSE_BYTES,
    timeout: aiohttp.ClientTimeout | None = None,
) -> tuple[int, bytes]:
    """GET a user-supplied URL safely. Returns (status, body). Raises UnsafeURLError / aiohttp errors."""
    current = validate_public_url(url)
    session = _get_public_session()
    for _ in range(MAX_REDIRECTS + 1):
        async with session.get(
            current, headers=headers, timeout=timeout or _DEFAULT_TIMEOUT, allow_redirects=False
        ) as response:
            if response.status in (301, 302, 303, 307, 308):
                location = response.headers.get('Location')
                if not location:
                    return response.status, b''
                current = validate_public_url(urljoin(current, location))
                continue
            if response.content_length is not None and response.content_length > max_bytes:
                raise UnsafeURLError('The response is too large.')
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.content.iter_chunked(64 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise UnsafeURLError('The response is too large.')
                chunks.append(chunk)
            return response.status, b''.join(chunks)
    raise UnsafeURLError('Too many redirects.')


async def aclose() -> None:
    """Close the shared sessions. Call once on bot shutdown."""
    global _session, _public_session
    for sess in (_session, _public_session):
        if sess is not None and not sess.closed:
            await sess.close()
    _session = None
    _public_session = None
