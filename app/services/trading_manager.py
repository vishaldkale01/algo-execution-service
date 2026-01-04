import asyncio
from app.services.websocket_client import UpstoxWebSocket
from app.services.trend_analyzer import analyze_trend, update_market_context
from app.services.market_data_service import MarketDataService
from app.database import get_database
from app.services.redis_manager import redis_manager
from datetime import datetime, date

from app.services.trade_lifecycle_manager import DailyRiskMonitor, ActiveTradeContext
from app.models.trade import VirtualTrade, TradeType

class UserTrader:
    def __init__(self, user_id: str, access_token: str, config: dict):
        self.user_id = user_id
        self.access_token = access_token
        self.config = config
        self.ws_client = None
        self.market_data_service = MarketDataService(access_token)
        self.is_active = False
        self.bg_tasks = []
        
        # Managers
        self.risk_monitor = DailyRiskMonitor(max_trades=5, max_loss_amt=2500)
        self.active_trade: Optional[ActiveTradeContext] = None

    async def on_market_data(self, message):
        """Callback from WebSocket"""
        try:
            # Extract basic info locally for Trade Management before Analysis
            # We need LTP to manage active trade.
            # Assuming message structure matches what verify scripts sent or what analyze_trend parses.
            # We'll need a helper to extract LTP from 'message' quickly without re-parsing everything.
            # For now, let's rely on analyze_trend returning data or extract manually.
            
            feeds = message.get("feeds", {})
            for instrument_key, feed in feeds.items():
                if "INDEX" not in instrument_key: continue # Simple filter
                
                ff = feed.get('ff', {})
                ltpc = ff.get('ltpc', {})
                ltp = ltpc.get('ltp', ltpc.get('cp', 0))
                if not ltp: continue
                
                # 1. Manage Active Trade
                if self.active_trade:
                    # Trailing Stop requires Market Structure (Previous Candle High/Low)
                    # LTP is used for SL triggers
                    
                    prev_high = ltp
                    prev_low = ltp
                    
                    # Extract last closed candle for separate Trailing Logic
                    if 'marketOHLC' in ff:
                        ohlc_data = ff['marketOHLC'].get('ohlc', [])
                        # We need at least 2 candles (Current + Previous) to get a closed one
                        # If list has > 1, [-2] is previous. If len=1, it might be the only one (current).
                        if len(ohlc_data) >= 2:
                            prev_c = ohlc_data[-2]
                            prev_high = float(prev_c.get('high', ltp))
                            prev_low = float(prev_c.get('low', ltp))
                    
                    actions = self.active_trade.update(current_price=ltp, high=prev_high, low=prev_low)
                    
                    if actions:
                        print(f"⚡ Trade Update ({self.user_id}): {actions}")
                        
                        if "update_sl" in actions:
                            # TODO: Send Modify Order to Broker
                            pass
                            
                        if "partial_exit" in actions:
                            # TODO: Send Sell Order (50%)
                            pass
                            
                        if "entry_price" in actions:
                            pass # Just log
                            
                        if actions.get("action") == "EXIT_ALL":
                            reason = actions.get("reason")
                            price = actions.get("price")
                            # TODO: Send Sell Order (All)
                            
                            # Calculate PnL (Approx)
                            entry = self.active_trade.entry_price
                            pnl = (price - entry) if self.active_trade.trade.tradeType == TradeType.CALL else (entry - price)
                            # Multiply by Qty
                            pnl_amt = pnl * self.active_trade.trade.quantity
                            
                            self.risk_monitor.record_trade(pnl_amt)
                            print(f"❌ Trade CLOSED ({reason}) PnL: {pnl_amt}")
                            
                            self.active_trade = None
                            
                    continue # Skip analysis if we have active trade (Single concurrency)

            # 2. If No Active Trade, Check Risk & Look for Signals
            can_trade, reason = self.risk_monitor.can_trade()
            if not can_trade:
                # Log rejection periodically or on signal (handled in logic or we can log here if verbose)
                return

            # Check Cooldown
            if self.risk_monitor.last_trade_result == "LOSS" and self.risk_monitor.last_trade_time:
                 secs_since = (datetime.now() - self.risk_monitor.last_trade_time).total_seconds()
                 if secs_since < (15 * 60):
                     return

            # 3. Analyze for Entry
            await analyze_trend(message, self.user_id, self.config, on_signal=self.handle_signal)
            
        except Exception as e:
            print(f"Error in on_market_data: {e}")

    async def handle_signal(self, signal: dict):
        """Callback when trend_analyzer finds a setup"""
        if self.active_trade: return
        
        # Double check Risk with logging
        can_trade, reason = self.risk_monitor.can_trade()
        if not can_trade:
             print(f"⚠️ Signal REJECTED (Risk): {signal['signal']} | Reason: {reason}")
             return
             
        # Check Cooldown again explicitly for log
        if self.risk_monitor.last_trade_result == "LOSS" and self.risk_monitor.last_trade_time:
             secs_since = (datetime.now() - self.risk_monitor.last_trade_time).total_seconds()
             if secs_since < (15 * 60):
                 print(f"⚠️ Signal REJECTED (Cooldown): {signal['signal']} | Wait {int(900-secs_since)}s")
                 return
        
        # Create Virtual Trade
        v_trade = VirtualTrade(
            symbol="BANKNIFTY",
            tradeType=getattr(TradeType, signal['signal'].replace("BUY_", "")),
            entryPrice=signal['entry_price'],
            stopLoss=signal['stop_loss'],
            targetPrice=signal['target'],
            quantity=15
        )
        
        print(f"🚀 ENTERING TRADE [{v_trade.id}]: {signal['signal']} | Price: {signal['entry_price']} | Score: {signal.get('confidence')}")
        print(f"   📝 Rationale: {signal.get('setup')} | ADX: {signal.get('adx'):.1f} | ATR: {signal.get('atr'):.1f}")
        
        # Create Context
        self.active_trade = ActiveTradeContext(
            v_trade,
            atr=signal['atr'],
            sl=signal['stop_loss'],
            target=signal['target']
        )

    async def update_option_chain_loop(self):
        """Periodic task to fetch Option Chain and update subscriptions"""
        print("🔄 Starting Option Chain Loop")
        symbol_index = "NSE_INDEX|Nifty Bank" # Default target
        
        while self.is_active:
            try:
                # 1. Get Spot Price to identify ATM
                market_status = await self.market_data_service.get_market_status(symbol_index)
                if not market_status:
                    print("⚠️ Could not fetch market status, retrying in 1 min..." , market_status)
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
