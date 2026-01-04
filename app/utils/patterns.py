from typing import List, Dict, Any, Tuple

def get_candle_metrics(candle: Dict[str, Any]) -> Dict[str, float]:
    """
    Calculate basic metrics for a single candle.
    Returns:
        Dict with keys: 'body', 'upper_wick', 'lower_wick', 'total_range', 'is_green'
    """
    open_p = candle['open']
    close_p = candle['close']
    high_p = candle['high']
    low_p = candle['low']

    body = abs(close_p - open_p)
    total_range = high_p - low_p
    is_green = close_p > open_p
    
    if is_green:
        upper_wick = high_p - close_p
        lower_wick = open_p - low_p
    else:
        upper_wick = high_p - open_p
        lower_wick = close_p - low_p

    return {
        "body": body,
        "upper_wick": upper_wick,
        "lower_wick": lower_wick,
        "total_range": total_range,
        "is_green": is_green,
        "high": high_p,
        "low": low_p,
        "close": close_p,
        "open": open_p
    }

def is_strong_candle(candle: Dict[str, Any]) -> str:
    """
    Check if candle is STRONG_BULL or STRONG_BEAR.
    Definition:
    - Body >= 60% of Total Range
    - Bullish: Close in top 25% of range
    - Bearish: Close in bottom 25% of range
    """
    m = get_candle_metrics(candle)
    if m['total_range'] == 0:
        return "NEUTRAL"

    body_pct = m['body'] / m['total_range']
    if body_pct < 0.6:
        return "NEUTRAL"
    
    # Check close position relative to range
    # Position: (Close - Low) / Range
    close_pos = (m['close'] - m['low']) / m['total_range']

    if m['is_green'] and close_pos >= 0.75:
        return "STRONG_BULL"
    elif not m['is_green'] and close_pos <= 0.25:
        return "STRONG_BEAR"
    
    return "NEUTRAL"

def is_hammer(candle: Dict[str, Any]) -> bool:
    """
    Bullish Hammer:
    - Lower Wick >= 2 * Body
    - Upper Wick <= 0.3 * Body (Tiny/No upper wick)
    - Body <= 0.3 * Total Range (Small body)
    """
    m = get_candle_metrics(candle)
    if m['total_range'] == 0: return False

    return (
        m['lower_wick'] >= 2 * m['body'] and
        m['upper_wick'] <= 0.3 * m['body'] and
        m['body'] <= 0.3 * m['total_range']
    )

def is_shooting_star(candle: Dict[str, Any]) -> bool:
    """
    Bearish Shooting Star:
    - Upper Wick >= 2 * Body
    - Lower Wick <= 0.3 * Body (Tiny/No lower wick)
    - Body <= 0.3 * Total Range (Small body)
    """
    m = get_candle_metrics(candle)
    if m['total_range'] == 0: return False

    return (
        m['upper_wick'] >= 2 * m['body'] and
        m['lower_wick'] <= 0.3 * m['body'] and
        m['body'] <= 0.3 * m['total_range']
    )

def is_bullish_engulfing(current: Dict[str, Any], previous: Dict[str, Any]) -> bool:
    """
    Bullish Engulfing:
    - Previous: RED
    - Current: GREEN
    - Current Open <= Previous Close
    - Current Close >= Previous Open
    """
    prev_m = get_candle_metrics(previous)
    curr_m = get_candle_metrics(current)

    if prev_m['is_green'] or not curr_m['is_green']:
        return False
    
    # Basic Engulfing Logic
    return (
        curr_m['open'] <= prev_m['close'] and 
        curr_m['close'] >= prev_m['open']
    )

def is_bearish_engulfing(current: Dict[str, Any], previous: Dict[str, Any]) -> bool:
    """
    Bearish Engulfing:
    - Previous: GREEN
    - Current: RED
    - Current Open >= Previous Close
    - Current Close <= Previous Open
    """
    prev_m = get_candle_metrics(previous)
    curr_m = get_candle_metrics(current)

    if not prev_m['is_green'] or curr_m['is_green']:
        return False
    
    return (
        curr_m['open'] >= prev_m['close'] and
        curr_m['close'] <= prev_m['open']
    )

def is_inside_bar(current: Dict[str, Any], previous: Dict[str, Any]) -> bool:
    """
    Inside Bar:
    - Current High < Previous High
    - Current Low > Previous Low
    """
    return (
        current['high'] < previous['high'] and
        current['low'] > previous['low']
    )

def is_range_compression(current: Dict[str, Any], recent_candles: List[Dict[str, Any]]) -> bool:
    """
    Range Compression (Consolidation):
    - Current Range < 50% of Average Range of last 5 candles
    """
    if not recent_candles:
        return False
    
    curr_range = current['high'] - current['low']
    
    # Calculate Avg Range of last N candles (excluding current)
    ranges = [(c['high'] - c['low']) for c in recent_candles]
    avg_range = sum(ranges) / len(ranges)
    
    if avg_range == 0: return False

    return curr_range < 0.5 * avg_range

def check_volume_breakout(current: Dict[str, Any], recent_candles: List[Dict[str, Any]], multiplier: float = 1.2) -> bool:
    """
    Fake Breakout Filter:
    - Current Volume > Multiplier * SMA(Volume, 20)
    """
    if len(recent_candles) < 5: # Need some history
        return True # Default to True if not enough data to filter, or handle as neutral
    
    # Calculate SMA Volume
    vols = [float(c.get('volume', 0)) for c in recent_candles]
    avg_vol = sum(vols) / len(vols)
    
    curr_vol = float(current.get('volume', 0))
    
    return curr_vol > multiplier * avg_vol

def identify_patterns(candles: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Main aggregator function to check for patterns on the latest candle.
    Returns dictionary with detected pattern flags.
    """
    if len(candles) < 2:
        return {}
    
    current = candles[-1]
    previous = candles[-2]
    
    # Recent history for averages (last 5 for range, last 20 for volume)
    # Exclude current candle for average calculations
    history_5 = candles[-6:-1] if len(candles) >= 6 else candles[:-1]
    history_20 = candles[-21:-1] if len(candles) >= 21 else candles[:-1]

    result = {
        "strong_candle": is_strong_candle(current),
        "is_hammer": is_hammer(current),
        "is_shooting_star": is_shooting_star(current),
        "is_bullish_engulfing": is_bullish_engulfing(current, previous),
        "is_bearish_engulfing": is_bearish_engulfing(current, previous),
        "is_inside_bar": is_inside_bar(current, previous),
        "is_range_compression": is_range_compression(current, history_5),
        "has_volume_support": check_volume_breakout(current, history_20, multiplier=1.2)
    }
    
    return result
