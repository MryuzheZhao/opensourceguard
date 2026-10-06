"""Extra guidance for first-time contributors.

Extends the publishing walkthrough with the parts beginners most often miss:
a real first-PR workflow, a pre-submit self-review checklist, guidance on how to
pick a first issue, a personal-site portfolio entry, and README badges.

Everything here is generated text and templates. Nothing is executed, and no
command that changes remote state is run on the user's behalf.
"""
from __future__ import annotations

import html
import re
from typing import Any, Dict, List
from urllib.parse import quote, urlparse

# Search queries that reliably surface beginner-friendly issues on each platform.
GOOD_FIRST_ISSUE_LABELS = [
    "good first issue", "good-first-issue", "help wanted",
    "beginner friendly", "easy", "documentation", "up-for-grabs",
]


def first_pr_workflow(clone_url: str, platform: str, default_branch: str = "main") -> List[Dict[str, Any]]:
    """The fork -> branch -> commit -> PR loop, which differs from pushing your own repo."""
    platform_name = "Gitee" if platform == "gitee" else "GitHub"
    upstream = clone_url or "https://github.com/UPSTREAM_OWNER/PROJECT.git"
    return [
        {
            "id": "fork",
            "title": "1. Fork 上游仓库",
            "why": "你通常没有上游仓库的写权限，必须先复制一份到自己账号下。",
            "commands": [
                f"在 {platform_name} 页面点击 Fork 按钮",
                "Fork 完成后复制你自己账号下那份仓库的地址",
            ],
            "note": "注意：要 clone 你 Fork 出来的地址，不是上游地址。这是新手最常搞混的一步。",
        },
        {
            "id": "clone",
            "title": "2. Clone 并关联上游",
            "why": "origin 指向你的 Fork，upstream 指向原项目，这样才能同步别人的最新代码。",
            "commands": [
                "git clone https://<平台>/<你的用户名>/<项目名>.git",
                "cd <项目名>",
                f"git remote add upstream {upstream}",
                "git remote -v",
            ],
            "note": "git remote -v 应该看到 origin（你的）和 upstream（原项目）两个地址。",
        },
        {
            "id": "sync",
            "title": "3. 同步上游最新代码",
            "why": "从最新代码开始改，可以大幅减少后面的冲突。",
            "commands": [
                "git fetch upstream",
                f"git checkout {default_branch}",
                f"git merge upstream/{default_branch}",
            ],
            "note": "每次开始新工作前都做一次，养成习惯。",
        },
        {
            "id": "branch",
            "title": "4. 新建功能分支",
            "why": "不要直接在 main 上改。一个分支对应一个 PR，评审和回滚都更清晰。",
            "commands": [
                "git checkout -b fix/describe-your-change",
            ],
            "note": "分支名用英文短横线描述做了什么，例如 fix/empty-csv-crash。",
        },
        {
            "id": "commit",
            "title": "5. 小步提交",
            "why": "清晰的提交信息能让评审者快速理解你的思路。",
            "commands": [
                "git add <你改动的具体文件>",
                'git commit -m "fix: 空 CSV 输入时返回空列表"',
            ],
            "note": "尽量避免 git add .，那样容易把无关文件一起提交。"
                    "提交信息推荐 Conventional Commits：fix / feat / docs / test / refactor / chore。",
        },
        {
            "id": "push",
            "title": "6. 推送到你的 Fork",
            "why": "推送后平台才会出现创建 PR 的入口。",
            "commands": [
                "git push -u origin fix/describe-your-change",
            ],
            "note": "推送到 origin（你的 Fork），不是 upstream。",
        },
        {
            "id": "pr",
            "title": "7. 创建 Pull Request",
            "why": "PR 描述决定了维护者第一眼的印象，也决定了合并速度。",
            "commands": [
                "打开你的 Fork 页面，点击 Compare & pull request",
                "目标选择上游仓库的默认分支",
                "按下面的 PR 模板填写描述",
            ],
            "note": "如果项目有 CONTRIBUTING.md，先按它的要求写；仓库规范优先于通用建议。",
        },
        {
            "id": "review",
            "title": "8. 回应评审意见",
            "why": "被要求修改是正常流程，不代表你的贡献被否定。",
            "commands": [
                "在同一分支继续修改并提交",
                "git push（PR 会自动更新，不需要重新创建）",
                "回复每一条评论，说明你怎么改的或为什么不改",
            ],
            "note": "被要求 rebase 时：git fetch upstream && git rebase upstream/main，"
                    "解决冲突后用 git push --force-with-lease（比 --force 安全）。",
        },
    ]


