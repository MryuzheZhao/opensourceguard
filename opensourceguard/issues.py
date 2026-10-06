"""Issue triage: cluster, summarise and locate the likely cause.

This is the "help me manage the issues people file on my repo" workflow:

1. Pull open issues from the connected platforms.
2. Group them into themes so twenty reports about one bug read as one problem.
3. Summarise each theme: what users are actually hitting, how urgent it is.
4. Point at the code that most likely causes it, using the repository index.
5. Produce a concrete, reviewable change proposal.

Honesty boundaries that are enforced, not just documented:
* Every conclusion carries a confidence level and the evidence it came from.
* A proposal is never applied automatically. Remote writes still require the
  existing explicit confirmation path.
* Without a model the module still works, using keyword clustering, and says so.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .indexer import index_repository, issue_keywords, rank_symbols
from .languages import language_label

# Issue themes we can recognise without a model. Each entry maps a theme id to
# the words that signal it, in both English and Chinese.
THEME_RULES: List[tuple] = [
    ("crash", "崩溃 / 报错", (
        "crash", "exception", "traceback", "panic", "fatal", "stacktrace",
        "error", "崩溃", "报错", "异常", "闪退", "挂掉",
    )),
    ("install", "安装 / 环境", (
        "install", "setup", "dependency", "requirements", "pip", "npm", "docker",
        "version", "环境", "安装", "依赖", "版本", "部署",
    )),
    ("performance", "性能 / 卡顿", (
        "slow", "performance", "timeout", "memory", "leak", "hang", "cpu",
        "性能", "卡顿", "超时", "内存", "很慢", "耗时",
    )),
    ("docs", "文档 / 使用说明", (
        "doc", "docs", "readme", "documentation", "example", "tutorial", "typo",
        "文档", "说明", "示例", "教程", "错别字", "不清楚",
    )),
    ("feature", "功能需求", (
        "feature", "request", "support", "add", "enhancement", "would be nice",
        "需求", "希望", "支持", "增加", "建议", "能不能",
    )),
    ("compatibility", "兼容性", (
        "windows", "macos", "linux", "python 3", "node ", "browser", "compatible",
        "兼容", "系统", "浏览器", "平台",
    )),
    ("security", "安全", (
        "security", "vulnerability", "cve", "injection", "xss", "leak", "token",
        "安全", "漏洞", "注入", "泄露", "凭据",
    )),
    ("data", "数据 / 结果不正确", (
        "wrong", "incorrect", "unexpected", "mismatch", "empty", "missing",
        "不对", "错误结果", "不正确", "为空", "缺失", "丢失",
    )),
]

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


@dataclass
class IssueCluster:
    """A group of issues that appear to describe the same underlying problem."""

    theme: str
    label: str
    issue_numbers: List[Any] = field(default_factory=list)
    issue_titles: List[str] = field(default_factory=list)
    size: int = 0
    severity: str = "medium"
    summary: str = ""
    likely_cause: str = ""
    suspect_files: List[Dict[str, Any]] = field(default_factory=list)
    proposed_change: str = ""
    confidence: str = "low"
    evidence: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)


@dataclass
class IssueDigest:
    """A periodic report over a repository's open issues."""

    repo: str
    platform: str
    generated_at: str
    window_days: int
    total_issues: int
    new_issues: int
    stale_issues: int
    clusters: List[IssueCluster] = field(default_factory=list)
    headline: str = ""
    recommended_order: List[str] = field(default_factory=list)
    mode: str = "rules"
    model_used: str = "heuristic"
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _issue_text(issue: Dict[str, Any]) -> str:
    return f"{issue.get('title', '')} {issue.get('body', '')}".lower()


def _parse_timestamp(value: Any) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    for pattern in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(text.replace("+00:00", "Z"), pattern)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
        except ValueError:
            continue
    return 0.0


