import sys
import os
from datetime import datetime, timedelta
import numpy as np

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.services.trend_analyzer import analyze_scalping_signals, SCALPING_CONFIG, orb_store, trade_lock_store, vwap_store
from app.utils.patterns import identify_patterns

def create_candle(ts, open_p, high_p, low_p, close_p, volume=1000):
    return {
        'timestamp': ts,
        'open': float(open_p),
        'high': float(high_p),
        'low': float(low_p),
        'close': float(close_p),
        'volume': float(volume)
    }

def test_hammer_reversal():
    print("\n--- Testing Hammer Reversal ---")
    
    # Setup: Down trend approaching VWAP
    base_time = datetime(2025, 12, 29, 10, 0, 0)
    candles = []
    price = 100.0
    
    # 25 Candles for EMA calc
    for i in range(25):
        candles.append(create_candle(base_time + timedelta(minutes=i), price, price+1, price-1, price-0.5))
        price -= 0.5 
    
    # Hammer Candle - Perfect Geometry
    # Body=2, Lower Wick=5, Upper=0
    # Range=7. Open=88, Close=90, High=90, Low=85.
    # Body=2. Lower=3. Upper=0.
    # Lower(3) >= 2*Body(2) => False (3 >= 4). 
    
    # Let's make it more obvious
    # Open=90, Close=91 (Body 1), Low=85 (Lower 5), High=91 (Upper 0).
    # Lower(5) >= 2*1 -> True.
    hammer = create_candle(base_time + timedelta(minutes=25), 90, 91, 85, 91, volume=5000)
    candles.append(hammer)
    
    # Identify Patterns
    p = identify_patterns(candles)
    print(f"Patterns: {p}")
    
    # Test Signal
    # Note: We need Location Valid. VWAP is likely far above.
    # Let's override VWAP store to be near 91
    from app.services.trend_analyzer import vwap_store
    if 'TEST_SYM' not in vwap_store:
        vwap_store['TEST_SYM'] = {'cum_pv': 0, 'cum_vol': 0, 'last_reset': datetime.now().date()}
        
    vwap_store['TEST_SYM']['cum_pv'] = 91 * 100000
    vwap_store['TEST_SYM']['cum_vol'] = 100000
    # VWAP = 91
    
    result = analyze_scalping_signals("TEST_SYM", candles, 91.0)
    print(f"Signal Result: {result}")

def test_orb_breakout():
    print("\n--- Testing ORB Breakout ---")
    orb_store.clear()
    trade_lock_store.clear()
    
    base_time = datetime(2025, 12, 29, 9, 15, 0)
    candles = []
    
    # 9:15 - 9:30 Range (High 105, Low 95)
    # 16 candles
    for i in range(16):
        candles.append(create_candle(base_time + timedelta(minutes=i), 100, 105, 95, 100))
        
    # Need 22+ candles for analysis
    # Add consolidation 9:31 - 9:40
    for i in range(16, 30):
        # Stay inside range
        candles.append(create_candle(base_time + timedelta(minutes=i), 100, 104, 96, 100))
        
    # Breakout at 9:45 (Index 30)
    breakout = create_candle(base_time + timedelta(minutes=30), 102, 110, 102, 108, volume=100000)
    candles.append(breakout)
    
    result = analyze_scalping_signals("TEST_SYM", candles, 108)
    print(f"ORB Signal: {result}")
    
def test_trade_lock():
    print("\n--- Testing Trade Lock ---")
    trade_lock_store.clear()
    
    # Force a lock
    from app.services.trend_analyzer import set_trade_lock
    set_trade_lock("TEST_SYM", "BUY_CALL", 100)
    
    base_time = datetime.now()
    candles = [create_candle(base_time, 100, 101, 99, 100) for _ in range(25)]
    
    result = analyze_scalping_signals("TEST_SYM", candles, 100)
    print(f"Locked Signal: {result}")

if __name__ == "__main__":
    test_hammer_reversal()
    test_orb_breakout()
    test_trade_lock()
