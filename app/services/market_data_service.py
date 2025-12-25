import httpx
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

class MarketDataService:
    def __init__(self, access_token: str):
        self.base_url = "https://api.upstox.com/v2"
        self.access_token = access_token
        self.headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}"
        }

    async def fetch_option_chain(self, instrument_key: str, expiry_date: str) -> Dict:
        """
        Fetch option chain for a given instrument and expiry.
        instrument_key: e.g., 'NSE_INDEX|Nifty Bank'
        expiry_date: e.g., '2025-12-25'
        """
        url = f"{self.base_url}/option/chain"
        params = {
            "instrument_key": instrument_key,
            "expiry_date": expiry_date
        }
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, params=params, headers=self.headers)
                if response.status_code == 200:
                    return response.json()
                else:
                    print(f"❌ Error fetching option chain: {response.status_code} - {response.text}")
                    return {}
            except Exception as e:
                print(f"❌ Exception fetching option chain: {e}")
                return {}

    def extract_target_strikes(self, option_chain: Dict, spot_price: float, step: int = 100) -> Tuple[List[str], Dict]:
        """
        Identify ATM, +1/-1 ITM/OTM strikes and return instrument_keys and metadata.
        Returns: 
            - List of instrument keys to subscribe to.
            - Dict of strike metadata (LTP, OI, etc.) for trend analysis.
        """
        if not option_chain or 'data' not in option_chain:
            return [], {}

        chain_data = option_chain['data']
        
        # 1. Find the closest ATM strike
        # Strikes are keys in the response list usually, but Upstox returns detailed list.
        # We need to parse valid strikes.
        
        # Structure of Upstox Option Chain response is a list of objects.
        # We need to organize by strike price.
        
        calls = {}
        puts = {}
        
        for entry in chain_data:
            strike_price = entry['strike_price']
            if entry['call_options']:
                calls[strike_price] = entry['call_options']
            if entry['put_options']:
                puts[strike_price] = entry['put_options']

        # Calculate Spot ATM
        atm_strike = round(spot_price / step) * step
        
        target_strikes = [
            atm_strike - step, # OTM Call / ITM Put
            atm_strike,        # ATM
            atm_strike + step  # ITM Call / OTM Put
        ]
        
        subscription_keys = []
        strike_metadata = {
            "pcr": 0.0,
            "strikes": {}
        }

        total_call_oi = 0
        total_put_oi = 0

        # Iterate all to calc PCR (Global context)
        for strike in calls:
            if strike in calls and strike in puts:
                total_call_oi += calls[strike]['market_data'].get('oi', 0)
                total_put_oi += puts[strike]['market_data'].get('oi', 0)

        strike_metadata['pcr'] = total_put_oi / total_call_oi if total_call_oi > 0 else 0

        # Extract specific keys for subscription
        for strike in target_strikes:
            if strike in calls:
                ce_data = calls[strike]
                ce_key = ce_data['instrument_key']
                subscription_keys.append(ce_key)
                
                strike_metadata['strikes'][f"{strike}_CE"] = {
                    "instrument_key": ce_key,
                    "ltp": ce_data['market_data']['ltp'],
                    "oi": ce_data['market_data']['oi'],
                    "volume": ce_data['market_data']['volume'],
                    "type": "CE",
                    "strike": strike
                }

            if strike in puts:
                pe_data = puts[strike]
                pe_key = pe_data['instrument_key']
                subscription_keys.append(pe_key)
                
                strike_metadata['strikes'][f"{strike}_PE"] = {
                    "instrument_key": pe_key,
                    "ltp": pe_data['market_data']['ltp'],
                    "oi": pe_data['market_data']['oi'],
                    "volume": pe_data['market_data']['volume'],
                    "type": "PE",
                    "strike": strike
                }
                
        return subscription_keys, strike_metadata

    async def get_market_status(self, instrument_key: str = "NSE_INDEX|Nifty Bank") -> float:
        """Helper to get current index spot price to find ATM"""
        # In a real scenario, we might use the last cached WebSocket tick.
        # But for initial setup, we can query a quote.
        url = f"{self.base_url}/market-quote/ltp"
        params = {"instrument_key": instrument_key}
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, params=params, headers=self.headers)
                if response.status_code == 200:
                    data = response.json()
                    # Response format: "data": { "NSE_INDEX|Nifty Bank": { "last_price": 12345.65, ... } }
                    if 'data' in data and instrument_key in data['data']:
                        return data['data'][instrument_key]['last_price']
            except Exception:
                pass
        return 0.0
