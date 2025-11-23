from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
from enum import Enum

class TradeType(str, Enum):
    CALL = "CALL"
    PUT = "PUT"

class TradeStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    STOPPED = "STOPPED"

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

class VirtualTrade(BaseModel):
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