def classify(issue: Dict[str, Any]) -> tuple:
    """Return (theme_id, label) for one issue using keyword rules."""
    text = _issue_text(issue)
    labels = " ".join(str(x).lower() for x in issue.get("labels") or [])
    haystack = f"{text} {labels}"
    best, best_hits = None, 0
    for theme, label, needles in THEME_RULES:
        hits = sum(1 for needle in needles if needle in haystack)
        if hits > best_hits:
            best, best_hits = (theme, label), hits
    return best or ("other", "其他")


def _severity_for(theme: str, cluster_size: int, issues: Sequence[Dict[str, Any]]) -> str:
    labels = " ".join(str(x).lower() for issue in issues for x in issue.get("labels") or [])
    if theme == "security" or "critical" in labels:
        return "critical"
    if theme == "crash" or cluster_size >= 4 or "bug" in labels:
        return "high"
    if theme in {"performance", "data", "compatibility", "install"}:
        return "high" if cluster_size >= 2 else "medium"
    if theme in {"docs"}:
        return "low"
    return "medium"


def _locate_suspects(repo: Optional[Path], issues: Sequence[Dict[str, Any]], limit: int = 3) -> List[Dict[str, Any]]:
    """Map a cluster onto the source files most likely responsible."""
    if repo is None or not repo.is_dir():
        return []
    combined = " ".join(f"{issue.get('title', '')} {issue.get('body', '')}" for issue in issues)
    if not combined.strip():
        return []
    try:
        symbols = index_repository(repo)
    except (OSError, ValueError):
        return []
    ranked = rank_symbols(symbols, issue_keywords(combined), combined)
    suspects = []
    for symbol in ranked[:limit]:
        suspects.append({
            "path": symbol.path,
            "symbol": symbol.name,
            "start_line": symbol.start_line,
            "end_line": symbol.end_line,
            "language": language_label(symbol.language),
            "confidence": symbol.confidence,
        })
    return suspects


