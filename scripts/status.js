#!/usr/bin/env node
"use strict";

const http = require("http");
const net = require("net");
const path = require("path");
const readline = require("readline");
const { spawnSync, spawn, execSync } = require("child_process");
const os = require("os");
const fs = require("fs");
const { detectPython } = require("./python");

const HOST = "127.0.0.1";
const PORT = 8000;
const CDP_PORT = 9222;
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

// ── Chrome detection ──────────────────────────────────────────────────────────
function detectChrome() {
  const win32 = [
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
  ];
  if (process.env.LOCALAPPDATA) {
    win32.push(path.join(process.env.LOCALAPPDATA, "Google", "Chrome", "Application", "chrome.exe"));
  }

  const candidates = {
    win32,
    darwin: [
      "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ],
    linux:  [
      "/usr/bin/google-chrome-stable",
      "/usr/bin/google-chrome",
      "/usr/bin/chromium",
      "/usr/bin/chromium-browser",
      "/snap/bin/chromium",
    ],
  };

  for (const p of (candidates[process.platform] || candidates.linux)) {
    if (fs.existsSync(p)) return p;
  }

  const lookupCmd = process.platform === "win32" ? "where" : "which";
  for (const bin of ["google-chrome-stable", "google-chrome", "chromium", "chromium-browser"]) {
    try { execSync(`${lookupCmd} ${bin}`, { stdio: "ignore" }); return bin; } catch {}
  }
  return null;
}

function launchChrome(chromePath) {
  const dataDir = path.join(os.tmpdir(), "chrome-cdp-profile");
  const args = [
    `--remote-debugging-port=${CDP_PORT}`,
    `--user-data-dir=${dataDir}`,
  ];
  try {
    const child = spawn(chromePath, args, {
      detached: true,
      stdio: "ignore",
      windowsHide: false,
    });
    child.unref();
    return true;
  } catch {
    return false;
  }
}

async function startBrowser() {
  console.log(`${c.dim}Checking browser...${c.reset}`);
  if (await isPortOpen(CDP_PORT)) {
    console.log(`${c.dim}Browser is already running.${c.reset}`);
    return true;
  }
  const chromePath = detectChrome();
  if (!chromePath) {
    console.log(`${c.red}Chrome not found. Cannot launch browser.${c.reset}`);
    return false;
  }
  console.log(`${c.dim}Starting browser on port ${CDP_PORT}...${c.reset}`);
  if (launchChrome(chromePath)) {
    for (let i = 0; i < 20; i++) {
        await new Promise(r => setTimeout(r, 500));
        if (await isPortOpen(CDP_PORT)) {
            console.log(`${c.green}✓ Browser started (CDP on ${CDP_PORT})${c.reset}`);
            return true;
        }
    }
  }
  console.log(`${c.red}✗ Failed to start browser.${c.reset}`);
  return false;
}

async function killBrowser() {
  console.log(`${c.dim}Stopping Chrome...${c.reset}`);
  if (process.platform === "win32") {
    spawnSync("powershell.exe", ["-Command", `Stop-Process -Name 'chrome' -PassThru | Where-Object {$_.CommandLine -match '${CDP_PORT}'}`], { stdio: "ignore" });
  } else {
    spawnSync("pkill", ["-f", `--remote-debugging-port=${CDP_PORT}`]);
  }
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

async function run() {
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  
  console.log(`\n${c.bold}templlm Server Status${c.reset}`);
  const up = await isPortOpen(PORT);
  
  let shouldMonitor = false;

  if (up) {
    console.log(`Status: ${c.green}● UP (Running on port ${PORT})${c.reset}\n`);
    const turnOff = await confirm(rl, "Do you want to turn it off?", true);
    if (turnOff) {
      await killServer();
      await killBrowser();
      rl.close();
      return;
    } else {
      console.log("Monitoring processes...");
      shouldMonitor = true;
    }
  } else {
    console.log(`Status: ${c.dim}○ DOWN (Not running)${c.reset}\n`);
    const turnOn = await confirm(rl, "Do you want to start it?", true);
    if (turnOn) {
      const browserUp = await startBrowser();
      if (!browserUp) {
         console.log(`${c.red}Cannot start server without browser.${c.reset}`);
         rl.close();
         return;
      }
      const serverUp = await startServer();
      if (!serverUp) {
         await killBrowser();
         rl.close();
         return;
      }
      console.log(`\n${c.dim}[Supervisor] Monitoring browser and server... Press Ctrl+C to stop.${c.reset}`);
      shouldMonitor = true;
    } else {
      console.log("Server remains off.");
      rl.close();
      return;
    }
  }

  rl.close();

  if (shouldMonitor) {
    setInterval(async () => {
       const browserUp = await isPortOpen(CDP_PORT);
       const serverUp = await isPortOpen(PORT);
       
       if (!browserUp || !serverUp) {
          if (!browserUp) {
              console.log(`\n${c.red}Browser closed! Shutting down server and exiting.${c.reset}`);
          } else {
              console.log(`\n${c.red}Server process died! Closing browser and exiting.${c.reset}`);
          }
          await killServer();
          await killBrowser();
          process.exit(1);
       }
    }, 3000);
  }
}

run().catch(e => {
  console.error(e);
  process.exit(1);
});
