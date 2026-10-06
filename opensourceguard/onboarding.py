from __future__ import annotations

import subprocess
import html
import re
from pathlib import Path
from urllib.parse import urlparse
from typing import Any, Dict, Optional

from .compliance import detect_project_license
from .contributing import build_contributor_guide
from .languages import is_test_path


EXTENSIONS = {
    ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript", ".go": "Go",
    ".rs": "Rust", ".java": "Java", ".cpp": "C++", ".c": "C",
    ".md": "Markdown", ".ipynb": "Jupyter",
}


def _git(repo: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args], cwd=repo, capture_output=True, text=True,
            timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def inspect_project(repo: Path) -> Dict[str, Any]:
    repo = repo.resolve()
    if not repo.is_dir():
        raise ValueError("项目目录不存在")
    files = []
    language_counts: Dict[str, int] = {}
    for path in repo.rglob("*"):
        if not path.is_file() or any(part in {".git", ".venv", "venv", "__pycache__", "node_modules"} for part in path.parts):
            continue
        files.append(path)
        language = EXTENSIONS.get(path.suffix.lower())
        if language:
            language_counts[language] = language_counts.get(language, 0) + 1
    language = max(language_counts, key=language_counts.get) if language_counts else "Unknown"
    readme = next((name for name in ("README.md", "README.rst", "README.txt") if (repo / name).exists()), "")
    license_file = next((name for name in ("LICENSE", "LICENSE.md", "LICENSE.txt") if (repo / name).exists()), "")
    # Detect tests so the contributor guide can adapt its advice.
    has_tests = any((repo / name).is_dir() for name in ("tests", "test", "spec", "__tests__")) or any(
        is_test_path(str(path.relative_to(repo)).replace("\\", "/")) for path in files[:500]
    )
    return {
        "path": str(repo),
        "name": repo.name,
        "file_count": len(files),
        "languages": dict(sorted(language_counts.items(), key=lambda item: (-item[1], item[0]))),
        "primary_language": language,
        "has_git": (repo / ".git").exists(),
        "has_readme": bool(readme),
        "readme_file": readme,
        "has_license": bool(license_file),
        "license_file": license_file,
        "has_tests": has_tests,
        "has_contributing": (repo / "CONTRIBUTING.md").exists(),
        "has_ci": (repo / ".github" / "workflows").is_dir() or (repo / ".gitee" / "workflows").is_dir(),
        "remote": _git(repo, "config", "--get", "remote.origin.url"),
        "branch": _git(repo, "branch", "--show-current"),
    }


def _clone_url(username: str, slug: str, platform: str) -> str:
    username = username.strip() or "YOUR_USERNAME"
    if platform.lower() == "gitee":
        return f"https://gitee.com/{username}/{slug}.git"
    return f"https://github.com/{username}/{slug}.git"


def _project_readme(name: str, language: str, homepage: str, description: str = "") -> str:
    link = f"\n项目主页：{homepage}\n" if homepage else ""
    return f"""# {name}

{description or f'一个使用 {language} 构建的开源项目。'}

## 解决什么问题

用一两句话说明用户遇到的痛点，以及这个项目带来的结果。

## 快速开始

~~~text
在这里写安装、配置和最小运行示例。
~~~

## 功能

- 功能一：说明实际效果
- 功能二：说明适用场景

## 贡献

欢迎提交 Issue 和 Pull Request。请先阅读 CONTRIBUTING.md，并在提交前运行测试。

## 许可证

建议选择一份明确的开源许可证，例如 Apache-2.0 或 MIT。
{link}"""


def _site_card(name: str, description: str, repo_url: str, homepage: str) -> Dict[str, str]:
    description = description or "一个面向真实用户的开源项目。"
    markdown = f"- [{name}]({repo_url})：{description}"
    card_html = f'<article class="project-card"><h3><a href="{html.escape(repo_url, quote=True)}">{html.escape(name)}</a></h3><p>{html.escape(description)}</p></article>'
    if homepage:
        card_html += f'\n<a href="{html.escape(homepage, quote=True)}">项目主页</a>'
    return {"markdown": markdown, "html": card_html}


