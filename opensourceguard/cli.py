from __future__ import annotations

import argparse
import json
import os
import re
import socket
import shutil
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .arena import ARENA_CASES, run_arena
from .compliance import audit as compliance_audit, to_markdown as compliance_markdown
from .discovery import find as find_projects, scan as scan_projects
from .health import evaluate as evaluate_health, to_markdown as health_markdown
from .integrations import draft_pr_payload, normalize_issue_payload
from .issues import schedule_hint, summarise as summarise_issues, to_markdown as issues_markdown
from .onboarding import build_onboarding
from .pipeline import analyze
from .report import to_markdown, write_report
from .model import ModelClient, clear_model_config, client_from_config, load_model_config, save_model_config
from .patching import apply_patch
from .providers import add_issue_comment, build_agent_plan, create_draft_pr, issue_from_payload, list_issues, list_projects, list_pull_requests
from .modelscope import prepare as prepare_modelscope, publish as publish_modelscope, status as modelscope_status
from .typesafe import recommend as recommend_projects, status as typesafe_status
from .connections import begin_oauth, callback_html, disconnect as disconnect_connection, finish_oauth, list_connections, save_token, token_for, token_guide


ROOT = Path(__file__).resolve().parents[1]


def demo_status() -> dict:
    """Describe the judge/demo account without ever exposing the key itself."""
    enabled = os.getenv("OSG_DEMO_MODE", "").strip() in {"1", "true", "yes", "on"}
    model = client_from_config()
    return {
        "enabled": enabled,
        "label": os.getenv("OSG_DEMO_LABEL", "演示账号"),
        "model_ready": model.enabled,
        "model": model.model if model.enabled else "",
        "capabilities": {
            "llm_analysis": model.enabled,
            "local_project_discovery": True,
            "issue_digest": True,
            "remote_write": False,
        },
        "boundaries": [
            "演示账号只读：不会评论、提交 PR 或上传任何内容。",
            "所有写操作仍然需要你自己的 Token 并二次确认。",
            "模型调用使用项目所有者预置的额度，请勿用于批量任务。",
        ],
    }

STATIC_FILES = {
    "/styles.css": (ROOT / "web" / "styles.css", "text/css; charset=utf-8"),
    "/app.js": (ROOT / "web" / "app.js", "application/javascript; charset=utf-8"),
    "/icons.js": (ROOT / "web" / "icons.js", "application/javascript; charset=utf-8"),
    "/report.html": (ROOT / "web" / "report.html", "text/html; charset=utf-8"),
    "/projects.html": (ROOT / "web" / "projects.html", "text/html; charset=utf-8"),
    "/issues.html": (ROOT / "web" / "issues.html", "text/html; charset=utf-8"),
    "/publish.html": (ROOT / "web" / "publish.html", "text/html; charset=utf-8"),
    "/arena.html": (ROOT / "web" / "arena.html", "text/html; charset=utf-8"),
}


class LocalHTTPServer(ThreadingHTTPServer):
    # Windows SO_REUSEADDR allows two servers to bind the very same port.
    allow_reuse_address = False

    def __init__(self, server_address, handler_class, bind_and_activate=True):
        super().__init__(server_address, handler_class, bind_and_activate)
        # Runtime state shared by all handler threads: the UI can switch the
        # working repo and the model configuration without restarting.
        self.state_lock = threading.Lock()
        default_repo = getattr(handler_class, "repo", None)
        self.repo = Path(default_repo).resolve() if default_repo else Path.cwd().resolve()
        self.model_config = load_model_config()

    def server_bind(self):
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def _print_report(report) -> None:
    print(to_markdown(report))


def run_demo() -> int:
    source = ROOT / "examples" / "buggy_csv"
    report = analyze(source, "读取空 CSV 文件时 parse_csv 崩溃，应该返回空列表")
    artifact = ROOT / "artifacts" / "demo_report.json"
    write_report(report, artifact)
    _print_report(report)
    print(f"\n报告已写入：{artifact}")
    return 0


_REPO_BLOCK_PARTS = (".ssh", ".gnupg", ".aws", ".azure", ".gcp", ".kube", "appdata",
                     "program files", "program files (x86)", "programdata", "windows", "$recycle.bin")


