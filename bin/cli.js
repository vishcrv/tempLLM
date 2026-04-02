#!/usr/bin/env node
"use strict";

const http     = require("http");
const net      = require("net");
const path     = require("path");
const fs       = require("fs");
const os       = require("os");
const readline = require("readline");
const { spawn, spawnSync } = require("child_process");

const HOST     = "127.0.0.1";
const PORT     = 8000;
const ENDPOINT = `http://${HOST}:${PORT}`;
const ROOT     = path.join(__dirname, "..");
const LOG_FILE = path.join(os.tmpdir(), "templlm-server.log");

const { detectPython } = require("../scripts/python");
const { getMode, ensureBrowser } = require("../scripts/browser");
const PYTHON = (detectPython() || {}).bin || "python";

// ── Colours ─────────────────────────────────────────────────────────────────
const c = process.stdout.isTTY ? {
  reset: "\x1b[0m", bold: "\x1b[1m", dim: "\x1b[2m",
  green: "\x1b[32m", yellow: "\x1b[33m", cyan: "\x1b[36m", red: "\x1b[31m",
} : { reset:"", bold:"", dim:"", green:"", yellow:"", cyan:"", red:"" };

// ── Network helpers ─────────────────────────────────────────────────────────

function isPortOpen() {
  return new Promise(resolve => {
    const s = net.createConnection(PORT, HOST);
    s.on("connect", () => { s.destroy(); resolve(true); });
    s.on("error",   () => resolve(false));
  });
}

function httpGet(urlPath) {
  return new Promise(resolve => {
    http.get(`${ENDPOINT}${urlPath}`, res => resolve(res.statusCode))
        .on("error", () => resolve(null));
  });
}

async function waitForServer(timeoutSecs = 90) {
  const deadline = Date.now() + timeoutSecs * 1000;
  while (Date.now() < deadline) {
    if (await httpGet("/health") !== null) return true;
    await new Promise(r => setTimeout(r, 1000));
  }
  return false;
}

// ── Server management ───────────────────────────────────────────────────────

async function ensureServer() {
  if (await isPortOpen()) return;

  const runPy = path.join(ROOT, "run.py");
  if (!fs.existsSync(runPy)) {
    console.error(`${c.red}Error:${c.reset} run.py not found. Reinstall with: npm install -g templlm`);
    process.exit(1);
  }

  // Check deps before starting
  try {
    require("child_process").execSync(
      `${PYTHON} -c "import fastapi, uvicorn, playwright"`,
      { stdio: "pipe", cwd: ROOT, timeout: 10000 }
    );
  } catch {
    console.log(`${c.yellow}First run — installing dependencies...${c.reset}`);
    try {
      try {
        require("child_process").execSync(`${PYTHON} -m pip --version`, { stdio: "ignore" });
      } catch {
        console.log(`${c.yellow}Installing pip...${c.reset}`);
        require("child_process").execSync(`${PYTHON} -m ensurepip --upgrade`, { stdio: "inherit" });
      }
      require("child_process").execSync(
        `${PYTHON} -m pip install -r requirements.txt --quiet`,
        { stdio: "inherit", cwd: ROOT, timeout: 300000 }
      );
      console.log(`${c.yellow}Installing browser (chromium)...${c.reset}`);
      require("child_process").execSync(
        `${PYTHON} -m playwright install chromium`,
        { stdio: "inherit", cwd: ROOT, timeout: 300000 }
      );
    } catch (e) {
      console.error(`${c.red}Dependency install failed.${c.reset} Run manually:`);
      console.error(`  ${PYTHON} -m pip install -r requirements.txt`);
      console.error(`  ${PYTHON} -m playwright install chromium`);
      process.exit(1);
    }
  }

  // Start server with log capture
  const logFd = fs.openSync(LOG_FILE, "w");
  const child = spawn(PYTHON, [runPy], {
    detached:     true,
    stdio:        ["ignore", logFd, logFd],
    cwd:          ROOT,
    windowsHide:  true,
  });
  child.unref();
  fs.closeSync(logFd);

  process.stderr.write(`${c.dim}Starting server...${c.reset}`);
  const tick = setInterval(() => process.stderr.write("."), 1000);
  const ready = await waitForServer(90);
  clearInterval(tick);
  process.stderr.write("\n");

  if (!ready) {
    console.error(`${c.red}Server failed to start.${c.reset}`);
    // Show last 20 lines of log
    if (fs.existsSync(LOG_FILE)) {
      const log = fs.readFileSync(LOG_FILE, "utf8").trim().split("\n").slice(-20).join("\n");
      if (log) {
        console.error(`\n${c.dim}── server log ──${c.reset}`);
        console.error(log);
        console.error(`${c.dim}── end log ──${c.reset}\n`);
      }
    }
    console.error(`Full log: ${LOG_FILE}`);
    process.exit(1);
  }
}

