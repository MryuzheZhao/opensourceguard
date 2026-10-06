from __future__ import annotations

"""Read-only project/issue integrations with explicit, opt-in writes.

Tokens are read only by the local service process. They are never returned to
the browser. When a platform is not configured, the UI receives a clearly
marked demo workspace so the flow remains usable offline.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional


PLATFORMS = ("github", "gitee", "gitlab", "generic")


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    label: str
    api_base: str
    token_env: str
    token_header: str = "Authorization"
    token_prefix: str = "Bearer"

    @property
    def token(self) -> str:
        if self.name in {"github", "gitee", "gitlab"}:
            try:
                from .connections import token_for
                return token_for(self.name, self.token_env)
            except Exception:
                pass
        return os.getenv(self.token_env, "").strip()

    @property
    def configured(self) -> bool:
        return bool(self.token and self.api_base)


def provider_config(name: str) -> ProviderConfig:
    name = (name or "").strip().lower()
    if name == "github":
        return ProviderConfig("github", "GitHub", os.getenv("OSG_GITHUB_API_URL", "https://api.github.com"), "OSG_GITHUB_TOKEN", token_prefix="Bearer")
    if name == "gitee":
        return ProviderConfig("gitee", "Gitee", os.getenv("OSG_GITEE_API_URL", "https://gitee.com/api/v5"), "OSG_GITEE_TOKEN", token_prefix="token")
    if name == "gitlab":
        return ProviderConfig("gitlab", "GitLab", os.getenv("OSG_GITLAB_API_URL", "https://gitlab.com/api/v4"), "OSG_GITLAB_TOKEN", token_header="PRIVATE-TOKEN", token_prefix="")
    if name == "generic":
        return ProviderConfig("generic", "兼容 API", os.getenv("OSG_GENERIC_API_URL", ""), "OSG_GENERIC_TOKEN", token_prefix="Bearer")
    raise ValueError(f"不支持的平台：{name}")


def provider_status() -> List[Dict[str, Any]]:
    rows = []
    for name in PLATFORMS:
        config = provider_config(name)
        rows.append({"name": name, "label": config.label, "configured": config.configured,
                     "api_host": urllib.parse.urlparse(config.api_base).netloc if config.api_base else "",
                     "read_only_default": True})
    return rows


def _url(base: str, path: str, query: Optional[Mapping[str, Any]] = None) -> str:
    url = base.rstrip("/") + "/" + path.lstrip("/")
    if query:
        encoded = urllib.parse.urlencode({k: v for k, v in query.items() if v is not None})
        if encoded:
            url += "?" + encoded
    return url


def _request(config: ProviderConfig, path: str, query: Optional[Mapping[str, Any]] = None,
             method: str = "GET", payload: Optional[Mapping[str, Any]] = None,
             timeout: float = 12.0) -> Any:
    headers = {"Accept": "application/json", "User-Agent": "OpenSourceGuard/0.3"}
    if config.token:
        value = f"{config.token_prefix} {config.token}".strip()
        headers[config.token_header] = value
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(_url(config.api_base, path, query), data=data, method=method, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
    if not raw:
        return {}
    return json.loads(raw)


def _demo_projects() -> List[Dict[str, Any]]:
    return [{
        "id": "local/buggy_csv", "name": "buggy_csv", "full_name": "本地示例 / buggy_csv",
        "platform": "local", "platform_label": "本地示例", "private": False,
        "html_url": "", "default_branch": "main", "open_issues": 1,
        "updated_at": "刚刚", "description": "用于演示 Issue 定位、Agent 介入和补丁验证。", "demo": True,
    }]


def _normalise_project(item: Mapping[str, Any], platform: str) -> Dict[str, Any]:
    if platform == "gitlab":
        full_name = str(item.get("path_with_namespace") or item.get("name_with_namespace") or item.get("name") or "")
        html_url = str(item.get("web_url") or "")
    else:
        full_name = str(item.get("full_name") or item.get("path") or item.get("name") or "")
        html_url = str(item.get("html_url") or item.get("web_url") or "")
    return {
        "id": full_name or str(item.get("id") or ""),
        "name": str(item.get("name") or full_name.rsplit("/", 1)[-1]),
        "full_name": full_name,
        "platform": platform,
        "platform_label": provider_config(platform).label,
        "private": bool(item.get("private", item.get("visibility") == "private")),
        "html_url": html_url,
        "default_branch": str(item.get("default_branch") or item.get("default_branch_name") or "main"),
        "open_issues": int(item.get("open_issues_count", item.get("open_issues", 0)) or 0),
        "updated_at": str(item.get("updated_at") or item.get("pushed_at") or ""),
        "description": str(item.get("description") or ""),
        "demo": False,
    }


def _normalise_issue(item: Mapping[str, Any], platform: str, repo: str) -> Dict[str, Any]:
    user = item.get("user") or item.get("author") or {}
    if not isinstance(user, Mapping):
        user = {}
    labels = item.get("labels") or []
    label_names = [str(x.get("name", x)) if isinstance(x, Mapping) else str(x) for x in labels]
    return {
        "id": str(item.get("id") or item.get("number") or ""),
        "number": item.get("number") or item.get("iid") or item.get("id"),
        "title": str(item.get("title") or "未命名 Issue"),
        "body": str(item.get("body") or item.get("description") or ""),
        "state": str(item.get("state") or "open").lower(),
        "labels": label_names,
        "author": str(user.get("login") or user.get("username") or user.get("name") or "unknown"),
        "url": str(item.get("html_url") or item.get("web_url") or ""),
        "comments": int(item.get("comments", 0) or 0),
        "created_at": str(item.get("created_at") or ""),
        "updated_at": str(item.get("updated_at") or ""),
        "repo": repo,
        "platform": platform,
    }


def list_projects(platform: Optional[str] = None) -> Dict[str, Any]:
    if platform == "local":
        return {"projects": _demo_projects(), "providers": provider_status(), "connected": [], "errors": [], "demo": True}
    names = [platform] if platform else list(PLATFORMS)
    projects: List[Dict[str, Any]] = []
    errors: List[str] = []
    connected = []
    for name in names:
        config = provider_config(name)
        if not config.configured:
            continue
        connected.append(name)
        try:
            if name == "github":
                data = _request(config, "/user/repos", {"sort": "updated", "per_page": 50, "affiliation": "owner,collaborator,organization_member"})
            elif name == "gitee":
                data = _request(config, "/user/repos", {"sort": "updated", "per_page": 50, "type": "all"})
            elif name == "gitlab":
                data = _request(config, "/projects", {"membership": "true", "order_by": "last_activity_at", "per_page": 50})
            else:
                data = _request(config, "/projects", {"per_page": 50})
            if isinstance(data, list):
                projects.extend(_normalise_project(item, name) for item in data if isinstance(item, Mapping))
        except (OSError, urllib.error.HTTPError, urllib.error.URLError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{name}: {type(exc).__name__}")
    if not projects and not connected:
        projects = _demo_projects()
    return {"projects": projects, "providers": provider_status(), "connected": connected,
            "errors": errors, "demo": not bool(connected)}


def list_issues(platform: str, repo: str, state: str = "open") -> Dict[str, Any]:
    if platform == "local":
        return {"issues": [{"id": "local-1", "number": 1, "title": "空 CSV 文件应返回空列表",
                             "body": "读取空 CSV 文件时 parse_csv 崩溃，应该返回空列表。",
                             "state": "open", "labels": ["bug", "good first issue"], "author": "OpenSourceGuard",
                             "url": "", "comments": 0, "created_at": "刚刚", "updated_at": "刚刚",
                             "repo": repo, "platform": "local"}], "demo": True, "errors": []}
    config = provider_config(platform)
    if not config.configured:
        raise ValueError(f"尚未配置 {config.label} Token")
    try:
        if platform == "github":
            data = _request(config, f"/repos/{urllib.parse.quote(repo, safe='/')}/issues", {"state": state, "per_page": 50})
        elif platform == "gitee":
            data = _request(config, f"/repos/{urllib.parse.quote(repo, safe='/')}/issues", {"state": state, "page": 1, "per_page": 50})
        elif platform == "gitlab":
            data = _request(config, f"/projects/{urllib.parse.quote(repo, safe='')}/issues", {"state": state, "per_page": 50})
        else:
            data = _request(config, f"/projects/{urllib.parse.quote(repo, safe='/')}/issues", {"state": state, "per_page": 50})
        rows = data if isinstance(data, list) else []
        return {"issues": [_normalise_issue(item, platform, repo) for item in rows if isinstance(item, Mapping)], "demo": False, "errors": []}
    except (OSError, urllib.error.HTTPError, urllib.error.URLError, ValueError, json.JSONDecodeError) as exc:
        return {"issues": [], "demo": False, "errors": [f"{config.label} 暂时无法读取 Issue：{type(exc).__name__}"]}


def issue_from_payload(body: Mapping[str, Any]) -> Dict[str, Any]:
    issue = body.get("issue")
    if isinstance(issue, Mapping):
        return dict(issue)
    return {"title": str(body.get("title", "")), "body": str(body.get("body", "")),
            "number": body.get("number"), "repo": str(body.get("repo", "")),
            "platform": str(body.get("platform", "local"))}


def build_agent_plan(issue: Mapping[str, Any], model: Any = None) -> Dict[str, Any]:
    title = str(issue.get("title") or "未命名 Issue").strip()
    body = str(issue.get("body") or "").strip()
    prompt = f"Issue 标题：{title}\nIssue 内容：{body}\n请给出安全、可审核的修复计划。"
    result = model.complete_json(
        "你是开源项目维护 Agent。只输出 JSON，字段为 reproduction_test、patch_plan、patch、warnings。不要声称已经修改远程仓库。",
        prompt,
    ) if model is not None and getattr(model, "enabled", False) else None
    if result:
        plan = str(result.get("patch_plan") or "先补充最小复现测试，再在隔离副本中验证候选补丁。")
        warnings = [str(x) for x in result.get("warnings", [])]
        model_used = getattr(model, "model", "model")
        patch = str(result.get("patch") or "")
        reproduction = str(result.get("reproduction_test") or "")
    else:
        plan = "先确认 Issue 的最小复现输入；让 Agent 在临时副本中定位相关文件；生成 unified diff；运行复现测试、全量测试和安全扫描；由维护者审核后再提交。"
        warnings = ["当前仅生成可审核方案，不会自动修改远程仓库。"]
        model_used = "heuristic"
        patch = ""
        reproduction = ""
    return {"action": "agent_plan", "issue": dict(issue), "model_used": model_used,
            "patch_plan": plan, "patch": patch, "reproduction_test": reproduction,
            "warnings": warnings, "approval_required": True,
            "remote_write_available": bool(issue.get("platform") in PLATFORMS and issue.get("repo")),
            "next_steps": ["查看 Agent 方案", "在本地临时副本验证", "确认后再创建平台草稿或评论"]}


def add_issue_comment(platform: str, repo: str, number: Any, comment: str, confirm: bool = False) -> Dict[str, Any]:
    if not confirm:
        return {"ok": False, "requires_confirmation": True, "message": "请明确确认后再写入平台 Issue。"}
    if platform not in PLATFORMS or platform == "generic":
        raise ValueError("当前平台不支持直接写入 Issue 评论")
    config = provider_config(platform)
    if not config.configured:
        raise ValueError(f"尚未配置 {config.label} Token")
    if not comment.strip() or len(comment) > 20000:
        raise ValueError("评论不能为空且不能超过 20000 字符")
    if platform == "github":
        path = f"/repos/{urllib.parse.quote(repo, safe='/')}/issues/{urllib.parse.quote(str(number), safe='')}/comments"
        payload = {"body": comment}
    elif platform == "gitee":
        path = f"/repos/{urllib.parse.quote(repo, safe='/')}/issues/{urllib.parse.quote(str(number), safe='')}/comments"
        payload = {"body": comment}
    else:
        path = f"/projects/{urllib.parse.quote(repo, safe='')}/issues/{urllib.parse.quote(str(number), safe='')}/notes"
        payload = {"body": comment}
    try:
        data = _request(config, path, method="POST", payload=payload)
        return {"ok": True, "platform": platform, "repo": repo, "number": number,
                "url": str(data.get("html_url") or data.get("web_url") or "") if isinstance(data, Mapping) else "",
                "message": "已写入平台 Issue 评论。"}
    except (OSError, urllib.error.HTTPError, urllib.error.URLError, ValueError, json.JSONDecodeError) as exc:
        return {"ok": False, "message": f"平台写入失败：{type(exc).__name__}"}


def create_draft_pr(platform: str, repo: str, title: str, body: str, head: str, base: str,
                    confirm: bool = False, draft: bool = True) -> Dict[str, Any]:
    """Open a real draft pull request after the maintainer confirms.

    The candidate patch is never pushed by this function: `head` must already
    exist on the remote (created by the maintainer with the same verified diff).
    Opening the PR is what makes the flow auditable, because the PR body carries
    the baseline/candidate test results and the reviewer decides what happens next.
    """
    if not confirm:
        return {"ok": False, "requires_confirmation": True,
                "message": "请明确确认后再创建平台草稿 PR。"}
    if platform not in PLATFORMS or platform == "generic":
        raise ValueError("当前平台不支持直接创建草稿 PR")
    config = provider_config(platform)
    if not config.configured:
        raise ValueError(f"尚未配置 {config.label} Token")
    if not head.strip() or not base.strip():
        raise ValueError("必须同时提供 head 分支和 base 分支")
    if head.strip() == base.strip():
        raise ValueError("head 与 base 不能是同一个分支，草稿 PR 必须指向独立分支")
    title = str(title or "").strip()
    if not title or len(title) > 240:
        raise ValueError("标题不能为空且不能超过 240 字符")
    if len(str(body or "")) > 60000:
        raise ValueError("PR 正文不能超过 60000 字符")
    if platform == "github":
        path = f"/repos/{urllib.parse.quote(repo, safe='/')}/pulls"
    elif platform == "gitee":
        path = f"/repos/{urllib.parse.quote(repo, safe='/')}/pulls"
    else:
        path = f"/projects/{urllib.parse.quote(repo, safe='')}/merge_requests"
    payload: Dict[str, Any] = {"title": title, "body": str(body or ""), "head": head, "base": base}
    if platform == "gitlab":
        payload["source_branch"] = head
        payload["target_branch"] = base
    # GitLab has no draft flag on creation; it is set by title prefix and an update.
    if platform != "gitlab":
        payload["draft"] = bool(draft)
    try:
        data = _request(config, path, method="POST", payload=payload)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:400]
        except Exception:
            pass
        hint = ""
        if exc.code == 404:
            hint = "，请确认 head 分支已经推送到远程（当前工具不会替你 push）"
        elif exc.code == 422:
            hint = "，请检查 head/base 分支名与仓库是否可写"
        elif exc.code in (401, 403):
            hint = "，请确认 Token 具有 pull_requests 写权限"
        return {"ok": False, "code": exc.code,
                "message": f"创建草稿 PR 失败：HTTP {exc.code}{hint}",
                "detail": detail}
    except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError) as exc:
        return {"ok": False, "message": f"创建草稿 PR 失败：{type(exc).__name__}"}
    if not isinstance(data, Mapping):
        return {"ok": False, "message": "平台返回了无法解析的响应。"}
    return {"ok": True, "platform": platform, "repo": repo, "number": data.get("number") or data.get("iid"),
            "url": str(data.get("html_url") or data.get("web_url") or ""),
            "state": str(data.get("state") or ""), "draft": bool(draft) and platform != "gitlab",
            "head": head, "base": base,
            "message": "草稿 PR 已创建，等待维护者审核。"}


def list_pull_requests(platform: str, repo: str, state: str = "open") -> Dict[str, Any]:
    """Read-only listing used to confirm that a draft PR really exists."""
    config = provider_config(platform)
    if not config.configured:
        raise ValueError(f"尚未配置 {config.label} Token")
    try:
        if platform == "gitlab":
            data = _request(config, f"/projects/{urllib.parse.quote(repo, safe='')}/merge_requests", {"state": state, "per_page": 20})
        else:
            data = _request(config, f"/repos/{urllib.parse.quote(repo, safe='/')}/pulls", {"state": state, "per_page": 20})
    except (OSError, urllib.error.HTTPError, urllib.error.URLError, ValueError, json.JSONDecodeError) as exc:
        return {"pulls": [], "errors": [f"{config.label} 无法读取 PR：{type(exc).__name__}"]}
    rows = data if isinstance(data, list) else []
    pulls = []
    for item in rows:
        if not isinstance(item, Mapping):
            continue
        pulls.append({"number": item.get("number") or item.get("iid"),
                      "title": str(item.get("title") or ""),
                      "url": str(item.get("html_url") or item.get("web_url") or ""),
                      "draft": bool(item.get("draft", False)),
                      "state": str(item.get("state") or ""),
                      "head": str((item.get("head") or {}).get("ref") if isinstance(item.get("head"), Mapping) else ""),
                      "base": str((item.get("base") or {}).get("ref") if isinstance(item.get("base"), Mapping) else "")})
    return {"pulls": pulls, "errors": []}

