"""
config.py — centralised environment configuration
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Google OAuth credentials ──────────────────────────────────────────────────
GOOGLE_EMAIL: str = os.getenv("GOOGLE_EMAIL", "")
GOOGLE_PASSWORD: str = os.getenv("GOOGLE_PASSWORD", "")

if not GOOGLE_EMAIL or not GOOGLE_PASSWORD:
    raise RuntimeError("GOOGLE_EMAIL and GOOGLE_PASSWORD must be set in .env")

# ── Browser / Playwright ──────────────────────────────────────────────────────
SESSION_FILE: str = os.getenv("SESSION_FILE", "./session.json")
HEADLESS: bool = os.getenv("HEADLESS", "true").lower() == "true"
SLOW_MO: int = int(os.getenv("SLOW_MO", "0"))
RESPONSE_TIMEOUT: int = int(os.getenv("RESPONSE_TIMEOUT", "120"))

# ── Server ────────────────────────────────────────────────────────────────────
HOST: str = os.getenv("HOST", "0.0.0.0")
PORT: int = int(os.getenv("PORT", "8000"))
