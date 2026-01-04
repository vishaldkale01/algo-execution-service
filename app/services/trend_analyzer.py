from typing import List, Dict, Any
from datetime import datetime, time
import pandas as pd
import pandas_ta as ta
from app.models.trade import VirtualTrade, TradeType, TradeStatus
from app.utils.patterns import identify_patterns, is_strong_candle
from app.database import get_database

# Cache for recent calculations
calculation_cache = {}
CACHE_EXPIRY = 1 * 60 * 1000  # 1 minute in milliseconds

# Signal history cache
previous_signals_cache = {}

# In-memory candle storage
# Structure: candle_store[symbol] = [{'timestamp': datetime, 'open': float, ...}, ...]
candle_store = {}

# VWAP Storage
# Structure: vwap_store[symbol] = {'cum_pv': float, 'cum_vol': float, 'last_reset': date}
vwap_store = {}

# Market Context (PCR, etc.)
# Structure: market_context[symbol] = {'pcr': float, 'updated_at': timestamp}
market_context = {}

# -----------------------------------------------------------------------------
# NEW: Global State for Strategy (Locks, ORB)
# -----------------------------------------------------------------------------

# Trade Lock Store
# Structure: trade_lock_store[symbol] = {
#     "locked": bool, "entry_price": float, "signal_type": str, "lock_time": datetime, "counter": int
# }
trade_lock_store = {}

# ORB Store (Opening Range Breakout - First 15 mins)
# Structure: orb_store[symbol] = { "high": float, "low": float, "set": bool, "date": date }
orb_store = {}

# Scalping configuration
SCALPING_CONFIG = {
    "targetPercent": 0.3, # Scalp target
    "stopLossPercent": 0.2, # Scalp SL
    "minConfidence": 80,  # High confidence for scalp
    "minCandles": {
        "oneMin": 20, # Need history for EMA21
    },
    "tradeLockCooldown": 5, # Candles to wait after a trade signal
    "orbStartTime": time(9, 15),
    "orbEndTime": time(9, 30)
}

def update_market_context(symbol: str, pcr: float):
    """Update global market context (e.g., PCR)"""
    market_context[symbol] = {
        'pcr': pcr,
        'updated_at': datetime.now()
    }

def calculate_vwap(symbol: str, candle: Dict) -> float:
    """Calculate Intraday VWAP"""
    current_date = candle['timestamp'].date()
    
    if symbol not in vwap_store:
        vwap_store[symbol] = {'cum_pv': 0.0, 'cum_vol': 0.0, 'last_reset': current_date}
    
    # Reset VWAP at start of day
    if vwap_store[symbol]['last_reset'] < current_date:
        vwap_store[symbol] = {'cum_pv': 0.0, 'cum_vol': 0.0, 'last_reset': current_date}
    
    typical_price = (candle['high'] + candle['low'] + candle['close']) / 3
    volume = candle.get('volume', 0)
    
    vwap_store[symbol]['cum_pv'] += typical_price * volume
    vwap_store[symbol]['cum_vol'] += volume
    
    if vwap_store[symbol]['cum_vol'] == 0:
        return typical_price # Fallback
        
    return vwap_store[symbol]['cum_pv'] / vwap_store[symbol]['cum_vol']

def update_orb_levels(symbol: str, candles: List[Dict]):
    """Update Open Range Breakout (ORB) levels for the day"""
    if not candles: return

    current_date = candles[-1]['timestamp'].date()
    
    # Initialize or Reset for new day
    if symbol not in orb_store or orb_store[symbol].get('date') != current_date:
        orb_store[symbol] = { "high": 0, "low": float('inf'), "set": False, "date": current_date }
    
    orb = orb_store[symbol]
    
    if orb['set']:
        return # Already set for the day

    # Filter candles between 9:15 and 9:30
    orb_candles = [
        c for c in candles 
        if c['timestamp'].date() == current_date and 
           SCALPING_CONFIG['orbStartTime'] <= c['timestamp'].time() < SCALPING_CONFIG['orbEndTime']
    ]
    
    if orb_candles:
        highs = [c['high'] for c in orb_candles]
        lows = [c['low'] for c in orb_candles]
        orb['high'] = max(highs)
        orb['low'] = min(lows)
        
        # If time is past 9:30, mark as SET
        if candles[-1]['timestamp'].time() >= SCALPING_CONFIG['orbEndTime']:
            orb['set'] = True
            # print(f"ORB SET for {symbol}: {orb['high']} - {orb['low']}")

