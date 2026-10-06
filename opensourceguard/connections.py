from __future__ import annotations

"""Local OAuth connections for GitHub, Gitee and GitLab.

The browser receives only connection metadata. OAuth codes and platform tokens
are exchanged and stored by the localhost service, never in localStorage or in
the ModelScope-hosted page. ``keyring`` is used when installed; the fallback is
a user-only JSON file so the feature still works on a fresh Python install.
"""

import base64
import hashlib
import html
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional


SUPPORTED = ("github", "gitee", "gitlab")
_PENDING: Dict[str, Dict[str, Any]] = {}
_LOCK = threading.RLock()
_MAX_STATE_AGE = 600


@dataclass(frozen=True)
class OAuthConfig:
    name: str
    label: str
    client_id_env: str
    client_secret_env: str
    authorize_url: str
    token_url: str
    user_url: str
    scope: str

    @property
    def client_id(self) -> str:
        return os.getenv(self.client_id_env, "").strip()

    @property
    def client_secret(self) -> str:
        return os.getenv(self.client_secret_env, "").strip()

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)


def oauth_config(platform: str) -> OAuthConfig:
    name = str(platform or "").strip().lower()
    configs = {
        "github": OAuthConfig("github", "GitHub", "OSG_GITHUB_CLIENT_ID", "OSG_GITHUB_CLIENT_SECRET",
                              "https://github.com/login/oauth/authorize", "https://github.com/login/oauth/access_token",
                              "https://api.github.com/user", "read:user repo"),
        "gitee": OAuthConfig("gitee", "Gitee", "OSG_GITEE_CLIENT_ID", "OSG_GITEE_CLIENT_SECRET",
                             "https://gitee.com/oauth/authorize", "https://gitee.com/oauth/token",
                             "https://gitee.com/api/v5/user", "user_info projects issues pull_requests"),
        "gitlab": OAuthConfig("gitlab", "GitLab", "OSG_GITLAB_CLIENT_ID", "OSG_GITLAB_CLIENT_SECRET",
                              "https://gitlab.com/oauth/authorize", "https://gitlab.com/oauth/token",
                              "https://gitlab.com/api/v4/user", "read_user api"),
    }
    if name not in configs:
        raise ValueError(f"不支持的 OAuth 平台：{name}")
    return configs[name]


