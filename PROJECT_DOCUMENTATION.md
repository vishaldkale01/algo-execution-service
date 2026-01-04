# Algo Execution Service - Project Documentation

## 1. Project Analysis

### 1.1 Tech Stack
- **Language**: Python 3.9+ (implied by `asyncio` usage)
- **Framework**: Custom AsyncIO Service
- **Database**: MongoDB (via `motor` async driver)
- **Message Broker**: Redis (via `redis-py`) for Pub/Sub events
- **Broker Integration**: Upstox V3 API (`upstox-python-sdk`)
- **WebSockets**: `websockets`, `upstox_client.MarketDataStreamerV3`
- **Data Analysis**: `pandas`, `pandas_ta` (Technical Analysis Lib)
- **HTTP Client**: `httpx` (Async HTTP)
- **Validation**: `pydantic` (implied for models)

### 1.2 Architecture Pattern
The project follows an **Event-Driven Microservice** architecture:
1.  **Command Pattern**: The service listens for commands (`START_TRADING`, `STOP_TRADING`) via a Redis Channel (`trading:commands`).
2.  **Worker Model**: A Global `TradingManager` spawns isolated `UserTrader` instances for each user.
3.  **Hybrid Data Pipeline**: 
    - **Real-time**: WebSockets for market data (ticks).
    - **Polled/Scheduled**: Async loops for Option Chain data (every 5 mins).
    - **Status Updates**: Publishes events back to Redis (`trading:events`).

### 1.3 Core Business Logic
The service is an **Algorithmic Execution Engine** specifically designed for **Scalping Bank Nifty Options**.
- it connects to Upstox for market data.
- It dynamically calculates ATM strikes and subscribes to them.
- It runs a hybrid technical analysis strategy (VWAP + Price Action + Candlestick Patterns).
- It generates signals (BUY_CALL / BUY_PUT) with a strict Priority Logic.
- *Critical Note*: Actual order execution logic is placeholder (print statements only).

### 1.4 Data Flow
1.  **Command**: External System (e.g., Node.js API) -> Redis `trading:commands` -> `TradingManager`.
2.  **Initialization**: `TradingManager` -> Creates `UserTrader` -> Connects WebSocket.
3.  **Market Data**: Upstox WS -> `UserTrader.on_market_data` -> `trend_analyzer.analyze_trend`.
4.  **Context Update**: `UserTrader` background loop -> Upstox REST API (Option Chain) -> Updates PCR & Strike Selection.
5.  **Signal**: `trend_analyzer` -> Logic Decision Tree -> Trade Lock Check -> Logs Signal.

---

## 2. File-Level Documentation

### `app/main.py`
- **Purpose**: Entry point of the application.
- **Responsibilities**:
    - Initializes Database (Mongo) and Broker (Redis) connections.
    - Subscribes to Redis command channel.
    - Keeps the main event loop running.
- **Key Functions**: `main()` (Analysis & Setup).

### `app/services/trading_manager.py`
- **Purpose**: Orchestrates trading sessions.
- **Classes**:
    - `TradingManager`: Singleton that routes Redis commands to specific User sessions.
    - `UserTrader`: Manage the lifecycle of a single user's trading bot (Start/Stop/Config).
- **Key Logic**:
    - `update_option_chain_loop()`: Running background task to fetch Option Chain, calculate PCR, and update WS subscriptions to relevant ATM/ITM/OTM strikes.
    - `on_market_data()`: Bridge between WebSocket and Analyzer.

### `app/services/market_data_service.py`
- **Purpose**: Handles HTTP REST calls to Upstox.
- **Responsibilities**:
    - `fetch_option_chain()`: Gets raw chain data.
    - `extract_target_strikes()`: Intelligent logic to parse the messy option chain, calculate Global PCR, and pick specific instruments (ATM ± 1) to track.
    - `get_market_status()`: Fetches underlying Spot price.

### `app/services/websocket_client.py`
- **Purpose**: Manages Real-time data feed.
- **Responsibilities**:
    - Wraps `upstox_client.MarketDataStreamerV3`.
    - Handles Connection, Reconnection (implied by SDK), and Subscriptions.
    - Routes incoming Protobuf-decoded messages to the callback.

### `app/services/trend_analyzer.py`
- **Purpose**: The "Brain" of the trading bot.
- **Responsibilities**:
    - **Global State**: Manages `trade_lock_store` (cooldowns) and `orb_store` (breakout levels).
    - **Indicators**: VWAP, EMA(9), EMA(21).
    - **Patterns**: Integrates `identify_patterns` for Hammer/Engulfing/Inside Bar.
    - **Signal Generation**: Multistage decision tree:
        1.  **Check Locks**: Cooldown active?
        2.  **Priority 1**: ORB Breakout (9:15-9:30 High/Low).
        3.  **Priority 2**: Inside Bar Breakout.
        4.  **Priority 3**: Engulfing / Hammer (Reversals).
        5.  **Priority 4**: Momentum Trend (Legacy).

