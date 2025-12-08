import upstox_client
try:
    print(f"upstox_client version: {upstox_client.__version__ if hasattr(upstox_client, '__version__') else 'unknown'}")
    if hasattr(upstox_client, 'MarketDataStreamerV3'):
        print("MarketDataStreamerV3 FOUND")
    else:
        print("MarketDataStreamerV3 NOT FOUND")
        print(f"Available attributes: {dir(upstox_client)}")
except Exception as e:
    print(f"Error: {e}")
