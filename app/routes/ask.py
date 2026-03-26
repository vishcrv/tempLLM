"""
routes/ask.py — All API endpoints
"""

import json
import logging
import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.models import AskRequest, AskResponse

logger = logging.getLogger("routes.ask")

router = APIRouter()


# ── SSE helpers ────────────────────────────────────────────────────────────────

def sse_event(data: str, event: str = "message") -> str:
    """Format a single SSE event."""
    safe = data.replace("\n", "\\n")
    return f"event: {event}\ndata: {safe}\n\n"


async def _stream_sse(prompt: str):
    """
    Async generator yielding SSE-formatted events.
    Events: start → message (chunks) → done | error
    """
    from app.main import gpt_browser  # deferred to avoid circular import

    try:
        yield sse_event(json.dumps({"status": "started"}), event="start")

        full_response: list[str] = []
        async for chunk in gpt_browser.ask_stream(prompt):
            full_response.append(chunk)
            yield sse_event(json.dumps({"delta": chunk}), event="message")

        yield sse_event(
            json.dumps({"full_response": "".join(full_response)}),
            event="done",
        )

    except Exception as exc:
        logger.exception("Error during streaming: %s", exc)
        yield sse_event(json.dumps({"error": str(exc)}), event="error")


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post(
    "/ask",
    response_model=AskResponse,
    summary="Send a prompt to ChatGPT and receive a JSON response",
)
async def ask(body: AskRequest):
    """
    Collects the full streamed response and returns it as a single JSON object.
    Ideal for Postman, curl, and any HTTP client that doesn't support SSE.
    """
    from app.main import gpt_browser

    if gpt_browser is None:
        raise HTTPException(status_code=503, detail="Browser not initialised yet")

    try:
        chunks: list[str] = []
        async for chunk in gpt_browser.ask_stream(body.prompt):
            chunks.append(chunk)

        return AskResponse(status="ok", response="".join(chunks))

    except Exception as exc:
        logger.exception("Error in /ask: %s", exc)
        return AskResponse(status="error", error=str(exc))


@router.post(
    "/ask/stream",
    summary="Send a prompt to ChatGPT and stream the response via SSE",
    response_description="Server-Sent Events stream",
)
async def ask_stream(body: AskRequest):
    """SSE streaming endpoint — use this from frontends that consume EventSource."""
    from app.main import gpt_browser

    if gpt_browser is None:
        raise HTTPException(status_code=503, detail="Browser not initialised yet")

    return StreamingResponse(
        _stream_sse(body.prompt),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/health", summary="Health check")
async def health():
    from app.main import gpt_browser
    from app.config import SESSION_FILE, HEADLESS

    return {
        "status": "ok",
        "browser_ready": gpt_browser is not None,
        "headless": HEADLESS,
        "session_exists": os.path.exists(SESSION_FILE),
    }


@router.post("/screenshot", summary="Take a debug screenshot of the current page")
async def take_screenshot():
    from app.main import gpt_browser

    if gpt_browser is None:
        raise HTTPException(status_code=503, detail="Browser not initialised")
    path = await gpt_browser.screenshot()
    return {"screenshot_path": path}


@router.post(
    "/session/invalidate",
    summary="Delete saved session — next server restart will re-authenticate",
)
async def invalidate_session():
    from app.main import gpt_browser

    if gpt_browser is None:
        raise HTTPException(status_code=503, detail="Browser not initialised")
    await gpt_browser.invalidate_session()
    return {"status": "session deleted — restart server to re-authenticate"}
