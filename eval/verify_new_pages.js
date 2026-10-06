// Verify the new pages (project finder, issue digest, demo banner) in a real browser.
const { spawn } = require("child_process");
const http = require("http");
const fs = require("fs");
const path = require("path");
const WebSocket = require("ws");

const BROWSER = process.env.HF_BROWSER;
const BASE = process.env.OSG_BASE || "http://127.0.0.1:8788";
const OUT = process.env.OSG_OUT || "artifacts/preview";
const PORT = 9366;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const getJSON = (u) => new Promise((res, rej) => http.get(u, (r) => {
  let b = ""; r.on("data", (c) => b += c); r.on("end", () => { try { res(JSON.parse(b)); } catch (e) { rej(e); } });
}).on("error", rej));

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const proc = spawn(BROWSER, ["--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
    `--remote-debugging-port=${PORT}`, "--window-size=1440,1100", "about:blank"], { stdio: "ignore" });

  let target = null;
  for (let i = 0; i < 40 && !target; i++) {
    await sleep(300);
    try { target = (await getJSON(`http://127.0.0.1:${PORT}/json/list`)).find((t) => t.type === "page"); } catch (_) {}
  }
  if (!target) { console.error("FAIL: no page"); proc.kill(); process.exit(1); }

  const ws = new WebSocket(target.webSocketDebuggerUrl, { perMessageDeflate: false, maxPayload: 256 * 1024 * 1024 });
  let id = 0; const pend = new Map(); const errors = [];
  await new Promise((r) => ws.on("open", r));
  ws.on("message", (raw) => {
    const m = JSON.parse(raw.toString());
    if (m.id && pend.has(m.id)) { pend.get(m.id).resolve(m.result); pend.delete(m.id); }
    if (m.method === "Log.entryAdded" && m.params.entry.level === "error") errors.push(m.params.entry.text);
  });
  const send = (method, params = {}) => new Promise((res) => { const i = ++id; pend.set(i, { resolve: res }); ws.send(JSON.stringify({ id: i, method, params })); });
  const ev = async (e) => {
    const r = await send("Runtime.evaluate", { expression: e, awaitPromise: true, returnByValue: true });
    return r && r.result ? r.result.value : undefined;
  };
  await send("Page.enable"); await send("Runtime.enable"); await send("Log.enable");

  async function shot(name, w = 1440, h = 1100) {
    await send("Emulation.setDeviceMetricsOverride", { width: w, height: h, deviceScaleFactor: 1, mobile: w < 600 });
    await sleep(600);
    const { data } = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
    fs.writeFileSync(path.join(OUT, `${name}.png`), Buffer.from(data, "base64"));
    console.log(`  saved ${name}.png`);
  }

  await send("Page.navigate", { url: `${BASE}/` });
  await sleep(2200);
  await ev(`document.querySelector("#demo-login").click()`);
  await sleep(1600);
  console.log("logged in:", await ev(`document.querySelector("#auth-screen").hasAttribute("hidden")`));

  // Demo banner (judge account)
  await sleep(1200);
  console.log("demo banner:", await ev(`document.querySelector("#demo-banner")?.textContent?.trim().slice(0,40) || "(none)"`));

  // Navigation structure
  console.log("nav:", JSON.stringify(await ev(
    `[...document.querySelectorAll("[data-nav]")].map(a=>(a.querySelector(".nav-step")?.textContent||"-")+":"+a.querySelector("span:not(.nav-step):not(.nav-dot)")?.textContent)`)));

  // 1. Natural-language project finder
  await ev(`window.location.hash="#projects"`); await sleep(900);
  await ev(`document.querySelector("#finder-query").value="开源治理的 python 项目"`);
  await ev(`document.querySelector("#finder-run").click()`);
  for (let i = 0; i < 90; i++) { await sleep(500); if (await ev(`!!document.querySelector(".finder-hit")`)) break; }
  console.log("finder hits:", await ev(`document.querySelectorAll(".finder-hit").length`));
  console.log("finder status:", await ev(`document.querySelector("#finder-status")?.textContent?.trim()`));
  await shot("07-finder");

  // 2. Issue digest
  await ev(`window.location.hash="#issues"`); await sleep(900);
  for (let i = 0; i < 120; i++) { await sleep(500); if (await ev(`!!document.querySelector(".issue-cluster")`)) break; }
  console.log("clusters:", await ev(`document.querySelectorAll(".issue-cluster").length`));
  console.log("headline:", await ev(`document.querySelector(".digest-headline h2")?.textContent?.trim().slice(0,60)`));
  console.log("has cause field:", await ev(`!!document.querySelector(".cluster-field.cause")`));
  console.log("has change field:", await ev(`!!document.querySelector(".cluster-field.change")`));
  await shot("08-issues");

  // Schedule box
  await ev(`document.querySelector("#digest-schedule").click()`); await sleep(900);
  console.log("schedule box:", await ev(`!!document.querySelector(".schedule-box")`));

  // 3. Responsive
  const overflow = {};
  for (const [name, w, h] of [["09-issues-390", 390, 900], ["10-issues-820", 820, 1000]]) {
    await send("Emulation.setDeviceMetricsOverride", { width: w, height: h, deviceScaleFactor: 1, mobile: w < 600 });
    await sleep(800);
    overflow[w] = await ev(`document.documentElement.scrollWidth - document.documentElement.clientWidth`);
    await shot(name, w, h);
  }

  console.log("\n=== RESULTS ===");
  console.log("overflow:", JSON.stringify(overflow));
  console.log("console errors:", errors.length);
  errors.slice(0, 8).forEach((e) => console.log("  ERR:", e.slice(0, 180)));
  ws.close(); proc.kill(); process.exit(0);
})().catch((e) => { console.error("FATAL:", e.message); process.exit(1); });
