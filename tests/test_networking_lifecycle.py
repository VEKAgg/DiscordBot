"""Persistent request views: reconciliation, completion, reload and bounded profile rendering."""

from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from src.cogs.networking import networking as module
from src.services.networking_service import NetworkingService
from src.utils.embed_limits import text_units
from src.utils.outbound import SendOutcome, SendStatus


def _request(request_id):
    return {'id': request_id, 'requester_discord_id': '123', 'recipient_discord_id': '456'}


def _make(cog, request_id=1):
    return cog._make_response_view(request_id, '123', '456', 'Requester', cog.svc)


async def test_ready_pages_pending_views_and_prunes_completed(mock_bot, monkeypatch):
    cog = module.Networking(mock_bot)
    fetcher = AsyncMock(side_effect=[[_request(1)], [_request(2)], [], [_request(2)], []])
    monkeypatch.setattr(cog.svc, 'get_pending_requests', fetcher)
    await cog.cog_ready()
    first, second = cog._response_views[1], cog._response_views[2]
    assert fetcher.call_args_list[1].kwargs == {'after_id': 1}
    await cog.cog_ready()
    assert first.is_finished() and cog._response_views == {2: second}
    cog.cog_unload()
    assert second.is_finished() and not cog._response_views


async def test_failed_reconciliation_keeps_existing_views_for_retry(mock_bot, monkeypatch):
    cog = module.Networking(mock_bot)
    view = _make(cog)
    monkeypatch.setattr(cog.svc, 'get_pending_requests', AsyncMock(side_effect=RuntimeError('DB down')))
    with pytest.raises(RuntimeError):
        await cog.cog_ready()
    assert cog._response_views[1] is view and not view.is_finished()
    cog.cog_unload()


async def test_unload_during_ready_cannot_register_late_views(mock_bot, monkeypatch):
    cog = module.Networking(mock_bot)

    async def fetch(**_kwargs):
        cog.cog_unload()
        return [_request(1)]

    monkeypatch.setattr(cog.svc, 'get_pending_requests', AsyncMock(side_effect=fetch))
    await cog.cog_ready()
    assert not cog._response_views
    with pytest.raises(RuntimeError, match='unloaded'):
        _make(cog)


async def test_ready_does_not_prune_view_created_after_snapshot_started(mock_bot, monkeypatch):
    cog = module.Networking(mock_bot)
    old = _make(cog)

    async def fetch(**_kwargs):
        _make(cog, 99)
        return []

    monkeypatch.setattr(cog.svc, 'get_pending_requests', AsyncMock(side_effect=fetch))
    await cog.cog_ready()
    assert old.is_finished() and set(cog._response_views) == {99}
    cog.cog_unload()


@pytest.mark.parametrize('button,changed', [(0, True), (1, True), (0, False), (1, False)])
async def test_response_completion_releases_registry_even_on_stale_request(
    button, changed, mock_bot, mock_interaction, monkeypatch
):
    cog = module.Networking(mock_bot)
    monkeypatch.setattr(cog.svc, 'respond_request', AsyncMock(return_value=changed))
    monkeypatch.setattr(module, '_fetch_user', AsyncMock(return_value=None))
    mock_interaction.user.id = 456
    mock_interaction.response.defer = AsyncMock()
    view = _make(cog)
    await view.children[button].callback(mock_interaction)
    assert view.is_finished() and not cog._response_views


async def test_failed_response_does_not_drop_retryable_view(mock_bot, mock_interaction, monkeypatch):
    cog = module.Networking(mock_bot)
    monkeypatch.setattr(cog.svc, 'respond_request', AsyncMock(side_effect=RuntimeError('DB down')))
    mock_interaction.response.defer = AsyncMock()
    view = _make(cog)
    await view.children[0].callback(mock_interaction)
    assert cog._response_views[1] is view and not view.is_finished()
    cog.cog_unload()


async def test_replaced_view_cannot_remove_new_registry_entry(mock_bot):
    cog = module.Networking(mock_bot)
    old = _make(cog)
    new = _make(cog)
    old.stop()
    assert old.is_finished() and cog._response_views[1] is new
    cog.cog_unload()


async def test_pending_page_is_bounded_and_ordered(monkeypatch, mock_db):
    monkeypatch.setattr('src.services.networking_service.db', mock_db)
    await NetworkingService().get_pending_requests(after_id=42, limit=50)
    sql, cursor, limit = mock_db.fetch.call_args.args
    assert (cursor, limit) == (42, 50)
    assert 'r.id > $1' in sql and 'ORDER BY r.id LIMIT $2' in sql
    with pytest.raises(ValueError):
        await NetworkingService().get_pending_requests(limit=501)


async def test_legacy_non_atomic_write_methods_are_removed():
    assert not hasattr(NetworkingService, 'create_connection')
    assert not hasattr(NetworkingService, 'update_request_status')


async def test_profile_rendering_bounds_valid_and_legacy_skill_arrays(monkeypatch, mock_bot, mock_user, mock_db):
    monkeypatch.setattr(module, 'db', mock_db)
    cog = module.Networking(mock_bot)
    monkeypatch.setattr(cog.svc, 'get_connection_count', AsyncMock(return_value=0))
    monkeypatch.setattr(cog.svc, 'get_seller_stats', AsyncMock(return_value=None))
    profile: dict = {key: '🙂' * 10000 for key in ['title', 'bio', 'links', 'looking_for', 'timezone']}
    profile['skills'] = ['🙂' * 10000] * 30
    embed = await cog._format_profile(mock_user, profile, mock_user)
    total = text_units(embed.title or '') + text_units(embed.description or '') + text_units(embed.footer.text or '')
    for field in embed.fields:
        assert text_units(field.value or '') <= 1024
        total += text_units(field.name or '') + text_units(field.value or '')
    assert total <= 6000
    assert 'more)' in next(field.value or '' for field in embed.fields if field.name == 'Skills')
    assert all(field.name != 'Last Active' for field in embed.fields)
    mock_db.fetch_one.assert_not_awaited()  # no last_active query or visibility side channel


@pytest.mark.parametrize('status', [SendStatus.SENT, SendStatus.FORBIDDEN])
async def test_new_prefix_response_views_are_tracked_and_failed_delivery_releases_them(
    status, mock_bot, mock_context, mock_member, monkeypatch
):
    cog = module.Networking(mock_bot)
    monkeypatch.setattr(cog.svc, 'create_request', AsyncMock(return_value=7))
    sender = AsyncMock(return_value=SendOutcome(status))
    mock_member.bot = False
    monkeypatch.setattr(module.outbound, 'dm', sender)
    callback = cast(Any, cog.connect_fallback.callback).__wrapped__
    await callback(cog, mock_context, mock_member, message='Hello')
    view = sender.call_args.kwargs['view']
    assert view.request_id == 7
    if status == SendStatus.SENT:
        assert cog._response_views[7] is view and not view.is_finished()
    else:
        assert not cog._response_views and view.is_finished()
    cog.cog_unload()
    assert view.is_finished()
