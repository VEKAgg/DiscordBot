"""Honeypot exemptions (audit H-08)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import nextcord

from src.cogs.admin.honeypot import _is_exempt


class _Role:
    def __init__(self, pos):
        self.pos = pos

    def __ge__(self, other):
        return self.pos >= other.pos


def _member(uid=5, admin=False, manage=False, pos=1):
    perms = SimpleNamespace(administrator=admin, manage_messages=manage)
    return SimpleNamespace(id=uid, guild_permissions=perms, top_role=_Role(pos))


GUILD = MagicMock(spec=nextcord.Guild)
GUILD.owner_id = 1
GUILD.me = SimpleNamespace(top_role=_Role(10))


def test_regular_member_is_not_exempt():
    assert _is_exempt(GUILD, _member()) is False


def test_staff_and_owner_are_exempt():
    assert _is_exempt(GUILD, _member(manage=True)) is True
    assert _is_exempt(GUILD, _member(admin=True)) is True
    assert _is_exempt(GUILD, _member(uid=1)) is True


def test_members_above_bot_are_exempt():
    assert _is_exempt(GUILD, _member(pos=10)) is True
