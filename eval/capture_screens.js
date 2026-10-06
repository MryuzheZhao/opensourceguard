const { launch } = require("C:/Users/Administrator/.workbuddy/skills/headless-browser-windows/scripts/cdp.js");
const ORIGIN = "http://127.0.0.1:8791";
const DIR = "C:/Users/Administrator/Documents/Codex/2026-09-20/wo/outputs/opensourceguard/artifacts/preview-v2";
const W = Number(process.argv[2] || 1440);
const H = Number(process.argv[3] || 1000);
const TAG = process.argv[4] || "desktop";
const DSF = Number(process.argv[5] || 1);

const withTimeout = (p, ms, label) => Promise.race([
  p, new Promise((_, rej) => setTimeout(() => rej(new Error("超时 " + label)), ms)),
]);

(async () => {
  const b = await launch();
  const t0 = Date.now();
  const log = (m) => console.log(`[${((Date.now() - t0) / 1000).toFixed(1)}s] ${m}`);
  try {
    await withTimeout(b.viewport(W, H, DSF, W < 500), 20000, "viewport");
    log("viewport ok");
    await withTimeout(b.goto(ORIGIN + "/"), 25000, "goto");
    log("loaded");
    await withTimeout(b.click("#demo-login"), 15000, "login");
    await b.sleep(900);
    log("logged in");

    await withTimeout(b.goto(ORIGIN + "/#diagnose"), 20000, "goto diagnose");
    await b.sleep(600);
    log(await b.shot(`01-diagnose-${TAG}`, DIR, false));

    // 真跑一次分析（视口内即可看到关键结果）
    await withTimeout(b.click("#run"), 15000, "run");
    const ok = await withTimeout(
      b.waitFor(`document.querySelector("#report-state").textContent !== "等待分析"`, 40000), 45000, "analyze");
    log("analyze done: " + ok + " / " + await b.ev(`document.querySelector("#report-state").textContent`));
    await b.sleep(400);
    log(await b.shot(`02-result-${TAG}`, DIR, false));

    // 抽屉展开态
    await withTimeout(b.click("#more-toggle"), 10000, "more");
    await b.sleep(300);
    log(await b.shot(`03-more-open-${TAG}`, DIR, false));
    await b.ev(`document.querySelector("#more-toggle").click()`);
    await b.sleep(200);

    await withTimeout(b.goto(ORIGIN + "/#projects"), 20000, "goto projects");
    await b.sleep(2500);
    log(await b.shot(`04-projects-${TAG}`, DIR, false));
    log("DONE " + TAG);
  } catch (e) {
    console.log("ERROR " + TAG + ": " + e.message);
    process.exitCode = 1;
  } finally {
    await withTimeout(b.close(), 15000, "close").catch(() => { });
  }
})();
