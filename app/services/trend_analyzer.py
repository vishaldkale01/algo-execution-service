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
candle_store = {}

# Scalping configuration
SCALPING_CONFIG = {
    "targetPercent": 0.3,
    "stopLossPercent": 0.2,
    "trailStopPercent": 0.1,
    "minVolumeRatio": 0.8,
    "minConfidence": 40,
    "minCandles": {
        "oneMin": 5,
        "thirtyMin": 3
    }
}



def analyze_price_action(candles: List[Dict]) -> str:
    """Analyze price action patterns"""
    if len(candles) < 3:
        return "NEUTRAL"
    
    prev2, prev1, current = candles[-3:]
    body_size = abs(current['close'] - current['open'])
    wick_size = abs(max(current['high'] - current['close'], current['open'] - current['low']))
    
    # Detect price action patterns
    if current['close'] > prev1['high'] and current['close'] > prev2['high']:
        return "BREAKOUT"
    if current['close'] < prev1['low'] and current['close'] < prev2['low']:
        return "BREAKDOWN"
    if body_size > wick_size * 2:
        return "STRONG_BULL" if current['close'] > current['open'] else "STRONG_BEAR"
    
    return "NEUTRAL"


def analyze_volume(candles: List[Dict]) -> Dict:
    """Analyze volume profile"""
    periods = 20
    recent_candles = candles[-periods:]
    
    valid_candles = [c for c in recent_candles if isinstance(c.get('volume'), (int, float)) and c['volume'] > 0]
    
    if not valid_candles:
        return {"profile": "NORMAL", "ratio": 1}
    
    avg_volume = sum(c['volume'] for c in valid_candles) / len(valid_candles)
    last_candle = candles[-1]
    last_volume = last_candle.get('volume', avg_volume)
    
    if not isinstance(last_volume, (int, float)) or last_volume <= 0:
        last_volume = avg_volume
    
    volume_ratio = last_volume / avg_volume if avg_volume > 0 else 1
    
    if not (0 < volume_ratio < float('inf')):
        volume_ratio = 1
    
    profile = "VERY_HIGH" if volume_ratio > 1.5 else \
              "HIGH" if volume_ratio > 1.2 else \
              "LOW" if volume_ratio < 0.8 else "NORMAL"
    
    return {"profile": profile, "ratio": volume_ratio}


def analyze_scalping_signals(candles: List[Dict], current_price: float) -> Dict:
    """Analyze scalping signals from candle data using pandas-ta"""
    if not candles:
        return {}
        
    # Convert to DataFrame
    df = pd.DataFrame(candles)
    
    # Ensure numeric columns
    cols = ['open', 'high', 'low', 'close', 'volume']
    for col in cols:
        df[col] = pd.to_numeric(df[col])
        
    # Calculate Indicators
    # EMA
    df['ema9'] = df.ta.ema(length=9)
    df['ema20'] = df.ta.ema(length=20)
    
    # RSI
    df['rsi'] = df.ta.rsi(length=14)
    
    # SuperTrend (returns SUPERT_10_3.0, SUPERTd_10_3.0, SUPERTl_10_3.0, SUPERTs_10_3.0)
    st = df.ta.supertrend(length=10, multiplier=3)
    
    # Check if SuperTrend calculation was successful
    if st is not None:
        df = df.join(st)
        # Identify the direction column (usually SUPERTd_10_3.0)
        st_dir_col = f"SUPERTd_10_3.0"
    else:
        # Fallback if not enough data
        st_dir_col = None

    # Momentum (ROC - Rate of Change)
    df['momentum'] = df.ta.roc(length=10)
    
    # Velocity (Average change over 5 periods)
    df['velocity'] = df['close'].diff().rolling(window=5).mean()

    # Get latest values
    last = df.iloc[-1]
    
    # Determine SuperTrend direction
    # pandas-ta returns 1 for UP, -1 for DOWN
    if st_dir_col and st_dir_col in last:
        st_val = last[st_dir_col]
        st_trend = "UP" if st_val == 1 else "DOWN"
    else:
        st_trend = "NEUTRAL"

    # Price action analysis (keep existing function call)
    price_action = analyze_price_action(candles)
    
    # Candlestick patterns
    patterns = identify_candlestick_patterns(candles)
    latest_pattern = patterns[-1]['pattern'] if patterns else "NONE"

    # Handle NaN values safely
    def get_val(val, default=0):
        return val if pd.notna(val) else default

    return {
        "ema": "BULLISH" if get_val(last['ema9']) > get_val(last['ema20']) else "BEARISH",
        "supertrend": st_trend,
        "rsi": get_val(last['rsi'], 50),
        "momentum": get_val(last['momentum']),
        "velocity": get_val(last['velocity']),
        "priceAction": price_action,
        "pattern": latest_pattern,
        "ema9Value": get_val(last['ema9']),
        "ema20Value": get_val(last['ema20'])
    }


