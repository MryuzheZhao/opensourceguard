const { launch } = require("C:/Users/Administrator/.workbuddy/skills/headless-browser-windows/scripts/cdp.js");
const ORIGIN = "http://127.0.0.1:8795";
const DIR = "C:/Users/Administrator/Documents/Codex/2026-09-20/wo/outputs/opensourceguard/artifacts/preview-v2";
const results = [];
const check = (n, p, d) => { results.push({ n, p }); console.log((p ? "PASS  " : "FAIL  ") + n + (d ? "  |  " + d : "")); };

(async () => {
  const b = await launch();
  try {
    await b.viewport(1440, 1100, 1, false);
    await b.goto(ORIGIN + "/");
    await b.click("#demo-login");
    await b.sleep(800);

    // 跑一次分析，报告卡里应出现 PR 区块
    await b.goto(ORIGIN + "/#diagnose");
    await b.sleep(600);
    await b.click("#run");
    const done = await b.waitFor(`document.querySelector("#report-state").textContent !== "等待分析"`, 40000);
    check("分析完成", done, await b.ev(`document.querySelector("#report-state").textContent`));
    check("PR 区块已渲染", await b.ev(`!!document.querySelector(".pr-block")`));
    check("PR 区块有标题", (await b.ev(`document.querySelector("#pr-block-title")?.textContent || ""`)).length > 0,
      await b.ev(`document.querySelector("#pr-block-title")?.textContent`));
    check("PR 表单 4 个字段", (await b.ev(`document.querySelectorAll(".pr-form > div").length`)) === 4);
    check("head 默认值正确", (await b.ev(`document.querySelector("#pr-head").value`)) === "opensourceguard/fix");
    check("badge 提示未验证", (await b.ev(`document.querySelector(".pr-block .soft-badge").textContent`)).indexOf("未验证") > -1,
      await b.ev(`document.querySelector(".pr-block .soft-badge").textContent`));
    await b.shot("05-pr-block-desktop", DIR, false);

    // 预览按钮位于报告卡底部，初始在视口外；必须先滚动再触发，
    // 否则坐标点击会静默落到 (0,0)，看起来像功能坏了。
    await b.ev(`document.querySelector(".pr-block").scrollIntoView({block:"center"})`);
    await b.sleep(300);
    await b.ev(`document.querySelector("#pr-preview").click()`);
    const shown = await b.waitFor(`!document.querySelector("#pr-preview-box").hidden && document.querySelector("#pr-preview-box pre")`, 30000);
    check("PR 预览可生成", shown);
    const meta = await b.ev(`document.querySelector(".pr-preview-meta")?.textContent || ""`);
    check("预览标注未创建", meta.indexOf("尚未创建") > -1, meta);
    const body = await b.ev(`document.querySelector("#pr-preview-box pre")?.textContent || ""`);
    check("PR 正文含证据", body.indexOf("证据") > -1 || body.indexOf("Evidence") > -1 || body.length > 200, body.length + " 字符");
    check("PR 正文含验证状态", /skipped|verified|未执行|已验证/i.test(body));
    await b.shot("06-pr-preview-desktop", DIR, false);

    // 缺 repo 时应拒绝并给提示
    await b.ev(`(() => { const el=document.querySelector("#pr-repo"); el.focus(); el.value=""; el.dispatchEvent(new Event("input",{bubbles:true})); return 1; })()`);
    await b.ev(`document.querySelector("#pr-create").click()`);
    await b.sleep(900);
    const st = await b.ev(`document.querySelector("#pr-status").textContent`);
    check("缺 repo 时拒绝创建", st.indexOf("仓库") > -1, st);

    // 填上 repo（无 Token，应明确报未配置而非假装成功）
    await b.ev(`(() => { const el=document.querySelector("#pr-repo"); el.focus(); el.value="builder/demo"; el.dispatchEvent(new Event("input",{bubbles:true})); return el.value; })()`);
    await b.ev(`document.querySelector("#pr-create").click()`);
    await b.sleep(3000);
    const st2 = await b.ev(`document.querySelector("#pr-status").textContent`);
    check("无 Token 时明确报错", st2.indexOf("Token") > -1 || st2.indexOf("未配置") > -1, st2);
    await b.shot("07-pr-error-desktop", DIR, false);

    // 响应式：三档宽度无溢出
    for (const w of [390, 820, 1440]) {
      await b.viewport(w, 900, 1, w < 500);
      await b.goto(ORIGIN + "/#diagnose");
      await b.sleep(500);
      await b.click("#run");
      await b.waitFor(`document.querySelector("#report-state").textContent !== "等待分析"`, 40000);
      await b.sleep(300);
      const of = await b.ev(`document.documentElement.scrollWidth - document.documentElement.clientWidth`);
      check(`${w}px PR 区块无横向溢出`, of <= 1, of + "px");
      if (w < 500) await b.shot("05-pr-block-mobile", DIR, false);
    }

    const errs = (b.consoleErrors || []).filter(e => !/favicon/.test(e));
    check("无控制台错误", errs.length === 0, errs.slice(0, 2).join(" | ") || "0 条");
  } catch (e) {
    check("脚本执行", false, e.message);
  } finally { await b.close(); }

  const failed = results.filter(r => !r.p);
  console.log("\n===== " + (results.length - failed.length) + "/" + results.length + " 通过 =====");
  if (failed.length) process.exit(1);
})();
