import asyncpg
import logging
from src.config.config import DATABASE_URL

logger = logging.getLogger('VEKA.database')

class Database:
    """PostgreSQL database connection manager using asyncpg"""
    
    def __init__(self):
        self.pool = None
    
    async def connect(self):
        """Initialize database connection pool"""
        try:
            self.pool = await asyncpg.create_pool(DATABASE_URL)
            logger.info("Database connection pool established")
        except Exception as e:
            logger.error(f"Failed to connect to database: {str(e)}")
            raise
    
    async def close(self):
        """Close database connection pool"""
        if self.pool:
            await self.pool.close()
            logger.info("Database connection closed")
    
    async def fetch_one(self, query: str, *args):
        """Fetch single record"""
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(query, *args)
    
    async def fetch_many(self, query: str, *args):
        """Fetch multiple records"""
        async with self.pool.acquire() as conn:
            return await conn.fetch(query, *args)
    
    async def execute(self, query: str, *args):
        """Execute query (INSERT, UPDATE, DELETE)"""
        async with self.pool.acquire() as conn:
            return await conn.execute(query, *args)
    
    async def execute_many(self, query: str, args_list):
        """Execute query with multiple parameter sets"""
        async with self.pool.acquire() as conn:
            return await conn.executemany(query, args_list)

# Global database instance
db = Database()

# Convenience functions for common operations

async def get_user(discord_id: str):
    """Get user by Discord ID or create if not exists"""
    user = await db.fetch_one(
        "SELECT * FROM users WHERE discord_id = $1", 
        discord_id
    )
    if not user:
        user = await db.fetch_one(
            """INSERT INTO users (discord_id) 
               VALUES ($1) 
               RETURNING *""",
            discord_id
        )
        logger.info(f"Created new user: {discord_id}")
    return user

async def get_or_create_user(discord_id: str):
    """Alias for get_user"""
    return await get_user(discord_id)

async def update_user_points(discord_id: str, points: int):
    """Update user points"""
    await db.execute(
        "UPDATE users SET points = points + $1 WHERE discord_id = $2",
        points, discord_id
    )
