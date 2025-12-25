import asyncio
import json
import upstox_client
from upstox_client.rest import ApiException


class UpstoxWebSocket:
    def __init__(self, access_token: str, user_id: str = None, config: dict = None, on_data_callback=None):
        """
        access_token: Upstox OAuth Access Token
        user_id: Optional custom user id (for multi-user setups)
        config: { symbols: ["NSE_INDEX|Nifty Bank", ...] }
        on_data_callback: Async function to call when data arrives
        """
        self.access_token = access_token
        self.user_id = user_id
        self.config = config or {}
        self.on_data_callback = on_data_callback

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
            # The SDK automatically decodes protobuf messages
            # message is already a Python dict
            feeds = message.get("feeds", {})
            
            if not feeds:
                return

            # If a callback is registered, pass the data asynchronously
            if self.on_data_callback:
                # We need to ensure this is run in the event loop
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        loop.create_task(self.on_data_callback(message))
                except RuntimeError:
                    # Fallback if no loop (should not happen in async app)
                    pass
            else:
                # Default logging if no callback
                print(f"📈 Tick Data: {len(feeds)} instruments updated")
                
        except Exception as e:
            print(f"❌ Error processing message: {e}")

    def on_open(self):
        """Called when WebSocket connection opens"""
        print(f"✅ WebSocket Connected for {self.user_id}")
        
        # Subscribe to initial instruments
        if self.symbols:
            self.subscribe(self.symbols)

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

    # ----------------------------------------------------------------------
    # Start WebSocket Connection (keeps same interface as before)
    # ----------------------------------------------------------------------
    async def start(self):
        """Initialize and start the market data streamer"""
        try:
            # Initialize streamer
            self._initialize_streamer()
            
            # Connect to WebSocket
            # Note: streamer.connect() is usually blocking or threaded in some SDKs.
            # Upstox V3 Python SDK streamer is threaded. 
            # We keep the main loop alive here.
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
        Subscribe to additional instruments.
        mode: "ltpc" (LTP+Close) or "full" (Depth, OHLC, Vol)
        """
        if self.streamer and instruments:
            try:
                self.streamer.subscribe(instruments, mode)
                print(f"📨 Subscribed to {len(instruments)} instruments")
            except Exception as e:
                print(f"❌ Subscribe Error: {e}")

    def unsubscribe(self, instruments: list):
        """Unsubscribe from instruments"""
        if self.streamer and instruments:
            try:
                self.streamer.unsubscribe(instruments)
                print(f"📭 Unsubscribed from {len(instruments)} instruments")
            except Exception as e:
                print(f"❌ Unsubscribe Error: {e}")


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