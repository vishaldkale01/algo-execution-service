# TradeCore Strategy & Logic

The **TradeCore Engine** is architected around **four core pillars** of analysis. This document details the logic used in each pillar to generate high-probability trading signals.

---

## 1. 📊 Technical Analysis (Indicators)
We use mathematical indicators to measure momentum and volatility.

| Indicator | Configuration | Purpose | Logic |
|-----------|---------------|---------|-------|
| **EMA** | 9 & 20 Periods | Trend Confirmation | **Bullish:** EMA 9 > EMA 20<br>**Bearish:** EMA 9 < EMA 20 |
| **RSI** | 14 Period | Momentum Strength | **Oversold:** < 30 (Potential Buy)<br>**Overbought:** > 70 (Potential Sell) |
| **SuperTrend** | 10 Period, 3 Multiplier | Trend Direction | **UP:** Price > SuperTrend Line<br>**DOWN:** Price < SuperTrend Line |
| **MACD** | 12, 26, 9 | Momentum Reversal | Used for confirmation of trend strength. |
| **Volume** | 20 Period Avg | Confirmation | Trade is valid only if **Current Volume > 0.8x Avg Volume**. |

---

## 2. 🕯️ Candlestick Patterns
We identify specific candle shapes that indicate potential reversals or continuations.

**Implemented Patterns:**
1.  **Doji:** Indicates indecision in the market.
    *   *Logic:* Body size is ≤ 10% of total candle range.
2.  **Hammer:** Bullish reversal signal.
    *   *Logic:* Small body at top, long lower wick (> 2x body).
3.  **Shooting Star:** Bearish reversal signal.
    *   *Logic:* Small body at bottom, long upper wick (> 2x body).
4.  **Engulfing:** Strong reversal signal.
    *   *Logic:* Current candle body completely covers the previous candle body.

---

## 3. 📈 Market Trend Analysis (Moving Averages)
We determine the broader market context (Side Trend vs. Uptrend/Downtrend) using Moving Averages.

**Trend Classification Logic:**

*   **🚀 Uptrend (Strong Bullish):**
    *   Price > EMA 9
    *   EMA 9 > EMA 20
    *   *Action:* Look for **CALL** entries.

*   **🔻 Downtrend (Strong Bearish):**
    *   Price < EMA 9
    *   EMA 9 < EMA 20
    *   *Action:* Look for **PUT** entries.

*   **↔️ Side Trend (Choppy/Neutral):**
    *   Price is bouncing between EMA 9 and EMA 20.
    *   OR EMA 9 and EMA 20 are frequently crossing over.
    *   *Action:* **NO TRADE** (Wait for breakout).

---

## 4. 📉 Price Action (Support/Resistance & Breakouts)
Based on the "Price Action Course" principles, we analyze pure price movement.

**Key Concepts:**
1.  **Breakout:**
    *   Current Close > Previous High AND Current Close > Pre-Previous High.
    *   *Signal:* Strong Buy.
2.  **Breakdown:**
    *   Current Close < Previous Low AND Current Close < Pre-Previous Low.
    *   *Signal:* Strong Sell.
3.  **Strong Candles:**
    *   **Strong Bull:** Green candle where Body > 2x Wicks.
    *   **Strong Bear:** Red candle where Body > 2x Wicks.

---

## 🎯 Trade Execution Logic (The Decision Matrix)

A trade is executed ONLY if the **Confidence Score** is above 40%.

**Scoring System:**
- **+40 pts:** Trend Alignment (EMA + SuperTrend match).
- **+20 pts:** RSI Confirmation (Not overbought/oversold against trend).
- **+20 pts:** Price Action (Breakout/Breakdown detected).
- **+20 pts:** Volume Confirmation (High relative volume).

**Total Possible Score: 100**

### Entry Rules:
- **CALL Entry:** Score > 40 AND Trend is UP AND Price Action is Bullish.
- **PUT Entry:** Score > 40 AND Trend is DOWN AND Price Action is Bearish.

### Exit Rules:
- **Target Hit:** +0.3% profit.
- **Stop Loss:** -0.2% loss.
- **Trend Reversal:** SuperTrend flips direction.
