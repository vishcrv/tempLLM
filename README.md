<div align="center">

# tempLLM

**local llm api — no sdk, no api key**

spin up a local server · hit clean REST endpoints · get responses

</div>

---

## how it works

templlm drives a live browser session via Playwright and exposes it as a FastAPI server with REST endpoints. the `templlm` CLI talks to that server over HTTP.

```
templlm "prompt"  →  POST /ask  →  FastAPI server  →  Playwright  →  ChatGPT  →  response
```

---

## requirements

| dependency | version | notes |
|------------|---------|-------|
| Node.js    | 18+     | runs the CLI |
| Python     | 3.8+    | runs the server |
| Google Chrome | any recent | for authenticated mode (recommended) |

---

## install

### option A — npm (recommended)

```bash
npm install -g templlm
templlm init        # interactive setup wizard
```

### option B — clone the repo

```bash
git clone https://github.com/YOUR_USER/tempLLM.git
cd tempLLM
npm install         # installs pip packages + playwright chromium automatically
npm install -g .    # puts `templlm` in your PATH
templlm init        # interactive setup wizard
```

---

## setup wizard

`templlm init` detects your OS and walks you through everything:

```
┌────────────────────────────────────────┐
│          templlm  ·  setup wizard       │
└────────────────────────────────────────┘

Detected OS:  Linux (Arch Linux)
Python:       ✓ 3.11.0  (python3)

Which connection mode?
  1  Mode A — CDP  (recommended)  Connect to your own Chrome with an active session
  2  Mode B — Headless            Playwright launches Chromium in the background

›
```

It then prints the exact Chrome launch command for your OS, writes `.env` automatically, and optionally runs the login flow.

---

## platform setup

<details>
<summary><strong>Linux</strong></summary>

```bash
# Arch / Manjaro
sudo pacman -S python python-pip nodejs npm
yay -S google-chrome          # for Mode A (CDP)

# Ubuntu / Debian
sudo apt install python3 python3-pip nodejs npm
# Chrome: https://google.com/chrome

# Fedora
sudo dnf install python3 python3-pip nodejs npm
sudo dnf install google-chrome-stable

npm install -g templlm
templlm init
```

**PATH note:** npm global bins land in `~/.local/bin`. Make sure it's in your PATH:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc   # bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc    # zsh
source ~/.bashrc   # or open a new terminal
```

</details>

<details>
<summary><strong>macOS</strong></summary>

```bash
# Install prerequisites via Homebrew
brew install python node
brew install --cask google-chrome    # for Mode A (CDP)

npm install -g templlm
templlm init
```

</details>

<details>
<summary><strong>Windows</strong></summary>

```powershell
# Install prerequisites via winget
winget install Python.Python.3
winget install OpenJS.NodeJS
winget install Google.Chrome        # for Mode A (CDP)

npm install -g templlm
templlm init
```

Or use [Chocolatey](https://chocolatey.org/):

```powershell
choco install python nodejs googlechrome
npm install -g templlm
templlm init
```

**Note:** Run PowerShell as Administrator for global npm installs, or configure a user-local npm prefix:

```powershell
npm config set prefix "$env:APPDATA\npm"
# add %APPDATA%\npm to your PATH in System Environment Variables
```

</details>

---

## usage

```bash
templlm init                          # first-time setup
templlm "give me a bubble sort"       # single response
templlm --stream "explain async/await"  # streaming response
templlm --setup                       # re-run login (session expired)
```

The server starts automatically in the background when you run a prompt. No need to run `python run.py` manually.

---

## connection modes

### mode A — CDP (recommended)

Connect to your existing Chrome with a live logged-in session.

**1. Launch Chrome with remote debugging:**

<details>
<summary>Linux</summary>

```bash
google-chrome-stable --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-cdp-profile
```

</details>

<details>
<summary>macOS</summary>

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-cdp-profile
```

</details>

<details>
<summary>Windows (PowerShell)</summary>

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --remote-debugging-port=9222 `
  --user-data-dir=C:\temp\chrome-cdp-profile
```

</details>

**2. Log in to ChatGPT in that window.**

**3. Run `templlm init` or set `CDP_URL=http://localhost:9222` in `.env`.**

> The Chrome profile is saved to `--user-data-dir` — you only log in once.

### mode B — headless

Don't open Chrome. Just run `templlm "prompt"` and Playwright handles its own Chromium. Session is limited to unauthenticated access unless you have a saved `session.json`.

---

## endpoints

| method | endpoint | description |
|--------|----------|-------------|
| `POST` | `/ask` | full JSON response |
| `POST` | `/ask/stream` | server-sent events (SSE) stream |
| `GET`  | `/health` | server & browser status |
| `POST` | `/screenshot` | debug screenshot, returns path |
| `POST` | `/session/invalidate` | clear saved session |

Interactive docs → `http://localhost:8000/docs`

---

## test the api

### curl

```bash
# Linux / macOS
curl -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"prompt": "give me a bubble sort"}'
```

```powershell
# Windows PowerShell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/ask `
  -ContentType "application/json" `
  -Body '{"prompt": "give me a bubble sort"}'
```

### python test client (no extra installs)

```bash
python test_client.py "give me a bubble sort"
python test_client.py --stream "give me a bubble sort"
```

---

## configuration

```dotenv
# .env

CDP_URL=http://localhost:9222   # blank = Mode B (headless)

HEADLESS=false                  # true = no visible browser in Mode B
SESSION_FILE=./session.json
SLOW_MO=0
RESPONSE_TIMEOUT=120

HOST=0.0.0.0
PORT=8000
```

---

## project structure

```
tempLLM/
│
├── app/
│   ├── main.py          FastAPI app + lifespan
│   ├── config.py        env config
│   ├── models.py        pydantic schemas
│   ├── browser.py       Playwright automation + mode detection
│   └── routes/
│       └── ask.py       endpoints
│
├── bin/
│   └── cli.js           npm CLI entry point
│
├── scripts/
│   ├── init.js          interactive setup wizard
│   └── postinstall.js   runs on npm install
│
├── run.py               server entry point
├── cli.py               direct browser CLI (no server)
├── test_client.py       HTTP test client
├── requirements.txt     Python dependencies
└── package.json         npm package
```
