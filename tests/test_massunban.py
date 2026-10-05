"""Mass-unban selection rules (audit H-02)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from src.cogs.admin.massunban import match_bans

START = datetime(2024, 1, 1, tzinfo=UTC)
END = datetime(2024, 12, 31, tzinfo=UTC)


def _ban(uid: int):
    return SimpleNamespace(user=SimpleNamespace(id=uid), reason=None)


BANS = [_ban(1), _ban(2), _ban(3), _ban(4)]
AUDIT = {
    '1': {'created_at': datetime(2024, 6, 1, tzinfo=UTC), 'moderator_id': '77'},
    '2': {'created_at': datetime(2023, 6, 1, tzinfo=UTC), 'moderator_id': '77'},  # outside range
    '3': {'created_at': datetime(2024, 7, 1), 'moderator_id': '88'},  # naive timestamp
    # 4 has no audit record
}


def _ids(matched):
    return sorted(ban.user.id for ban, _ in matched)


def test_unaudited_bans_excluded_by_default():
    matched, unaudited = match_bans(BANS, AUDIT, START, END, None, include_unaudited=False)
    assert _ids(matched) == [1, 3]
    assert unaudited == 1


def test_unaudited_bans_included_only_when_opted_in():
    matched, _ = match_bans(BANS, AUDIT, START, END, None, include_unaudited=True)
    assert _ids(matched) == [1, 3, 4]


def test_moderator_filter_never_includes_unaudited():
    matched, _ = match_bans(BANS, AUDIT, START, END, 77, include_unaudited=True)
    assert _ids(matched) == [1]