def build_onboarding(
    repo: Path,
    username: str = "",
    platform: str = "github",
    project_name: Optional[str] = None,
    description: str = "",
    homepage: str = "",
) -> Dict[str, Any]:
    info = inspect_project(repo)
    slug = (project_name or info["name"]).strip().lower().replace(" ", "-")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,99}", slug):
        raise ValueError("项目名请使用英文字母、数字、短横线或下划线，并以字母或数字开头")
    username = username.strip()
    if username and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", username):
        raise ValueError("平台用户名格式无效")
    platform = platform.lower()
    if platform not in {"github", "gitee"}:
        raise ValueError("平台必须是 github 或 gitee")
    if homepage:
        url = urlparse(homepage)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
            raise ValueError("个人网站必须是有效的 http(s) 链接")
    clone_url = _clone_url(username, slug, platform)
    web_url = clone_url[:-4] if clone_url.endswith(".git") else clone_url
    readme = _project_readme(project_name or info["name"], info["primary_language"], homepage, description)
    checklist = [
        {
            "id": "identity",
            "title": "配置 Git 身份",
            "why": "提交记录需要显示作者，团队协作和作品证明都依赖这一步。",
            "commands": [
                'git config --global user.name "你的姓名"',
                'git config --global user.email "你的邮箱"',
                "git config --global --list",
            ],
        },
        {
            "id": "local",
            "title": "整理本地仓库",
            "why": "先用 .gitignore 排除密钥、缓存、虚拟环境和构建产物。",
            "commands": [
                "git init",
                "git status",
                "git add .",
                'git commit -m "chore: initial open-source release"',
                "git branch -M main",
            ],
        },
        {
            "id": "remote",
            "title": f"上传到 {platform.title()}",
            "why": "先在平台创建同名空仓库，再绑定远程地址并推送。",
            "commands": [
                f"git remote add origin {clone_url}",
                "git remote -v",
                "git push -u origin main",
            ],
        },
        {
            "id": "quality",
            "title": "让别人敢于使用",
            "why": "README、许可证、测试和 CI 是开源项目的信任基础。",
            "commands": [
                "补充 README.md、LICENSE 和 CONTRIBUTING.md",
                "添加最小可运行示例和测试命令",
                "配置 CI：每次提交自动运行测试",
            ],
        },
        {
            "id": "portfolio",
            "title": "放进个人网站",
            "why": "把仓库变成可展示的项目案例，说明问题、效果和你的贡献。",
            "commands": [
                "复制下面生成的项目卡片到个人网站项目列表",
                "增加 Demo、截图、评测指标和线上链接",
                "在简历中写清你的角色、技术和可量化结果",
            ],
        },
    ]
    # Existing branches and remotes belong to the user: adapt rather than rename/overwrite.
    if info["has_git"]:
        checklist[1]["commands"] = ["git status", "git diff", "git add .", 'git commit -m "chore: prepare release"']
        checklist[2]["commands"] = ([f"git remote add origin {clone_url}"] if not info["remote"] else []) + ["git remote -v", "git push -u origin HEAD"]
        if info["remote"]:
            checklist[2]["why"] = "已有 origin；请核对 git remote -v 的目标。本指南保留原远程和当前分支，推送到原仓库。"
    if not username and not info["remote"]:
        checklist[2]["why"] = "当前是待补全指南：先填写真实平台用户名，再在平台创建同名空仓库。YOUR_USERNAME 是占位符，不能原样使用。"
    checklist[1]["why"] += " 暂存前检查 git diff；首次推送前补全 README 和许可证，并安装项目依赖。"
    mistakes = [
        "不要把 API Key、.env、模型凭据或个人隐私文件提交到仓库。",
        "不要直接上传 node_modules、.venv、__pycache__ 和大模型权重。",
        "第一次推送遇到分支名不一致时，先执行 git branch -M main。",
        "README 要让陌生人从零开始跑通，而不是只介绍项目名称。",
    ]
    repo_card = _site_card(project_name or info["name"], description, web_url, homepage)
    license_id = detect_project_license(repo)[0]
    contributor_guide = build_contributor_guide(
        info, username=username, platform=platform, slug=slug, clone_url=clone_url,
        license_id=license_id, description=description, homepage=homepage,
    )
    return {
        "project": info,
        "repository": {"slug": slug, "platform": platform, "clone_url": clone_url, "web_url": web_url},
        "needs_username": not username and not bool(info["remote"]),
        "checklist": checklist,
        "common_mistakes": mistakes,
        "readme_template": readme,
        "website_card": repo_card,
        "detected_license": license_id,
        "contributor_guide": contributor_guide,
        "next_step": "完成 Git 身份配置后，执行本页第二组命令；不要把密钥写进命令或仓库。",
    }
