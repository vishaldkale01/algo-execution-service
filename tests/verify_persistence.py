import asyncio
import os
from datetime import datetime
from app.database import get_database, connect_to_mongo
from app.models.trade import VirtualTrade, TradeType, TradeStatus
from app.services.trade_lifecycle_manager import ActiveTradeContext

async def verify_persistence():
    print("[TEST] Verifying MongoDB Persistence...")
    
    # 1. Connect
    try:
        await connect_to_mongo()
        db = await get_database()
    except Exception as e:
        print(f"[FAIL] Could not connect to MongoDB: {e}")
        return

    # 2. Test Trade Insertion
    print("\n[STEP 1] Testing Trade Record...")
    v_trade = VirtualTrade(
        symbol="NSE_FO|BANKNIFTY25JAN60000CE",
        tradeType=TradeType.CALL,
        entryPrice=450.5,
        targetPrice=550.0,
        stopLoss=400.0,
        quantity=15,
        status=TradeStatus.OPEN
    )
    
    try:
        # Insert
        trade_dict = v_trade.model_dump()
        result = await db.trades.insert_one(trade_dict)
        print(f"[PASS] Trade inserted. ID: {result.inserted_id}")
        
        # Update
        v_trade.status = TradeStatus.CLOSED
        v_trade.exitPrice = 500.0
        v_trade.pnl = (500.0 - 450.5) * 15
        
        await db.trades.update_one(
            {"id": v_trade.id},
            {"$set": v_trade.model_dump()}
        )
        print("[PASS] Trade updated to CLOSED")
        
    except Exception as e:
        print(f"[FAIL] Trade persistence error: {e}")

    # 3. Test Signal Logging
    print("\n[STEP 2] Testing Signal Logging...")
    signal_doc = {
        "user_id": "TEST_USER",
        "timestamp": datetime.now(),
        "instrument": "NSE_INDEX|Nifty Bank",
        "candle": {"close": 60000, "volume": 1000},
        "signal_data": {"signal": "BUY_CALL", "confidence": 8}
    }
    
    try:
        result = await db.signals.insert_one(signal_doc)
        print(f"[PASS] Signal logged. ID: {result.inserted_id}")
    except Exception as e:
        print(f"[FAIL] Signal logging error: {e}")

    # 4. Test Snapshot
    print("\n[STEP 3] Testing Snapshot...")
    snapshot = {
        "user_id": "TEST_USER",
        "timestamp": datetime.now(),
        "symbol": "NSE_INDEX|Nifty Bank",
        "pcr": 1.25,
        "spot_price": 60120.5
    }
    
    try:
        result = await db.snapshots.insert_one(snapshot)
        print(f"[PASS] Snapshot saved. ID: {result.inserted_id}")
    except Exception as e:
        print(f"[FAIL] Snapshot error: {e}")

    print("\n[DONE] Persistence Verification Finished")

if __name__ == "__main__":
    asyncio.run(verify_persistence())
