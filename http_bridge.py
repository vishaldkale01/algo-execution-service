import asyncio
import os
import json
import redis.asyncio as redis
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

# ---------------------------------------------------------
# 🛠️ SETUP INSTRUCTIONS
# 1. Install dependencies: pip install fastapi uvicorn
# 2. Run this server: uvicorn http_bridge:app --reload
# 3. Use Postman to POST to http://127.0.0.1:8000/start-trading
# ---------------------------------------------------------

load_dotenv()

app = FastAPI(title="TradeCore Bridge", description="HTTP to Redis Bridge for Postman Testing")

# Redis Config
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

class StartTradingRequest(BaseModel):
    user_id: str
    access_token: str
    capital: float = 100000
    trade_mode: str = "VIRTUAL"

@app.post("/start-trading")
async def start_trading(data: StartTradingRequest):
    """
    Simulates the START_TRADING command from Node.js
    """
    try:
        r = redis.from_url(REDIS_URL, decode_responses=True)
        
        command = {
            "action": "START_TRADING",
            "user_id": data.user_id,
            "data": {
                "access_token": data.access_token,
                "strategy_config": {
                    "trade_mode": data.trade_mode,
                    "capital": data.capital
                }
            }
        }
        
        await r.publish("trading:commands", json.dumps(command))
        await r.close()
        
        return {
            "status": "success", 
            "message": f"Command sent for {data.user_id}", 
            "payload": command
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/stop-trading")
async def stop_trading(user_id: str):
    """
    Simulates the STOP_TRADING command
    """
    try:
        r = redis.from_url(REDIS_URL, decode_responses=True)
        
        command = {
            "action": "STOP_TRADING",
            "user_id": user_id,
            "data": {}
        }
        
        await r.publish("trading:commands", json.dumps(command))
        await r.close()
        
        return {"status": "success", "message": f"Stop command sent for {user_id}"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    print("⚠️  Requires 'fastapi' and 'uvicorn' installed.")
    print("👉 Run: pip install fastapi uvicorn")
    print("👉 Then: uvicorn http_bridge:app --reload")
    uvicorn.run(app, host="0.0.0.0", port=8000)
