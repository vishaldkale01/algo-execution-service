import json
from datetime import datetime
from typing import Tuple, Optional
from app.services.redis_manager import redis_manager

class RiskEngine:
    """
    Redis-backed Risk Management Engine.
    Persists:
    - Daily Trade Count
    - Daily PnL
    - Kill Switch Status
    """
    
    def __init__(self, user_id: str, max_trades: int = 5, max_loss_amt: float = 2500.0):
        self.user_id = user_id
        self.max_trades = max_trades
        self.max_loss_amt = max_loss_amt
        
        # Redis Keys
        today_str = datetime.now().strftime("%Y-%m-%d")
        self.KEY_PREFIX = f"risk:{user_id}:{today_str}"
        self.KEY_TRADES = f"{self.KEY_PREFIX}:trades"
        self.KEY_PNL = f"{self.KEY_PREFIX}:pnl"
        self.KEY_LOCKED = f"{self.KEY_PREFIX}:locked"

    async def _ensure_connection(self):
        if not redis_manager.redis:
            await redis_manager.connect()

    async def get_stats(self) -> dict:
        """Fetch current risk stats from Redis"""
        await self._ensure_connection()
        
        trades = await redis_manager.redis.get(self.KEY_TRADES) or 0
        pnl = await redis_manager.redis.get(self.KEY_PNL) or 0.0
        locked = await redis_manager.redis.get(self.KEY_LOCKED) or "0"
        
        return {
            "trades": int(trades),
            "pnl": float(pnl),
            "locked": locked == "1"
        }

    async def can_trade(self) -> Tuple[bool, str]:
        """Check if a new trade is allowed"""
        stats = await self.get_stats()
        
        if stats["locked"]:
            return False, "[ALERT] KILL SWITCH ACTIVE (Locked)"
            
        if stats["trades"] >= self.max_trades:
            return False, f"Max Trades Reached ({stats['trades']}/{self.max_trades})"
            
        if stats["pnl"] <= -self.max_loss_amt:
            # Auto-lock if not already locked
            await self.lock_trading("Max Loss Hit")
            return False, f"Max Daily Loss Reached ({stats['pnl']})"
            
        return True, "OK"

    async def record_trade(self, pnl: float):
        """Update stats after a trade closes"""
        await self._ensure_connection()
        
        # Increment trade count
        await redis_manager.redis.incr(self.KEY_TRADES)
        
        # Update PnL (Redis has no incrbyfloat, so we read-mod-write or use lua, 
        # but for simple atomic need: incrbyfloat is supported in newer redis-py/server)
        await redis_manager.redis.incrbyfloat(self.KEY_PNL, pnl)
        
        # Check Stop Loss immediately
        new_pnl = float(await redis_manager.redis.get(self.KEY_PNL))
        if new_pnl <= -self.max_loss_amt:
            await self.lock_trading(f"Loss Limit Hit: {new_pnl}")

    async def lock_trading(self, reason: str = ""):
        """Force enable Kill Switch"""
        await self._ensure_connection()
        await redis_manager.redis.set(self.KEY_LOCKED, "1")
        print(f"[ALERT] TRADING LOCKED for {self.user_id}: {reason}")

    async def reset(self):
        """Manual reset (for testing/admin)"""
        await self._ensure_connection()
        await redis_manager.redis.delete(self.KEY_TRADES, self.KEY_PNL, self.KEY_LOCKED)
