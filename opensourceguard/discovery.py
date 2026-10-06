"""Find the user's own projects on this machine by natural language.

The goal is to remove the "where did I put that project" step. The user types
something like "我那个用 Python 写的爬虫" and gets a ranked list of real local
repositories, without ever typing a path.

Safety boundaries, by design:
* Only well-known code locations are scanned, never the whole filesystem.
* Credential, system and package directories are skipped outright.
* Scanning is depth- and time-bounded so the UI never hangs.
* Nothing is ever written, moved or executed. This module only reads metadata.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .languages import LANGUAGE_BY_SUFFIX, language_label

# Directories that must never be walked: credentials, system files, caches,
# and dependency trees that would dominate the scan budget.
BLOCKED_NAMES = {
    ".ssh", ".gnupg", ".aws", ".azure", ".kube", ".docker", ".password-store",
    "AppData", "Application Data", "Library", "System", "System32", "Windows",
    "Program Files", "Program Files (x86)", "ProgramData", "$Recycle.Bin",
    "node_modules", ".venv", "venv", "env", "__pycache__", ".git", ".svn",
    "site-packages", "dist-packages", "vendor", "target", "build", "dist",
    ".gradle", ".m2", ".cargo", ".rustup", ".nuget", ".npm", ".yarn", ".pnpm",
    ".cache", ".local", ".config", "Cache", "Caches", "Temp", "tmp",
    "OneDriveTemp", ".Trash", ".idea", ".vscode-server",
}

# Files that identify a directory as a real project root.
PROJECT_MARKERS = {
    ".git": ("git", "Git 仓库"),
    "package.json": ("npm", "Node.js 项目"),
    "pyproject.toml": ("python", "Python 项目"),
    "setup.py": ("python", "Python 项目"),
    "requirements.txt": ("python", "Python 项目"),
    "go.mod": ("go", "Go 模块"),
    "Cargo.toml": ("rust", "Rust crate"),
    "pom.xml": ("maven", "Java Maven 项目"),
    "build.gradle": ("gradle", "Java/Kotlin Gradle 项目"),
    "composer.json": ("php", "PHP 项目"),
    "Gemfile": ("ruby", "Ruby 项目"),
    "CMakeLists.txt": ("cmake", "C/C++ 项目"),
    "Makefile": ("make", "Make 项目"),
    "index.html": ("web", "网页项目"),
    "Dockerfile": ("docker", "容器化项目"),
}

# Common places developers actually keep code, relative to the home directory.
HOME_CANDIDATES = (
    "Documents", "Desktop", "Projects", "projects", "Code", "code", "src",
    "workspace", "Workspace", "dev", "Dev", "repos", "Repos", "git", "GitHub",
    "OneDrive/Documents", "OneDrive/Desktop", "源代码", "代码", "项目",
)

# Developers commonly nest projects a few levels deep (Documents/Code/2026/foo),
# so the default depth must be generous enough to reach them.
MAX_DEPTH = 7
MAX_PROJECTS = 200
DEFAULT_TIME_BUDGET = 8.0


@dataclass
class LocalProject:
    """A project discovered on this machine."""

    path: str
    name: str
    kinds: List[str] = field(default_factory=list)
    kind_labels: List[str] = field(default_factory=list)
    languages: Dict[str, int] = field(default_factory=dict)
    primary_language: str = ""
    has_git: bool = False
    has_readme: bool = False
    has_tests: bool = False
    readme_excerpt: str = ""
    file_count: int = 0
    modified_at: float = 0.0
    modified_text: str = ""
    remote: str = ""
    score: float = 0.0
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _is_blocked(name: str) -> bool:
    return name in BLOCKED_NAMES or name.startswith(".") and name not in {".git"}


def search_roots(extra: Optional[Iterable[str]] = None) -> List[Path]:
    """Return the directories that will actually be scanned."""
    roots: List[Path] = []
    seen = set()

    def add(path: Path) -> None:
        try:
            resolved = path.resolve()
        except (OSError, ValueError):
            return
        key = str(resolved).lower()
        if key not in seen and resolved.is_dir():
            seen.add(key)
            roots.append(resolved)

    for raw in extra or []:
        if raw and str(raw).strip():
            add(Path(str(raw).strip()))

    configured = os.getenv("OSG_PROJECT_ROOTS", "")
    for part in configured.split(os.pathsep):
        if part.strip():
            add(Path(part.strip()))

    home = Path.home()
    for relative in HOME_CANDIDATES:
        add(home / relative)
    return roots


def _read_head(path: Path, limit: int = 600) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def _git_remote(project: Path) -> str:
    config = project / ".git" / "config"
    if not config.is_file():
        return ""
    text = _read_head(config, 4000)
    match = re.search(r"url\s*=\s*(\S+)", text)
    return match.group(1) if match else ""


def _relative_time(timestamp: float) -> str:
    if not timestamp:
        return ""
    delta = time.time() - timestamp
    if delta < 3600:
        return "1 小时内"
    if delta < 86400:
        return f"{int(delta // 3600)} 小时前"
    days = int(delta // 86400)
    if days < 30:
        return f"{days} 天前"
    if days < 365:
        return f"{days // 30} 个月前"
    return f"{days // 365} 年前"


def _inspect(project: Path) -> Optional[LocalProject]:
    """Collect lightweight metadata for one candidate project directory."""
    kinds, labels = [], []
    for marker, (kind, label) in PROJECT_MARKERS.items():
        if (project / marker).exists():
            if kind not in kinds:
                kinds.append(kind)
                labels.append(label)
    if not kinds:
        return None

    languages: Dict[str, int] = {}
    file_count = 0
    newest = 0.0
    has_tests = False
    try:
        for entry in project.rglob("*"):
            if file_count > 4000:
                break
            parts = entry.relative_to(project).parts
            if any(part in BLOCKED_NAMES for part in parts):
                continue
            if not entry.is_file():
                continue
            file_count += 1
            language = LANGUAGE_BY_SUFFIX.get(entry.suffix.lower())
            if language:
                languages[language] = languages.get(language, 0) + 1
            lowered = entry.name.lower()
            if lowered.startswith("test") or "_test." in lowered or ".test." in lowered or ".spec." in lowered:
                has_tests = True
            try:
                stamp = entry.stat().st_mtime
                newest = max(newest, stamp)
            except OSError:
                continue
    except (OSError, ValueError):
        pass

    if not languages and "git" not in kinds:
        return None

    readme = next((project / name for name in ("README.md", "README.rst", "README.txt", "readme.md")
                   if (project / name).is_file()), None)
    excerpt = ""
    if readme is not None:
        raw = _read_head(readme, 900)
        lines = [line.strip() for line in raw.splitlines()
                 if line.strip() and not line.strip().startswith(("#", "!", "[!", "---", "```"))]
        excerpt = " ".join(lines)[:260]

    ordered = dict(sorted(languages.items(), key=lambda item: (-item[1], item[0])))
    return LocalProject(
        path=str(project),
        name=project.name,
        kinds=kinds,
        kind_labels=labels,
        languages=ordered,
        primary_language=next(iter(ordered), ""),
        has_git=(project / ".git").exists(),
        has_readme=readme is not None,
        has_tests=has_tests,
        readme_excerpt=excerpt,
        file_count=file_count,
        modified_at=newest,
        modified_text=_relative_time(newest),
        remote=_git_remote(project),
    )


def scan(roots: Optional[Iterable[str]] = None, time_budget: float = DEFAULT_TIME_BUDGET,
         limit: int = MAX_PROJECTS) -> Dict[str, Any]:
    """Walk the known code locations and collect project metadata."""
    started = time.time()
    found: List[LocalProject] = []
    scanned_roots: List[str] = []
    truncated = False

    for root in search_roots(roots):
        scanned_roots.append(str(root))
        stack = [(root, 0)]
        while stack:
            if time.time() - started > time_budget or len(found) >= limit:
                truncated = True
                break
            directory, depth = stack.pop()
            try:
                entries = list(directory.iterdir())
            except (OSError, PermissionError):
                continue
            project = _inspect(directory)
            if project is not None:
                found.append(project)
                # A project root is a leaf: do not descend into sub-packages.
                continue
            if depth >= MAX_DEPTH:
                continue
            for entry in entries:
                try:
                    if entry.is_dir() and not entry.is_symlink() and not _is_blocked(entry.name):
                        stack.append((entry, depth + 1))
                except OSError:
                    continue
        if truncated:
            break

    found.sort(key=lambda item: -item.modified_at)
    return {
        "projects": [item.to_dict() for item in found],
        "roots": scanned_roots,
        "truncated": truncated,
        "elapsed_seconds": round(time.time() - started, 2),
        "count": len(found),
    }


# --------------------------------------------------------------------------
# Natural-language matching
# --------------------------------------------------------------------------

# Words users say that map onto a language id.
LANGUAGE_HINTS = {
    "python": "python", "py": "python", "django": "python", "flask": "python",
    "爬虫": "python", "数据分析": "python", "机器学习": "python", "深度学习": "python",
    "javascript": "javascript", "js": "javascript", "node": "javascript",
    "react": "javascript", "vue": "javascript", "前端": "javascript", "网页": "javascript",
    "typescript": "typescript", "ts": "typescript",
    "java": "java", "springboot": "java", "spring": "java", "安卓": "java", "android": "java",
    "go": "go", "golang": "go",
    "rust": "rust", "c++": "cpp", "cpp": "cpp", "c语言": "c",
    "php": "php", "ruby": "ruby", "swift": "swift", "kotlin": "kotlin",
    "shell": "shell", "脚本": "shell",
}

# Words that describe a project purpose; matched against name and README.
PURPOSE_HINTS = {
    "爬虫": ("crawler", "spider", "scrapy", "爬虫", "抓取"),
    "网站": ("web", "site", "website", "网站", "主页"),
    "博客": ("blog", "博客"),
    "接口": ("api", "server", "backend", "接口", "服务端"),
    "后端": ("api", "server", "backend", "服务端"),
    "前端": ("frontend", "ui", "web", "前端", "界面"),
    "游戏": ("game", "游戏"),
    "工具": ("tool", "util", "cli", "工具"),
    "机器人": ("bot", "robot", "agent", "机器人"),
    "数据": ("data", "dataset", "analysis", "数据"),
    "算法": ("algorithm", "leetcode", "算法"),
    "作业": ("homework", "assignment", "课程", "作业", "实验"),
    "毕设": ("graduation", "thesis", "毕设", "毕业设计"),
    "比赛": ("contest", "competition", "比赛", "竞赛"),
    "agent": ("agent", "llm", "ai", "gpt", "智能体"),
}

STOP_TOKENS = {
    "我", "的", "那个", "一个", "项目", "写的", "用", "是", "在", "有", "找", "帮",
    "就是", "之前", "以前", "上次", "这个", "里面", "关于", "想", "要", "看看",
    "my", "the", "a", "an", "project", "that", "one", "find", "with", "for",
}


def _tokenize(query: str) -> List[str]:
    lowered = query.lower()
    tokens = re.findall(r"[a-z_][a-z0-9_+#-]{1,}|[\u4e00-\u9fff]{2,}", lowered)
    result = []
    for token in tokens:
        if token in STOP_TOKENS or len(token) < 2:
            continue
        if token not in result:
            result.append(token)
    return result


def rank(projects: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
    """Score projects against a natural-language query using local rules."""
    if not query.strip():
        for project in projects:
            project["score"] = 0.0
            project["reasons"] = []
        return projects

    tokens = _tokenize(query)
    lowered_query = query.lower()
    wanted_languages = {
        language for hint, language in LANGUAGE_HINTS.items() if hint in lowered_query
    }

    for project in projects:
        score = 0.0
        reasons: List[str] = []
        name = str(project.get("name", "")).lower()
        path = str(project.get("path", "")).lower()
        excerpt = str(project.get("readme_excerpt", "")).lower()
        languages = project.get("languages") or {}

        for token in tokens:
            if token in name:
                score += 28
                reasons.append(f"项目名包含「{token}」")
            elif token in path:
                score += 10
                reasons.append(f"路径包含「{token}」")
            if token in excerpt:
                score += 12
                reasons.append(f"README 提到「{token}」")

        for language in wanted_languages:
            if language in languages:
                share = languages[language] / max(1, sum(languages.values()))
                score += 25 * min(1.0, share * 2)
                reasons.append(f"主要使用 {language_label(language)}")

        for keyword, needles in PURPOSE_HINTS.items():
            if keyword not in lowered_query:
                continue
            haystack = f"{name} {path} {excerpt}"
            if any(needle in haystack for needle in needles):
                score += 18
                reasons.append(f"内容与「{keyword}」相关")

        # Recently touched projects are much more likely to be the one meant.
        modified = project.get("modified_at") or 0
        if modified:
            age_days = max(0.0, (time.time() - modified) / 86400)
            score += max(0.0, 12 - age_days / 10)

        if project.get("has_git"):
            score += 4
        if project.get("has_readme"):
            score += 3

        project["score"] = round(score, 2)
        # Keep reasons short and unique for the UI.
        deduped = []
        for reason in reasons:
            if reason not in deduped:
                deduped.append(reason)
        project["reasons"] = deduped[:4]

    projects.sort(key=lambda item: (-float(item.get("score") or 0), -(item.get("modified_at") or 0)))
    return projects


def _model_rerank(projects: List[Dict[str, Any]], query: str, model: Any) -> Optional[List[Dict[str, Any]]]:
    """Ask the model to pick the projects that match the user's description.

    Only compact metadata is sent: name, languages, a short README excerpt and
    when it was last touched. No source code and no absolute paths leave the
    machine beyond the project folder name.
    """
    if model is None or not getattr(model, "enabled", False) or not projects:
        return None
    candidates = projects[:25]
    listing = []
    for index, project in enumerate(candidates):
        languages = ", ".join(list((project.get("languages") or {}).keys())[:3])
        listing.append(
            f"[{index}] 名称={project.get('name')} 语言={languages or '未知'} "
            f"最近修改={project.get('modified_text') or '未知'} "
            f"简介={(project.get('readme_excerpt') or '')[:120]}"
        )
    result = model.complete_json(
        "你在帮用户从本机项目列表中找到他描述的那个项目。只输出 JSON，"
        '格式为 {"matches":[{"index":0,"confidence":0.0,"reason":"简短中文理由"}]}。'
        "confidence 取 0 到 1。只返回真正相关的项目，最多 8 个；没有匹配就返回空数组。"
        "不要编造列表中不存在的索引。",
        f"用户的描述：{query}\n\n候选项目：\n" + "\n".join(listing),
        schema_fields=("matches",),
    )
    if not result or not isinstance(result.get("matches"), list):
        return None

    ranked: List[Dict[str, Any]] = []
    for item in result["matches"]:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("index", -1))
            confidence = float(item.get("confidence", 0))
        except (TypeError, ValueError):
            continue
        if not 0 <= index < len(candidates):
            continue
        project = dict(candidates[index])
        project["score"] = round(max(0.0, min(1.0, confidence)) * 100, 2)
        reason = str(item.get("reason") or "").strip()
        project["reasons"] = [reason] if reason else project.get("reasons", [])
        project["matched_by"] = "model"
        ranked.append(project)
    return ranked or None


def find(query: str, roots: Optional[Iterable[str]] = None, model: Any = None,
         limit: int = 12, time_budget: float = DEFAULT_TIME_BUDGET) -> Dict[str, Any]:
    """Find local projects matching a natural-language description."""
    scan_result = scan(roots, time_budget=time_budget)
    projects = scan_result["projects"]

    mode = "rules"
    ranked = rank(list(projects), query)
    model_ranked = _model_rerank(ranked, query, model)
    if model_ranked:
        ranked = model_ranked
        mode = "model"
    else:
        for project in ranked:
            project.setdefault("matched_by", "rules")

    top = [project for project in ranked if not query.strip() or project.get("score", 0) > 0][:limit]
    if not top:
        top = ranked[:limit]

    notes = [
        "只扫描常见代码目录（文档、桌面、Projects、Code 等），不会遍历整个磁盘。",
        "凭据目录（.ssh/.aws/.gnupg 等）、系统目录和依赖目录一律跳过。",
        "只读取项目元信息，不读取也不上传源码内容。",
    ]
    if mode == "model":
        notes.append("模型只收到项目名、语言、最近修改时间和 README 摘要，不包含源码。")
    if scan_result["truncated"]:
        notes.append(f"扫描在 {scan_result['elapsed_seconds']} 秒后达到上限，可能还有项目未列出；"
                     "可用 OSG_PROJECT_ROOTS 指定更精确的目录。")

    return {
        "query": query,
        "mode": mode,
        "matches": top,
        "total_scanned": scan_result["count"],
        "roots": scan_result["roots"],
        "elapsed_seconds": scan_result["elapsed_seconds"],
        "truncated": scan_result["truncated"],
        "notes": notes,
    }
