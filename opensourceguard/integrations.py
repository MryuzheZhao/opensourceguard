from __future__ import annotations

from typing import Any, Dict, Mapping

from .report import to_markdown
from .types import AnalysisReport


def normalize_issue_payload(payload: Mapping[str, Any]) -> str:
    """Normalize local, GitHub, and Gitee webhook payloads into Issue text."""
    issue = payload.get("issue")
    if isinstance(issue, Mapping):
        title = str(issue.get("title", "")).strip()
        body = str(issue.get("body", "")).strip()
        return "\n\n".join(part for part in (title, body) if part)
    if isinstance(issue, str) and issue.strip():
        return issue.strip()
    title = str(payload.get("title", "")).strip()
    body = str(payload.get("body", "")).strip()
    return "\n\n".join(part for part in (title, body) if part)


def _public_repo_label(repo: str) -> str:
    """Reduce a local absolute path to a bare repository name.

    A pull request is public. The report is produced against a path like
    `C:\\Users\\someone\\code\\my-project`, and pasting that into a PR body
    publishes the maintainer's username and directory layout. Only the final
    path segment is meaningful to a reviewer.
    """
    text = str(repo or "").replace("\\", "/").rstrip("/")
    if not text:
        return "unknown"
    return text.rsplit("/", 1)[-1] or "unknown"


def to_public_markdown(report: AnalysisReport) -> str:
    """Markdown safe to publish: no absolute local paths."""
    return to_markdown(report).replace(f"`{report.repo}`", f"`{_public_repo_label(report.repo)}`")


def draft_pr_payload(report: AnalysisReport, head: str = "opensourceguard/fix", base: str = "main") -> Dict[str, Any]:
    """Create a provider-neutral Draft PR payload without making network calls."""
    issue_type = report.issue.issue_type
    title_prefix = "安全修复" if issue_type == "security" else "AI 候选修复"
    title = f"{title_prefix}: {report.issue.issue[:72].replace(chr(10), ' ')}"
    body = to_public_markdown(report)
    return {
        "title": title,
        "body": body,
        "head": head,
        "base": base,
        "draft": True,
        "labels": ["opensourceguard", f"type:{issue_type}"],
        "metadata": {
            "tool": "OpenSourceGuard",
            "model": report.model_used,
            "verification_status": report.verification_status,
            "baseline_passed": all(item.passed for item in report.tests if item.stage == "baseline"),
            "candidate_passed": all(item.passed for item in report.tests if item.stage == "candidate_patch") if any(item.stage == "candidate_patch" for item in report.tests) else None,
            "full_suite_passed": all(item.passed for item in report.tests if item.stage == "candidate_full") if any(item.stage == "candidate_full" for item in report.tests) else None,
            "security_findings": len(report.security_findings),
        },
    }
