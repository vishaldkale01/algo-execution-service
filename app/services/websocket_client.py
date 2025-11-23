import asyncio
import websockets
import json
from app.config import settings
import httpx
from app.services.trend_analyzer import analyze_trend

class UpstoxWebSocket:
    def __init__(self, access_token: str, user_id: str = None, config: dict = None):
        self.access_token = access_token
        self.user_id = user_id
        self.config = config or {}
        self.ws_url = None
        self.ws = None
        
    async def get_market_feed_url(self):
        """Get authorized WebSocket URL from Upstox API"""
        url = "https://api.upstox.com/v2/feed/market-data-feed/authorize"
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.access_token}"
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
            
        if response.status_code == 200:
            data = response.json()
            return data["data"]["authorizedRedirectUri"]
        else:
            raise Exception(f"Failed to get WebSocket URL: {response.text}")
    
    async def connect(self):
        """Establish WebSocket connection"""
        self.ws_url = await self.get_market_feed_url()
        
        headers = {
            "Api-Version": "2.0",
            "Authorization": f"Bearer {self.access_token}"
        }
        
        self.ws = await websockets.connect(
            self.ws_url,
            extra_headers=headers
        )
        
        print(f"WebSocket connected successfully for user {self.user_id}")
        
        # Subscribe to instruments
        # Use symbols from config if available, else default
        symbols = self.config.get("symbols", ["NSE_INDEX|Nifty Bank", "NSE_INDEX|Nifty 50"])
        
        subscription_data = {
            "guid": "someguid",
            "method": "sub",
            "data": {
                "mode": "full",
                "instrumentKeys": symbols
            }
        }
        
        await self.ws.send(json.dumps(subscription_data))
        print(f"Subscribed to instruments: {symbols}")
        
    async def listen(self):
        """Listen for WebSocket messages"""
        try:
            from app.services.protobuf_decoder import decode_message
            
            async for message in self.ws:
                try:
                    # Upstox sends protobuf encoded binary data
                    if isinstance(message, bytes):
                        # Decode protobuf message
                        decoded_data = decode_message(message)
                        
                        if decoded_data:
                            # Analyze the decoded market data with user context
                            await analyze_trend(decoded_data, self.user_id, self.config)
                        else:
                            print(f"Failed to decode message of {len(message)} bytes")
                    else:
                        # Handle JSON messages (if any)
                        print(f"Received non-binary message: {message}")
                        
                except Exception as e:
                    print(f"Error processing message: {e}")
                    import traceback
                    traceback.print_exc()
                    
        except websockets.exceptions.ConnectionClosed:
            print("WebSocket connection closed")
        except Exception as e:
            print(f"WebSocket error: {e}")
            import traceback
            traceback.print_exc()
    
    async def start(self):
        """Start WebSocket connection and listening"""
        await self.connect()
        await self.listen()


async def initialize_websocket(access_token: str):
    """Initialize and start WebSocket connection"""
    ws_client = UpstoxWebSocket(access_token)
    await ws_client.start()
