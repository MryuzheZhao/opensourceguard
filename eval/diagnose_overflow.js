// Locate which element actually overflows at 390px, instead of guessing.
const { spawn } = require("child_process");
const http = require("http");
const WebSocket = require("ws");
const BROWSER = process.env.HF_BROWSER, PORT = 9377;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const getJSON = (u) => new Promise((res, rej) => http.get(u, (r) => {
  let b = ""; r.on("data", (c) => b += c); r.on("end", () => { try { res(JSON.parse(b)); } catch (e) { rej(e); } });
}).on("error", rej));

(async () => {
  const proc = spawn(BROWSER, ["--headless=new", "--disable-gpu", "--no-sandbox",
    `--remote-debugging-port=${PORT}`, "--window-size=390,900", "about:blank"], { stdio: "ignore" });
  let target = null;
  for (let i = 0; i < 40 && !target; i++) {
    await sleep(300);
    try { target = (await getJSON(`http://127.0.0.1:${PORT}/json/list`)).find((t) => t.type === "page"); } catch (_) {}
  }
  const ws = new WebSocket(target.webSocketDebuggerUrl, { perMessageDeflate: false });
  let id = 0; const pend = new Map();
  await new Promise((r) => ws.on("open", r));
  ws.on("message", (raw) => { const m = JSON.parse(raw.toString()); if (m.id && pend.has(m.id)) { pend.get(m.id).resolve(m.result); pend.delete(m.id); } });
  const send = (method, params = {}) => new Promise((res) => { const i = ++id; pend.set(i, { resolve: res }); ws.send(JSON.stringify({ id: i, method, params })); });
  const ev = async (e) => { const r = await send("Runtime.evaluate", { expression: e, awaitPromise: true, returnByValue: true }); return r && r.result ? r.result.value : undefined; };

  await send("Page.enable"); await send("Runtime.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 900, deviceScaleFactor: 1, mobile: true });
  await send("Page.navigate", { url: "http://127.0.0.1:8788/" });
  await sleep(2200);
  await ev(`document.querySelector("#demo-login").click()`);
  await sleep(1500);
  await ev(`window.location.hash="#issues"`);
  await sleep(1000);
  for (let i = 0; i < 120; i++) { await sleep(500); if (await ev(`!!document.querySelector(".issue-cluster")`)) break; }
  await ev(`document.querySelector("#digest-schedule")?.click()`);
  await sleep(900);

  console.log("doc overflow:", await ev(`document.documentElement.scrollWidth - document.documentElement.clientWidth`));
  console.log("\nelements extending past 390px:");
  console.log(await ev(`
    [...document.querySelectorAll("body *")]
      .map(e => { const r = e.getBoundingClientRect(); return { e, right: r.right, w: r.width }; })
      .filter(x => x.right > 391 && x.w > 0 && getComputedStyle(x.e).position !== "fixed")
      .sort((a,b) => b.right - a.right)
      .slice(0, 12)
      .map(x => x.e.tagName + "." + (x.e.className||"").toString().trim().split(/\\s+/)[0]
        + " right=" + x.right.toFixed(0) + " w=" + x.w.toFixed(0)
        + " scrollW=" + x.e.scrollWidth)
      .join("\\n")
  `));
  console.log("\nelements with internal h-scroll:");
  console.log(await ev(`
    [...document.querySelectorAll("body *")]
      .filter(e => e.scrollWidth - e.clientWidth > 2 && e.clientWidth > 0)
      .slice(0, 12)
      .map(e => e.tagName + "." + (e.className||"").toString().trim().split(/\\s+/)[0]
        + " +" + (e.scrollWidth - e.clientWidth) + "px  overflowX=" + getComputedStyle(e).overflowX)
      .join("\\n")
  `));
  ws.close(); proc.kill(); process.exit(0);
})().catch((e) => { console.error("FATAL:", e.message); process.exit(1); });
