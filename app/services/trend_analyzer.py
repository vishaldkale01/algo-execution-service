from typing import List, Dict, Any
from datetime import datetime
import pandas as pd
import pandas_ta as ta
from app.models.trade import VirtualTrade, TradeType, TradeStatus
from app.utils.patterns import identify_candlestick_patterns
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

# Scalping configuration
SCALPING_CONFIG = {
    "targetPercent": 0.3, # Scalp target
    "stopLossPercent": 0.2, # Scalp SL
    "minConfidence": 80,  # High confidence for scalp
    "minCandles": {
        "oneMin": 20, # Need history for EMA21
    }
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

def analyze_price_action(candles: List[Dict]) -> str:
    """Analyze price action patterns"""
    if len(candles) < 3:
        return "NEUTRAL"
    
    current = candles[-1]
    body_size = abs(current['close'] - current['open'])
    wick_size = abs(max(current['high'] - current['close'], current['open'] - current['low']))
    
    if body_size > wick_size * 2:
        return "STRONG_BULL" if current['close'] > current['open'] else "STRONG_BEAR"
    
    return "NEUTRAL"

def analyze_scalping_signals(symbol: str, candles: List[Dict], current_price: float) -> Dict:
    """
    Analyze scalping signals based on User Logic:
    IF
    - Price > VWAP
    - EMA 9 > EMA 21
    - Strong bullish candle
    - PCR < 1 (Context)
    THEN BUY CALL
    """
    if len(candles) < 22: # Need at least 21 candles for EMA21
        return {}
        
    # Convert to DataFrame
    df = pd.DataFrame(candles)
    cols = ['open', 'high', 'low', 'close', 'volume']
    for col in cols:
        df[col] = pd.to_numeric(df[col])
        
    # Calculate Indicators
    df['ema9'] = df.ta.ema(length=9)
    df['ema21'] = df.ta.ema(length=21)
    
    # VWAP (already computed per candle, but let's take the latest cached or recompute if needed)
    # Ideally, we pass the series, but we have a running VWAP. 
    # Let's trust the running VWAP for the current tick signal.
    vwap_value = calculate_vwap(symbol, candles[-1])
    
    last = df.iloc[-1]
    
    ema9_val = last['ema9']
    ema21_val = last['ema21']
    
    # Price Action
    price_action = analyze_price_action(candles)
    
    # Market Context
    pcr = market_context.get(symbol, {}).get('pcr', 1.0) # Default to 1 (Neutral)
    
    signal = "NEUTRAL"
    confidence = 0
    
    # ------------------------------------------------------------------
    # CORE STRATEGY LOGIC
    # ------------------------------------------------------------------
    
    # BUY CALL CONDITIONS
    if (current_price > vwap_value and 
        ema9_val > ema21_val and 
        price_action == "STRONG_BULL" and
        pcr < 1): # PCR < 1 usually means Bullish (lots of Puts sold support) or Bearish? 
        # Standard: High PCR (>1.5) = Bearish/Overbought? No.
        # Nifty Analysis: PCR > 1 means more Puts OI (Support), usually Bullish sentiment (Put writing).
        # PCR < 1 means more Calls OI (Resistance), usually Bearish sentiment.
        # USER REQUESTED: "PCR < 1 -> BUY CALL". 
        # CAUTION: This contradicts standard "Put Writing = Bullish" logic (High PCR = Bullish).
        # User prompt says: "IF ... PCR < 1 ... THEN BUY CALL (scalp)".
        # Wait, usually PCR < 0.7 is Oversold (Buy msg). Maybe that's the logic?
        # I will strictly follow USER LOGIC: "PCR < 1 -> BUY CALL".
        
        signal = "BUY_CALL"
        confidence = 90
        
    # BUY PUT CONDITIONS (Inverse)
    elif (current_price < vwap_value and 
          ema9_val < ema21_val and 
          price_action == "STRONG_BEAR" and 
          pcr > 1): # Inverse of user logic for Put
          
        signal = "BUY_PUT"
        confidence = 90

    return {
        "signal": signal,
        "confidence": confidence,
        "vwap": vwap_value,
        "ema9": ema9_val,
        "ema21": ema21_val,
        "pcr": pcr,
        "priceAction": price_action
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
            
            # --- FIXED: Merge with existing history ---
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
            
            # Keep last 100
            if len(merged) > 100:
                merged = merged[-100:]
                
            candle_store[instrument_key] = merged
            candles = merged # Use full history for analysis
            # ------------------------------------------
            
            # Only analyze if it's the Index (or the main signal source)
            # If instrument_key is the Spot Index (e.g. NSE_INDEX|Nifty Bank)
            if "INDEX" in instrument_key:
                # Analyze
                signals = analyze_scalping_signals(instrument_key, candles, ltp)
                
                if not signals:
                    print(f"Stats: {len(candles)} candles (Need 22 for signals)")
                    continue
                
                print(f"Data {instrument_key} | {signals.get('signal')} | Conf: {signals.get('confidence')} | Price: {ltp} | VWAP: {signals.get('vwap', 0):.2f}")
                
                # Execute Trade Logic
                if signals.get('signal') in ["BUY_CALL", "BUY_PUT"] and signals.get('confidence', 0) >= SCALPING_CONFIG['minConfidence']:
                    # Trigger Trade
                    # We need to find the correct Option Symbol (ATM) from the Context
                    # For now, just print TRADING SIGNAL
                    print(f"EXECUTE {signals['signal']} on {instrument_key}")
                    
                    # Store logic or call place_order here
                    # ...

        except Exception as e:
            print(f"Analysis Error ({instrument_key}): {e}")
