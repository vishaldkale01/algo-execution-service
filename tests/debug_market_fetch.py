import asyncio
from unittest.mock import MagicMock, patch
from app.services.market_data_service import MarketDataService

async def test_key_handling():
    service = MarketDataService("dummy_token")
    
    test_cases = [
        {
            "name": "Standard Match",
            "key": "NSE_INDEX|Nifty Bank",
            "response": {"data": {"NSE_INDEX|Nifty Bank": {"last_price": 1000.0}}},
            "expected": 1000.0
        },
        {
            "name": "Encoded Response Match",
            "key": "NSE_INDEX|Nifty Bank",
            "response": {"data": {"NSE_INDEX|Nifty%20Bank": {"last_price": 2000.0}}},
            "expected": 2000.0
        },
        {
            "name": "Space Response Match (Request encoded)",
            "key": "NSE_INDEX|Nifty%20Bank",
            "response": {"data": {"NSE_INDEX|Nifty Bank": {"last_price": 3000.0}}},
            "expected": 3000.0
        },
        {
            "name": "Key Missing",
            "key": "NSE_INDEX|Nifty Bank",
            "response": {"data": {"NSE_INDEX|Other": {"last_price": 4000.0}}},
            "expected": 0.0
        }
    ]

    print("🚀 Starting Logic Verification")
    
    for case in test_cases:
        print(f"\nTesting: {case['name']}")
        
        # Mock httpx client
        with patch('httpx.AsyncClient') as mock_client_cls:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = case['response']
            
            # Setup async context manager mock
            mock_client.get.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_cls.return_value = mock_client
            
            # Run
            result = await service.get_market_status(case['key'])
            
            # Verify
            if result == case['expected']:
                print(f"✅ PASSED | Got {result}")
            else:
                print(f"❌ FAILED | Expected {case['expected']}, Got {result}")

if __name__ == "__main__":
    asyncio.run(test_key_handling())
