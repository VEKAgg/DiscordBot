"""Authentication and authorisation dependencies.

- User principal: ``Authorization: Bearer <Discord OAuth token>`` verified with Discord.
- Service principal: ``X-Service-Token`` (constant-time compared). Its scope is limited to the routes
  that explicitly accept it; ``X-Acting-User`` is only *asserted* audit metadata, never identity.
- Guild access = the user's Discord permissions in that guild (owner/Administrator imply all) AND the
  bot is in the guild (fresh ``bot_guild_snapshot`` row).
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass

from fastapi import Depends, Path, Request

from src.api.config import settings
from src.api.discord_client import MANAGE_GUILD, Identity, UserGuild, discord_client
from src.api.errors import ApiError
from src.api.ratelimit import RateLimiter
from src.database.database import db

preauth_limiter = RateLimiter(settings.preauth_limit_per_minute)
client_limiter = RateLimiter(settings.rate_limit_per_minute)


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client else 'unknown'
    if peer in settings.trusted_proxies:
        forwarded = request.headers.get('x-forwarded-for', '')
        if forwarded:
            return forwarded.split(',')[0].strip()
    return peer


@dataclass(frozen=True)
class Principal:
    kind: str  # 'user' | 'service'
    identity: Identity | None = None
    asserted_actor: int | None = None  # service calls only; audit metadata, not identity

    @property
    def user_id(self) -> int | None:
        return self.identity.user.id if self.identity else None

    @property
    def audit_actor(self) -> str:
        if self.identity:
            return str(self.identity.user.id)
        return f'service:{self.asserted_actor}' if self.asserted_actor else 'service'


def _bearer(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith('bearer '):
        token = authorization[7:].strip()
        return token or None
    return None


async def _principal(request: Request, allow_service: bool, fresh: bool = False) -> Principal:
    service_token = request.headers.get('x-service-token')
    if service_token is not None:
        configured = settings.service_token
        if not configured or not hmac.compare_digest(service_token.encode('utf-8', 'replace'), configured.encode()):
            preauth_limiter.check(f'ip:{client_ip(request)}')
            raise ApiError(401, 'invalid_service_token', 'Invalid service token.')
        if not allow_service:
            raise ApiError(403, 'service_not_allowed', 'This endpoint needs a signed-in user.')
        client_limiter.check('service')
        actor = request.headers.get('x-acting-user', '')
        asserted = int(actor) if actor.isdigit() and len(actor) <= 20 and 0 < int(actor) < 2**63 else None
        return Principal(kind='service', asserted_actor=asserted)

    token = _bearer(request.headers.get('authorization'))
    if token is None:
        preauth_limiter.check(f'ip:{client_ip(request)}')
        raise ApiError(401, 'missing_token', 'Send a Discord OAuth token as "Authorization: Bearer …".')
    # Unauthenticated tries are charged to the IP before we call Discord.
    preauth_limiter.check(f'ip:{client_ip(request)}')
    identity = await discord_client.identify(token, fresh=fresh)
    client_limiter.check(f'user:{identity.user.id}')
    return Principal(kind='user', identity=identity)


async def current_user(request: Request) -> Principal:
    """A verified Discord user (no service tokens)."""
    return await _principal(request, allow_service=False)


async def user_or_service(request: Request) -> Principal:
    return await _principal(request, allow_service=True)


async def bot_in_guild(guild_id: int) -> dict:
    row = await db.fetch_one(
        """SELECT guild_id, name, icon_url, owner_id, member_count, online_count, channels, roles,
                  bot_permissions, bot_top_role_position, updated_at
           FROM bot_guild_snapshot
           WHERE guild_id = $1 AND updated_at > NOW() - make_interval(secs => $2)""",
        guild_id,
        settings.snapshot_max_age_seconds,
    )
    if row is None:
        raise ApiError(403, 'bot_not_in_guild', 'The bot is not in this server (or has been offline too long).')
    return dict(row)


@dataclass(frozen=True)
class GuildAccess:
    principal: Principal
    guild_id: int
    member: UserGuild | None  # None for service principals
    snapshot: dict

    def require(self, *bits: int) -> None:
        """Require at least one of ``bits`` (owner/Administrator always pass). Service → forbidden."""
        if self.member is None or not any(self.member.has(bit) for bit in bits):
            raise ApiError(403, 'missing_permission', 'You lack the Discord permission this action needs.')


def guild_access(*required_any: int, fresh: bool = False):
    """Dashboard gate: Manage Server is mandatory, plus any action-specific permission.

    Service credentials never substitute for a signed-in server manager. Owner/Administrator
    implication is handled by UserGuild.has. Writes retain fresh Discord permission checks.
    """

    async def dependency(request: Request, guild_id: int = Path(gt=0, lt=2**63)) -> GuildAccess:
        principal = await _principal(request, allow_service=False, fresh=fresh)
        snapshot = await bot_in_guild(guild_id)
        assert principal.identity is not None
        member = principal.identity.guilds.get(guild_id)
        if member is None:
            raise ApiError(403, 'not_a_member', 'You are not a member of this server.')
        access = GuildAccess(principal, guild_id, member, snapshot)
        access.require(MANAGE_GUILD)
        if required_any:
            access.require(*required_any)
        return access

    return Depends(dependency)
