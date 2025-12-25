import asyncio
import sys
import os

# Add app to path
sys.path.append(os.getcwd())

from app.services.trend_analyzer import analyze_trend, update_market_context, candle_store
from datetime import datetime, timedelta


async def test_pipeline():
    print("Starting Pipeline Verification...")
    
    # 1. Simulate Market Context (REST API)
    # Scenario: Bullish Context (PCR < 1)
    print("\n1. Simulating Option Chain Update (REST)")
    symbol = "NSE_INDEX|Nifty Bank"
    pcr = 0.6 # Bullish
    update_market_context(symbol, pcr)
    print(f"Market Context Updated: PCR={pcr}")

    # 2. Simulate Ticks to Build History (WebSocket)
    print("\n2. Simulating Tick Data Stream (WebSocket)")
    
    # We need to generate ~25 fake candles to prime indicators (EMA21)
    base_price = 45000.0
    start_time = datetime.now() - timedelta(minutes=30)
    
    ticks = []
    
    # Generate Trending Up Scenario
    # Price increasing, Volume increasing
    for i in range(30):
        t_time = start_time + timedelta(minutes=i)
        
        # Bullish Candle
        open_p = base_price + (i * 10)
        close_p = open_p + 15
        high_p = close_p + 2
        low_p = open_p - 2
        volume = 1000 + (i * 100)
        
        # Upstox Message Format Mock
        msg = {
            "feeds": {
                symbol: {
                    "ff": {
                        "ltpc": {"ltp": close_p},
                        "marketOHLC": {
                            "ohlc": [
                                {
                                    "interval": "I1", 
                                    "ts": int(t_time.timestamp() * 1000),
                                    "open": open_p, "high": high_p, "low": low_p, "close": close_p, "volume": volume
                                }
                            ]
                        }
                    }
                }
            }
        }
        await analyze_trend(msg)
        
    print(f"History Built: {len(candle_store.get(symbol, []))} candles")
    
    # 3. Trigger Verification
    # Send one last "Strong Bull" candle on top of current context
    print("\n3. Verifying Signal Generation")
    
    # Last Price = 45000 + 290 + 15 = 45305
    # VWAP should be roughly (Mean Price * Vol) / Vol. 
    # Since price is strictly increasing, Price > VWAP should hold.
    # EMA9 should be > EMA21.
    # Price Action = Strong Bull.
    # PCR = 0.6 (< 1).
    
    # Expected: BUY_CALL
    
    # Wait a tiny bit for async prints to flush? No need in script.
    
    print("\nVerification Complete. Check console output for 'EXECUTE BUY_CALL'")

if __name__ == "__main__":
    asyncio.run(test_pipeline())
