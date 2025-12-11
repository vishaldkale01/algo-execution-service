import asyncio
import json
import upstox_client
from upstox_client.rest import ApiException


class UpstoxWebSocket:
    def __init__(self, access_token: str, user_id: str = None, config: dict = None):
        """
        access_token: Upstox OAuth Access Token
        user_id: Optional custom user id (for multi-user setups)
        config: { symbols: ["NSE_INDEX|Nifty 50", ...] }
        """
        self.access_token = access_token
        self.user_id = user_id
        self.config = config or {}

        self.symbols = self.config.get("symbols", [
            "NSE_INDEX|Nifty Bank",
            "NSE_INDEX|Nifty 50",
        ])

        self.streamer = None
        self._initialized = False

    # ----------------------------------------------------------------------
    # Callback: Handle incoming market data
    # ----------------------------------------------------------------------
    def on_message(self, message):
        """Called when market data is received"""
        try:
            print("\n📈 Tick Data:")
            
            # The SDK automatically decodes protobuf messages
            # message is already a Python dict
            feeds = message.get("feeds", {})
            
            if not feeds:
                print("⚠ No feed data in packet (heartbeat or header)")
                return
            
            for instrument, feed in feeds.items():
                # print(f"\n📊 {instrument}:")
                # print(json.dumps(feed, indent=2))
                
        except Exception as e:
            print(f"❌ Error processing message: {e}")

    def on_open(self):
        """Called when WebSocket connection opens"""
        print("✅ WebSocket Connected")
        
        # Subscribe to instruments
        try:
            self.streamer.subscribe(
                self.symbols,
                "full"  # Options: "ltpc", "full"
            )
            print(f"📨 Subscribed to: {self.symbols}")
        except Exception as e:
            print(f"❌ Subscription error: {e}")

    def on_error(self, error):
        """Called when an error occurs"""
        print(f"❌ WebSocket error: {error}")

    def on_close(self):
        """Called when WebSocket connection closes"""
        print("🔌 WebSocket closed")

    # ----------------------------------------------------------------------
    # Initialize streamer (replaces load_proto + get_market_feed_url)
    # ----------------------------------------------------------------------
    def _initialize_streamer(self):
        """Initialize the market data streamer"""
        if not self._initialized:
            print("🔌 Initializing Upstox WebSocket…")
            
            # Create configuration and set access token
            configuration = upstox_client.Configuration()
            configuration.access_token = self.access_token
            
            # Create API client
            api_client = upstox_client.ApiClient(configuration)
            
            # Initialize streamer with API client
            self.streamer = upstox_client.MarketDataStreamerV3(api_client)
            
            # Register event handlers using .on() method
            self.streamer.on("open", self.on_open)
            self.streamer.on("message", self.on_message)
            self.streamer.on("error", self.on_error)
            self.streamer.on("close", self.on_close)
            
            self._initialized = True
            print("✅ WebSocket Initialized")

    # ----------------------------------------------------------------------
    # Start WebSocket Connection (keeps same interface as before)
    # ----------------------------------------------------------------------
    async def start(self):
        """Initialize and start the market data streamer"""
        try:
            # Initialize streamer
            self._initialize_streamer()
            
            # Connect to WebSocket
            self.streamer.connect()
            
            # Keep the connection alive
            while True:
                await asyncio.sleep(1)
                
        except ApiException as e:
            print(f"❌ API Exception: {e}")
        except Exception as e:
            print(f"❌ Connection error: {e}")

    # ----------------------------------------------------------------------
    # Stop WebSocket Connection
    # ----------------------------------------------------------------------
    def stop(self):
        """Gracefully close the WebSocket connection"""
        if self.streamer:
            self.streamer.disconnect()
            print("🔌 WebSocket disconnected")

    # ----------------------------------------------------------------------
    # Change subscription (add/remove instruments)
    # ----------------------------------------------------------------------
    def subscribe(self, instruments: list, mode: str = "full"):
        """
        Subscribe to additional instruments
        mode: "ltpc" or "full"
        """
        if self.streamer:
            self.streamer.subscribe(instruments, mode)
            print(f"📨 Subscribed to: {instruments}")

    def unsubscribe(self, instruments: list):
        """Unsubscribe from instruments"""
        if self.streamer:
            self.streamer.unsubscribe(instruments)
            print(f"📭 Unsubscribed from: {instruments}")


# ----------------------------------------------------------------------
# 🔥 EXAMPLE USAGE - Maintains backward compatibility
# ----------------------------------------------------------------------
# async def main():
#     # Your existing initialization pattern works unchanged:
#     access_token = ""
#     user_id = "user123"
#     config = {
#         "symbols": [
#             "NSE_INDEX|Nifty Bank",
#             "NSE_INDEX|Nifty 50",
#             "NSE_EQ|INE669E01016",
#         ]
#     }
    
    
#     ws_client = UpstoxWebSocket(access_token, user_id, config)
    
#     try:
#         # Start streaming (same as before)
#         await ws_client.start()
#     except KeyboardInterrupt:
#         print("\n⏹ Stopping...")
#         ws_client.stop()


# # Run the WebSocket client
# if __name__ == "__main__":
#     asyncio.run(main())