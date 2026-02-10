from datetime import datetime
from typing import Dict, Tuple, Optional
from app.models.trade import VirtualTrade, TradeStatus, TradeType

class ActiveTradeContext:
    def __init__(self, trade: VirtualTrade, atr: float, sl: float, target: float, entry_order_id: str = None):
        self.trade = trade
        self.atr = atr
        self.current_sl = sl
        self.target = target
        
        # Order Tracking
        self.entry_order_id = entry_order_id
        self.sl_order_id: Optional[str] = None
        self.exit_order_id: Optional[str] = None
        
        # State
        self.highest_mfe = 0.0 # Max Favorable Excursion (Points)
        self.is_partial_booked = False
        self.be_moved = False
        self.trailing_active = False
        
        # For trailing logic
        self.entry_price = trade.entryPrice
        
    def update(self, current_price: float, high: float, low: float) -> Dict:
        """
        Update trade state per tick/candle.
        Returns Dict of actions e.g. {"action": "UPDATE_SL", "price": ...} or {"action": "EXIT", ...}
        """
        
        # 0. Check Hit SL
        if self.trade.tradeType == TradeType.CALL:
            if current_price <= self.current_sl:
                return {"action": "EXIT_ALL", "reason": "STOP_LOSS", "price": self.current_sl}
        else:
            if current_price >= self.current_sl:
                 return {"action": "EXIT_ALL", "reason": "STOP_LOSS", "price": self.current_sl}
                 
        # Calculate MFE (Points in favor)
        if self.trade.tradeType == TradeType.CALL:
            mfe = current_price - self.entry_price
        else:
            mfe = self.entry_price - current_price
            
        if mfe > self.highest_mfe:
            self.highest_mfe = mfe
            
        actions = {}
        
        # 1. Break-Even Logic (At 1.0 ATR)
        # Move SL to Entry if not already moved
        if not self.be_moved and mfe >= (1.0 * self.atr):
            self.current_sl = self.entry_price
            self.be_moved = True
            actions["update_sl"] = self.current_sl
            actions["log"] = "Moved SL to Break-Even (1 ATR Reached)"
            
        # 2. Partial Exit (At 1.2 ATR)
        if not self.is_partial_booked and mfe >= (1.2 * self.atr):
            self.is_partial_booked = True
            actions["partial_exit"] = 0.5 # 50%
            actions["log"] = "Partial Profit Booked (1.2 ATR Reached)"
            
        # 3. Trailing Stop (Starts at 1.5 ATR)
        # Soft Trail: Use Candle High/Low logic
        if mfe >= (1.5 * self.atr):
            self.trailing_active = True
            
        if self.trailing_active:
            new_sl = self.current_sl
            
            if self.trade.tradeType == TradeType.CALL:
                # Trail using Previous Candle Low (passed as 'low' here usually representing last completed candle low)
                # But for safety, we allow standard ATR trailing or structured trailing.
                # User asked: "Trail using Previous candle low (CALL)"
                # If we are in the middle of a candle, we might not have 'prev candle low' easily unless passed context.
                # Assuming 'low' arg is the relevant anchor.
                
                # Logic: Never move SL down
                if low > self.current_sl:
                    new_sl = low
                    
            else: # PUT
                # Trail using Candle High
                if high < self.current_sl:
                    new_sl = high
            
            if new_sl != self.current_sl:
                self.current_sl = new_sl
                actions["update_sl"] = self.current_sl
                actions["log"] = f"Trailing SL Updated to {new_sl}"

        return actions
