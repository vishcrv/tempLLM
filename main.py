"""
main.py — FastAPI server
Exposes:
  POST /ask   → SSE stream of ChatGPT response
  GET  /health → health check
"""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from browser import ChatGPTBrowser

load_dotenv()

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("main")

# ── Config from env ────────────────────────────────────────────────────────────
GOOGLE_EMAIL      = os.getenv("GOOGLE_EMAIL", "")
GOOGLE_PASSWORD   = os.getenv("GOOGLE_PASSWORD", "")
SESSION_FILE      = os.getenv("SESSION_FILE", "./session.json")
HEADLESS          = os.getenv("HEADLESS", "true").lower() == "true"
SLOW_MO           = int(os.getenv("SLOW_MO", "0"))       # set ~150 for visual debugging
RESPONSE_TIMEOUT  = int(os.getenv("RESPONSE_TIMEOUT", "120"))

if not GOOGLE_EMAIL or not GOOGLE_PASSWORD:
    raise RuntimeError("GOOGLE_EMAIL and GOOGLE_PASSWORD must be set in .env")

# ── Single shared browser instance ────────────────────────────────────────────
gpt_browser: ChatGPTBrowser | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start browser on startup, clean up on shutdown."""
    global gpt_browser
    logger.info("Launching ChatGPT browser… (headless=%s)", HEADLESS)
    gpt_browser = ChatGPTBrowser(
        google_email=GOOGLE_EMAIL,
        google_password=GOOGLE_PASSWORD,
        session_file=SESSION_FILE,
        headless=HEADLESS,
        slow_mo=SLOW_MO,
        response_timeout=RESPONSE_TIMEOUT,
    )
    await gpt_browser.start()
    logger.info("Browser ready ✓")
    yield
    logger.info("Shutting down browser…")
    await gpt_browser.stop()


# ── App ────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="ChatGPT Scraper API",
    description="SSE-streaming endpoint that scrapes ChatGPT responses via Playwright",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / Response models ──────────────────────────────────────────────────
class AskRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=4000, description="The prompt to send to ChatGPT")


# ── SSE helpers ────────────────────────────────────────────────────────────────
def sse_event(data: str, event: str = "message") -> str:
    """Format a single SSE event."""
    # Escape newlines inside data field
    safe = data.replace("\n", "\\n")
    return f"event: {event}\ndata: {safe}\n\n"


async def stream_response(prompt: str):
    """
    Async generator that yields SSE-formatted events.
    Sent events:
      - event: message  → a chunk of text delta
      - event: done     → signals the stream is complete
      - event: error    → something went wrong
    """
    try:
        yield sse_event(json.dumps({"status": "started"}), event="start")

        full_response = []
        async for chunk in gpt_browser.ask_stream(prompt):
            full_response.append(chunk)
            payload = json.dumps({"delta": chunk})
            yield sse_event(payload, event="message")

        # Send final done event with full assembled text
        yield sse_event(
            json.dumps({"full_response": "".join(full_response)}),
            event="done",
        )

    except Exception as exc:
        logger.exception("Error during streaming: %s", exc)
        yield sse_event(json.dumps({"error": str(exc)}), event="error")


# ── Endpoints ──────────────────────────────────────────────────────────────────
@app.post(
    "/ask",
    summary="Send a prompt to ChatGPT and stream the response via SSE",
    response_description="Server-Sent Events stream",
)
async def ask(body: AskRequest):
    if gpt_browser is None:
        raise HTTPException(status_code=503, detail="Browser not initialised yet")

    return StreamingResponse(
        stream_response(body.prompt),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering if behind a proxy
        },
    )


@app.get("/health", summary="Health check")
async def health():
    return {
        "status": "ok",
        "browser_ready": gpt_browser is not None,
        "headless": HEADLESS,
        "session_exists": os.path.exists(SESSION_FILE),
    }


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=False,
        log_level="info",
    )

@app.post("/screenshot", summary="Take a debug screenshot of the current page")
async def take_screenshot():
    if gpt_browser is None:
        raise HTTPException(status_code=503, detail="Browser not initialised")
    path = await gpt_browser.screenshot()
    return {"screenshot_path": path}


@app.post(
    "/session/invalidate",
    summary="Delete saved session — next server restart will re-authenticate",
)
async def invalidate_session():
    if gpt_browser is None:
        raise HTTPException(status_code=503, detail="Browser not initialised")
    await gpt_browser.invalidate_session()
    return {"status": "session deleted — restart server to re-authenticate"}