def calculate_scalping_confidence(signals: Dict, volume_ratio: float) -> float:
    """Calculate confidence score for scalping trade"""
    score = 0
    
    # Validate signals
    if not signals or not isinstance(signals.get('rsi'), (int, float)):
        return 0
    
    # Trend alignment (40 points)
    if signals['ema'] == 'BULLISH' and signals['supertrend'] == 'UP':
        score += 40
    elif signals['ema'] == 'BEARISH' and signals['supertrend'] == 'DOWN':
        score += 40
    
    # RSI (20 points)
    if signals['rsi'] < 30 and signals['ema'] == 'BULLISH':
        score += 20
    elif signals['rsi'] > 70 and signals['ema'] == 'BEARISH':
        score += 20
    
    # Price action (20 points)
    if (signals['priceAction'] == 'BREAKOUT' and signals['ema'] == 'BULLISH') or \
       (signals['priceAction'] == 'STRONG_BULL' and signals['supertrend'] == 'UP'):
        score += 20
    elif (signals['priceAction'] == 'BREAKDOWN' and signals['ema'] == 'BEARISH') or \
         (signals['priceAction'] == 'STRONG_BEAR' and signals['supertrend'] == 'DOWN'):
        score += 20
    
    # Volume confirmation (20 points)
    if volume_ratio > SCALPING_CONFIG['minVolumeRatio']:
        volume_score = 20 * min(volume_ratio - 1, 1)
        score += volume_score
    
    return min(score, 100)


def validate_signal_consistency(symbol: str, current_signals: Dict) -> bool:
    """Validate signal consistency across time"""
    now = datetime.now().timestamp() * 1000
    
    previous = previous_signals_cache.get(symbol)
    previous_signals_cache[symbol] = {
        "signals": current_signals,
        "timestamp": now
    }
    
    if not previous or (now - previous['timestamp']) > CACHE_EXPIRY:
        return False
    
    prev_signals = previous['signals']
    
    # Compare signals
    checks = {
        "emaTrend": current_signals['ema'] == prev_signals['ema'],
        "supertrendConsistent": current_signals['supertrend'] == prev_signals['supertrend'],
        "rsiTrending": (
            (current_signals['ema'] == 'BULLISH' and current_signals['rsi'] > prev_signals['rsi']) or
            (current_signals['ema'] == 'BEARISH' and current_signals['rsi'] < prev_signals['rsi'])
        ),
        "momentumContinuation": (
            (current_signals['ema'] == 'BULLISH' and current_signals['momentum'] > prev_signals['momentum']) or
            (current_signals['ema'] == 'BEARISH' and current_signals['momentum'] < prev_signals['momentum'])
        ),
        "velocityAligned": (current_signals['velocity'] * prev_signals['velocity']) > 0
    }
    
    consistent = (checks['emaTrend'] and checks['supertrendConsistent']) or \
                 sum(checks.values()) >= 3
    
    return consistent


