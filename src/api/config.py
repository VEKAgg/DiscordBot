"""API settings from the environment (all optional for the bot; read only by the API process)."""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass, field


def _csv(name: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, '').split(',') if item.strip()]


def _networks(name: str) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """IPs or CIDRs; a bad entry fails startup instead of silently trusting nothing."""
    return [ipaddress.ip_network(item, strict=False) for item in _csv(name)]


@dataclass(frozen=True)
class ApiSettings:
    service_token: str | None = field(default_factory=lambda: os.getenv('API_SERVICE_TOKEN') or None)
    cors_origins: list[str] = field(default_factory=lambda: _csv('API_CORS_ORIGINS'))
    rate_limit_per_minute: int = field(default_factory=lambda: max(10, int(os.getenv('API_RATE_LIMIT', '120'))))
    preauth_limit_per_minute: int = field(default_factory=lambda: max(10, int(os.getenv('API_PREAUTH_LIMIT', '60'))))
    discord_api_base: str = field(
        default_factory=lambda: os.getenv('DISCORD_API_BASE', 'https://discord.com/api/v10').rstrip('/')
    )
    trusted_proxy_networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = field(
        default_factory=lambda: _networks('API_TRUSTED_PROXIES')
    )
    docs_enabled: bool = field(
        default_factory=lambda: (
            os.getenv('API_DOCS', '') == '1' or os.getenv('ENVIRONMENT', 'development') != 'production'
        )
    )
    max_body_bytes: int = 64 * 1024
    snapshot_max_age_seconds: int = 600  # a guild snapshot older than this means "bot not in guild / offline"


settings = ApiSettings()
