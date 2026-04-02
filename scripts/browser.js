"use strict";

const net    = require("net");
const fs     = require("fs");
const path   = require("path");
const os     = require("os");
const { execSync, spawn } = require("child_process");

const CDP_PORT = 9222;
const ROOT     = path.join(__dirname, "..");

function isPortOpen(port) {
  return new Promise(resolve => {
    const s = net.createConnection(port, "127.0.0.1");
    s.on("connect", () => { s.destroy(); resolve(true); });
    s.on("error",   () => resolve(false));
  });
}

function getMode() {
  const envPath = path.join(ROOT, ".env");
  if (!fs.existsSync(envPath)) return "headless";
  const content = fs.readFileSync(envPath, "utf8");
  const match   = content.match(/^CDP_URL=(.+)$/m);
  return match && match[1].trim() ? "cdp" : "headless";
}

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
    darwin: ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"],
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
  try {
    const child = spawn(chromePath, [
      `--remote-debugging-port=${CDP_PORT}`,
      `--user-data-dir=${dataDir}`,
    ], { detached: true, stdio: "ignore", windowsHide: false });
    child.unref();
    return true;
  } catch {
    return false;
  }
}

async function ensureBrowser() {
  if (await isPortOpen(CDP_PORT)) return true;

  const chromePath = detectChrome();
  if (!chromePath) return false;

  if (!launchChrome(chromePath)) return false;

  for (let i = 0; i < 20; i++) {
    await new Promise(r => setTimeout(r, 500));
    if (await isPortOpen(CDP_PORT)) return true;
  }
  return false;
}

module.exports = { getMode, detectChrome, launchChrome, ensureBrowser, CDP_PORT };
