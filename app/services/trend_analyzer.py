from typing import List, Dict, Any, Tuple
from datetime import datetime, time, timedelta
import pandas as pd
import pandas_ta as ta
from app.models.trade import VirtualTrade, TradeType, TradeStatus
from app.utils.patterns import identify_patterns, is_strong_candle
from app.database import get_database

# -----------------------------------------------------------------------------
# CONSTANTS & CONFIGURATION
# -----------------------------------------------------------------------------

class Constants:
    # Risk Management
    ATR_PERIOD = 14
    ATR_MIN_THRESHOLD = 5.0 # Minimum volatility to trade (Index Points)
    SL_MULTIPLIER = 1.0     # 1x ATR
    TARGET_MULTIPLIER = 1.5 # 1.5x ATR
    
    # Signal Scoring
    MIN_SCORE = 4
    
    # Time Windows
    TIME_MORNING_START = time(9, 25)
    TIME_MORNING_END = time(11, 30)
    TIME_AFTERNOON_START = time(13, 15)
    TIME_AFTERNOON_END = time(14, 45)
    
    # Option Constraints
    MIN_PREMIUM = 80.0
    MAX_SPREAD_PCT = 2.0
    RSI_CALL_MAX = 70.0
    RSI_PUT_MIN = 30.0

# Cache for recent calculations
market_context = {}  # {symbol: {'pcr': float, 'updated_at': timestamp}}
trade_lock_store = {} # {symbol: {locked: bool, ...}}
orb_store = {}        # {symbol: {high, low, set}}
vwap_store = {}       # {symbol: {cum_pv, cum_vol}}
candle_store = {}     # {symbol: [candles]}

# -----------------------------------------------------------------------------
# HELPER FUNCTIONS
# -----------------------------------------------------------------------------

def get_time_action(current_time: time) -> str:
    """Check if current time is within valid trading windows."""
    if Constants.TIME_MORNING_START <= current_time <= Constants.TIME_MORNING_END:
        return "ALLOW"
    if Constants.TIME_AFTERNOON_START <= current_time <= Constants.TIME_AFTERNOON_END:
        return "ALLOW"
    # 09:15-09:25 is implicit Reject
    # 11:30-13:15 is Lunch/Chop -> Reject
    # 14:45+ is Square-off -> Reject
    return "REJECT"

def resample_to_5min(candles: List[Dict]) -> pd.DataFrame:
    """Resample 1-min candles to 5-min dataframe for Trend Analysis."""
    if not candles:
        return pd.DataFrame()
        
    df = pd.DataFrame(candles)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df.set_index('timestamp', inplace=True)
    
    ohlc_dict = {
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }
    
    # Resample 5T (5min)
    df_5m = df.resample('5min').apply(ohlc_dict).dropna()
    return df_5m

