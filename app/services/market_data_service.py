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
        strike_metadata['total_call_oi'] = total_call_oi
        strike_metadata['total_put_oi'] = total_put_oi

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
                    
                    if 'data' in data:
                        feed_data = data['data']
                        
                        # 1. Direct lookup
                        if instrument_key in feed_data:
                            return feed_data[instrument_key]['last_price']
                        
                        # 2. Try fuzzy matching (separators | vs : and spaces)
                        for key, details in feed_data.items():
                            # Normalize: treat | and : as same, spaces as %20
                            k_norm = key.replace('|', ':').replace(' ', '%20')
                            i_norm = instrument_key.replace('|', ':').replace(' ', '%20')
                            
                            if k_norm == i_norm:
                                print(f"[WARN] Key mismatch handled: Requested '{instrument_key}', Found '{key}'")
                                return details['last_price']
                                
                        # 3. Debug if still not found
                        print(f"[ERROR] Market Status: Key '{instrument_key}' not found in response keys: {list(feed_data.keys())}")
                        print(f"[DEBUG] Full Response: {data}")
                        
                    else:
                        print(f"[ERROR] Market Status: 'data' field missing in response: {data}")

            except Exception as e:
                print(f"[ERROR] Exception fetching market status: {e}")
        return 0.0

    async def fetch_historical_data(self, instrument_key: str, interval: str = "1minute", days: int = 5) -> List[Dict]:
        """
        Fetch historical candles to warm up indicators.
        interval: 1minute, 5minute, 30minute, day
        """
        # Calculate to_date and from_date
        to_date = datetime.now().strftime("%Y-%m-%d")
        from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        
        url = f"https://api.upstox.com/v2/historical-candle/{instrument_key}/{interval}/{to_date}/{from_date}"
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers={"Accept": "application/json"})
                if response.status_code == 200:
                    data = response.json()
                    if "data" in data and "candles" in data["data"]:
                        # Convert to standard format
                        candles = []
                        for c in data["data"]["candles"]:
                            # Upstox Format: [timestamp, open, high, low, close, volume, oi]
                            candles.append({
                                'timestamp': datetime.fromisoformat(c[0]),
                                'open': float(c[1]),
                                'high': float(c[2]),
                                'low': float(c[3]),
                                'close': float(c[4]),
                                'volume': float(c[5])
                            })
                        # Sort by timestamp ascending
                        candles.sort(key=lambda x: x['timestamp'])
                        print(f"[INFO] Fetched {len(candles)} historical candles for {instrument_key}")
                        return candles
                
                print(f"[WARN] Failed to fetch history: {response.status_code} - {response.text}")
                return []
                
            except Exception as e:
                print(f"[ERROR] Exception fetching history: {e}")
                return []