// ── Backend bootstrap (server + browser) ───────────────────────────────────

async function ensureBackend() {
  const mode = getMode();
  if (mode === "cdp") {
    process.stderr.write(`${c.dim}Checking browser...${c.reset}\n`);
    const ok = await ensureBrowser();
    if (!ok) {
      console.error(`${c.red}CDP mode configured but Chrome not found.${c.reset} Run \`templlm init\` to reconfigure.`);
      process.exit(1);
    }
    process.stderr.write(`${c.dim}Browser ready.${c.reset}\n`);
  }
  await ensureServer();
}

// ── HTTP post ───────────────────────────────────────────────────────────────

function post(urlPath, body) {
  return new Promise((resolve, reject) => {
    const data    = JSON.stringify(body);
    const options = {
      hostname: HOST, port: PORT, path: urlPath, method: "POST",
      headers: { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(data) },
    };
    const req = http.request(options, resolve);
    req.on("error", reject);
    req.write(data);
    req.end();
  });
}

// ── Streaming response ──────────────────────────────────────────────────────

async function streamResponse(prompt, new_chat = false) {
  const res = await post("/ask/stream", { prompt, new_chat });
  let event = "";
  let buf   = "";

  return new Promise((resolve, reject) => {
    res.on("data", (chunk) => {
      buf += chunk.toString();
      const lines = buf.split("\n");
      buf = lines.pop();

      for (const line of lines) {
        const t = line.trim();
        if (!t) continue;
        if (t.startsWith("event:")) { event = t.slice(6).trim(); continue; }
        if (!t.startsWith("data:"))  continue;

        let data;
        try { data = JSON.parse(t.slice(5).trim()); } catch { data = { raw: t.slice(5).trim() }; }

        if      (event === "message") process.stdout.write((data.delta ?? "").replace(/\\n/g, "\n"));
        else if (event === "done")    { process.stdout.write("\n"); resolve(); return; }
        else if (event === "error")   { reject(new Error(data.error || "Server error")); return; }
      }
    });

    res.on("end", resolve);
    res.on("error", reject);
  });
}

// ── Interactive REPL ────────────────────────────────────────────────────────

async function repl() {
  console.log(`${c.bold}${c.cyan}templlm${c.reset} ${c.dim}— LLM in your terminal${c.reset}`);
  console.log(`${c.dim}Type your prompt and press Enter. Ctrl+C to exit.${c.reset}\n`);

  const rl = readline.createInterface({
    input:  process.stdin,
    output: process.stdout,
    prompt: `${c.green}> ${c.reset}`,
  });

  rl.prompt();

  rl.on("line", async (line) => {
    const input = line.trim();
    if (!input) { rl.prompt(); return; }
    if (input === "exit" || input === "quit") { rl.close(); return; }

    try {
      process.stdout.write(`\n${c.cyan}`);
      await streamResponse(input, false);
      process.stdout.write(`${c.reset}\n`);
    } catch (err) {
      console.error(`\n${c.red}Error: ${err.message}${c.reset}\n`);
    }

    rl.prompt();
  });

  rl.on("close", () => {
    console.log(`\n${c.dim}Bye!${c.reset}`);
    process.exit(0);
  });
}

// ── Entry point ─────────────────────────────────────────────────────────────

const args = process.argv.slice(2);

if (args[0] === "--help" || args[0] === "-h") {
  console.log(`${c.bold}templlm${c.reset} — LLM in your terminal\n`);
  console.log("Usage:");
  console.log(`  ${c.cyan}templlm${c.reset}                — interactive chat`);
  console.log(`  ${c.cyan}templlm "prompt"${c.reset}       — one-shot response`);
  console.log(`  ${c.cyan}templlm status${c.reset}         — check / manage backend`);
  console.log(`  ${c.cyan}templlm init${c.reset}           — first-time setup wizard`);
  process.exit(0);
}

if (args[0] === "init")   { require("../scripts/init.js"); }
if (args[0] === "status") { require("../scripts/status.js"); }

else {
  const prompt = args.join(" ");

  (async () => {
    try {
      await ensureBackend();

      console.log(`\n${c.green}● API is ACTIVE at http://0.0.0.0:8000${c.reset}`);
      console.log(`${c.dim}  You can now use /ask or /ask/stream in external projects!${c.reset}\n`);
      
      if (prompt) {
        // One-shot mode
        await streamResponse(prompt, true);
      } else {
        // Interactive REPL
        await repl();
      }
    } catch (err) {
      console.error(`${c.red}Error: ${err.message}${c.reset}`);
      process.exit(1);
    }
  })();
}
