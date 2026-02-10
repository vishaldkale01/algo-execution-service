import asyncio
from app.services.risk_engine import RiskEngine
from app.services.trend_analyzer import TrendAnalyzer
from datetime import datetime

async def verify_core_hardening():
    print("[TEST] Verifying Core Hardening...")
    
    # 1. Test Risk Engine Import & Instantiation
    try:
        risk = RiskEngine("test_user")
        print("[OK] RiskEngine Instantiated")
    except Exception as e:
        print(f"❌ RiskEngine Failed: {e}")
        
    # 2. Test Trend Analyzer Import & Instantiation
    try:
        analyzer = TrendAnalyzer("test_user")
        print("[OK] TrendAnalyzer Instantiated")
        
        # Test generic tick
        candle = {
            "timestamp": datetime.now(),
            "open": 45000, "high": 45100, "low": 44900, "close": 45050, "volume": 1000
        }
        res = analyzer.process_tick("NSE_INDEX|Nifty Bank", candle, is_index=True)
        print(f"[OK] TrendAnalyzer.process_tick executed. Result: {res}")
        
    except Exception as e:
        print(f"[FAIL] TrendAnalyzer Failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(verify_core_hardening())
