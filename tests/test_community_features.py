"""Community correctness regressions (Phase 4, no DB/network)."""

from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import nextcord
import pytest

from src.cogs import marketplace_enhanced as enhanced_module
from src.cogs.external.export import ChatExport
from src.cogs.networking.networking import ConnectionResponseView
from src.services.marketplace_service import bump_listing, validate_listing_text, validate_price
from src.services.networking_service import NetworkingService, normalize_skills, normalize_timezone


@pytest.mark.parametrize('price', ['NaN', 'Infinity', '-1', '-$1', '0', '-0', '999999.991', '1000000', '1.234', 'one'])
def test_price_rejects_nonfinite_negative_out_of_range_and_fractional_cents(price):
    with pytest.raises(ValueError):
        validate_price(price)


@pytest.mark.parametrize('price,expected', [('$12.34', '12.34'), (10.0, '10.00')])
def test_price_preserves_exact_cents(price, expected):
    assert validate_price(price) == Decimal(expected)


def test_skills_normalize_to_bounded_array():
    assert normalize_skills(' Python, SQL, Python, ') == ['Python', 'SQL']
    assert normalize_skills([' Python ', 'SQL']) == ['Python', 'SQL']
    with pytest.raises(ValueError):
        normalize_skills(['x' * 65])
    with pytest.raises(ValueError):
        normalize_skills([str(i) for i in range(21)])


def test_timezone_is_validated():
    assert normalize_timezone(' UTC ') == 'UTC'
    with pytest.raises(ValueError):
        normalize_timezone('not/a/timezone')


async def test_profile_sql_persists_array_and_timezone(monkeypatch, mock_db):
    monkeypatch.setattr('src.services.networking_service.db', mock_db)
    svc = NetworkingService()
    monkeypatch.setattr(svc, '_resolve_user_id', AsyncMock(return_value=5))
    await svc.upsert_profile('123', {'title': 'Developer', 'skills': 'Python, SQL', 'timezone': 'UTC'})
    args = mock_db.execute.call_args.args
    assert args[3] == ['Python', 'SQL']
    assert args[7:] == ('UTC', True)
    assert '$3::text[]' in args[0] and 'timezone = CASE' in args[0]


async def test_profile_omitted_timezone_is_not_cleared(monkeypatch, mock_db):
    monkeypatch.setattr('src.services.networking_service.db', mock_db)
    svc = NetworkingService()
    monkeypatch.setattr(svc, '_resolve_user_id', AsyncMock(return_value=5))
    await svc.upsert_profile('123', {'title': 'Developer', 'skills': []})
    assert mock_db.execute.call_args.args[-1] is False


async def test_bump_enforces_owner_status_and_cooldown_in_update(mock_db):
    mock_db.fetch_one.return_value = {'id': 'listing'}
    assert await bump_listing('listing', 123, database=mock_db)
    sql, listing_id, owner = mock_db.fetch_one.call_args.args
    assert (listing_id, owner) == ('listing', '123')
    assert "l.status = 'active'" in sql
    assert "INTERVAL '24 hours'" in sql
    assert 'u.discord_id = $2' in sql
    mock_db.fetch_one.return_value = None
    assert not await bump_listing('listing', 123, database=mock_db)


async def test_connection_response_is_recipient_only_and_persistent():
    view = ConnectionResponseView(42, '123', '456', 'Requester', NetworkingService())
    assert view.is_persistent()
    assert {button.custom_id for button in view.children if isinstance(button, nextcord.ui.Button)} == {
        'connection:42:accept',
        'connection:42:decline',
    }
    other = SimpleNamespace(user=SimpleNamespace(id=789), response=SimpleNamespace(send_message=AsyncMock()))
    assert not await view.interaction_check(cast(Any, other))
    other.response.send_message.assert_awaited_once()
    other.user.id = 456
    assert await view.interaction_check(cast(Any, other))
    view.stop()


