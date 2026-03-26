# ChatGPT Scraper API

FastAPI server that scrapes ChatGPT via Playwright and exposes the responses through a clean REST API.

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
```

Copy `.env` and fill in your Google credentials:

```bash
cp .env.example .env
```

## Run

```bash
python run.py
```

Server starts at `http://localhost:8000`. Docs at `/docs`.

## Endpoints

### `POST /ask` — JSON response (Postman-friendly)

```json
// Request
{ "prompt": "What is 2 + 2?" }

// Response
{ "status": "ok", "response": "2 + 2 equals 4.", "error": null }
```

### `POST /ask/stream` — SSE streaming

Same request body, returns `text/event-stream` with events: `start`, `message` (deltas), `done`, `error`.

### `GET /health`

Returns server/browser status.

### `POST /screenshot`

Saves a debug screenshot, returns the file path.

### `POST /session/invalidate`

Deletes saved session — next restart will re-authenticate.

## Test Client

```bash
# JSON mode (default) — prints response and exits
python test_client.py "What is 2 + 2?"

# SSE streaming mode
python test_client.py --stream "Tell me a joke"
```

## Project Structure

```
app/
├── __init__.py
├── main.py        # FastAPI app, lifespan, CORS
├── config.py      # .env config
├── models.py      # Pydantic schemas
├── browser.py     # Playwright ChatGPT automation
└── routes/
    ├── __init__.py
    └── ask.py     # All endpoints
run.py             # Entry point
test_client.py     # CLI test client
```
