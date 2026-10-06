from __future__ import annotations

"""Optional ModelScope Hub publishing support.

Preparation is dependency-free and read-only. The actual upload is opt-in and
uses the official ``modelscope`` SDK when it is installed in the service
environment. Credentials are read from ``OSG_MODELSCOPE_TOKEN`` only.
"""

import importlib.util
import inspect
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional


MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}/[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", ".pytest_cache", "artifacts", "dist", "build"}
SECRET_NAMES = {".env", ".env.local", ".env.production", "id_rsa", "credentials.json"}
SECRET_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}
MAX_FILES = 5000
MAX_BYTES = 2 * 1024 * 1024 * 1024


def _token() -> str:
    return os.getenv("OSG_MODELSCOPE_TOKEN", "").strip()


def sdk_available() -> bool:
    return importlib.util.find_spec("modelscope") is not None


def status() -> Dict[str, Any]:
    return {
        "configured": bool(_token()),
        "sdk_available": sdk_available(),
        "ready": bool(_token()) and sdk_available(),
        "endpoint": os.getenv("OSG_MODELSCOPE_ENDPOINT", "https://www.modelscope.cn"),
        "token_configured": bool(_token()),
        "upload_mode": "official_sdk" if sdk_available() else "sdk_required",
    }


def _iter_files(repo: Path) -> Iterable[Path]:
    for root, dirs, files in os.walk(repo):
        root_path = Path(root)
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not (root_path / d).is_symlink())
        for name in sorted(files):
            path = root_path / name
            if path.is_symlink():
                continue
            yield path


def _is_secret(path: Path) -> bool:
    return path.name in SECRET_NAMES or path.suffix.lower() in SECRET_SUFFIXES or path.name.startswith(".env")


def prepare(repo: Path, model_id: str, kind: str = "model", visibility: str = "public", description: str = "") -> Dict[str, Any]:
    repo = repo.resolve()
    model_id = model_id.strip()
    kind = kind.strip().lower()
    visibility = visibility.strip().lower()
    if not repo.is_dir():
        raise ValueError("项目目录不存在")
    if not MODEL_ID_RE.fullmatch(model_id):
        raise ValueError("ModelScope 项目 ID 应为 namespace/name，例如 yourname/my-model")
    if kind not in {"model", "dataset", "space"}:
        raise ValueError("类型必须是 model 或 dataset")
    if visibility not in {"public", "private"}:
        raise ValueError("可见性必须是 public 或 private")
    upload_repo = repo / "space" if kind == "space" and (repo / "space").is_dir() else repo
    files: List[Dict[str, Any]] = []
    blocked: List[str] = []
    total = 0
    for path in _iter_files(upload_repo):
        rel = path.relative_to(upload_repo).as_posix()
        size = path.stat().st_size
        if _is_secret(path):
            blocked.append(rel)
            continue
        total += size
        files.append({"path": rel, "size": size})
        if len(files) > MAX_FILES or total > MAX_BYTES:
            raise ValueError("上传内容超过 5000 个文件或 2 GB 限制，请先精简项目")
    _default_desc = "OpenSourceGuard \u751f\u6210\u7684\u5f00\u6e90\u9879\u76ee\u3002"
    return {
        "platform": "modelscope", "model_id": model_id, "kind": kind, "visibility": visibility,
        "repo": str(upload_repo), "source_repo": str(repo), "files": files, "file_count": len(files), "total_bytes": total,
        "blocked_files": blocked, "safe_to_upload": not blocked,
        "description": description.strip()[:1000], "sdk_available": sdk_available(),
        "token_configured": bool(_token()), "approval_required": True,
        "readme_hint": f"# {model_id.split('/', 1)[-1]}\n\n{description.strip() or _default_desc}\n\n## README \u53d1\u5e03\u8bf4\u660e\n\n\u6b64\u9879\u76ee\u901a\u8fc7 OpenSourceGuard \u53d1\u5e03\u5230 ModelScope\u3002",
    }


