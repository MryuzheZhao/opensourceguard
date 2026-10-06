const { launch } = require("C:/Users/Administrator/.workbuddy/skills/headless-browser-windows/scripts/cdp.js");

const ORIGIN = "http://127.0.0.1:8791";
const results = [];
const check = (name, pass, detail) => {
  results.push({ name, pass, detail });
  console.log((pass ? "PASS  " : "FAIL  ") + name + (detail ? "  |  " + detail : ""));
};

(async () => {
  const b = await launch();
  try {
    await b.viewport(1440, 1000, 1, false);
    await b.goto(ORIGIN + "/");

    // --- 登录页仍为首屏 ---
    check("登录页首屏可见", await b.ev(`!document.querySelector("#auth-screen").hidden`));
    await b.click("#demo-login");
    await b.sleep(900);
    check("演示登录后进入工作台", await b.ev(`document.querySelector("#auth-screen").hidden`));
    check("服务已连接", (await b.ev(`document.querySelector("#connection-text").textContent`)) === "本地服务已连接");

    // --- 首页即诊断页 ---
    check("默认落在 diagnose", await b.ev(`!document.querySelector("#view-diagnose").hidden`));
    check("首页标题为诊断", (await b.ev(`document.querySelector("#page-name").textContent`)) === "诊断与修复");
    check("首页含 Issue 输入框", await b.ev(`!!document.querySelector("#issue") && !!document.querySelector("#run")`));
    check("首页含 3 个示例 chip", (await b.ev(`document.querySelectorAll("[data-issue-preset]").length`)) === 3);
    check("侧边栏主导航仅 2 项", (await b.ev(`document.querySelectorAll("nav > .nav-item").length`)) === 2,
      "实际 " + await b.ev(`document.querySelectorAll("nav > .nav-item").length`));
    check("更多面板默认收起", await b.ev(`document.querySelector("#more-nav").hidden`));

    // --- 抽屉开合 ---
    await b.click("#more-toggle");
    await b.sleep(260);
    check("更多面板可展开", await b.ev(`!document.querySelector("#more-nav").hidden`));
    check("展开后含 5 个工具", (await b.ev(`document.querySelectorAll("#more-nav .nav-item").length`)) === 5);

    // --- 真实跑一次 demo 分析（static） ---
    await b.ev(`document.querySelector("#more-toggle").click()`);
    await b.sleep(200);
    await b.click('[data-issue-preset]');
    await b.sleep(150);
    check("示例 chip 填入输入框",
      (await b.ev(`document.querySelector("#issue").value`)).indexOf("parse_csv") > -1,
      await b.ev(`document.querySelector("#issue").value`));
    await b.click("#run");
    const ok = await b.waitFor(`document.querySelector("#report-state").textContent !== "等待分析"`, 40000);
    check("点击开始分析后出报告", ok, await b.ev(`document.querySelector("#report-state").textContent`));
    check("静态分析标记未执行", (await b.ev(`document.querySelector("#report-state").textContent`)) === "未执行代码");
    check("报告含代码证据", (await b.ev(`document.querySelectorAll("#result .evidence-row").length`)) > 0,
      (await b.ev(`document.querySelectorAll("#result .evidence-row").length`)) + " 行");
    check("报告含候选补丁", await b.ev(`document.querySelector("#result").innerText.indexOf("候选补丁") > -1`));
    check("session 条已更新", (await b.ev(`document.querySelector("#recent-title").textContent`)).length > 0,
      await b.ev(`document.querySelector("#recent-title").textContent`));

    

    // --- 旧路由别名仍可用 ---
    await b.goto(ORIGIN + "/#repair");
    await b.sleep(500);
    check("#repair 别名指向诊断页", await b.ev(`!document.querySelector("#view-diagnose").hidden`));
    await b.goto(ORIGIN + "/#health");
    await b.sleep(500);
    check("#health 别名指向报告页", await b.ev(`!document.querySelector("#view-report").hidden`));
    await b.goto(ORIGIN + "/#home");
    await b.sleep(400);
    check("#home 别名指向诊断页", await b.ev(`!document.querySelector("#view-diagnose").hidden`));

    // --- 次级页面仍可用 ---
    await b.goto(ORIGIN + "/#projects");
    await b.sleep(2500);
    check("项目页加载项目卡", (await b.ev(`document.querySelectorAll("#project-list .project-card").length`)) >= 1,
      (await b.ev(`document.querySelectorAll("#project-list .project-card").length`)) + " 个");
    check("项目页 Issue 已加载", (await b.ev(`document.querySelectorAll("#issue-list .issue-card").length`)) >= 1);
    check("推荐排序默认折叠", await b.ev(`document.querySelector(".recommendation-fold").open === false`));
    check("平台连接默认折叠", await b.ev(`document.querySelector("#connections-card").open === false`));
    check("项目页自动展开更多面板", await b.ev(`!document.querySelector("#more-nav").hidden`));

    // Agent 介入
    await b.click("#issue-list [data-assist-issue]");
    const planned = await b.waitFor(`!document.querySelector("#project-agent-result").hidden`, 40000);
    check("Agent 介入生成方案", planned);
    check("方案含待审核提示", (await b.ev(`document.querySelector("#project-agent-result").innerText`)).indexOf("Agent 已完成第一轮分析") > -1);

    await b.goto(ORIGIN + "/#publish");
    await b.sleep(800);
    await b.ev(`(() => { const el = document.querySelector("#onboard-name"); el.scrollIntoView({block:"center"}); el.focus(); el.value = "acceptance-agent"; el.dispatchEvent(new Event("input", {bubbles:true})); return el.value; })()`);
    check("发布页输入已填入", (await b.ev(`document.querySelector("#onboard-name").value`)) === "acceptance-agent");
    await b.click("#onboard-run");
    const onb = await b.waitFor(`document.querySelectorAll("#onboard-result .onboarding-step").length > 0`, 40000);
    check("发布指南生成 5 步", onb && (await b.ev(`document.querySelectorAll("#onboard-result .onboarding-step").length`)) === 5,
      (await b.ev(`document.querySelectorAll("#onboard-result .onboarding-step").length`)) + " 步");
    check("发布页提示未上传代码", (await b.ev(`document.querySelector("#onboard-result").innerText`)).indexOf("尚未上传代码") > -1);

    await b.goto(ORIGIN + "/#arena");
    await b.sleep(700);
    await b.click("#arena-run");
    const arena = await b.waitFor(`document.querySelectorAll("#arena-result .arena-row:not(.header)").length > 0`, 90000);
    check("竞技场出排行榜", arena, (await b.ev(`document.querySelectorAll("#arena-result .arena-row:not(.header)").length`)) + " 行");
    check("竞技场逐题 9 个", (await b.ev(`document.querySelectorAll("#arena-result .detail-card").length`)) === 9,
      (await b.ev(`document.querySelectorAll("#arena-result .detail-card").length`)) + " 个");

    await b.goto(ORIGIN + "/#issues");
    const digest = await b.waitFor(`document.querySelectorAll("#digest-result .issue-cluster").length > 0`, 60000);
    check("Issue 归类可用", digest, (await b.ev(`document.querySelectorAll("#digest-result .issue-cluster").length`)) + " 主题");

    await b.goto(ORIGIN + "/#report");
    await b.sleep(600);
    const health = await b.waitFor(`document.querySelectorAll("#health-result .health-dimension").length > 0`, 90000);
    check("体检报告出 5 维度", health, (await b.ev(`document.querySelectorAll("#health-result .health-dimension").length`)) + " 个");

    // --- 各路由无横向溢出（三个宽度） ---
    for (const w of [390, 820, 1440]) {
      await b.viewport(w, 900, 1, w < 500);
      for (const r of ["diagnose", "report", "projects", "repair", "issues", "health", "publish", "arena"]) {
        await b.goto(ORIGIN + "/#" + r);
        await b.sleep(320);
        const vis = await b.ev(`!document.querySelector("#view-${["home","repair","health"].indexOf(r) > -1 ? (r === "home" ? "diagnose" : r === "repair" ? "diagnose" : "report") : r}").hidden`);
        if (!vis) { check(`${w}px 路由 ${r} 可见`, false); continue; }
        const of = await b.ev(`document.documentElement.scrollWidth - document.documentElement.clientWidth`);
        if (of > 1) check(`${w}px 路由 ${r} 横向溢出`, false, of + "px");
      }
      check(`${w}px 全部 8 个路由无横向溢出`, true);
      
    }

    // --- 渲染后内容在三个宽度下都不能撑破视口（长 Git 命令是最易触发点） ---
    for (const w of [390, 820, 1440]) {
      await b.viewport(w, 900, 1, w < 500);
      await b.goto(ORIGIN + "/#publish");
      await b.sleep(700);
      await b.ev(`(() => { const el=document.querySelector("#onboard-name"); el.scrollIntoView({block:"center"}); el.focus(); el.value="a-long-project-name-for-overflow-check"; el.dispatchEvent(new Event("input",{bubbles:true})); return el.value; })()`);
      await b.click("#onboard-run");
      await b.waitFor(`document.querySelectorAll("#onboard-result .onboarding-step").length > 0`, 40000);
      const ofP = await b.ev(`document.documentElement.scrollWidth - document.documentElement.clientWidth`);
      check(`${w}px 发布指南渲染后无溢出`, ofP <= 1, ofP + "px");

      await b.goto(ORIGIN + "/#projects");
      await b.sleep(2600);
      await b.click("#issue-list [data-assist-issue]");
      await b.waitFor(`!document.querySelector("#project-agent-result").hidden`, 40000);
      const ofJ = await b.ev(`document.documentElement.scrollWidth - document.documentElement.clientWidth`);
      check(`${w}px Agent 方案渲染后无溢出`, ofJ <= 1, ofJ + "px");
    }
    await b.viewport(1440, 1000, 1, false);

    // --- 登录态持久化 ---
    await b.viewport(1440, 1000, 1, false);
    await b.goto(ORIGIN + "/#diagnose");
    await b.sleep(500);
    await b.reload();
    await b.sleep(900);
    check("刷新后仍保持登录", await b.ev(`document.querySelector("#auth-screen").hidden`));

    // --- 控制台干净 ---
    const errs = (b.consoleErrors || []).filter(e => !/favicon|net::ERR_/.test(e));
    check("无控制台错误", errs.length === 0, errs.slice(0, 3).join(" | ") || "0 条");
    const ext = (b.externalRequests || []).filter(u => /^https?:/i.test(u) && u.indexOf("127.0.0.1:8791") === -1);
    check("无外部网络请求", ext.length === 0, ext.slice(0, 2).join(" | ") || "0 条");
  } catch (e) {
    check("脚本执行", false, e.message);
  } finally {
    await b.close();
  }

  const failed = results.filter(r => !r.pass);
  console.log("\n===== " + (results.length - failed.length) + "/" + results.length + " 通过 =====");
  if (failed.length) { failed.forEach(f => console.log("FAILED: " + f.name + "  " + (f.detail || ""))); process.exit(1); }
})();
