import asyncpg
import logging
from typing import Any, Optional

from src.config.config import DATABASE_URL
from src.core.runtime_state import runtime_state
from src.database.migrations import MIGRATIONS_TABLE, list_migration_files
from src.utils.safety import DatabaseUnavailableError

logger = logging.getLogger('VEKA.database')

class Database:
    """PostgreSQL database connection manager using asyncpg."""

    def __init__(self) -> None:
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self) -> None:
        if self.pool is not None:
            return

        self.pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=1,
            max_size=10,
        )
        logger.info('Database connection pool established')

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()
            self.pool = None
            logger.info('Database connection closed')

    async def ping(self) -> bool:
        if self.pool is None:
            runtime_state.db_available = False
            raise DatabaseUnavailableError('Database pool is not initialized')

        try:
            async with self.pool.acquire() as connection:
                await connection.fetchval('SELECT 1')
            return True
        except asyncpg.PostgresError as exc:
            runtime_state.db_available = False
            logger.error('Database ping failed: %s', exc, exc_info=True)
            raise DatabaseUnavailableError('PostgreSQL unavailable') from exc
        except Exception as exc:
            runtime_state.db_available = False
            logger.error('Database ping failed: %s', exc, exc_info=True)
            raise DatabaseUnavailableError('Database ping error') from exc

    async def fetch_one(self, query: str, *args: Any) -> Optional[asyncpg.Record]:
        if self.pool is None:
            runtime_state.db_available = False
            raise DatabaseUnavailableError('Database pool is not initialized')

        try:
            async with self.pool.acquire() as connection:
                return await connection.fetchrow(query, *args)
        except asyncpg.PostgresError as exc:
            runtime_state.db_available = False
            logger.error('Database fetch_one failed: %s | query=%s | args=%s', exc, query, args, exc_info=True)
            raise DatabaseUnavailableError('Database query failed') from exc

    async def fetchrow(self, query: str, *args: Any) -> Optional[asyncpg.Record]:
        return await self.fetch_one(query, *args)

    async def fetch(self, query: str, *args: Any):
        if self.pool is None:
            runtime_state.db_available = False
            raise DatabaseUnavailableError('Database pool is not initialized')

        try:
            async with self.pool.acquire() as connection:
                return await connection.fetch(query, *args)
        except asyncpg.PostgresError as exc:
            runtime_state.db_available = False
            logger.error('Database fetch failed: %s | query=%s | args=%s', exc, query, args, exc_info=True)
            raise DatabaseUnavailableError('Database query failed') from exc

    async def fetch_many(self, query: str, *args: Any):
        return await self.fetch(query, *args)

    async def fetchval(self, query: str, *args: Any) -> Any:
        if self.pool is None:
            runtime_state.db_available = False
            raise DatabaseUnavailableError('Database pool is not initialized')

        try:
            async with self.pool.acquire() as connection:
                return await connection.fetchval(query, *args)
        except asyncpg.PostgresError as exc:
            runtime_state.db_available = False
            logger.error('Database fetchval failed: %s | query=%s | args=%s', exc, query, args, exc_info=True)
            raise DatabaseUnavailableError('Database query failed') from exc

    async def execute(self, query: str, *args: Any) -> str:
        if self.pool is None:
            runtime_state.db_available = False
            raise DatabaseUnavailableError('Database pool is not initialized')

        try:
            async with self.pool.acquire() as connection:
                return await connection.execute(query, *args)
        except asyncpg.PostgresError as exc:
            runtime_state.db_available = False
            logger.error('Database execute failed: %s | query=%s | args=%s', exc, query, args, exc_info=True)
            raise DatabaseUnavailableError('Database query failed') from exc

    async def execute_many(self, query: str, args_list: list[tuple[Any, ...]]) -> None:
        if self.pool is None:
            runtime_state.db_available = False
            raise DatabaseUnavailableError('Database pool is not initialized')

        try:
            async with self.pool.acquire() as connection:
                await connection.executemany(query, args_list)
        except asyncpg.PostgresError as exc:
            runtime_state.db_available = False
            logger.error('Database execute_many failed: %s | query=%s | args_list=%s', exc, query, args_list, exc_info=True)
            raise DatabaseUnavailableError('Database query failed') from exc

    async def run_migrations(self) -> None:
        if self.pool is None:
            runtime_state.db_available = False
            raise DatabaseUnavailableError('Database pool is not initialized')

        migration_files = list_migration_files()
        if not migration_files:
            logger.info('No migration files found')
            return

        async with self.pool.acquire() as connection:
            await connection.execute(
                f"CREATE TABLE IF NOT EXISTS {MIGRATIONS_TABLE} ("
                "filename TEXT PRIMARY KEY, applied_at TIMESTAMP DEFAULT NOW()"
                ")"
            )
            existing = {
                row['filename']
                for row in await connection.fetch(f"SELECT filename FROM {MIGRATIONS_TABLE}")
            }

            for migration_path in migration_files:
                migration_name = migration_path.name
                if migration_name in existing:
                    continue

                sql = migration_path.read_text()
                async with connection.transaction():
                    logger.info('Applying migration: %s', migration_name)
                    await connection.execute(sql)
                    await connection.execute(
                        f"INSERT INTO {MIGRATIONS_TABLE} (filename) VALUES ($1)",
                        migration_name,
                    )
                    logger.info('Applied migration: %s', migration_name)


# Global database instance

db = Database()


async def get_user(discord_id: str):
    user = await db.fetch_one('SELECT * FROM users WHERE discord_id = $1', discord_id)
    if user:
        return user

    return await create_user(discord_id)


async def create_user(discord_id: str):
    return await db.fetch_one(
        '''
        INSERT INTO users (discord_id)
        VALUES ($1)
        ON CONFLICT (discord_id) DO UPDATE SET updated_at = NOW()
        RETURNING *
        ''',
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
