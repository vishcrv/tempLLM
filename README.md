<div align="center">
  <br />
  <h1>templlm</h1>
  <p><strong>your browser is the API key.</strong></p>
  <p>pipe prompts through any LLM tab. get REST responses back.</p>
  <p><code>no key · no cost · no SDK</code></p>
  <br />
  
  [![npm version](https://img.shields.io/npm/v/templlm?style=flat-square&color=black)](https://www.npmjs.com/package/templlm)
  [![npm downloads](https://img.shields.io/npm/dm/templlm?style=flat-square&color=black)](https://www.npmjs.com/package/templlm)
  [![license](https://img.shields.io/npm/l/templlm?style=flat-square&color=black)](./LICENSE)
  [![node](https://img.shields.io/badge/node-18%2B-black?style=flat-square)](https://nodejs.org)
</div>

<br />

<div align="center">
  <table>
    <tr>
      <td align="center" width="140">
        <img src="./assets/openai.svg" width="28" height="28" alt="OpenAI" /><br />
        <strong>ChatGPT</strong><br />
        <sub>live</sub>
      </td>
      <td align="center" width="140">
        <img src="./assets/claude-color.svg" width="28" height="28" alt="Claude" /><br />
        <strong>Claude</strong><br />
        <sub>wip</sub>
      </td>
    </tr>
  </table>
</div>

---

## overview

LLM providers give you their best models for free through a chat tab. Want the same models via API? That costs money. templlm bridges the gap.

It connects to your browser session via **Chrome DevTools Protocol**, watches the chat, and exposes it as a local REST API. Any language, any framework, any project, if it can hit `localhost`, it can talk to your LLM.

```
your app  →  POST localhost:8000/ask  →  templlm  →  CDP  →  browser  →  LLM  →  response
```

No API key. No billing page. No rate limits. Just a server you own, talking to a browser you own, using a session you already have.

> [!WARNING]
> tempLLM is built to explore browser automation via Playwright and CDP. **Educational and experimental use only.** Not affiliated with or endorsed by OpenAI or Anthropic. Users are responsible for complying with each platform's Terms of Service.

---

## quick start

```bash
npm install -g templlm
templlm init
```

That's it. The server starts automatically the first time you use it.

---

## terminal usage

No code needed. Use it straight from your terminal.

```bash
templlm "what's the difference between Promise.all and Promise.allSettled?"
templlm "write a debounce function in TypeScript with proper types"
templlm "explain what EXPLAIN ANALYZE does in Postgres"
```

**Interactive session** — context retained across messages:

```bash
$ templlm
```

```
you  ›  I'm getting "cannot read properties of undefined (reading 'map')" in React

llm  ›  You're likely rendering before your data loads.
        Add a guard: if (!data) return null

you  ›  state is initialised as undefined, would that cause it?

llm  ›  Yes. Change useState() to useState([])
        Undefined breaks .map() — an empty array won't.

you  ›  should I even use useEffect for fetching or is there something better?

llm  ›  Fine for simple cases. For anything serious, use React Query or SWR.
        They handle loading states, caching, and refetching out of the box.
```

---

## API usage

Once the server is running, any project can talk to it.

<details>
<summary><b>Python</b></summary>
<br />

```python
import requests

response = requests.post("http://localhost:8000/ask", json={
    "prompt": "summarise this in 3 bullet points: ..."
})

print(response.json()["response"])
```

</details>

<details>
<summary><b>JavaScript / Node</b></summary>
<br />

```javascript
const res = await fetch("http://localhost:8000/ask", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ prompt: "refactor this function: ..." })
});

const { response } = await res.json();
```

</details>

<details>
<summary><b>Streaming (SSE)</b></summary>
<br />

```javascript
const res = await fetch("http://localhost:8000/ask/stream", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ prompt: "write me a sorting algorithm" })
});

for await (const chunk of res.body) {
  process.stdout.write(new TextDecoder().decode(chunk));
}
```

</details>

<details>
<summary><b>curl</b></summary>
<br />

```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"prompt": "give me a bubble sort in Python"}'
```

</details>

---

## endpoints

| Method | Endpoint | What it does |
|--------|----------|--------------|
| `POST` | `/ask` | full response as JSON |
| `POST` | `/ask/stream` | streaming response via SSE |
| `GET` | `/health` | server + browser status |
| `POST` | `/screenshot` | debug screenshot |
| `POST` | `/session/invalidate` | clear saved session |

> interactive docs → `http://localhost:8000/docs`

---

## CLI reference

```
templlm init              first-time setup wizard
templlm setup             re-login (session expired)
templlm status            check server — start or stop
templlm stop              kill background server
templlm logs              tail the server log
templlm "prompt"          one-shot prompt (fresh chat)
templlm                   interactive REPL (context retained)
templlm --version         print version
templlm --help            all commands
```

---

## connection modes

### mode A — CDP *(recommended)*

Attaches to a running Chrome instance via **Chrome DevTools Protocol** on `--remote-debugging-port=9222`. Playwright connects over WebSocket — no new process, just your existing browser.

`templlm init` launches Chrome with the right flags automatically. Log in once, session is saved.

→ works with your real logged-in accounts
→ session persists across restarts
→ fastest and most stable

### mode B — headless

Playwright spawns its own Chromium in the background. No Chrome install required.

→ good for servers or CI
→ unauthenticated unless you supply `session.json`

---

## configuration

`templlm init` writes this automatically. Edit if needed:

```dotenv
CDP_URL=http://localhost:9222   # blank = headless mode
HEADLESS=false                  # show/hide browser in headless mode
SESSION_FILE=./session.json
RESPONSE_TIMEOUT=120
HOST=0.0.0.0
PORT=8000
```

---

## installation

<details>
<summary><b>Linux</b></summary>
<br />

```bash
# arch / manjaro
sudo pacman -S python python-pip nodejs npm
yay -S google-chrome

# ubuntu / debian
sudo apt install python3 python3-pip nodejs npm
# chrome → https://google.com/chrome

# fedora
sudo dnf install python3 python3-pip nodejs npm
sudo dnf install google-chrome-stable
```

> **PATH:** npm global bins land in `~/.local/bin` on some distros.
> ```bash
> echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc
> ```

</details>

<details>
<summary><b>macOS</b></summary>
<br />

```bash
brew install python node
brew install --cask google-chrome
```

</details>

<details>
<summary><b>Windows</b></summary>
<br />

```powershell
winget install Python.Python.3
winget install OpenJS.NodeJS
winget install Google.Chrome
```

> run PowerShell as Administrator for global npm installs, or:
> ```powershell
> npm config set prefix "$env:APPDATA\npm"
> ```

</details>

then:

```bash
npm install -g templlm
templlm init
```

---

<div align="center">
  <sub>built with playwright · fastapi · CDP</sub>
</div>