async def should_open_new_trade(symbol: str, user_id: str = None) -> bool:
    """Check if we can open a new trade for this symbol"""
    db = await get_database()
    collection = db.virtual_trades
    
    query = {"symbol": symbol, "status": "OPEN"}
    if user_id:
        query["user_id"] = user_id
        
    open_trade = await collection.find_one(query)
    return open_trade is None


async def update_existing_trades(symbol: str, current_price: float, signals: Dict, user_id: str = None, trade_mode: str = "VIRTUAL", access_token: str = None):
    """Update existing open trades with trailing stops and exit conditions"""
    db = await get_database()
    collection = db.virtual_trades
    
    query = {"symbol": symbol, "status": "OPEN"}
    if user_id:
        query["user_id"] = user_id
        
    open_trades = await collection.find(query).to_list(length=100)
    
    for trade in open_trades:
        # Dynamic trailing stop
        trail_stop = SCALPING_CONFIG['trailStopPercent'] * 1.5 if abs(signals['velocity']) > 1 else SCALPING_CONFIG['trailStopPercent']
        
        # Update trailing stop
        if trade['tradeType'] == 'CALL' and current_price > trade['entryPrice']:
            new_stop = current_price * (1 - trail_stop / 100)
            if new_stop > trade['stopLoss']:
                await collection.update_one(
                    {"_id": trade['_id']},
                    {"$set": {"stopLoss": new_stop}}
                )
        elif trade['tradeType'] == 'PUT' and current_price < trade['entryPrice']:
            new_stop = current_price * (1 + trail_stop / 100)
            if new_stop < trade['stopLoss']:
                await collection.update_one(
                    {"_id": trade['_id']},
                    {"$set": {"stopLoss": new_stop}}
                )
        
        # Check exit conditions
        target_hit = (
            (trade['tradeType'] == 'CALL' and current_price >= trade['targetPrice']) or
            (trade['tradeType'] == 'PUT' and current_price <= trade['targetPrice'])
        )
        
        should_exit = target_hit or (
            (trade['tradeType'] == 'CALL' and (
                current_price <= trade['stopLoss'] or
                signals['supertrend'] == 'DOWN' or
                (signals['velocity'] < -0.5 and signals['momentum'] < -0.5)
            )) or
            (trade['tradeType'] == 'PUT' and (
                current_price >= trade['stopLoss'] or
                signals['supertrend'] == 'UP' or
                (signals['velocity'] > 0.5 and signals['momentum'] > 0.5)
            ))
        )
        
        if should_exit:
            pnl = (current_price - trade['entryPrice']) * trade['quantity'] if trade['tradeType'] == 'CALL' \
                  else (trade['entryPrice'] - current_price) * trade['quantity']
            
            # LIVE TRADE EXIT
            if trade_mode == "LIVE" and access_token and trade.get("order_id"):
                # Place SELL order to exit
                import httpx
                url = "https://api.upstox.com/v2/order/place"
                headers = {
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {access_token}"
                }
                payload = {
                    "quantity": trade['quantity'],
                    "product": "D",
                    "validity": "DAY",
                    "price": 0,
                    "tag": "algo_exit",
                    "instrument_token": trade['instrument_token'],
                    "order_type": "MARKET",
                    "transaction_type": "SELL", # Exit Long position
                    "disclosed_quantity": 0,
                    "trigger_price": 0,
                    "is_amo": False
                }
                async with httpx.AsyncClient() as client:
                    try:
                        resp = await client.post(url, json=payload, headers=headers)
                        if resp.status_code == 200:
                            print(f"✅ Live Trade Exited for {user_id}")
                        else:
                            print(f"❌ Live Exit Failed: {resp.text}")
                    except Exception as e:
                        print(f"❌ Live Exit Error: {e}")

            await collection.update_one(
                {"_id": trade['_id']},
                {"$set": {
                    "status": "CLOSED",
                    "exitPrice": current_price,
                    "exitTime": datetime.now(),
                    "pnl": pnl,
                    "exitReason": "TARGET_HIT" if target_hit else "STOP_OR_SIGNAL"
                }}
            )
            
            print(f"Trade closed for {symbol}: PNL={pnl}, Entry={trade['entryPrice']}, Exit={current_price}")


