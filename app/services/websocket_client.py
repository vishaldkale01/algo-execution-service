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
        url = "https://api.upstox.com/v3/feed/market-data-feed/authorize"
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.access_token}",
            "Api-Version": "3.0"  # ✅ Add Api-Version header
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
            
        if response.status_code == 200:
            data = response.json()
            # ✅ Check for correct field name (might be authorized_redirect_uri)
            ws_url = data["data"].get("authorizedRedirectUri") or data["data"].get("authorized_redirect_uri")
            return ws_url
        else:
            raise Exception(f"Failed to get WebSocket URL: {response.text}")
    
    async def connect(self):
        """Establish WebSocket connection"""
        self.ws_url = await self.get_market_feed_url()
        
        headers = {
            "Api-Version": "3.0",
            "Authorization": f"Bearer {self.access_token}"
        }
        
        try:
            from websockets.asyncio.client import connect as ws_connect
            import websockets
            print(f"DEBUG: websockets version: {websockets.__version__}")
            print(f"DEBUG: Connecting to {self.ws_url}")
            
            self.ws = await ws_connect(
                self.ws_url,
                additional_headers=headers
            )
            
            print(f"✅ WebSocket connected successfully for user {self.user_id}")
        except Exception as e:
            print(f"❌ Connection error: {e}")
            raise e
        
        # ✅ Wait a moment for connection to stabilize
        await asyncio.sleep(0.5)
        
        # Subscribe to instruments
        symbols = self.config.get("symbols", ["NSE_INDEX|Nifty Bank", "NSE_INDEX|Nifty 50"])
        print(f"📊 Subscribing to: {symbols}")
        
        subscription_data = {
            "guid": "someguid",  # ✅ Use same guid format as Node.js
            "method": "sub",
            "data": {
                "mode": "full",
                "instrumentKeys": symbols
            }
        }
        
        await self.ws.send(json.dumps(subscription_data))
        print(f"✅ Subscription sent for instruments: {symbols}")
        
    async def listen(self):
        """Listen for WebSocket messages"""
        try:
            from app.services.protobuf_decoder import decode_message
            
            message_count = 0
            async for message in self.ws:
                try:
                    message_count += 1
                    
                    # Upstox sends protobuf encoded binary data
                    if isinstance(message, bytes):
                        print(f"\n📦 Received binary message #{message_count} ({len(message)} bytes)")
                        
                        # Decode protobuf message
                        decoded_data = decode_message(message)
                        
                        if decoded_data:
                            print(f"✅ Decoded data: {json.dumps(decoded_data, indent=2)}")
                            
                            # ✅ Check message type
                            msg_type = decoded_data.get('type')
                            
                            if msg_type == 1:
                                # Type 1 = Full feed data
                                print("📈 MARKET DATA FEED RECEIVED")
                                if 'feeds' in decoded_data:
                                    print(f"📊 Feed contains {len(decoded_data['feeds'])} instruments")
                                    await analyze_trend(decoded_data, self.user_id, self.config)
                                else:
                                    print("⚠️ No 'feeds' field in decoded data")
                                    
                            elif msg_type == 2:
                                # Type 2 = Heartbeat/ping
                                print("💓 Heartbeat message")
                                
                            else:
                                print(f"ℹ️ Message type: {msg_type}")
                                # Still analyze other message types
                                await analyze_trend(decoded_data, self.user_id, self.config)
                        else:
                            print(f"❌ Failed to decode message")
                            # Print first 100 bytes for debugging
                            print(f"Raw bytes (first 100): {message[:100]}")
                    else:
                        # Handle JSON messages (if any)
                        print(f"📄 Received text message: {message}")
                        
                except Exception as e:
                    print(f"❌ Error processing message #{message_count}: {e}")
                    import traceback
                    traceback.print_exc()
                    
        except websockets.exceptions.ConnectionClosed as e:
            print(f"🔌 WebSocket connection closed: {e}")
        except Exception as e:
            print(f"❌ WebSocket error: {e}")
            import traceback
            traceback.print_exc()
    
    async def start(self):
        """Start WebSocket connection and listening"""
        try:
            await self.connect()
            await self.listen()
        except Exception as e:
            print(f"❌ Failed to start WebSocket: {e}")
            raise


async def initialize_websocket(access_token: str, user_id: str = "default", config: dict = None):
    """Initialize and start WebSocket connection"""
    ws_client = UpstoxWebSocket(access_token, user_id, config)
    await ws_client.start()