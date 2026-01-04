
import sys
import os
from datetime import datetime

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.services.trade_lifecycle_manager import ActiveTradeContext, DailyRiskMonitor
from app.models.trade import VirtualTrade, TradeType

def test_daily_risk():
    print("\n--- Testing Daily Risk Monitor ---")
    risk = DailyRiskMonitor(max_trades=2, max_loss_amt=100)
    
    # 1. Check Initial
    ok, msg = risk.can_trade()
    print(f"Initial Check: {ok} ({msg})")
    assert ok == True
    
    # 2. Record Loss
    risk.record_trade(-50)
    print("Recorded Loss -50")
    ok, msg = risk.can_trade()
    assert ok == True
    
    # 3. Record Another Loss (Total -150 > -100)
    risk.record_trade(-100)
    print("Recorded Loss -100 (Total -150)")
    ok, msg = risk.can_trade()
    print(f"Check after Breach: {ok} ({msg})")
    assert ok == False
    assert ("Loss Reached" in msg) or ("Locked" in msg)

def test_trade_lifecycle_call():
    print("\n--- Testing Trade Lifecycle (CALL) ---")
    # Entry: 100, ATR: 10, SL: 90
    trade = VirtualTrade(symbol="TEST", tradeType=TradeType.CALL, entryPrice=100, quantity=100)
    ctx = ActiveTradeContext(trade, atr=10.0, sl=90.0, target=120.0)
    
    # 1. Price moves to 105 (+0.5 ATR) -> No Action
    actions = ctx.update(current_price=105, high=105, low=102)
    print(f"Price 105: {actions}")
    assert not actions
    
    # 2. Price moves to 110 (+1.0 ATR) -> Break Even
    actions = ctx.update(current_price=110, high=110, low=108)
    print(f"Price 110: {actions}")
    assert "update_sl" in actions
    assert actions["update_sl"] == 100.0 # BE
    
    # 3. Price moves to 112 (+1.2 ATR) -> Partial Exit
    actions = ctx.update(current_price=112, high=112, low=111)
    print(f"Price 112: {actions}")
    assert "partial_exit" in actions
    
    # 4. Price moves to 115 (+1.5 ATR) -> Trailing Active
    # Need to pass Candle Low. Say Candle Low was 113.
    # Current SL is 100 (BE). Should move to 113.
    actions = ctx.update(current_price=115, high=115, low=113)
    print(f"Price 115 (Low 113): {actions}")
    assert "update_sl" in actions
    assert actions["update_sl"] == 113

if __name__ == "__main__":
    test_daily_risk()
    test_trade_lifecycle_call()