def pre_submit_checklist(has_tests: bool, has_ci: bool, primary_language: str) -> List[Dict[str, Any]]:
    """Self-review items that prevent the most common PR rejections."""
    test_command = {
        "Python": "python -m pytest",
        "JavaScript": "npm test",
        "TypeScript": "npm test",
        "Go": "go test ./...",
        "Rust": "cargo test",
        "Java": "mvn test",
    }.get(primary_language, "项目约定的测试命令")

    items = [
        {
            "id": "scope",
            "title": "改动范围是否聚焦",
            "detail": "一个 PR 只做一件事。顺手做的格式化、重命名、依赖升级都应该拆成独立 PR。",
            "blocking": True,
        },
        {
            "id": "diff",
            "title": "是否逐行看过自己的 diff",
            "detail": "执行 git diff --staged，确认没有调试语句、注释掉的代码、无关空行和本地路径。",
            "blocking": True,
        },
        {
            "id": "secrets",
            "title": "是否包含凭据或隐私",
            "detail": "检查 .env、Token、密码、内网地址、真实用户数据。一旦推送到公开仓库就必须立刻轮换凭据。",
            "blocking": True,
        },
        {
            "id": "tests",
            "title": "是否补了测试",
            "detail": f"修 Bug 要加一个「修复前失败、修复后通过」的测试。运行：{test_command}",
            "blocking": True,
        },
        {
            "id": "existing-tests",
            "title": "原有测试是否仍然通过",
            "detail": f"跑全量测试而不只是你新加的那个：{test_command}",
            "blocking": True,
        },
        {
            "id": "style",
            "title": "是否遵循项目风格",
            "detail": "看项目有没有 .editorconfig、linter 配置或格式化脚本，按它们执行，不要按个人习惯改。",
            "blocking": False,
        },
        {
            "id": "docs",
            "title": "是否需要更新文档",
            "detail": "改了行为、参数或接口，就要同步 README、docstring 或使用说明。",
            "blocking": False,
        },
        {
            "id": "issue-link",
            "title": "是否关联了 Issue",
            "detail": "在 PR 描述中写 Fixes #123，合并时会自动关闭对应 Issue。",
            "blocking": False,
        },
    ]
    if not has_tests:
        items.insert(3, {
            "id": "no-tests-yet",
            "title": "项目还没有测试目录",
            "detail": "这是一个很好的首次贡献方向：为现有功能补第一个测试，风险低、价值高、容易被接受。",
            "blocking": False,
        })
    if not has_ci:
        items.append({
            "id": "no-ci",
            "title": "项目还没有 CI",
            "detail": "可以提议加一个最小 GitHub Actions 流程，让每次提交自动跑测试。",
            "blocking": False,
        })
    return items


def pr_description_template(project_name: str, language: str) -> str:
    """A PR description template that answers what maintainers actually ask."""
    return f"""## 这个 PR 做了什么

一句话说明改动内容。

关联 Issue：Fixes #<编号>

## 为什么需要这个改动

说明问题的实际影响：谁会遇到、在什么情况下出现、造成什么后果。

## 怎么改的

- 改动点一：说明修改的文件和思路
- 改动点二：如果有取舍，说明为什么选这个方案

## 如何验证

复现步骤：

```text
1. 执行 ...
2. 观察到 ...
```

测试结果：

```text
把测试命令和输出贴在这里（{language} 项目通常是测试框架的输出）
```

- [ ] 新增了能覆盖这个问题的测试
- [ ] 原有测试全部通过
- [ ] 没有引入新的依赖（如有，已在描述中说明原因）
- [ ] 没有提交凭据、临时文件或无关改动

## 补充说明

截图、性能数据、兼容性影响，或者你希望评审者重点看的地方。
"""


