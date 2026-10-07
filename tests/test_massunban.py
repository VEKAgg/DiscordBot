"""Mass-unban selection rules (audit H-02)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import nextcord

from src.cogs.admin.massunban import MassUnban, match_bans

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


# --- 403 handling: a refused unban stops the job instead of failing every item ---


def _forbidden(code: int) -> nextcord.Forbidden:
    response = MagicMock(status=403, reason='Forbidden')
    return nextcord.Forbidden(response, {'code': code, 'message': 'refused'})


def _item(uid: int) -> dict:
    return {'id': uid, 'target_user_id': str(uid), 'target_username': f'user{uid}'}


JOB = {'id': 1, 'guild_id': 10, 'requested_by': 99, 'reason': None}


async def test_unban_403_mfa_required_is_job_stopping(mock_bot):
    cog = MassUnban(mock_bot)
    guild = MagicMock()
    guild.fetch_ban = AsyncMock()
    guild.unban = AsyncMock(side_effect=_forbidden(60003))

    result = await cog._process_unban_item(guild, _item(5), JOB)

    assert result['forbidden'] is True
    assert result['status'] == 'pending'  # not recorded as a per-user failure
    assert '2FA' in result['failure_reason']


async def test_fetch_ban_403_is_job_stopping(mock_bot):
    cog = MassUnban(mock_bot)
    guild = MagicMock()
    guild.fetch_ban = AsyncMock(side_effect=_forbidden(50013))
    guild.unban = AsyncMock()

    result = await cog._process_unban_item(guild, _item(5), JOB)

    assert result['forbidden'] is True
    assert 'Missing permission' in result['failure_reason']
    guild.unban.assert_not_awaited()


async def test_job_stops_after_first_403(mock_bot, _reset_runtime_state):
    _reset_runtime_state.db_available = True
    cog = MassUnban(mock_bot)
    guild = MagicMock()
    guild.fetch_ban = AsyncMock()
    guild.unban = AsyncMock(side_effect=_forbidden(60003))
    mock_bot.get_guild = MagicMock(return_value=guild)
    mock_bot.get_user = MagicMock(return_value=None)
    cog._active_jobs[1] = False

    db = MagicMock()
    db.fetch_one = AsyncMock(return_value=JOB)
    db.fetch = AsyncMock(return_value=[_item(1), _item(2), _item(3)])
    db.execute = AsyncMock()

    # Patch the globals the class was defined with: test_cog_loading may have reloaded the module.
    with (
        patch.dict(MassUnban._run_job.__globals__, {'db': db}),
        patch.object(cog, '_log_job_event', AsyncMock()),
        patch.object(cog, '_complete_job', AsyncMock()) as complete,
    ):
        await cog._run_job(1, resumed=False)

    assert guild.unban.await_count == 1
    complete.assert_not_awaited()
    sql = db.execute.await_args.args[0]
    assert "status = 'failed'" in sql and 'forbidden' in sql
    assert 1 not in cog._active_jobs
