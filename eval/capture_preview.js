// Capture screenshots of the OpenSourceGuard workbench using the managed
// headless Chromium over the DevTools protocol (no Playwright dependency).
const { spawn } = require("child_process");
const http = require("http");
const fs = require("fs");
const path = require("path");

const BROWSER = process.env.HF_BROWSER;
const BASE = process.env.OSG_BASE || "http://127.0.0.1:8787";
const OUT = process.env.OSG_OUT || "artifacts/preview";
const PORT = 9333;

function getJSON(url) {
  return new Promise((resolve, reject) => {
    http.get(url, (res) => {
      let body = "";
      res.on("data", (c) => (body += c));
      res.on("end", () => { try { resolve(JSON.parse(body)); } catch (e) { reject(e); } });
    }).on("error", reject);
  });
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

class CDP {
  constructor(wsUrl) { this.wsUrl = wsUrl; this.id = 0; this.pending = new Map(); }
  connect() {
    return new Promise((resolve, reject) => {
      const WebSocket = require("ws");
      this.ws = new WebSocket(this.wsUrl, { perMessageDeflate: false, maxPayload: 256 * 1024 * 1024 });
      this.ws.on("open", resolve);
      this.ws.on("error", reject);
      this.ws.on("message", (raw) => {
        const msg = JSON.parse(raw.toString());
        if (msg.id && this.pending.has(msg.id)) {
          const { resolve: res, reject: rej } = this.pending.get(msg.id);
          this.pending.delete(msg.id);
          if (msg.error) rej(new Error(JSON.stringify(msg.error)));
          else res(msg.result);
        }
      });
    });
  }
  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
  async evaluate(expression) {
    const r = await this.send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails));
    return r.result.value;
  }
  close() { try { this.ws.close(); } catch (_) {} }
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const proc = spawn(BROWSER, [
    "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
    `--remote-debugging-port=${PORT}`, "--window-size=1440,1100", "about:blank",
  ], { stdio: "ignore" });

  let target = null;
  for (let i = 0; i < 40 && !target; i++) {
    await sleep(300);
    try {
      const list = await getJSON(`http://127.0.0.1:${PORT}/json/list`);
      target = list.find((t) => t.type === "page");
    } catch (_) { /* browser still starting */ }
  }
  if (!target) { console.error("FAIL: no debuggable page"); proc.kill(); process.exit(1); }

  const cdp = new CDP(target.webSocketDebuggerUrl);
  await cdp.connect();
  await cdp.send("Page.enable");
  await cdp.send("Runtime.enable");
  await cdp.send("Log.enable");

  const consoleErrors = [];
  cdp.ws.on("message", (raw) => {
    const m = JSON.parse(raw.toString());
    if (m.method === "Log.entryAdded" && m.params.entry.level === "error") {
      consoleErrors.push(m.params.entry.text);
    }
  });

  async function goto(url) {
    await cdp.send("Page.navigate", { url });
    for (let i = 0; i < 50; i++) {
      await sleep(200);
      const ready = await cdp.evaluate("document.readyState === 'complete'");
      if (ready) break;
    }
    await sleep(700);
  }

  async function shot(name, width = 1440, height = 1100, full = true) {
    await cdp.send("Emulation.setDeviceMetricsOverride", {
      width, height, deviceScaleFactor: 1, mobile: width < 600,
    });
    await sleep(500);
    const params = { format: "png" };
    if (full) params.captureBeyondViewport = true;
    const { data } = await cdp.send("Page.captureScreenshot", params);
    const file = path.join(OUT, `${name}.png`);
    fs.writeFileSync(file, Buffer.from(data, "base64"));
    console.log(`  saved ${file}`);
  }

  // 1. Login via the demo account so the workbench is reachable.
  await goto(`${BASE}/`);
  await cdp.evaluate(`document.querySelector("#demo-login").click(); true`);
  await sleep(1500);
  const loggedIn = await cdp.evaluate(`document.querySelector("#auth-screen").hasAttribute("hidden")`);
  console.log("logged in:", loggedIn);
  if (!loggedIn) {
    console.error("FAIL: demo login did not unlock the workbench");
    console.error(await cdp.evaluate(`document.querySelector("#login-status")?.textContent || ""`));
  }

  await shot("01-home");

  // 2. Health dashboard: trigger the score and wait for the result to render.
  await cdp.evaluate(`window.location.hash = "#health"; true`);
  await sleep(800);
  await cdp.evaluate(`document.querySelector("#health-run")?.click(); true`);
  for (let i = 0; i < 90; i++) {
    await sleep(500);
    const done = await cdp.evaluate(`!!document.querySelector("#health-result .health-hero")`);
    if (done) break;
  }
  const scoreText = await cdp.evaluate(`document.querySelector(".health-score strong")?.textContent?.trim() || "(none)"`);
  const dimCount = await cdp.evaluate(`document.querySelectorAll(".health-dimension").length`);
  const healthStatus = await cdp.evaluate(`document.querySelector("#health-status")?.textContent?.trim() || ""`);
  console.log(`health score="${scoreText}" dimensions=${dimCount} status="${healthStatus}"`);
  await shot("02-health");

  // Wait for the contributor guide that runHealth() loads in the background.
  for (let i = 0; i < 40; i++) {
    await sleep(500);
    const shown = await cdp.evaluate(`!!document.querySelector("#contributor-panel:not([hidden])")`);
    if (shown) break;
  }
  const prSteps = await cdp.evaluate(`document.querySelectorAll(".pr-step").length`);
  const checks = await cdp.evaluate(`document.querySelectorAll(".check-list li").length`);
  const ladder = await cdp.evaluate(`document.querySelectorAll(".ladder-step").length`);
  console.log(`contributor guide: prSteps=${prSteps} checklist=${checks} ladder=${ladder}`);
  await cdp.evaluate(`document.querySelector("#contributor-panel")?.scrollIntoView(); true`);
  await sleep(400);
  await shot("03-contributor");

  // 3. Compliance audit view.
  await cdp.evaluate(`document.querySelector("#compliance-run")?.click(); true`);
  for (let i = 0; i < 60; i++) {
    await sleep(500);
    const done = await cdp.evaluate(`!!document.querySelector(".compliance-hero")`);
    if (done) break;
  }
  const compTable = await cdp.evaluate(`document.querySelectorAll(".compliance-table tbody tr").length`);
  const compFindings = await cdp.evaluate(`document.querySelectorAll(".compliance-finding").length`);
  console.log(`compliance: findings=${compFindings} depRows=${compTable}`);
  await shot("04-compliance");

  // 4. Responsive checks for horizontal overflow.
  const widths = [{ name: "05-mobile-390", w: 390, h: 900 }, { name: "06-tablet-820", w: 820, h: 1000 }];
  const overflow = {};
  for (const { name, w, h } of widths) {
    await cdp.send("Emulation.setDeviceMetricsOverride", { width: w, height: h, deviceScaleFactor: 1, mobile: w < 600 });
    await sleep(700);
    overflow[w] = await cdp.evaluate(
      `(() => { const d = document.documentElement; return { scrollW: d.scrollWidth, clientW: d.clientWidth, overflow: d.scrollWidth - d.clientWidth }; })()`
    );
    await shot(name, w, h);
  }

  console.log("\n=== RESULTS ===");
  console.log("overflow:", JSON.stringify(overflow));
  console.log("console errors:", consoleErrors.length);
  consoleErrors.slice(0, 10).forEach((e) => console.log("  ERR:", e.slice(0, 200)));

  cdp.close();
  proc.kill();
  process.exit(0);
})().catch((e) => { console.error("FATAL:", e.message); process.exit(1); });
