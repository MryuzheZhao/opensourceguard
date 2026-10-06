"""Project health scoring.

Aggregates security, compliance, documentation, testing and maintenance signals
into a single reviewable score. The scoring rubric is fully explicit: every
dimension states its weight, what was measured and why points were lost, so a
user (or a competition judge) can audit the number instead of trusting it.

Deliberate honesty constraints:
* Scores describe *observable repository signals only*. They do not measure code
  correctness, architecture quality or real-world reliability.
* Signals that could not be measured are reported as ``unmeasured`` and excluded
  from the weighted average rather than silently scored as zero or full marks.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .compliance import audit as compliance_audit
from .indexer import index_repository, language_breakdown
from .languages import is_test_path, language_label
from .security import scan_repository, severity_counts

# Weight per dimension. They sum to 100 for the "all measured" case; when a
# dimension is unmeasured, the remaining weights are renormalised.
WEIGHTS: Dict[str, int] = {
    "security": 30,
    "compliance": 20,
    "testing": 20,
    "documentation": 15,
    "maintainability": 15,
}

GRADE_BANDS = [
    (90, "A", "优秀", "可以直接作为开源代表作展示。"),
    (80, "B", "良好", "整体健康，补齐少量短板即可。"),
    (70, "C", "合格", "基础具备，但有明显可改进项。"),
    (60, "D", "偏弱", "开源前建议先处理高优先级问题。"),
    (0, "E", "较差", "存在阻塞性问题，不建议直接公开发布。"),
]

# Directories that intentionally contain detectable problems (test fixtures,
# demo inputs, vulnerable samples). Findings here are reported separately rather
# than counted against the project's own security score, otherwise any security
# tool would be penalised for shipping its own test corpus.
FIXTURE_DIRECTORIES = ("examples/", "fixtures/", "testdata/", "test-data/",
                       "samples/", "demo/", "demos/", "benchmark/")


def _is_fixture_path(relative_path: str) -> bool:
    normalized = relative_path.replace("\\", "/").lower()
    return (any(normalized.startswith(prefix) or f"/{prefix}" in normalized
                for prefix in FIXTURE_DIRECTORIES)
            or is_test_path(normalized))


@dataclass
class Dimension:
    """One scored dimension of project health."""

    key: str
    label: str
    weight: int
    score: int                       # 0-100
    measured: bool = True
    signals: List[str] = field(default_factory=list)      # what we observed
    deductions: List[Dict[str, Any]] = field(default_factory=list)
    actions: List[str] = field(default_factory=list)      # what to do next


@dataclass
class HealthReport:
    repo: str
    score: int
    grade: str
    grade_label: str
    grade_note: str
    dimensions: List[Dimension]
    stats: Dict[str, Any]
    blocking_issues: List[str]
    quick_wins: List[str]
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _clamp(value: float) -> int:
    return max(0, min(100, int(round(value))))


def _grade(score: int):
    for threshold, grade, label, note in GRADE_BANDS:
        if score >= threshold:
            return grade, label, note
    return "E", "较差", ""


# --------------------------------------------------------------------------
# Individual dimensions
# --------------------------------------------------------------------------

def _score_security(findings, fixture_findings: int = 0) -> Dimension:
    counts = severity_counts(findings)
    score = 100
    deductions: List[Dict[str, Any]] = []

    # High findings dominate; medium matters; low is a nudge. Capped so a single
    # noisy file cannot push the dimension below a floor that would hide progress.
    if counts["high"]:
        penalty = min(60, counts["high"] * 20)
        score -= penalty
        deductions.append({"reason": f"{counts['high']} 个高风险安全问题", "points": penalty})
    if counts["medium"]:
        penalty = min(25, counts["medium"] * 5)
        score -= penalty
        deductions.append({"reason": f"{counts['medium']} 个中风险安全问题", "points": penalty})
    if counts["low"]:
        penalty = min(10, counts["low"] * 2)
        score -= penalty
        deductions.append({"reason": f"{counts['low']} 个低风险提示", "points": penalty})

    rules = sorted({finding.rule_id for finding in findings})
    signals = [f"扫描命中规则：{', '.join(rules[:8])}" if rules else "未命中任何安全规则"]
    if findings:
        cwes = sorted({finding.cwe for finding in findings if finding.cwe})
        if cwes:
            signals.append(f"涉及 CWE：{', '.join(cwes[:8])}")
    if fixture_findings:
        signals.append(
            f"另有 {fixture_findings} 个问题位于测试夹具/示例目录，已排除在评分之外"
            "（这些目录通常刻意保留可检出的问题）"
        )

    actions = []
    if counts["high"]:
        top = [f for f in findings if f.severity == "high"][:3]
        for finding in top:
            actions.append(f"修复 {finding.path}:{finding.line} — {finding.recommendation}")
    elif counts["medium"]:
        actions.append("处理中风险问题，或对确认无害的行添加 `# osg:ignore` 并写明原因。")
    else:
        actions.append("保持现状；建议在 CI 中加入扫描，防止回退。")

    return Dimension("security", "安全", WEIGHTS["security"], _clamp(score),
                     signals=signals, deductions=deductions, actions=actions)


def _score_compliance(report) -> Dimension:
    score = 100
    deductions: List[Dict[str, Any]] = []
    summary = report.summary
    severity = summary["severity"]

    if not report.project_license:
        score -= 40
        deductions.append({"reason": "没有 LICENSE 文件，也未在清单中声明许可证", "points": 40})
    elif report.project_license == "unknown":
        score -= 15
        deductions.append({"reason": "许可证文件内容无法匹配标准许可证", "points": 15})

    license_conflicts = [f for f in report.findings if f.kind == "license" and f.severity == "high"]
    if license_conflicts:
        penalty = min(35, len(license_conflicts) * 18)
        score -= penalty
        deductions.append({"reason": f"{len(license_conflicts)} 个高风险许可证冲突", "points": penalty})

    dependency_issues = [f for f in report.findings if f.kind == "dependency" and f.severity == "medium"]
    if dependency_issues:
        penalty = min(15, len(dependency_issues) * 5)
        score -= penalty
        deductions.append({"reason": f"{len(dependency_issues)} 个有风险的依赖", "points": penalty})

    credential_files = [f for f in report.findings if f.kind == "file" and f.severity == "high"
                        and f.subject != "LICENSE"]
    if credential_files:
        penalty = min(30, len(credential_files) * 15)
        score -= penalty
        deductions.append({"reason": f"{len(credential_files)} 个疑似凭据文件位于仓库根目录", "points": penalty})

    signals = [
        f"项目许可证：{report.project_license or '未声明'}"
        + (f"（{report.license_source}）" if report.license_source else ""),
        f"依赖 {summary['dependency_count']} 个，已解析许可证 {summary['resolved_licenses']} 个，"
        f"未知 {summary['unknown_licenses']} 个",
    ]
    if report.manifests:
        signals.append(f"依赖清单：{', '.join(report.manifests[:5])}")

    actions = []
    if not report.project_license:
        actions.append("添加 LICENSE 文件；个人开源项目通常选 MIT（最宽松）或 Apache-2.0（含专利条款）。")
    for finding in license_conflicts[:2]:
        actions.append(f"{finding.subject}：{finding.recommendation}")
    for finding in credential_files[:2]:
        actions.append(f"{finding.subject}：{finding.recommendation}")
    if not actions:
        actions.append("合规状态良好；新增依赖时重新运行一次审计即可。")

    return Dimension("compliance", "合规", WEIGHTS["compliance"], _clamp(score),
                     signals=signals, deductions=deductions, actions=actions)


def _score_testing(repo: Path, symbols) -> Dimension:
    source_files = [s for s in symbols if s.kind == "module"]
    test_files = [s for s in source_files if is_test_path(s.path)]
    implementation = [s for s in source_files if not is_test_path(s.path)]

    if not source_files:
        return Dimension("testing", "测试", WEIGHTS["testing"], 0, measured=False,
                         signals=["仓库中没有可识别的源码文件，无法评估测试情况"],
                         actions=["确认传入的目录是项目根目录。"])

    score = 100
    deductions: List[Dict[str, Any]] = []
    has_test_dir = any((repo / name).is_dir() for name in ("tests", "test", "spec", "__tests__"))

    if not test_files:
        score -= 70
        deductions.append({"reason": "没有找到任何测试文件", "points": 70})
    else:
        ratio = len(test_files) / max(1, len(implementation))
        # A healthy repo usually has at least one test file per ~4 source files.
        if ratio < 0.1:
            score -= 35
            deductions.append({"reason": f"测试文件占比偏低（{len(test_files)}/{len(implementation)}）", "points": 35})
        elif ratio < 0.25:
            score -= 15
            deductions.append({"reason": f"测试覆盖面可能不足（{len(test_files)}/{len(implementation)}）", "points": 15})

    if not has_test_dir and test_files:
        score -= 5
        deductions.append({"reason": "测试文件分散，没有统一的 tests/ 目录", "points": 5})

    ci_configured = (repo / ".github" / "workflows").is_dir() or (repo / ".gitee" / "workflows").is_dir()
    if not ci_configured:
        score -= 20
        deductions.append({"reason": "没有配置 CI，测试不会自动运行", "points": 20})

    signals = [
        f"源码文件 {len(implementation)} 个，测试文件 {len(test_files)} 个",
        f"CI 配置：{'已配置' if ci_configured else '未配置'}",
    ]
    actions = []
    if not test_files:
        actions.append("先为最核心的一个函数补一个测试，建立测试目录结构。")
    if not ci_configured:
        actions.append("添加 .github/workflows/ci.yml，让每次推送自动运行测试。")
    if not actions:
        actions.append("测试基础完善；建议补充边界条件和失败路径的用例。")

    return Dimension("testing", "测试", WEIGHTS["testing"], _clamp(score),
                     signals=signals, deductions=deductions, actions=actions)


def _score_documentation(repo: Path) -> Dimension:
    score = 100
    deductions: List[Dict[str, Any]] = []
    signals: List[str] = []
    actions: List[str] = []

    readme = next((repo / name for name in ("README.md", "README.rst", "README.txt")
                   if (repo / name).is_file()), None)
    if readme is None:
        score -= 45
        deductions.append({"reason": "缺少 README", "points": 45})
        actions.append("添加 README.md：项目做什么、怎么安装、最小运行示例、许可证。")
    else:
        try:
            content = readme.read_text(encoding="utf-8", errors="replace")
        except OSError:
            content = ""
        lines = len(content.splitlines())
        signals.append(f"{readme.name}：{lines} 行")
        if lines < 15:
            score -= 25
            deductions.append({"reason": f"README 过于简短（{lines} 行）", "points": 25})
            actions.append("扩充 README：加入快速开始、使用示例和功能说明。")
        lowered = content.lower()
        missing_sections = []
        if not any(marker in lowered for marker in ("install", "安装", "quick start", "快速开始", "getting started")):
            missing_sections.append("安装/快速开始")
        if "```" not in content and "~~~" not in content:
            missing_sections.append("代码示例")
        if not any(marker in lowered for marker in ("license", "许可")):
            missing_sections.append("许可证说明")
        if missing_sections:
            penalty = min(20, len(missing_sections) * 7)
            score -= penalty
            deductions.append({"reason": f"README 缺少：{', '.join(missing_sections)}", "points": penalty})
            actions.append(f"在 README 中补充：{', '.join(missing_sections)}。")

    for name, points, note in (
        ("CONTRIBUTING.md", 15, "贡献指南"),
        ("CODE_OF_CONDUCT.md", 5, "行为准则"),
        ("SECURITY.md", 5, "安全披露政策"),
        ("CHANGELOG.md", 5, "变更日志"),
    ):
        if (repo / name).is_file():
            signals.append(f"{name}：已提供")
        else:
            score -= points
            deductions.append({"reason": f"缺少 {name}（{note}）", "points": points})

    if not actions:
        actions.append("文档完善；建议补充架构说明或使用截图。")

    return Dimension("documentation", "文档", WEIGHTS["documentation"], _clamp(score),
                     signals=signals, deductions=deductions, actions=actions)


def _score_maintainability(repo: Path, symbols) -> Dimension:
    modules = [s for s in symbols if s.kind == "module" and not is_test_path(s.path)]
    functions = [s for s in symbols if s.kind in {"function", "method"}]

    if not modules:
        return Dimension("maintainability", "可维护性", WEIGHTS["maintainability"], 0,
                         measured=False,
                         signals=["没有可分析的源码文件"],
                         actions=["确认目录中包含受支持语言的源码。"])

    score = 100
    deductions: List[Dict[str, Any]] = []

    # Oversized files are the single most reliable structural smell we can
    # measure without executing or deeply parsing the code.
    large_files = [s for s in modules if s.end_line > 800]
    if large_files:
        penalty = min(25, len(large_files) * 8)
        score -= penalty
        deductions.append({
            "reason": f"{len(large_files)} 个文件超过 800 行（最大 {max(s.end_line for s in large_files)} 行）",
            "points": penalty,
        })

    long_functions = [s for s in functions if (s.end_line - s.start_line) > 120]
    if long_functions:
        penalty = min(20, len(long_functions) * 5)
        score -= penalty
        deductions.append({"reason": f"{len(long_functions)} 个函数超过 120 行", "points": penalty})

    if not (repo / ".gitignore").is_file():
        score -= 15
        deductions.append({"reason": "缺少 .gitignore", "points": 15})

    has_dependency_manifest = any((repo / name).is_file() for name in (
        "requirements.txt", "pyproject.toml", "setup.py", "package.json",
        "go.mod", "Cargo.toml", "pom.xml", "build.gradle"))
    if not has_dependency_manifest:
        score -= 20
        deductions.append({"reason": "没有依赖声明文件，别人无法复现环境", "points": 20})

    languages = language_breakdown(symbols)
    if len(languages) > 4:
        score -= 5
        deductions.append({"reason": f"涉及 {len(languages)} 种语言，维护成本较高", "points": 5})

    total_lines = sum(s.end_line for s in modules)
    signals = [
        f"源码文件 {len(modules)} 个，约 {total_lines} 行",
        f"函数/方法 {len(functions)} 个",
        "语言分布：" + "、".join(f"{language_label(name)} {count}" for name, count in list(languages.items())[:5]),
    ]

    actions = []
    if large_files:
        actions.append(f"拆分最大的文件：{large_files[0].path}（{large_files[0].end_line} 行）。")
    if long_functions:
        worst = max(long_functions, key=lambda s: s.end_line - s.start_line)
        actions.append(f"重构过长函数：{worst.path}:{worst.start_line} 的 {worst.name}。")
    if not has_dependency_manifest:
        actions.append("添加依赖声明文件，并锁定版本。")
    if not (repo / ".gitignore").is_file():
        actions.append("添加 .gitignore，排除虚拟环境、缓存和凭据文件。")
    if not actions:
        actions.append("结构清晰；继续保持小文件、小函数。")

    return Dimension("maintainability", "可维护性", WEIGHTS["maintainability"], _clamp(score),
                     signals=signals, deductions=deductions, actions=actions)


# --------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------

def evaluate(repo: Path, security_findings=None, compliance_report=None) -> HealthReport:
    """Compute a full health report for a repository.

    ``security_findings`` and ``compliance_report`` can be passed in to reuse
    results that the caller already computed, avoiding a second scan.
    """
    repo = repo.resolve()
    if not repo.is_dir():
        raise ValueError(f"仓库目录不存在：{repo}")

    symbols = index_repository(repo)
    all_findings = scan_repository(repo) if security_findings is None else security_findings
    compliance = compliance_audit(repo) if compliance_report is None else compliance_report

    # Separate fixture/demo findings from the project's own code. Paths are
    # relative to the scanned root, so scanning a demo directory directly still
    # scores its contents normally.
    own_findings = [f for f in all_findings if not _is_fixture_path(f.path)]
    fixture_count = len(all_findings) - len(own_findings)

    dimensions = [
        _score_security(own_findings, fixture_count),
        _score_compliance(compliance),
        _score_testing(repo, symbols),
        _score_documentation(repo),
        _score_maintainability(repo, symbols),
    ]

    # Renormalise weights across measured dimensions only.
    measured = [d for d in dimensions if d.measured]
    total_weight = sum(d.weight for d in measured)
    if total_weight:
        score = _clamp(sum(d.score * d.weight for d in measured) / total_weight)
    else:
        score = 0

    grade, grade_label, grade_note = _grade(score)

    blocking: List[str] = []
    for finding in own_findings:
        if finding.severity == "high":
            blocking.append(f"安全：{finding.path}:{finding.line} {finding.rule_id} — {finding.message}")
    for finding in compliance.findings:
        if finding.severity == "high":
            blocking.append(f"合规：{finding.subject} — {finding.message}")

    quick_wins: List[str] = []
    for dimension in sorted(dimensions, key=lambda d: d.score):
        for action in dimension.actions[:1]:
            quick_wins.append(f"[{dimension.label}] {action}")

    warnings = [
        "评分只反映可观测的仓库信号（安全规则、依赖清单、文档文件、测试文件、文件规模），"
        "不评估代码正确性、架构质量或运行时可靠性。",
        "非 Python 语言使用启发式解析，行数与符号统计可能存在偏差。",
    ]
    if fixture_count:
        warnings.append(
            f"examples/、tests/ 等夹具目录中的 {fixture_count} 个问题未计入安全评分；"
            "这些目录通常刻意保留可检出的问题作为演示或测试输入。"
        )
    unmeasured = [d.label for d in dimensions if not d.measured]
    if unmeasured:
        warnings.append(f"以下维度无法测量，已从加权平均中排除：{', '.join(unmeasured)}。")

    stats = {
        "source_files": len([s for s in symbols if s.kind == "module"]),
        "symbols": len(symbols),
        "languages": language_breakdown(symbols),
        "security": severity_counts(own_findings),
        "security_in_fixtures": fixture_count,
        "dependencies": compliance.summary["dependency_count"],
        "license": compliance.project_license or "未声明",
        "measured_weight": total_weight,
    }

    return HealthReport(
        repo=str(repo), score=score, grade=grade, grade_label=grade_label,
        grade_note=grade_note, dimensions=dimensions, stats=stats,
        blocking_issues=blocking[:10], quick_wins=quick_wins[:5], warnings=warnings,
    )


def to_markdown(report: HealthReport) -> str:
    """Render a health report as reviewable Markdown."""
    lines = [
        "# 项目健康度报告",
        "",
        f"- 仓库：`{report.repo}`",
        f"- 综合评分：**{report.score} / 100**（{report.grade} · {report.grade_label}）",
        f"- 结论：{report.grade_note}",
        f"- 源码文件 {report.stats['source_files']} 个｜依赖 {report.stats['dependencies']} 个"
        f"｜许可证 {report.stats['license']}",
        "",
        "## 各维度评分",
        "",
        "| 维度 | 权重 | 得分 | 状态 |",
        "|---|---|---|---|",
    ]
    for dimension in report.dimensions:
        status = "未测量" if not dimension.measured else (
            "良好" if dimension.score >= 80 else ("一般" if dimension.score >= 60 else "需改进"))
        lines.append(f"| {dimension.label} | {dimension.weight}% | {dimension.score} | {status} |")
    lines.append("")

    for dimension in report.dimensions:
        lines.append(f"### {dimension.label}（{dimension.score}/100）")
        for signal in dimension.signals:
            lines.append(f"- 观测：{signal}")
        for deduction in dimension.deductions:
            lines.append(f"- 扣分 {deduction['points']}：{deduction['reason']}")
        for action in dimension.actions:
            lines.append(f"- 建议：{action}")
        lines.append("")

    if report.blocking_issues:
        lines += ["## 阻塞性问题", ""] + [f"- {item}" for item in report.blocking_issues] + [""]
    if report.quick_wins:
        lines += ["## 优先改进项", ""] + [f"- {item}" for item in report.quick_wins] + [""]
    lines += ["## 边界说明", ""] + [f"- {item}" for item in report.warnings] + [""]
    return "\n".join(lines)
