"""
Database configuration and connection management
"""
from motor.motor_asyncio import AsyncIOMotorClient
from app.config import settings
import os

# MongoDB client
_client = None
_database = None


async def connect_to_mongo():
    """Connect to MongoDB"""
    global _client, _database
    
    mongodb_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
    database_name = os.getenv("DATABASE_NAME", "upstox_trading")
    
    try:
        _client = AsyncIOMotorClient(mongodb_uri)
        _database = _client[database_name]
        
        # Test connection
        await _client.admin.command('ping')
        print(f"[OK] Connected to MongoDB: {database_name}")
        
    except Exception as e:
        print(f"[ERROR] Failed to connect to MongoDB: {e}")
        raise


async def close_mongo_connection():
    """Close MongoDB connection"""
    global _client
    if _client:
        _client.close()
        print("MongoDB connection closed")


async def get_database():
    """Get database instance"""
    global _database
    
    if _database is None:
        await connect_to_mongo()
    
    return _database