def issue_search_links(platform: str, language: str, keywords: str = "") -> List[Dict[str, str]]:
    """Ready-made search URLs for finding a suitable first issue."""
    language_query = language.lower() if language and language != "Unknown" else ""
    extra = f" {keywords.strip()}" if keywords.strip() else ""
    links: List[Dict[str, str]] = []

    if platform == "gitee":
        base = "https://gitee.com/explore"
        links.append({
            "label": "Gitee 探索页（按语言筛选）",
            "url": f"{base}?lang={quote(language_query)}" if language_query else base,
            "note": "Gitee 的 Issue 标签检索能力有限，建议先找活跃项目再看它的 Issue 列表。",
        })
        links.append({
            "label": "Gitee 搜索「新手任务」",
            "url": f"https://search.gitee.com/?skin=rec&type=repository&q={quote('新手任务' + extra)}",
            "note": "很多中文项目会用「新手任务」「新人友好」这类标签。",
        })
        return links

    for label in ("good first issue", "help wanted"):
        query = f'is:open is:issue label:"{label}" no:assignee'
        if language_query:
            query += f" language:{language_query}"
        query += extra
        links.append({
            "label": f'GitHub：{label}（{language_query or "全部语言"}，无人认领）',
            "url": f"https://github.com/issues?q={quote(query)}",
            "note": "no:assignee 过滤掉已被认领的，避免重复劳动。",
        })
    query = f"is:open is:issue label:documentation no:assignee{extra}"
    links.append({
        "label": "GitHub：文档类 Issue（最容易上手）",
        "url": f"https://github.com/issues?q={quote(query)}",
        "note": "文档改进不需要深入理解代码，是很好的第一个 PR。",
    })
    return links


def choose_first_issue_guide() -> List[Dict[str, str]]:
    """How to evaluate whether an issue is actually a good first contribution."""
    return [
        {
            "title": "先看项目是否还活着",
            "detail": "最近一个月有提交、有人回复 Issue。向已经停止维护的项目提 PR，很可能永远不会被合并。",
        },
        {
            "title": "确认 Issue 没有被认领",
            "detail": "看评论区有没有人说「我来做」。如果有，换一个；如果没有，可以先留言说明你准备开始。",
        },
        {
            "title": "选描述清楚的 Issue",
            "detail": "好的 Issue 会写清复现步骤和预期行为。描述含糊的先在评论里提问，不要直接猜着改。",
        },
        {
            "title": "从小处开始",
            "detail": "第一个 PR 的目标是走通流程，不是证明实力。修文档错别字、补一个测试、改一条报错信息都完全可以。",
        },
        {
            "title": "先读 CONTRIBUTING.md",
            "detail": "分支命名、提交格式、测试要求、是否需要签 CLA，都写在里面。不读它是被打回的常见原因。",
        },
        {
            "title": "留言时说清你的计划",
            "detail": "「我想处理这个 Issue，计划从 X 文件入手，预计本周提 PR」比「我可以做吗」更容易得到回应。",
        },
    ]


def readme_badges(username: str, slug: str, platform: str, license_id: str = "") -> Dict[str, Any]:
    """Generate README badge markdown. Badges are how a repo signals it is maintained."""
    safe_user = username.strip() or "YOUR_USERNAME"
    if platform == "gitee":
        repo_path = f"{safe_user}/{slug}"
        badges = [
            {"label": "Gitee star", "markdown": f"[![Gitee stars](https://gitee.com/{repo_path}/badge/star.svg?theme=dark)](https://gitee.com/{repo_path}/stargazers)"},
            {"label": "Gitee fork", "markdown": f"[![Gitee forks](https://gitee.com/{repo_path}/badge/fork.svg?theme=dark)](https://gitee.com/{repo_path}/members)"},
        ]
    else:
        repo_path = f"{safe_user}/{slug}"
        badges = [
            {"label": "CI 状态", "markdown": f"[![CI](https://github.com/{repo_path}/actions/workflows/ci.yml/badge.svg)](https://github.com/{repo_path}/actions/workflows/ci.yml)"},
            {"label": "Star 数", "markdown": f"[![Stars](https://img.shields.io/github/stars/{repo_path}?style=flat)](https://github.com/{repo_path}/stargazers)"},
            {"label": "最近提交", "markdown": f"[![Last commit](https://img.shields.io/github/last-commit/{repo_path})](https://github.com/{repo_path}/commits)"},
            {"label": "Issue 数", "markdown": f"[![Issues](https://img.shields.io/github/issues/{repo_path})](https://github.com/{repo_path}/issues)"},
        ]
    if license_id and license_id not in {"unknown", ""}:
        badges.append({
            "label": "许可证",
            "markdown": f"[![License](https://img.shields.io/badge/license-{quote(license_id)}-blue.svg)](./LICENSE)",
        })
    return {
        "badges": badges,
        "combined": " ".join(badge["markdown"] for badge in badges),
        "note": "把这一行放在 README 标题下面。徽章要真实反映状态——没有配置 CI 就不要放 CI 徽章。",
    }


