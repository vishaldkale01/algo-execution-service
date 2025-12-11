import asyncio
from app.services.websocket_client import UpstoxWebSocket
from app.services.trend_analyzer import analyze_trend
from app.database import get_database
from app.services.redis_manager import redis_manager
from datetime import datetime

class UserTrader:
    def __init__(self, user_id: str, access_token: str, config: dict):
        self.user_id = user_id
        self.access_token = access_token
        self.config = config
        self.ws_client = None
        self.is_active = False

    async def start(self):
        """Start trading for this user"""
        if self.is_active:
            return
        
        print(f"🚀 Starting trading for user {self.user_id}")
        self.is_active = True
        
        # Initialize WebSocket for this user
        self.ws_client = UpstoxWebSocket(self.access_token, self.user_id, self.config)
        
        # Start WebSocket in background task
        asyncio.create_task(self.ws_client.start())
        
        # Notify Node.js
        await redis_manager.publish("trading:events", {
            "type": "STATUS",
            "user_id": self.user_id,
            "data": {"status": "RUNNING", "msg": "Trading started successfully"}
        })

    async def stop(self):
        """Stop trading for this user"""
        if not self.is_active:
            return
            
        print(f"🛑 Stopping trading for user {self.user_id}")
        self.is_active = False
        
        # Close WebSocket
        # (Assuming ws_client has a close method or we just let it die)
        # self.ws_client.close() 
        
        await redis_manager.publish("trading:events", {
            "type": "STATUS",
            "user_id": self.user_id,
            "data": {"status": "STOPPED", "msg": "Trading stopped"}
        })

class TradingManager:
    def __init__(self):
        self.active_traders = {} # user_id -> UserTrader

    async def handle_command(self, command: dict):
        """Handle command from Redis"""
        action = command.get("action")
        user_id = command.get("user_id")
        data = command.get("data", {})

        print(f"📨 Received command: {action} for {user_id}")

        if action == "START_TRADING":
            await self.start_user_trading(user_id, data)
        elif action == "STOP_TRADING":
            await self.stop_user_trading(user_id)
        elif action == "UPDATE_SETTINGS":
            await self.update_settings(user_id, data)
        else:
            print(f"⚠️ Unknown command: {action}")

    async def start_user_trading(self, user_id: str, data: dict):
        access_token = data.get("access_token")
        config = data.get("strategy_config")
        print("config:", config)    
        if not access_token:
            print(f"❌ Missing access token for {user_id}")
            return

        if user_id in self.active_traders:
            print(f"⚠️ User {user_id} already active")
            return

        trader = UserTrader(user_id, access_token, config)
        print("trader:", trader)
        self.active_traders[user_id] = trader
        await trader.start()

    async def stop_user_trading(self, user_id: str):
        if user_id in self.active_traders:
            await self.active_traders[user_id].stop()
            del self.active_traders[user_id]
        else:
            print(f"⚠️ User {user_id} not found")

    async def update_settings(self, user_id: str, config: dict):
        if user_id in self.active_traders:
            self.active_traders[user_id].config = config
            print(f"✅ Updated settings for {user_id}")
        else:
            print(f"⚠️ User {user_id} not active, cannot update settings")

# Global instance
trading_manager = TradingManager()
