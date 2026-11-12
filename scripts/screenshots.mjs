// Refreshes docs/screenshots/*.png from a running EGX Flow (demo mode).
//   node scripts/screenshots.mjs                      # UI at http://localhost:3100
//   UI_URL=http://localhost:3000 BROWSER="C:\path\to\chrome.exe" node scripts/screenshots.mjs
// Needs Node 22+ (built-in WebSocket) and Chrome or Edge. No npm packages.
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const UI = (process.env.UI_URL ?? "http://localhost:3100").replace(/\/$/, "");
const OUT = join(dirname(fileURLToPath(import.meta.url)), "..", "docs", "screenshots");
const PORT = 9333;
const SHOTS = [
  ["terminal", "/", 9000],
  ["whale-radar", "/whales", 5000],
  ["portfolio", "/portfolio", 5000],
  ["market", "/market", 5000],
  ["status", "/status", 4000],
];
const candidates = [
  process.env.BROWSER,
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
].filter(Boolean);
const browser = candidates.find((p) => existsSync(p));
if (!browser) throw new Error("No Chrome/Edge found. Set BROWSER=<path to the executable>.");

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
mkdirSync(OUT, { recursive: true });
const proc = spawn(browser, [
  "--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${mkdtempSync(join(tmpdir(), "egxshot-"))}`,
  "--no-first-run", "--hide-scrollbars", "--window-size=1600,950", "about:blank",
], { stdio: "ignore" });

try {
  let target;
  for (let i = 0; i < 40 && !target; i++) {
    await sleep(250);
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json();
      target = list.find((t) => t.type === "page");
    } catch { /* browser still starting */ }
  }
  if (!target) throw new Error("Browser did not expose a debugging target.");
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  let id = 0;
  const pending = new Map();
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m.result); pending.delete(m.id); }
  };
  const send = (method, params = {}) => new Promise((res) => { pending.set(++id, res); ws.send(JSON.stringify({ id, method, params })); });

  await send("Emulation.setDeviceMetricsOverride", { width: 1600, height: 950, deviceScaleFactor: 1, mobile: false });
  for (const [name, path, wait] of SHOTS) {
    await send("Page.navigate", { url: UI + path });
    await sleep(wait); // real time: lets the WebSocket snapshot arrive and the canvas paint
    const { data } = await send("Page.captureScreenshot", { format: "png" });
    writeFileSync(join(OUT, `${name}.png`), Buffer.from(data, "base64"));
    console.log(`saved docs/screenshots/${name}.png`);
  }
  ws.close();
} finally {
  proc.kill();
}
