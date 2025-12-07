from typing import List, Dict, Any

def identify_candlestick_patterns(candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if len(candles) < 2:
        return []

    patterns = []

    def is_doji(candle):
        return abs(candle['close'] - candle['open']) <= (candle['high'] - candle['low']) * 0.1

    def is_hammer(candle):
        return (candle['close'] - candle['open']) / (candle['high'] - candle['low']) > 0.5 and \
               (candle['high'] - candle['close']) > (candle['open'] - candle['low']) * 2

    def is_shooting_star(candle):
        return (candle['open'] - candle['close']) / (candle['high'] - candle['low']) > 0.5 and \
               (candle['high'] - candle['open']) > (candle['close'] - candle['low']) * 2

    def is_engulfing(current, previous):
        return (current['open'] < previous['close'] and current['close'] > previous['open']) or \
               (current['open'] > previous['close'] and current['close'] < previous['open'])

    for i in range(1, len(candles)):
        current = candles[i]
        previous = candles[i - 1]

        if is_doji(current):
            patterns.append({"timestamp": current['timestamp'], "pattern": "Doji"})
        if is_hammer(current):
            patterns.append({"timestamp": current['timestamp'], "pattern": "Hammer"})
        if is_shooting_star(current):
            patterns.append({"timestamp": current['timestamp'], "pattern": "Shooting Star"})
        if is_engulfing(current, previous):
            pattern_name = "Bullish Engulfing" if current['close'] > current['open'] else "Bearish Engulfing"
            patterns.append({"timestamp": current['timestamp'], "pattern": pattern_name})

    return patterns
