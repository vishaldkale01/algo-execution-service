import asyncio
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from app.services.replay_service import MarketReplayService
from app.services.mock_services import MockMarketDataService, MockExecutionService
from app.services.trend_analyzer import TrendAnalyzer
from app.services.risk_engine import RiskEngine
from app.services.trade_lifecycle_manager import ActiveTradeContext
from app.models.trade import TradeType, TradeStatus, VirtualTrade

# Simple Replay Logic
async def run_replay():
    print("Fetching History (Bank Nifty)...")
    
    # 1. Load Data (YFinance ^NSEBANK)
    # 5 days, 1m interval
    ticker = yf.Ticker("^NSEBANK")
    df = ticker.history(period="5d", interval="1m")
    
    if df.empty:
        print("No data fetched.")
        return

    # Convert to list of dicts
    candles = []
    for idx, row in df.iterrows():
        # idx is Timestamp (tz-aware usually)
        # remove tz for simplicity
        ts = idx.replace(tzinfo=None)
        candles.append({
            "timestamp": ts,
            "open": row['Open'],
            "high": row['High'],
            "low": row['Low'],
            "close": row['Close'],
            "volume": row['Volume']
        })
        
    print(f"Loaded {len(candles)} candles.")
    
    # 2. Setup Services
    replay = MarketReplayService(candles)
    mock_market = MockMarketDataService(replay)
    mock_exec = MockExecutionService(replay)
    
    # 3. Setup Components
    user_id = "REPLAY_USER"
    analyzer = TrendAnalyzer(user_id)
    risk_engine = RiskEngine(user_id)
    
    # Manually wire them up (simulating UserTrader logic without full class overhead for now)
    # Or better: Instantiate UserTrader with mocks injected?
    # UserTrader creates its own services. We'd need to monkeypatch or subclass.
    # Monkeypatching UserTrader for this test is easier.
    
    from app.services.trading_manager import UserTrader
    
    # Subclass to inject mocks
    class ReplayTrader(UserTrader):
        def __init__(self, uid, token, cfg):
            self.user_id = uid
            self.access_token = token
            self.config = cfg
            self.ws_client = None # No WS needed
            self.bg_tasks = []
            
            # INJECT MOCKS
            self.market_data_service = mock_market
            self.execution_service = mock_exec
            self.risk_engine = risk_engine
            self.analyzer = analyzer
            self.active_trade = None
            self.is_active = True
            
        async def start(self):
            print("Replay Trader Ready.")
            # Skip background tasks
            
    trader = ReplayTrader(user_id, "mock_token", {"PAPER_TRADING": True})
    
    # 4. Run Loop
    print("\n--- STARTING REPLAY ---")
    
    trades_taken = 0
    
    # Pre-loading history into analyzer (First 200 candles)
    warmup_count = 200
    for _ in range(warmup_count):
        c = await replay.next_tick()
        if c:
             analyzer.process_tick("NSE_INDEX|BankNifty", c, is_index=True)
             
    print(f"Warmed up with {warmup_count} candles.")
    
    try:
        while replay.has_next():
            candle = await replay.next_tick()
            if not candle: break
            
            current_time = candle['timestamp']
            
            # 4.1 Update Active Trade
            if trader.active_trade:
                # Simulate OPTION price movement (Delta 0.5 approx)
                # We don't have option candles. 
                # We must use Index Movement * Delta.
                # Entry Index Price
                # entry_idx = trader.active_trade.entry_order_id # We stored order_id, oops.
                # In mock exec, we stored price.
                
                # Let's simplify: 
                # We just pass the INDEX candle to update().
                # ActiveTradeContext.update() expects 'current_price' (LTP).
                # If we pass Index LTP, the PnL will be huge (Index Points).
                # We need to scale it or just track Index Points captured.
                
                # Hack: Pass Index Price, but treat PnL as Index Points.
                actions = trader.active_trade.update(
                     current_price=candle['close'],
                     high=candle['high'],
                     low=candle['low']
                )
                
                if actions:
                    print(f"[{current_time.time()}] TRADE ACTION: {actions}")
                    if actions.get("action") == "EXIT_ALL":
                         # Close
                         await mock_exec.place_order("OPT", "SELL", 15, "MARKET")
                         pnl = actions.get("price") - trader.active_trade.entry_price
                         if trader.active_trade.trade.tradeType == TradeType.PUT:
                             pnl = -pnl
                             
                         print(f"[{current_time.time()}] EXIT PnL (Points): {pnl:.2f}")
                         trader.active_trade = None
                         trades_taken += 1

            # 4.2 Analyze New Signal
            # Simulated "Update Context" (every 5 mins)
            if current_time.minute % 5 == 0:
                 # Fetch Option Chain (Mock)
                 chain = await mock_market.fetch_option_chain("IDX", "EXP")
                 _, meta = mock_market.extract_target_strikes(chain, candle['close'])
                 analyzer.update_context("NSE_INDEX|BankNifty", pcr=meta['pcr'], oi_data={"timestamp": current_time, "pcr": meta['pcr'], "call_oi": 100, "put_oi": 100})

            # Process Tick
            signal = analyzer.process_tick("NSE_INDEX|BankNifty", candle, is_index=True)
            
            if signal and signal.get("signal") in ["BUY_CALL", "BUY_PUT"] and not trader.active_trade:
                 # Handle Signal
                 print(f"[{current_time.time()}] SIGNAL: {signal.get('signal')} Score: {signal.get('confidence')}")
                 await trader.handle_signal(signal)
                 
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"CRASH: {e}")
             
    print(f"\n--- REPLAY FINISHED ---")
    print(f"Total Trades: {trades_taken}")

if __name__ == "__main__":
    asyncio.run(run_replay())
