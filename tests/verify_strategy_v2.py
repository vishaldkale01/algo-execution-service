import asyncio
import pandas as pd
from datetime import datetime, timedelta
from app.services.trend_analyzer import TrendAnalyzer, MarketState

def create_mock_candle(timestamp, close, trend="FLAT"):
    """Helper to create a candle"""
    open_p = close
    if trend == "UP":
        close = close + 10
        high = close + 5
        low = open_p - 2
    elif trend == "DOWN":
        close = close - 10
        high = open_p + 2
        low = close - 5
    else:
        high = close + 2
        low = close - 2
        
    return {
        "timestamp": timestamp,
        "open": open_p,
        "high": high,
        "low": low,
        "close": close,
        "volume": 1000
    }

async def verify_strategy_v2():
    print("[TEST] Verifying Strategy V2 (OI & Multi-Timeframe)...")
    
    analyzer = TrendAnalyzer("test_user_v2")
    symbol = "NSE_INDEX|Nifty Bank"
    state = analyzer._get_state(symbol)
    
    # 1. Test OI Analysis
    print("\n[STEP 1] Testing OI Analysis Logic")
    # Scenario A: Bullish OI (Rising PCR)
    # Ensure distinct timestamps
    t0 = datetime.now() - timedelta(minutes=15)
    t1 = datetime.now() - timedelta(minutes=10)
    t2 = datetime.now() - timedelta(minutes=5)
    
    analyzer.update_context(symbol, oi_data={"timestamp": t0, "pcr": 0.9, "call_oi": 100, "put_oi": 90})
    analyzer.update_context(symbol, oi_data={"timestamp": t1, "pcr": 1.1, "call_oi": 100, "put_oi": 110})
    analyzer.update_context(symbol, oi_data={"timestamp": t2, "pcr": 1.3, "call_oi": 100, "put_oi": 130})
    
    sentiment = analyzer.analyze_oi_trends(state)
    print(f"      OI Sentiment (Expected BULLISH): {sentiment}")
    print(f"      OI History Len: {len(state.oi_history)}")
    
    if sentiment != "BULLISH":
        print("[FAIL] OI Sentiment detection failed")
    else:
        print("[PASS] OI Sentiment detected correctly")

    # 2. Test 5-min Resampling & Confirmation (Confluence Scenario)
    print("\n[STEP 2] Testing 5-min Resampling & Signal Generation (Confluence)")
    
    # Generate 120 minutes of UPTREND (to set 5-min EMA Bullish and satisfy min_history)
    # Use fixed time inside trading hours (10:00 AM)
    today_10am = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
    base_time = today_10am - timedelta(minutes=140)
    price = 45000
    
    # 120 mins of uptrend
    for i in range(120):
        c_time = base_time + timedelta(minutes=i)
        c = create_mock_candle(c_time, price, trend="UP")
        price = c['close']
        analyzer.process_tick(symbol, c, is_index=True)
        
    # Now simulate a short pullback (Down)
    for i in range(3):
        c_time = base_time + timedelta(minutes=120+i)
        c = create_mock_candle(c_time, price, trend="DOWN")
        price = c['close']
        analyzer.process_tick(symbol, c, is_index=True)

    # Now Bullish Engulfing Logic (Reversal)
    # First candle: Red
    c_time = base_time + timedelta(minutes=123)
    c_red = {
        "timestamp": c_time,
        "open": price, "high": price+2, "low": price-10, "close": price-8, "volume": 2000
    }
    analyzer.process_tick(symbol, c_red, is_index=True)
    
    # Second candle: Green (Engulfing)
    c_time = base_time + timedelta(minutes=124)
    c_green = {
        "timestamp": c_time,
        "open": price-8, "high": price+15, "low": price-10, "close": price+12, "volume": 5000
    }
    
    # Force Price > EMA (to satisfy is_uptrend bias logic in analyzer)
    # We generated uptrend for 25 mins, so EMA should be well below price.
    
    result = analyzer.process_tick(symbol, c_green, is_index=True)
    
    # Expectation: 
    # 5-min Trend: BULLISH (Long uptrend) -> +2
    # Pattern: Engulfing -> +3
    # OI: BULLISH (from Step 1) -> +1
    # PCR > 1.2 -> +2
    # Strong Candle -> +1
    # Total Score approx 9
    
    print(f"      Result Signal: {result.get('signal', 'NONE')}")
    print(f"      Confidence Score: {result.get('confidence', 0)}")
    print(f"      Reason: {result.get('reason', 'N/A')}")
    
    df_5m = analyzer.resample_to_5min(state.candles)
    print(f"      5-min Candles Generated: {len(df_5m)}")
    
    if result.get('signal') == "BUY_CALL" and result.get('confidence', 0) >= 5:
         print("[PASS] Confluence Signal Generated Successfully")
    else:
         print("[FAIL] Signal Generation Failed")

if __name__ == "__main__":
    asyncio.run(verify_strategy_v2())
