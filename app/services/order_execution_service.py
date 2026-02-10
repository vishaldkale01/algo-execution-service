import httpx
import uuid
from typing import Optional, Dict
from app.models.trade import TradeType, TradeStatus

class OrderExecutionService:
    """
    Handles Broker API interactions for Order Management.
    Supports PAPER_TRADING mode to bypass actual API calls.
    """
    
    def __init__(self, access_token: str, paper_trading: bool = False):
        self.base_url = "https://api.upstox.com/v2"
        self.access_token = access_token
        self.paper_trading = paper_trading
        
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}"
        }

    async def place_order(
        self, 
        instrument_key: str, 
        transaction_type: str, # BUY / SELL
        quantity: int,
        order_type: str = "MARKET",
        price: float = 0.0,
        trigger_price: float = 0.0,
        product: str = "I", # Intraday
        tag: str = None
    ) -> Dict:
        """
        Place an order via Upstox API.
        Returns Dict with 'order_id' or 'error'.
        """
        
        req_id = tag or str(uuid.uuid4())[:10]
        
        # 1. Paper Trading Simulation
        # 1. Paper Trading Simulation
        if self.paper_trading:
            print(f"[PAPER] TRADE: {transaction_type} {quantity} {instrument_key} @ {order_type} {price}")
            return {
                "status": "success",
                "data": {"order_id": f"PAPER_{uuid.uuid4().hex[:8]}"},
                "simulated": True
            }

        # 2. Real API Call
        url = f"{self.base_url}/order/place"
        
        body = {
            "quantity": quantity,
            "product": product,
            "validity": "DAY",
            "price": price,
            "tag": req_id,
            "instrument_token": instrument_key,
            "order_type": order_type,
            "transaction_type": transaction_type,
            "disclosed_quantity": 0,
            "trigger_price": trigger_price,
            "is_amo": False
        }
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=body, headers=self.headers)
                
                if response.status_code == 200:
                    resp_json = response.json()
                    if resp_json['status'] == 'success':
                        return resp_json # contains data.order_id
                    else:
                        print(f"[ERROR] Order Rejected: {resp_json}")
                        return {"status": "error", "message": str(resp_json)}
                else:
                     print(f"[ERROR] API Error {response.status_code}: {response.text}")
                     return {"status": "error", "message": response.text}
                     
            except Exception as e:
                print(f"[ERROR] Exception placing order: {e}")
                return {"status": "error", "message": str(e)}

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order"""
        if self.paper_trading or order_id.startswith("PAPER_"):
            print(f"[PAPER] CANCEL: {order_id}")
            return True
            
        url = f"{self.base_url}/order/cancel"
        params = {"order_id": order_id}
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.delete(url, params=params, headers=self.headers)
                return response.status_code == 200
            except Exception as e:
                print(f"[ERROR] Cancel Failed: {e}")
                return False

    async def modify_order(
        self, 
        order_id: str, 
        order_type: str = None, 
        price: float = 0.0, 
        trigger_price: float = 0.0,
        quantity: int = None
    ) -> bool:
        """Modify an open order (e.g. SL modification)"""
        
        if self.paper_trading or order_id.startswith("PAPER_"):
            print(f"[PAPER] MODIFY: {order_id} -> SL {trigger_price}")
            return True
            
        url = f"{self.base_url}/order/modify"
        
        body = {
            "order_id": order_id,
            "validity": "DAY",
            "price": price,
            "order_type": order_type, # MARKET, LIMIT, SL, SL-M
            "trigger_price": trigger_price,
            "quantity": quantity
        }
        # Filter None
        body = {k: v for k, v in body.items() if v is not None}
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.put(url, json=body, headers=self.headers)
                return response.status_code == 200
            except Exception as e:
                print(f"[ERROR] Modify Failed: {e}")
                return False

    async def get_order_history(self, order_id: str = None) -> Dict:
        """Fetch order status details"""
        if self.paper_trading:
             # Simulation: Always return 'filled' for simplicity in demo
             # unless we build a complex mock broker.
             return {"status": "complete", "details": "Paper Trade"}
        
        url = f"{self.base_url}/order/history"
        params = {"order_id": order_id} if order_id else {}
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, params=params, headers=self.headers)
                return response.json()
            except Exception as e:
                return {}
