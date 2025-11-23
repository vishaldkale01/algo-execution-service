"""
Protobuf decoder for Upstox WebSocket market data feed.
This module handles decoding of binary protobuf messages from Upstox WebSocket.
"""

import os
from google.protobuf import descriptor_pool, message_factory
from google.protobuf.compiler import parser
from google.protobuf import descriptor_pb2

class ProtobufDecoder:
    def __init__(self):
        self.feed_response_class = None
        self._initialize_protobuf()
    
    def _initialize_protobuf(self):
        """Initialize protobuf message classes from .proto file"""
        try:
            # For now, we'll use a manual approach
            # In production, you should compile the .proto file using protoc
            # Command: protoc --python_out=. MarketDataFeed.proto
            
            # Import the generated protobuf module
            # This assumes you've run: protoc --python_out=. MarketDataFeed.proto
            try:
                from app.services import MarketDataFeed_pb2
                self.feed_response_class = MarketDataFeed_pb2.FeedResponse
                print("Protobuf decoder initialized successfully")
            except ImportError:
                print("WARNING: Protobuf classes not generated. Run: protoc --python_out=app/services app/services/MarketDataFeed.proto")
                self.feed_response_class = None
        except Exception as e:
            print(f"Error initializing protobuf: {e}")
            self.feed_response_class = None
    
    def decode(self, binary_data: bytes) -> dict:
        """
        Decode binary protobuf message to Python dictionary
        
        Args:
            binary_data: Binary protobuf message from WebSocket
            
        Returns:
            Decoded message as dictionary
        """
        if not self.feed_response_class:
            print("Protobuf decoder not initialized")
            return None
        
        try:
            # Decode the protobuf message
            feed_response = self.feed_response_class()
            feed_response.ParseFromString(binary_data)
            
            # Convert to dictionary for easier processing
            return self._protobuf_to_dict(feed_response)
        except Exception as e:
            print(f"Error decoding protobuf message: {e}")
            return None
    
    def _protobuf_to_dict(self, message) -> dict:
        """
        Convert protobuf message to dictionary
        
        Args:
            message: Protobuf message object
            
        Returns:
            Dictionary representation
        """
        from google.protobuf.json_format import MessageToDict
        return MessageToDict(message, preserving_proto_field_name=True)


# Global decoder instance
_decoder = None

def get_decoder() -> ProtobufDecoder:
    """Get or create global protobuf decoder instance"""
    global _decoder
    if _decoder is None:
        _decoder = ProtobufDecoder()
    return _decoder


def decode_message(binary_data: bytes) -> dict:
    """
    Convenience function to decode protobuf message
    
    Args:
        binary_data: Binary protobuf message
        
    Returns:
        Decoded message as dictionary
    """
    decoder = get_decoder()
    return decoder.decode(binary_data)
