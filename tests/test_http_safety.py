"""SSRF guard for user-supplied URLs (audit H-04)."""

from __future__ import annotations

import socket
from unittest.mock import AsyncMock

import pytest

from src.utils.http import PublicOnlyResolver, UnsafeURLError, validate_public_url


@pytest.mark.parametrize(
    'url',
    [
        'file:///etc/passwd',
        'gopher://example.com/',
        'ftp://example.com/feed',
        'http://127.0.0.1/feed',
        'http://localhost:8080/',
        'http://foo.localhost/',
        'http://169.254.169.254/latest/meta-data/',
        'http://10.0.0.5/rss',
        'http://192.168.1.1/',
        'http://[::1]/',
        'http://[::ffff:127.0.0.1]/',
        'http://0.0.0.0/',
        'http:///nohost',
    ],
)
def test_rejects_unsafe_urls(url):
    with pytest.raises(UnsafeURLError):
        validate_public_url(url)


@pytest.mark.parametrize('url', ['https://example.com/feed.xml', 'http://8.8.8.8/rss', '  https://blog.example.org/  '])
def test_accepts_public_urls(url):
    assert validate_public_url(url) == url.strip()


def _result(ip):
    return {'hostname': 'h', 'host': ip, 'port': 80, 'family': socket.AF_INET, 'proto': 0, 'flags': 0}


async def test_resolver_drops_private_addresses():
    resolver = PublicOnlyResolver()
    resolver._inner = AsyncMock()
    resolver._inner.resolve = AsyncMock(return_value=[_result('10.1.2.3'), _result('93.184.216.34')])
    results = await resolver.resolve('mixed.example', 80)
    assert [r['host'] for r in results] == ['93.184.216.34']


async def test_resolver_rejects_hosts_with_only_private_addresses():
    resolver = PublicOnlyResolver()
    resolver._inner = AsyncMock()
    resolver._inner.resolve = AsyncMock(return_value=[_result('127.0.0.1'), _result('169.254.169.254')])
    with pytest.raises(OSError):
        await resolver.resolve('rebind.example', 80)
