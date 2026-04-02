#!/usr/bin/env node
"use strict";

const { execSync } = require("child_process");
const readline = require("readline");
const os       = require("os");
const path     = require("path");
const fs       = require("fs");
const { detectPython } = require("./python");

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

  // PATH-based lookup: `where` on Windows, `which` on Unix
  const lookupCmd = process.platform === "win32" ? "where" : "which";
  for (const bin of ["google-chrome-stable", "google-chrome", "chromium", "chromium-browser"]) {
    try { execSync(`${lookupCmd} ${bin}`, { stdio: "ignore" }); return bin; } catch {}
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
  const dataDir = path.join(os.tmpdir(), "chrome-cdp-profile");
  if (platform === "win32") {
    // cmd.exe needs: start "" "path with spaces" args
    return `start "" "${chromePath}" --remote-debugging-port=9222 --user-data-dir="${dataDir}"`;
  }
  const chrome = chromePath.includes(" ") ? `"${chromePath}"` : chromePath;
  return `${chrome} --remote-debugging-port=9222 --user-data-dir="${dataDir}" &`;
}

function launchChrome(chromePath) {
  const dataDir = path.join(os.tmpdir(), "chrome-cdp-profile");
  const args = [
    `--remote-debugging-port=9222`,
    `--user-data-dir=${dataDir}`,
  ];
  try {
    const child = require("child_process").spawn(chromePath, args, {
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
    try {
      execSync(`${py.bin} -m pip --version`, { stdio: "ignore" });
    } catch {
      console.log(`${c.yellow}Installing pip...${c.reset}`);
      execSync(`${py.bin} -m ensurepip --upgrade`, { stdio: "inherit" });
    }
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

    const chromePath = chrome || "google-chrome";
    console.log(`\n${c.bold}Step 1 — Opening Chrome with remote debugging...${c.reset}`);
    const launched = launchChrome(chromePath);

    if (launched) {
      console.log(`${ok}  Chrome launched with CDP on port 9222`);
      console.log(`\n${c.dim}A Chrome window should have opened.${c.reset}`);
      console.log(`${c.dim}Log in to ChatGPT in that window, then come back here.${c.reset}`);
    } else {
      const cmd = chromeDebugCmd(chromePath, os);
      console.log(`${warn}  Could not auto-launch Chrome. Run this manually:\n`);
      console.log(`  ${c.cyan}${cmd}${c.reset}`);
      console.log(`\n${c.dim}Log in to ChatGPT in that window, then come back here.${c.reset}`);
    }

    await confirm(rl, "\nDone logging in?");

    // Write CDP_URL to .env
    const envPath = path.join(ROOT, ".env");
    let envContent = fs.existsSync(envPath) ? fs.readFileSync(envPath, "utf8") : "";
    if (envContent.includes("CDP_URL=")) {
      envContent = envContent.replace(/^CDP_URL=.*$/m, "CDP_URL=http://127.0.0.1:9222");
    } else {
      envContent += "\nCDP_URL=http://127.0.0.1:9222\n";
    }
    fs.writeFileSync(envPath, envContent);
    console.log(`\n${ok}  .env updated — CDP_URL=http://127.0.0.1:9222`);

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

    console.log(`${c.dim}Run \`templlm\` to start the server — it will open a browser window for login on first use.${c.reset}`);
  }

  console.log(`\n${c.green}${c.bold}✓ Setup complete!${c.reset}`);
  console.log(`\n${c.bold}Try it:${c.reset}`);
  console.log(`  ${c.cyan}templlm "hello"${c.reset}       one-shot prompt`);
  console.log(`  ${c.cyan}templlm${c.reset}               interactive chat\n`);
  console.log(`${c.dim}The server starts automatically — no extra steps needed.${c.reset}\n`);

  rl.close();
}

run().catch(e => { console.error(e.message); process.exit(1); });