async def select_strike_rate(symbol: str, spot_price: float, transaction_type: str, capital: float) -> str:
    """Select best strike rate based on capital"""
    # Simplified logic for BankNifty (Step 100) and Nifty (Step 50)
    step = 100 if "Bank" in symbol else 50
    atm_strike = round(spot_price / step) * step
    
    # Determine strike based on capital (simplified heuristic)
    # High capital (> 50k) -> ITM
    # Medium capital (10k-50k) -> ATM
    # Low capital (< 10k) -> OTM
    
    offset = 0
    if capital > 50000:
        offset = -step if transaction_type == 'CALL' else step  # ITM
    elif capital < 10000:
        offset = step if transaction_type == 'CALL' else -step   # OTM
    
    selected_strike = atm_strike + offset
    
    # Construct instrument key (This requires mapping or API lookup in real app)
    # For now, returning a placeholder format that needs to be resolved to actual instrument_token
    # In a real scenario, we would call Upstox Option Chain API here.
    return f"{symbol}{selected_strike}{transaction_type}"

async def place_live_order(trade_data: Dict, user_id: str, access_token: str):
    """Place actual order on Upstox"""
    import httpx
    url = "https://api.upstox.com/v2/order/place"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}"
    }
    
    # Map trade_data to Upstox payload
    payload = {
        "quantity": trade_data['quantity'],
        "product": "D",  # Delivery/Carry Forward
        "validity": "DAY",
        "price": 0,  # Market Order
        "tag": "algo_trade",
        "instrument_token": trade_data['instrument_token'], # Needs actual token
        "order_type": "MARKET",
        "transaction_type": "BUY", # We always BUY options (Long Call or Long Put)
        "disclosed_quantity": 0,
        "trigger_price": 0,
        "is_amo": False
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=payload, headers=headers)
            if response.status_code == 200:
                print(f"✅ Live Order Placed for {user_id}: {response.json()}")
                return response.json()['data']['order_id']
            else:
                print(f"❌ Live Order Failed: {response.text}")
        except Exception as e:
            print(f"❌ Live Order Error: {e}")
    return None

