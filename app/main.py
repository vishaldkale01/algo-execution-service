import asyncio
import os
from app.database import connect_to_mongo, close_mongo_connection
from app.services.redis_manager import redis_manager
from app.services.trading_manager import trading_manager
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

async def main():
    print("🚀 Starting Algo Execution Service...")
    
    # 1. Connect to MongoDB
    try:
        await connect_to_mongo()
    except Exception as e:
        print(f"❌ Failed to connect to DB: {e}")
        return

    # 2. Connect to Redis
    try:
        await redis_manager.connect()
    except Exception as e:
        print(f"❌ Failed to connect to Redis: {e}")
        return

    # 3. Subscribe to Commands
    print("🎧 Waiting for commands on 'trading:commands'...")
    try:
        await redis_manager.subscribe("trading:commands", trading_manager.handle_command)
        breakpoint()
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
    finally:
        await redis_manager.disconnect()
        await close_mongo_connection()
        print("👋 Goodbye!")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

