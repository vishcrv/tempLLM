"""
main.py — FastAPI application factory
"""

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
    CDP_URL,
    USER_DATA_DIR,
)
from app.browser import ChatGPTBrowser
from app.routes.ask import router as ask_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("main")

gpt_browser: ChatGPTBrowser | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global gpt_browser

    mode = (
        "A-CDP" if CDP_URL
        else "B-PersistentProfile" if USER_DATA_DIR
        else "C-OAuth"
    )
    logger.info("Launching ChatGPT browser — mode=%s headless=%s", mode, HEADLESS)

    gpt_browser = ChatGPTBrowser(
        google_email=GOOGLE_EMAIL,
        google_password=GOOGLE_PASSWORD,
        session_file=SESSION_FILE,
        headless=HEADLESS,
        slow_mo=SLOW_MO,
        response_timeout=RESPONSE_TIMEOUT,
        cdp_url=CDP_URL,
        user_data_dir=USER_DATA_DIR,
    )
    await gpt_browser.start()
    logger.info("Browser ready")
    yield
    logger.info("Shutting down browser")
    await gpt_browser.stop()


app = FastAPI(
    title="ChatGPT Scraper API",
    description=(
        "JSON + SSE-streaming endpoints that scrape ChatGPT responses "
        "via Playwright. Supports CDP, persistent-profile, and OAuth modes."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ask_router)