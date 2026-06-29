"""
Dynamic Embed Footer Engine
Builds footer text based on user role, server join date, and DB-persisted state.
"""

import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import nextcord

from src.database.database import db
from src.utils.security.rbac import ROLE_HIERARCHY, Role, rbac

logger = logging.getLogger('VEKA.footer')

# ============================================================
# Constants
# ============================================================

REPO_URL = 'https://github.com/VEKAgg/DiscordBot'
DEFAULT_CONTRIBUTOR = {'name': 'shifu', 'discord_id': '941009204045557842'}

CONTRIBUTION_COOLDOWN_HOURS = 24
NEW_USER_DAYS = 30

# ============================================================
# Footer templates — no emojis anywhere
# ============================================================

_FULL_FOOTER = 'Command by @{name} ({discord_id}) | [Contribute]({repo})'
_COMPACT_FOOTER = 'Command by @{name} ({discord_id})'
_DONATOR_FOOTER = 'Command by @{name} ({discord_id}) | Thank you for your patronage!'
_ACTIVE_PRO_FOOTER = 'Command by @{name} ({discord_id}) | Thank you for being an Active Pro!'
_NEW_USER_FOOTER = 'Command by @{name} ({discord_id}) | Tip: {tip}'

# New user tips (rotate through these)
_NEW_USER_TIPS = [
    'Use /help to explore all commands',
    'Check out /portfolio to showcase your work',
    'Join the mentorship program with /mentor list',
    'Sell your services on /marketplace post',
    'Use /resource to share and find useful links',
    'Connect with others using /connect request',
    'Set up your profile with /profile setup',
    'Read the latest updates with /resource latest',
]

# Advertisements shown after contribution cooldown
_ADS = [
    'Subscribe to [Shifu](https://twitch.tv/whoisshafaat) and help cover development and server costs',
]

# ============================================================
# DB helpers
# ============================================================


async def _get_footer_state(user_id: int) -> dict | None:
    """Fetch user footer state from DB. Returns None if no row exists."""
    try:
        row = await db.fetch_one('SELECT * FROM user_footer_state WHERE user_id = $1', user_id)
        return dict(row) if row else None
    except Exception as exc:
        logger.warning('Failed to fetch footer state for %s: %s', user_id, exc)
        return None


async def _upsert_footer_state(
    user_id: int,
    *,
    last_contribution_prompt: datetime | None = None,
    tip_index: int | None = None,
) -> None:
    """Insert or update user footer state row."""
    try:
        existing = await _get_footer_state(user_id)
        if existing:
            updates = []
            params: list = []
            idx = 1
            if last_contribution_prompt is not None:
                updates.append(f'last_contribution_prompt = ${idx}')
                params.append(last_contribution_prompt)
                idx += 1
            if tip_index is not None:
                updates.append(f'tip_index = ${idx}')
                params.append(tip_index)
                idx += 1
            if updates:
                params.append(user_id)
                await db.execute(
                    f'UPDATE user_footer_state SET {", ".join(updates)} WHERE user_id = ${idx}',
                    *params,
                )
        else:
            await db.execute(
                'INSERT INTO user_footer_state (user_id, last_contribution_prompt, tip_index) VALUES ($1, $2, $3)',
                user_id,
                last_contribution_prompt or datetime.now(UTC),
                tip_index if tip_index is not None else 0,
            )
    except Exception as exc:
        logger.warning('Failed to upsert footer state for %s: %s', user_id, exc)


# ============================================================
# Role detection helper
# ============================================================


def _get_user_role(user: nextcord.Member | nextcord.User, guild: nextcord.Guild | None = None) -> Role:
    """Determine a user's RBAC role from a Member or User object."""
    ctx = SimpleNamespace(author=user, guild=guild)
    try:
        return rbac.get_user_role(ctx)
    except Exception:
        return Role.USER


