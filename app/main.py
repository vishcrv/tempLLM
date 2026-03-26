"""
main.py — FastAPI application factory
Exposes:
  POST /ask          → JSON response (Postman-friendly)
  POST /ask/stream   → SSE stream of ChatGPT response
  GET  /health       → health check
  POST /screenshot   → debug screenshot
  POST /session/invalidate → clear saved session
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import (
    GOOGLE_EMAIL,
    GOOGLE_PASSWORD,
    SESSION_FILE,
    HEADLESS,
    SLOW_MO,
    RESPONSE_TIMEOUT,
)
from app.browser import ChatGPTBrowser
from app.routes.ask import router as ask_router

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("main")

# ── Single shared browser instance ────────────────────────────────────────────
gpt_browser: ChatGPTBrowser | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start browser on startup, clean up on shutdown."""
    global gpt_browser
    logger.info("Launching ChatGPT browser (headless=%s)", HEADLESS)
    gpt_browser = ChatGPTBrowser(
        google_email=GOOGLE_EMAIL,
        google_password=GOOGLE_PASSWORD,
        session_file=SESSION_FILE,
        headless=HEADLESS,
        slow_mo=SLOW_MO,
        response_timeout=RESPONSE_TIMEOUT,
    )
    await gpt_browser.start()
    logger.info("Browser initialisation complete and ready")
    yield
    logger.info("Initiating browser shutdown sequence")
    await gpt_browser.stop()


# ── App ────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="ChatGPT Scraper API",
    description=(
        "JSON + SSE-streaming endpoints that scrape ChatGPT responses "
        "via Playwright"
    ),
    version="1.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ask_router)
