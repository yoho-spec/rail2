"""
database/mongodb.py
MongoDB connection and initialization
"""
import logging
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from config.settings import settings
from database.schemas import create_indexes

logger = logging.getLogger(__name__)

db: AsyncIOMotorDatabase = None


async def init_db() -> None:
    """Initialize MongoDB connection."""
    global db
    try:
        client = AsyncIOMotorClient(settings.MONGODB_URI)
        db = client[settings.MONGODB_DB_NAME]

        # Test connection
        await db.command("ping")
        logger.info(f"✅ MongoDB connected → {settings.MONGODB_DB_NAME}")

        # Create indexes
        await create_indexes(db)
        logger.info("✅ MongoDB indexes created")

    except Exception as e:
        logger.error(f"❌ MongoDB connection failed: {e}")
        raise


async def close_db() -> None:
    """Close MongoDB connection."""
    global db
    if db:
        db.client.close()
        logger.info("✅ MongoDB connection closed")

