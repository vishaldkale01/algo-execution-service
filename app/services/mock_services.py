from typing import Dict, List, Tuple, Any
from datetime import datetime
from app.services.replay_service import MarketReplayService

class MockMarketDataService:
    """
    Mocks MarketDataService using ReplayService as the source of truth.
    """
    def __init__(self, replay_service: MarketReplayService):
        self.replay_service = replay_service
        # Simulate an Option Chain state
        # In a real replay, we'd load full option chain history.
        # For MVP, we'll auto-generate a synthetic chain around the Spot Price.
        
    async def get_market_status(self, instrument_key: str) -> float:
        # Return current Spot Price from Replay
        return self.replay_service.get_current_price()
        
    async def fetch_historical_data(self, instrument_key: str, interval: str, days: int) -> List[Dict]:
        # During replay, we might not need this if we pre-load data.
        # Or we can return a slice of history up to current_time.
        return [] 

    async def fetch_option_chain(self, instrument_key: str, expiry_date: str) -> Dict:
        """
        Generate a synthetic option chain based on current spot price.
        """
        spot = self.replay_service.get_current_price()
        if spot == 0: return {}
        
        # Round to nearest 100
        atm = round(spot / 100) * 100
        
        # Create a fake structure mimicking Upstox response
        # We only need enough data for extract_target_strikes to work
        # i.e., Call/Put OI and LTP.
        
        chain = []
        
        # Generate 5 strikes up/down
        for strike in range(atm - 500, atm + 600, 100):
            # Synthetic OI (Random or based on trend?)
            # Let's make it static for now, or random variance
            # For testing OI logic, we might need better control.
            
            chain.append({
                "strike_price": strike,
                "call_options": {
                    "market_data": {
                        "oi": 100000, 
                        "ltp": max(0.05, spot - strike + 20) if spot > strike else max(0.05, 20 - (strike - spot)*0.5) 
                    },
                    "instrument_key": f"NSE_FO|BANKNIFTY....{strike}CE"
                },
                "put_options": {
                    "market_data": {
                        "oi": 100000,
                        "ltp": max(0.05, strike - spot + 20) if strike > spot else max(0.05, 20 - (spot - strike)*0.5)
                    },
                    "instrument_key": f"NSE_FO|BANKNIFTY....{strike}PE"
                }
            })
            
        return {"data": chain}

    def extract_target_strikes(self, option_chain: Dict, spot_price: float, step: int = 100) -> Tuple[List[str], Dict]:
        # Reuse logic from original service or reimplement simplified version
        # Let's copy the logic slightly simplified
        
        data = option_chain.get('data', [])
        if not data: return [], {}
        
        calls = {}
        puts = {}
        
        total_call_oi = 0
        total_put_oi = 0
        
        for item in data:
            strike = item['strike_price']
            if 'call_options' in item:
                calls[strike] = item['call_options']
            if 'put_options' in item:
                puts[strike] = item['put_options']
                
        # Calculate PCR
        for strike in calls:
            if strike in calls and strike in puts:
                total_call_oi += calls[strike]['market_data'].get('oi', 0)
                total_put_oi += puts[strike]['market_data'].get('oi', 0)
                
        pcr = total_put_oi / total_call_oi if total_call_oi > 0 else 0
        
        atm_strike = round(spot_price / step) * step
        
        target_strikes = []
        # Get ATM, ITM, OTM... for now just return ATM keys
        if atm_strike in calls:
            target_strikes.append(calls[atm_strike]['instrument_key'])
        if atm_strike in puts:
            target_strikes.append(puts[atm_strike]['instrument_key'])
            
        return target_strikes, {
            "pcr": pcr,
            "total_call_oi": total_call_oi,
            "total_put_oi": total_put_oi,
            "atm_strike": atm_strike
        }

class MockExecutionService:
    """
    Simulates Order Execution.
    Unconditionally fills orders at current market price (or logic).
    """
    def __init__(self, replay_service: MarketReplayService):
        self.replay_service = replay_service
        self.orders = []
        
    async def place_order(self, instrument_key: str, transaction_type: str, quantity: int, order_type: str, price: float = 0.0, tag: str = None, **kwargs) -> Dict:
        
        # Determine Fill Price
        # For Market Replay, we assume fill at Current 'Close' (conservative)
        fill_price = self.replay_service.get_current_price()
        
        # If it's an Option, we don't have the Option's price in ReplayService (it only tracks Index).
        # We must approximate Option Price.
        # Black-Scholes is overkill. 
        # Intrinsic Value + Time Value? 
        # Or just log it and assume PnL calc happens elsewhere?
        # User's 'ActiveTradeContext' updates PnL based on `market_data_service` feeds.
        # In Replay, `on_market_data` will receive Index Candles.
        # But `ActiveTradeContext` needs updates on the OPTION price.
        # This is the tricky part of Replay. 
        
        # SOLUTON: active_trade.update() calls handle the trailing logic based on 'current_price'.
        # We need to simulate the OPTION candle stream too.
        # For now, let's auto-calculate a Dummy Option Price:
        # Option Price = Intrinsic + decay? 
        # Let's assume Delta=0.5.
        # We'd need to track the Entry Spot Price to calculate PnL delta.
        
        order_id = f"MOCK_{len(self.orders)+1}"
        
        self.orders.append({
            "order_id": order_id,
            "type": transaction_type,
            "qty": quantity,
            "instrument": instrument_key,
            "price": fill_price,  # This might be Index Price, which is wrong for Option
            "timestamp": self.replay_service.current_time
        })
        
        print(f"[MOCK EXEC] Placed {transaction_type} {quantity} {instrument_key}")
        
        return {
            "status": "success",
            "data": {"order_id": order_id}
        }
        
    async def modify_order(self, *args, **kwargs):
        return True
        
    async def cancel_order(self, *args, **kwargs):
        return True