async def test_connection_response_commits_request_and_connection_together(monkeypatch, mock_db):
    conn = MagicMock()
    conn.execute = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={'requester_id': 5, 'recipient_id': 7})
    committed = []

    @asynccontextmanager
    async def transaction():
        yield conn
        committed.append(True)

    monkeypatch.setattr(mock_db, 'transaction', transaction, raising=False)
    mock_db.fetch_one.return_value = {'requester_id': 5, 'recipient_id': 7}
    monkeypatch.setattr('src.services.networking_service.db', mock_db)
    assert await NetworkingService().respond_request(42, '456', accept=True)
    assert committed == [True]
    assert 'pg_advisory_xact_lock' in conn.execute.call_args_list[0].args[0]
    assert "r.status = 'pending'" in conn.fetchrow.call_args.args[0]
    assert conn.fetchrow.call_args.args[1:] == (42, '456', 'accepted')
    assert 'INSERT INTO connections' in conn.execute.call_args_list[-1].args[0]
    conn.fetchrow.return_value = None
    conn.execute.reset_mock()
    assert not await NetworkingService().respond_request(42, '789', accept=True)
    assert conn.execute.await_count == 1  # lock only; no connection inserted


def test_export_slot_is_reserved_before_acknowledgement(mock_bot):
    cog = ChatExport(mock_bot)
    assert cog._claim_export(123, 77)
    assert not cog._claim_export(456, 88)
    assert (cog._export_owner_id, cog._export_guild_id) == (123, 77)


@pytest.mark.parametrize(
    'query',
    [
        '',
        'x' * 1001,
        'gpu | min_price:NaN',
        'gpu | max_price:Infinity',
        'gpu | min_price:-1',
        'gpu | min_price:20 | max_price:10',
        'gpu | condition:bogus',
        'gpu | sort:whatever',
        'gpu | min_rating:NaN',
        'gpu | min_rating:6',
        'gpu | min_rating:1e-999999999',
        'gpu | min_price:1 | min_price:2',
        'gpu | unknown:1',
        'gpu | malformed',
        'gpu | min_price:',
    ],
)
def test_marketplace_search_rejects_bad_filters_before_query(query, mock_bot):
    with pytest.raises(ValueError):
        enhanced_module.MarketplaceEnhanced(mock_bot)._parse_search_query(query)


async def test_marketplace_search_bounds_normalizes_and_parameterizes_values(mock_bot, mock_db, monkeypatch):
    monkeypatch.setattr(enhanced_module, 'db', mock_db)
    cog = enhanced_module.MarketplaceEnhanced(mock_bot)
    filters = cog._parse_search_query("x' OR 1=1 -- | min_price:0 | max_price:$12.34 | min_rating:4.5 | sort:price_low")
    assert filters['min_price'] == Decimal('0.00')
    await cog._run_search(filters)
    sql, *params = mock_db.fetch_many.call_args.args
    assert "x' OR 1=1 --" not in sql
    assert params == ["x' OR 1=1 --", Decimal('0.00'), Decimal('12.34'), Decimal('4.50')]
    assert 'NULLS LAST, l.id DESC' in sql and sql.endswith(' LIMIT 20')


def test_zero_price_only_allowed_for_search_bounds():
    with pytest.raises(ValueError):
        validate_price('0')  # existing schema requires positive listing/offer prices
    assert validate_price('0', allow_zero=True) == Decimal('0.00')


@pytest.mark.parametrize(
    'title,description', [('   ', ''), ('x' * 101, ''), ('🙂' * 51, ''), ('Good title', 'x' * 3001)]
)
def test_marketplace_listing_text_rejects_blank_or_unrenderable_content(title, description):
    with pytest.raises(ValueError):
        validate_listing_text(title, description)
    assert validate_listing_text(' Laptop ', ' Working ') == ('Laptop', 'Working')


async def test_direct_search_revalidates_before_sql(mock_bot, mock_db, monkeypatch):
    monkeypatch.setattr(enhanced_module, 'db', mock_db)
    with pytest.raises(ValueError):
        await enhanced_module.MarketplaceEnhanced(mock_bot)._run_search({'min_rating': 'NaN'})
    mock_db.fetch_many.assert_not_awaited()
