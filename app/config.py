"""
config.py — centralised environment configuration
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Google OAuth credentials ──────────────────────────────────────────────────
# Only required when CDP_URL and USER_DATA_DIR are both unset (fresh login mode)
GOOGLE_EMAIL: str = os.getenv("GOOGLE_EMAIL", "")
GOOGLE_PASSWORD: str = os.getenv("GOOGLE_PASSWORD", "")

# ── Connection mode ────────────────────────────────────────────────────────────
#
#  MODE A — CDP (recommended): Connect to an already-running Chrome that you
#            manually logged into. Set CDP_URL=http://localhost:9222 and launch
#            Chrome once with --remote-debugging-port=9222.
#
#  MODE B — Persistent profile: Playwright launches Chromium but reuses a fixed
#            user-data directory on disk.  Set USER_DATA_DIR to a local path.
#            First run will need a manual login (headless=false); after that the
#            profile persists cookies / local-storage across restarts.
#
#  MODE C — session.json (original behaviour): Fresh Chromium + Google OAuth,
#            then saves cookies to SESSION_FILE for subsequent runs.
#            Needs GOOGLE_EMAIL + GOOGLE_PASSWORD.
#
CDP_URL: str = os.getenv("CDP_URL", "")          # e.g. http://localhost:9222
USER_DATA_DIR: str = os.getenv("USER_DATA_DIR", "")  # e.g. /home/you/.config/chatgpt-profile

# Validate: MODE C requires credentials
if not CDP_URL and not USER_DATA_DIR:
    if not GOOGLE_EMAIL or not GOOGLE_PASSWORD:
        raise RuntimeError(
            "Set CDP_URL (Mode A), USER_DATA_DIR (Mode B), "
            "or both GOOGLE_EMAIL + GOOGLE_PASSWORD (Mode C) in .env"
        )

# ── Browser / Playwright ──────────────────────────────────────────────────────
SESSION_FILE: str = os.getenv("SESSION_FILE", "./session.json")
HEADLESS: bool = os.getenv("HEADLESS", "true").lower() == "true"
SLOW_MO: int = int(os.getenv("SLOW_MO", "0"))
RESPONSE_TIMEOUT: int = int(os.getenv("RESPONSE_TIMEOUT", "120"))

# ── Server ────────────────────────────────────────────────────────────────────
HOST: str = os.getenv("HOST", "0.0.0.0")
PORT: int = int(os.getenv("PORT", "8000"))