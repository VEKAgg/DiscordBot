import logging
import urllib.parse
from typing import Any

import asyncpg

from src.config.config import DATABASE_URL
from src.core.runtime_state import runtime_state
from src.database.migrations import (
    LEGACY_MIGRATION_NAMES,
    MIGRATIONS_TABLE,
    check_duplicate_prefixes,
    list_migration_files,
)
from src.utils.safety import DatabaseQueryError, DatabaseUnavailableError

logger = logging.getLogger('VEKA.database')

# Errors meaning "can't talk to PostgreSQL" (vs. a bad query). OSError covers refused/reset connections;
# TimeoutError covers pool acquire / command timeouts.
_CONNECTION_ERRORS = (
    asyncpg.ConnectionFailureError,
    asyncpg.InterfaceError,
    asyncpg.CannotConnectNowError,
    OSError,
    TimeoutError,
)

POOL_COMMAND_TIMEOUT = 30.0  # seconds per statement
POOL_ACQUIRE_TIMEOUT = 10.0  # seconds to get a connection


def _short(query: str) -> str:
    return ' '.join(query.split())[:300]


def _arg_types(args: tuple) -> str:
    if len(args) == 1 and isinstance(args[0], list):  # execute_many
        return f'<{len(args[0])} rows>'
    return ','.join(type(a).__name__ for a in args)


# SQLSTATE classes whose primary message can embed submitted values (22 = data exception, e.g.
# 'invalid input syntax for type integer: "<value>"'; P0 = PL/pgSQL RAISE with arbitrary text).
_VALUE_BEARING_SQLSTATE_CLASSES = ('22', 'P0')


def _describe_pg_error(exc: asyncpg.PostgresError) -> str:
    """Summarize a PostgreSQL error without parameter values (audit M-02).

    ``str(exc)`` appends DETAIL/HINT, and DETAIL carries row values (``Key (discord_id)=(123) already
    exists.``), so only the class, SQLSTATE, schema object names and — for classes that never embed
    data — the primary message are kept.
    """
    sqlstate = getattr(exc, 'sqlstate', None) or '?'
    parts = [f'sqlstate={sqlstate}']
    for field in ('table_name', 'column_name', 'constraint_name'):
        value = getattr(exc, field, None)
        if value:
            parts.append(f'{field.removesuffix("_name")}={value}')
    message = exc.args[0] if exc.args else ''
    if message and not str(sqlstate).startswith(_VALUE_BEARING_SQLSTATE_CLASSES):
        parts.append(f'message={str(message)[:200]!r}')
    return f'{type(exc).__name__}({", ".join(parts)})'


