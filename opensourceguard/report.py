from __future__ import annotations

import json
from pathlib import Path

from .types import AnalysisReport


def to_markdown(report: AnalysisReport) -> str:
    lines = [
        "# OpenSourceGuard 修复报告", "",
        f"- 仓库：`{report.repo}`",
        f"- 问题类型：{report.issue.issue_type}",
        f"- 严重程度：{report.issue.severity}",
        f"- 分析方式：{report.model_used}", "",
        f"- 验证状态：{report.verification_status}",
        f"- 执行模式：{report.execution_mode}",
        f"- 仓库快照：{report.snapshot_sha256[:16] or '未计算'}…", "",
        "## Issue 分析", "", report.issue.issue, "",
        f"预期行为：{report.issue.expected_behavior}", "",
        f"实际行为：{report.issue.actual_behavior}", "",
        "## 代码证据", "",
    ]
    for item in report.evidence:
        lines.append(f"- `{item.path}:{item.start_line}-{item.end_line}`（{item.score:.2f}）：{item.reason}")
    lines += ["", "## 复现测试建议", "", "```python", report.reproduction_test, "```", "", "## 补丁计划", "", report.patch_plan]
    if report.patch:
        lines += ["", "## 候选补丁", "", "```diff", report.patch, "```"]
    else:
        lines += ["", "## 候选补丁", "", "当前分析没有生成可直接审核的 unified diff，请根据补丁计划补充复现信息后再修改。"]
    lines += ["", "## 验证结果", ""]
    for result in report.tests:
        status = ("未执行" if result.command[0] == "skip" else
                  "环境错误" if result.infrastructure_error else
                  "通过" if result.passed else ("超时" if result.timed_out else "失败"))
        counts = f"，运行 {result.tests_run} 项，失败 {result.failures}，错误 {result.errors}" if result.tests_run else ""
        lines.append(f"- [{result.stage}] {' '.join(result.command)}：**{status}**（退出码 {result.return_code}{counts}）")
        if result.stdout or result.stderr:
            lines += ["", "```text", result.stdout + result.stderr, "```"]
    lines += ["", "## 安全扫描", ""]
    if report.security_findings:
        for finding in report.security_findings:
            lines.append(f"- **{finding.severity}** `{finding.rule_id}` `{finding.path}:{finding.line}`：{finding.message} 建议：{finding.recommendation}")
    else:
        lines.append("- 未命中内置 Python 安全规则。")
    if report.security_findings_after:
        lines += ["", "补丁后安全扫描："]
        for finding in report.security_findings_after:
            lines.append(f"- **{finding.severity}** `{finding.rule_id}` `{finding.path}:{finding.line}`：{finding.message}")
    lines += ["", "## 下一步", ""] + [f"- {action}" for action in report.next_actions]
    if report.warnings:
        lines += ["", "## 风险提示", ""] + [f"- {warning}" for warning in report.warnings]
    return "\n".join(lines) + "\n"


def write_report(report: AnalysisReport, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    output.with_suffix(".md").write_text(to_markdown(report), encoding="utf-8")
