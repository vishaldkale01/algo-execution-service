from datetime import datetime
from app.database import get_database

class AuditLogger:
    """
    Saves system events and errors to MongoDB for auditing.
    """
    def __init__(self, user_id: str):
        self.user_id = user_id
        
    async def log(self, event: str, level: str = "INFO", details: dict = None):
        try:
            db = await get_database()
            doc = {
                "user_id": self.user_id,
                "timestamp": datetime.now(),
                "level": level,
                "event": event,
                "details": details or {}
            }
            await db.audit_logs.insert_one(doc)
            # Also print for console visibility
            print(f"[{level}] {event}")
        except Exception as e:
            print(f"[ERROR] Could not save audit log: {e}")

# Factory or singleton-like usage in UserTrader