def _call(method: Any, positional: tuple = (), **kwargs: Any) -> Any:
    """Call SDK methods while tolerating minor SDK signature differences."""
    try:
        signature = inspect.signature(method)
        accepts_any = any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values())
        accepted = dict(kwargs) if accepts_any else {key: value for key, value in kwargs.items() if key in signature.parameters}
    except (TypeError, ValueError):
        accepted = kwargs
    try:
        return method(*positional, **accepted)
    except TypeError:
        if positional:
            return method(**accepted)
        raise


def publish(repo: Path, model_id: str, kind: str = "model", visibility: str = "public",
            description: str = "", confirm: bool = False) -> Dict[str, Any]:
    if not confirm:
        return {"ok": False, "requires_confirmation": True, "message": "请确认后才会上传到 ModelScope。"}
    if not _token():
        return {"ok": False, "error": "token_missing", "message": "\u5c1a\u672a\u914d\u7f6e ModelScope Token\uff08\u4ec5\u4ece\u670d\u52a1\u7aef\u73af\u5883\u53d8\u91cf\u8bfb\u53d6\uff09\u3002"}
    if not sdk_available():
        return {"ok": False, "error": "sdk_missing", "message": "当前环境未安装 ModelScope SDK。请先安装 modelscope，再重新启动本地服务。", "install_command": "pip install modelscope"}
    prepared = prepare(repo, model_id, kind, visibility, description)
    if prepared["blocked_files"]:
        return {"ok": False, "error": "secret_files", "message": "检测到疑似凭据文件，已停止上传。", "blocked_files": prepared["blocked_files"]}
    try:
        from modelscope.hub.api import HubApi  # type: ignore
        try:
            api = _call(HubApi, (), token=_token(), endpoint=os.getenv("OSG_MODELSCOPE_ENDPOINT", "").strip() or None)
        except TypeError:
            api = HubApi()
        login = getattr(api, "login", None)
        if login is not None:
            try:
                _call(login, (_token(),))
            except TypeError:
                _call(login, access_token=_token())
        create = getattr(api, "create_repo" if kind == "space" else ("create_dataset" if kind == "dataset" else "create_model"), None)
        if create is None:
            create = getattr(api, "create_repo", None)
        push = getattr(api, "push_dataset" if kind == "dataset" else "push_model", None)
        upload_folder = getattr(api, "upload_folder", None)
        if create is None or (push is None and upload_folder is None):
            return {"ok": False, "error": "sdk_method_missing", "message": "ModelScope SDK \u7f3a\u5c11\u6240\u9700\u4e0a\u4f20\u63a5\u53e3\uff0c\u8bf7\u5347\u7ea7 SDK\u3002"}
        try:
            if kind == "space" or getattr(create, "__name__", "") == "create_repo":
                _call(create, (model_id,), repo_type="studio" if kind == "space" else kind, visibility=visibility, description=description[:1000])
            else:
                _call(create, (model_id,), visibility=visibility, description=description[:1000])
        except Exception as exc:
            # Existing repositories can still receive a new upload. Only hide
            # the create error; push errors remain visible as a failure.
            if "exist" not in str(exc).lower() and "已存在" not in str(exc):
                return {"ok": False, "error": "create_failed", "message": "ModelScope 项目创建失败，请检查命名空间和权限。"}
        if upload_folder is not None:
            _call(upload_folder, (), repo_id=model_id, folder_path=str(Path(prepared["repo"]).resolve()), repo_type="studio" if kind == "space" else kind)
        else:
            _call(push, (model_id, str(Path(prepared["repo"]).resolve())))
        return {"ok": True, "platform": "modelscope", "model_id": model_id, "kind": kind,
                "visibility": visibility, "url": f"https://modelscope.cn/{'studios' if kind == 'space' else kind + 's'}/{model_id}",
                "file_count": prepared["file_count"], "message": "已上传到 ModelScope。"}
    except Exception as exc:
        return {"ok": False, "error": "upload_failed", "message": "ModelScope 上传失败，请检查网络、Token 和仓库权限。", "detail_type": type(exc).__name__}
