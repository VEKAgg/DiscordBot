"""Platform-scope operators — the bot's Discord Developer Portal team.

Operators are the application team's owner plus accepted members with the Admin or Developer
role, so owners add/remove operators in the Developer Portal with no deploy and no environment
variables. ``nextcord``'s ``TeamMember`` does not parse ``role`` and ``Bot.is_owner`` caches
forever, so the raw ``/oauth2/applications/@me`` payload is parsed here instead.
"""

from __future__ import annotations

import nextcord

from src.utils.logger import get_logger

logger = get_logger('VEKA.operators')

# Discord team roles that carry operational authority. ``read_only`` never does.
OPERATOR_TEAM_ROLES = frozenset({'admin', 'developer'})
# ``membership_state`` 2 = ACCEPTED (1 = INVITED, 3 = PENDING).
ACCEPTED_MEMBERSHIP_STATE = 2
REFRESH_INTERVAL_MINUTES = 10


def parse_operators(payload: dict) -> frozenset[int]:
    """Operator user IDs from the raw application-info payload.

    Team-owned applications: the team owner plus members with ``membership_state == 2`` and
    ``role`` in ``{"admin", "developer"}``. Not team-owned: the application owner alone.
    """
    team = payload.get('team')
    if not team:
        owner = payload.get('owner') or {}
        owner_id = owner.get('id')
        return frozenset({int(owner_id)}) if owner_id else frozenset()

    ids: set[int] = set()
    team_owner = team.get('owner_user_id')
    if team_owner:
        ids.add(int(team_owner))
    for member in team.get('members') or []:
        if member.get('membership_state') != ACCEPTED_MEMBERSHIP_STATE:
            continue
        if member.get('role') not in OPERATOR_TEAM_ROLES:
            continue
        user_id = (member.get('user') or {}).get('id')
        if user_id:
            ids.add(int(user_id))
    return frozenset(ids)


class OperatorRegistry:
    """In-memory operator set: sync reads, async refresh, last-good retention on failure."""

    def __init__(self) -> None:
        self._operators: frozenset[int] = frozenset()
        self._bot: nextcord.Client | None = None
        self._disabled_warned = False

    @property
    def ids(self) -> frozenset[int]:
        return self._operators

    def bind(self, bot: nextcord.Client) -> None:
        """Attach the bot whose HTTP client can read the application info."""
        self._bot = bot

    def is_operator(self, user_id: int) -> bool:
        """True when ``user_id`` is a known platform operator (sync, no I/O)."""
        return user_id in self._operators

    def _warn_disabled(self, reason: str) -> None:
        """One warning while the operator set is empty (same semantics as the old empty allowlist)."""
        if self._disabled_warned:
            return
        self._disabled_warned = True
        logger.warning(
            'Bot-global operator commands are disabled (%s). Operators are the Discord Developer '
            'Portal team owner and accepted Admin/Developer members; manage them in the portal '
            '(no deploy needed).',
            reason,
        )

    async def refresh(self) -> bool:
        """Re-read the application info from Discord. Returns True on success.

        On failure the last good set is kept; an empty set (first failure or an application
        with no team/owner) leaves operator commands disabled with a single warning.
        """
        if self._bot is None:
            self._warn_disabled('the operator registry is not bound to a bot')
            return False
        try:
            payload = await self._bot.http.application_info()
        except Exception as exc:
            if self._operators:
                logger.warning(
                    'Operator refresh failed (%s); keeping the last known set (%d operators).',
                    type(exc).__name__,
                    len(self._operators),
                )
            else:
                self._warn_disabled(f'refresh failed: {type(exc).__name__}')
            return False

        operators = parse_operators(dict(payload or {}))
        self._operators = operators
        if operators:
            self._disabled_warned = False
            logger.info('Operator registry refreshed (%d operators).', len(operators))
        else:
            self._warn_disabled('the application has no team or owner')
        return True


# Global singleton used by RBAC, safety guards and the /operator commands.
operators = OperatorRegistry()
