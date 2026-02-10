import os
import json
import asyncio
import google.generativeai as genai
from datetime import datetime
from typing import Tuple, Dict, Any

class AIValidator:
    """
    Acts as a 'Senior Trader' using Gemini API to validate signals.
    """
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if self.api_key:
            genai.configure(api_key=self.api_key)
            self.model = genai.GenerativeModel('gemini-1.5-flash')
        else:
            self.model = None

    async def validate_signal(self, context: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Validates a signal using LLM.
        Returns (is_approved, reason).
        """
        if not self.model:
            return True, "No API Key configured. Defaulting to GO."

        # Prepare Prompt
        prompt = f"""
        Act as a professional Bank Nifty scalper. Validate this signal:
        Signal: {context.get('signal_data', {})}
        Market Context: {context.get('market_context', {})}
        Symbol: {context.get('instrument', 'BANKNIFTY')}
        
        Indicators:
        - ADX: {context.get('adx', 'N/A')}
        - Price Position: {context.get('price_pos', 'N/A')}
        - Pattern: {context.get('pattern', 'N/A')}
        
        Recent Candles (1-min):
        {context.get('recent_candles', [])}

        Instructions:
        1. Repy ONLY with valid JSON.
        2. Format: {{"verdict": "GO" or "NO_GO", "reason": "concise explanation", "confidence": 1-10}}
        3. Be conservative. If volatility is dry or patterns are messy, reject.
        """

        try:
            # Run in thread/executor if the library isn't fully async
            # or use async generate_content if available
            response = await asyncio.to_thread(
                self.model.generate_content, 
                prompt,
                generation_config=genai.types.GenerationConfig(
                    response_mime_type="application/json"
                )
            )
            
            res_json = json.loads(response.text)
            verdict = res_json.get("verdict", "NO_GO")
            reason = res_json.get("reason", "Unknown AI reason")
            
            return verdict == "GO", reason
            
        except Exception as e:
            print(f"[REPLAY] AI Validation Error: {e}")
            return True, f"AI Error: {str(e)}. Defaulting to GO."
