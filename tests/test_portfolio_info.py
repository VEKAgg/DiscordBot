"""Portfolio command parity, bounded reads/legacy rendering and external info limits."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from src.cogs.external.info import ExternalInfo
from src.cogs.portfolio import portfolio_manager as module
from src.services import portfolio_service as service
from src.utils.embed_limits import bounded_items, clip_text, text_units
from src.utils.safety import ValidationError


@pytest.mark.parametrize(
    'overrides',
    [
        {'title': ' '},
        {'title': 'x' * 201},
        {'title': '🙂' * 101},
        {'description': ''},
        {'description': 'x' * 3001},
        {'url': 'not-a-url'},
        {'url': 'ftp://example.com/file'},
        {'url': 'https://example.com/' + 'x' * 500},
        {'tags': 'x' * 41},
        {'tags': ','.join(str(i) for i in range(11))},
    ],
)
def test_project_validation_rejects_unrenderable_or_invalid_input(overrides):
    params = {'title': 'Project', 'description': 'Description', 'url': '', 'tags': ''} | overrides
    with pytest.raises(ValidationError):
        service.validate_project(**params)


def test_project_validation_normalizes_and_deduplicates_tags():
    assert service.validate_project(' Title ', ' Description ', ' https://example.com ', ' Python,python, SQL, ') == (
        'Title',
        'Description',
        'https://example.com',
        ['Python', 'SQL'],
    )


@pytest.mark.parametrize('page', [0, -1, 1001, True])
async def test_bad_pages_do_not_query_database(page, monkeypatch, mock_db):
    monkeypatch.setattr(service, 'db', mock_db)
    with pytest.raises(ValidationError):
        await service.list_projects(123, page)
    mock_db.fetch_many.assert_not_awaited()


async def test_read_queries_bound_rows_and_have_stable_tie_order(monkeypatch, mock_db):
    monkeypatch.setattr(service, 'db', mock_db)
    await service.list_projects(123, 3)
    sql, *args = mock_db.fetch_many.call_args.args
    assert args == ['123', 6, 10]
    assert 'ORDER BY p.created_at DESC, p.id DESC LIMIT $2 OFFSET $3' in sql
    await service.search_projects('python', 2)
    sql, *args = mock_db.fetch_many.call_args.args
    assert args == ['python', 6, 5]
    assert "COALESCE(p.description, '')" in sql


async def test_invalid_add_performs_no_write_or_user_creation(monkeypatch, mock_db):
    monkeypatch.setattr(service, 'db', mock_db)
    resolve = AsyncMock()
    monkeypatch.setattr(service, 'get_or_create_user', resolve)
    with pytest.raises(ValidationError):
        await service.add_project(123, 'title', 'description', 'javascript:bad')
    resolve.assert_not_awaited()
    mock_db.execute.assert_not_awaited()


async def test_delete_is_owner_qualified_and_does_not_create_user(monkeypatch, mock_db):
    monkeypatch.setattr(service, 'db', mock_db)
    mock_db.execute.return_value = 'DELETE 0'
    assert not await service.delete_project(123, ' proj-1 ')
    sql, project_id, uid = mock_db.execute.call_args.args
    assert 'user_id =' in sql and 'discord_id = $2' in sql
    assert (project_id, uid) == ('proj-1', '123')


def _legacy_row():
    return {
        'id': 'project-1',
        'title': '🙂' * 20000,
        'description': '🙂' * 20000,
        'tags': ['🙂' * 20000] * 20,
        'url': 'x' * 20000,
        'owner_discord_id': '123',
        'created_at': datetime.now(UTC),
        'updated_at': datetime.now(UTC),
    }


def _assert_embed_limits(embed):
    assert text_units(embed.title or '') <= 256
    assert text_units(embed.description or '') <= 4096
    assert len(embed.fields) <= 25
    total = text_units(embed.title or '') + text_units(embed.description or '') + text_units(embed.footer.text or '')
    for field in embed.fields:
        assert text_units(field.name) <= 256 and text_units(field.value) <= 1024
        total += text_units(field.name) + text_units(field.value)
    assert total <= 6000


@pytest.mark.parametrize('searching', [False, True])
async def test_legacy_page_rendering_is_bounded_and_has_next_page(searching, monkeypatch, mock_bot, mock_interaction):
    send = AsyncMock()
    monkeypatch.setattr(module, 'safe_send', send)
    cog = module.PortfolioManager(mock_bot)
    mock_interaction.user.display_name = '🙂' * 20000
    mock_interaction.guild.get_member.return_value = mock_interaction.user
    await cog._show_page(
        mock_interaction,
        [_legacy_row() for _ in range(6)],
        1,
        member=None if searching else mock_interaction.user,
        query='🙂' * 20000 if searching else None,
    )
    embed = send.call_args.kwargs['embed']
    _assert_embed_limits(embed)
    assert len(embed.fields) == 5 and 'page 2' in embed.description


async def test_legacy_detail_and_missing_guild_render_safely(monkeypatch, mock_bot, mock_interaction):
    send = AsyncMock()
    monkeypatch.setattr(module, 'safe_send', send)
    monkeypatch.setattr(service, 'get_project', AsyncMock(return_value=_legacy_row()))
    cog = module.PortfolioManager(mock_bot)
    monkeypatch.setattr(cog, '_defer', AsyncMock())
    mock_interaction.guild = None
    await cog._view(mock_interaction, 'project-1')
    _assert_embed_limits(send.call_args.kwargs['embed'])


async def test_prefix_search_preserves_old_query_syntax_and_accepts_page_flag(mock_bot, mock_context, monkeypatch):
    cog = module.PortfolioManager(mock_bot)
    search = AsyncMock()
    monkeypatch.setattr(cog, '_search', search)
    callback = cast(Any, cog.portfolio_search_prefix.callback).__wrapped__
    await callback(cog, mock_context, query='Python web')
    search.assert_awaited_with(mock_context, 'Python web', 1)
    await callback(cog, mock_context, query='--page 2 Python web')
    search.assert_awaited_with(mock_context, 'Python web', 2)


def test_clip_counts_supplementary_unicode_conservatively():
    assert text_units(clip_text('🙂' * 1000, 50)) <= 50
    roles = [f'<@&{123456789012345678 + i}>' for i in range(250)]
    shown = bounded_items(roles, 900)
    assert text_units(shown) <= 900 and 'more)' in shown
    assert shown.count('<@&') == shown.count('>')


async def test_memberinfo_bounds_many_roles(monkeypatch, mock_bot, mock_interaction):
    from src.cogs.external import info

    send = AsyncMock()
    monkeypatch.setattr(info, 'safe_send', send)
    member = SimpleNamespace(
        id=123, mention='<@123>', display_name='🙂' * 20000, joined_at=None, created_at=None, bot=False, avatar=None
    )
    member.guild = cast(Any, SimpleNamespace(default_role=object()))
    member.roles = cast(Any, [SimpleNamespace(mention=f'<@&{123456789012345678 + i}>') for i in range(250)])
    member.top_role = member.roles[-1]
    cog = ExternalInfo(mock_bot)
    callback = cast(Any, cog.memberinfo.callback).__wrapped__
    await callback(cog, mock_interaction, member)
    embed = send.call_args.kwargs['embed']
    _assert_embed_limits(embed)
    assert 'more)' in embed.description


async def test_prefix_add_releases_prompt_slot_after_validation_failure(monkeypatch, mock_bot, mock_context):
    monkeypatch.setattr(module, 'safe_send', AsyncMock())
    mock_bot.wait_for = AsyncMock(
        side_effect=[SimpleNamespace(content=text) for text in ['x' * 201, 'description', 'skip', 'Python']]
    )
    cog = module.PortfolioManager(mock_bot)
    callback = cast(Any, cog.portfolio_add_prefix.callback).__wrapped__
    with pytest.raises(ValidationError):
        await callback(cog, mock_context)
    assert not cog._pending_adds


async def test_slash_and_prefix_add_delegate_to_same_operation(monkeypatch, mock_bot, mock_interaction, mock_context):
    cog = module.PortfolioManager(mock_bot)
    add = AsyncMock()
    monkeypatch.setattr(cog, '_add', add)
    callback = cast(Any, cog.portfolio_add_slash.callback).__wrapped__
    await callback(cog, mock_interaction, 'Title', 'Description', 'https://example.com', 'Python')
    add.assert_awaited_with(mock_interaction, 'Title', 'Description', 'https://example.com', 'Python')
    monkeypatch.setattr(module, 'safe_send', AsyncMock())
    mock_bot.wait_for = AsyncMock(
        side_effect=[
            SimpleNamespace(content=text) for text in ['Title', 'Description', 'https://example.com', 'Python']
        ]
    )
    callback = cast(Any, cog.portfolio_add_prefix.callback).__wrapped__
    await callback(cog, mock_context)
    add.assert_awaited_with(mock_context, 'Title', 'Description', 'https://example.com', 'Python')


def test_tiny_display_budgets_never_overflow():
    assert clip_text('🙂', 0) == ''
    assert clip_text(0, 10) == '0'
    assert text_units(bounded_items(['<@&123>'], 3)) <= 3


async def test_serverinfo_bounds_title_and_labels_cached_counts(monkeypatch, mock_bot, mock_interaction):
    from src.cogs.external import info

    send = AsyncMock()
    monkeypatch.setattr(info, 'safe_send', send)
    mock_interaction.guild = SimpleNamespace(
        id=123,
        name='🙂' * 20000,
        owner=None,
        member_count=None,
        members=[],
        text_channels=[],
        voice_channels=[],
        categories=[],
        roles=[],
        premium_tier=0,
        premium_subscription_count=0,
        created_at=None,
        icon=None,
    )
    cog = ExternalInfo(mock_bot)
    callback = cast(Any, cog.serverinfo.callback).__wrapped__
    await callback(cog, mock_interaction)
    embed = send.call_args.kwargs['embed']
    _assert_embed_limits(embed)
    assert 'Members**: Unknown' in embed.description and 'Online in cache: 0' in embed.description
