import asyncio
from unittest.mock import MagicMock, patch
from app.services.trading_manager import UserTrader
from app.services.ai_validator import AIValidator
from app.models.trade import TradeType, TradeStatus

async def verify_ai_logic():
    print("[TEST] Verifying AI Validation Flow (Optional Toggle)...")
    
    # Setup mock config
    config_with_ai = {"USE_AI_VALIDATION": True, "PAPER_TRADING": True}
    config_without_ai = {"USE_AI_VALIDATION": False, "PAPER_TRADING": True}
    
    # 1. Test Disabled Flow
    print("\n[STEP 1] Testing Disabled AI Flow...")
    trader_no_ai = UserTrader("TEST_USER", "TOKEN", config_without_ai)
    # Mock Risk Engine to always pass
    from unittest.mock import AsyncMock
    trader_no_ai.risk_engine.can_trade = AsyncMock(return_value=(True, ""))
    
    signal = {
        "signal": "BUY_CALL", 
        "entry_price": 45000, 
        "stop_loss": 44900, 
        "target": 45200, 
        "confidence": 7,
        "atr": 50.0,
        "setup": "BULL_FLAG"
    }
    
    with patch.object(trader_no_ai.ai_validator, 'validate_signal') as mock_val:
        await trader_no_ai.handle_signal(signal)
        mock_val.assert_not_called()
        print("[PASS] AI Validator not called when disabled.")

    # 2. Test Enabled AI Flow (Simulation of Veto)
    print("\n[STEP 2] Testing Enabled AI Flow (VETO Simulation)...")
    trader_ai = UserTrader("TEST_USER", "TOKEN", config_with_ai)
    trader_ai.risk_engine.can_trade = AsyncMock(return_value=(True, ""))
    
    with patch.object(trader_ai.ai_validator, 'validate_signal', new_callable=AsyncMock) as mock_val:
        mock_val.return_value = (False, "Choppy conditions detected by AI")
        await trader_ai.handle_signal(signal)
        mock_val.assert_called_once()
        if trader_ai.active_trade is None:
            print("[PASS] Signal VETOED correctly by AI.")
        else:
            print("[FAIL] Signal was executed despite AI Veto.")

    # 3. Test Enabled AI Flow (Simulation of PASS)
    print("\n[STEP 3] Testing Enabled AI Flow (PASS Simulation)...")
    with patch.object(trader_ai.ai_validator, 'validate_signal', new_callable=AsyncMock) as mock_val:
        mock_val.return_value = (True, "High probability breakout approved")
        # Reset active_trade
        trader_ai.active_trade = None
        await trader_ai.handle_signal(signal)
        mock_val.assert_called_once()
        if trader_ai.active_trade is not None:
            print("[PASS] Signal APPROVED and EXECUTED correctly.")
        else:
            print("[FAIL] Signal was not executed despite AI Approval.")

    print("\n[DONE] AI Validation Flow Verification Finished.")

if __name__ == "__main__":
    asyncio.run(verify_ai_logic())