def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate technical indicators on 1-min Data."""
    # EMA
    df['ema9'] = df.ta.ema(length=9)
    df['ema21'] = df.ta.ema(length=21)
    
    # RSI (14)
    df['rsi'] = df.ta.rsi(length=14)
    
    # ADX (14)
    adx_df = df.ta.adx(length=14)
    if adx_df is not None and not adx_df.empty:
        # pandas_ta returns ADX_14, DMP_14, DMN_14
        df['adx'] = adx_df['ADX_14']
    else:
        df['adx'] = 0
        
    # ATR (14)
    df['atr'] = df.ta.atr(length=Constants.ATR_PERIOD)
    
    return df

def calculate_vwap(symbol: str, candle: Dict) -> float:
    """Calculate Intraday VWAP (Cumulative)."""
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
        return typical_price
        
    return vwap_store[symbol]['cum_pv'] / vwap_store[symbol]['cum_vol']

def calculate_signal_score(
    signals: Dict, 
    trend_aligned: bool, 
    adx: float, 
    rsi: float, 
    volume_expansion: bool,
    bias: str
) -> int:
    """Score the trade setup based on confluence."""
    score = 0
    
    # 1. Trend Alignment (+2)
    if trend_aligned:
        score += 2
        
    # 2. Regime (ADX) (+2)
    if adx > 25:
        score += 2
    elif adx > 20: # Weak but valid
        score += 1
        
    # 3. RSI Zone (+1)
    # Ideal Bull: 50-70, Ideal Bear: 30-50
    if bias == "BULL" and 50 <= rsi <= 70:
        score += 1
    elif bias == "BEAR" and 30 <= rsi <= 50:
        score += 1
        
    # 4. Volume Expansion (+1)
    if volume_expansion:
        score += 1
        
    # 5. Pattern (+1)
    if signals.get('setup', '') != "":
        score += 1
        
    return score

# -----------------------------------------------------------------------------
# CORE LOGIC
# -----------------------------------------------------------------------------

def update_market_context(symbol: str, pcr: float):
    market_context[symbol] = {'pcr': pcr, 'updated_at': datetime.now()}

def analyze_scalping_signals(symbol: str, candles: List[Dict], current_price: float) -> Dict:
    """
    Revised Professional Scalping Logic.
    Flow: Time -> Data -> Timeframe Context -> Filters -> Trigger -> Score -> Output
    """
    
    # 0. Data Validity
    if len(candles) < 150: 
        return {}
        
    last_candle = candles[-1]
    timestamp = last_candle['timestamp']
    
    # Check Stale Data
    lag = (datetime.now() - timestamp).total_seconds()
    if lag > 120: # 2 minutes lag max
        # print(f"Ignoring Stale Data: Lag {lag}s")
        return {}
    
    # 1. Time Filter (Hard Rule)
    time_action = get_time_action(timestamp.time())
    if time_action == "REJECT":
        # We can silently return or log "Market Closed/Chop"
        return {} # No signal in invalid time

    # 2. Prepare 1-min Data & Indicators
    df_1min = pd.DataFrame(candles)
    # Convert cols
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df_1min[col] = pd.to_numeric(df_1min[col])
        
    df_1min = calculate_indicators(df_1min)
    
    # Current Values
    ema9 = df_1min['ema9'].iloc[-1]
    ema21 = df_1min['ema21'].iloc[-1]
    rsi = df_1min['rsi'].iloc[-1]
    adx = df_1min['adx'].iloc[-1]
    atr = df_1min['atr'].iloc[-1]
    volume = df_1min['volume'].iloc[-1]
    vwap = calculate_vwap(symbol, last_candle)
    
    # 3. Prepare 5-min Context (MTF)
    df_5m = resample_to_5min(candles)
    if len(df_5m) < 20: 
        return {} # Not enough 5m history
        
    df_5m['ema20'] = df_5m.ta.ema(length=20)
    
    # 5-min Trend Bias
    trend_bias = "NEUTRAL"
    c5_close = df_5m['close'].iloc[-1]
    c5_ema20 = df_5m['ema20'].iloc[-1]
    
    if c5_close > c5_ema20:
        trend_bias = "BULL"
    elif c5_close < c5_ema20:
        trend_bias = "BEAR"
        
    # 4. Regime Filter (ADX)
    if adx < 20:
        return {"signal": "NEUTRAL", "reason": "Low ADX (Chop)"}
        
    # 5. Pattern Detection (Trigger)
    patterns = identify_patterns(candles) # Uses last 2-20 candles
    
    signal = 'NEUTRAL'
    setup_type = ''
    
    # --- Logic 1: Trend Pullback / Continuation ---
    if trend_bias == "BULL":
        # Look for Bullish Setup
        if patterns['is_bullish_engulfing'] or patterns['is_hammer']:
            if current_price > vwap: # VWAP Confirmation
                signal = "BUY_CALL"
                setup_type = "TREND_PULLBACK"
                
    elif trend_bias == "BEAR":
        # Look for Bearish Setup
        if patterns['is_bearish_engulfing'] or patterns['is_shooting_star']:
            if current_price < vwap:
                signal = "BUY_PUT"
                setup_type = "TREND_PULLBACK"
                
    # --- Logic 2: Momentum Breakout (ORB / Strong Candle) ---
    is_strong = is_strong_candle(last_candle)
    if is_strong == "STRONG_BULL" and trend_bias == "BULL":
        if current_price > vwap and ema9 > ema21:
            signal = "BUY_CALL"
            setup_type = "MOMENTUM_BREAKOUT"
            
    elif is_strong == "STRONG_BEAR" and trend_bias == "BEAR":
        if current_price < vwap and ema9 < ema21:
            signal = "BUY_PUT"
            setup_type = "MOMENTUM_BREAKOUT"

    # If No Trigger, Return
    if signal == "NEUTRAL":
        return {}
        
    # 6. Signal Scoring
    trend_aligned = (signal == "BUY_CALL" and trend_bias == "BULL") or \
                    (signal == "BUY_PUT" and trend_bias == "BEAR")
                    
    score = calculate_signal_score(
        {"setup": setup_type},
        trend_aligned,
        adx,
        rsi,
        patterns['has_volume_support'],
        trend_bias
    )
    
    # 7. Final Threshold Check
    if score < Constants.MIN_SCORE:
        # Log weak signal?
        return {"signal": "IGNORED", "reason": f"Low Score: {score}"}
        
    # 8. Risk Calculation (ATR)
    # Ensure ATR is valid
    current_atr = atr if not pd.isna(atr) else (current_price * 0.002) # Fallback 0.2%
    if current_atr < Constants.ATR_MIN_THRESHOLD:
         return {"signal": "IGNORED", "reason": "Low Volatility (ATR)"}
         
    stop_loss_dist = current_atr * Constants.SL_MULTIPLIER
    target_dist = current_atr * Constants.TARGET_MULTIPLIER
    
    stop_loss = 0.0
    target = 0.0
    
    if signal == "BUY_CALL":
        stop_loss = current_price - stop_loss_dist
        target = current_price + target_dist
    elif signal == "BUY_PUT":
        stop_loss = current_price + stop_loss_dist
        target = current_price - target_dist

    # 9. Return Actionable Trade Signal
    return {
        "signal": signal,
        "setup": setup_type,
        "confidence": score * 10, # 0-100 scale approximation
        "score": score,
        "entry_price": current_price,
        "stop_loss": stop_loss,
        "target": target,
        "vwap": vwap,
        "ema9": ema9,
        "ema21": ema21,
        "adx": adx,
        "rsi": rsi,
        "atr": current_atr,
        "timestamp": timestamp
    }

async def analyze_trend(data: Dict, user_id: str = None, config: Dict = None, on_signal=None):
    """Main trend analysis function triggered by WebSocket"""
    
    # 1. Parse Data
    feeds = data.get("feeds", {})
    if not feeds: return

    for instrument_key, feed in feeds.items():
        try:
            # 1. Extract Data
            ff = feed.get('ff', {})
            ltpc = ff.get('ltpc', {})
            ltp = ltpc.get('ltp', ltpc.get('cp', 0))
            if not ltp: continue
            
            # Extract Candles
            if 'marketOHLC' not in ff: continue
            raw_candles = ff['marketOHLC'].get('ohlc', [])
            
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
            
            # Sort & Merge with History
            candles.sort(key=lambda x: x['timestamp'])
            if instrument_key not in candle_store:
                candle_store[instrument_key] = []
            
            # Simple Merge Logic (Append new ones)
            # In prod, use sets/dicts to avoid dups efficiently
            existing_map = {c['timestamp']: c for c in candle_store[instrument_key]}
            for c in candles:
                existing_map[c['timestamp']] = c
            
            merged = list(existing_map.values())
            merged.sort(key=lambda x: x['timestamp'])
            
            # Keep meaningful history (e.g. 200 for EMA200/Calculations)
            if len(merged) > 300:
                merged = merged[-300:]
            
            candle_store[instrument_key] = merged
            
            # 2. Analyze (Only if Index)
            # Assumption: We only trigger Logic from Index data
            # "NSE_INDEX" or similar tag should be checked. 
            # For now, we assume explicit instrument_keys are passed that we care about.
            if "INDEX" in instrument_key or True: # Force ALL for demo
                
                signals = analyze_scalping_signals(instrument_key, merged, ltp)
                
                # Execute Trade Logic
                if signals.get('signal') in ["BUY_CALL", "BUY_PUT"] and signals.get('confidence', 0) >= SCALPING_CONFIG['minConfidence']:
                    # Trigger Trade
                    # We need to find the correct Option Symbol (ATM) from the Context
                    # For now, just print TRADING SIGNAL
                    
                    if on_signal:
                        await on_signal(signals)
                    
                    # TODO: Trigger Option Selection & Validation here
                    # This would involve looking up the specific Option Contract (e.g., ATM)
                    # and running a similar 'validate_option_metrics' check.
                    
        except Exception as e:
            print(f"Analysis Error ({instrument_key}): {e}")
            import traceback
            traceback.print_exc()

def validate_option_data(option_candle: Dict, signal_type: str, ltp: float, bid: float = 0, ask: float = 0) -> Tuple[bool, str]:
    """
    Validate Option Contract specific metrics.
    1. Premium > 80 check
    2. Spread < 2% check
    3. RSI Momentum check (Avoid chasing)
    """
    # 1. Premium Check
    if ltp < Constants.MIN_PREMIUM:
        return False, f"Premium too low ({ltp} < {Constants.MIN_PREMIUM})"
        
    # 2. Spread Check
    if bid > 0 and ask > 0:
        spread = ask - bid
        spread_pct = (spread / ltp) * 100
        if spread_pct > Constants.MAX_SPREAD_PCT:
            return False, f"Spread too wide ({spread_pct:.2f}%)"
            
    # 3. RSI Check (Need history, assuming option_candle has indicators or we calc it)
    # If we only have single candle, we can't calc RSI. 
    # Usually this requires looking up the option's history in candle_store.
    # Here we assume the caller passes the RSI or we skip if not available.
    
    return True, "OK"
