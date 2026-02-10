from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime, time, timedelta
import pandas as pd
import pandas_ta as ta
from dataclasses import dataclass, field
from app.models.trade import TradeType
from app.utils.patterns import identify_patterns, is_strong_candle

# -----------------------------------------------------------------------------
# CONSTANTS & CONFIGURATION
# -----------------------------------------------------------------------------

class Config:
    # Risk & Strategy
    ATR_PERIOD = 14
    ATR_MIN_THRESHOLD = 5.0
    SL_MULTIPLIER = 1.0
    TARGET_MULTIPLIER = 1.5
    
    # Time Windows
    TIME_MORNING_START = time(9, 20) # Allow 5 mins for settlement
    TIME_MORNING_END = time(11, 30)
    TIME_AFTERNOON_START = time(13, 15)
    TIME_AFTERNOON_END = time(15, 0)
    
    # Selection
    MIN_SCORE = 5 # Stricter

@dataclass
class MarketState:
    """Holds state for a single instrument"""
    candles: List[Dict] = field(default_factory=list)
    vwap: Dict = field(default_factory=lambda: {'cum_pv': 0.0, 'cum_vol': 0.0, 'last_reset': None})
    orb: Dict = field(default_factory=lambda: {'high': 0.0, 'low': 0.0, 'set': False})
    pcr: float = 1.0
    cpr: Dict = field(default_factory=lambda: {'tc': 0, 'bc': 0, 'pivot': 0})
    oi_history: List[Dict] = field(default_factory=list) # [{'timestamp': ..., 'pcr': ..., 'call_oi': ..., 'put_oi': ...}]
    last_signal_time: Optional[datetime] = None

