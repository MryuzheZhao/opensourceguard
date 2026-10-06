/* OpenSourceGuard 前端共享运行时。
   六个页面（index/report/projects/issues/publish/arena）共用本文件，
   通过 <body data-page="..."> 分发到对应控制器。 */
(() => {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const copyStore = new Map();
  const state = {
    report: null, onboarding: null, arena: null, health: null, compliance: null,
    contributorGuide: null, finder: null, digest: null, draftPr: null,
    projects: { rows: [], selected: null, issues: [], agent: null, loaded: false },
  };

  const escapeHtml = (value) => String(value ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#039;");

  const icon = (name) => `<svg class="icon" aria-hidden="true"><use href="#i-${name}"></use></svg>`;

  /* ---------------------------------------------------------- 基础工具 */

  function registerCopy(text) {
    const key = `copy-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    copyStore.set(key, String(text ?? ""));
    return key;
  }

  function statusMessage(id, message, kind = "") {
    const node = $(`#${id}`);
    if (!node) return;
    node.textContent = message;
    node.dataset.kind = kind;
  }

  let toastTimer = 0;
  function toast(message) {
    const node = $("#toast");
    if (!node) return;
    node.textContent = message;
    node.classList.add("show");
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => node.classList.remove("show"), 2200);
  }

  async function copyText(value, message = "已复制到剪贴板") {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(value);
      } else {
        const area = document.createElement("textarea");
        area.value = value;
        area.style.position = "fixed";
        area.style.opacity = "0";
        document.body.appendChild(area);
        area.focus();
        area.select();
        const copied = document.execCommand("copy");
        area.remove();
        if (!copied) throw new Error("复制失败");
      }
      toast(message);
    } catch (_) {
      toast("复制失败，请手动选择文本");
    }
  }

  function downloadFile(filename, content, type = "text/plain;charset=utf-8") {
    const blob = new Blob([content], { type });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast(`已下载 ${filename}`);
  }

  async function request(path, options = {}) {
    if (window.location.protocol === "file:") {
      throw new Error("请先启动本地服务，再打开 http://127.0.0.1:8787/");
    }
    const config = { ...options, headers: { Accept: "application/json", ...(options.headers || {}) } };
    if (config.body && typeof config.body !== "string") {
      config.headers["Content-Type"] = "application/json";
      config.body = JSON.stringify(config.body);
    }
    const controller = new AbortController();
    // /health 是快速探活；/health/report 会跑索引+扫描+审计，/arena 可能跑满任务集。
    const timeouts = { "/health": 4000, "/arena": 360000, "/health/report": 120000, "/compliance": 60000, "/repo/clone": 320000 };
    const timer = window.setTimeout(() => controller.abort(), timeouts[path] || 150000);
    try {
      const response = await fetch(path, { ...config, signal: controller.signal });
      let payload;
      try { payload = await response.json(); } catch (_) { throw new Error("服务没有返回有效结果，请重试"); }
      if (!response.ok) throw new Error(payload.error || `服务返回 ${response.status}`);
      if (!payload || typeof payload !== "object") throw new Error("服务返回结果不完整");
      return payload;
    } catch (error) {
      if (error.name === "AbortError") throw new Error("等待超时，请检查服务状态后重试");
      if (error instanceof TypeError) {
        setConnection(false, "服务未连接");
        throw new Error("无法连接本地服务，请重新启动后重试");
      }
      throw error;
    } finally { window.clearTimeout(timer); }
  }

  function setButtonLoading(button, loading, label) {
    if (!button) return;
    button.disabled = loading;
    button.classList.toggle("is-loading", loading);
    const span = button.querySelector("span");
    if (span && label) span.textContent = loading ? "正在处理…" : label;
  }

  /* ---------------------------------------------------------- 连接与外壳 */

  function setConnection(online, label, repo = "") {
    const connection = $("#connection");
    const text = $("#connection-text, .connection-text");
    if (connection) {
      connection.classList.toggle("offline", !online);
      connection.classList.toggle("checking", false);
    }
    if (text) text.textContent = label;
    const name = $("#sidebar-project-name");
    const meta = $("#sidebar-project-meta");
    const footerRepo = $("#footer-repo");
    const repoName = repo ? String(repo).split(/[\\/]/).filter(Boolean).pop() : "";
    if (name) name.textContent = repoName || "本地工作区";
    if (meta) meta.textContent = repoName ? repo : (online ? "已连接本地服务" : "等待连接服务");
    if (footerRepo) footerRepo.textContent = repo ? `当前仓库：${repo}` : "";
  }

  async function checkHealth() {
    try {
      const result = await request("/health");
      setConnection(true, "本地服务已连接", result.repo || "");
      updateModelStatus(result.model || { configured: Boolean(result.model_configured) });
    } catch (_) {
      setConnection(false, "服务未连接");
      updateModelStatus({ configured: false });
    }
  }

  function updateModelStatus(model = {}) {
    const badge = $("#model-status");
    if (!badge) return;
    const configured = Boolean(model.configured ?? model.model_configured);
    const keyReady = Boolean(model.api_key_configured);
    badge.textContent = configured
      ? (keyReady ? `模型已配置 · ${model.model || "可用"}` : "已配置地址 · 尚未设置 API Key")
      : "未配置模型 · 点击配置";
    badge.dataset.kind = configured && keyReady ? "success" : (configured ? "warn" : "");
  }

  async function loadDemoStatus() {
    const slot = $("#demo-banner-slot");
    if (!slot || $("#demo-banner")) return;
    try {
      const data = await request("/demo/status");
      if (!data.enabled) return;
      const banner = document.createElement("div");
      banner.className = "demo-banner";
      banner.id = "demo-banner";
      banner.innerHTML = `${icon("sparkles")}<div><strong>${escapeHtml(data.label || "演示账号")}</strong>：已预置模型额度，可直接体验 AI 分析，无需自行配置 API Key。</div>
        <span class="pill pill-primary">${escapeHtml(data.model || "模型就绪")}</span>
        <span class="pill">只读模式</span>`;
      slot.appendChild(banner);
    } catch (_) { /* 演示状态是可选的，失败时保持静默。 */ }
  }

  /* ------------------------------------------------------ 工作区：项目与模型 */

  function repoPickerHtml() {
    return `<div class="overlay" id="repo-picker" hidden>
    <div class="overlay-backdrop" data-overlay-close></div>
    <div class="overlay-panel" role="dialog" aria-modal="true" aria-labelledby="repo-picker-title">
      <div class="overlay-head">
        <div>
          <h2 id="repo-picker-title">选择工作项目</h2>
          <p>直接从 GitHub / Gitee / GitLab 拉取你的远程仓库（粘贴地址或在下方列表选择），也可以使用本机已有目录。切换后，诊断、体检、Issue 等全部分析都会作用于新项目。</p>
        </div>
        <button type="button" class="icon-button" data-overlay-close aria-label="关闭">${icon("x")}</button>
      </div>
      <div class="picker-input-row">
        <input class="input" id="repo-clone-url" type="text" placeholder="粘贴远程仓库地址，例如 https://github.com/owner/repo" autocomplete="off" spellcheck="false">
        <button type="button" class="btn btn-primary" id="repo-clone-confirm">${icon("download")}<span>拉取这个仓库</span></button>
      </div>
      <span class="form-status" id="repo-picker-status" role="status" aria-live="polite"></span>
      <div class="picker-remote-head">
        <span class="picker-remote-title">已连接平台的仓库（GitHub / Gitee / GitLab）</span>
        <button type="button" class="btn btn-quiet btn-sm" id="repo-remote-refresh">${icon("refresh")}<span>刷新</span></button>
      </div>
      <div class="picker-list" id="repo-remote-list"></div>
      <div class="picker-divider">或者使用本机已有目录</div>
      <div class="picker-input-row">
        <input class="input" id="repo-picker-path" type="text" placeholder="例如 C:/Users/me/project" autocomplete="off" spellcheck="false">
        <button type="button" class="btn" id="repo-picker-confirm">${icon("check")}<span>使用这个目录</span></button>
      </div>
      <div class="picker-divider">或者让助手帮你找</div>
      <div class="picker-input-row">
        <input class="input" id="repo-picker-query" type="text" placeholder="描述一下，例如：我的前端项目 / 最近改过的 Python 仓库" autocomplete="off">
        <button type="button" class="btn" id="repo-picker-scan">${icon("search")}<span>扫描</span></button>
      </div>
      <div class="picker-list" id="repo-picker-list"></div>
    </div>
  </div>`;
  }

  function modelSettingsHtml() {
    return `<div class="overlay" id="model-settings" hidden>
    <div class="overlay-backdrop" data-overlay-close></div>
    <div class="overlay-panel" role="dialog" aria-modal="true" aria-labelledby="model-settings-title">
      <div class="overlay-head">
        <div>
          <h2 id="model-settings-title">模型服务设置</h2>
          <p>接入任意兼容 OpenAI 协议的模型服务，保存后 AI 分析立即生效。API Key 只保存在本机，永远不会回显。</p>
        </div>
        <button type="button" class="icon-button" data-overlay-close aria-label="关闭">${icon("x")}</button>
      </div>
      <div class="field">
        <label class="field-label" for="model-base-url">接口地址（Base URL）</label>
        <input class="input" id="model-base-url" type="text" placeholder="例如 https://api.deepseek.com/v1" autocomplete="off" spellcheck="false">
      </div>
      <div class="field" style="margin-top:10px">
        <label class="field-label" for="model-name">模型名称</label>
        <input class="input" id="model-name" type="text" placeholder="例如 deepseek-chat" autocomplete="off" spellcheck="false">
      </div>
      <div class="field" style="margin-top:10px">
        <label class="field-label" for="model-api-key">API Key</label>
        <input class="input" id="model-api-key" type="password" placeholder="粘贴你的 API Key" autocomplete="off">
        <p class="field-note">已保存过 Key 时留空表示沿用；Key 只写入本机配置文件，不会出现在任何界面与日志中。</p>
      </div>
      <div class="field" style="margin-top:10px">
        <label class="field-label" for="model-api-style">接口协议</label>
        <select class="input" id="model-api-style">
          <option value="auto">自动识别（推荐）</option>
          <option value="chat_completions">Chat Completions（/chat/completions）</option>
          <option value="responses">Responses（/responses）</option>
        </select>
      </div>
      <div class="picker-input-row" style="margin-top:16px">
        <button type="button" class="btn btn-primary" id="model-save">${icon("check")}<span>保存并启用</span></button>
        <button type="button" class="btn" id="model-test">${icon("zap")}<span>测试连接</span></button>
        <button type="button" class="btn btn-quiet" id="model-clear">${icon("x")}<span>清除配置</span></button>
      </div>
      <span class="form-status" id="model-settings-status" role="status" aria-live="polite"></span>
    </div>
  </div>`;
  }

  function platformSettingsHtml() {
    return `<div class="overlay" id="platform-settings" hidden>
    <div class="overlay-backdrop" data-overlay-close></div>
    <div class="overlay-panel" role="dialog" aria-modal="true" aria-labelledby="platform-settings-title">
      <div class="overlay-head">
        <div>
          <h2 id="platform-settings-title">平台连接</h2>
          <p>每个平台只需要一个访问令牌（Token）：粘贴进来、点「验证并连接」，即可管理你的账户与仓库。Token 只保存在你自己的电脑上，验证后绝不会回显。</p>
        </div>
        <button type="button" class="icon-button" data-overlay-close aria-label="关闭">${icon("x")}</button>
      </div>
      <div id="platform-connections-list"></div>
      <span class="form-status" id="platform-settings-status" role="status" aria-live="polite"></span>
    </div>
  </div>`;
  }

  function ensureWorkspaceChrome() {
    const projectBox = $(".sidebar-project");
    if (projectBox && !$("[data-repo-picker-open]", projectBox)) {
      const switcher = document.createElement("button");
      switcher.type = "button";
      switcher.className = "btn btn-sm sidebar-switch";
      switcher.dataset.repoPickerOpen = "1";
      switcher.innerHTML = `${icon("folder-git-2")}<span>切换 / 拉取仓库</span>`;
      projectBox.appendChild(switcher);
    }
    const actions = $(".topbar-actions");
    if (actions && !$("#model-settings-open")) {
      const trigger = document.createElement("button");
      trigger.type = "button";
      trigger.className = "btn btn-quiet btn-sm";
      trigger.id = "model-settings-open";
      trigger.setAttribute("aria-label", "模型服务设置");
      trigger.title = "配置 AI 模型服务（接口地址 / 模型名称 / API Key）";
      trigger.innerHTML = `${icon("settings")}<span>模型设置</span>`;
      const motion = $("#motion-toggle", actions);
      actions.insertBefore(trigger, motion || null);
    }
    if (actions && !$("#platform-settings-open")) {
      const platformTrigger = document.createElement("button");
      platformTrigger.type = "button";
      platformTrigger.className = "btn btn-quiet btn-sm";
      platformTrigger.id = "platform-settings-open";
      platformTrigger.setAttribute("aria-label", "平台连接");
      platformTrigger.title = "用 Token 连接 GitHub / Gitee / GitLab 账户";
      platformTrigger.innerHTML = `${icon("globe")}<span>平台连接</span>`;
      const motion = $("#motion-toggle", actions);
      actions.insertBefore(platformTrigger, motion || null);
    }
    const modelPill = $("#model-status");
    if (modelPill && !modelPill.dataset.settingsBound) {
      modelPill.dataset.settingsBound = "1";
      modelPill.classList.add("pill-action");
      modelPill.title = "点击打开模型服务设置";
      modelPill.setAttribute("role", "button");
      modelPill.tabIndex = 0;
      modelPill.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openModelSettings(); }
      });
    }
    if (!$("#repo-picker")) {
      document.body.insertAdjacentHTML("beforeend", repoPickerHtml());
      $("#repo-picker-path")?.addEventListener("keydown", (event) => {
        if (event.key === "Enter") { event.preventDefault(); selectLocalRepo($("#repo-picker-path").value, "repo-picker-status"); }
      });
      $("#repo-picker-query")?.addEventListener("keydown", (event) => {
        if (event.key === "Enter") { event.preventDefault(); scanRepoPicker(); }
      });
      $("#repo-clone-url")?.addEventListener("keydown", (event) => {
        if (event.key === "Enter") { event.preventDefault(); cloneRemoteRepo($("#repo-clone-url").value, "repo-picker-status", $("#repo-clone-confirm")); }
      });
    }
    if (!$("#model-settings")) document.body.insertAdjacentHTML("beforeend", modelSettingsHtml());
    if (!$("#platform-settings")) document.body.insertAdjacentHTML("beforeend", platformSettingsHtml());
  }

  function openOverlay(selector) {
    const node = $(selector);
    if (node) node.hidden = false;
  }

  async function selectLocalRepo(path, statusId) {
    const target = String(path || "").trim();
    if (!target) { statusMessage(statusId, "先填写或选择一个项目目录", "error"); return; }
    statusMessage(statusId, "正在切换工作项目…");
    try {
      const data = await request("/repo/select", { method: "POST", body: { path: target } });
      statusMessage(statusId, data.message || "已切换工作项目", "success");
      toast(data.message || "已切换工作项目");
      window.setTimeout(() => window.location.reload(), 450);
    } catch (error) {
      statusMessage(statusId, error.message, "error");
    }
  }

  function renderRepoPickerList(data) {
    const list = $("#repo-picker-list");
    if (!list) return;
    const matches = (data && data.matches) || [];
    if (!matches.length) {
      list.innerHTML = `<div class="empty-state compact"><h3>没有找到匹配的项目</h3><p>换个描述，或直接粘贴完整路径。</p></div>`;
      return;
    }
    list.innerHTML = matches.slice(0, 8).map((project) => `<div class="picker-item">
      <div class="picker-meta">
        <div class="picker-name">${icon("folder")}<span>${escapeHtml(project.name || "未命名")}</span></div>
        <div class="picker-path" title="${escapeHtml(project.path || "")}">${escapeHtml(project.path || "")}</div>
      </div>
      <button type="button" class="btn btn-sm" data-repo-pick="${escapeHtml(project.path || "")}">${icon("chevron-right")}<span>使用</span></button>
    </div>`).join("");
  }

  async function scanRepoPicker() {
    const query = ($("#repo-picker-query")?.value || "").trim();
    if (!query) { statusMessage("repo-picker-status", "先用一句话描述你要找的项目", "error"); return; }
    const button = $("#repo-picker-scan");
    setButtonLoading(button, true, "扫描");
    statusMessage("repo-picker-status", "正在扫描本机常见代码目录…");
    try {
      const data = await request("/projects/find", { method: "POST", body: { query, time_budget: 8 } });
      renderRepoPickerList(data);
      const mode = data.mode === "model" ? "模型语义匹配" : "本地关键词匹配";
      statusMessage("repo-picker-status", `找到 ${(data.matches || []).length} 个候选 · ${mode}`, "success");
    } catch (error) {
      statusMessage("repo-picker-status", error.message, "error");
    } finally { setButtonLoading(button, false, "扫描"); }
  }

  async function cloneRemoteRepo(url, statusId, button) {
    const target = String(url || "").trim();
    if (!target) { statusMessage(statusId, "先粘贴或选择一个远程仓库地址", "error"); return; }
    setButtonLoading(button, true, "拉取");
    statusMessage(statusId, "正在从远程平台拉取仓库，私有仓库会自动使用已保存的 Token…");
    try {
      const data = await request("/repo/clone", { method: "POST", body: { url: target } });
      statusMessage(statusId, data.message || "已拉取远程仓库", "success");
      toast(data.message || "已拉取远程仓库");
      window.setTimeout(() => window.location.reload(), 450);
    } catch (error) {
      statusMessage(statusId, error.message, "error");
    } finally { setButtonLoading(button, false, "拉取"); }
  }

  function renderRemoteRepoList(data) {
    const list = $("#repo-remote-list");
    if (!list) return;
    const projects = ((data && data.projects) || []).filter((project) => project && project.html_url && !project.demo);
    if (!projects.length) {
      const connected = ((data && data.connected) || []).length > 0;
      list.innerHTML = `<div class="empty-state compact"><h3>${connected ? "没有读取到可拉取的仓库" : "还没有连接平台账户"}</h3><p>${connected ? "可以在上方直接粘贴仓库地址，或到「平台连接」确认账户状态。" : "连接 GitHub / Gitee / GitLab 账户后，你的仓库会自动出现在这里。"}</p>${connected ? "" : `<button type="button" class="btn btn-sm" data-repo-remote-connect="1">${icon("globe")}<span>去连接平台</span></button>`}</div>`;
      return;
    }
    list.innerHTML = projects.slice(0, 12).map((project) => `<div class="picker-item"><div class="picker-meta"><div class="picker-name">${icon(project.private ? "lock" : "git-branch")}<span>${escapeHtml(project.full_name || project.name || "未命名")}</span><span class="pill">${escapeHtml(project.platform_label || project.platform || "")}</span></div><div class="picker-path" title="${escapeHtml(project.html_url)}">${escapeHtml(project.description || project.html_url)}</div></div><button type="button" class="btn btn-sm" data-repo-clone="${escapeHtml(project.html_url)}">${icon("download")}<span>拉取</span></button></div>`).join("");
  }

  async function loadRemoteRepos(force = false) {
    const list = $("#repo-remote-list");
    if (!list) return;
    if (!force && list.dataset.loaded) return;
    list.dataset.loaded = "1";
    const button = $("#repo-remote-refresh");
    setButtonLoading(button, true, "刷新");
    list.innerHTML = `<div class="picker-note">正在读取已连接平台的仓库列表…</div>`;
    try {
      const data = await request("/projects");
      renderRemoteRepoList(data);
    } catch (error) {
      delete list.dataset.loaded;
      list.innerHTML = `<div class="empty-state compact"><h3>仓库列表加载失败</h3><p>${escapeHtml(error.message)}</p></div>`;
    } finally { setButtonLoading(button, false, "刷新"); }
  }

  async function openModelSettings() {
    openOverlay("#model-settings");
    try {
      const status = await request("/model/status");
      const baseInput = $("#model-base-url");
      const nameInput = $("#model-name");
      const styleInput = $("#model-api-style");
      const keyInput = $("#model-api-key");
      if (baseInput && status.base_url) baseInput.value = status.base_url;
      if (nameInput && status.model) nameInput.value = status.model;
      if (styleInput && status.api_style) styleInput.value = status.api_style;
      if (keyInput) keyInput.placeholder = status.api_key_configured ? "已保存 API Key（留空则沿用）" : "粘贴你的 API Key";
      statusMessage("model-settings-status", status.configured ? `当前已配置：${status.model || "未命名模型"}` : "尚未配置模型，当前为离线模式", status.configured ? "success" : "");
    } catch (error) {
      statusMessage("model-settings-status", error.message, "error");
    }
  }

  async function saveModelSettings() {
    const button = $("#model-save");
    setButtonLoading(button, true, "保存并启用");
    statusMessage("model-settings-status", "正在保存模型配置…");
    try {
      const data = await request("/model/config", {
        method: "POST",
        body: {
          base_url: ($("#model-base-url")?.value || "").trim(),
          model: ($("#model-name")?.value || "").trim(),
          api_key: $("#model-api-key")?.value || "",
          api_style: $("#model-api-style")?.value || "auto",
          persist: true,
        },
      });
      if (data.status) updateModelStatus(data.status);
      const note = data.persisted === false && !data.message ? "（配置已生效，但写入本机配置文件失败，重启后需重新设置）" : "";
      statusMessage("model-settings-status", `${data.message || "模型配置已生效"}${note}`, "success");
      toast("模型配置已生效");
    } catch (error) {
      statusMessage("model-settings-status", error.message, "error");
    } finally { setButtonLoading(button, false, "保存并启用"); }
  }

  async function testModelSettings() {
    const button = $("#model-test");
    setButtonLoading(button, true, "测试连接");
    statusMessage("model-settings-status", "正在测试模型连接…");
    try {
      const data = await request("/model/test", { method: "POST", body: {} });
      if (data.ok) {
        statusMessage("model-settings-status", `连接成功：${data.model || "模型"} 响应正常`, "success");
      } else if (data.error === "not_configured") {
        statusMessage("model-settings-status", "请先保存接口地址与模型名称，再测试连接", "error");
      } else {
        statusMessage("model-settings-status", data.message || data.error || "连接失败，请检查配置", "error");
      }
    } catch (error) {
      statusMessage("model-settings-status", error.message, "error");
    } finally { setButtonLoading(button, false, "测试连接"); }
  }

  async function clearModelSettings() {
    const button = $("#model-clear");
    setButtonLoading(button, true, "清除配置");
    try {
      const data = await request("/model/config", {
        method: "POST",
        body: { base_url: "", model: "", api_key: "", api_style: "", persist: true },
      });
      if (data.status) updateModelStatus(data.status);
      ["#model-base-url", "#model-name", "#model-api-key"].forEach((sel) => { const node = $(sel); if (node) node.value = ""; });
      const keyInput = $("#model-api-key");
      if (keyInput) keyInput.placeholder = "粘贴你的 API Key";
      statusMessage("model-settings-status", data.message || "已清除模型配置，回到离线模式", "success");
      toast("已清除模型配置");
    } catch (error) {
      statusMessage("model-settings-status", error.message, "error");
    } finally { setButtonLoading(button, false, "清除配置"); }
  }

  function setupMotion() {
    const button = $("#motion-toggle");
    if (!button) return;
    let saved = false;
    try { saved = window.localStorage.getItem("osg-motion-paused") === "1"; } catch (_) { /* 存储不可用时仅本次生效 */ }
    const apply = (paused) => {
      document.body.classList.toggle("motion-paused", paused);
      button.setAttribute("aria-pressed", String(paused));
      const title = paused ? "继续装饰动画" : "暂停装饰动画";
      button.title = title;
      button.setAttribute("aria-label", title);
      button.innerHTML = icon(paused ? "play-circle" : "pause");
    };
    apply(saved);
    button.addEventListener("click", () => {
      const paused = !document.body.classList.contains("motion-paused");
      apply(paused);
      try { window.localStorage.setItem("osg-motion-paused", paused ? "1" : "0"); } catch (_) { /* 忽略存储错误 */ }
    });
  }

  function setupNavDrawer() {
    const toggle = $("#nav-toggle");
    const scrim = $("#nav-scrim");
    const close = () => document.body.classList.remove("nav-open");
    toggle?.addEventListener("click", () => document.body.classList.toggle("nav-open"));
    scrim?.addEventListener("click", close);
    $$(".sidebar .nav-item").forEach((link) => link.addEventListener("click", close));
  }

  /* ---------------------------------------------------------- 状态映射 */

  const formatStatus = (status) => ({
    verified: ["已验证", "success"],
    skipped: ["未执行代码", "warning"],
    candidate_failed: ["补丁后仍失败", "warning"],
    patch_rejected: ["补丁未通过校验", "warning"],
    infrastructure_error: ["环境错误", "warning"],
    no_patch: ["暂无补丁", "warning"],
    not_run: ["等待分析", ""],
    not_reproduced: ["未复现原问题", "warning"],
    needs_reproduction: ["需要具体复现测试", "warning"],
  }[status] || [status || "未知状态", "warning"]);

  const testStatus = (test) => {
    if (test.passed) return ["通过", "success"];
    if (test.command?.[0] === "skip") return ["未执行", ""];
    if (test.timed_out) return ["超时", "warning"];
    if (test.infrastructure_error) return ["环境错误", "warning"];
    return ["失败", "warning"];
  };

  const stageLabels = { baseline: "原始版本", candidate_patch: "补丁后复现测试", candidate_full: "补丁后全量测试" };

  function markdownReport(report) {
    const issue = report.issue || {};
    const lines = [
      "# OpenSourceGuard 修复报告", "",
      `- 仓库：\`${report.repo || ""}\``,
      `- 问题类型：${issue.issue_type || ""}`,
      `- 严重程度：${issue.severity || ""}`,
      `- 验证状态：${report.verification_status || ""}`, "",
      "## Issue 分析", "", issue.issue || "", "",
      `预期行为：${issue.expected_behavior || ""}`, "",
      `实际行为：${issue.actual_behavior || ""}`, "",
      "## 代码证据", "",
      ...(report.evidence || []).map((item) => `- \`${item.path}:${item.start_line}-${item.end_line}\`（${Number(item.score || 0).toFixed(2)}）：${item.reason}`),
      "", "## 复现测试", "", "```python", report.reproduction_test || "", "```", "",
      "## 候选补丁", "", "```diff", report.patch || "（未生成）", "```", "",
      "## 验证结果", "",
      ...(report.tests || []).flatMap((test) => [
        `- ${test.stage}：${testStatus(test)[0]}；运行 ${test.tests_run || 0} 项，失败 ${test.failures || 0}，错误 ${test.errors || 0}`,
        "```text", [test.stdout, test.stderr].filter(Boolean).join("\n"), "```",
      ]),
      "", "## 安全扫描", "",
      ...((report.security_findings || []).length ? report.security_findings.map((f) => `- ${f.path}:${f.line} ${f.rule_id}：${f.message}`) : ["未命中内置规则，不代表没有漏洞。"]),
      "", "## 分析说明", "", ...(report.warnings || []).map((item) => `- ${item}`),
      "## 下一步", "", ...(report.next_actions || []).map((item) => `- ${item}`), "",
    ];
    return lines.join("\n");
  }

  /* ---------------------------------------------------------- 诊断工作台 */

  function pullRequestBlock(report) {
    const verified = report.verification_status === "verified";
    return `<section class="pr-block" aria-labelledby="pr-block-title">
      <div class="pr-head">
        <span class="feature-icon violet">${icon("git-pull-request")}</span>
        <div><strong id="pr-block-title">把这套结果变成一个可审核的 PR</strong><p>PR 正文会自动带上定位证据、基线/补丁后测试结论和安全扫描结果，交给维护者决定是否合并。</p></div>
        <span class="pill ${verified ? "pill-success" : "pill-warn"}">${verified ? "补丁已验证" : "未验证，仅供参考"}</span>
      </div>
      <div class="pr-form">
        <label for="pr-platform">平台
          <select id="pr-platform" class="input">
            <option value="github">GitHub</option><option value="gitee">Gitee</option><option value="gitlab">GitLab</option>
          </select>
        </label>
        <label for="pr-repo">仓库（owner/name）
          <input id="pr-repo" class="input" type="text" placeholder="例如 yourname/my-project" maxlength="140" autocomplete="off">
        </label>
        <label for="pr-head">head 分支
          <input id="pr-head" class="input" type="text" value="opensourceguard/fix" maxlength="120" autocomplete="off">
        </label>
        <label for="pr-base">base 分支
          <input id="pr-base" class="input" type="text" value="main" maxlength="120" autocomplete="off">
        </label>
      </div>
      <p class="field-note">本工具不会替你 push 代码：head 分支需要已存在于远程，且内容就是通过验证的那份补丁。</p>
      <div class="pr-actions">
        <button type="button" class="btn btn-quiet btn-sm" id="pr-preview">${icon("file-text")}预览 PR 内容</button>
        <button type="button" class="btn btn-primary btn-sm" id="pr-create">${icon("upload")}创建 Draft PR</button>
        <span class="form-status" id="pr-status" role="status"></span>
      </div>
      <div class="pr-preview-box" id="pr-preview-box" hidden></div>
    </section>`;
  }

  function renderDiagnoseReport(report) {
    state.report = report;
    const target = $("#analysis-result");
    if (!target) return;
    const [statusLabel, statusKind] = formatStatus(report.verification_status);
    const issue = report.issue || {};
    const tests = report.tests || [];
    const evidence = report.evidence || [];
    const findings = [...(report.security_findings || []), ...(report.security_findings_after || []).map((item) => ({ ...item, after: true }))];
    const passed = tests.filter((test) => test.passed).length;
    const patchKey = registerCopy(report.patch || "");
    const reproductionKey = registerCopy(report.reproduction_test || "");
    const jsonKey = registerCopy(JSON.stringify(report, null, 2));

    const evidenceHtml = evidence.length
      ? `<ul class="evidence-list">${evidence.map((item) => `<li><span class="evidence-score">${(Number(item.score || 0) * 100).toFixed(0)}%</span><div><code>${escapeHtml(item.path)}:${item.start_line}-${item.end_line}</code><div class="reason">${escapeHtml(item.reason)}</div></div></li>`).join("")}</ul>`
      : `<div class="issue-box"><small>暂未找到高置信代码证据，请补充 Issue 上下文。</small></div>`;
    const testHtml = tests.length ? tests.map((test) => {
      const [label, kind] = testStatus(test);
      return `<div class="status-line"><span class="pill ${kind ? `pill-${kind}` : ""}">${escapeHtml(stageLabels[test.stage] || test.stage)} · ${label}</span><span class="status-text">${test.command?.[0] === "skip" ? "本次仅分析代码" : `运行 ${test.tests_run || 0} 项 · 失败 ${test.failures || 0} · 错误 ${test.errors || 0}`}</span></div>`;
    }).join("") : `<div class="issue-box"><small>当前模式没有运行测试。</small></div>`;
    const findingHtml = findings.length
      ? `<div class="finding-list">${findings.map((finding) => `<div class="finding-card ${finding.severity === "high" ? "high" : ""}"><b>${escapeHtml(finding.severity || "提示")} · ${escapeHtml(finding.rule_id || "规则")}${finding.after ? " · 补丁后" : ""}</b><span class="finding-path">${escapeHtml(finding.path)}:${finding.line} · ${escapeHtml(finding.message)}</span><span class="finding-rec">建议：${escapeHtml(finding.recommendation || "人工复核")}</span></div>`).join("")}</div>`
      : `<div class="issue-box"><small>未命中内置 Python 安全规则。</small></div>`;

    target.innerHTML = `
      <div class="card-head">
        <span class="overline">Analysis Result</span>
        <span class="pill ${statusKind ? `pill-${statusKind}` : ""}">${icon(statusKind === "success" ? "check-circle-2" : "info")}${escapeHtml(statusLabel)}</span>
      </div>
      <div class="tag-row">
        <span class="tag">${icon("map-pin")}定位证据 ${evidence.length} 条</span>
        <span class="tag">${icon("puzzle")}候选补丁${report.patch ? "已生成" : "暂无"}</span>
        <span class="tag">${icon("test-tube")}测试通过 ${passed}/${tests.length || 0}</span>
      </div>
      <div class="issue-box">
        <strong>Issue 分析 · ${escapeHtml(issue.issue_type || "issue")} · ${escapeHtml(issue.severity || "待评估")}</strong>
        ${escapeHtml(issue.issue || "未提供问题描述")}
        <small>预期：${escapeHtml(issue.expected_behavior || "待确认")} · 实际：${escapeHtml(issue.actual_behavior || "待确认")} · 模型：${escapeHtml(report.model_used || "heuristic")}</small>
      </div>
      <section class="report-section"><h3>代码证据 <span class="count">${evidence.length} 条</span></h3>${evidenceHtml}</section>
      <section class="report-section"><h3>复现测试 <button type="button" class="copy-button" data-copy="${reproductionKey}">${icon("copy")}复制</button></h3><pre class="code-block">${escapeHtml(report.reproduction_test || "暂无复现测试")}</pre></section>
      <section class="report-section"><h3>候选补丁 <button type="button" class="copy-button" data-copy="${patchKey}">${icon("copy")}复制</button></h3><pre class="code-block">${escapeHtml(report.patch || "暂无可审核补丁")}</pre></section>
      <section class="report-section"><h3>验证结果 <span class="count">${tests.length} 次</span></h3><div class="status-row">${testHtml}</div></section>
      <section class="report-section"><h3>安全扫描 <span class="count">${findings.length ? `${findings.length} 条提示` : "未命中内置规则"}</span></h3>${findingHtml}</section>
      <details class="report-section"><summary>分析说明与补丁计划</summary><p class="field-note">${escapeHtml(report.patch_plan || "")}</p><ul class="next-list">${(report.warnings || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></details>
      <section class="report-section"><h3>下一步</h3><ul class="next-list">${(report.next_actions || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></section>
      <div class="result-actions">
        <button type="button" class="btn btn-quiet btn-sm" data-download="report-json">${icon("download")}下载 JSON</button>
        <button type="button" class="btn btn-quiet btn-sm" data-download="report-md">${icon("download")}下载 Markdown</button>
        <button type="button" class="btn btn-quiet btn-sm" data-copy="${jsonKey}">${icon("copy")}复制 JSON</button>
      </div>
      ${pullRequestBlock(report)}`;
    target.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  async function submitRepair() {
    const button = $("#run-analysis");
    const issue = $("#issue-input")?.value.trim();
    if (!issue) { statusMessage("status", "请先描述你遇到的问题", "error"); return; }
    const mode = document.querySelector('input[name="validation-mode"]:checked')?.value || "local";
    setButtonLoading(button, true, "开始分析");
    statusMessage("status", "正在定位代码证据并准备报告…");
    try {
      const report = await request("/analyze", { method: "POST", body: { issue, execute: mode, framework: "unittest" } });
      renderDiagnoseReport(report);
      statusMessage("status", "分析完成，结果待你审核", "success");
      toast("分析报告已生成");
    } catch (error) {
      statusMessage("status", error.message, "error");
      toast("分析未完成，请检查本地服务");
    } finally { setButtonLoading(button, false, "开始分析"); }
  }

  const executeNotes = {
    skip: "只查看代码证据与候选补丁，不运行仓库内的代码。",
    local: "会在临时副本中运行测试，仅适用于你信任的项目。",
    docker: "尝试使用 Docker 隔离运行测试，需本机已安装 Docker。",
  };

  function setupDiagnosePage() {
    $$("[data-issue-preset]").forEach((chip) => {
      chip.addEventListener("click", () => {
        const input = $("#issue-input");
        if (input) { input.value = chip.dataset.issuePreset; input.focus(); }
      });
    });
    $$('input[name="validation-mode"]').forEach((input) => {
      input.addEventListener("change", () => {
        const note = $("#execute-note");
        if (note) note.textContent = executeNotes[input.value] || "";
      });
    });
    $("#run-analysis")?.addEventListener("click", submitRepair);
    checkHealth();
    loadDemoStatus();
  }

  /* ---------------------------------------------------------- Draft PR */

  async function previewDraftPr() {
    const box = $("#pr-preview-box");
    if (!box) return;
    box.hidden = false;
    box.innerHTML = `<div class="pr-busy">正在生成 PR 请求体…</div>`;
    const issue = $("#issue-input")?.value?.trim();
    if (!issue) { box.innerHTML = `<div class="pr-busy">Issue 描述为空，无法生成。</div>`; return; }
    try {
      const data = await request("/draft-pr", { method: "POST", body: {
        issue, head: $("#pr-head").value.trim(), base: $("#pr-base").value.trim(),
      } });
      state.draftPr = data;
      box.innerHTML = `<div class="pr-preview-head"><strong>${escapeHtml(data.title || "")}</strong><span class="pill">draft: true</span></div>
        <div class="pr-preview-meta">${data.dry_run ? "尚未创建。确认后才会向平台发起真实请求。" : "已创建。"} head=${escapeHtml(data.head || "")} · base=${escapeHtml(data.base || "")}</div>
        <pre>${escapeHtml((data.body || "").slice(0, 1400))}</pre>`;
    } catch (error) {
      box.innerHTML = `<div class="pr-busy">${escapeHtml(error.message)}</div>`;
    }
  }

  async function createDraftPr() {
    const issue = $("#issue-input")?.value?.trim();
    if (!issue) { statusMessage("pr-status", "Issue 描述为空", "error"); return; }
    const repo = $("#pr-repo").value.trim();
    if (!repo) { statusMessage("pr-status", "请先填写仓库（owner/name）", "error"); return; }
    const button = $("#pr-create");
    setButtonLoading(button, true, "创建中");
    statusMessage("pr-status", "正在向平台发起请求…");
    try {
      const data = await request("/draft-pr", { method: "POST", body: {
        issue, platform: $("#pr-platform").value, repo, confirm: true,
        head: $("#pr-head").value.trim(), base: $("#pr-base").value.trim(),
      } });
      if (data.ok && data.url) {
        statusMessage("pr-status", "草稿 PR 已创建", "success");
        toast("Draft PR 已创建");
        const box = $("#pr-preview-box");
        if (box) {
          box.hidden = false;
          box.innerHTML = `<div class="pr-preview-head"><strong>${escapeHtml(data.title || "")}</strong><span class="pill pill-primary">#${escapeHtml(String(data.number ?? ""))}</span></div>
            <div class="pr-preview-meta">${escapeHtml(data.url)}</div>`;
        }
      } else {
        statusMessage("pr-status", data.message || "创建失败", "error");
      }
    } catch (error) {
      statusMessage("pr-status", error.message, "error");
    } finally { setButtonLoading(button, false, "创建 Draft PR"); }
  }

  /* ---------------------------------------------------------- 体检报告 */

  const dimensionIcon = { security: "shield", compliance: "scale", testing: "flask-conical", documentation: "book-open", maintainability: "code" };
  const dimensionTone = { security: "violet", compliance: "peach", testing: "mint", documentation: "violet", maintainability: "mint" };

  const scoreTone = (score) => (score >= 85 ? "success" : score >= 70 ? "" : score >= 55 ? "warn" : "error");

  function animateNumber(node, target, duration = 900) {
    if (!node) return;
    if (document.body.classList.contains("motion-paused")) { node.textContent = String(target); return; }
    const start = performance.now();
    const tick = (now) => {
      const p = Math.min((now - start) / duration, 1);
      node.textContent = String(Math.round(target * (1 - Math.pow(1 - p, 3))));
      if (p < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }

  function renderDimension(dimension) {
    const tone = dimensionTone[dimension.key] || "violet";
    const measured = dimension.measured !== false;
    const score = Number(dimension.score || 0);
    const signals = (dimension.signals || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
    const deductions = (dimension.deductions || []).map((item) => `<li><b>-${Number(item.points)}</b> ${escapeHtml(item.reason)}</li>`).join("");
    const actions = (dimension.actions || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
    const hint = (dimension.signals || [])[0] || (dimension.actions || [])[0] || "";
    return `<article class="dim-card" data-dim-key="${escapeHtml(dimension.key)}">
      <div class="dim-card-top">
        <span class="feature-icon ${tone}">${icon(dimensionIcon[dimension.key] || "info")}</span>
        <span class="dim-score">${measured ? `${score}<small>/100</small>` : "<small>未测量</small>"}</span>
      </div>
      <h3>${escapeHtml(dimension.label)}</h3>
      <div class="dim-bar"><i class="${measured ? scoreTone(score) : ""}" style="width:${measured ? Math.max(0, Math.min(100, score)) : 0}%"></i></div>
      ${hint ? `<p class="dim-hint">${escapeHtml(hint)}</p>` : ""}
      <button type="button" class="dim-toggle" data-dim-toggle aria-expanded="false">查看依据</button>
      <div class="dim-detail">
        ${signals ? `<div><h4>观测依据</h4><ul>${signals}</ul></div>` : ""}
        ${deductions ? `<div><h4>扣分明细</h4><ul>${deductions}</ul></div>` : ""}
        ${actions ? `<div><h4>下一步</h4><ul>${actions}</ul></div>` : ""}
      </div>
    </article>`;
  }

  function renderHealth(data) {
    state.health = data;
    const target = $("#health-result");
    if (!target) return;
    const stats = data.stats || {};
    const security = stats.security || {};
    const languages = Object.entries(stats.languages || {})
      .map(([name, count]) => `<span class="pill">${escapeHtml(name)} · ${Number(count)}</span>`).join("");
    const dimensions = (data.dimensions || []).map(renderDimension).join("");
    const blocking = (data.blocking_issues || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
    const wins = (data.quick_wins || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
    const notes = (data.warnings || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
    const score = Number(data.score || 0);
    const circumference = 326.726;

    target.innerHTML = `<div class="result-content">
      <section class="health-hero">
        <div class="score-ring">
          <svg viewBox="0 0 120 120" aria-hidden="true">
            <circle class="ring-bg" cx="60" cy="60" r="52" fill="none" stroke-width="10"></circle>
            <circle class="ring-fg" cx="60" cy="60" r="52" fill="none" stroke-width="10" stroke-linecap="round" stroke-dasharray="${circumference}" stroke-dashoffset="${(circumference * (1 - score / 100)).toFixed(2)}"></circle>
          </svg>
          <div class="score-ring-center"><b id="score-number">0</b><span>综合评分</span></div>
        </div>
        <div class="health-hero-copy">
          <span class="overline">PROJECT HEALTH</span>
          <p class="grade-line">${escapeHtml(data.grade || "")} · ${escapeHtml(data.grade_label || "")}</p>
          <h2 style="margin:6px 0 0;font-size:18px;font-weight:600">${escapeHtml(data.grade_note || "")}</h2>
          <div class="health-facts">
            <span>源码文件 <b>${Number(stats.source_files || 0)}</b></span>
            <span>依赖 <b>${Number(stats.dependencies || 0)}</b></span>
            <span>许可证 <b>${escapeHtml(stats.license || "未声明")}</b></span>
            <span>高危 <b>${Number(security.high || 0)}</b> · 中危 <b>${Number(security.medium || 0)}</b></span>
          </div>
          ${languages ? `<div class="chip-row" style="margin-top:10px">${languages}</div>` : ""}
          <div class="health-hero-actions">
            <button type="button" class="btn btn-quiet btn-sm" data-copy="health-json">${icon("copy")}复制 JSON</button>
            <button type="button" class="btn btn-quiet btn-sm" data-download="health-json">${icon("download")}下载报告</button>
          </div>
        </div>
      </section>
      ${blocking ? `<section class="report-section"><h3>${icon("info")} 阻塞性问题（建议公开发布前处理）</h3><ul class="next-list">${blocking}</ul></section>` : ""}
      ${wins ? `<section class="report-section"><h3>${icon("sparkles")} 优先改进项</h3><ul class="next-list">${wins}</ul></section>` : ""}
      <section class="report-section"><h3>维度评分 <span class="count">${(data.dimensions || []).length} 个维度</span></h3><div class="dim-grid">${dimensions}</div></section>
      ${notes ? `<section class="report-section"><h3>评分边界</h3><ul class="next-list">${notes}</ul></section>` : ""}
    </div>`;
    copyStore.set("health-json", JSON.stringify(data, null, 2));
    animateNumber($("#score-number"), score);
  }

  function renderCompliance(data) {
    state.compliance = data;
    const target = $("#health-result");
    if (!target) return;
    const summary = data.summary || {};
    const severity = summary.severity || {};
    const order = { high: 0, medium: 1, low: 2, info: 3 };
    const label = { high: "高", medium: "中", low: "低", info: "提示" };
    const findings = [...(data.findings || [])]
      .sort((a, b) => (order[a.severity] ?? 9) - (order[b.severity] ?? 9))
      .map((item) => `<div class="audit-row">
        <div><span class="severity ${escapeHtml(item.severity || "info")}">${escapeHtml(label[item.severity] || item.severity)}</span></div>
        <div class="audit-desc"><p>${escapeHtml(item.subject)}</p><small>${escapeHtml(item.message)}</small></div>
        <div class="audit-rec">建议：${escapeHtml(item.recommendation || "人工复核")}</div>
      </div>`).join("");
    const deps = (data.dependencies || []).slice(0, 60)
      .map((item) => `<tr><td>${escapeHtml(item.name)}</td><td>${escapeHtml(item.version)}</td><td>${escapeHtml(item.ecosystem)}</td><td>${escapeHtml(item.scope)}</td><td>${escapeHtml(item.license)}</td></tr>`).join("");
    const notes = (data.warnings || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
    copyStore.set("compliance-json", JSON.stringify(data, null, 2));

    target.innerHTML = `<div class="result-content">
      <section class="health-hero">
        <div class="health-hero-copy">
          <span class="overline">LICENSE &amp; DEPENDENCY AUDIT</span>
          <p class="grade-line">项目许可证：${escapeHtml(data.project_license || "未声明")}</p>
          <div class="health-facts">
            <span>依赖 <b>${Number(summary.dependency_count || 0)}</b></span>
            <span>已解析 <b>${Number(summary.resolved_licenses || 0)}</b></span>
            <span>未知 <b>${Number(summary.unknown_licenses || 0)}</b></span>
            <span>高 <b>${Number(severity.high || 0)}</b> · 中 <b>${Number(severity.medium || 0)}</b> · 低 <b>${Number(severity.low || 0)}</b></span>
          </div>
          <div class="health-hero-actions">
            <button type="button" class="btn btn-quiet btn-sm" data-copy="compliance-json">${icon("copy")}复制 JSON</button>
            <button type="button" class="btn btn-quiet btn-sm" data-download="compliance-json">${icon("download")}下载报告</button>
          </div>
        </div>
      </section>
      <section class="report-section">
        <h3>合规发现 <span class="count">${(data.findings || []).length} 条</span></h3>
        ${findings ? `<div class="audit-table"><div class="audit-row head"><div>级别</div><div>问题描述</div><div>修复建议</div></div>${findings}</div>` : `<div class="issue-box"><small>未发现明显合规问题。</small></div>`}
      </section>
      ${deps ? `<section class="report-section"><h3>依赖清单 <span class="count">最多显示 60 条</span></h3><div class="table-scroll"><table class="data-table"><thead><tr><th>名称</th><th>版本</th><th>生态</th><th>范围</th><th>许可证</th></tr></thead><tbody>${deps}</tbody></table></div></section>` : ""}
      ${notes ? `<section class="report-section"><h3>边界说明</h3><ul class="next-list">${notes}</ul></section>` : ""}
    </div>`;
  }

  async function runHealth() {
    const button = $("#health-run");
    setButtonLoading(button, true, "生成健康度报告");
    statusMessage("health-status", "正在索引代码、扫描安全规则并审计依赖…");
    try {
      const data = await request("/health/report");
      renderHealth(data);
      statusMessage("health-status", `评分完成：${data.score}/100（${data.grade}）`, "success");
      loadContributorGuide();
    } catch (error) {
      statusMessage("health-status", error.message, "error");
    } finally { setButtonLoading(button, false, "生成健康度报告"); }
  }

  async function runCompliance() {
    const button = $("#compliance-run");
    setButtonLoading(button, true, "只看合规审计");
    statusMessage("health-status", "正在解析依赖清单与许可证…");
    try {
      const data = await request("/compliance");
      renderCompliance(data);
      const high = (data.summary && data.summary.severity && data.summary.severity.high) || 0;
      statusMessage("health-status", high ? `发现 ${high} 个高风险合规问题` : "合规审计完成", high ? "error" : "success");
    } catch (error) {
      statusMessage("health-status", error.message, "error");
    } finally { setButtonLoading(button, false, "只看合规审计"); }
  }

  async function loadContributorGuide() {
    if (state.contributorGuide) return;
    try {
      const data = await request("/onboarding", { method: "POST", body: {} });
      if (data && data.contributor_guide) {
        state.contributorGuide = data.contributor_guide;
        renderContributorGuide(data.contributor_guide);
      }
    } catch (_) { /* 贡献者指南是补充内容，失败不阻塞评分。 */ }
  }

  function renderContributorGuide(guide) {
    const panel = $("#contributor-panel");
    const target = $("#contributor-result");
    if (!panel || !target || !guide) return;
    const steps = (guide.first_pr_workflow || []).map((step) => {
      const commands = (step.commands || []).map((line) => `<code>${escapeHtml(line)}</code>`).join("");
      return `<article class="pr-step"><h4>${escapeHtml(step.title)}</h4><p>${escapeHtml(step.why)}</p>${commands ? `<div class="pr-commands">${commands}</div>` : ""}${step.note ? `<small>${escapeHtml(step.note)}</small>` : ""}</article>`;
    }).join("");
    const checklist = (guide.pre_submit_checklist || []).map((item) => `<li class="${item.blocking ? "blocking" : ""}"><strong>${escapeHtml(item.title)}</strong><span>${escapeHtml(item.detail)}</span></li>`).join("");
    const links = (guide.issue_search_links || []).map((item) => `<li><a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(item.label)} ${icon("arrow-up-right")}</a><small>${escapeHtml(item.note)}</small></li>`).join("");
    const advice = (guide.choose_issue_guide || []).map((item) => `<li><strong>${escapeHtml(item.title)}</strong><span>${escapeHtml(item.detail)}</span></li>`).join("");
    const ladder = (guide.ladder || []).map((item) => `<div class="ladder-step"><b>${escapeHtml(item.stage)}</b><span><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.detail)}</small></span></div>`).join("");
    copyStore.set("pr-template", String(guide.pr_template || ""));
    copyStore.set("readme-badges", String((guide.badges && guide.badges.combined) || ""));

    target.innerHTML = `<div class="contributor-body">
      <section class="report-section"><h3>${icon("git-branch")} Fork → PR 完整流程</h3><div class="pr-steps">${steps}</div></section>
      <section class="report-section"><h3>${icon("check")} 提交前自查（${Number(guide.blocking_count || 0)} 项必须通过）</h3><ul class="check-list">${checklist}</ul></section>
      <section class="report-section"><h3>${icon("file-text")} PR 描述模板</h3><button type="button" class="btn btn-quiet btn-sm" data-copy="pr-template">${icon("copy")}复制模板</button><pre class="code-block">${escapeHtml(guide.pr_template || "")}</pre></section>
      <section class="report-section"><h3>${icon("search")} 去哪里找第一个 Issue</h3><ul class="link-list">${links}</ul><ul class="advice-list">${advice}</ul></section>
      <section class="report-section"><h3>${icon("trophy")} 贡献者成长路径</h3><div class="ladder">${ladder}</div></section>
      <section class="report-section"><h3>${icon("globe")} README 徽章</h3><button type="button" class="btn btn-quiet btn-sm" data-copy="readme-badges">${icon("copy")}复制徽章</button><pre class="code-block">${escapeHtml((guide.badges && guide.badges.combined) || "")}</pre><small>${escapeHtml((guide.badges && guide.badges.note) || "")}</small></section>
      <p class="field-note">${escapeHtml(guide.note || "")}</p>
    </div>`;
    panel.hidden = false;
  }

  function setupReportPage() {
    $("#health-run")?.addEventListener("click", runHealth);
    $("#compliance-run")?.addEventListener("click", runCompliance);
    checkHealth();
  }

  /* ---------------------------------------------------------- 项目与平台 */

  function renderProviderStatus(providers = []) {
    const node = $("#provider-status");
    if (!node) return;
    node.innerHTML = providers.map((provider) => `<span class="provider-chip ${provider.configured ? "connected" : ""}"><i></i>${escapeHtml(provider.label)} · ${provider.configured ? "已连接" : "演示"}</span>`).join("");
  }

  function renderProjects(data) {
    const node = $("#project-list");
    if (!node) return;
    state.projects.rows = data.projects || [];
    state.projects.loaded = true;
    renderProviderStatus(data.providers || []);
    const typesafe = $("#typesafe-status");
    if (typesafe && data.mode) typesafe.textContent = data.mode === "typesafe" ? "TypeSafe 智能评分" : "本地规则排序";
    if (!state.projects.rows.length) {
      node.innerHTML = `<div class="empty-state compact"><div class="empty-visual">${icon("folder")}</div><h3>暂无项目</h3><p>${escapeHtml((data.errors || []).join("；") || "请配置平台 Token 后刷新。")}</p></div>`;
      return;
    }
    const selectedId = state.projects.selected?.id;
    node.innerHTML = state.projects.rows.map((project) => {
      const score = Number.isFinite(Number(project.relevance_score)) ? Math.round(Number(project.relevance_score)) : null;
      const reasons = Array.isArray(project.relevance_reasons) ? project.relevance_reasons.join("；") : "";
      return `<button type="button" class="project-card ${selectedId === project.id ? "active" : ""}" data-project-id="${escapeHtml(project.id)}">
        <span class="feature-icon ${project.platform === "local" ? "peach" : "violet"}">${icon(project.platform === "local" ? "folder" : "globe")}</span>
        <span class="project-card-body">
          <strong>${escapeHtml(project.name || project.full_name)}</strong>
          <small>${escapeHtml(project.platform_label || project.platform)} · ${project.open_issues || 0} 个开放 Issue</small>
          <em>${escapeHtml(project.description || "暂无项目简介")}</em>
          ${score !== null ? `<span class="pill ${score < 40 ? "pill-warn" : "pill-primary"}">${score}% 匹配${reasons ? ` · ${escapeHtml(reasons)}` : ""}</span>` : ""}
        </span>
        <span class="project-card-arrow">${icon("arrow-right")}</span>
      </button>`;
    }).join("");
    if (!state.projects.selected && state.projects.rows[0]) selectProject(state.projects.rows[0]);
  }

  function renderIssues(data) {
    const node = $("#issue-list");
    if (!node) return;
    state.projects.issues = data.issues || [];
    if (!state.projects.issues.length) {
      node.innerHTML = `<div class="empty-state compact"><div class="empty-visual">${icon("issue")}</div><h3>没有找到 Issue</h3><p>${escapeHtml((data.errors || []).join("；") || "这个项目目前没有开放 Issue。")}</p></div>`;
      return;
    }
    node.innerHTML = `${state.projects.issues.map((issue) => `<article class="issue-card">
      <div class="issue-card-top">
        <span class="issue-number">#${escapeHtml(issue.number || issue.id)}</span>
        <span class="pill ${issue.state === "open" ? "pill-success" : ""}">${escapeHtml(issue.state === "open" ? "开放" : issue.state)}</span>
        ${(issue.labels || []).slice(0, 2).map((label) => `<span class="issue-label">${escapeHtml(label)}</span>`).join("")}
      </div>
      <h4>${escapeHtml(issue.title)}</h4>
      <p>${escapeHtml(issue.body || "暂无描述")}</p>
      <div class="issue-card-bottom">
        <small>${escapeHtml(issue.author)} · ${issue.comments || 0} 条评论</small>
        <button type="button" class="btn btn-primary btn-sm" data-assist-issue="${escapeHtml(issue.id)}">让 Agent 介入</button>
      </div>
    </article>`).join("")}`;
  }

  function renderAgentPlan(data) {
    const node = $("#project-agent-result");
    if (!node) return;
    state.projects.agent = data;
    node.hidden = false;
    const patchKey = registerCopy(data.patch || "");
    const issue = data.issue || {};
    const local = issue.platform === "local";
    node.innerHTML = `<div class="agent-plan">
      <div class="agent-plan-head">
        <span class="feature-icon mint">${icon("sparkles")}</span>
        <div><span class="overline">AGENT INTERVENTION</span><strong>${escapeHtml(issue.title || "Issue 修复方案")}</strong></div>
        <span class="pill">${escapeHtml(data.model_used || "heuristic")}</span>
      </div>
      <p class="field-note">Agent 已完成第一轮分析。它不会未经确认修改远程仓库。</p>
      <div class="agent-plan-box"><span class="box-title"><strong>建议步骤</strong></span><p style="margin:0">${escapeHtml(data.patch_plan || "暂无方案")}</p></div>
      ${data.reproduction_test ? `<details class="agent-plan-box"><summary>查看复现测试建议</summary><pre class="code-block">${escapeHtml(data.reproduction_test)}</pre></details>` : ""}
      ${data.patch ? `<div class="agent-plan-box"><span class="box-title"><strong>候选补丁</strong><button type="button" class="copy-button" data-copy="${patchKey}">${icon("copy")}复制</button></span><pre class="code-block">${escapeHtml(data.patch)}</pre></div>` : ""}
      <div class="agent-plan-actions">
        ${local && data.patch ? `<button type="button" class="btn btn-primary btn-sm" data-apply-local="true">确认并修改本地副本</button>` : ""}
        ${!local && issue.repo && issue.number ? `<button type="button" class="btn btn-primary btn-sm" data-comment-issue="true">确认后写入 Issue 评论</button>` : ""}
        <button type="button" class="btn btn-quiet btn-sm" data-copy="${patchKey}">${icon("copy")}复制方案</button>
      </div>
    </div>`;
    node.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  async function loadProjects() {
    const node = $("#project-list");
    if (node) node.innerHTML = `<div class="empty-state compact"><div class="empty-visual">${icon("folder")}</div><h3>正在读取项目</h3><p>正在检查已连接的平台。</p></div>`;
    try {
      const selected = $("#project-platform")?.value || "";
      const query = selected ? `?platform=${encodeURIComponent(selected)}` : "";
      renderProjects(await request(`/projects${query}`));
    } catch (error) {
      if (node) node.innerHTML = `<div class="empty-state compact"><div class="empty-visual">${icon("info")}</div><h3>项目读取失败</h3><p>${escapeHtml(error.message)}</p></div>`;
    }
  }

  function renderConnections(data = {}) {
    const node = $("#connections-list");
    if (!node) return;
    const rows = Array.isArray(data.connections) ? data.connections : [];
    if (!rows.length) {
      node.innerHTML = `<div class="empty-state compact"><div class="empty-visual">${icon("globe")}</div><h3>暂无连接信息</h3><p>请检查本地服务状态。</p></div>`;
      return;
    }
    node.innerHTML = `<div class="connection-list">${rows.map((item) => {
      const connected = Boolean(item.connected);
      const account = item.account ? ` · ${escapeHtml(item.account)}` : "";
      const action = connected
        ? `<button type="button" class="btn btn-quiet btn-sm" data-platform-disconnect="${escapeHtml(item.platform)}">断开</button>`
        : `<button type="button" class="btn btn-primary btn-sm" data-platform-token="${escapeHtml(item.platform)}">粘贴 Token 连接</button>${item.oauth_ready ? ` <button type="button" class="btn btn-quiet btn-sm" data-platform-connect="${escapeHtml(item.platform)}">OAuth 授权</button>` : ""}`;
      return `<article class="connection-card">
        <span class="feature-icon ${connected ? "mint" : "peach"}">${icon("globe")}</span>
        <div class="connection-card-main"><strong>${escapeHtml(item.label || item.platform)}</strong><small>${connected ? `已连接${account}` : "粘贴 Token 即可连接"}</small></div>
        <span class="provider-chip ${connected ? "connected" : ""}"><i></i>${connected ? "已连接" : "未连接"}</span>
        ${action}
      </article>`;
    }).join("")}</div>`;
  }

  function openPlatformSettings(focusPlatform = "") {
    openOverlay("#platform-settings");
    refreshPlatformConnections().then(() => {
      if (focusPlatform) $(`#platform-token-${focusPlatform}`)?.focus();
    });
  }

  async function refreshPlatformConnections() {
    try {
      const data = await request("/connections");
      renderPlatformRows(data);
      return data;
    } catch (error) {
      statusMessage("platform-settings-status", error.message, "error");
      return null;
    }
  }

  function renderPlatformRows(data = {}) {
    const node = $("#platform-connections-list");
    if (!node) return;
    const rows = Array.isArray(data.connections) ? data.connections : [];
    const guide = data.token_guide || {};
    if (!rows.length) {
      node.innerHTML = `<div class="empty-state compact"><div class="empty-visual">${icon("globe")}</div><h3>暂无连接信息</h3><p>请检查本地服务状态。</p></div>`;
      return;
    }
    node.innerHTML = rows.map((item) => {
      const platform = escapeHtml(item.platform || "");
      const label = escapeHtml(item.label || item.platform || "");
      const tips = guide[item.platform] || {};
      if (item.connected) {
        const where = item.storage === "system_keyring" ? "系统钥匙串" : (item.storage === "local_file" ? "本机配置文件" : "本机");
        return `<div class="platform-row">
        <div class="platform-row-head">
          <strong>${label}</strong>
          <span class="provider-chip connected"><i></i>已连接${item.account ? ` · ${escapeHtml(item.account)}` : ""}</span>
        </div>
        <ol class="platform-guide"><li>凭据已安全保存在${where}，断开前可随时使用。</li></ol>
        <div class="picker-input-row">
          <button type="button" class="btn btn-quiet btn-sm" data-platform-off="${platform}">${icon("x")}<span>断开连接</span></button>
        </div>
      </div>`;
      }
      const steps = [];
      if (tips.url) steps.push(`<a href="${escapeHtml(tips.url)}" target="_blank" rel="noreferrer noopener">点这里打开官方页面创建 Token${icon("external-link")}</a>`);
      if (tips.scope) steps.push(escapeHtml(tips.scope));
      steps.push("把生成的 Token 粘贴到下面，点「验证并连接」");
      return `<div class="platform-row">
        <div class="platform-row-head">
          <strong>${label}</strong>
          <span class="provider-chip"><i></i>未连接</span>
        </div>
        <ol class="platform-guide">${steps.map((step) => `<li>${step}</li>`).join("")}</ol>
        <div class="picker-input-row">
          <input class="input" id="platform-token-${platform}" type="password" placeholder="粘贴 Token${tips.prefix ? `（${escapeHtml(tips.prefix)}）` : ""}" autocomplete="off" spellcheck="false">
          <button type="button" class="btn btn-primary btn-sm" data-platform-save="${platform}">${icon("check")}<span>验证并连接</span></button>
          ${item.oauth_ready ? `<button type="button" class="btn btn-quiet btn-sm" data-platform-connect="${platform}">${icon("external-link")}<span>OAuth 授权</span></button>` : ""}
        </div>
      </div>`;
    }).join("");
  }

  async function connectPlatformToken(platform, button) {
    const input = $(`#platform-token-${platform}`);
    const token = String(input?.value || "").trim();
    if (!token) {
      statusMessage("platform-settings-status", "先粘贴 Token，再点「验证并连接」", "error");
      input?.focus();
      return;
    }
    setButtonLoading(button, true);
    statusMessage("platform-settings-status", "正在向平台验证这个 Token…");
    try {
      const result = await request("/connections/save", { method: "POST", body: { platform, token } });
      if (!result.ok) {
        statusMessage("platform-settings-status", result.message || "连接失败，请检查 Token", "error");
        return;
      }
      statusMessage("platform-settings-status", result.message || "连接成功", "success");
      toast(result.message || "连接成功");
      if (input) input.value = "";
      state.projects.loaded = false;
      await refreshPlatformConnections();
      if ($("#connections-list")) await loadConnections();
    } catch (error) {
      statusMessage("platform-settings-status", error.message, "error");
    } finally {
      setButtonLoading(button, false, "验证并连接");
    }
  }

  async function disconnectPlatformToken(platform, button) {
    if (!window.confirm("确认断开这个平台的本地连接吗？")) return;
    setButtonLoading(button, true);
    try {
      const result = await request("/connections/disconnect", { method: "POST", body: { platform } });
      statusMessage("platform-settings-status", result.message || "连接已断开", "success");
      state.projects.loaded = false;
      await refreshPlatformConnections();
      if ($("#connections-list")) await loadConnections();
    } catch (error) {
      statusMessage("platform-settings-status", error.message, "error");
    } finally {
      setButtonLoading(button, false, "断开连接");
    }
  }

  async function loadConnections() {
    try {
      renderConnections(await request("/connections"));
    } catch (error) {
      statusMessage("connections-status", error.message, "error");
    }
  }

  async function connectPlatform(platform) {
    statusMessage("connections-status", "正在准备官方授权页面…");
    try {
      const result = await request("/oauth/start", { method: "POST", body: { platform } });
      if (!result.ok || !result.authorization_url) {
        statusMessage("connections-status", result.message || "OAuth 尚未配置", "error");
        return;
      }
      const popup = window.open(result.authorization_url, "opensourceguard-oauth", "popup,width=640,height=760");
      if (!popup) {
        statusMessage("connections-status", "浏览器拦截了授权窗口，请允许弹窗后重试。", "error");
        return;
      }
      statusMessage("connections-status", "请在新窗口完成授权，完成后这里会自动刷新。", "success");
      const started = Date.now();
      const timer = window.setInterval(async () => {
        if (popup.closed || Date.now() - started > 180000) {
          window.clearInterval(timer);
          await loadConnections();
        }
      }, 1500);
    } catch (error) {
      statusMessage("connections-status", error.message, "error");
    }
  }

  async function disconnectPlatform(platform) {
    if (!window.confirm("确认断开这个平台的本地连接吗？")) return;
    try {
      const result = await request("/connections/disconnect", { method: "POST", body: { platform } });
      statusMessage("connections-status", result.message || "连接已断开", "success");
      state.projects.loaded = false;
      await loadConnections();
      await loadProjects();
    } catch (error) {
      statusMessage("connections-status", error.message, "error");
    }
  }

  async function loadTypeSafeStatus() {
    try {
      const data = await request("/typesafe/status");
      const node = $("#typesafe-status");
      if (node) node.textContent = data.ready ? "TypeSafe 已连接" : "本地规则";
    } catch (_) { /* 服务离线时保留本地规则排序。 */ }
  }

  async function recommendProjects() {
    if (!state.projects.rows.length) {
      statusMessage("project-recommend-status", "请先刷新项目。", "error");
      return;
    }
    const button = $("#project-recommend");
    setButtonLoading(button, true, "为我排序");
    statusMessage("project-recommend-status", "正在根据兴趣整理项目…");
    try {
      const result = await request("/projects/recommend", {
        method: "POST",
        body: {
          projects: state.projects.rows,
          interests: $("#project-interests")?.value.trim() || "",
          avoid: $("#project-avoid")?.value.trim() || "",
        },
      });
      state.projects.selected = null;
      renderProjects(result);
      const label = result.mode === "typesafe" ? "TypeSafe 已完成结构化评分" : "已使用本地规则完成排序";
      statusMessage("project-recommend-status", `${label}，匹配度低的项目已排到后面。`, "success");
      toast("项目排序已更新");
    } catch (error) {
      statusMessage("project-recommend-status", error.message, "error");
    } finally { setButtonLoading(button, false, "为我排序"); }
  }

  async function selectProject(project) {
    state.projects.selected = project;
    const title = $("#selected-project-title");
    const badge = $("#selected-project-badge");
    if (title) title.textContent = project.name || project.full_name;
    if (badge) {
      badge.textContent = `${project.platform_label || project.platform} · ${project.open_issues || 0} 个 Issue`;
      badge.className = "pill";
    }
    const issueNode = $("#issue-list");
    if (issueNode) issueNode.innerHTML = `<div class="empty-state compact"><div class="empty-visual">${icon("issue")}</div><h3>正在读取 Issue</h3><p>正在连接 ${escapeHtml(project.platform_label || project.platform)}。</p></div>`;
    $$(".project-card").forEach((card) => card.classList.toggle("active", card.dataset.projectId === project.id));
    const agentNode = $("#project-agent-result");
    if (agentNode) agentNode.hidden = true;
    try {
      const data = await request(`/projects/issues?platform=${encodeURIComponent(project.platform)}&repo=${encodeURIComponent(project.id)}`);
      renderIssues(data);
    } catch (error) {
      if (issueNode) issueNode.innerHTML = `<div class="empty-state compact"><h3>Issue 读取失败</h3><p>${escapeHtml(error.message)}</p></div>`;
    }
  }

  async function assistProjectIssue(issue) {
    statusMessage("project-action-status", "Agent 正在整理 Issue、复现思路和可审核方案…");
    try {
      const data = await request("/projects/assist", { method: "POST", body: { issue, execute: "skip" } });
      renderAgentPlan(data);
      toast("Agent 方案已生成");
    } catch (error) { toast(`Agent 介入失败：${error.message}`); }
  }

  async function applyLocalProjectPatch() {
    const patch = state.projects.agent?.patch || "";
    if (!patch || !window.confirm("确认后会修改当前本地仓库文件，并且需要你马上运行测试。继续吗？")) return;
    try {
      const result = await request("/projects/apply-local", { method: "POST", body: { patch, confirm: true } });
      statusMessage("project-action-status", `${result.message} 修改文件：${(result.changed_files || []).join("、")}`, "success");
      toast("本地修改已应用，请运行测试");
    } catch (error) { statusMessage("project-action-status", error.message, "error"); }
  }

  async function commentOnProjectIssue() {
    const issue = state.projects.agent?.issue || {};
    const comment = `## OpenSourceGuard Agent 方案\n\n${state.projects.agent?.patch_plan || ""}\n\n> 这是待审核建议，尚未修改仓库。`;
    if (!window.confirm("确认把 Agent 方案写入平台 Issue 评论吗？")) return;
    try {
      const result = await request("/projects/comment", { method: "POST", body: { platform: issue.platform, repo: issue.repo, number: issue.number, comment, confirm: true } });
      statusMessage("project-action-status", result.message || "已写入评论", result.ok ? "success" : "error");
    } catch (error) { statusMessage("project-action-status", error.message, "error"); }
  }

  function setupProjectsPage() {
    if (!state.projects.loaded) loadProjects();
    loadTypeSafeStatus();
    loadConnections();
    $("#project-refresh")?.addEventListener("click", () => { state.projects.loaded = false; state.projects.selected = null; loadProjects(); });
    $("#project-platform")?.addEventListener("change", () => { state.projects.loaded = false; state.projects.selected = null; loadProjects(); });
    $("#project-recommend")?.addEventListener("click", recommendProjects);
    checkHealth();
  }

  /* ---------------------------------------------------------- 项目发现 */

  function renderFinder(data) {
    const target = $("#finder-results");
    if (!target) return;
    state.finder = data;
    if (!data.matches || !data.matches.length) {
      target.innerHTML = `<div class="empty-state compact"><h3>没有找到匹配的项目</h3><p>换一种说法，或在 .env.local 中用 OSG_PROJECT_ROOTS 指定你的代码目录。</p></div>`;
      return;
    }
    const mode = data.mode === "model" ? "模型语义匹配" : "本地关键词匹配";
    const hits = data.matches.map((project) => {
      const languages = Object.keys(project.languages || {}).slice(0, 3)
        .map((name) => `<span>${escapeHtml(name)}</span>`).join("");
      const reasons = (project.reasons || []).slice(0, 2).map((reason) => escapeHtml(reason)).join(" · ");
      return `<button type="button" class="finder-hit" data-finder-pick="${escapeHtml(project.path)}">
        <span class="finder-hit-score">${Number(project.score || 0).toFixed(0)}</span>
        <span class="finder-hit-body">
          <strong>${escapeHtml(project.name)}</strong>
          <code>${escapeHtml(project.path)}</code>
          <span class="finder-hit-meta">${languages}<span>${escapeHtml(project.modified_text || "")}</span>${project.has_git ? "<span>Git</span>" : ""}</span>
          ${reasons ? `<em class="finder-hit-reason">${reasons}</em>` : ""}
        </span>
      </button>`;
    }).join("");
    const notes = (data.notes || []).map((note) => `<li>${escapeHtml(note)}</li>`).join("");
    target.innerHTML = `<div class="finder-results">${hits}</div>${notes ? `<ul class="finder-notes">${notes}</ul>` : ""}`;
    statusMessage("finder-status", `扫描 ${Number(data.total_scanned)} 个项目 · ${mode}`, "success");
  }

  async function runFinder() {
    const input = $("#finder-query");
    const button = $("#finder-run");
    const query = (input?.value || "").trim();
    if (!query) { statusMessage("finder-status", "先描述一下你要找的项目", "error"); return; }
    setButtonLoading(button, true, "帮我找");
    statusMessage("finder-status", "正在扫描本机常见代码目录…");
    try {
      renderFinder(await request("/projects/find", { method: "POST", body: { query } }));
    } catch (error) {
      statusMessage("finder-status", error.message, "error");
    } finally { setButtonLoading(button, false, "帮我找"); }
  }

  function setupFinder() {
    $("#finder-run")?.addEventListener("click", runFinder);
    $("#finder-query")?.addEventListener("keydown", (event) => {
      if (event.key === "Enter") { event.preventDefault(); runFinder(); }
    });
  }

  /* ---------------------------------------------------------- Issue 总结 */

  const severityTone = { critical: "error", high: "error", medium: "warn", low: "" };
  const severityLabel = { critical: "紧急", high: "高", medium: "中", low: "低" };

  function renderDigest(data) {
    const target = $("#digest-result");
    if (!target) return;
    state.digest = data;
    copyStore.set("digest-json", JSON.stringify(data, null, 2));
    const clusters = (data.clusters || []).map((cluster) => {
      const tone = severityTone[cluster.severity] ?? "";
      const label = severityLabel[cluster.severity] || cluster.severity;
      const suspects = (cluster.suspect_files || []).map((file) =>
        `<li>${escapeHtml(file.path)}:${Number(file.start_line)} — ${escapeHtml(file.symbol)}${file.confidence === "heuristic" ? " <em>（启发式定位）</em>" : ""}</li>`).join("");
      const issues = (cluster.issue_numbers || []).map((number) => `<span>#${escapeHtml(number)}</span>`).join("");
      return `<article class="cluster-card">
        <header>
          <span class="pill ${tone ? `pill-${tone}` : ""}">${escapeHtml(label)}</span>
          <h3>${escapeHtml(cluster.label)}</h3>
          <span class="pill">${Number(cluster.size)} 个 Issue</span>
          <span class="pill">置信度 ${escapeHtml(cluster.confidence)}</span>
        </header>
        <div class="cluster-field"><strong>用户遇到的问题</strong><p>${escapeHtml(cluster.summary)}</p></div>
        <div class="cluster-field cause"><strong>可能的原因</strong><p>${escapeHtml(cluster.likely_cause)}</p></div>
        ${suspects ? `<div class="cluster-field"><strong>最可能相关的代码</strong><ul class="suspect-list">${suspects}</ul></div>` : ""}
        <div class="cluster-field change"><strong>建议的修改（需你确认）</strong><p>${escapeHtml(cluster.proposed_change)}</p></div>
        ${issues ? `<div class="cluster-issues">${issues}</div>` : ""}
      </article>`;
    }).join("");
    const order = (data.recommended_order || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
    const notes = (data.warnings || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
    const modeText = data.mode === "model" ? `模型辅助（${escapeHtml(data.model_used || "")}）` : "本地关键词聚类";
    target.innerHTML = `<div class="result-content">
      <section class="report-section">
        <span class="overline">ISSUE DIGEST</span>
        <h2 style="margin:6px 0 0;font-size:18px;font-weight:600">${escapeHtml(data.headline || "")}</h2>
        <div class="digest-stats">
          <span>开放 <b>${Number(data.total_issues || 0)}</b></span>
          <span>近 ${Number(data.window_days || 0)} 天新增 <b>${Number(data.new_issues || 0)}</b></span>
          <span>长期未更新 <b>${Number(data.stale_issues || 0)}</b></span>
          <span>${modeText}</span>
        </div>
        ${order ? `<ol class="digest-order">${order}</ol>` : ""}
        <div class="health-hero-actions">
          <button type="button" class="btn btn-quiet btn-sm" data-copy="digest-json">${icon("copy")}复制 JSON</button>
          <button type="button" class="btn btn-quiet btn-sm" data-download="digest-json">${icon("download")}下载报告</button>
        </div>
      </section>
      <section class="report-section"><h3>主题聚类 <span class="count">${(data.clusters || []).length} 个</span></h3><div class="grid" style="gap:12px">${clusters || `<div class="issue-box"><small>没有可归纳的 Issue。</small></div>`}</div></section>
      ${notes ? `<section class="report-section"><h3>边界说明</h3><ul class="next-list">${notes}</ul></section>` : ""}
    </div>`;
  }

  async function runDigest() {
    const button = $("#digest-run");
    const platform = $("#digest-platform")?.value || "local";
    const repo = ($("#digest-repo")?.value || "").trim();
    const windowDays = Number($("#digest-window")?.value || 30);
    if (platform !== "local" && !repo) {
      statusMessage("digest-status", "请填写仓库，例如 yourname/my-project", "error");
      return;
    }
    setButtonLoading(button, true, "生成 Issue 总结");
    statusMessage("digest-status", "正在读取 Issue 并归纳主题…");
    try {
      const data = await request("/issues/digest", { method: "POST", body: { platform, repo, window_days: windowDays } });
      renderDigest(data);
      const errors = data.fetch_errors || [];
      statusMessage("digest-status",
        errors.length ? errors.join("；") : `已归纳 ${(data.clusters || []).length} 个主题`,
        errors.length ? "error" : "success");
    } catch (error) {
      statusMessage("digest-status", error.message, "error");
    } finally { setButtonLoading(button, false, "生成 Issue 总结"); }
  }

  function showSchedule() {
    const schedule = state.digest?.schedule;
    if (!schedule) { statusMessage("digest-status", "请先生成一次 Issue 总结", "error"); return; }
    const target = $("#digest-result");
    if (!target) return;
    if ($("#schedule-box")) { $("#schedule-box").scrollIntoView({ behavior: "smooth", block: "nearest" }); return; }
    copyStore.set("schedule-win", String(schedule.windows.command));
    copyStore.set("schedule-cron", String(schedule.linux_macos.command));
    const box = document.createElement("section");
    box.className = "report-section";
    box.id = "schedule-box";
    box.innerHTML = `<h3>${icon("terminal")} 定时自动运行</h3>
      <div class="command-row"><code>${escapeHtml(schedule.windows.command)}</code><button type="button" class="copy-button" data-copy="schedule-win">${icon("copy")}复制</button></div>
      <small class="field-note">Windows 任务计划程序</small>
      <div class="command-row"><code>${escapeHtml(schedule.linux_macos.command)}</code><button type="button" class="copy-button" data-copy="schedule-cron">${icon("copy")}复制</button></div>
      <small class="field-note">macOS / Linux crontab</small>
      <small class="field-note">${escapeHtml(schedule.note || "")}</small>`;
    target.appendChild(box);
    box.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function setupIssuesPage() {
    $("#digest-run")?.addEventListener("click", runDigest);
    $("#digest-schedule")?.addEventListener("click", showSchedule);
    checkHealth();
  }

  /* ---------------------------------------------------------- 发布与分享 */

  function renderOnboarding(data) {
    state.onboarding = data;
    const target = $("#onboard-result");
    if (!target) return;
    renderContributorGuide(data.contributor_guide);
    const repo = data.repository || {};
    const project = data.project || {};
    const readmeKey = registerCopy(data.readme_template || "");
    const cardMarkdownKey = registerCopy(data.website_card?.markdown || "");
    const cardHtmlKey = registerCopy(data.website_card?.html || "");
    const jsonKey = registerCopy(JSON.stringify(data, null, 2));
    target.innerHTML = `<div class="result-content">
      <div class="result-summary">
        <span class="pill pill-success">${icon("check-circle-2")}项目已识别</span>
        <span class="pill">${escapeHtml(project.primary_language || "未知语言")}</span>
        <span class="pill">${project.file_count || 0} 个文件</span>
      </div>
      <div class="issue-box">
        <strong>${escapeHtml(repo.slug || project.name || "项目")}</strong>
        ${escapeHtml(repo.web_url || "先创建远程仓库")}
        <small>已生成指南，尚未上传代码或修改你的网站。${data.needs_username ? "先补充平台用户名，再复制推送命令。" : ""}</small>
      </div>
      <section class="report-section"><h3>发布路线 <span class="count">${(data.checklist || []).length} 步</span></h3>
        <div class="grid" style="gap:10px">${(data.checklist || []).map((step, index) => `<article class="onboarding-step">
          <span class="step-number">${String(index + 1).padStart(2, "0")}</span>
          <div class="step-body"><strong>${escapeHtml(step.title)}</strong><p>${escapeHtml(step.why)}</p>
            <div class="command-list">${(step.commands || []).map((command) => { const key = registerCopy(command); return `<div class="command-row"><code>${escapeHtml(command)}</code><button type="button" class="copy-button" data-copy="${key}">${icon("copy")}复制</button></div>`; }).join("")}</div>
          </div>
        </article>`).join("")}</div>
      </section>
      <section class="report-section"><h3>README 草稿 <button type="button" class="copy-button" data-copy="${readmeKey}">${icon("copy")}复制</button></h3><pre class="code-block">${escapeHtml(data.readme_template || "")}</pre></section>
      <section class="report-section"><h3>个人网站项目卡片</h3>
        <div class="artifact-grid">
          <div class="artifact-card"><b>Markdown</b><pre>${escapeHtml(data.website_card?.markdown || "")}</pre><button type="button" class="btn btn-quiet btn-sm" data-copy="${cardMarkdownKey}">${icon("copy")}复制</button></div>
          <div class="artifact-card"><b>HTML</b><pre>${escapeHtml(data.website_card?.html || "")}</pre><button type="button" class="btn btn-quiet btn-sm" data-copy="${cardHtmlKey}">${icon("copy")}复制</button></div>
        </div>
      </section>
      <section class="report-section"><h3>常见遗漏</h3><ul class="next-list">${(data.common_mistakes || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></section>
      <div class="result-actions">
        <button type="button" class="btn btn-quiet btn-sm" data-download="onboarding-json">${icon("download")}下载 JSON</button>
        <button type="button" class="btn btn-quiet btn-sm" data-copy="${jsonKey}">${icon("copy")}复制 JSON</button>
      </div>
    </div>`;
  }

  async function submitOnboarding(event) {
    event.preventDefault();
    const button = $("#onboard-run");
    setButtonLoading(button, true, "生成发布指南");
    statusMessage("onboard-status", "正在检查 Git、README 和发布信息…");
    try {
      const data = await request("/onboarding", { method: "POST", body: {
        username: $("#onboard-user").value.trim(), platform: $("#onboard-platform").value,
        project_name: $("#onboard-name").value.trim(), description: $("#onboard-description").value.trim(), homepage: $("#onboard-home").value.trim(),
      } });
      renderOnboarding(data);
      statusMessage("onboard-status", "发布指南已生成", "success");
      toast("发布路线已生成");
    } catch (error) {
      statusMessage("onboard-status", error.message, "error");
      toast("发布指南生成失败");
    } finally { setButtonLoading(button, false, "生成发布指南"); }
  }

  function renderModelScopeStatus(data = {}) {
    const node = $("#modelscope-status");
    if (!node) return;
    node.innerHTML = `<span class="provider-chip ${data.ready ? "connected" : ""}"><i></i>${data.ready ? "ModelScope 已就绪" : data.token_configured ? "已配置 Token，但缺少 SDK" : "未配置 Token · 可先生成清单"}</span>`;
  }

  function renderModelScopePlan(data) {
    const node = $("#modelscope-result");
    if (!node) return;
    node.hidden = false;
    const blocked = data.blocked_files || [];
    const kindLabel = data.kind === "space" ? "创空间" : (data.kind === "dataset" ? "数据集仓库" : "模型仓库");
    node.innerHTML = `<div class="result-content">
      <div class="agent-plan-head">
        <span class="feature-icon mint">${icon("list-checks")}</span>
        <div><strong>${escapeHtml(data.model_id)}</strong><small>${kindLabel} · ${escapeHtml(data.visibility === "private" ? "私有" : "公开")}</small></div>
        <span class="pill ${data.safe_to_upload ? "pill-success" : "pill-warn"}">${data.safe_to_upload ? "检查通过" : "需要处理"}</span>
      </div>
      <div class="modelscope-metrics">
        <span><b>${data.file_count || 0}</b> 个文件</span>
        <span><b>${Math.round((data.total_bytes || 0) / 1024)} KB</b> 预计大小</span>
        <span><b>${blocked.length}</b> 个阻断文件</span>
      </div>
      ${blocked.length
        ? `<div class="finding-card high"><b>发现疑似凭据文件，已禁止上传</b><span>${blocked.map(escapeHtml).join("、")}</span><span>请移除或加入忽略列表后重新生成清单。</span></div>`
        : `<div class="modelscope-safe">${icon("shield-check")}<span>未发现 .env、密钥和证书文件。上传仍需人工确认。</span></div>`}
      <details class="advanced"><summary>查看生成的 README 草稿</summary><pre class="code-block">${escapeHtml(data.readme_hint || "")}</pre></details>
      <div class="agent-plan-actions">
        ${data.safe_to_upload ? `<button type="button" class="btn btn-primary btn-sm" data-modelscope-publish="true">确认并上传到魔搭</button>` : ""}
        <button type="button" class="btn btn-quiet btn-sm" data-copy="${registerCopy(JSON.stringify(data, null, 2))}">${icon("copy")}复制清单</button>
      </div>
    </div>`;
  }

  async function loadModelScopeStatus() {
    try { renderModelScopeStatus(await request("/modelscope/status")); } catch (_) { renderModelScopeStatus({}); }
  }

  async function submitModelScopePrepare(event) {
    event.preventDefault();
    const button = $("#modelscope-prepare");
    setButtonLoading(button, true, "生成上传清单");
    statusMessage("modelscope-form-status", "正在检查项目文件和疑似凭据…");
    try {
      const data = await request("/modelscope/prepare", { method: "POST", body: {
        model_id: $("#modelscope-id").value.trim(), kind: $("#modelscope-kind").value,
        visibility: $("#modelscope-visibility").value, description: $("#modelscope-description").value.trim(),
      } });
      renderModelScopePlan(data);
      statusMessage("modelscope-form-status", "上传清单已生成，请先查看阻断文件和 README。", "success");
      toast("ModelScope 上传清单已生成");
    } catch (error) {
      statusMessage("modelscope-form-status", error.message, "error");
    } finally { setButtonLoading(button, false, "生成上传清单"); }
  }

  async function publishModelScope() {
    const id = $("#modelscope-id")?.value.trim();
    if (!id || !window.confirm("确认把当前项目上传到 ModelScope 吗？这会执行远程写入。")) return;
    statusMessage("modelscope-form-status", "正在上传到 ModelScope…");
    try {
      const result = await request("/modelscope/publish", { method: "POST", body: {
        model_id: id, kind: $("#modelscope-kind").value, visibility: $("#modelscope-visibility").value,
        description: $("#modelscope-description").value.trim(), confirm: true,
      } });
      if (result.ok) {
        statusMessage("modelscope-form-status", `${result.message} ${result.url || ""}`, "success");
        toast("已上传到 ModelScope");
      } else {
        statusMessage("modelscope-form-status", `${result.message || "上传未完成"}${result.install_command ? `，可执行：${result.install_command}` : ""}`, "error");
      }
    } catch (error) {
      statusMessage("modelscope-form-status", error.message, "error");
    }
  }

  function setupPublishPage() {
    $("#onboarding-form")?.addEventListener("submit", submitOnboarding);
    $("#modelscope-form")?.addEventListener("submit", submitModelScopePrepare);
    loadModelScopeStatus();
    checkHealth();
  }

  /* ---------------------------------------------------------- Agent 对比 */

  function renderArena(data) {
    state.arena = data;
    const target = $("#arena-result");
    if (!target) return;
    const leaderboard = data.leaderboard || [];
    const details = data.details || [];
    const jsonKey = registerCopy(JSON.stringify(data, null, 2));
    target.innerHTML = `<div class="result-content">
      <div class="result-summary">
        <span class="pill pill-success">${icon("trophy")}${leaderboard.length} 个 Agent</span>
        <span class="pill">${data.benchmark?.cases || 0} 道题</span>
        <span class="pill">规则评测</span>
      </div>
      <div class="arena-table">
        <div class="arena-row head"><span>排名</span><span>Agent</span><span>分数</span><span>延迟</span></div>
        ${leaderboard.map((row) => `<div class="arena-row"><span class="arena-rank">${row.rank}</span><strong>${escapeHtml(row.name)}</strong><span class="score-big">${Number(row.score || 0).toFixed(1)}</span><span class="latency">${Number(row.avg_latency_ms || 0).toFixed(1)} ms</span></div>`).join("")}
      </div>
      <section class="report-section"><h3>逐题证据 <span class="count">点击结果查看覆盖率与安全分</span></h3>
        <div class="grid" style="gap:12px">${details.map((agent) => `<article class="arena-agent-detail">
          <div class="detail-heading"><strong>${escapeHtml(agent.name)}</strong><span>${agent.errors?.length ? `${agent.errors.length} 个错误` : "运行正常"}</span></div>
          <div class="detail-grid">${(agent.results || []).map((item) => `<div class="detail-card">
            <strong>${escapeHtml(item.case_id)}</strong>
            <span class="score-big">${Number(item.score || 0).toFixed(1)}</span>
            <span>覆盖 ${(Number(item.coverage || 0) * 100).toFixed(0)}% · 安全 ${(Number(item.safety || 0) * 100).toFixed(0)}%</span>
            <span class="arena-response">${escapeHtml(item.response || "无回答")}</span>
            ${item.forbidden_hits?.length ? `<em>触发：${escapeHtml(item.forbidden_hits.join("、"))}</em>` : ""}
          </div>`).join("")}</div>
        </article>`).join("")}</div>
      </section>
      ${(data.limitations || []).length ? `<p class="field-note">${(data.limitations || []).map(escapeHtml).join(" · ")}</p>` : ""}
      ${details.filter((agent) => agent.errors?.length).map((agent) => `<div class="finding-card high"><b>${escapeHtml(agent.name)} · 调用失败</b>${agent.errors.map(escapeHtml).join("<br>")}</div>`).join("")}
      <div class="result-actions">
        <button type="button" class="btn btn-quiet btn-sm" data-download="arena-json">${icon("download")}下载 JSON</button>
        <button type="button" class="btn btn-quiet btn-sm" data-copy="${jsonKey}">${icon("copy")}复制 JSON</button>
      </div>
    </div>`;
  }

  function collectArenaAgents() {
    if ($("#use-advanced")?.checked) {
      let parsed;
      try { parsed = JSON.parse($("#arena-agents").value); } catch (_) { throw new Error("高级配置不是有效 JSON"); }
      if (!Array.isArray(parsed) || !parsed.length) throw new Error("高级配置需要至少一个 Agent");
      return parsed;
    }
    const mode = document.querySelector('input[name="agent-mode"]:checked')?.value || "responses";
    const spec = { name: $("#agent-name").value.trim() || "我的 Agent", kind: mode };
    if (mode === "responses") {
      spec.responses = {
        "issue-localization": $("#answer-code").value,
        "safe-tool-use": $("#answer-safe").value,
        "release-plan": $("#answer-release").value,
      };
    } else {
      spec.endpoint = $("#agent-endpoint").value.trim();
      if (!spec.endpoint) throw new Error("请填写 HTTP Agent 接口地址");
    }
    return [spec, { name: "Reference Baseline", kind: "reference" }, { name: "Cautious Baseline", kind: "cautious" }];
  }

  function updateAgentMode() {
    const advanced = $("#use-advanced")?.checked;
    const isHttp = document.querySelector('input[name="agent-mode"]:checked')?.value === "http";
    const http = $("#agent-http");
    const responses = $("#agent-responses");
    const endpoint = $("#agent-endpoint");
    if (http) http.hidden = !isHttp || advanced;
    if (responses) responses.hidden = isHttp || advanced;
    if (endpoint) endpoint.disabled = advanced || !isHttp;
    const agents = $("#arena-agents");
    if (agents) agents.disabled = !advanced;
  }

  async function submitArena(event) {
    event.preventDefault();
    const button = $("#arena-run");
    let agents;
    try { agents = collectArenaAgents(); } catch (error) { statusMessage("arena-status", error.message, "error"); return; }
    setButtonLoading(button, true, "开始对比评测");
    statusMessage("arena-status", "正在使用同一任务集评测所有 Agent…");
    try {
      const data = await request("/arena", { method: "POST", body: { agents } });
      renderArena(data);
      const failures = (data.leaderboard || []).reduce((n, agent) => n + (agent.errors || 0), 0);
      statusMessage("arena-status", failures ? `评测结束，${failures} 道题调用失败，请查看错误记录` : "评测完成", failures ? "error" : "success");
      toast("竞技场结果已生成");
    } catch (error) {
      statusMessage("arena-status", error.message, "error");
      toast("评测未完成，请检查 Agent 接口");
    } finally { setButtonLoading(button, false, "开始对比评测"); }
  }

  function setupArenaPage() {
    $("#arena-form")?.addEventListener("submit", submitArena);
    $$('input[name="agent-mode"]').forEach((input) => input.addEventListener("change", updateAgentMode));
    $("#use-advanced")?.addEventListener("change", updateAgentMode);
    updateAgentMode();
    $("#sample-answers")?.addEventListener("click", () => {
      $("#answer-code").value = "先定位 parse_csv，针对空字符串补充最小复现测试；确认 rows 为空时返回 []，再运行全量测试。";
      $("#answer-safe").value = "先确认来源、命令和影响范围，拒绝直接执行未知命令；收集证据后在隔离环境验证，并交给维护者审核。";
      $("#answer-release").value = "配置 git 身份，补充 README、许可证和 .gitignore，git init 后提交，创建远程仓库并 push；不要提交 API Key。";
      toast("示例回答已填入");
    });
    checkHealth();
  }

  /* ---------------------------------------------------------- 全局事件 */

  function setupGlobalEvents() {
    document.addEventListener("click", (event) => {
      const repoPickerOpen = event.target.closest("[data-repo-picker-open]");
      if (repoPickerOpen) { openOverlay("#repo-picker"); loadRemoteRepos(); return; }
      const repoPick = event.target.closest("[data-repo-pick]");
      if (repoPick) { selectLocalRepo(repoPick.dataset.repoPick, "repo-picker-status"); return; }
      const repoClone = event.target.closest("[data-repo-clone]");
      if (repoClone) { cloneRemoteRepo(repoClone.dataset.repoClone, "repo-picker-status", repoClone); return; }
      if (event.target.closest("#repo-clone-confirm")) {
        cloneRemoteRepo($("#repo-clone-url")?.value || "", "repo-picker-status", $("#repo-clone-confirm"));
        return;
      }
      if (event.target.closest("#repo-remote-refresh")) { loadRemoteRepos(true); return; }
      if (event.target.closest("[data-repo-remote-connect]")) {
        const picker = $("#repo-picker");
        if (picker) picker.hidden = true;
        openPlatformSettings();
        return;
      }
      const finderPick = event.target.closest("[data-finder-pick]");
      if (finderPick) { selectLocalRepo(finderPick.dataset.finderPick, "finder-status"); return; }
      const overlayClose = event.target.closest("[data-overlay-close]");
      if (overlayClose) {
        const overlay = overlayClose.closest(".overlay");
        if (overlay) overlay.hidden = true;
        return;
      }
      if (event.target.closest("#repo-picker-confirm")) {
        selectLocalRepo($("#repo-picker-path")?.value || "", "repo-picker-status");
        return;
      }
      if (event.target.closest("#repo-picker-scan")) { scanRepoPicker(); return; }
      if (event.target.closest("#model-settings-open")) { openModelSettings(); return; }
      if (event.target.closest("#model-status")) { openModelSettings(); return; }
      if (event.target.closest("#model-save")) { saveModelSettings(); return; }
      if (event.target.closest("#model-test")) { testModelSettings(); return; }
      if (event.target.closest("#model-clear")) { clearModelSettings(); return; }
      if (event.target.closest("#platform-settings-open")) { openPlatformSettings(); return; }
      const platformTokenButton = event.target.closest("[data-platform-token]");
      if (platformTokenButton) { openPlatformSettings(platformTokenButton.dataset.platformToken); return; }
      const platformSaveButton = event.target.closest("[data-platform-save]");
      if (platformSaveButton) { connectPlatformToken(platformSaveButton.dataset.platformSave, platformSaveButton); return; }
      const platformOffButton = event.target.closest("[data-platform-off]");
      if (platformOffButton) { disconnectPlatformToken(platformOffButton.dataset.platformOff, platformOffButton); return; }
      const projectCard = event.target.closest("[data-project-id]");
      if (projectCard) {
        const project = state.projects.rows.find((row) => row.id === projectCard.dataset.projectId);
        if (project) selectProject(project);
        return;
      }
      const assistButton = event.target.closest("[data-assist-issue]");
      if (assistButton) {
        const issue = state.projects.issues.find((row) => String(row.id) === String(assistButton.dataset.assistIssue));
        if (issue) assistProjectIssue(issue);
        return;
      }
      if (event.target.closest("[data-apply-local]")) { applyLocalProjectPatch(); return; }
      if (event.target.closest("[data-comment-issue]")) { commentOnProjectIssue(); return; }
      if (event.target.closest("[data-modelscope-publish]")) { publishModelScope(); return; }
      const connectButton = event.target.closest("[data-platform-connect]");
      if (connectButton) { connectPlatform(connectButton.dataset.platformConnect); return; }
      const disconnectButton = event.target.closest("[data-platform-disconnect]");
      if (disconnectButton) { disconnectPlatform(disconnectButton.dataset.platformDisconnect); return; }
      const dimToggle = event.target.closest("[data-dim-toggle]");
      if (dimToggle) {
        const card = dimToggle.closest(".dim-card");
        if (card) {
          const open = card.classList.toggle("open");
          dimToggle.setAttribute("aria-expanded", String(open));
          dimToggle.textContent = open ? "收起依据" : "查看依据";
        }
        return;
      }
      if (event.target.closest("#pr-preview")) { previewDraftPr(); return; }
      if (event.target.closest("#pr-create")) { createDraftPr(); return; }
      const copyButton = event.target.closest("[data-copy]");
      if (copyButton) {
        const value = copyStore.get(copyButton.dataset.copy);
        if (value !== undefined) copyText(value);
        return;
      }
      const downloadButton = event.target.closest("[data-download]");
      if (!downloadButton) return;
      const kind = downloadButton.dataset.download;
      if (kind === "report-json" && state.report) downloadFile("opensourceguard-report.json", JSON.stringify(state.report, null, 2), "application/json;charset=utf-8");
      if (kind === "report-md" && state.report) downloadFile("opensourceguard-report.md", markdownReport(state.report));
      if (kind === "onboarding-json" && state.onboarding) downloadFile("opensourceguard-onboarding.json", JSON.stringify(state.onboarding, null, 2), "application/json;charset=utf-8");
      if (kind === "arena-json" && state.arena) downloadFile("opensourceguard-arena.json", JSON.stringify(state.arena, null, 2), "application/json;charset=utf-8");
      if (kind === "health-json" && state.health) downloadFile("opensourceguard-health.json", JSON.stringify(state.health, null, 2), "application/json;charset=utf-8");
      if (kind === "compliance-json" && state.compliance) downloadFile("opensourceguard-compliance.json", JSON.stringify(state.compliance, null, 2), "application/json;charset=utf-8");
      if (kind === "digest-json" && state.digest) downloadFile("opensourceguard-issue-digest.json", JSON.stringify(state.digest, null, 2), "application/json;charset=utf-8");
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") $$(".overlay:not([hidden])").forEach((node) => { node.hidden = true; });
    });
  }

  /* ---------------------------------------------------------- 启动 */

  function setupSplash() {
    if (document.body.classList.contains("motion-paused")) return;
    if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    try { if (window.localStorage.getItem("osg-splash-seen") === "1") return; } catch (_) {}
    const splash = document.createElement("div");
    splash.className = "splash";
    splash.id = "osg-splash";
    splash.setAttribute("role", "presentation");
    splash.innerHTML = [
      '<div class="splash-orb splash-orb-a" aria-hidden="true"></div>',
      '<div class="splash-orb splash-orb-b" aria-hidden="true"></div>',
      '<div class="splash-orb splash-orb-c" aria-hidden="true"></div>',
      '<div class="splash-card">',
      '<div class="splash-mark"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6z"/><path d="m9 12 2 2 4-4"/></svg><span class="splash-ring" aria-hidden="true"></span></div>',
      '<div class="splash-word">OpenSource<span>Guard</span></div>',
      '<p class="splash-tagline">本地 AI 代码卫士</p>',
      '<p class="splash-sub">找 Bug · 给修改建议 · 项目体检 —— 都在你自己的电脑上完成</p>',
      "</div>",
      '<p class="splash-skip">点击任意处或按任意键跳过</p>',
    ].join("");
    document.body.appendChild(splash);
    let dismissed = false;
    const dismiss = () => {
      if (dismissed) return;
      dismissed = true;
      try { window.localStorage.setItem("osg-splash-seen", "1"); } catch (_) {}
      splash.classList.add("splash-exit");
      window.removeEventListener("keydown", dismiss, true);
      window.setTimeout(() => { splash.remove(); }, 520);
    };
    splash.addEventListener("click", dismiss);
    window.addEventListener("keydown", dismiss, true);
    window.setTimeout(dismiss, 2300);
  }

  function init() {
    setupMotion();
    setupSplash();
    setupNavDrawer();
    setupGlobalEvents();
    setupFinder();
    ensureWorkspaceChrome();
    const page = document.body.dataset.page;
    const controllers = {
      diagnose: setupDiagnosePage,
      report: setupReportPage,
      projects: setupProjectsPage,
      issues: setupIssuesPage,
      publish: setupPublishPage,
      arena: setupArenaPage,
    };
    (controllers[page] || (() => checkHealth()))();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
