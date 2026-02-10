import asyncio
from app.services.websocket_client import UpstoxWebSocket
from app.services.trend_analyzer import TrendAnalyzer
from app.services.market_data_service import MarketDataService
from app.database import get_database
from app.services.redis_manager import redis_manager
from app.services.risk_engine import RiskEngine
from datetime import datetime, date

from app.services.trade_lifecycle_manager import ActiveTradeContext 
from app.models.trade import VirtualTrade, TradeType, TradeStatus

from app.services.order_execution_service import OrderExecutionService
from app.services.audit_logger import AuditLogger

class UserTrader:
    def __init__(self, user_id: str, access_token: str, config: dict):

        self.user_id = user_id
        self.access_token = access_token
        self.config = config
        self.ws_client = None
        self.market_data_service = MarketDataService(access_token)
        
        # Managers
        self.audit_log = AuditLogger(user_id)
        
        # Execution Service (Paper Trading by default if not specified)
        is_paper = config.get("PAPER_TRADING", True)
        self.execution_service = OrderExecutionService(access_token, paper_trading=is_paper)
        
        self.is_active = False
        self.bg_tasks = []
        
        # Managers
        self.risk_engine = RiskEngine(user_id, max_trades=5, max_loss_amt=2500)
        self.analyzer = TrendAnalyzer(user_id)
        self.active_trade: Optional[ActiveTradeContext] = None

    async def on_market_data(self, message):
        """Callback from WebSocket"""
        try:
            feeds = message.get("feeds", {})
            for instrument_key, feed in feeds.items():
                
                # Check if it's an Index or Option
                is_index = "INDEX" in instrument_key
                
                ff = feed.get('ff', {})
                ltpc = ff.get('ltpc', {})
                ltp = ltpc.get('ltp', ltpc.get('cp', 0))
                if not ltp: continue
                
                # Extract Candle Data for Analyzer
                candle = None
                if 'marketOHLC' in ff:
                    ohlc_data = ff['marketOHLC'].get('ohlc', [])
                    if ohlc_data:
                        for c in ohlc_data:
                             if c.get('interval') == 'I1':
                                  candle = {
                                      'timestamp': datetime.fromtimestamp(int(c['ts']) / 1000),
                                      'open': float(c['open']),
                                      'high': float(c['high']),
                                      'low': float(c['low']),
                                      'close': float(c['close']),
                                      'volume': float(c.get('volume', 0))
                                  }
                                  break
                
                # 1. Manage Active Trade (If any)
                if self.active_trade and candle:
                     # Use candle high/low for accurate trailing
                     actions = self.active_trade.update(
                         current_price=ltp, 
                         high=candle['high'], 
                         low=candle['low']
                     )
                     
                     if actions:
                        print(f"[TRADE] Trade Update ({self.user_id}): {actions}")
                        
                        if "update_sl" in actions:
                            # Update SL Order logic (simulated or real modifiers)
                            # For MVP: If we had a real SL-M order, we would modify it here.
                            # self.execution_service.modify_order(...)
                            pass
                            
                        if actions.get("action") == "EXIT_ALL":
                            reason = actions.get("reason")
                            price = actions.get("price")
                            
                            # Execute Exit Order
                            exit_resp = await self.execution_service.place_order(
                                instrument_key=self.active_trade.trade.symbol, # We tracked symbol/key
                                transaction_type="SELL", # Assuming BUY entry
                                quantity=self.active_trade.trade.quantity,
                                order_type="MARKET",
                                tag="EXIT"
                            )
                            
                            # Calculate PnL (Approx based on LTP, real PnL comes from fills)
                            entry = self.active_trade.entry_price
                            pnl = (price - entry) if self.active_trade.trade.tradeType == TradeType.CALL else (entry - price)
                            pnl_amt = pnl * self.active_trade.trade.quantity
                            
                            await self.risk_engine.record_trade(pnl_amt)
                            
                            # Update Persistence
                            self.active_trade.trade.status = TradeStatus.CLOSED
                            self.active_trade.trade.exitTime = datetime.now()
                            self.active_trade.trade.exitPrice = price
                            self.active_trade.trade.pnl = pnl_amt
                            
                            db = await get_database()
                            await db.trades.update_one(
                                {"id": self.active_trade.trade.id},
                                {"$set": self.active_trade.trade.model_dump()},
                                upsert=True
                            )
                            
                            print(f"[EXIT] Trade CLOSED ({reason}) PnL: {pnl_amt} | OrderID: {exit_resp.get('data', {}).get('order_id')}")
                            
                            self.active_trade = None
                     
                     continue

                # 2. Analyze for New Signals
                if is_index and candle:
                    start_time = datetime.now()
                    signal = self.analyzer.process_tick(instrument_key, candle, is_index=True)
                    latency_ms = (datetime.now() - start_time).total_seconds() * 1000
                    
                    if signal:
                        # Log Signal for Audit
                        db = await get_database()
                        await db.signals.insert_one({
                            "user_id": self.user_id,
                            "timestamp": datetime.now(),
                            "instrument": instrument_key,
                            "candle": candle,
                            "signal_data": signal,
                            "latency_ms": latency_ms
                        })
                        
                        if signal.get("signal") in ["BUY_CALL", "BUY_PUT"]:
                            await self.handle_signal(signal)

        except Exception as e:
            print(f"Error in on_market_data: {e}")
            import traceback
            traceback.print_exc()

    async def handle_signal(self, signal: dict):
        """Callback when trend_analyzer finds a setup"""
        if self.active_trade: return
        
        # Risk Check
        can_trade, reason = await self.risk_engine.can_trade()
        if not can_trade:
             print(f"[WARN] Signal REJECTED (Risk): {signal['signal']} | Reason: {reason}")
             return
        
        # 1. Identify Option Strike (ATM)
        # We need to pick the right option based on 'signal' (BUY_CALL / BUY_PUT)
        # signal['entry_price'] is Index Spot Price.
        # We need to look up the Option Instrument Key we are subscribed to
        
        # Simplify: Use the 'opt_instrument_key' if we tracked it, or calculate ATM again.
        # For MVP: Let's assume we find the ATM strike from our MarketDataService or Analyzer Context
        # Analyzer now tracks 'context'. 
        
        # Quick Hack: Calculate ATM from Spot Entry
        target_strike = round(signal['entry_price'] / 100) * 100
        option_type = "CE" if "CALL" in signal['signal'] else "PE"
        # We need the Instrument Key for this Strike + Type
        # Ideally, Analyzer should return the Instrument Key to trade.
        # Since it doesn't yet, we'll try to reconstruct or pick from subscription.
        # This is a gap. I will assume we have a helper or just print mapping for now.
        # REALITY: We need to map Strike -> Instrument Key. 
        # For now, I will use a placeholder function or look at self.analyzer.state keys
        
        instrument_key_to_trade = f"NSE_FO|BANKNIFTY...{target_strike}{option_type}" # Pseudo
        
        # 2. Place Broker Order
        qty = 15 # Freeze qty
        txn_type = "BUY"
        
        print(f"[SIGNAL] {signal['signal']} @ {signal['entry_price']}")
        
        # Execute
        order_resp = await self.execution_service.place_order(
            instrument_key=instrument_key_to_trade, # This needs to be real
            transaction_type=txn_type,
            quantity=qty,
            order_type="MARKET",
            tag="ENTRY"
        )
        
        if order_resp.get("status") == "error":
            print(f"[ERROR] Order Execution Failed: {order_resp.get('message')}")
            return

        order_id = order_resp.get("data", {}).get("order_id")
        
        # 3. Create Virtual Trade Wrapper
        v_trade = VirtualTrade(
            symbol=instrument_key_to_trade,
            tradeType=getattr(TradeType, "CALL" if "CALL" in signal['signal'] else "PUT"),
            entryPrice=signal['entry_price'], # Index Price (Approx) - Real fill price unknown yet
            stopLoss=signal['stop_loss'],
            targetPrice=signal['target'],
            quantity=qty,
            status=TradeStatus.SUBMITTED
        )
        
        # 4. Create Context
        self.active_trade = ActiveTradeContext(
            v_trade,
            atr=signal['atr'],
            sl=signal['stop_loss'],
            target=signal['target'],
            entry_order_id=order_id
        )
        
        # Save Initial Trade to DB
        db = await get_database()
        await db.trades.insert_one(v_trade.model_dump())
        
        print(f"[OK] Trade Initialized (Order {order_id})")

    async def update_option_chain_loop(self):
        """Periodic task to fetch Option Chain and update subscriptions"""
        print("[INFO] Starting Option Chain Loop")
        symbol_index = "NSE_INDEX|Nifty Bank" # Default target
        
        while self.is_active:
            try:
                # 1. Get Spot Price to identify ATM
                market_status = await self.market_data_service.get_market_status(symbol_index)
                if not market_status:
                    print("[WARN] Could not fetch market status, retrying in 1 min..." , market_status)
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
                total_call_oi = metadata.get('total_call_oi', 0)
                total_put_oi = metadata.get('total_put_oi', 0)
                
                print(f"[MARKET] Spot={market_status} | PCR={pcr:.2f} | Subs={len(sub_keys)}")
                
                # 4. Update Context in Analyzer Instance
                self.analyzer.update_context(
                    symbol_index, 
                    pcr=pcr,
                    oi_data={
                        "timestamp": datetime.now(),
                        "pcr": pcr,
                        "call_oi": total_call_oi,
                        "put_oi": total_put_oi
                    }
                )
                
                # 5. Update WebSocket Subscriptions
                # Subscribe to Index + Options
                all_keys = [symbol_index] + sub_keys
                if self.ws_client:
                    self.ws_client.subscribe(all_keys, mode="full")
                
                # 6. Save Market Snapshot
                state = self.analyzer._get_state(symbol_index)
                if state:
                    db = await get_database()
                    await db.snapshots.insert_one({
                        "user_id": self.user_id,
                        "timestamp": datetime.now(),
                        "symbol": symbol_index,
                        "pcr": pcr,
                        "spot_price": market_status,
                        "indicators": {
                            "vwap": state.vwap_cum_vol_price / state.vwap_cum_vol if state.vwap_cum_vol > 0 else 0,
                            # EMA/Supertrend are calculated on the fly in Analyzer, 
                            # we could store the last calculated values if we cached them.
                        }
                    })

                # Wait 5 minutes
                await asyncio.sleep(300)
                
            except Exception as e:
                print(f"[ERROR] Option Chain Loop Error: {e}")
                await asyncio.sleep(60)

    async def start(self):
        """Start trading for this user"""
        if self.is_active:
            return
        
        print(f"[START] Starting trading for user {self.user_id}")
        self.is_active = True
        await self.audit_log.log("TRADING_SESSION_START", details=self.config)
        
        # Initialize WebSocket for this user
        # Pass callback
        self.ws_client = UpstoxWebSocket(
            self.access_token, 
            self.user_id, 
            self.config,
            on_data_callback=self.on_market_data
        )

        # 0. Warmup with Historical Data (Index Only)
        try:
             # Default is Bank Nifty for now
             symbol_index = "NSE_INDEX|Nifty Bank" 
             print(f"[WAIT] Warming up indicators for {symbol_index}...")
             history = await self.market_data_service.fetch_historical_data(symbol_index, "1minute", days=10)
             if history:
                 # Populate Analyzer state
                 state = self.analyzer._get_state(symbol_index)
                 # We need to process them one by one to build VWAP/EMA state correctly 
                 # OR just load them if logic supports bulk load (Our current logic processes tick by tick)
                 # Better to batch load into candles list and run a bulk calc? 
                 # Current TrendAnalyzer.process_tick calculates dataframe from state.candles list.
                 # So we just need to set the list.
                 state.candles = history
                 # We also need to init VWAP. 
                 # Simplified: Just calculating VWAP from last day would be enough or let it build up.
                 # Ideally, we loop through today's candles to build accumulation.
                 today = datetime.now().date()
                 todays_candles = [c for c in history if c['timestamp'].date() == today]
                 for c in todays_candles:
                     self.analyzer._calculate_vwap(state, c)
                     
                 print(f"[OK] Warmup Complete. Loaded {len(history)} candles.")
        except Exception as e:
             print(f"[WARN] Warmup Failed: {e}")
        
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
            
        print(f"[STOP] Stopping trading for user {self.user_id}")
        self.is_active = False
        await self.audit_log.log("TRADING_SESSION_STOP")
        
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

        print(f"[CMD] Received command: {action} for {user_id}")

        if action == "START_TRADING":
            await self.start_user_trading(user_id, data)
        elif action == "STOP_TRADING":
            await self.stop_user_trading(user_id)
        elif action == "UPDATE_SETTINGS":
            await self.update_settings(user_id, data)
        else:
            print(f"[WARN] Unknown command: {action}")

    async def start_user_trading(self, user_id: str, data: dict):
        access_token = data.get("access_token")
        config = data.get("strategy_config")
        print("config:", config)    
        if not access_token:
            print(f"[ERROR] Missing access token for {user_id}")
            return

        if user_id in self.active_traders:
            print(f"[WARN] User {user_id} already active")
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
            print(f"[WARN] User {user_id} not found")

    async def update_settings(self, user_id: str, config: dict):
        if user_id in self.active_traders:
            self.active_traders[user_id].config = config
            print(f"[OK] Updated settings for {user_id}")
        else:
            print(f"[WARN] User {user_id} not active, cannot update settings")

# Global instance
trading_manager = TradingManager()
