#!/usr/bin/env node
"use strict";

const http = require("http");
const net = require("net");
const path = require("path");
const readline = require("readline");
const { spawnSync, spawn } = require("child_process");
const os = require("os");
const fs = require("fs");
const { detectPython } = require("./python");
const { getMode, ensureBrowser, CDP_PORT } = require("./browser");

const HOST = "127.0.0.1";
const PORT = 8000;
const ROOT = path.join(__dirname, "..");
const LOG_FILE = path.join(os.tmpdir(), "templlm-server.log");

const PYTHON = (detectPython() || {}).bin || "python";

// ── Colours ───────────────────────────────────────────────────────────────────
const c = {
  reset:  "\x1b[0m",
  bold:   "\x1b[1m",
  dim:    "\x1b[2m",
  green:  "\x1b[32m",
  yellow: "\x1b[33m",
  cyan:   "\x1b[36m",
  red:    "\x1b[31m",
};

function isPortOpen(port = PORT) {
  return new Promise(resolve => {
    const s = net.createConnection(port, HOST);
    s.on("connect", () => { s.destroy(); resolve(true); });
    s.on("error",   () => resolve(false));
  });
}

function prompt(rl, question) {
  return new Promise(resolve => rl.question(question, resolve));
}

async function confirm(rl, question, defaultYes = true) {
  const hint = defaultYes ? "(Y/n)" : "(y/N)";
  const ans  = (await prompt(rl, `${c.bold}${question}${c.reset} ${c.dim}${hint}${c.reset} `)).trim().toLowerCase();
  if (!ans) return defaultYes;
  return ans === "y" || ans === "yes";
}

async function startServer() {
  const runPy = path.join(ROOT, "run.py");
  console.log(`${c.dim}Starting server...${c.reset}`);

  const logFd = fs.openSync(LOG_FILE, "w");
  const child = spawn(PYTHON, [runPy], {
    detached:     true,
    stdio:        ["ignore", logFd, logFd],
    cwd:          ROOT,
    windowsHide:  true,
  });
  child.unref();
  fs.closeSync(logFd);

  for (let i = 0; i < 30; i++) {
    process.stdout.write(".");
    await new Promise(r => setTimeout(r, 1000));
    if (await isPortOpen(PORT)) {
      console.log(`\n${c.green}● Server started successfully at http://${HOST}:${PORT}${c.reset}`);
      return true;
    }
  }
  console.log(`\n${c.red}Failed to start server. Check logs: ${LOG_FILE}${c.reset}`);
  return false;
}

async function killServer() {
  if (process.platform === "win32") {
    console.log(`${c.dim}Stopping Python background processes...${c.reset}`);
    spawnSync("powershell.exe", ["-Command", "Stop-Process -Name 'python' -PassThru | Where-Object {$_.CommandLine -match 'run.py'}"], { stdio: "ignore" });
  } else {
    spawnSync("pkill", ["-f", "run.py"]);
  }

  for (let i = 0; i < 10; i++) {
    if (!(await isPortOpen(PORT))) {
      console.log(`${c.green}✓ Server turned off.${c.reset}`);
      return;
    }
    await new Promise(r => setTimeout(r, 500));
  }
  console.log(`${c.red}✗ Could not fully confirm server shutdown.${c.reset}`);
}

async function killBrowser() {
  console.log(`${c.dim}Stopping Chrome...${c.reset}`);
  if (process.platform === "win32") {
    spawnSync("powershell.exe", ["-Command", `Stop-Process -Name 'chrome' -PassThru | Where-Object {$_.CommandLine -match '${CDP_PORT}'}`], { stdio: "ignore" });
  } else {
    spawnSync("pkill", ["-f", `--remote-debugging-port=${CDP_PORT}`]);
  }
}

async function run() {
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });

  const mode      = getMode();
  const serverUp  = await isPortOpen(PORT);
  const browserUp = mode === "cdp" ? await isPortOpen(CDP_PORT) : true;
  const active    = serverUp && browserUp;

  console.log(`\n${c.bold}templlm Status${c.reset}  ${c.dim}(mode: ${mode})${c.reset}`);

  if (active) {
    console.log(`API: ${c.green}● ACTIVE${c.reset}`);
    if (mode === "cdp") {
      console.log(`  ${c.dim}Server: port ${PORT} ✓   Browser (CDP): port ${CDP_PORT} ✓${c.reset}`);
    } else {
      console.log(`  ${c.dim}Server: port ${PORT} ✓${c.reset}`);
    }
    console.log();

    const turnOff = await confirm(rl, "Do you want to turn it off?", true);
    if (turnOff) {
      await killServer();
      if (mode === "cdp") await killBrowser();
      rl.close();
      return;
    }
    console.log(`${c.dim}[Supervisor] Monitoring... Press Ctrl+C to stop.${c.reset}`);

  } else if (serverUp && !browserUp) {
    // Server up but browser missing (Mode A only)
    console.log(`API: ${c.yellow}◑ PARTIAL${c.reset}  ${c.dim}(server running, browser not detected on port ${CDP_PORT})${c.reset}\n`);

    const fix = await confirm(rl, "Start the browser to make the API fully active?", true);
    if (fix) {
      const ok = await ensureBrowser();
      if (ok) {
        console.log(`${c.green}✓ Browser started. API is now ACTIVE.${c.reset}`);
        console.log(`${c.dim}[Supervisor] Monitoring... Press Ctrl+C to stop.${c.reset}`);
      } else {
        console.log(`${c.red}✗ Could not start browser. Run \`templlm init\` to reconfigure.${c.reset}`);
        rl.close();
        return;
      }
    } else {
      rl.close();
      return;
    }

  } else {
    // Fully down
    console.log(`API: ${c.dim}○ DOWN${c.reset}\n`);

    const turnOn = await confirm(rl, "Do you want to start it?", true);
    if (turnOn) {
      if (mode === "cdp") {
        const browserOk = await ensureBrowser();
        if (!browserOk) {
          console.log(`${c.red}Cannot start: Chrome not found. Run \`templlm init\` to configure.${c.reset}`);
          rl.close();
          return;
        }
      }
      const serverOk = await startServer();
      if (!serverOk) {
        if (mode === "cdp") await killBrowser();
        rl.close();
        return;
      }
      console.log(`\n${c.green}● API is ACTIVE${c.reset}`);
      console.log(`${c.dim}[Supervisor] Monitoring... Press Ctrl+C to stop.${c.reset}`);
    } else {
      console.log("Server remains off.");
      rl.close();
      return;
    }
  }

  rl.close();

  // ── Supervisor loop ─────────────────────────────────────────────────────────
  setInterval(async () => {
    const sUp = await isPortOpen(PORT);
    const bUp = mode === "cdp" ? await isPortOpen(CDP_PORT) : true;

    if (!sUp || !bUp) {
      if (!bUp) {
        console.log(`\n${c.red}Browser closed! Shutting down server and exiting.${c.reset}`);
      } else {
        console.log(`\n${c.red}Server process died! Closing browser and exiting.${c.reset}`);
      }
      await killServer();
      if (mode === "cdp") await killBrowser();
      process.exit(1);
    }
  }, 3000);
}

run().catch(e => {
  console.error(e);
  process.exit(1);
});
