#!/usr/bin/env node
"use strict";

const { execSync, spawnSync } = require("child_process");
const readline = require("readline");
const path     = require("path");
const fs       = require("fs");

const ROOT = path.join(__dirname, "..");

// ── Colours ───────────────────────────────────────────────────────────────────
const c = {
  reset:  "\x1b[0m",
  bold:   "\x1b[1m",
  dim:    "\x1b[2m",
  green:  "\x1b[32m",
  yellow: "\x1b[33m",
  cyan:   "\x1b[36m",
  red:    "\x1b[31m",
  white:  "\x1b[37m",
};
const ok    = `${c.green}✓${c.reset}`;
const warn  = `${c.yellow}!${c.reset}`;
const err   = `${c.red}✗${c.reset}`;
const arrow = `${c.cyan}›${c.reset}`;

// ── OS detection ──────────────────────────────────────────────────────────────
function detectOS() {
  const p = process.platform;
  if (p === "win32")  return { name: "Windows",  platform: p, distro: null };
  if (p === "darwin") return { name: "macOS",    platform: p, distro: null };
  try {
    const rel   = fs.readFileSync("/etc/os-release", "utf8");
    const id    = (rel.match(/^ID=(.+)$/m)  || [])[1]?.replace(/"/g, "") ?? "linux";
    const pretty= (rel.match(/^PRETTY_NAME="?([^"\n]+)"?/m) || [])[1] ?? "Linux";
    return { name: pretty, platform: p, distro: id.toLowerCase() };
  } catch {
    return { name: "Linux", platform: p, distro: "linux" };
  }
}

// ── Python detection ──────────────────────────────────────────────────────────
function detectPython() {
  for (const bin of ["python3", "python"]) {
    try {
      const out = execSync(`${bin} --version 2>&1`, { stdio: "pipe" }).toString().trim();
      const m   = out.match(/Python (\d+\.\d+)/);
      if (m) return { bin, version: m[1] };
    } catch {}
  }
  return null;
}

// ── Chrome detection ──────────────────────────────────────────────────────────
function detectChrome() {
  const candidates = {
    win32:  [
      "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
      "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
      "%LOCALAPPDATA%\\Google\\Chrome\\Application\\chrome.exe",
    ],
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
  for (const bin of ["google-chrome-stable", "google-chrome", "chromium", "chromium-browser"]) {
    try { execSync(`which ${bin}`, { stdio: "ignore" }); return bin; } catch {}
  }
  return null;
}

// ── Install hint tables ───────────────────────────────────────────────────────
function pythonHint({ platform, distro }) {
  if (platform === "win32")  return "  winget install Python.Python.3\n  OR: https://python.org/downloads";
  if (platform === "darwin") return "  brew install python\n  OR: https://python.org/downloads";
  const m = {
    arch:    "  sudo pacman -S python python-pip",
    manjaro: "  sudo pacman -S python python-pip",
    ubuntu:  "  sudo apt install python3 python3-pip",
    debian:  "  sudo apt install python3 python3-pip",
    fedora:  "  sudo dnf install python3 python3-pip",
    centos:  "  sudo yum install python3 python3-pip",
    opensuse:"  sudo zypper install python3 python3-pip",
  };
  return m[distro] || "  https://python.org/downloads";
}

function chromeHint({ platform, distro }) {
  if (platform === "win32")  return "  winget install Google.Chrome\n  OR: https://google.com/chrome";
  if (platform === "darwin") return "  brew install --cask google-chrome\n  OR: https://google.com/chrome";
  const m = {
    arch:    "  yay -S google-chrome  OR  paru -S google-chrome",
    manjaro: "  pamac install google-chrome",
    ubuntu:  "  sudo apt install google-chrome-stable  (needs Google PPA)\n  OR: https://google.com/chrome",
    fedora:  "  sudo dnf install google-chrome-stable",
    debian:  "  https://google.com/chrome  (download .deb)",
  };
  return m[distro] || "  https://google.com/chrome";
}

function chromeDebugCmd(chromePath, { platform }) {
  const dataDir = platform === "win32"
    ? "C:\\temp\\chrome-cdp-profile"
    : "/tmp/chrome-cdp-profile";
  const chrome  = chromePath.includes(" ") ? `"${chromePath}"` : chromePath;
  if (platform === "win32") {
    return `& ${chrome} --remote-debugging-port=9222 --user-data-dir="${dataDir}"`;
  }
  return `${chrome} --remote-debugging-port=9222 --user-data-dir=${dataDir}`;
}

// ── Readline helper ───────────────────────────────────────────────────────────
function prompt(rl, question) {
  return new Promise(resolve => rl.question(question, resolve));
}

async function choose(rl, question, options) {
  console.log(`\n${c.bold}${question}${c.reset}`);
  options.forEach((o, i) => console.log(`  ${c.cyan}${i + 1}${c.reset}  ${o}`));
  while (true) {
    const ans = (await prompt(rl, `\n${arrow} `)).trim();
    const n   = parseInt(ans, 10);
    if (n >= 1 && n <= options.length) return n - 1;
    console.log(`${warn}  Enter a number between 1 and ${options.length}`);
  }
}

async function confirm(rl, question, defaultYes = true) {
  const hint = defaultYes ? "(Y/n)" : "(y/N)";
  const ans  = (await prompt(rl, `${c.bold}${question}${c.reset} ${c.dim}${hint}${c.reset} `)).trim().toLowerCase();
  if (!ans) return defaultYes;
  return ans === "y" || ans === "yes";
}

// ── Main wizard ───────────────────────────────────────────────────────────────
async function run() {
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  rl.on("close", () => process.exit(0));

  console.log(`\n${c.bold}${c.cyan}┌────────────────────────────────────────┐${c.reset}`);
  console.log(`${c.bold}${c.cyan}│          templlm  ·  setup wizard       │${c.reset}`);
  console.log(`${c.bold}${c.cyan}└────────────────────────────────────────┘${c.reset}\n`);

  // ── OS ──
  const os = detectOS();
  console.log(`${c.dim}Detected OS:${c.reset}  ${c.bold}${os.name}${c.reset}`);

  // ── Python ──
  const py = detectPython();
  if (py) {
    console.log(`${c.dim}Python:${c.reset}       ${ok} ${py.version}  ${c.dim}(${py.bin})${c.reset}`);
  } else {
    console.log(`${c.dim}Python:${c.reset}       ${err} not found`);
    console.log(`\n${c.yellow}Install Python 3.8+ first:${c.reset}`);
    console.log(pythonHint(os));
    console.log(`\nThen re-run: ${c.cyan}templlm init${c.reset}`);
    rl.close(); return;
  }

  // ── Connection mode ──
  const modeIdx = await choose(rl,
    "Which connection mode?",
    [
      `${c.bold}Mode A — CDP${c.reset}  ${c.dim}(recommended)${c.reset}  Connect to your own Chrome with an active session`,
      `${c.bold}Mode B — Headless${c.reset}               Playwright launches Chromium in the background`,
    ]
  );

  if (modeIdx === 0) {
    // ── Mode A ──
    const chrome = detectChrome();
    if (chrome) {
      console.log(`\n${ok}  Chrome found: ${c.dim}${chrome}${c.reset}`);
    } else {
      console.log(`\n${warn}  Chrome not found.`);
      console.log(`${c.yellow}Install it:${c.reset}`);
      console.log(chromeHint(os));

      const cont = await confirm(rl, "\nContinue anyway?", false);
      if (!cont) { rl.close(); return; }
    }

    const cmd = chromeDebugCmd(chrome || "google-chrome", os);
    console.log(`\n${c.bold}Step 1 — Open Chrome with remote debugging:${c.reset}`);
    console.log(`\n  ${c.cyan}${cmd}${c.reset}`);
    console.log(`\n${c.dim}Log in to ChatGPT in that window, then come back here.${c.reset}`);

    await confirm(rl, "\nDone logging in?");

    // Write CDP_URL to .env
    const envPath = path.join(ROOT, ".env");
    let envContent = fs.existsSync(envPath) ? fs.readFileSync(envPath, "utf8") : "";
    if (envContent.includes("CDP_URL=")) {
      envContent = envContent.replace(/^CDP_URL=.*$/m, "CDP_URL=http://localhost:9222");
    } else {
      envContent += "\nCDP_URL=http://localhost:9222\n";
    }
    fs.writeFileSync(envPath, envContent);
    console.log(`\n${ok}  .env updated — CDP_URL=http://localhost:9222`);

  } else {
    // ── Mode B ──
    console.log(`\n${ok}  Mode B selected — no Chrome needed.`);
    console.log(`${c.dim}Playwright will manage its own Chromium browser.${c.reset}`);

    const envPath = path.join(ROOT, ".env");
    let envContent = fs.existsSync(envPath) ? fs.readFileSync(envPath, "utf8") : "";
    // Remove CDP_URL or blank it
    envContent = envContent.replace(/^CDP_URL=.*$/m, "CDP_URL=");
    if (!envContent.includes("CDP_URL=")) envContent += "\nCDP_URL=\n";
    fs.writeFileSync(envPath, envContent);
    console.log(`${ok}  .env updated — CDP_URL cleared`);

    const runSetup = await confirm(rl, "\nRun first-time session setup now? (opens a browser window to log in)");
    if (runSetup) {
      spawnSync("python", [path.join(ROOT, "cli.py"), "--setup"], { stdio: "inherit", cwd: ROOT });
    }
  }

  console.log(`\n${c.green}${c.bold}✓ Setup complete!${c.reset}`);
  console.log(`\nStart the server:  ${c.cyan}python run.py${c.reset}`);
  console.log(`Then prompt:       ${c.cyan}templlm "hello"${c.reset}`);
  console.log(`Or streaming:      ${c.cyan}templlm --stream "hello"${c.reset}\n`);

  rl.close();
}

run().catch(e => { console.error(e.message); process.exit(1); });
