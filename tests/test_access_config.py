"""Configurable access: Developer Portal operators and per-server access roles (no env ID lists)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from src.services.guild_settings_service import GuildSettings
from src.services.operators import OperatorRegistry, parse_operators
from src.services.operators import operators as registry
from src.utils.security.rbac import Role, rbac

GUILD_ID = 900


def _member(uid=1, roles=(), administrator=False, moderate=False):
    perms = SimpleNamespace(
        administrator=administrator, moderate_members=moderate, kick_members=False, ban_members=False
    )
    return SimpleNamespace(id=uid, roles=[SimpleNamespace(id=r) for r in roles], guild_permissions=perms)


def _guild(owner_id=999):
    return SimpleNamespace(id=GUILD_ID, owner_id=owner_id)


def _settings(admin=(), staff=(), perk=()):
    return GuildSettings(
        guild_id=GUILD_ID, admin_role_ids=list(admin), staff_role_ids=list(staff), perk_role_ids=list(perk)
    )


# ------------------------------------------------------------------ operators


def test_team_operators_are_owner_admins_and_developers_only():
    payload = {
        'owner': {'id': '5'},
        'team': {
            'owner_user_id': '10',
            'members': [
                {'membership_state': 2, 'role': 'admin', 'user': {'id': '11'}},
                {'membership_state': 2, 'role': 'developer', 'user': {'id': '12'}},
                {'membership_state': 2, 'role': 'read_only', 'user': {'id': '13'}},
                {'membership_state': 1, 'role': 'admin', 'user': {'id': '14'}},  # invited, not accepted
            ],
        },
    }
    assert parse_operators(payload) == frozenset({10, 11, 12})


def test_non_team_application_owner_is_the_operator():
    assert parse_operators({'owner': {'id': '42'}, 'team': None}) == frozenset({42})
    assert parse_operators({}) == frozenset()


async def test_refresh_failure_keeps_last_known_operators():
    registry = OperatorRegistry()
    bot = SimpleNamespace(http=SimpleNamespace(application_info=AsyncMock(return_value={'owner': {'id': '7'}})))
    registry.bind(bot)  # type: ignore[arg-type]
    assert await registry.refresh() is True
    assert registry.is_operator(7)

    bot.http.application_info = AsyncMock(side_effect=RuntimeError('discord down'))
    assert await registry.refresh() is False
    assert registry.is_operator(7)


async def test_unbound_registry_disables_operators():
    registry = OperatorRegistry()
    assert await registry.refresh() is False
    assert not registry.is_operator(1)


# ------------------------------------------------------------------ role resolution


def _resolve(member, guild=None, settings=None):
    return rbac._resolve(member, guild if guild is not None else _guild(), settings)


def test_operator_outranks_everything_even_in_dms(monkeypatch):
    monkeypatch.setattr(registry, '_operators', frozenset({1}))
    assert rbac._resolve(_member(uid=1), None, None) is Role.OPERATOR
    assert rbac._resolve(_member(uid=2), None, None) is Role.USER


def test_owner_administrator_and_admin_roles_are_admin():
    assert _resolve(_member(uid=999)) is Role.ADMIN
    assert _resolve(_member(administrator=True)) is Role.ADMIN
    assert _resolve(_member(roles=[50]), settings=_settings(admin=[50])) is Role.ADMIN


def test_staff_permission_fallback_only_while_no_staff_roles_are_chosen():
    moderator = _member(moderate=True)
    assert _resolve(moderator, settings=_settings()) is Role.STAFF
    assert _resolve(moderator, settings=None) is Role.STAFF  # unknown settings: permissions decide
    assert _resolve(moderator, settings=_settings(staff=[60])) is Role.USER
    assert _resolve(_member(roles=[60]), settings=_settings(staff=[60])) is Role.STAFF


def test_perk_roles_and_no_role_name_mapping():
    assert _resolve(_member(roles=[70]), settings=_settings(perk=[70])) is Role.PERK
    named_admin = _member(roles=[80])
    named_admin.roles[0].name = 'admin'  # a role *called* admin grants nothing
    assert _resolve(named_admin, settings=_settings()) is Role.USER


def test_unknown_settings_never_grant_configured_roles():
    assert _resolve(_member(roles=[50]), settings=None) is Role.USER


def test_perk_bypasses_cooldowns_and_user_does_not():
    assert rbac.has_cooldown_bypass(Role.PERK)
    assert not rbac.has_cooldown_bypass(Role.USER)