async def analyze_trend(data: Dict, user_id: str = None, config: Dict = None):
    """Main trend analysis function"""
    if 'feeds' not in data:
        return
    
    # Default config if none provided
    user_config = config or {}
    trade_mode = user_config.get("trade_mode", "VIRTUAL") # VIRTUAL or LIVE
    capital = user_config.get("capital", 100000)
    access_token = user_config.get("access_token") # Needed for live orders
    
    for symbol, feed in data['feeds'].items():
        try:
            if 'ff' not in feed or 'indexFF' not in feed['ff']:
                continue
            
            index_ff = feed['ff']['indexFF']
            if 'marketOHLC' not in index_ff or 'ohlc' not in index_ff['marketOHLC']:
                continue
            
            current_price = index_ff['ltpc']['ltp']
            
            # Process candles
            candles = []
            for c in index_ff['marketOHLC']['ohlc']:
                if c['interval'] in ['I1', 'I30']:
                    candles.append({
                        'timestamp': datetime.fromtimestamp(int(c['ts']) / 1000),
                        'open': c['open'],
                        'high': c['high'],
                        'low': c['low'],
                        'close': c['close'],
                        'volume': float(c.get('volume', 0)),
                        'interval': c['interval']
                    })
            
            candles.sort(key=lambda x: x['timestamp'])
            
            # Store candles (User specific storage would be better, but using global for now)
            # To make it user-specific, we'd need a nested dict: candle_store[user_id][symbol]
            # For simplicity in this migration step, assuming one user or shared data is acceptable for analysis
            # BUT for multi-user, we should really separate. 
            # However, market data is same for all users. So global candle_store is actually CORRECT.
            
            if symbol not in candle_store:
                candle_store[symbol] = []
            
            existing_timestamps = {c['timestamp'] for c in candle_store[symbol]}
            for candle in candles:
                if candle['timestamp'] not in existing_timestamps:
                    candle_store[symbol].append(candle)
            
            # Limit memory
            if len(candle_store[symbol]) > 500:
                candle_store[symbol] = candle_store[symbol][-500:]
            
            unique_candles = candle_store[symbol]
            
            min_required = 3 if any(c['interval'] == 'I30' for c in unique_candles) else 5
            if len(unique_candles) < min_required:
                continue
            
            # Analyze signals
            signals = analyze_scalping_signals(unique_candles, current_price)
            volume_data = analyze_volume(unique_candles)
            confidence = calculate_scalping_confidence(signals, volume_data['ratio'])
            
            # Check conditions
            # Pass user_id to check if THIS user has an open trade
            can_trade = await should_open_new_trade(symbol, user_id)
            signals_consistent = validate_signal_consistency(symbol, signals)
            
            # Execute trade if conditions met
            if (confidence >= SCALPING_CONFIG['minConfidence'] and 
                can_trade and signals_consistent):
                
                trade_type = 'CALL' if (signals['supertrend'] == 'UP' and signals['ema'] == 'BULLISH') else 'PUT'
                
                # Validation
                # Check for supportive patterns
                bullish_patterns = ['Hammer', 'Bullish Engulfing']
                bearish_patterns = ['Shooting Star', 'Bearish Engulfing']
                
                valid = (
                    current_price > 0 and
                    ((trade_type == 'CALL' and 
                      signals['ema'] == 'BULLISH' and 
                      signals['supertrend'] == 'UP' and
                      (signals['pattern'] in bullish_patterns or signals['priceAction'] in ['BREAKOUT', 'STRONG_BULL'])) or
                     (trade_type == 'PUT' and 
                      signals['ema'] == 'BEARISH' and 
                      signals['supertrend'] == 'DOWN' and
                      (signals['pattern'] in bearish_patterns or signals['priceAction'] in ['BREAKDOWN', 'STRONG_BEAR'])))
                )
                
                if valid:
                    # Select Strike Rate
                    strike_instrument = await select_strike_rate(symbol, current_price, trade_type, capital)
                    
                    db = await get_database()
                    collection = db.virtual_trades
                    
                    new_trade = {
                        "user_id": user_id, # Link trade to user
                        "symbol": symbol,
                        "instrument_token": strike_instrument, # The actual option contract
                        "tradeType": trade_type,
                        "entryPrice": current_price, # This is Spot Price. Real entry price would be Option Price.
                        "targetPrice": current_price * (1 + SCALPING_CONFIG['targetPercent'] / 100) if trade_type == 'CALL' 
                                      else current_price * (1 - SCALPING_CONFIG['targetPercent'] / 100),
                        "stopLoss": current_price * (1 - SCALPING_CONFIG['stopLossPercent'] / 100) if trade_type == 'CALL'
                                   else current_price * (1 + SCALPING_CONFIG['stopLossPercent'] / 100),
                        "quantity": 15 if "Bank" in symbol else 50, # Default lot size
                        "status": "OPEN",
                        "mode": trade_mode,
                        "entryTime": datetime.now(),
                        "signals": {**signals, "confidence": confidence, "volumeRatio": volume_data['ratio']}
                    }
                    
                    # LIVE TRADE EXECUTION
                    if trade_mode == "LIVE" and access_token:
                        order_id = await place_live_order(new_trade, user_id, access_token)
                        if order_id:
                            new_trade["order_id"] = order_id
                            new_trade["status"] = "OPEN" # Confirmed
                        else:
                            new_trade["status"] = "FAILED"
                    
                    await collection.insert_one(new_trade)
                    print(f"New {trade_mode} trade for {user_id} on {symbol}: {trade_type} @ {current_price}")
            
            # Update existing trades
            await update_existing_trades(symbol, current_price, signals, user_id, trade_mode, access_token)
            
        except Exception as e:
            print(f"Error analyzing {symbol}: {e}")
