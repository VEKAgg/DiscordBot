"""Punitive roles are re-validated at assignment time (configuration can go stale)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import nextcord

from src.cogs.admin.honeypot import Honeypot
from src.utils.roles import punitive_role_problem as _problem


def punitive_role_problem(role, guild) -> str:
    return _problem(cast(Any, role), cast(Any, guild)) or ''


class _Role:
    def __init__(self, pos, perms=0, managed=False, default=False):
        self.pos = pos
        self.permissions = nextcord.Permissions(perms)
        self.managed = managed
        self._default = default
        self.id = 1

    def is_default(self):
        return self._default

    def __ge__(self, other):
        return self.pos >= other.pos


def _guild(top=10):
    return SimpleNamespace(me=SimpleNamespace(top_role=_Role(top)), id=5)


def test_safe_role_passes():
    assert punitive_role_problem(_Role(2), _guild()) == ''


def test_role_that_gained_admin_or_moderation_is_refused():
    assert 'permissions' in punitive_role_problem(
        _Role(2, perms=nextcord.Permissions(administrator=True).value), _guild()
    )
    assert 'permissions' in punitive_role_problem(
        _Role(2, perms=nextcord.Permissions(ban_members=True).value), _guild()
    )


def test_role_above_bot_managed_or_missing_is_refused():
    assert punitive_role_problem(_Role(12), _guild())
    assert punitive_role_problem(_Role(2, managed=True), _guild())
    assert punitive_role_problem(None, _guild())


async def test_honeypot_refuses_role_that_became_admin():
    guild = MagicMock()
    guild.id = 5
    guild.me = SimpleNamespace(top_role=_Role(10))
    guild.get_role = MagicMock(return_value=_Role(2, perms=nextcord.Permissions(administrator=True).value))
    member = MagicMock()
    member.add_roles = AsyncMock()
    result = await Honeypot(MagicMock())._execute_role(guild, member, 1)
    assert result == 'failed'
    member.add_roles.assert_not_awaited()
