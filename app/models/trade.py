from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
from enum import Enum

class TradeType(str, Enum):
    CALL = "CALL"
    PUT = "PUT"

class TradeStatus(str, Enum):
    # Lifecycle
    PENDING_ENTRY = "PENDING_ENTRY"
    SUBMITTED = "SUBMITTED"
    OPEN = "OPEN"           # Fully filled
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    
    # Exit States
    EXIT_PENDING = "EXIT_PENDING"
    CLOSED = "CLOSED"
    
    # Failure/Cancel States
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    ERROR = "ERROR"

class Signals(BaseModel):
    ema: Optional[str] = None
    sma: Optional[str] = None
    macd: Optional[str] = None
    rsi: Optional[float] = None
    overallTrend: Optional[str] = None

class CandleData(BaseModel):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

import uuid

class VirtualTrade(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    symbol: str
    tradeType: TradeType
    entryPrice: float
    targetPrice: Optional[float] = None
    stopLoss: Optional[float] = None
    quantity: int = 1
    status: TradeStatus = TradeStatus.OPEN
    entryTime: datetime = Field(default_factory=datetime.now)
    exitTime: Optional[datetime] = None
    exitPrice: Optional[float] = None
    pnl: Optional[float] = None
    signals: Optional[Signals] = None
    thirtyMinData: List[CandleData] = []

    class Config:
        use_enum_values = True
        populate_by_name = True

    def to_mongo(self):
        return self.model_dump(by_alias=True)
