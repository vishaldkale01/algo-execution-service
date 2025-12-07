import asyncio
import json
import redis.asyncio as redis
from dotenv import load_dotenv
import os

load_dotenv()

async def send_start_command():
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    r = redis.from_url(redis_url, decode_responses=True)
    
    # Get token from env or use placeholder
    access_token = os.getenv("UPSTOX_ACCESS_TOKEN")
    if not access_token:
        print("⚠️ UPSTOX_ACCESS_TOKEN not found in .env. Using placeholder (will fail connection).")
        access_token = "your_upstox_access_token_here"

    # Dummy configuration for testing
    command = {
        "action": "START_TRADING",
        "user_id": "test_user_123",
        "data": {
            "access_token": access_token,
            "strategy_config": {
                "trade_mode": "VIRTUAL",  # Change to LIVE for real money
                "capital": 100000,
                "risk_per_trade": 2
            }
        }
    }
    
    print(f"📤 Sending command to {redis_url}...")
    await r.publish("trading:commands", json.dumps(command))
    print("✅ Command sent! Check your main app terminal.")
    
    await r.close()

if __name__ == "__main__":
    asyncio.run(send_start_command())
