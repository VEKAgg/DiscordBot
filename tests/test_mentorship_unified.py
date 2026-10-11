"""D13 unit contracts; transaction/concurrency behavior is covered by the central PG gate."""

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from src.cogs import mentorship as module
from src.services.mentorship_service import MentorshipService
from src.utils.safety import ValidationError


@pytest.mark.parametrize('guild', [None, 0, -1, True, 2**63])
async def test_bad_guild_cannot_create_registration(guild, mock_db):
    service = MentorshipService(database=mock_db)
    with pytest.raises(ValidationError):
        await service.register_mentor(guild, '123')
    mock_db.fetch_one.assert_not_awaited()


@pytest.mark.parametrize('value', ['1', 'M0', 'M-1', 'M2147483648', 'M١', 'legacy:1', 'M1e3'])
def test_ui_namespace_rejects_legacy_match_numbers(value):
    with pytest.raises(ValidationError):
        module.Mentorship._id(value)
    assert module.Mentorship._id('M123') == 123


async def test_directory_and_history_queries_are_scoped_bounded(mock_db):
    service = MentorshipService(database=mock_db)
    await service.find_mentors(77, None, 2)
    sql, guild, category, offset = mock_db.fetch.call_args.args
    assert (guild, category, offset) == (77, None, 5)
    assert 'r.available' in sql and 'LIMIT 6' in sql
    await service.get_user_mentorships('123', None)
    sql, guild, actor, _ = mock_db.fetch.call_args.args
    assert guild is None and actor == '123'
    assert 'IS NOT DISTINCT FROM $1::bigint' in sql and 'a.discord_id=$2 OR b.discord_id=$2' in sql


async def test_invalid_request_validates_before_user_creation(mock_db):
    service = MentorshipService(database=mock_db)
    with pytest.raises(ValidationError):
        await service.create_mentorship_request(77, '123', '123', 'programming')
    with pytest.raises(ValidationError):
        await service.create_mentorship_request(77, '123', '456', 'bad-category')
    with pytest.raises(ValidationError):
        await service.create_mentorship_request(77, '123', '456', 'programming', '🙂' * 501)
    mock_db.fetch_one.assert_not_awaited()


async def test_user_lock_order_matches_activity_service(mock_db):
    await MentorshipService._lock_users(mock_db, [9, 2])
    sql, ids = mock_db.fetch.call_args.args
    assert ids == [9, 2]
    assert 'ORDER BY discord_id FOR UPDATE' in sql


async def test_preferences_generation_guards_and_bounded_recipient_query(mock_db):
    service = MentorshipService(database=mock_db)
    await service.due_reminders()
    sql = mock_db.fetch.call_args.args[0]
    assert 'p.enabled' in sql and 'EXISTS' in sql
    assert 'LIMIT 12' in sql and 'LIMIT 10' in sql and "INTERVAL '7 days'" in sql
    await service.finish_reminder(77, 9, 3, False)
    sql, *args = mock_db.execute.call_args.args
    assert args == [77, 9, 3, False]
    assert 'enabled AND revision=$3' in sql and "INTERVAL '1 day'" in sql


async def test_prefix_and_slash_complete_delegate_same_canonical_operation(
    monkeypatch, mock_bot, mock_context, mock_interaction, mock_member
):
    cog = module.Mentorship(mock_bot)
    complete = AsyncMock()
    monkeypatch.setattr(cog, '_complete', complete)
    await cast(Any, cog.mentor_complete_slash.callback).__wrapped__(cog, mock_interaction, mock_member)
    complete.assert_awaited_with(mock_interaction, mock_member)
    await cast(Any, cog.mentor_complete_prefix.callback).__wrapped__(cog, mock_context, mock_member)
    complete.assert_awaited_with(mock_context, mock_member)


async def test_registration_and_apply_have_prefix_slash_parity(monkeypatch, mock_bot, mock_context, mock_interaction):
    cog = module.Mentorship(mock_bot)
    register = AsyncMock()
    monkeypatch.setattr(cog, '_register', register)
    await cast(Any, cog.mentor_apply.callback).__wrapped__(cog, mock_interaction, 'Python', 'Bio', 'programming')
    register.assert_awaited_with(mock_interaction, 'mentor', 'Python', 'Bio', ['programming'])
    await cast(Any, cog.mentor_apply_prefix.callback).__wrapped__(
        cog, mock_context, 'Python', bio='--categories programming | Bio'
    )
    register.assert_awaited_with(mock_context, 'mentor', 'Python', 'Bio', ['programming'])


async def test_revoked_reminder_generation_never_sends(monkeypatch, mock_bot, mock_user):
    cog = module.Mentorship(mock_bot)
    rows = [dict(guild_id=77, user_id=9, revision=3, discord_id='123', id=1, category='programming')]
    monkeypatch.setattr(cog.mentorship_service, 'due_reminders', AsyncMock(return_value=rows))
    monkeypatch.setattr(cog.mentorship_service, 'claim_reminder', AsyncMock(return_value=True))
    monkeypatch.setattr(cog.mentorship_service, 'current_reminder_matches', AsyncMock(return_value=[]))
    monkeypatch.setattr(mock_bot, 'get_guild', lambda _gid: SimpleNamespace(get_member=lambda _uid: mock_user))
    send = AsyncMock()
    monkeypatch.setattr(module.outbound, 'dm', send)
    await cog.check_in_loop.coro(cog)
    send.assert_not_awaited()


async def test_personal_prefix_records_never_fall_back_to_public(monkeypatch, mock_bot, mock_context):
    cog = module.Mentorship(mock_bot)
    dm = AsyncMock(return_value=SimpleNamespace(ok=False))
    public = AsyncMock()
    monkeypatch.setattr(module.outbound, 'dm', dm)
    monkeypatch.setattr(module, 'safe_send', public)
    await cog._reply(mock_context, 'Records', 'private-request-message', personal=True)
    dm.assert_awaited_once()
    public.assert_awaited_once()
    assert 'private-request-message' not in public.call_args.kwargs['embed'].description
