from __future__ import annotations

"""Optional OpenAI-compatible model client with safe offline fallback."""

import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

_ALLOWED_FIELDS = {"reproduction_test", "patch_plan", "patch", "warnings"}
_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "reproduction_test": {"type": "string"},
        "patch_plan": {"type": "string"},
        "patch": {"type": "string"},
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["reproduction_test", "patch_plan", "patch", "warnings"],
    "additionalProperties": False,
}


class ModelClient:
    """Dependency-free client for Chat Completions or Responses APIs."""

    def __init__(self, base_url: Optional[str] = None, model: Optional[str] = None,
                 api_key: Optional[str] = None, timeout: Optional[float] = None,
                 api_style: Optional[str] = None):
        self.base_url = (base_url if base_url is not None else os.getenv("OSG_MODEL_BASE_URL", "")).strip()
        self.model = (model if model is not None else os.getenv("OSG_MODEL_NAME", "")).strip()
        self.api_key = api_key if api_key is not None else os.getenv("OSG_MODEL_API_KEY", "")
        raw_timeout = timeout if timeout is not None else os.getenv("OSG_MODEL_TIMEOUT", "45")
        try:
            self.timeout = max(0.1, min(float(raw_timeout), 180.0))
        except (TypeError, ValueError):
            self.timeout = 45.0
        self.api_style = (api_style or os.getenv("OSG_MODEL_API_STYLE", "auto")).strip().lower()
        if self.api_style not in {"auto", "chat_completions", "responses"}:
            self.api_style = "auto"
        self.last_error: Optional[str] = None

    @property
    def enabled(self) -> bool:
        return bool(self.base_url and self.model)

    @property
    def style(self) -> str:
        if self.api_style != "auto":
            return self.api_style
        return "responses" if "/responses" in self.base_url.rstrip("/").lower() else "chat_completions"

    def status(self) -> Dict[str, Any]:
        host = ""
        if self.base_url:
            try:
                host = urllib.parse.urlparse(self.base_url).netloc
            except ValueError:
                pass
        return {"configured": self.enabled, "model": self.model if self.enabled else "",
                "base_url": self.base_url if self.enabled else "",
                "endpoint_host": host, "api_style": self.style if self.enabled else "",
                "api_key_configured": bool(self.api_key), "last_error": self.last_error}

    @staticmethod
    def _content(raw: Dict[str, Any], style: str) -> Any:
        if style == "responses":
            if raw.get("output_text") is not None:
                return raw["output_text"]
            for item in raw.get("output", []) or []:
                for part in item.get("content", []) if isinstance(item, dict) else []:
                    if isinstance(part, dict) and part.get("text") is not None:
                        return part["text"]
            return None
        choices = raw.get("choices")
        if not isinstance(choices, list) or not choices:
            return None
        message = choices[0].get("message", {})
        return message.get("content") if isinstance(message, dict) else None

    @staticmethod
    def _normalise(value: Any, allowed: Optional[tuple] = None) -> Optional[Dict[str, Any]]:
        """Validate and narrow a model response to the expected shape.

        ``allowed`` defaults to the patch-analysis fields. Callers that need a
        different result shape (project matching, issue digests) pass their own
        field names; those fields are returned as-is after a type check, so a
        malformed response still fails closed instead of reaching the UI.
        """
        if isinstance(value, str):
            value = value.strip()
            if value.startswith("```") and value.endswith("```"):
                value = value[3:-3].strip()
                if value.lower().startswith("json"):
                    value = value[4:].strip()
            try:
                value = json.loads(value)
            except (TypeError, ValueError, json.JSONDecodeError):
                return None
        if not isinstance(value, dict):
            return None

        if allowed is not None:
            result: Dict[str, Any] = {}
            for key in allowed:
                if key in value:
                    result[key] = value[key]
            return result or None

        result = {}
        for key in _ALLOWED_FIELDS:
            if key not in value:
                continue
            item = value[key]
            if key == "warnings":
                if not isinstance(item, list) or not all(isinstance(entry, (str, int, float, bool)) for entry in item):
                    return None
                result[key] = [str(entry) for entry in item if str(entry).strip()]
            elif isinstance(item, str):
                result[key] = item
            else:
                return None
        return result or None

    def _payload(self, system: str, user: str) -> Dict[str, Any]:
        if self.style == "responses":
            return {"model": self.model,
                    "input": [{"role": "system", "content": [{"type": "input_text", "text": system}]},
                               {"role": "user", "content": [{"type": "input_text", "text": user}]}],
                    "text": {"format": {"type": "json_schema", "name": "opensourceguard_result",
                                          "strict": True, "schema": _OUTPUT_SCHEMA}}}
        return {"model": self.model, "temperature": 0, "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}

    def _request(self, system: str, user: str, schema_fields: Optional[tuple] = None) -> Optional[Dict[str, Any]]:
        self.last_error = None
        if not self.enabled:
            self.last_error = "not_configured"
            return None
        body = json.dumps(self._payload(system, user), ensure_ascii=False).encode()
        # A single retry for transient connection aborts/resets. These happen in
        # practice (proxies, keep-alive races, Windows WinError 10053) and are
        # safe to retry because the request was never processed. Timeouts and
        # HTTP error statuses are NOT retried: the server may have acted on them,
        # and retrying would double the latency the caller asked us to bound.
        for attempt in (0, 1):
            request = urllib.request.Request(
                self.base_url, data=body, method="POST",
                headers={"Content-Type": "application/json", "Accept": "application/json"})
            if self.api_key:
                request.add_header("Authorization", f"Bearer {self.api_key}")
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    raw = json.loads(response.read().decode("utf-8"))
                result = self._normalise(self._content(raw, self.style), schema_fields) if isinstance(raw, dict) else None
                if result is None:
                    self.last_error = "invalid_json_result"
                return result
            except urllib.error.HTTPError as exc:
                self.last_error = f"http_{exc.code}"
                return None
            except (TimeoutError, socket.timeout):
                self.last_error = "connection_failed"
                return None
            except (ConnectionResetError, ConnectionAbortedError) as exc:
                self.last_error = "connection_aborted"
                if attempt == 0:
                    continue
                return None
            except urllib.error.URLError as exc:
                # URLError wraps the underlying socket error; retry transient aborts.
                reason = getattr(exc, "reason", None)
                if attempt == 0 and isinstance(reason, (ConnectionResetError, ConnectionAbortedError)):
                    self.last_error = "connection_aborted"
                    continue
                self.last_error = "connection_failed"
                return None
            except (OSError, UnicodeDecodeError, TypeError, ValueError, json.JSONDecodeError):
                self.last_error = "invalid_response"
                return None
        return None

    def complete_json(self, system: str, user: str, schema_fields: Optional[tuple] = None) -> Optional[Dict[str, Any]]:
        """Request a JSON object from the model.

        ``schema_fields`` lets callers other than the patch pipeline (project
        discovery, issue digests) declare their own expected keys.
        """
        return self._request(system, user, schema_fields)

    def test_connection(self) -> Dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "configured": False, "error": "not_configured",
                    "message": "尚未配置模型服务"}
        result = self._request('Return only JSON: {"warnings":["connection ok"]}.', "Reply with that JSON object.")
        if result is None:
            code = self.last_error or "request_failed"
            return {"ok": False, "configured": True, "error": code, "message": self._test_error_message(code)}
        return {"ok": True, "configured": True, "model": self.model}

    @staticmethod
    def _test_error_message(code: str) -> str:
        if code.startswith("http_"):
            return f"模型服务返回了错误（HTTP {code[5:]}），请检查接口地址、模型名称与 API Key"
        return {
            "invalid_json_result": "模型返回的内容无法解析，请检查接口协议（Chat Completions / Responses）是否选对",
            "connection_failed": "无法连接到模型服务，请检查接口地址与网络",
            "connection_aborted": "连接被中断，请稍后重试或检查网络",
            "invalid_response": "模型服务返回了无法识别的响应",
        }.get(code, "连接失败，请检查配置")