def _is_new_user(member: nextcord.Member) -> bool:
    """Check if a member joined within the last NEW_USER_DAYS."""
    if member.joined_at is None:
        return False
    now = datetime.now(UTC)
    joined = member.joined_at
    if joined.tzinfo is None:
        joined = joined.replace(tzinfo=UTC)
    return (now - joined) < timedelta(days=NEW_USER_DAYS)


# ============================================================
# Main builder
# ============================================================


async def build_footer(
    user: nextcord.Member | nextcord.User | None,
    contributor: dict[str, str] | None = None,
) -> str:
    """
    Build dynamic footer text based on user role and conditions.

    - Staff+ roles: no footer (empty string)
    - Donator: patronage message
    - Active Pro: active pro message
    - New user (joined < 30 days): rotating tip
    - Regular user: contribution link (once/day) or ad
    """
    if user is None:
        contrib = contributor or DEFAULT_CONTRIBUTOR
        return _COMPACT_FOOTER.format(**contrib)

    contrib = contributor or DEFAULT_CONTRIBUTOR

    # Resolve guild from Member or User
    guild = getattr(user, 'guild', None)

    role = _get_user_role(user, guild)

    # Staff+ get no footer
    if ROLE_HIERARCHY.index(role) >= ROLE_HIERARCHY.index(Role.STAFF):
        return ''

    # Donator footer
    if role == Role.DONATOR:
        return _DONATOR_FOOTER.format(**contrib)

    # Active Pro footer
    if role == Role.ACTIVE_PRO:
        return _ACTIVE_PRO_FOOTER.format(**contrib)

    # New user check (by server join date)
    if isinstance(user, nextcord.Member) and _is_new_user(user):
        state = await _get_footer_state(user.id)
        tip_idx = (state.get('tip_index', 0) if state else 0) % len(_NEW_USER_TIPS)
        tip = _NEW_USER_TIPS[tip_idx]
        # Advance tip index for next time
        await _upsert_footer_state(user.id, tip_index=tip_idx + 1)
        return _NEW_USER_FOOTER.format(**contrib, tip=tip)

    # Regular user: contribution link once/day, then ads
    state = await _get_footer_state(user.id)
    now = datetime.now(UTC)
    show_contribution = True
    if state and state.get('last_contribution_prompt'):
        last_prompt = state['last_contribution_prompt']
        if last_prompt.tzinfo is None:
            last_prompt = last_prompt.replace(tzinfo=UTC)
        if (now - last_prompt) < timedelta(hours=CONTRIBUTION_COOLDOWN_HOURS):
            show_contribution = False

    if show_contribution:
        await _upsert_footer_state(user.id, last_contribution_prompt=now)
        return _FULL_FOOTER.format(**contrib, repo=REPO_URL)

    # Ad rotation
    ad = _ADS[user.id % len(_ADS)]
    return f'{_COMPACT_FOOTER.format(**contrib)} | {ad}'


def build_footer_sync(
    user: nextcord.Member | nextcord.User | None,
    contributor: dict[str, str] | None = None,
) -> str:
    """
    Synchronous fallback for contexts where async DB access is not possible.
    Uses role-based logic only (no DB persistence, no tip rotation).
    """
    if user is None:
        contrib = contributor or DEFAULT_CONTRIBUTOR
        return _COMPACT_FOOTER.format(**contrib)

    contrib = contributor or DEFAULT_CONTRIBUTOR
    guild = getattr(user, 'guild', None)
    role = _get_user_role(user, guild)

    if ROLE_HIERARCHY.index(role) >= ROLE_HIERARCHY.index(Role.STAFF):
        return ''
    if role == Role.DONATOR:
        return _DONATOR_FOOTER.format(**contrib)
    if role == Role.ACTIVE_PRO:
        return _ACTIVE_PRO_FOOTER.format(**contrib)
    if isinstance(user, nextcord.Member) and _is_new_user(user):
        tip = _NEW_USER_TIPS[0]
        return _NEW_USER_FOOTER.format(**contrib, tip=tip)

    return _FULL_FOOTER.format(**contrib, repo=REPO_URL)
