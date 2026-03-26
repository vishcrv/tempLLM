"""
test_client.py — Quick SSE test client
Usage:  python test_client.py "What is 2 + 2?"
"""

import sys
import json
import urllib.request

ENDPOINT = "http://localhost:8000/ask"
PROMPT   = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Tell me a short joke."

print(f"→ Sending prompt: {PROMPT!r}\n")

req = urllib.request.Request(
    ENDPOINT,
    data=json.dumps({"prompt": PROMPT}).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)

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
                # Print delta in-place without newline
                print(data.get("delta", "").replace("\\n", "\n"), end="", flush=True)
            elif event == "done":
                print("\n\n[stream complete]")
                break
            elif event == "error":
                print(f"\n[ERROR] {data.get('error')}")
                break