def check_trade_lock(symbol: str, current_price: float, candles: List[Dict]) -> bool:
    """
    Check if trading is locked for this symbol.
    Unlock conditions:
    1. Cooldown timer expired (5 candles).
    2. Price returns to range (simple mean reversion check vs Entry).
    """
    if symbol not in trade_lock_store:
        return False
        
    lock = trade_lock_store[symbol]
    if not lock['locked']:
        return False
        
    # Condition 1: Counter / Time
    # In a real async stream, we count invocations or time. Here we rely on candle updates.
    # We'll just check time difference if simple, or assume this is called per candle.
    # Let's use time difference since 'lock_time'. 
    # Assuming 1-min candles, 5 mins cooldown.
    time_diff = datetime.now() - lock['lock_time']
    if time_diff.total_seconds() > (SCALPING_CONFIG['tradeLockCooldown'] * 60):
        lock['locked'] = False
        return False
        
    # Condition 2: Deep Reversal (Stop Loss hit effectively or Invalidated)
    # This is handled by Trade Manager usually. 
    # Here we just implement strict time cooldown to prevent over-signaling.
    
    return True

def set_trade_lock(symbol: str, signal: str, price: float):
    """Lock trading after substantial signal"""
    trade_lock_store[symbol] = {
        "locked": True,
        "entry_price": price,
        "signal_type": signal,
        "lock_time": datetime.now(),
        "counter": 0
    }

