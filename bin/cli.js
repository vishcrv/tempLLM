#!/usr/bin/env node
"use strict";

const http = require("http");
const net  = require("net");
const path = require("path");
const fs   = require("fs");
const { spawn, spawnSync } = require("child_process");

const HOST     = "127.0.0.1";
const PORT     = 8000;
const ENDPOINT = `http://${HOST}:${PORT}`;
const ROOT     = path.join(__dirname, "..");

// ── Helpers ──────────────────────────────────────────────────────────────────

function isPortOpen() {
  return new Promise(resolve => {
    const s = net.createConnection(PORT, HOST);
    s.on("connect", () => { s.destroy(); resolve(true); });
    s.on("error",   () => resolve(false));
  });
}

function httpGet(path) {
  return new Promise(resolve => {
    http.get(`${ENDPOINT}${path}`, res => resolve(res.statusCode)).on("error", () => resolve(null));
  });
}

async function waitForServer(timeoutSecs = 60) {
  const deadline = Date.now() + timeoutSecs * 1000;
  while (Date.now() < deadline) {
    if (await httpGet("/docs") !== null) return true;
    await new Promise(r => setTimeout(r, 1000));
  }
  return false;
}

async function ensureServer() {
  if (await isPortOpen()) return;

  const runPy = path.join(ROOT, "run.py");
  if (!fs.existsSync(runPy)) {
    console.error("Error: run.py not found next to this package.");
    console.error("Clone the repo: https://github.com/YOUR_USER/tempLLM");
    process.exit(1);
  }

  process.stderr.write("Starting server");
  const child = spawn("python", [runPy], {
    detached: true,
    stdio:    "ignore",
    cwd:      ROOT,
  });
  child.unref();

  const tick = setInterval(() => process.stderr.write("."), 1000);
  const ready = await waitForServer(60);
  clearInterval(tick);
  process.stderr.write("\n");

  if (!ready) {
    console.error("Error: server did not become ready within 60 s.");
    console.error("Run manually in another terminal: python run.py");
    process.exit(1);
  }
}

function post(urlPath, body) {
  return new Promise((resolve, reject) => {
    const data    = JSON.stringify(body);
    const options = {
      hostname: HOST, port: PORT, path: urlPath,
      method:  "POST",
      headers: { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(data) },
    };
    const req = http.request(options, resolve);
    req.on("error", reject);
    req.write(data);
    req.end();
  });
}

// ── Modes ────────────────────────────────────────────────────────────────────

async function askJson(prompt) {
  const res = await post("/ask", { prompt });
  let raw = "";
  for await (const chunk of res) raw += chunk;
  const body = JSON.parse(raw);
  if (body.status === "ok") {
    process.stdout.write(body.response + "\n");
  } else {
    console.error("Error:", body.error);
    process.exit(1);
  }
}

async function askStream(prompt) {
  const res = await post("/ask/stream", { prompt });
  let event = "";
  let buf   = "";

  for await (const chunk of res) {
    buf += chunk.toString();
    const lines = buf.split("\n");
    buf = lines.pop();

    for (const line of lines) {
      const t = line.trim();
      if (!t) continue;
      if (t.startsWith("event:")) { event = t.slice(6).trim(); continue; }
      if (!t.startsWith("data:")) continue;

      let data;
      try { data = JSON.parse(t.slice(5).trim()); } catch { data = { raw: t.slice(5).trim() }; }

      if      (event === "message") process.stdout.write((data.delta ?? "").replace(/\\n/g, "\n"));
      else if (event === "done")    { process.stdout.write("\n"); return; }
      else if (event === "error")   { console.error("\nError:", data.error); process.exit(1); }
    }
  }
}

function runSetup() {
  const cliPy = path.join(ROOT, "cli.py");
  if (!fs.existsSync(cliPy)) {
    console.error("cli.py not found — clone the full repo to run setup.");
    process.exit(1);
  }
  spawnSync("python", [cliPy, "--setup"], { stdio: "inherit", cwd: ROOT });
}

// ── Entry point ───────────────────────────────────────────────────────────────

const args = process.argv.slice(2);

if (args.length === 0 || args[0] === "--help" || args[0] === "-h") {
  console.log("Usage:");
  console.log("  templlm init                — interactive setup wizard");
  console.log("  templlm <prompt>            — single response");
  console.log("  templlm --stream <prompt>   — streaming response");
  console.log("  templlm --setup             — re-run ChatGPT login");
  process.exit(0);
}

if (args[0] === "--setup") { runSetup(); process.exit(0); }
if (args[0] === "init")    { require("../scripts/init.js"); process.exit(0); }

const streamIdx = args.indexOf("--stream");
const stream    = streamIdx !== -1;
if (stream) args.splice(streamIdx, 1);

const prompt = args.join(" ");

(async () => {
  await ensureServer();
  if (stream) await askStream(prompt);
  else        await askJson(prompt);
})();