class Database:
    """PostgreSQL database connection manager using asyncpg."""

    def __init__(self) -> None:
        self.pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        if self.pool is not None:
            return

        # Strip libpq-only keepalive params — asyncpg passes unknown DSN query
        # params as PostgreSQL server_settings, causing the server to reject them.
        _libpq_params = {'keepalives', 'tcp_keepalives_idle', 'tcp_keepalives_interval', 'tcp_keepalives_count'}
        parsed = urllib.parse.urlparse(DATABASE_URL)
        query = {k: v for k, v in urllib.parse.parse_qsl(parsed.query) if k not in _libpq_params}
        parsed = parsed._replace(query=urllib.parse.urlencode(query))
        dsn = urllib.parse.urlunparse(parsed)

        self.pool = await asyncpg.create_pool(
            dsn,
            min_size=1,
            max_size=10,
            max_inactive_connection_lifetime=60.0,
            command_timeout=POOL_COMMAND_TIMEOUT,
            timeout=POOL_ACQUIRE_TIMEOUT,
        )
        logger.info('Database connection pool established')

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()
            self.pool = None
            logger.info('Database connection closed')

    async def reconnect(self) -> None:
        """Close the existing pool and create a brand-new one."""
        logger.info('Attempting database reconnection...')
        if self.pool is not None:
            try:
                await self.pool.close()
            except Exception:
                logger.warning('Error closing old pool during reconnect', exc_info=True)
            self.pool = None
        await self.connect()
        logger.info('Database reconnection successful')

    async def ping(self) -> bool:
        if self.pool is None:
            runtime_state.db_available = False
            raise DatabaseUnavailableError('Database pool is not initialized')

        try:
            async with self.pool.acquire(timeout=POOL_ACQUIRE_TIMEOUT) as connection:
                await connection.fetchval('SELECT 1')
            return True
        except asyncpg.PostgresError as exc:
            runtime_state.db_available = False
            logger.error('Database ping failed: %s', _describe_pg_error(exc))
            raise DatabaseUnavailableError('PostgreSQL unavailable') from None
        except Exception as exc:
            runtime_state.db_available = False
            logger.error('Database ping failed: %s', exc, exc_info=True)
            raise DatabaseUnavailableError('Database ping error') from exc

    async def _run(self, method: str, query: str, *args: Any) -> Any:
        """Run one pool query. Connection-class failures mark the DB unavailable; SQL errors don't.

        Only argument *types* are logged — values can contain user content and IDs (audit M-02).
        """
        if self.pool is None:
            runtime_state.db_available = False
            raise DatabaseUnavailableError('Database pool is not initialized')

        try:
            async with self.pool.acquire(timeout=POOL_ACQUIRE_TIMEOUT) as connection:
                return await getattr(connection, method)(query, *args)
        except _CONNECTION_ERRORS as exc:
            runtime_state.db_available = False
            runtime_state.last_db_error = f'{type(exc).__name__}: {exc}'
            logger.error(
                'Database connection error: %s | query=%s | arg_types=%s', exc, _short(query), _arg_types(args)
            )
            raise DatabaseUnavailableError('Database unavailable') from exc
        except asyncpg.PostgresError as exc:
            # Never format ``exc`` itself (DETAIL holds row values) and don't chain it: anything that
            # later logs the DatabaseQueryError traceback would print the cause's DETAIL.
            summary = _describe_pg_error(exc)
            runtime_state.last_db_error = summary
            logger.error(
                'Database query error: %s | query=%s | arg_types=%s',
                summary,
                _short(query),
                _arg_types(args),
            )
            raise DatabaseQueryError(f'Database query failed: {summary}') from None

    async def fetch_one(self, query: str, *args: Any) -> asyncpg.Record | None:
        return await self._run('fetchrow', query, *args)

    async def fetchrow(self, query: str, *args: Any) -> asyncpg.Record | None:
        return await self.fetch_one(query, *args)

    async def fetch(self, query: str, *args: Any):
        return await self._run('fetch', query, *args)

    async def fetch_many(self, query: str, *args: Any):
        return await self.fetch(query, *args)

    async def fetchval(self, query: str, *args: Any) -> Any:
        return await self._run('fetchval', query, *args)

    async def execute(self, query: str, *args: Any) -> str:
        return await self._run('execute', query, *args)

    async def execute_many(self, query: str, args_list: list[tuple[Any, ...]]) -> None:
        await self._run('executemany', query, args_list)

    async def run_migrations(self) -> None:
        if self.pool is None:
            runtime_state.db_available = False
            raise DatabaseUnavailableError('Database pool is not initialized')

        migration_files = list_migration_files()
        if not migration_files:
            logger.info('No migration files found')
            return

        check_duplicate_prefixes(migration_files)

        async with self.pool.acquire(timeout=POOL_ACQUIRE_TIMEOUT) as connection:
            await connection.execute(
                f'CREATE TABLE IF NOT EXISTS {MIGRATIONS_TABLE} ('
                'filename TEXT PRIMARY KEY, applied_at TIMESTAMPTZ DEFAULT NOW()'
                ')'
            )
            existing = {row['filename'] for row in await connection.fetch(f'SELECT filename FROM {MIGRATIONS_TABLE}')}

            for migration_path in migration_files:
                migration_name = migration_path.name
                if migration_name in existing:
                    continue

                legacy_name = LEGACY_MIGRATION_NAMES.get(migration_name)
                if legacy_name and legacy_name in existing:
                    # Same migration applied under its old filename: record it, don't re-run it.
                    await connection.execute(
                        f'INSERT INTO {MIGRATIONS_TABLE} (filename) VALUES ($1) ON CONFLICT DO NOTHING',
                        migration_name,
                    )
                    logger.info('Migration %s already applied as %s; recorded new name', migration_name, legacy_name)
                    continue

                sql = migration_path.read_text()
                try:
                    async with connection.transaction():
                        logger.info('Applying migration: %s', migration_name)
                        await connection.execute(sql)
                        await connection.execute(
                            f'INSERT INTO {MIGRATIONS_TABLE} (filename) VALUES ($1)',
                            migration_name,
                        )
                except asyncpg.PostgresError as exc:
                    # DETAIL can quote existing rows (e.g. a unique index over duplicated IDs).
                    raise RuntimeError(f'Migration {migration_name} failed: {_describe_pg_error(exc)}') from None
                logger.info('Applied migration: %s', migration_name)


# Global database instance

db = Database()


async def get_user(discord_id: str):
    return await create_user(discord_id)


async def create_user(discord_id: str):
    return await db.fetch_one(
        """
        INSERT INTO users (discord_id)
        VALUES ($1)
        ON CONFLICT (discord_id) DO UPDATE SET updated_at = NOW()
        RETURNING *
        """,
        discord_id,
    )


async def get_or_create_user(discord_id: str):
    return await get_user(discord_id)


async def update_user_points(discord_id: str, points: int) -> None:
    await db.execute(
        'UPDATE users SET points = points + $1 WHERE discord_id = $2',
        points,
        discord_id,
    )
