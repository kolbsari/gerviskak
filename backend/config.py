"""Model registry and API key loading."""

import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

MODELS = [
    {
        "id": "gpt-4o-mini",
        "name": "GPT-4o Mini",
        "provider": "openai",
        "model_string": "gpt-4o-mini",
        "api_base": None,
    },
    {
        "id": "gpt-4o",
        "name": "GPT-4o",
        "provider": "openai",
        "model_string": "gpt-4o",
        "api_base": None,
    },
]

# Build a lookup dict for fast access
MODELS_BY_ID: dict = {m["id"]: m for m in MODELS}

API_KEYS = {
    "openai": os.getenv("OPENAI_API_KEY", ""),
}

STOCKFISH_PATH = os.getenv("STOCKFISH_PATH", "stockfish")