def _cluster_by_rules(issues: Sequence[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for issue in issues:
        theme, _ = classify(issue)
        buckets.setdefault(theme, []).append(issue)
    return buckets


def _model_digest(issues: Sequence[Dict[str, Any]], model: Any) -> Optional[List[Dict[str, Any]]]:
    """Ask the model to cluster issues and explain the likely cause."""
    if model is None or not getattr(model, "enabled", False) or not issues:
        return None
    listing = []
    for issue in issues[:40]:
        title = str(issue.get("title", ""))[:140]
        body = re.sub(r"\s+", " ", str(issue.get("body", "")))[:320]
        labels = ", ".join(str(x) for x in (issue.get("labels") or [])[:4])
        listing.append(f"#{issue.get('number')} 标题：{title}\n  标签：{labels or '无'}\n  内容：{body}")

    result = model.complete_json(
        "你在帮开源维护者整理用户提交的 Issue。只输出 JSON，格式为 "
        '{"clusters":[{"label":"中文主题名","issue_numbers":[1,2],"severity":"critical|high|medium|low",'
        '"summary":"用户实际遇到的问题","likely_cause":"最可能的原因","proposed_change":"具体建议的修改",'
        '"confidence":"high|medium|low"}],"headline":"一句话总体结论"}。'
        "把描述同一个根本问题的 Issue 归到一组。summary 写用户的真实痛点，不要复述标题。"
        "likely_cause 必须基于 Issue 内容推断，没有把握就写不确定并把 confidence 设为 low。"
        "proposed_change 要具体可执行。绝对不要声称问题已经被修复。",
        "以下是仓库当前的开放 Issue：\n\n" + "\n\n".join(listing),
        schema_fields=("clusters", "headline"),
    )
    if not result or not isinstance(result.get("clusters"), list):
        return None
    return result


def summarise(
    issues: Sequence[Dict[str, Any]],
    repo: Optional[Path] = None,
    model: Any = None,
    window_days: int = 7,
    platform: str = "",
    repo_name: str = "",
) -> IssueDigest:
    """Build a periodic digest over a repository's open issues."""
    issues = [dict(issue) for issue in issues if isinstance(issue, dict)]
    now = time.time()
    cutoff = now - window_days * 86400
    stale_cutoff = now - 60 * 86400

    new_issues = sum(1 for issue in issues if _parse_timestamp(issue.get("created_at")) >= cutoff)
    stale_issues = sum(1 for issue in issues
                       if 0 < _parse_timestamp(issue.get("updated_at")) < stale_cutoff)

    digest = IssueDigest(
        repo=repo_name or (str(repo) if repo else ""),
        platform=platform,
        generated_at=datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        window_days=window_days,
        total_issues=len(issues),
        new_issues=new_issues,
        stale_issues=stale_issues,
    )

    if not issues:
        digest.headline = "当前没有开放 Issue。"
        digest.warnings.append("没有可分析的 Issue；连接平台并确认仓库有开放 Issue 后再试。")
        return digest

    by_number = {str(issue.get("number")): issue for issue in issues}
    model_result = _model_digest(issues, model)
    clusters: List[IssueCluster] = []

    if model_result:
        digest.mode = "model"
        digest.model_used = getattr(model, "model", "model")
        digest.headline = str(model_result.get("headline") or "")
        for item in model_result.get("clusters", []):
            if not isinstance(item, dict):
                continue
            numbers = [n for n in (item.get("issue_numbers") or []) if str(n) in by_number]
            members = [by_number[str(n)] for n in numbers]
            if not members:
                continue
            theme, _ = classify(members[0])
            severity = str(item.get("severity", "medium")).lower()
            clusters.append(IssueCluster(
                theme=theme,
                label=str(item.get("label") or "未命名主题"),
                issue_numbers=numbers,
                issue_titles=[str(m.get("title", "")) for m in members],
                size=len(members),
                severity=severity if severity in SEVERITY_ORDER else "medium",
                summary=str(item.get("summary") or ""),
                likely_cause=str(item.get("likely_cause") or ""),
                proposed_change=str(item.get("proposed_change") or ""),
                confidence=str(item.get("confidence", "low")).lower(),
                suspect_files=_locate_suspects(repo, members),
                evidence=[f"#{n} {by_number[str(n)].get('title', '')}"[:120] for n in numbers[:5]],
                keywords=issue_keywords(" ".join(str(m.get("title", "")) for m in members))[:6],
            ))
    else:
        digest.mode = "rules"
        reason = getattr(model, "last_error", None) if model is not None else None
        if model is not None and getattr(model, "enabled", False):
            digest.warnings.append(
                f"模型调用未成功{f'（{reason}）' if reason else ''}，本次使用本地关键词聚类。")
        else:
            digest.warnings.append("未配置模型，本次使用本地关键词聚类；配置模型后可得到更准确的根因推断。")
        for theme, members in _cluster_by_rules(issues).items():
            label = next((lab for tid, lab, _ in THEME_RULES if tid == theme), "其他")
            severity = _severity_for(theme, len(members), members)
            clusters.append(IssueCluster(
                theme=theme,
                label=label,
                issue_numbers=[m.get("number") for m in members],
                issue_titles=[str(m.get("title", "")) for m in members],
                size=len(members),
                severity=severity,
                summary=f"{len(members)} 个 Issue 指向「{label}」类问题。",
                likely_cause="本地规则只能按关键词归类，无法推断根因；配置模型后可给出具体原因。",
                proposed_change="逐条查看下方 Issue，确认是否为同一根因后再决定修复方式。",
                confidence="low",
                suspect_files=_locate_suspects(repo, members),
                evidence=[f"#{m.get('number')} {m.get('title', '')}"[:120] for m in members[:5]],
                keywords=issue_keywords(" ".join(str(m.get("title", "")) for m in members))[:6],
            ))

    clusters.sort(key=lambda c: (SEVERITY_ORDER.get(c.severity, 9), -c.size))
    digest.clusters = clusters
    digest.recommended_order = [
        f"{index + 1}. [{cluster.severity}] {cluster.label}（{cluster.size} 个 Issue）"
        for index, cluster in enumerate(clusters[:5])
    ]
    if not digest.headline:
        top = clusters[0] if clusters else None
        digest.headline = (f"共 {len(issues)} 个开放 Issue；最应优先处理的是「{top.label}」。"
                           if top else f"共 {len(issues)} 个开放 Issue。")

    digest.warnings.append("所有结论都是基于 Issue 文本的推断，需要人工确认后再修改代码。")
    digest.warnings.append("本工具不会自动提交任何修改；写入评论或创建 PR 都需要你再次确认。")
    if stale_issues:
        digest.warnings.append(f"有 {stale_issues} 个 Issue 超过 60 天没有更新，建议确认是否仍然有效。")
    return digest


def to_markdown(digest: IssueDigest) -> str:
    """Render a digest as a report the maintainer can paste anywhere."""
    lines = [
        f"# Issue 定期总结：{digest.repo or '当前仓库'}",
        "",
        f"- 生成时间：{digest.generated_at}",
        f"- 统计窗口：最近 {digest.window_days} 天",
        f"- 开放 Issue：{digest.total_issues} 个（新增 {digest.new_issues}，长期未更新 {digest.stale_issues}）",
        f"- 分析方式：{'模型辅助（' + digest.model_used + '）' if digest.mode == 'model' else '本地关键词聚类'}",
        "",
        f"**{digest.headline}**",
        "",
    ]
    if digest.recommended_order:
        lines += ["## 建议处理顺序", ""] + [f"- {item}" for item in digest.recommended_order] + [""]

    for cluster in digest.clusters:
        label = {"critical": "紧急", "high": "高", "medium": "中", "low": "低"}.get(cluster.severity, cluster.severity)
        lines += [
            f"## [{label}] {cluster.label}（{cluster.size} 个 Issue，置信度 {cluster.confidence}）",
            "",
            f"**用户遇到的问题**：{cluster.summary}",
            "",
            f"**可能的原因**：{cluster.likely_cause}",
            "",
        ]
        if cluster.suspect_files:
            lines.append("**最可能相关的代码**：")
            for suspect in cluster.suspect_files:
                note = "（启发式定位）" if suspect["confidence"] == "heuristic" else ""
                lines.append(f"- `{suspect['path']}:{suspect['start_line']}` "
                             f"{suspect['symbol']} [{suspect['language']}]{note}")
            lines.append("")
        lines += [f"**建议的修改**：{cluster.proposed_change}", "", "**涉及的 Issue**："]
        lines += [f"- {item}" for item in cluster.evidence]
        lines.append("")

    lines += ["## 边界说明", ""] + [f"- {item}" for item in digest.warnings] + [""]
    return "\n".join(lines)


def schedule_hint(interval_hours: int = 24) -> Dict[str, Any]:
    """Describe how to run this digest on a schedule.

    The tool deliberately does not install a background daemon: a maintainer
    should stay in control of when their repository is read. Instead it gives
    the exact command for the platform's own scheduler.
    """
    interval_hours = max(1, min(int(interval_hours), 24 * 14))
    command = "python -m opensourceguard.cli issues --repo . --platform github --repo-name OWNER/REPO --markdown artifacts/issue-digest.md"
    return {
        "interval_hours": interval_hours,
        "command": command,
        "windows": {
            "description": "使用 Windows 任务计划程序，每 N 小时运行一次。",
            "command": (
                f'schtasks /create /tn "OpenSourceGuard Issue Digest" /sc hourly /mo {interval_hours} '
                f'/tr "cmd /c cd /d \\"%CD%\\" && {command}"'
            ),
        },
        "linux_macos": {
            "description": "使用 cron，每 N 小时运行一次。",
            "command": f"0 */{interval_hours} * * * cd $(pwd) && {command}",
        },
        "note": "定时任务只生成报告，不会自动修改代码或提交 PR；每次修改仍需你确认。",
    }
