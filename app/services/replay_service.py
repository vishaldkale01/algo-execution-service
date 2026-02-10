from datetime import datetime
from typing import List, Dict, Optional, Generator
import pandas as pd
import asyncio

class MarketReplayService:
    """
    Manages the playback of historical data.
    Acts as the 'Clock' and 'Data Source' for the replay.
    """
    def __init__(self, data: List[Dict]):
        # data: List of 1-min candles [{'timestamp':..., 'open':..., ...}]
        self.data = sorted(data, key=lambda x: x['timestamp'])
        self.current_index = 0
        self._current_time = None
        self.current_candle = None
        
    @property
    def current_time(self) -> datetime:
        return self._current_time

    def has_next(self) -> bool:
        return self.current_index < len(self.data)

    async def next_tick(self) -> Optional[Dict]:
        """
        Advance one minute.
        Returns the candle for that minute.
        """
        if not self.has_next():
            return None
            
        self.current_candle = self.data[self.current_index]
        self._current_time = self.current_candle['timestamp']
        self.current_index += 1
        
        return self.current_candle

    def get_current_price(self) -> float:
        if self.current_candle:
            return self.current_candle['close'] # Use close as 'LTP' for simplicity
        return 0.0

    def reset(self):
        self.current_index = 0
        self._current_time = None
        self.current_candle = None