def _store_path() -> Path:
    configured = os.getenv("OSG_CONNECTION_STORE", "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".opensourceguard" / "connections.json"


def _keyring_name(platform: str) -> str:
    return f"opensourceguard/{platform}"


def _read_store() -> Dict[str, Any]:
    path = _store_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def _write_store(data: Mapping[str, Any]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(dict(data), ensure_ascii=False, indent=2)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    try:
        os.replace(temporary, path)
    except OSError:
        # Sandboxes and some AV tools block rename inside the profile dir even
        # when plain writes are allowed; fall back to a direct write so the
        # connection still persists, and never leave the temp file behind.
        try:
            path.write_text(payload, encoding="utf-8")
        finally:
            temporary.unlink(missing_ok=True)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def _keyring_get(platform: str) -> str:
    try:
        import keyring  # type: ignore
        value = keyring.get_password("opensourceguard", _keyring_name(platform))
        return str(value or "").strip()
    except Exception:
        return ""


def _keyring_set(platform: str, token: str) -> bool:
    try:
        import keyring  # type: ignore
        keyring.set_password("opensourceguard", _keyring_name(platform), token)
        return True
    except Exception:
        return False


def _keyring_delete(platform: str) -> None:
    try:
        import keyring  # type: ignore
        keyring.delete_password("opensourceguard", _keyring_name(platform))
    except Exception:
        pass


def token_for(platform: str, env_name: str = "") -> str:
    """Return an OAuth token first, then the legacy environment token."""
    name = str(platform or "").strip().lower()
    with _LOCK:
        metadata = _read_store().get(name)
    token = _keyring_get(name) if isinstance(metadata, Mapping) else ""
    if not token and isinstance(metadata, Mapping) and metadata.get("token"):
        token = str(metadata.get("token"))
    return token or os.getenv(env_name, "").strip()


def _storage_name(platform: str) -> str:
    if _keyring_get(platform):
        return "system_keyring"
    return "local_file"


def list_connections() -> Dict[str, Any]:
    store = _read_store()
    rows = []
    for name in SUPPORTED:
        config = oauth_config(name)
        metadata = store.get(name) if isinstance(store.get(name), Mapping) else {}
        env_name = {"github": "OSG_GITHUB_TOKEN", "gitee": "OSG_GITEE_TOKEN", "gitlab": "OSG_GITLAB_TOKEN"}[name]
        oauth_token = token_for(name, env_name)
        env_token = os.getenv(env_name, "").strip()
        connected = bool(oauth_token)
        rows.append({
            "platform": name,
            "label": config.label,
            "connected": connected,
            "account": str(metadata.get("account") or ("已配置 Token" if env_token else "")),
            "scopes": list(metadata.get("scopes") or []),
            "connected_at": str(metadata.get("connected_at") or ""),
            "source": "oauth" if metadata else ("environment" if env_token else ""),
            "storage": _storage_name(name) if metadata else "",
            "oauth_ready": config.configured,
            "client_id_configured": bool(config.client_id),
            "setup_hint": f"设置 {config.client_id_env} 和 {config.client_secret_env} 后可使用官方 OAuth" if not config.configured else "",
        })
    return {"connections": rows, "store_path": str(_store_path()), "token_exposed": False}


# Where a user creates a token, and the minimum scope they should tick. Shown
# in the UI so connecting does not require reading platform documentation.
TOKEN_GUIDE: Dict[str, Dict[str, str]] = {
    "github": {
        "url": "https://github.com/settings/tokens/new?scopes=repo&description=OpenSourceGuard",
        "scope": "勾选 repo（读取仓库与 Issue）",
        "prefix": "ghp_ 或 github_pat_",
    },
    "gitee": {
        "url": "https://gitee.com/personal_access_tokens/new",
        "scope": "勾选 projects、issues",
        "prefix": "通常为 32 位字符",
    },
    "gitlab": {
        "url": "https://gitlab.com/-/user_settings/personal_access_tokens",
        "scope": "勾选 read_api",
        "prefix": "glpat-",
    },
}


def _verify_token(platform: str, token: str) -> Dict[str, Any]:
    """Call the platform's own "who am I" endpoint to validate a pasted token."""
    endpoints = {
        "github": ("https://api.github.com/user", {"Authorization": f"Bearer {token}"}),
        "gitee": (f"https://gitee.com/api/v5/user?access_token={urllib.parse.quote(token)}", {}),
        "gitlab": ("https://gitlab.com/api/v4/user", {"PRIVATE-TOKEN": token}),
    }
    if platform not in endpoints:
        return {"ok": False, "error": "unsupported_platform"}
    url, headers = endpoints[platform]
    request = urllib.request.Request(url, headers={
        "Accept": "application/json", "User-Agent": "OpenSourceGuard/0.4", **headers})
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return {"ok": False, "error": "invalid_token",
                    "message": "平台拒绝了这个 Token：可能已过期、被撤销，或权限范围不足。"}
        return {"ok": False, "error": f"http_{exc.code}",
                "message": f"平台返回 {exc.code}，请稍后重试。"}
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        return {"ok": False, "error": "connection_failed",
                "message": "无法连接平台，请检查网络或代理设置。"}
    if not isinstance(data, Mapping):
        return {"ok": False, "error": "invalid_response"}
    account = str(data.get("login") or data.get("username") or data.get("name") or "")
    return {"ok": True, "account": account}


def save_token(platform: str, token: str, verify: bool = True) -> Dict[str, Any]:
    """Connect a platform by pasting a personal access token.

    This is the one-step alternative to registering an OAuth app. The token is
    verified against the platform, stored in the system keyring when available,
    and never returned to the browser.
    """
    name = str(platform or "").strip().lower()
    if name not in SUPPORTED:
        raise ValueError(f"不支持的平台：{platform}")
    token = str(token or "").strip()
    if not token:
        raise ValueError("Token 不能为空")
    if len(token) > 500 or any(ch.isspace() for ch in token):
        raise ValueError("Token 格式无效：不应包含空格或换行")

    account = ""
    if verify:
        result = _verify_token(name, token)
        if not result.get("ok"):
            return {"ok": False, "platform": name, "error": result.get("error"),
                    "message": result.get("message", "Token 校验失败。")}
        account = result.get("account", "")

    stored_in_keyring = _keyring_set(name, token)
    with _LOCK:
        store = _read_store()
        entry: Dict[str, Any] = {
            "account": account or "已连接",
            "scopes": [],
            "connected_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "source": "token",
        }
        if not stored_in_keyring:
            # Fall back to the restricted local file only when no keyring exists.
            entry["token"] = token
        store[name] = entry
        try:
            _write_store(store)
        except OSError as exc:
            return {"ok": False, "platform": name, "error": "store_write_failed",
                    "message": f"无法写入本机连接文件（{exc}）。请检查目录权限，"
                               "或设置 OSG_CONNECTION_STORE 指向可写目录后重试。",
                    "token_exposed": False}

    return {
        "ok": True,
        "platform": name,
        "account": account,
        "storage": "system_keyring" if stored_in_keyring else "local_file",
        "message": f"已连接 {oauth_config(name).label}"
                   + (f"（{account}）" if account else ""),
        "token_exposed": False,
    }


def token_guide(platform: str = "") -> Dict[str, Any]:
    """Return where to create a token for each supported platform."""
    if platform:
        name = platform.strip().lower()
        return {name: TOKEN_GUIDE.get(name, {})}
    return dict(TOKEN_GUIDE)


def begin_oauth(platform: str, redirect_uri: str) -> Dict[str, Any]:
    config = oauth_config(platform)
    if not redirect_uri.startswith("http://127.0.0.1:") and not redirect_uri.startswith("http://localhost:"):
        raise ValueError("OAuth 回调地址必须是本机 localhost")
    if not config.configured:
        return {"ok": False, "error": "oauth_app_not_configured", "platform": config.name,
                "message": f"请先配置 {config.client_id_env} 和 {config.client_secret_env}。",
                "client_id_env": config.client_id_env, "client_secret_env": config.client_secret_env}
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    state = secrets.token_urlsafe(32)
    with _LOCK:
        _PENDING[state] = {"platform": config.name, "verifier": verifier, "redirect_uri": redirect_uri, "created_at": time.time()}
        for old, pending in list(_PENDING.items()):
            if time.time() - float(pending.get("created_at", 0)) > _MAX_STATE_AGE:
                _PENDING.pop(old, None)
    query = urllib.parse.urlencode({"client_id": config.client_id, "redirect_uri": redirect_uri,
                                    "response_type": "code", "scope": config.scope, "state": state,
                                    "code_challenge": challenge, "code_challenge_method": "S256"})
    return {"ok": True, "platform": config.name, "label": config.label, "state": state,
            "authorization_url": f"{config.authorize_url}?{query}", "redirect_uri": redirect_uri,
            "expires_in": _MAX_STATE_AGE}


def _request_json(url: str, payload: Mapping[str, Any], headers: Optional[Mapping[str, str]] = None) -> Mapping[str, Any]:
    data = urllib.parse.urlencode(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST", headers={
        "Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "OpenSourceGuard/0.5", **dict(headers or {}),
    })
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read().decode("utf-8")
    value = json.loads(raw or "{}")
    if not isinstance(value, Mapping):
        raise ValueError("OAuth 响应格式无效")
    return value


def finish_oauth(platform: str, code: str, state: str, error: str = "") -> Dict[str, Any]:
    config = oauth_config(platform)
    if error:
        return {"ok": False, "error": "oauth_denied", "message": f"用户取消了 {config.label} 授权。"}
    with _LOCK:
        pending = _PENDING.pop(state, None)
    if not pending or pending.get("platform") != config.name or time.time() - float(pending.get("created_at", 0)) > _MAX_STATE_AGE:
        return {"ok": False, "error": "oauth_state_invalid", "message": "OAuth 状态已过期，请重新连接。"}
    if not code:
        return {"ok": False, "error": "oauth_code_missing", "message": "平台没有返回授权码。"}
    token_response = _request_json(config.token_url, {"client_id": config.client_id, "client_secret": config.client_secret,
                                                      "code": code, "redirect_uri": pending["redirect_uri"],
                                                      "grant_type": "authorization_code", "code_verifier": pending["verifier"]})
    token = str(token_response.get("access_token") or "").strip()
    if not token:
        raise ValueError("平台没有返回 access_token")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json", "User-Agent": "OpenSourceGuard/0.5"}
    if config.name == "gitee":
        headers["Authorization"] = f"token {token}"
    request = urllib.request.Request(config.user_url, headers=headers)
    with urllib.request.urlopen(request, timeout=20) as response:
        profile = json.loads(response.read().decode("utf-8") or "{}")
    if not isinstance(profile, Mapping):
        profile = {}
    account = str(profile.get("login") or profile.get("username") or profile.get("name") or "已连接")
    scopes_raw = token_response.get("scope") or config.scope
    scopes = [x for x in str(scopes_raw).replace(",", " ").split() if x]
    metadata = {"account": account, "scopes": scopes, "connected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "token": token, "token_type": str(token_response.get("token_type") or "bearer")}
    stored_in_keyring = _keyring_set(config.name, token)
    if stored_in_keyring:
        metadata.pop("token", None)
    with _LOCK:
        store = _read_store()
        store[config.name] = metadata
        _write_store(store)
    return {"ok": True, "platform": config.name, "label": config.label, "account": account,
            "scopes": scopes, "storage": "system_keyring" if stored_in_keyring else "local_file"}


def disconnect(platform: str) -> Dict[str, Any]:
    config = oauth_config(platform)
    with _LOCK:
        store = _read_store()
        store.pop(config.name, None)
        _write_store(store)
    _keyring_delete(config.name)
    return {"ok": True, "platform": config.name, "message": f"已断开 {config.label} 连接。"}


def callback_html(result: Mapping[str, Any]) -> str:
    message = html.escape(str(result.get("message") or (f"已连接 {result.get('account')}" if result.get("ok") else "连接未完成")))
    payload = json.dumps({"ok": bool(result.get("ok")), "platform": result.get("platform", "")}, ensure_ascii=False)
    return f'''<!doctype html><meta charset="utf-8"><title>OpenSourceGuard 平台连接</title>
<style>body{{font-family:system-ui,sans-serif;padding:48px;color:#4d4960;background:#f7f5fb}}main{{max-width:520px;margin:auto;padding:28px;border-radius:20px;background:white;box-shadow:0 12px 40px #7567a122}}button{{padding:10px 16px;border:0;border-radius:10px;background:#7c6bc0;color:white}}</style>
<main><h2>{'连接成功' if result.get('ok') else '连接未完成'}</h2><p>{message}</p><button onclick="window.close()">关闭此页</button></main>
<script>window.opener&&window.opener.postMessage({payload}, location.origin);</script>'''