def analyze_scalping_signals(symbol: str, candles: List[Dict], current_price: float) -> Dict:
    """
    Analyze scalping signals using:
    1. Market Structure (Trend)
    2. Patterns (Hammer, Engulfing, etc.)
    3. Breakouts (ORB)
    4. Filters (Volume, VWAP, Trade Lock)
    """
    if len(candles) < 22: 
        return {}
        
    # 1. Update ORB
    update_orb_levels(symbol, candles)
    
    # 2. Check Lock
    if check_trade_lock(symbol, current_price, candles):
        return {"signal": "LOCKED", "reason": "Cooldown Active"}

    # Convert to DataFrame for Indicators
    df = pd.DataFrame(candles)
    cols = ['open', 'high', 'low', 'close', 'volume']
    for col in cols:
        df[col] = pd.to_numeric(df[col])
        
    # Calculate Indicators
    df['ema9'] = df.ta.ema(length=9)
    df['ema21'] = df.ta.ema(length=21)
    
    vwap_value = calculate_vwap(symbol, candles[-1])
    
    last_candle = candles[-1]
    prev_candle = candles[-2]
    
    ema9_val = df['ema9'].iloc[-1]
    ema21_val = df['ema21'].iloc[-1]
    
    # Pattern Recognition
    patterns = identify_patterns(candles)
    
    # Market Context
    pcr = market_context.get(symbol, {}).get('pcr', 1.0)
    
    signal = "NEUTRAL"
    confidence = 0
    setup_type = ""
    stop_loss = 0.0

    # ------------------------------------------------------------------
    # DECISION TREE IMPLEMENTATION
    # ------------------------------------------------------------------
    
    # Valid Locations
    near_vwap = abs(current_price - vwap_value) <= (0.001 * current_price)
    near_ema = abs(current_price - ema9_val) <= (0.001 * current_price)
    location_valid = near_vwap or near_ema

    # PRIORITY 1: ORB Breakout (High Confidence)
    orb = orb_store.get(symbol)
    if orb and orb['set']:
        # Bullish ORB
        if current_price > orb['high'] and patterns['has_volume_support']:
            # Ensure we haven't ranged too far? Breakout just happened?
            # Check if previous Close was BELOW ORB High (Fresh Breakout)
            if prev_candle['close'] <= orb['high']:
                signal = "BUY_CALL"
                confidence = 95
                setup_type = "ORB_BREAKOUT"
                stop_loss = orb['high'] * (1 - 0.001) # Tight SL below breakout

        # Bearish ORB
        elif current_price < orb['low'] and patterns['has_volume_support']:
            if prev_candle['close'] >= orb['low']:
                signal = "BUY_PUT"
                confidence = 95
                setup_type = "ORB_BREAKOUT"
                stop_loss = orb['low'] * (1 + 0.001)

    # PRIORITY 2: Range Breakout / Generic Breakout (Skipped for now, covered by ORB/Momentum)
    
    # PRIORITY 3: Inside Bar Breakout
    if signal == "NEUTRAL" and patterns['is_inside_bar']: 
        # Inside Bar itself is neutral, we need the NEXT candle to break it
        # This checks if PREVIOUS was inside bar ?? 
        # No, 'is_inside_bar' from helper checks if CURRENT is inside previous.
        # So we can't trade ON the inside bar. We trade the BREAK of it.
        # Logic: If Previous Checks was Inside Bar... (Need state or lookback)
        # Let's check lag:
        is_prev_inside = identify_patterns(candles[:-1]).get('is_inside_bar', False)
        if is_prev_inside:
            prev_high = prev_candle['high']
            prev_low = prev_candle['low']
            if current_price > prev_high:
                signal = "BUY_CALL"
                confidence = 85
                setup_type = "INSIDE_BAR_BREAK"
            elif current_price < prev_low:
                signal = "BUY_PUT"
                confidence = 85
                setup_type = "INSIDE_BAR_BREAK"

    # PRIORITY 4: Engulfing (Reversal/Continuation)
    if signal == "NEUTRAL":
        if patterns['is_bullish_engulfing'] and (location_valid or ema9_val > ema21_val):
            signal = "BUY_CALL"
            confidence = 80
            setup_type = "BULL_ENGULFING"
        elif patterns['is_bearish_engulfing'] and (location_valid or ema9_val < ema21_val):
            signal = "BUY_PUT"
            confidence = 80
            setup_type = "BEAR_ENGULFING"

    # PRIORITY 5: Hammer / Shooting Star (Reversal)
    if signal == "NEUTRAL" and location_valid:
        if patterns['is_hammer']:
            # Confirm with trend or context
            if ema9_val > ema21_val or pcr < 1: 
                signal = "BUY_CALL"
                confidence = 75
                setup_type = "HAMMER_REVERSAL"
        elif patterns['is_shooting_star']:
             if ema9_val < ema21_val or pcr > 1:
                signal = "BUY_PUT"
                confidence = 75
                setup_type = "SHOOTING_STAR"

    # PRIORITY 6: Momentum (Fallback - Existing Logic)
    if signal == "NEUTRAL":
        price_action = is_strong_candle(last_candle) # Replaces old analyze_price_action
        if (current_price > vwap_value and ema9_val > ema21_val and 
            price_action == "STRONG_BULL" and pcr < 1.2): # Relaxed PCR slightly
            signal = "BUY_CALL"
            confidence = 70
            setup_type = "MOMENTUM_TREND"
        elif (current_price < vwap_value and ema9_val < ema21_val and 
              price_action == "STRONG_BEAR" and pcr > 0.8):
            signal = "BUY_PUT"
            confidence = 70
            setup_type = "MOMENTUM_TREND"

    # Lock Signal
    if signal in ["BUY_CALL", "BUY_PUT"]:
        set_trade_lock(symbol, signal, current_price)

    return {
        "signal": signal,
        "confidence": confidence,
        "setup": setup_type,
        "vwap": vwap_value,
        "ema9": ema9_val,
        "ema21": ema21_val,
        "pcr": pcr,
        "stop_loss": stop_loss
    }