def _repo_block_reason(path: Path) -> str:
    parts = {part.lower() for part in path.parts}
    for name in _REPO_BLOCK_PARTS:
        if name in parts:
            return f"为保护你的凭据与系统文件，不能选择包含 {name} 的目录"
    return ""


_CLONE_HOSTS = {
    "github.com": ("github", "OSG_GITHUB_TOKEN"),
    "gitee.com": ("gitee", "OSG_GITEE_TOKEN"),
    "gitlab.com": ("gitlab", "OSG_GITLAB_TOKEN"),
}
_CLONE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _clone_root() -> Path:
    root = Path.home() / ".opensourceguard" / "clones"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _parse_clone_url(raw_url: str) -> tuple:
    """Validate a remote repo URL, returning (host, platform, env_name, full_name)."""
    parsed = urlparse(raw_url if "://" in raw_url else f"https://{raw_url}")
    if parsed.scheme != "https":
        raise ValueError("只支持 https:// 形式的仓库地址")
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    entry = _CLONE_HOSTS.get(host)
    if not entry:
        raise ValueError("只支持 GitHub、Gitee 或 GitLab 的仓库地址")
    repo_path = parsed.path.strip("/")
    if repo_path.endswith(".git"):
        repo_path = repo_path[:-4]
    segments = [seg for seg in repo_path.split("/") if seg]
    if not 2 <= len(segments) <= 5 or any(not _CLONE_SEGMENT_RE.fullmatch(seg) for seg in segments):
        raise ValueError("仓库地址格式应为 https://主机/所有者/仓库名")
    return host, entry[0], entry[1], "/".join(segments)


def _git_clone(url: str, target: Path, token: str) -> None:
    if shutil.which("git") is None:
        raise ValueError("未检测到 git，请先安装 Git 后重试")
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    try:
        proc = subprocess.run(["git", "clone", "--depth", "1", "--single-branch", url, str(target)],
                              capture_output=True, text=True, errors="replace", timeout=300, env=env)
    except subprocess.TimeoutExpired:
        shutil.rmtree(target, ignore_errors=True)
        raise ValueError("克隆超时（超过 5 分钟），请检查网络后重试")
    if proc.returncode == 0:
        return
    shutil.rmtree(target, ignore_errors=True)
    detail = (proc.stderr or proc.stdout or "").strip()
    if token:
        detail = detail.replace(token, "***")
    if "@" in url:
        detail = detail.replace(url, "https://" + url.split("@", 1)[-1])
    lines = [line.strip() for line in detail.splitlines() if line.strip()]
    fatal = next((line for line in lines if "fatal" in line.lower()), lines[-1] if lines else "未知错误")
    raise ValueError(f"克隆失败：{fatal[:200]}")