### `app/utils/patterns.py` (New)
- **Purpose**: Pure functions for candlestick pattern recognition.
- **Patterns Implemented**:
    - **Hammer / Shooting Star**: Strict geometry checks (wick/body ratios).
    - **Engulfing**: Bullish/Bearish overlap logic.
    - **Inside Bar**: High/Low containment checks.
    - **Range Compression**: Volatility squeeze detection.
    - **Strong Candle**: Body > 60% of range + Closure in extents.
- **Helpers**: `get_candle_metrics`, `check_volume_breakout`.

---

## 3. System-Level Documentation

### Application Flow
1.  **Startup**: App connects to Redis/Mongo. Prints "Waiting for commands".
2.  **User Activation**: Redis receives `{"action": "START_TRADING", "user_id": "123", "data": {...}}`.
3.  **Session Setup**:
    - `UserTrader` initialized with Access Token.
    - `MarketDataService` fetches Spot & Option Chain.
    - WebSocket subscribes to Index + Calculated Option Strikes.
4.  **Runtime Loop**:
    - **Tick**: WS receives price -> `analyze_trend`.
    - **Analysis**:
        - Updates ORB levels (if time < 9:30).
        - Checks Trade Lock.
        - Scans for Patterns.
        - Evaluates Signal Priority.
    - **Signal**: If Valid -> Lock Trading -> Log Signal.
    - **5-Min Interval**: Re-fetch Option Chain -> Update PCR -> Subscribe to NEW ATM strikes if market moved.
5.  **Termination**: Redis `STOP_TRADING` -> Closes WS, Cancel Tasks, cleanup memory.

### Error Handling
- **Network**: `try-except` blocks around external API calls.
- **Retries**: `update_option_chain_loop` sleeps and retries on failure.
- **WebSocket**: The Upstox SDK handles some connection stability, but custom error handlers print errors.

---

## 4. Algo Trading App–Specific Analysis

### Market Data Strategy
- **Hybrid Approach**: simple Ticks for price, REST API for Chain context.
- **Dynamic Subscription**: The bot does *not* subscribe to all options. It intelligently subscribes only to strikes near the Spot price.

### Strategy Execution Flow (Enhanced)
1.  **Ingest**: 1-minute candle constructed/received from Upstox.
2.  **Enrich**: Append to history, calculate EMA9, EMA21, VWAP.
3.  **Structure Check**: Update ORB High/Low.
4.  **Context Check**: Look up latest PCR.
5.  **Pattern ID**: Scan for Hammers, Engulfing, Inside Bars.
6.  **Signal Decision**:
    - **ORB Breakout**: Prioritized if Time > 9:30 and Price breaks ORB High/Low with Volume.
    - **Reversal**: Hammer/Engulfing valid ONLY if near VWAP/EMA.
    - **Momentum**: Strong Candle + EMA Trend.
7.  **Guardrails**:
    - **Trade Lock**: 5-minute cooldown after any signal.
    - **Location Filter**: Reversals ignored in "No Man's Land".

### Broker API Usage
- **Auth**: Bearer Token passed from external source (no login logic in this app).
- **Rate Limits**: Not explicitly handled; relies on 5-min intervals for heavy calls (Option Chain) which is safe.

---

## 5. Improvements & Missing Components

> [!IMPORTANT]
> **CRITICAL MISSING FEATURE: ORDER EXECUTION**
> The current code **DOES NOT PLACE ORDERS**. It contains a placeholder: `print(f"EXECUTE {signals['signal']}...")`.

### 5.1 Trading Engine
- **Order Placement**: Implement `OrderService` to call `upstox.place_order`.
- **Order Management**: Track Open Positions using `TradeManager`.
- **State Machine**: Implement `Neutral -> InTrade -> Exit` states.

### 5.2 Risk Management (Partially Mitigated)
- **Trade Lock**: Implemented to prevent over-trading.
- **Stop Loss / Target**: Logic exists in Config (`stopLossPercent: 0.2`) and Signal Output (`stop_loss`), but no active monitoring loop checks LTP vs SL.
- **Max Loss Per Day**: No circuit breaker.
- **Quantity Sizing**: Quantity is not calculated based on capital/risk.

### 5.3 Reliability
- **Candle Integrity**: The logic relies on `candle_store` which is in-memory. If the app restarts, it loses history.
    - *Fix*: Fetch historical candles on startup.
- **Race Conditions**: `market_context` and `candle_store` are global dictionaries.

### 5.4 Architecture
- **Backtesting**: No way to run this against historical data.
- **Paper Trading**: No "Dry Run" mode flag that simulates fills.

---

## 6. Best Practices Recommendations

1.  **Database Persistence**: Store Order History and Signals in MongoDB for audit trails.
2.  **Secrets Management**: Ensure Access Tokens are not logged in plaintext.
3.  **Time Synchronization**: Ensure server time is synced (NTP).
4.  **Logging**: Replace `print()` with structured logging (`logging.getLogger`).
