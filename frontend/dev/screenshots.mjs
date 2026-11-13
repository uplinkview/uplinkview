// Zrzuty ekranu panelu do README (docs/img/) z atrapy API, po angielsku, przez Chrome headless (DevTools Protocol).
// Najpierw: podgląd „mock-api” i „panel” z .claude/launch.json (atrapa na 8000, Vite na 5173). Potem z katalogu frontend/:
//   node dev/screenshots.mjs            (w Git Bash: MSYS_NO_PATHCONV=1 – inaczej ścieżki "/..." zamienia na Windowsowe)
// Chrome: CHROME=ścieżka, domyślnie typowa instalacja na Windowsie. Konto w atrapie: admin / mock-screenshots-only.
import { spawn } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const SHOTS = [
  ["/", "dashboard-light.png", "light"],
  ["/", "dashboard-dark.png", "dark"],
  ["/topology", "network-map.png", "light"],
];
const BASE = process.env.PANEL_URL ?? "http://localhost:5173";
const OUT = new URL("../../docs/img/", import.meta.url);
const CHROME = process.env.CHROME ?? "C:/Program Files/Google/Chrome/Application/chrome.exe";
const W = 1440, H = 900, PORT = 9333;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const chrome = spawn(CHROME, ["--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${mkdtempSync(join(tmpdir(), "np-shot-"))}`,
  `--window-size=${W},${H}`, "--hide-scrollbars", "about:blank"], { stdio: "ignore" });
try {
  let targets;
  for (let i = 0; i < 50 && !targets; i++) {
    try { targets = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json(); } catch { await sleep(200); }
  }
  const ws = new WebSocket(targets.find((t) => t.type === "page").webSocketDebuggerUrl);
  await new Promise((r) => ws.addEventListener("open", r));
  let id = 0;
  const pending = new Map();
  ws.addEventListener("message", (e) => { const m = JSON.parse(e.data); pending.get(m.id)?.(m); pending.delete(m.id); });
  const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
  const run = async (expression) => (await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true })).result?.result?.value;
  const open = async (path, wait) => { await send("Page.navigate", { url: BASE + path }); await sleep(wait); };

  await send("Emulation.setDeviceMetricsOverride", { width: W, height: H, deviceScaleFactor: 1, mobile: false });
  await open("/favicon.svg", 1500);
  const status = await run(`(async () => {
    const h = { "content-type": "application/json" }, body = JSON.stringify({ username: "admin", password: "mock-screenshots-only" });
    let r = await fetch("/api/auth/setup", { method: "POST", headers: h, body });
    if (r.status === 409) r = await fetch("/api/auth/login", { method: "POST", headers: h, body });
    return r.status; })()`);
  if (status >= 300) throw new Error(`logowanie do atrapy: HTTP ${status}`);
  for (const [path, file, theme] of SHOTS) {
    await open("/favicon.svg", 800); // localStorage w adresie panelu, zanim panel wystartuje
    await run(`localStorage.setItem("netpulse.language", "en"); localStorage.setItem("netpulse.theme", "${theme}")`);
    await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: theme }] });
    await open(path, 7000);
    const shot = await send("Page.captureScreenshot", { format: "png" });
    writeFileSync(new URL(file, OUT), Buffer.from(shot.result.data, "base64"));
    console.log("zapisano", file);
  }
  ws.close();
} finally {
  chrome.kill();
}
