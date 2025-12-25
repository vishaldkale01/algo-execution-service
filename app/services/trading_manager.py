import asyncio
from app.services.websocket_client import UpstoxWebSocket
from app.services.trend_analyzer import analyze_trend, update_market_context
from app.services.market_data_service import MarketDataService
from app.database import get_database
from app.services.redis_manager import redis_manager
from datetime import datetime, date

class UserTrader:
    def __init__(self, user_id: str, access_token: str, config: dict):
        self.user_id = user_id
        self.access_token = access_token
        self.config = config
        self.ws_client = None
        self.market_data_service = MarketDataService(access_token)
        self.is_active = False
        self.bg_tasks = []

    async def on_market_data(self, message):
        """Callback from WebSocket"""
        await analyze_trend(message, self.user_id, self.config)

    async def update_option_chain_loop(self):
        """Periodic task to fetch Option Chain and update subscriptions"""
        print("🔄 Starting Option Chain Loop")
        symbol_index = "NSE_INDEX|Nifty Bank" # Default target
        
        while self.is_active:
            try:
                # 1. Get Spot Price to identify ATM
                market_status = await self.market_data_service.get_market_status(symbol_index)
                if not market_status:
                    print("⚠️ Could not fetch market status, retrying in 1 min...")
                    await asyncio.sleep(60)
                    continue
                
                # 2. Fetch Option Chain (Current Expiry)
                # For demo, hardcoding generic expiry logic or need a function to get next expiry
                # This needs to be dynamic. 
                expiry = "2025-01-01" # Placeholder - In real app, calculate next Thursday
                
                # Fetch chain
                chain_data = await self.market_data_service.fetch_option_chain(symbol_index, expiry)
                
                # 3. Extract Strikes & PCR
                sub_keys, metadata = self.market_data_service.extract_target_strikes(
                    chain_data, market_status, step=100
                )
                
                pcr = metadata.get('pcr', 0)
                print(f"📊 Market Update: Spot={market_status} | PCR={pcr:.2f} | Subs={len(sub_keys)}")
                
                # 4. Update Context in Analyzer
                update_market_context(symbol_index, pcr)
                
                # 5. Update WebSocket Subscriptions
                # Subscribe to Index + Options
                all_keys = [symbol_index] + sub_keys
                if self.ws_client:
                    self.ws_client.subscribe(all_keys, mode="full")
                
                # Wait 5 minutes
                await asyncio.sleep(300)
                
            except Exception as e:
                print(f"❌ Option Chain Loop Error: {e}")
                await asyncio.sleep(60)

    async def start(self):
        """Start trading for this user"""
        if self.is_active:
            return
        
        print(f"🚀 Starting trading for user {self.user_id}")
        self.is_active = True
        
        # Initialize WebSocket for this user
        # Pass callback
        self.ws_client = UpstoxWebSocket(
            self.access_token, 
            self.user_id, 
            self.config,
            on_data_callback=self.on_market_data
        )
        
        # Start WebSocket in background task
        ws_task = asyncio.create_task(self.ws_client.start())
        self.bg_tasks.append(ws_task)
        
        # Start Option Chain Loop
        chain_task = asyncio.create_task(self.update_option_chain_loop())
        self.bg_tasks.append(chain_task)
        
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
        
        # Stop Web Socket
        if self.ws_client:
            self.ws_client.stop()
            
        # Cancel tasks
        for task in self.bg_tasks:
            task.cancel()
        self.bg_tasks = []
        
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
