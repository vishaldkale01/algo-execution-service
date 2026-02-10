import redis.asyncio as redis
import json
import os
from typing import Callable, Awaitable

class RedisManager:
    def __init__(self):
        self.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        self.redis = None
        self.pubsub = None

    async def connect(self):
        """Connect to Redis"""
        self.redis = redis.from_url(self.redis_url, decode_responses=True)
        print(f"[OK] Connected to Redis at {self.redis_url}")

    async def disconnect(self):
        """Disconnect from Redis"""
        if self.redis:
            await self.redis.close()
            print("Redis connection closed")

    async def publish(self, channel: str, message: dict):
        """Publish a message to a channel"""
        if not self.redis:
            await self.connect()
        await self.redis.publish(channel, json.dumps(message))

    async def subscribe(self, channel: str, callback: Callable[[dict], Awaitable[None]]):
        """Subscribe to a channel and execute callback on message"""
        if not self.redis:
            await self.connect()
        
        self.pubsub = self.redis.pubsub()
        await self.pubsub.subscribe(channel)
        print(f"[INFO] Subscribed to channel: {channel}")

        async for message in self.pubsub.listen():
            if message["type"] == "message":
                try:
                    data = json.loads(message["data"])
                    await callback(data)
                except json.JSONDecodeError:
                    print(f"[ERROR] Failed to decode message: {message['data']}")
                except Exception as e:
                    print(f"[ERROR] Error processing message: {e}")

# Global instance
redis_manager = RedisManager()
