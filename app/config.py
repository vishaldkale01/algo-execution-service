import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    UPSTOX_API_KEY = os.getenv("UPSTOX_API_KEY")
    UPSTOX_API_SECRET = os.getenv("UPSTOX_API_SECRET")
    UPSTOX_REDIRECT_URI = os.getenv("UPSTOX_REDIRECT_URI")
    MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    PORT = int(os.getenv("PORT", 8000))

settings = Settings()
