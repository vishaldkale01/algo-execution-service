from datetime import datetime
from typing import Dict, Tuple, Optional
from app.models.trade import VirtualTrade, TradeStatus, TradeType

class DailyRiskMonitor:
    def __init__(self, max_trades: int = 5, max_loss_amt: float = 2000.0):
        self.max_trades = max_trades
        self.max_loss_amt = max_loss_amt
        self.current_date = datetime.now().date()
        self.trades_taken = 0
        self.daily_pnl = 0.0
        self.is_locked = False
        self.last_trade_time = None
        self.last_trade_result = "WIN" # WIN/LOSS

    def check_new_day(self):
        if datetime.now().date() > self.current_date:
            self.current_date = datetime.now().date()
            self.trades_taken = 0
            self.daily_pnl = 0.0
            self.is_locked = False
            print("🔄 Daily Risk Monitor Reset for New Day")

    def can_trade(self) -> Tuple[bool, str]:
        self.check_new_day()
        
        if self.is_locked:
            return False, "Daily Limit Breached (Locked)"
            
        if self.trades_taken >= self.max_trades:
            return False, f"Max Trades Reached ({self.trades_taken}/{self.max_trades})"
            
        if self.daily_pnl <= -self.max_loss_amt:
             return False, f"Max Daily Loss Reached ({self.daily_pnl})"
             
        return True, "OK"

    def record_trade(self, pnl: float):
        self.trades_taken += 1
        self.daily_pnl += pnl
        self.last_trade_time = datetime.now()
        
        if pnl < 0:
            self.last_trade_result = "LOSS"
        else:
             self.last_trade_result = "WIN"
             
        if self.daily_pnl <= -self.max_loss_amt:
            self.is_locked = True
            print(f"STOP DAILY STOP LOSS HIT: {self.daily_pnl}")

class ActiveTradeContext:
    def __init__(self, trade: VirtualTrade, atr: float, sl: float, target: float):
        self.trade = trade
        self.atr = atr
        self.current_sl = sl
        self.target = target
        
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
