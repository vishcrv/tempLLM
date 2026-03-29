"""
test_client.py — Quick test client for the ChatGPT Scraper API

JSON mode (default):
    python test_client.py "What is 2 + 2?"

SSE streaming mode:
    python test_client.py --stream "Tell me a short joke."
"""

import sys
import json
import urllib.request

ENDPOINT = "http://127.0.0.1:8000"


def ask_json(prompt: str) -> None:
    """Hit POST /ask — get a single JSON response and exit."""
    url = f"{ENDPOINT}/ask"
    req = urllib.request.Request(
        url,
        data=json.dumps({"prompt": prompt}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    print(f"→ POST {url}")
    print(f"→ Prompt: {prompt!r}\n")

    with urllib.request.urlopen(req) as resp:
        body = json.loads(resp.read().decode())

    print(json.dumps(body, indent=2))

    if body.get("status") == "ok":
        print(f"\n✅ Response received ({len(body.get('response', ''))} chars)")
    else:
        print(f"\n❌ Error: {body.get('error')}")


def ask_stream(prompt: str) -> None:
    """Hit POST /ask/stream — consume SSE events and exit when done."""
    url = f"{ENDPOINT}/ask/stream"
    req = urllib.request.Request(
        url,
        data=json.dumps({"prompt": prompt}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    print(f"→ POST {url}")
    print(f"→ Prompt: {prompt!r}\n")

    event = ""
    with urllib.request.urlopen(req) as resp:
        for raw_line in resp:
            line = raw_line.decode().strip()
            if not line:
                continue

            if line.startswith("event:"):
                event = line[len("event:"):].strip()
            elif line.startswith("data:"):
                raw_data = line[len("data:"):].strip()
                try:
                    data = json.loads(raw_data)
                except json.JSONDecodeError:
                    data = {"raw": raw_data}

                if event == "start":
                    print("[stream started]")
                elif event == "message":
                    print(data.get("delta", "").replace("\\n", "\n"), end="", flush=True)
                elif event == "done":
                    print("\n\n[stream complete]")
                    break
                elif event == "error":
                    print(f"\n[ERROR] {data.get('error')}")
                    break


if __name__ == "__main__":
    args = sys.argv[1:]
    stream_mode = False

    if "--stream" in args:
        stream_mode = True
        args.remove("--stream")

    prompt = " ".join(args) if args else "Tell me a short joke."

    if stream_mode:
        ask_stream(prompt)
    else:
        ask_json(prompt)
