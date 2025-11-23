from typing import List, Dict, Any
from datetime import datetime
from app.models.trade import VirtualTrade, TradeType, TradeStatus
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


def calculate_ema(prices: List[float], period: int) -> float:
    """Calculate Exponential Moving Average"""
    if len(prices) < period:
        return prices[-1] if prices else 0
    
    k = 2 / (period + 1)
    ema = prices[0]
    for price in prices[1:]:
        ema = price * k + ema * (1 - k)
    return ema


def calculate_rsi(prices: List[float], period: int = 14) -> float:
    """Calculate Relative Strength Index"""
    if len(prices) < period + 1:
        return 50
    
    avg_gain = 0
    avg_loss = 0
    
    # Initial RSI calculation
    for i in range(1, period + 1):
        diff = prices[i] - prices[i - 1]
        if diff > 0:
            avg_gain += diff
        else:
            avg_loss -= diff
    
    avg_gain /= period
    avg_loss /= period
    
    # Wilder's smoothing
    for i in range(period + 1, len(prices)):
        diff = prices[i] - prices[i - 1]
        avg_gain = (avg_gain * 13 + (diff if diff > 0 else 0)) / 14
        avg_loss = (avg_loss * 13 + (-diff if diff < 0 else 0)) / 14
    
    if avg_loss == 0:
        return 100
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calculate_macd(prices: List[float]) -> float:
    """Calculate MACD"""
    ema12 = calculate_ema(prices, 12)
    ema26 = calculate_ema(prices, 26)
    return ema12 - ema26


def calculate_supertrend(candles: List[Dict], period: int = 10, multiplier: int = 3) -> Dict:
    """Calculate SuperTrend indicator"""
    highs = [c['high'] for c in candles]
    lows = [c['low'] for c in candles]
    closes = [c['close'] for c in candles]
    
    # Calculate ATR
    tr = []
    for i, h in enumerate(highs):
        if i == 0:
            tr.append(h - lows[i])
        else:
            previous_close = closes[i - 1]
            tr.append(max(
                h - lows[i],
                abs(h - previous_close),
                abs(lows[i] - previous_close)
            ))
    
    atr = sum(tr[-period:]) / period
    
    # Current SuperTrend
    current_close = closes[-1]
    upper_band = current_close + (multiplier * atr)
    lower_band = current_close - (multiplier * atr)
    
    return {
        "upperBand": upper_band,
        "lowerBand": lower_band,
        "trend": "UP" if current_close > lower_band else "DOWN"
    }


def calculate_momentum(prices: List[float], period: int = 10) -> float:
    """Calculate price momentum"""
    if len(prices) < period:
        return 0
    return ((prices[-1] - prices[-period]) / prices[-period]) * 100


def calculate_velocity(prices: List[float], period: int = 5) -> float:
    """Calculate price velocity (rate of change)"""
    if len(prices) < period:
        return 0
    
    changes = []
    for i in range(1, period):
        changes.append(prices[-i] - prices[-i - 1])
    
    return sum(changes) / period


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
    """Analyze scalping signals from candle data"""
    prices = [c['close'] for c in candles]
    
    # Short-term indicators
    ema9 = calculate_ema(prices, 9)
    ema20 = calculate_ema(prices, 20)
    rsi = calculate_rsi(prices, 14)
    supertrend = calculate_supertrend(candles)
    momentum = calculate_momentum(prices)
    velocity = calculate_velocity(prices)
    
    # Price action analysis
    price_action = analyze_price_action(candles)
    
    return {
        "ema": "BULLISH" if ema9 > ema20 else "BEARISH",
        "supertrend": supertrend["trend"],
        "rsi": rsi,
        "momentum": momentum,
        "velocity": velocity,
        "priceAction": price_action,
        "ema9Value": ema9,
        "ema20Value": ema20
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
                valid = (
                    current_price > 0 and
                    ((trade_type == 'CALL' and signals['ema'] == 'BULLISH' and signals['supertrend'] == 'UP') or
                     (trade_type == 'PUT' and signals['ema'] == 'BEARISH' and signals['supertrend'] == 'DOWN'))
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
