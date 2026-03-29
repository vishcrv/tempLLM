# Update: Supervisor Daemon & IPv6 DNS Fixes

**Date:** March 29, 2026

## 1. Automated Status Supervisor
**Why:** The `status.js` tool was a simple one-shot ping tool. We needed it to aggressively guarantee Chrome launched *before* the Python server, and we needed it to sit in the background proactively managing their lifespans.
**How:** 
- Upgraded `scripts/status.js` into an attached CLI daemon.
- When initialized, it hooks into OS-level detectors (`init.js` logic), launching Chrome via `--remote-debugging-port=9222` and polling until the TCP socket responds.
- It then boots `run.py` and initiates an endless `setInterval` loop, surveying the health of both ports every 3 seconds.
- Introduced a "Kill both if no" clean-up mechanism: If the user manually closes the Chrome browser or the Python Server crashes abruptly, `status.js` instantly hits system routes (`pkill` / `Stop-Process`) to extinguish the surviving process before exiting gracefully.

## 2. Windows IPv6 Localhost DNS Bug
**Why:** Even though Chrome reliably started in Mode A (CDP), the Python `templlm` backend rejected it as unresponsive and forcefully dropped back to a headless Mode B connection.
**How:** 
- Investigated the Python backend probe and found `urllib.request.urlopen("http://localhost:9222")` was resolving to the IPv6 standard `[::1]` initially on Windows, dropping into a hard 2-second timeout before parsing Chrome's native IPv4 `127.0.0.1` listener. 
- Patched `_cdp_is_reachable()` in `app/browser.py` to securely sanitize and replace `localhost` strings dynamically with the explicit `127.0.0.1` IPv4 loopback socket.
- Modified the `.env` generator mapped in `scripts/init.js` to universally output `CDP_URL=http://127.0.0.1:9222` to avoid upstream configuration hazards.

easy to undeerstand:
1. i transformed status.js into a true supervisor that boots chrome, then server, and if either one crashes it immediately kills both.
2. fixed a weird bug on windows where localhost delayed the server for 2 seconds searching for IPv6, making python think chrome was closed. switched to strict 127.0.0.1 bindings instead!