class Handler(BaseHTTPRequestHandler):
    repo: Path

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def _trusted_origin(self):
        origin = self.headers.get("Origin")
        if not origin:
            return True  # CLI/integration requests
        port = self.server.server_address[1]
        return origin == "null" or origin in {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}

    def _write_cors(self):
        origin = self.headers.get("Origin")
        if origin == "null":
            self.send_header("Access-Control-Allow-Origin", "*")
        elif origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        if origin:
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Accept")

    def _send(self, status: int, data: object) -> None:
        raw = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._write_cors()
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _send_text(self, status: int, content: str, content_type: str) -> None:
        raw = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self._write_cors()
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _repo(self) -> Path:
        repo = getattr(self.server, "repo", None)
        if isinstance(repo, Path):
            return repo
        return type(self).repo

    def _model(self) -> ModelClient:
        config = getattr(self.server, "model_config", None)
        return client_from_config(config)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path
        query = parse_qs(parsed.query)
        if route == "/favicon.ico":
            self._send_text(204, "", "image/x-icon")
        elif route == "/health":
            model = self._model()
            self._send(200, {"status": "ok", "repo": str(self._repo()), "pid": os.getpid(),
                             "api_version": "0.2", "model_configured": model.enabled,
                             "model": model.status()})
        elif route == "/model/status":
            self._send(200, self._model().status())
        elif route == "/model/test":
            if not self._trusted_origin():
                self._send(403, {"error": "请通过本地工作台访问模型测试"})
            else:
                self._send(200, self._model().test_connection())
        elif route == "/arena/cases":
            self._send(200, {"cases": ARENA_CASES})
        elif route == "/health/report":
            # Full project health dashboard for the currently served repository.
            try:
                self._send(200, evaluate_health(self._repo()).to_dict())
            except ValueError as exc:
                self._send(400, {"error": str(exc)})
        elif route == "/compliance":
            try:
                self._send(200, compliance_audit(self._repo()).to_dict())
            except ValueError as exc:
                self._send(400, {"error": str(exc)})
        elif route == "/demo/status":
            self._send(200, demo_status())
        elif route == "/modelscope/status":
            self._send(200, modelscope_status())
        elif route == "/typesafe/status":
            self._send(200, typesafe_status())
        elif route == "/connections":
            payload = list_connections()
            payload["token_guide"] = token_guide()
            self._send(200, payload)
        elif route.startswith("/oauth/callback/"):
            platform = route.rsplit("/", 1)[-1]
            try:
                result = finish_oauth(platform, query.get("code", [""])[0], query.get("state", [""])[0], query.get("error", [""])[0])
            except Exception as exc:
                result = {"ok": False, "platform": platform, "error": "oauth_exchange_failed",
                          "message": "平台授权交换失败，请检查 OAuth App 配置和网络。", "detail_type": type(exc).__name__}
            self._send_text(200, callback_html(result), "text/html; charset=utf-8")
        elif route == "/projects":
            platform = query.get("platform", [None])[0]
            if platform and platform not in {"github", "gitee", "gitlab", "generic", "local"}:
                self._send(400, {"error": "不支持的平台"})
            else:
                self._send(200, list_projects(platform))
        elif route == "/projects/issues":
            platform = query.get("platform", [""])[0]
            repo = query.get("repo", [""])[0]
            if not platform or not repo:
                self._send(400, {"error": "platform 和 repo 是必需的"})
            elif platform not in {"github", "gitee", "gitlab", "generic", "local"}:
                self._send(400, {"error": "不支持的平台"})
            else:
                self._send(200, list_issues(platform, repo, query.get("state", ["open"])[0]))
        elif route in {"/", "/index.html"}:
            page = ROOT / "web" / "index.html"
            self._send_text(200, page.read_text(encoding="utf-8"), "text/html; charset=utf-8")
        elif route in STATIC_FILES:
            path, content_type = STATIC_FILES[route]
            self._send_text(200, path.read_text(encoding="utf-8"), content_type)
        else:
            self._send(404, {"error": "not found"})

    def do_OPTIONS(self) -> None:  # noqa: N802
        if not self._trusted_origin():
            self._send(403, {"error": "请通过本地工作台访问服务"})
            return
        self.send_response(204)
        self._write_cors()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        if not self._trusted_origin():
            self._send(403, {"error": "请通过本地工作台访问服务"})
            return
        route = urlparse(self.path).path
        if route not in {"/analyze", "/webhook", "/draft-pr", "/onboarding", "/arena", "/model/test", "/model/config", "/repo/select", "/repo/clone", "/projects/assist", "/projects/comment", "/projects/apply-local", "/projects/recommend", "/projects/find", "/issues/digest", "/modelscope/prepare", "/modelscope/publish", "/oauth/start", "/connections/disconnect", "/connections/save", "/projects/pulls"} and not route.startswith("/connections/"):
            self._send(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1_000_000:
                raise ValueError("请求内容为空或超过 1 MB")
            if self.headers.get_content_type() != "application/json":
                raise ValueError("请使用 application/json 提交请求")
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(body, dict):
                raise ValueError("请求内容必须是 JSON 对象")
            if route == "/model/test":
                self._send(200, self._model().test_connection())
                return
            if route == "/model/config":
                base_url = str(body.get("base_url", "")).strip()
                model_name = str(body.get("model", "")).strip()
                api_key = str(body.get("api_key", "")).strip()
                api_style = str(body.get("api_style", "auto") or "auto").strip().lower()
                persist = bool(body.get("persist", True))
                if len(base_url) > 300 or len(model_name) > 200 or len(api_key) > 500:
                    raise ValueError("配置内容过长")
                if api_style not in {"auto", "chat_completions", "responses"}:
                    raise ValueError("api_style 必须是 auto、chat_completions 或 responses")
                if base_url and not base_url.startswith(("http://", "https://")):
                    raise ValueError("base_url 必须以 http:// 或 https:// 开头")
                if not base_url and not model_name and not api_key:
                    with self.server.state_lock:
                        self.server.model_config = {}
                    clear_model_config()
                    self._send(200, {"ok": True, "cleared": True, "status": ModelClient().status(),
                                     "message": "已清除界面保存的模型配置，回到环境变量模式"})
                    return
                if not base_url or not model_name:
                    raise ValueError("base_url 和 model 都是必需的")
                if not api_key:
                    current = getattr(self.server, "model_config", None) or {}
                    api_key = str(current.get("api_key", "")) or os.getenv("OSG_MODEL_API_KEY", "")
                config = {"base_url": base_url, "model": model_name,
                          "api_key": api_key, "api_style": api_style}
                client = client_from_config(config)
                if not client.enabled:
                    raise ValueError("配置不完整：需要 base_url 与 model")
                with self.server.state_lock:
                    self.server.model_config = config
                saved_to = ""
                if persist:
                    try:
                        saved_to = str(save_model_config(config))
                    except OSError as exc:
                        self._send(200, {"ok": True, "status": client.status(), "persisted": False,
                                         "message": f"配置已生效，但写入本机文件失败（{exc}），重启后需要重新配置"})
                        return
                self._send(200, {"ok": True, "status": client.status(), "persisted": bool(persist),
                                 "saved_to": saved_to, "message": "模型配置已生效，API Key 不会回显"})
                return
            if route == "/repo/select":
                raw_path = str(body.get("path", "")).strip()
                if not raw_path:
                    raise ValueError("path 是必需的")
                if len(raw_path) > 500:
                    raise ValueError("路径过长")
                try:
                    resolved = Path(raw_path).expanduser().resolve()
                except OSError as exc:
                    raise ValueError(f"无法解析路径：{exc}")
                if not resolved.is_dir():
                    raise ValueError("目录不存在或不可访问")
                reason = _repo_block_reason(resolved)
                if reason:
                    raise ValueError(reason)
                with self.server.state_lock:
                    self.server.repo = resolved
                self._send(200, {"ok": True, "repo": str(resolved),
                                 "name": resolved.name or str(resolved),
                                 "message": f"已切换工作仓库：{resolved.name or resolved}"})
                return
            if route == "/repo/clone":
                raw_url = str(body.get("url", "")).strip()
                if not raw_url:
                    raise ValueError("url 是必需的")
                if len(raw_url) > 500:
                    raise ValueError("URL 过长")
                if raw_url.lower().startswith(("git@", "ssh://", "git://", "file:")):
                    raise ValueError("只支持 https:// 形式的仓库地址")
                host, platform, env_name, full_name = _parse_clone_url(raw_url)
                target = _clone_root() / f"{host}-{full_name.replace('/', '-')}"
                reused = target.exists()
                if reused:
                    if not (target / ".git").is_dir():
                        raise ValueError(f"本地目录 {target} 已存在但不是完整的仓库副本，请手动处理后重试")
                else:
                    token = token_for(platform, env_name)
                    clone_url = f"https://{host}/{full_name}.git"
                    if token:
                        user = "x-access-token" if host == "github.com" else "oauth2"
                        clone_url = f"https://{user}:{token}@{host}/{full_name}.git"
                    _git_clone(clone_url, target, token)
                reason = _repo_block_reason(target)
                if reason:
                    raise ValueError(reason)
                with self.server.state_lock:
                    self.server.repo = target
                message = (f"本地已有 {full_name} 的副本，已直接切换" if reused
                           else f"已拉取并切换工作仓库：{full_name}")
                self._send(200, {"ok": True, "repo": str(target), "name": target.name,
                                 "reused": reused, "message": message})
                return
            if route == "/oauth/start":
                platform = str(body.get("platform", "")).strip().lower()
                port = self.server.server_address[1]
                result = begin_oauth(platform, f"http://127.0.0.1:{port}/oauth/callback/{platform}")
                self._send(200, result)
                return
            if route == "/connections/save":
                platform = str(body.get("platform", "")).strip().lower()
                token = str(body.get("token", ""))
                result = save_token(platform, token, verify=bool(body.get("verify", True)))
                # The token itself is never echoed back to the browser.
                self._send(200, result)
                return
            if route == "/connections/disconnect" or route.startswith("/connections/"):
                platform = str(body.get("platform", "") or route.rsplit("/", 1)[-1]).strip().lower()
                self._send(200, disconnect_connection(platform))
                return
            if route == "/modelscope/prepare":
                result = prepare_modelscope(self._repo(), str(body.get("model_id", "")), str(body.get("kind", "model")), str(body.get("visibility", "public")), str(body.get("description", "")))
                self._send(200, result)
                return
            if route == "/modelscope/publish":
                result = publish_modelscope(self._repo(), str(body.get("model_id", "")), str(body.get("kind", "model")), str(body.get("visibility", "public")), str(body.get("description", "")), bool(body.get("confirm")))
                self._send(200, result)
                return
            if route == "/projects/recommend":
                projects = body.get("projects", [])
                if not isinstance(projects, list) or len(projects) > 50:
                    raise ValueError("projects 必须是最多 50 个项目的数组")
                if any(not isinstance(project, dict) for project in projects):
                    raise ValueError("projects 中的每一项必须是对象")
                result = recommend_projects(projects, str(body.get("interests", "")), str(body.get("avoid", "")))
                self._send(200, result)
                return
            if route == "/projects/find":
                query = str(body.get("query", "")).strip()
                if len(query) > 300:
                    raise ValueError("描述不能超过 300 字符")
                roots = body.get("roots") if isinstance(body.get("roots"), list) else None
                result = find_projects(query, roots=roots, model=self._model(),
                                       time_budget=float(body.get("time_budget", 8.0)))
                self._send(200, result)
                return
            if route == "/issues/digest":
                platform = str(body.get("platform", "local")).strip().lower()
                repo_name = str(body.get("repo", "")).strip()
                window = int(body.get("window_days", 7) or 7)
                if platform not in {"github", "gitee", "gitlab", "generic", "local"}:
                    raise ValueError("不支持的平台")
                issue_rows = body.get("issues")
                if isinstance(issue_rows, list) and issue_rows:
                    rows = [x for x in issue_rows if isinstance(x, dict)][:100]
                    errors = []
                else:
                    fetched = list_issues(platform, repo_name or "local/demo", "open")
                    rows = fetched.get("issues", [])
                    errors = fetched.get("errors", [])
                digest = summarise_issues(rows, repo=self._repo(), model=self._model(),
                                          window_days=window, platform=platform,
                                          repo_name=repo_name)
                payload = digest.to_dict()
                payload["schedule"] = schedule_hint(int(body.get("interval_hours", 24) or 24))
                payload["fetch_errors"] = errors
                self._send(200, payload)
                return
            if route == "/onboarding":
                result = build_onboarding(
                    self._repo(),
                    username=str(body.get("username", "")),
                    platform=str(body.get("platform", "github")),
                    project_name=str(body.get("project_name", "")) or None,
                    description=str(body.get("description", "")),
                    homepage=str(body.get("homepage", "")),
                )
                self._send(200, result)
                return
            if route == "/arena":
                agents = body.get("agents", [])
                if not isinstance(agents, list):
                    raise ValueError("agents 必须是数组")
                cases = body.get("cases", ARENA_CASES)
                if not isinstance(cases, list):
                    raise ValueError("cases 必须是数组")
                self._send(200, run_arena(agents, cases))
                return
            if route == "/projects/assist":
                issue = issue_from_payload(body)
                if not str(issue.get("title") or issue.get("body") or "").strip():
                    raise ValueError("Issue 标题或内容不能为空")
                if str(issue.get("platform", "local")) == "local":
                    report = analyze(self._repo(), str(issue.get("title", "")) + "\n" + str(issue.get("body", "")), mode=str(body.get("execute", "skip")), framework="unittest")
                    result = build_agent_plan(issue, self._model())
                    result["analysis"] = report.to_dict()
                    result["patch"] = report.patch or result.get("patch", "")
                    result["reproduction_test"] = report.reproduction_test or result.get("reproduction_test", "")
                    result["model_used"] = report.model_used
                else:
                    result = build_agent_plan(issue, self._model())
                self._send(200, result)
                return
            if route == "/projects/comment":
                platform = str(body.get("platform", ""))
                repo = str(body.get("repo", ""))
                number = body.get("number")
                comment = str(body.get("comment", ""))
                if not platform or not repo or number is None:
                    raise ValueError("platform、repo 和 number 是必需的")
                self._send(200, add_issue_comment(platform, repo, number, comment, bool(body.get("confirm"))))
                return
            if route == "/projects/pulls":
                platform = str(body.get("platform", ""))
                repo = str(body.get("repo", ""))
                if not platform or not repo:
                    raise ValueError("platform 和 repo 是必需的")
                self._send(200, list_pull_requests(platform, repo, str(body.get("state", "open"))))
                return
            if route == "/projects/apply-local":
                patch = str(body.get("patch", ""))
                if not patch:
                    raise ValueError("patch 不能为空")
                if not bool(body.get("confirm")):
                    self._send(200, {"ok": False, "requires_confirmation": True, "message": "请确认后才会修改当前本地仓库。"})
                    return
                changed = apply_patch(self._repo(), patch)
                self._send(200, {"ok": True, "changed_files": changed, "verification_required": True,
                                 "message": "已修改本地仓库，请立即运行测试并人工审核。"})
                return
            issue = normalize_issue_payload(body)
            if not issue:
                raise ValueError("issue is required")
            if len(issue) > 12000:
                raise ValueError("Issue 不能超过 12000 字符")
            report = analyze(self._repo(), issue, mode=str(body.get("execute", "skip")), framework=str(body.get("framework", "unittest")))
            if route == "/draft-pr":
                head = str(body.get("head", "opensourceguard/fix"))
                base = str(body.get("base", "main"))
                payload = draft_pr_payload(report, head, base)
                # Without confirm this stays a dry run: it returns the exact
                # request body so the maintainer can review before any write.
                if not bool(body.get("confirm")):
                    self._send(200, {**payload, "dry_run": True,
                                     "message": "尚未创建 PR。确认后才会向平台发起真实请求。"})
                    return
                platform = str(body.get("platform", ""))
                repo_full = str(body.get("repo", ""))
                if not platform or not repo_full:
                    self._send(200, {**payload, "ok": False, "requires_confirmation": True,
                                     "message": "缺少 platform 或 repo，无法创建 PR。", "dry_run": True})
                    return
                created = create_draft_pr(platform, repo_full, payload["title"], payload["body"],
                                          head, base, confirm=True, draft=bool(body.get("draft", True)))
                self._send(200, {**payload, **created})
            else:
                self._send(200, report.to_dict())
        except (ValueError, json.JSONDecodeError) as exc:
            self._send(400, {"error": str(exc)})
        except Exception as exc:  # keep the local API responsive when an integration fails
            self._send(500, {"error": f"{type(exc).__name__}: {exc}"})


def serve(repo: Path, port: int, host: str = "127.0.0.1") -> int:
    Handler.repo = repo.resolve()
    if not Handler.repo.is_dir():
        print(f"仓库目录不存在：{Handler.repo}")
        return 2
    try:
        server = LocalHTTPServer((host, port), Handler)
    except OSError as exc:
        print(f"无法启动端口 {port}：端口已占用或不可用，请关闭原服务或改用 --port。({exc})")
        return 2
    shown = "127.0.0.1" if host in {"127.0.0.1", "localhost", "::1"} else host
    print(f"OpenSourceGuard API: http://{shown}:{port}", flush=True)
    if shown not in {"127.0.0.1", "localhost"}:
        print("警告：当前监听所有网卡。公开部署时请勿配置任何平台 Token。", flush=True)
    print("按 Ctrl+C 停止")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="opensourceguard")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("demo", help="运行内置演示")
    onboarding_parser = sub.add_parser("onboarding", help="生成 Git、开源发布和个人网站指导")
    onboarding_parser.add_argument("--repo", type=Path, required=True)
    onboarding_parser.add_argument("--username", default="")
    onboarding_parser.add_argument("--platform", choices=["github", "gitee"], default="github")
    onboarding_parser.add_argument("--project-name")
    onboarding_parser.add_argument("--description", default="")
    onboarding_parser.add_argument("--homepage", default="")
    onboarding_parser.add_argument("--output", type=Path)
    arena_parser = sub.add_parser("arena", help="比较 Agent 的任务质量和安全性")
    arena_parser.add_argument("--agents", help="JSON 数组；省略时运行内置基线")
    arena_parser.add_argument("--output", type=Path)
    analyze_parser = sub.add_parser("analyze", help="分析本地 Python 仓库")
    analyze_parser.add_argument("--repo", type=Path, required=True)
    analyze_parser.add_argument("--issue", required=True)
    analyze_parser.add_argument("--output", type=Path)
    analyze_parser.add_argument("--execute", choices=["skip", "local", "docker"], default="skip")
    analyze_parser.add_argument("--framework", choices=["unittest", "pytest"], default="unittest")
    health_parser = sub.add_parser("health", help="生成项目健康度评分报告")
    health_parser.add_argument("--repo", type=Path, required=True)
    health_parser.add_argument("--output", type=Path, help="写入 JSON 结果")
    health_parser.add_argument("--markdown", type=Path, help="写入 Markdown 报告")
    health_parser.add_argument("--min-score", type=int,
                               help="低于该分数时返回非零退出码，便于在 CI 中做门禁")
    compliance_parser = sub.add_parser("compliance", help="审计依赖与许可证合规风险")
    compliance_parser.add_argument("--repo", type=Path, required=True)
    compliance_parser.add_argument("--output", type=Path, help="写入 JSON 结果")
    compliance_parser.add_argument("--markdown", type=Path, help="写入 Markdown 报告")
    compliance_parser.add_argument("--fail-on-high", action="store_true",
                                   help="存在高风险合规问题时返回非零退出码")
    find_parser = sub.add_parser("find", help="用自然语言在本机查找自己的项目")
    find_parser.add_argument("query", nargs="?", default="", help='例如 "我那个用 Python 写的爬虫"')
    find_parser.add_argument("--root", action="append", default=[], help="额外的搜索目录，可重复")
    find_parser.add_argument("--json", action="store_true", help="输出完整 JSON")
    find_parser.add_argument("--time-budget", type=float, default=8.0)
    issues_parser = sub.add_parser("issues", help="定期总结 Issue 并定位可能的原因")
    issues_parser.add_argument("--repo", type=Path, required=True, help="本地代码目录，用于定位可疑文件")
    issues_parser.add_argument("--platform", default="local",
                               choices=["github", "gitee", "gitlab", "generic", "local"])
    issues_parser.add_argument("--repo-name", default="", help="平台上的仓库，如 owner/name")
    issues_parser.add_argument("--window-days", type=int, default=7)
    issues_parser.add_argument("--output", type=Path, help="写入 JSON 结果")
    issues_parser.add_argument("--markdown", type=Path, help="写入 Markdown 报告")
    issues_parser.add_argument("--show-schedule", action="store_true", help="打印定时任务配置命令")
    serve_parser = sub.add_parser("serve", help="启动本地 HTTP API")
    serve_parser.add_argument("--repo", type=Path, required=True)
    serve_parser.add_argument("--port", type=int, default=8787)
    # Loopback stays the default on purpose: this tool reads local repos and holds
    # platform tokens. Containers and public demos must opt in explicitly.
    serve_parser.add_argument("--host", default="127.0.0.1",
                              help="监听地址；容器或公开部署需要显式传 0.0.0.0")
    args = parser.parse_args(argv)
    if args.command == "demo":
        return run_demo()
    if args.command == "onboarding":
        if not args.repo.exists():
            parser.error(f"仓库不存在：{args.repo}")
        result = build_onboarding(
            args.repo, args.username, args.platform, args.project_name,
            args.description, args.homepage,
        )
        raw = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(raw, encoding="utf-8")
        print(raw)
        return 0
    if args.command == "arena":
        try:
            agents = json.loads(args.agents) if args.agents else []
        except json.JSONDecodeError as exc:
            parser.error(f"--agents 不是有效 JSON：{exc}")
        if not isinstance(agents, list):
            parser.error("--agents 必须是 JSON 数组")
        result = run_arena(agents)
        raw = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(raw, encoding="utf-8")
        print(raw)
        return 0
    if args.command == "serve":
        return serve(args.repo, args.port, args.host)
    if args.command == "find":
        result = find_projects(args.query, roots=args.root, model=client_from_config(),
                               time_budget=args.time_budget)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        mode = "模型语义匹配" if result["mode"] == "model" else "本地关键词匹配"
        print(f"扫描 {result['total_scanned']} 个项目，耗时 {result['elapsed_seconds']} 秒（{mode}）")
        if not result["matches"]:
            print("没有找到匹配的项目。可用 --root 指定目录，或设置 OSG_PROJECT_ROOTS。")
            return 0
        for index, project in enumerate(result["matches"], 1):
            languages = "、".join(list((project.get("languages") or {}).keys())[:3]) or "未知"
            print(f"\n{index}. {project['name']}  [{languages}]  {project.get('modified_text', '')}")
            print(f"   {project['path']}")
            for reason in project.get("reasons", [])[:3]:
                print(f"   · {reason}")
        for note in result["notes"]:
            print(f"\n提示：{note}")
        return 0
    if args.command == "issues":
        if not args.repo.exists():
            parser.error(f"仓库不存在：{args.repo}")
        if args.platform == "local":
            rows = list_issues("local", args.repo_name or "local/demo", "open").get("issues", [])
        else:
            if not args.repo_name:
                parser.error("使用真实平台时必须提供 --repo-name，例如 owner/name")
            fetched = list_issues(args.platform, args.repo_name, "open")
            rows = fetched.get("issues", [])
            for message in fetched.get("errors", []):
                print(f"警告：{message}")
        digest = summarise_issues(rows, repo=args.repo, model=client_from_config(),
                                  window_days=args.window_days, platform=args.platform,
                                  repo_name=args.repo_name)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(digest.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"JSON 结果已写入：{args.output}")
        if args.markdown:
            args.markdown.parent.mkdir(parents=True, exist_ok=True)
            args.markdown.write_text(issues_markdown(digest), encoding="utf-8")
            print(f"Markdown 报告已写入：{args.markdown}")
        if not args.output and not args.markdown:
            print(issues_markdown(digest))
        else:
            print(f"{digest.headline}（{digest.total_issues} 个开放 Issue，{len(digest.clusters)} 个主题）")
        if args.show_schedule:
            hint = schedule_hint()
            print("\n定时运行：")
            print(f"  Windows：{hint['windows']['command']}")
            print(f"  cron   ：{hint['linux_macos']['command']}")
            print(f"  说明   ：{hint['note']}")
        return 0
    if args.command == "health":
        if not args.repo.exists():
            parser.error(f"仓库不存在：{args.repo}")
        report = evaluate_health(args.repo)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"JSON 结果已写入：{args.output}")
        if args.markdown:
            args.markdown.parent.mkdir(parents=True, exist_ok=True)
            args.markdown.write_text(health_markdown(report), encoding="utf-8")
            print(f"Markdown 报告已写入：{args.markdown}")
        if not args.output and not args.markdown:
            print(health_markdown(report))
        else:
            print(f"综合评分 {report.score}/100（{report.grade} · {report.grade_label}）")
            for dimension in report.dimensions:
                state = "未测量" if not dimension.measured else str(dimension.score)
                print(f"  {dimension.label}：{state}")
        if args.min_score is not None and report.score < args.min_score:
            print(f"健康度 {report.score} 低于门槛 {args.min_score}")
            return 1
        return 0
    if args.command == "compliance":
        if not args.repo.exists():
            parser.error(f"仓库不存在：{args.repo}")
        report = compliance_audit(args.repo)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"JSON 结果已写入：{args.output}")
        if args.markdown:
            args.markdown.parent.mkdir(parents=True, exist_ok=True)
            args.markdown.write_text(compliance_markdown(report), encoding="utf-8")
            print(f"Markdown 报告已写入：{args.markdown}")
        if not args.output and not args.markdown:
            print(compliance_markdown(report))
        else:
            severity = report.summary["severity"]
            print(f"许可证 {report.project_license or '未声明'}｜依赖 {report.summary['dependency_count']} 个"
                  f"｜高 {severity['high']} 中 {severity['medium']} 低 {severity['low']}")
        if args.fail_on_high and report.summary["severity"]["high"]:
            print("存在高风险合规问题")
            return 1
        return 0
    if not args.repo.exists():
        parser.error(f"仓库不存在：{args.repo}")
    report = analyze(args.repo, args.issue, mode=args.execute, framework=args.framework)
    if args.output:
        write_report(report, args.output)
    _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
