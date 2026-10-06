// Measure real overflow at 390px instead of guessing from a screenshot.
const { spawn } = require("child_process");
const http = require("http");
const WebSocket = require("ws");
const BROWSER = process.env.HF_BROWSER, PORT = 9355;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const getJSON = (u) => new Promise((res, rej) => http.get(u, (r) => { let b = ""; r.on("data", (c) => b += c); r.on("end", () => { try { res(JSON.parse(b)); } catch (e) { rej(e); } }); }).on("error", rej));

(async () => {
  const p = spawn(BROWSER, ["--headless=new", "--disable-gpu", "--no-sandbox", `--remote-debugging-port=${PORT}`, "--window-size=390,900", "about:blank"], { stdio: "ignore" });
  let t = null;
  for (let i = 0; i < 40 && !t; i++) { await sleep(300); try { t = (await getJSON(`http://127.0.0.1:${PORT}/json/list`)).find((x) => x.type === "page"); } catch (_) {} }
  const ws = new WebSocket(t.webSocketDebuggerUrl, { perMessageDeflate: false });
  let id = 0; const pend = new Map();
  await new Promise((r) => ws.on("open", r));
  ws.on("message", (raw) => { const m = JSON.parse(raw.toString()); if (m.id && pend.has(m.id)) { pend.get(m.id).resolve(m.result); pend.delete(m.id); } });
  const send = (method, params = {}) => new Promise((res) => { const i = ++id; pend.set(i, { resolve: res }); ws.send(JSON.stringify({ id: i, method, params })); });
  const ev = async (e) => (await send("Runtime.evaluate", { expression: e, awaitPromise: true, returnByValue: true })).result.value;

  await send("Page.enable"); await send("Runtime.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 900, deviceScaleFactor: 1, mobile: true });
  await send("Page.navigate", { url: "http://127.0.0.1:8787/" }); await sleep(2000);
  await ev(`document.querySelector("#demo-login").click()`); await sleep(1200);
  await ev(`window.location.hash="#health"`); await sleep(600);
  await ev(`document.querySelector("#health-run")?.click()`);
  for (let i = 0; i < 80; i++) { await sleep(500); if (await ev(`!!document.querySelector(".health-hero")`)) break; }
  for (let i = 0; i < 40; i++) { await sleep(500); if (await ev(`!!document.querySelector("#contributor-panel:not([hidden])")`)) break; }

  console.log("=== 390px overflow audit ===");
  console.log("document:", JSON.stringify(await ev(`({scrollW:document.documentElement.scrollWidth,clientW:document.documentElement.clientWidth})`)));
  console.log("elements wider than viewport:", JSON.stringify(await ev(
    `[...document.querySelectorAll("body *")].filter(e=>{const r=e.getBoundingClientRect();return r.width>394&&r.left<390&&getComputedStyle(e).position!=="fixed"}).slice(0,10).map(e=>e.tagName+"."+(e.className||"").toString().split(" ")[0]+" w="+Math.round(e.getBoundingClientRect().width))`
  )));
  console.log("code blocks with h-overflow:", JSON.stringify(await ev(
    `[...document.querySelectorAll(".code-block,.pr-commands code,pre")].filter(e=>e.scrollWidth-e.clientWidth>2).map(e=>(e.className||e.tagName)+" +"+(e.scrollWidth-e.clientWidth)+"px")`
  )));
  console.log("nav wraps ok:", JSON.stringify(await ev(
    `(()=>{const s=document.querySelector(".sidebar");if(!s)return"none";const r=s.getBoundingClientRect();return{w:Math.round(r.width),scrollW:s.scrollWidth,overflow:s.scrollWidth-s.clientWidth}})()`
  )));
  console.log("smallest font sizes in px:", JSON.stringify(await ev(
    `[...new Set([...document.querySelectorAll(".health-dimension li,.check-list span,.pr-commands code,.lang-chip")].map(e=>getComputedStyle(e).fontSize))].sort()`
  )));
  console.log("health grid cols:", await ev(`getComputedStyle(document.querySelector(".health-grid")).gridTemplateColumns`));
  console.log("pr-steps cols:", await ev(`getComputedStyle(document.querySelector(".pr-steps")).gridTemplateColumns`));
  ws.close(); p.kill(); process.exit(0);
})();