_MODEL_STORE_ENV = "OSG_MODEL_STORE"


def model_store_path() -> Path:
    """Where the UI-saved model configuration lives (never committed to git)."""
    override = os.getenv(_MODEL_STORE_ENV, "").strip()
    if override:
        return Path(override)
    return Path.home() / ".opensourceguard" / "model.json"


def load_model_config() -> Dict[str, str]:
    """Read the UI-saved model configuration; invalid files fail closed."""
    try:
        raw = model_store_path().read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        "base_url": str(data.get("base_url", "") or ""),
        "model": str(data.get("model", "") or ""),
        "api_key": str(data.get("api_key", "") or ""),
        "api_style": str(data.get("api_style", "auto") or "auto"),
    }


def save_model_config(config: Dict[str, Any]) -> Path:
    """Persist the configuration atomically with owner-only permissions."""
    path = model_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "base_url": str(config.get("base_url", "") or ""),
        "model": str(config.get("model", "") or ""),
        "api_key": str(config.get("api_key", "") or ""),
        "api_style": str(config.get("api_style", "auto") or "auto"),
    }
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(body, encoding="utf-8")
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    try:
        os.replace(temporary, path)
    except OSError:
        # Rename can be blocked by sandboxes/AV even when plain writes are
        # allowed; fall back to a direct write and clean up the temp file.
        try:
            path.write_text(body, encoding="utf-8")
        finally:
            temporary.unlink(missing_ok=True)
    return path


def clear_model_config() -> None:
    try:
        model_store_path().unlink()
    except OSError:
        pass


def client_from_config(config: Optional[Dict[str, Any]] = None) -> "ModelClient":
    """Build a client from the UI-saved config, falling back to env vars."""
    stored = load_model_config() if config is None else dict(config or {})
    if stored.get("base_url") or stored.get("model"):
        return ModelClient(
            base_url=str(stored.get("base_url", "")),
            model=str(stored.get("model", "")),
            api_key=str(stored.get("api_key", "")),
            api_style=str(stored.get("api_style", "auto")),
        )
    return ModelClient()
