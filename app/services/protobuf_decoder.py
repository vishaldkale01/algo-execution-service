"""
Protobuf decoder for Upstox WebSocket market data feed.
This module handles decoding of binary protobuf messages from Upstox WebSocket.
"""

from google.protobuf.json_format import MessageToDict


class ProtobufDecoder:
    def __init__(self):
        self.feed_response_class = None
        self._initialize_protobuf()

    def _initialize_protobuf(self):
        """Initialize protobuf message classes from .proto file"""
        try:
            # Relative import from the same package: app/services
            from . import MarketDataFeed_pb2
            self.feed_response_class = MarketDataFeed_pb2.FeedResponse
            print("Protobuf decoder initialized successfully")
            print(MarketDataFeed_pb2)
            # print response
            print("response class:", self.feed_response_class)
        except ImportError as e:
            print("IMPORT ERROR while loading MarketDataFeed_pb2:", e)
            print("WARNING: Protobuf classes not generated or import path wrong.")
            self.feed_response_class = None
        except Exception as e:
            print(f"Error initializing protobuf: {e}")
            self.feed_response_class = None

    def decode(self, binary_data: bytes) -> dict:
        """Decode binary protobuf message to Python dictionary"""
        if not self.feed_response_class:
            print("Protobuf decoder not initialized")
            return None

        try:
            msg = self.feed_response_class()
            msg.ParseFromString(binary_data)
            print("decoded message:", msg)
            return MessageToDict(msg, preserving_proto_field_name=True)
        except Exception as e:
            print(f"Error decoding protobuf message: {e}")
            return None


# Global decoder instance
_decoder: ProtobufDecoder | None = None


def get_decoder() -> ProtobufDecoder:
    """Get or create global protobuf decoder instance"""
    global _decoder
    if _decoder is None:
        _decoder = ProtobufDecoder()
    return _decoder


def decode_message(binary_data: bytes) -> dict:
    """Convenience function to decode protobuf message"""
    decoder = get_decoder()
    return decoder.decode(binary_data)
