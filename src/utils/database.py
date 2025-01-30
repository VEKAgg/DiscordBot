from motor.motor_asyncio import AsyncIOMotorClient
from typing import Optional
import os
from dotenv import load_dotenv
from .logger import setup_logger

logger = setup_logger()
load_dotenv()

class Database:
    client: Optional[AsyncIOMotorClient] = None
    db = None

    @classmethod
    async def init_database(cls):
        """Initialize database connection"""
        try:
            # Get MongoDB URI from environment variables
            mongodb_uri = os.getenv('MONGODB_URI')
            if not mongodb_uri:
                raise ValueError("MONGODB_URI environment variable not set")

            # Initialize MongoDB client
            cls.client = AsyncIOMotorClient(mongodb_uri)
            cls.db = cls.client.veka_bot
            
            # Test connection
            await cls.client.admin.command('ping')
            logger.info("Successfully connected to MongoDB")
            
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {str(e)}")
            raise

    @classmethod
    async def close_database(cls):
        """Close database connection"""
        if cls.client:
            cls.client.close()
            logger.info("Closed MongoDB connection")

# Initialize database connection
async def init_database():
    await Database.init_database()

# Get database instance
def get_database():
    return Database.db 