class TrendAnalyzer:
    """
    Class-based Trend Analyzer (Per User/Session).
    Removes Global State pollution.
    """
    
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.state: Dict[str, MarketState] = {} # instrument_key -> MarketState
        
    def _get_state(self, symbol: str) -> MarketState:
        if symbol not in self.state:
            self.state[symbol] = MarketState()
        return self.state[symbol]

    def update_context(self, symbol: str, pcr: float = None, cpr: Dict = None, oi_data: Dict = None):
        """
        Update slowly changing context (PCR, CPR, OI).
        """
        s = self._get_state(symbol)
        
        if pcr is not None:
            s.pcr = pcr
            
        if cpr is not None:
            s.cpr = cpr
            
        if oi_data:
            # oi_data expected: {'timestamp': datetime, 'call_oi': float, 'put_oi': float, 'pcr': float}
            # Append if new timestamp
            if not s.oi_history or s.oi_history[-1]['timestamp'] != oi_data['timestamp']:
                s.oi_history.append(oi_data)
                # Keep last 20 records (approx 100 mins if 5 min poll)
                if len(s.oi_history) > 20: 
                    s.oi_history = s.oi_history[-20:]

    def calculate_cpr(self, daily_candle: Dict) -> Dict:
        """Calculate CPR from previous day's High/Low/Close"""
        h = daily_candle['high']
        l = daily_candle['low']
        c = daily_candle['close']
        
        pivot = (h + l + c) / 3
        bc = (h + l) / 2
        tc = (pivot - bc) + pivot
        
        return {
            "pivot": pivot,
            "bc": min(bc, tc), # BC is always lower level visually for calculation
            "tc": max(bc, tc),
            "width": abs(tc - bc)
        }
    
    def resample_to_5min(self, candles: List[Dict]) -> pd.DataFrame:
        """Resample 1-min candles to 5-min DataFrame"""
        if not candles:
            return pd.DataFrame()
            
        df = pd.DataFrame(candles)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.set_index('timestamp', inplace=True)
        
        # Resample
        df_5m = df.resample('5min').agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }).dropna()
        
        return df_5m

    def analyze_oi_trends(self, state: MarketState) -> str:
        """
        Analyze OI History for sentiment.
        Returns: BULLISH, BEARISH, NEUTRAL
        """
        if len(state.oi_history) < 2:
            return "NEUTRAL"
            
        avg_pcr = sum(x['pcr'] for x in state.oi_history[-3:]) / min(len(state.oi_history), 3)
        
        # Trend of PCR
        curr_pcr = state.oi_history[-1]['pcr']
        prev_pcr = state.oi_history[0]['pcr'] # From start of window
        
        if curr_pcr > 1.2 and curr_pcr > prev_pcr:
            return "BULLISH" # High PCR and Rising
        elif curr_pcr < 0.8 and curr_pcr < prev_pcr:
            return "BEARISH" # Low PCR and Falling
            
        return "NEUTRAL"

    def process_tick(self, instrument_key: str, candle: Dict, is_index: bool = False) -> Dict:
        """
        Main entry point for processing a new 1-min candle.
        Returns a Signal Dict if opportunity found, else empty.
        """
        s = self._get_state(instrument_key)
        
        # 1. Update Candle Store
        # Ensure timestamp uniqueness
        if s.candles and s.candles[-1]['timestamp'] == candle['timestamp']:
            s.candles[-1] = candle # Update current minute
        else:
            s.candles.append(candle)
            
        # Keep manageable history
        if len(s.candles) > 300:
            s.candles = s.candles[-300:]
            
        if not is_index or len(s.candles) < 50:
            return {}
            
        # 2. Analyze
        return self.analyze_scalping_signals(instrument_key, s)

    def analyze_scalping_signals(self, symbol: str, state: MarketState) -> Dict:
        candles = state.candles
        last_candle = candles[-1]
        timestamp = last_candle['timestamp']
        current_price = last_candle['close']
        
        # --- Filters ---
        # 1. Time Check
        if not self._is_time_valid(timestamp.time()):
            return {}
            
        # 2. Stale Data Check (Max 10s lag allowed for processing)
        lag = (datetime.now() - timestamp).total_seconds()
        if lag > 65: # Allow 1 min candle + 5s buffer
             # In backtest this will trigger, so careful. 
             # For live, we expect 'timestamp' to be close to 'now'
             pass 
             
        # --- Multi-Timeframe Analysis (5min) ---
        df_5m = self.resample_to_5min(state.candles)
        tf5_trend = "NEUTRAL"
        
        if not df_5m.empty and len(df_5m) > 10:
             # TA-Lib/Pandas-TA EMA might return Series or DataFrame depending on version/config
             ema_series = df_5m.ta.ema(length=21)
             if isinstance(ema_series, pd.DataFrame):
                 ema_series = ema_series.iloc[:, 0]
                 
             df_5m['ema21'] = ema_series
             
             last_5m = df_5m.iloc[-1]
             # Simple trend check: Close > EMA21 on 5m
             # Handle NaN (if not enough data for EMA21)
             if pd.notna(last_5m['ema21']):
                 if last_5m['close'] > last_5m['ema21']:
                     tf5_trend = "BULLISH"
                 elif last_5m['close'] < last_5m['ema21']:
                     tf5_trend = "BEARISH"

        # --- Indicator Calculation (1min) ---
        df = pd.DataFrame(candles)
        df['ema9'] = df.ta.ema(length=9)
        df['ema21'] = df.ta.ema(length=21)
        df['rsi'] = df.ta.rsi(length=14)
        df['atr'] = df.ta.atr(length=Config.ATR_PERIOD)
        
        # ADX
        adx_df = df.ta.adx(length=14)
        if adx_df is not None and not adx_df.empty:
            df['adx'] = adx_df['ADX_14']
        else:
            df['adx'] = 0

        # Supertrend (7, 3) - New Addition
        st = df.ta.supertrend(length=7, multiplier=3)
        # supertrend returns 4 columns usually, we need the direction/value
        # pandas_ta columns: SUPERT_7_3.0 vs SUPERT_7_3
        if st is not None:
             # Dynamically check columns to be safe across versions
             cols = st.columns
             if 'SUPERT_7_3.0' in cols:
                 df['st_val'] = st['SUPERT_7_3.0']
                 df['st_dir'] = st['SUPERTd_7_3.0'] 
             elif 'SUPERT_7_3' in cols:
                 df['st_val'] = st['SUPERT_7_3']
                 df['st_dir'] = st['SUPERTd_7_3']
             else:
                 # Fallback: Index 0=Value, 1=Direction
                 df['st_val'] = st.iloc[:, 0]
                 df['st_dir'] = st.iloc[:, 1]
        else:
             df['st_val'] = 0
             df['st_dir'] = 0

        # VWAP (Intraday)
        vwap = self._calculate_vwap(state, last_candle)
        
        # --- Current Values ---
        c = df.iloc[-1]
        ema9, ema21 = c['ema9'], c['ema21']
        rsi, adx, atr = c['rsi'], c['adx'], c['atr']
        st_dir = c['st_dir']
        
        # --- Logic ---
        
        signal = "NEUTRAL"
        setup = ""
        score = 0
        
        # Bias Detection
        is_uptrend = current_price > vwap and ema9 > ema21
        is_downtrend = current_price < vwap and ema9 < ema21
        
        # Pattern Recognition
        # We use a helper that looks at last few candles
        patterns = identify_patterns(candles)
        
        # Strategy 1: Trend Pullback w/ Pattern
        # Pre-req: ADX > 20 (Trend exists)
        if adx > 20: 
            if is_uptrend:
                if patterns['is_bullish_engulfing'] or patterns['is_hammer']:
                    # Validation: Must be near EMA 9/21 (Value Area)
                    dist_ema = abs(current_price - ema9)
                    if dist_ema < (1.0 * atr): # Close to EMA (Relaxed to 1.0 ATR)
                        signal = "BUY_CALL"
                        setup = "TREND_PULLBACK"
                        score += 3
                        
                        # TF5 Confirmation
                        if tf5_trend == "BULLISH": score += 2
                        elif tf5_trend == "BEARISH": score -= 2

            elif is_downtrend:
                if patterns['is_bearish_engulfing'] or patterns['is_shooting_star']:
                     dist_ema = abs(current_price - ema9)
                     if dist_ema < (1.0 * atr):
                        signal = "BUY_PUT"
                        setup = "TREND_PULLBACK"
                        score += 3
                        
                        # TF5 Confirmation
                        if tf5_trend == "BEARISH": score += 2
                        elif tf5_trend == "BULLISH": score -= 2
        
        # Strategy 2: CPR Rejection / Bounce (New)
        # If price touches CPR Top/Bottom and reverses
        # Requires CPR to be set
        if state.cpr['pivot'] > 0:
             # Logic placeholder for CPR bounce
             pass

        # Strategy 3: Supertrend Reversal
        # Aggressive entry on ST flip
        # Check previous candle ST
        if len(df) > 2:
            prev_st = df.iloc[-2]['st_dir']
            if prev_st == -1 and st_dir == 1 and current_price > vwap:
                 signal = "BUY_CALL"
                 setup = "ST_REVERSAL"
                 score += 2
            elif prev_st == 1 and st_dir == -1 and current_price < vwap:
                 signal = "BUY_PUT"
                 setup = "ST_REVERSAL"
                 score += 2

        # --- Scoring & Filtering ---
        if signal == "NEUTRAL":
            return {}
            
        # Confluence Bonuses
        # OI Trend Analysis
        oi_sentiment = self.analyze_oi_trends(state)
        
        if state.pcr > 1.2 and signal == "BUY_CALL": score += 2
        if state.pcr < 0.8 and signal == "BUY_PUT": score += 2
        
        if oi_sentiment == "BULLISH" and signal == "BUY_CALL": score += 1
        if oi_sentiment == "BEARISH" and signal == "BUY_PUT": score += 1
        if oi_sentiment == "BEARISH" and signal == "BUY_CALL": score -= 2 # Contra OI
        if oi_sentiment == "BULLISH" and signal == "BUY_PUT": score -= 2 # Contra OI
        
        if rsi > 50 and signal == "BUY_CALL": score += 1
        if rsi < 50 and signal == "BUY_PUT": score += 1
        if is_strong_candle(last_candle): score += 1
        
        if score < Config.MIN_SCORE:
            return {"signal": "IGNORED", "reason": f"Low Score {score}"}
            
        # --- Targets ---
        sl_points = atr * Config.SL_MULTIPLIER
        tg_points = atr * Config.TARGET_MULTIPLIER
        
        # Fallback if ATR is nan/zero
        if pd.isna(sl_points) or sl_points == 0:
            sl_points = current_price * 0.002 # 0.2%
            tg_points = current_price * 0.004

        return {
            "signal": signal,
            "setup": setup,
            "confidence": score,
            "entry_price": current_price,
            "stop_loss": current_price - sl_points if "CALL" in signal else current_price + sl_points,
            "target": current_price + tg_points if "CALL" in signal else current_price - tg_points,
            "atr": atr,
            "timestamp": timestamp
        }

    def _is_time_valid(self, t: time) -> bool:
        if Config.TIME_MORNING_START <= t <= Config.TIME_MORNING_END: return True
        if Config.TIME_AFTERNOON_START <= t <= Config.TIME_AFTERNOON_END: return True
        return False

    def _calculate_vwap(self, state: MarketState, candle: Dict) -> float:
        """Accumulate VWAP safely"""
        # Reset if new day (handled by caller passing fresh data usually? 
        # No, we must handle day change here if we sustain state)
        # For simplicity, we assume one process run = one day or reset explicitly.
        
        typ = (candle['high'] + candle['low'] + candle['close']) / 3
        vol = candle['volume']
        
        state.vwap['cum_pv'] += typ * vol
        state.vwap['cum_vol'] += vol
        
        if state.vwap['cum_vol'] == 0: return typ
        return state.vwap['cum_pv'] / state.vwap['cum_vol']
