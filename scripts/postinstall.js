#!/usr/bin/env node
"use strict";

const { execSync } = require("child_process");
const path = require("path");
const ROOT = path.join(__dirname, "..");

function run(cmd) {
  execSync(cmd, { cwd: ROOT, stdio: "inherit" });
}

function which(bin) {
  try { execSync(`which ${bin}`, { stdio: "ignore" }); return true; }
  catch { return false; }
}

console.log("\n── templlm: setting up Python dependencies ──\n");

// Detect python binary
const py = which("python3") ? "python3" : which("python") ? "python" : null;
if (!py) {
  console.error("WARNING: Python not found. Install Python 3.8+ then run:");
  console.error("  pip install -r requirements.txt");
  console.error("  python -m playwright install chromium\n");
  process.exit(0);
}

try {
  console.log("1/2  Installing pip packages...");
  run(`${py} -m pip install -r requirements.txt --quiet`);

  console.log("2/2  Installing Playwright browser (chromium)...");
  run(`${py} -m playwright install chromium`);

  console.log("\n✓ Setup complete. Run `templlm --setup` to log in to ChatGPT.\n");
} catch (err) {
  console.error("\nWARNING: Automatic setup failed. Run these manually:");
  console.error(`  ${py} -m pip install -r requirements.txt`);
  console.error(`  ${py} -m playwright install chromium\n`);
}