async def analyze_trend(data: Dict, user_id: str = None, config: Dict = None):
    """Main trend analysis function triggered by WebSocket"""
    
    # 1. Parse Data
    # Upstox WS "full" mode structure:
    # data['feeds'][instrument_key] = { 'ff': { 'marketOHLC': { ... }, 'ltpc': { ... } } }
    
    feeds = data.get("feeds", {})
    if not feeds:
        return

    # User Config
    user_config = config or {}
    trade_mode = user_config.get("trade_mode", "VIRTUAL")
    capital = user_config.get("capital", 100000)
    
    for instrument_key, feed in feeds.items():
        try:
            # We focus on the INDEX for signals (Bank Nifty)
            # But we entered specific keys.
            # Assuming instrument_key maps to "NSE_INDEX|Nifty Bank" or similar.
            # Or if we are tracking options, we handle them separately.
            
            # Extract LTP and Candle
            ff = feed.get('ff', {})
            
            # LTP
            ltpc = ff.get('ltpc', {})
            ltp = ltpc.get('ltp', ltpc.get('cp', 0))
            if not ltp: continue
            
            # Volume (Try to find it)
            volume = 0
            if 'marketOHLC' in ff and 'ohlc' in ff['marketOHLC']:
                # Last candle volume
                 ohlc_data = ff['marketOHLC']['ohlc']
                 if ohlc_data:
                     # Usually the last one is the current minute
                     volume = float(ohlc_data[-1].get('volume', 0))

            # Store Candle
            # We need to build our own minute candles if we want strict control, 
            # but Upstox sends 'marketOHLC'. Let's use that for simplicity and speed.
            
            if 'marketOHLC' not in ff:
                continue
                
            raw_candles = ff['marketOHLC'].get('ohlc', [])
            # Convert to our format
            # Filter for 1min candles (interval 'I1')
            candles = []
            for c in raw_candles:
                if c.get('interval') == 'I1':
                    candles.append({
                        'timestamp': datetime.fromtimestamp(int(c['ts']) / 1000),
                        'open': float(c['open']),
                        'high': float(c['high']),
                        'low': float(c['low']),
                        'close': float(c['close']),
                        'volume': float(c.get('volume', 0))
                    })
            
            if not candles: continue
            
            candles.sort(key=lambda x: x['timestamp'])
            
            # --- Merge with existing history ---
            if instrument_key not in candle_store:
                candle_store[instrument_key] = []
            
            existing = candle_store[instrument_key]
            # Create dict for fast lookup
            existing_map = {c['timestamp']: c for c in existing}
            
            for c in candles:
                existing_map[c['timestamp']] = c
            
            # Convert back to list and sort
            merged = list(existing_map.values())
            merged.sort(key=lambda x: x['timestamp'])
            
            # Keep last 150 for deeper analysis
            if len(merged) > 150:
                merged = merged[-150:]
                
            candle_store[instrument_key] = merged
            candles = merged # Use full history for analysis
            # ------------------------------------------
            
            # Only analyze if it's the Index (or the main signal source)
            # If instrument_key is the Spot Index (e.g. NSE_INDEX|Nifty Bank)
            if "INDEX" in instrument_key or True: # Force analyze for now
                # Analyze
                signals = analyze_scalping_signals(instrument_key, candles, ltp)
                
                if not signals:
                    continue
                
                if signals.get('signal') == "LOCKED":
                    # print(f"LOCKED: {instrument_key} - Cooldown")
                    continue
                
                print(f"[{datetime.now().time()}] {instrument_key} | {signals.get('signal')} | {signals.get('setup')} | Conf: {signals.get('confidence')}")
                
                # Execute Trade Logic
                if signals.get('signal') in ["BUY_CALL", "BUY_PUT"] and signals.get('confidence', 0) >= SCALPING_CONFIG['minConfidence']:
                    # Trigger Trade
                    # We need to find the correct Option Symbol (ATM) from the Context
                    # For now, just print TRADING SIGNAL
                    print(f"!!! EXECUTE {signals['signal']} !!! Setup: {signals['setup']} | Price: {ltp}")
                    
                    # Store logic or call place_order here
                    # ...

        except Exception as e:
            print(f"Analysis Error ({instrument_key}): {e}")
