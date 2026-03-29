# npm CLI + cross-platform setup — what changed

## session summary
date: 2026-03-29

---

## problems fixed

| problem | fix |
|---------|-----|
| `ConnectionRefusedError` on `test_client.py` | server wasn't running — user needed to start `python run.py` first |
| `localhost` not resolving to `127.0.0.1` on Arch Linux | changed `ENDPOINT` in `test_client.py` from `localhost` to `127.0.0.1` |
| npm global install failing with `EACCES` (writes to `/usr/lib/node_modules`) | set npm prefix to `~/.local` via `npm config set prefix ~/.local` |
| `templlm` command not found after install | `~/.local/bin` not in `$PATH` — added export to `~/.zshrc` and created `~/.zprofile`; symlinked to `~/.cargo/bin` (already in PATH) |
| `requirements.txt` encoded as UTF-16 | converted to UTF-8 with `iconv` |

---

## new files

### `bin/cli.js`
node.js CLI entry point. zero external dependencies (stdlib only).

**commands:**
```
templlm init                  interactive setup wizard
templlm <prompt>              single JSON response
templlm --stream <prompt>     streaming SSE response
templlm --setup               re-run ChatGPT browser login
```

**auto-server-spawn:** if port 8000 is not open when a prompt is sent, the CLI spawns `python run.py` as a detached background process and polls `/docs` until the server is ready (up to 60s). no manual `python run.py` needed.

### `scripts/init.js`
interactive setup wizard — runs when user calls `templlm init`.

**what it does:**
1. detects OS (`process.platform` + `/etc/os-release` for Linux distro)
2. checks Python — if missing, prints the correct install command for the detected OS/distro
3. asks user to choose connection mode:
   - **Mode A — CDP** (recommended): connect to existing Chrome session
   - **Mode B — Headless**: Playwright manages its own Chromium
4. for Mode A: prints the exact `--remote-debugging-port=9222` Chrome launch command for their OS
5. writes `CDP_URL` to `.env` automatically
6. optionally runs `python cli.py --setup` (browser login flow)

**OS/distro aware for:** Arch, Manjaro, Ubuntu, Debian, Fedora, CentOS, openSUSE, macOS, Windows.

### `scripts/postinstall.js`
runs automatically on `npm install` / `npm install -g templlm`.

1. detects `python3` or `python` binary
2. runs `pip install -r requirements.txt --quiet`
3. runs `python -m playwright install chromium`
4. if anything fails, prints manual fallback commands and exits cleanly (non-fatal)

### `package.json`
```json
{
  "name": "templlm",
  "bin": { "templlm": "./bin/cli.js" },
  "scripts": { "postinstall": "node scripts/postinstall.js" },
  "files": ["bin/", "app/", "run.py", "cli.py", "requirements.txt", "scripts/"],
  "engines": { "node": ">=18" }
}
```
`files` field ensures the Python server code is bundled with the npm package so it works after `npm install -g templlm` from the registry.

---

## modified files

### `test_client.py`
- `ENDPOINT` changed from `http://localhost:8000` → `http://127.0.0.1:8000`

### `requirements.txt`
- re-encoded from UTF-16LE to UTF-8 (was unreadable by pip)

### `README.md`
full rewrite. now covers:
- npm install (global) + git clone workflows
- cross-platform setup: Linux (Arch/Ubuntu/Fedora), macOS, Windows
- PATH fix instructions per platform
- Mode A / Mode B explanation with OS-specific Chrome launch commands
- all endpoints, curl examples for Linux/macOS/Windows
- updated project structure tree

---

## path setup (system-wide)

| method | what was done |
|--------|---------------|
| `~/.zshrc` | `export PATH="$HOME/.local/bin:$PATH"` appended |
| `~/.zprofile` | created with same export (covers login shells) |
| `~/.cargo/bin/templlm` | symlink → `~/.local/bin/templlm` (immediately in PATH without re-sourcing) |

---

## install flows (for reference)

**npm (anyone worldwide):**
```bash
npm install -g templlm   # postinstall auto-runs pip + playwright
templlm init             # wizard: OS detection → mode select → .env write → login
templlm "hello"
```

**git clone:**
```bash
git clone <repo>
cd tempLLM
npm install              # same postinstall
npm install -g .
templlm init
templlm "hello"
```
