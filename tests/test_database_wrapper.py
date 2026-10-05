"""DB wrapper error taxonomy (audit M-01 / M-02)."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import asyncpg
import pytest

from src.core.runtime_state import runtime_state
from src.database.database import Database
from src.utils.safety import DatabaseQueryError, DatabaseUnavailableError, map_exception_to_message


def _db_raising(exc: Exception) -> Database:
    conn = MagicMock()
    conn.fetchval = AsyncMock(side_effect=exc)

    @asynccontextmanager
    async def acquire(*, timeout):
        assert timeout == 10.0
        yield conn

    database = Database()
    database.pool = MagicMock()
    database.pool.acquire = acquire
    return database


async def test_query_error_does_not_mark_db_unavailable(caplog):
    database = _db_raising(asyncpg.UndefinedColumnError('column "x" does not exist'))
    runtime_state.db_available = True
    with caplog.at_level(logging.ERROR), pytest.raises(DatabaseQueryError):
        await database.fetchval('SELECT x FROM t WHERE secret = $1', 'user-secret-text')
    assert runtime_state.db_available is True
    assert 'user-secret-text' not in caplog.text  # values are never logged
    assert 'arg_types=str' in caplog.text


async def test_connection_error_marks_db_unavailable():
    database = _db_raising(ConnectionRefusedError('refused'))
    runtime_state.db_available = True
    with pytest.raises(DatabaseUnavailableError) as info:
        await database.fetchval('SELECT 1')
    assert not isinstance(info.value, DatabaseQueryError)
    assert runtime_state.db_available is False


def test_query_error_message_is_not_an_outage_message():
    assert 'unavailable' not in map_exception_to_message(DatabaseQueryError('x')).lower()


async def test_query_error_detail_and_data_message_are_not_logged(caplog):
    unique = asyncpg.UniqueViolationError('duplicate key value violates unique constraint "users_discord_id_key"')
    unique.detail = 'Key (discord_id)=(123456789012345678) already exists.'
    unique.constraint_name = 'users_discord_id_key'
    bad_input = asyncpg.InvalidTextRepresentationError('invalid input syntax for type integer: "private-note"')

    for exc in (unique, bad_input):
        database = _db_raising(exc)
        with caplog.at_level(logging.ERROR), pytest.raises(DatabaseQueryError) as info:
            await database.fetchval('INSERT INTO users (discord_id) VALUES ($1)', 'x')
        assert info.value.__cause__ is None  # no chained asyncpg error to leak through later tracebacks
        assert '123456789012345678' not in str(info.value)

    assert '123456789012345678' not in caplog.text
    assert 'private-note' not in caplog.text
    assert 'private-note' not in (runtime_state.last_db_error or '')
    assert 'constraint=users_discord_id_key' in caplog.text
    assert 'sqlstate=22P02' in caplog.text