def portfolio_entry(project_name: str, description: str, repo_url: str,
                    homepage: str, language: str, highlights: List[str]) -> Dict[str, str]:
    """A richer personal-site entry than a one-line link.

    Recruiters and judges look for: what problem, what you did, what result.
    """
    safe_name = html.escape(project_name)
    safe_desc = html.escape(description or f"一个使用 {language} 构建的开源项目。")
    safe_repo = html.escape(repo_url, quote=True)
    points = highlights or [
        "说明你解决的具体问题，而不是罗列技术栈",
        "写出可验证的结果：测试覆盖、性能提升、使用量或评测指标",
        "说明你在项目中的具体角色和负责的模块",
    ]

    list_items = "\n".join(f"    <li>{html.escape(point)}</li>" for point in points)
    homepage_link = (f'\n  <a class="project-demo" href="{html.escape(homepage, quote=True)}">在线演示</a>'
                     if homepage else "")
    card_html = f"""<article class="project-card">
  <header>
    <h3><a href="{safe_repo}">{safe_name}</a></h3>
    <span class="project-language">{html.escape(language)}</span>
  </header>
  <p class="project-summary">{safe_desc}</p>
  <ul class="project-highlights">
{list_items}
  </ul>{homepage_link}
</article>"""

    markdown_lines = [f"### [{project_name}]({repo_url})", "", safe_desc.replace("&#x27;", "'"), ""]
    markdown_lines += [f"- {point}" for point in points]
    if homepage:
        markdown_lines += ["", f"[在线演示]({homepage})"]

    resume_line = (f"{project_name}（{language}，开源）：{description or '解决了…'}"
                   f"，负责…，实现了…，可量化结果…")

    return {
        "html": card_html,
        "markdown": "\n".join(markdown_lines),
        "resume_line": resume_line,
        "note": "简历和个人网站都应该写「问题 → 做法 → 结果」，只写技术栈说服力很弱。",
    }


def contribution_ladder() -> List[Dict[str, str]]:
    """A realistic progression from first PR to maintainer."""
    return [
        {"stage": "01", "title": "修文档", "detail": "错别字、失效链接、补充使用说明。熟悉 PR 流程，几乎零风险。"},
        {"stage": "02", "title": "补测试", "detail": "为已有功能写测试。需要读懂代码，但不改变行为，容易被接受。"},
        {"stage": "03", "title": "修小 Bug", "detail": "带 good first issue 标签的问题。完整走一遍定位、修复、验证。"},
        {"stage": "04", "title": "实现小功能", "detail": "先在 Issue 里讨论方案，得到维护者认可后再动手写代码。"},
        {"stage": "05", "title": "参与评审", "detail": "帮别人复现问题、看 PR、回答新人提问。社区信任由此建立。"},
        {"stage": "06", "title": "长期维护", "detail": "负责某个模块、参与路线图讨论，可能被邀请成为 maintainer。"},
    ]


def build_contributor_guide(
    project_info: Dict[str, Any],
    username: str = "",
    platform: str = "github",
    slug: str = "",
    clone_url: str = "",
    license_id: str = "",
    description: str = "",
    homepage: str = "",
    keywords: str = "",
) -> Dict[str, Any]:
    """Assemble the full first-time-contributor guide."""
    language = project_info.get("primary_language", "Unknown")
    has_tests = bool(project_info.get("has_tests"))
    has_ci = bool(project_info.get("has_ci"))
    branch = project_info.get("branch") or "main"

    if homepage:
        parsed = urlparse(homepage)
        if parsed.scheme not in {"http", "https"}:
            homepage = ""

    checklist = pre_submit_checklist(has_tests, has_ci, language)
    return {
        "first_pr_workflow": first_pr_workflow(clone_url, platform, branch),
        "pre_submit_checklist": checklist,
        "blocking_count": sum(1 for item in checklist if item["blocking"]),
        "pr_template": pr_description_template(
            project_info.get("name", slug or "your-project"), language),
        "issue_search_links": issue_search_links(platform, language, keywords),
        "choose_issue_guide": choose_first_issue_guide(),
        "badges": readme_badges(username, slug or project_info.get("name", "project"),
                                platform, license_id),
        "portfolio": portfolio_entry(
            project_info.get("name", slug or "project"), description,
            clone_url[:-4] if clone_url.endswith(".git") else clone_url,
            homepage, language, []),
        "ladder": contribution_ladder(),
        "good_first_issue_labels": GOOD_FIRST_ISSUE_LABELS,
        "note": "以上是通用建议。目标项目的 CONTRIBUTING.md 与维护者要求优先于这里的任何内容。",
    }
