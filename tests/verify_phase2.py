import asyncio
from app.services.trading_manager import UserTrader
from app.models.trade import TradeType
from datetime import datetime

# Mock Config
config = {
    "PAPER_TRADING": True,
    "strategy": "SCALPING"
}

async def verify_execution_engine():
    print("[TEST] Verifying Execution Engine...")
    
    # 1. Initialize UserTrader
    trader = UserTrader("test_user_phase2", "mock_token", config)
    print("[OK] UserTrader Instantiated")
    
    # 2. Simulate Signal
    signal = {
        "signal": "BUY_CALL",
        "entry_price": 45000.0,
        "stop_loss": 44950.0,
        "target": 45100.0,
        "confidence": 0.8,
        "setup": "Test Setup",
        "adx": 25.0,
        "atr": 50.0
    }
    
    # 3. Handle Signal (Entry)
    print("[STEP] Triggering Signal Handling...")
    await trader.handle_signal(signal)
    
    if trader.active_trade:
        print(f"[OK] Active Trade Created. Order ID: {trader.active_trade.entry_order_id}")
        t = trader.active_trade.trade
        print(f"     Trade: {t.symbol} | PENDING {t.status}")
    else:
        print("[FAIL] No Active Trade created")
        return

    # 4. Simulate Market Data (SL Hit)
    print("[STEP] Simulating Market Data (SL Hit)...")
    
    # Message structure mimicking Upstox
    # We need to construct a message that on_market_data understands
    # It requires 'feeds' -> 'instrument_key' -> 'ff' -> 'ltpc' -> 'ltp'
    # And 'marketOHLC' -> 'ohlc' -> 'I1' for candle
    
    # We need to know the symbol created.
    symbol = trader.active_trade.trade.symbol
    print(f"     Targeting Symbol: {symbol}")
    
    msg = {
        "feeds": {
            symbol: {
                "ff": {
                    "ltpc": {"ltp": 44940.0}, # Below SL (44950)
                    "marketOHLC": {
                        "ohlc": [
                            {
                                "interval": "I1", 
                                "ts": int(datetime.now().timestamp() * 1000),
                                "open": 44960, "high": 44960, 
                                "low": 44940, "close": 44940, "volume": 100
                            }
                        ]
                    }
                }
            }
        }
    }
    
    await trader.on_market_data(msg)
    
    if trader.active_trade is None:
        print("[OK] Trade Exited Successfully (Active Trade is None)")
    else:
        print("[FAIL] Trade did not exit")

if __name__ == "__main__":
    asyncio.run(verify_execution_engine())
