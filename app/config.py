"""
config.py — centralised environment configuration
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Connection mode ────────────────────────────────────────────────────────────
#
#  MODE A — CDP (recommended)
#           Connect to an already-running Chrome via Chrome DevTools Protocol.
#           Set CDP_URL=http://127.0.0.1:9222
#
#  MODE B — Fallback (no login)
#           Playwright launches fresh Chromium, restores session.json if it
#           exists, and goes straight to ChatGPT. No login flow — ever.
#           If not authenticated, the server will error rather than prompt.
#
CDP_URL: str = os.getenv("CDP_URL", "")

# ── Browser / Playwright ──────────────────────────────────────────────────────
SESSION_FILE: str     = os.getenv("SESSION_FILE", "./session.json")
HEADLESS: bool        = os.getenv("HEADLESS", "false").lower() == "true"
SLOW_MO: int          = int(os.getenv("SLOW_MO", "0"))
RESPONSE_TIMEOUT: int = int(os.getenv("RESPONSE_TIMEOUT", "120"))

# ── Server ────────────────────────────────────────────────────────────────────
HOST: str = os.getenv("HOST", "0.0.0.0")
PORT: int = int(os.getenv("PORT", "8000"))