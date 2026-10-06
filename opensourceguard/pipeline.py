from __future__ import annotations

import difflib
import hashlib
import re
import tempfile
from pathlib import Path
from typing import List

from .indexer import index_repository, issue_keywords, language_breakdown, rank_symbols
from .languages import is_test_path, language_label
from .model import ModelClient
from .patching import apply_patch
from .repository import repository_files, snapshot
from .sandbox import run_tests
from .security import scan_repository
from .types import AnalysisReport, Evidence, IssueAnalysis


def _issue_analysis(issue: str) -> IssueAnalysis:
    lower = issue.lower()
    if any(word in lower for word in ("security", "vulnerability", "cve", "漏洞", "注入")):
        issue_type, severity = "security", "high"
    elif any(word in lower for word in ("feature", "支持", "增加", "enhancement")):
        issue_type, severity = "feature", "medium"
    else:
        issue_type = "bug"
        severity = "high" if any(word in lower for word in ("crash", "panic", "漏洞", "崩溃", "安全")) else "medium"
    actual = issue.split("应该")[0].strip() if "应该" in issue else issue
    expected = issue.split("应该", 1)[1].strip() if "应该" in issue else "修复后程序应稳定处理该输入并保持现有测试通过。"
    return IssueAnalysis(issue, issue_type, severity, issue_keywords(issue), expected, actual)


def _test_snippet(issue: str, evidence: List[Evidence]) -> str:
    target = evidence[0].path if evidence else "src/module.py"
    language = evidence[0].language if evidence else "python"
    lower = issue.lower()
    if language == "python" and ("csv" in lower or "CSV" in issue) and ("empty" in lower or "空" in issue):
        return (
            "import unittest\n"
            "from parser import parse_csv\n\n\n"
            "class ReproductionTests(unittest.TestCase):\n"
            "    def test_empty_csv_returns_empty_list(self):\n"
            "        self.assertEqual(parse_csv(\"\"), [])\n"
        )
    name = re.sub(r"\W+", "_", lower).strip("_")[:45] or "reported_issue"
    line = evidence[0].start_line if evidence else 1
    if language in {"javascript", "typescript"}:
        return (
            f"// 最小化复现 Issue；提交前应把输入替换成真实样例。\n"
            f"// 相关代码：{target}:{line}\n"
            f"test('{name}', () => {{\n"
            f"  // TODO: 填入 Issue 的最小输入，并断言预期行为。\n"
            f"  expect(true).toBe(true);\n"
            f"}});\n"
        )
    if language == "go":
        return (
            f"// 相关代码：{target}:{line}\n"
            f"func Test_{name}(t *testing.T) {{\n"
            f"\t// TODO: 填入 Issue 的最小输入，并断言预期行为。\n"
            f"}}\n"
        )
    if language == "java":
        return (
            f"// 相关代码：{target}:{line}\n"
            f"@Test\n"
            f"public void {name}() {{\n"
            f"    // TODO: 填入 Issue 的最小输入，并断言预期行为。\n"
            f"}}\n"
        )
    if language == "rust":
        return (
            f"// 相关代码：{target}:{line}\n"
            f"#[test]\n"
            f"fn {name}() {{\n"
            f"    // TODO: 填入 Issue 的最小输入，并断言预期行为。\n"
            f"}}\n"
        )
    return (
        f"def test_{name}():\n"
        f"    \"\"\"最小化复现 Issue；提交前应把输入替换成真实样例。\"\"\"\n"
        f"    # 相关代码：{target}:{line}\n"
        f"    # TODO: 填入 Issue 的最小输入，并断言预期行为。\n"
        f"    assert True\n"
    )


def _heuristic_patch(repo: Path, evidence: List[Evidence], issue: IssueAnalysis) -> str:
    if not evidence or ("csv" not in " ".join(issue.keywords).lower() and "CSV" not in issue.issue):
        return ""
    path = repo / evidence[0].path
    try:
        before = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    old = "    return rows[0] if len(rows) <= 1 else rows"
    new = "    return [] if not rows else (rows[0] if len(rows) == 1 else rows)"
    if old not in before or ("empty" not in " ".join(issue.keywords).lower() and "空" not in issue.issue):
        return ""
    after = before.replace(old, new, 1)
    return "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), fromfile=f"a/{evidence[0].path}", tofile=f"b/{evidence[0].path}"))


def _evidence_context(repo: Path, evidence: List[Evidence]) -> str:
    chunks = []
    for item in evidence[:3]:
        path = repo / item.path
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        start = max(1, item.start_line - 3)
        end = min(len(lines), item.end_line + 3)
        snippet = "\n".join(f"{line_no}: {lines[line_no - 1]}" for line_no in range(start, end + 1))
        chunks.append(f"{item.path}:{start}-{end}\n{snippet}")
    return "\n\n".join(chunks)


def _repository_digest(repo: Path) -> str:
    digest = hashlib.sha256()
    for path in repository_files(repo):
        digest.update(path.relative_to(repo).as_posix().encode("utf-8") + b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _write_reproduction(repo: Path, source: str) -> str:
    name = "test_osg_reproduction.py"
    while (repo / name).exists():
        name = name.replace(".py", "_new.py")
    (repo / name).write_text(source, encoding="utf-8", newline="\n")
    return name


def _is_concrete_reproduction(source: str) -> bool:
    return "assert True" not in source and "TODO:" not in source


def analyze(
    repo: Path,
    issue: str,
    model: ModelClient | None = None,
    timeout: int = 30,
    mode: str = "skip",
    framework: str = "unittest",
    test_path: str = "",
) -> AnalysisReport:
    repo = repo.resolve()
    if not repo.is_dir():
        raise ValueError(f"仓库目录不存在：{repo}")
    if mode not in {"skip", "local", "docker"}:
        raise ValueError("mode 必须是 skip、local 或 docker。")
    if framework not in {"unittest", "pytest"}:
        raise ValueError("framework 必须是 unittest 或 pytest。")

    model = model or ModelClient()
    analysis = _issue_analysis(issue)
    symbols = index_repository(repo)
    languages = language_breakdown(symbols)
    primary_language = next(iter(languages), "")
    ranked = rank_symbols(symbols, analysis.keywords, issue)
    evidence: List[Evidence] = []
    for index, symbol in enumerate(ranked[:5]):
        score = max(0.2, 1.0 - index * 0.12)
        reason = f"符号 {symbol.name} 与 Issue 关键词和代码内容匹配"
        if is_test_path(symbol.path):
            reason += "，同时存在相关测试线索"
        if symbol.confidence == "heuristic":
            reason += f"（{language_label(symbol.language)} 使用启发式定位，需人工确认）"
        evidence.append(Evidence(symbol.path, symbol.start_line, symbol.end_line, reason, score,
                                 language=symbol.language, confidence=symbol.confidence,
                                 symbol=symbol.name))
    if not evidence and symbols:
        symbol = symbols[0]
        evidence.append(Evidence(symbol.path, symbol.start_line, symbol.end_line,
                                 "未找到高置信匹配，返回仓库首个可分析模块作为人工检查入口", 0.2,
                                 language=symbol.language, confidence=symbol.confidence,
                                 symbol=symbol.name))
    evidence_confidence = evidence[0].confidence if evidence else "parsed"

    model_used = "heuristic"
    patch_plan = "先补充最小复现测试；确认原始代码能够重现问题后，在最相关函数内做最小修改；保留兼容行为，运行全部测试和安全扫描，再由维护者审核。"
    patch = _heuristic_patch(repo, evidence, analysis)
    patch_source = "heuristic" if patch else "none"
    reproduction = _test_snippet(issue, evidence)
    warnings = ["当前报告不会修改目标仓库；补丁只会在临时副本中校验。"]
    if evidence_confidence == "heuristic":
        warnings.append(
            f"{language_label(primary_language or 'unknown')} 等非 Python 语言使用启发式符号定位，"
            "证据位置可能偏移，必须人工确认后再采用补丁。"
        )
    if len(languages) > 1:
        detail = "、".join(f"{language_label(name)} {count}" for name, count in list(languages.items())[:5])
        warnings.append(f"仓库包含多种语言（{detail}）；自动验证目前只覆盖 Python 测试命令。")
    if model.enabled:
        prompt = "\n".join([
            f"Issue: {issue}",
            "候选证据:",
            *[f"{e.path}:{e.start_line}-{e.end_line} {e.reason}" for e in evidence],
            "源码上下文:",
            _evidence_context(repo, evidence),
        ])
        result = model.complete_json(
            "你是开源项目维护助手。只输出 JSON，字段 reproduction_test、patch_plan、patch、warnings。"
            "patch 必须是可审核的 unified diff；只能修改现有 Python 实现文件，不能修改测试、配置或新增文件。"
            "没有足够证据时返回空字符串。不要臆造测试结果。",
            prompt,
        )
        if result:
            reproduction = str(result.get("reproduction_test") or reproduction)
            patch_plan = str(result.get("patch_plan") or patch_plan)
            patch = str(result.get("patch") or "")
            patch_source = "model" if patch else "none"
            warnings.extend(str(item) for item in result.get("warnings", []) if item)
            model_used = model.model
        else:
            reason = getattr(model, "last_error", None)
            suffix = f"（{reason}）" if reason else ""
            warnings.append(f"模型调用失败{suffix}，本次使用本地规则分析。")

    security_findings = scan_repository(repo)
    if security_findings:
        warnings.append(f"安全扫描发现 {len(security_findings)} 个候选问题，提交 PR 前需要人工复核。")

    tests = []
    verification_status = "not_run"
    security_findings_after = []
    snapshot_sha256 = _repository_digest(repo)

    if mode == "skip":
        tests.append(run_tests(repo, timeout=timeout, stage="baseline", mode="skip", framework=framework))
        verification_status = "skipped"
        warnings.append("当前请求未启用代码执行；如需验证，请在受控环境中选择 local 或 docker 模式。")
    else:
        with tempfile.TemporaryDirectory(prefix="osg-verify-") as temp_dir:
            baseline = Path(temp_dir) / "baseline"
            candidate = Path(temp_dir) / "candidate"
            snapshot(repo, baseline)
            snapshot(repo, candidate)
            generated_test = ""
            if _is_concrete_reproduction(reproduction):
                generated_test = _write_reproduction(baseline, reproduction)
                _write_reproduction(candidate, reproduction)
            baseline_test = test_path or generated_test
            baseline_result = run_tests(baseline, test_path=baseline_test, timeout=timeout, stage="baseline", mode=mode, framework=framework)
            tests.append(baseline_result)
            candidate_applied = False
            if patch:
                try:
                    apply_patch(candidate, patch)
                    candidate_applied = True
                except (OSError, ValueError, SyntaxError) as exc:
                    warnings.append(f"候选补丁未通过严格补丁校验：{exc}")
            if candidate_applied:
                candidate_result = run_tests(candidate, test_path=baseline_test, timeout=timeout, stage="candidate_patch", mode=mode, framework=framework)
                tests.append(candidate_result)
                # A patch is only considered verified when the focused reproduction
                # and the repository's pre-existing tests both pass in the candidate copy.
                if candidate_result.passed:
                    full_result = run_tests(candidate, timeout=timeout, stage="candidate_full", mode=mode, framework=framework)
                    tests.append(full_result)
                security_findings_after = scan_repository(candidate)
            if any(result.infrastructure_error for result in tests):
                verification_status = "infrastructure_error"
            elif candidate_applied and not baseline_test:
                verification_status = "needs_reproduction"
            elif candidate_applied and baseline_result.passed:
                verification_status = "not_reproduced"
            elif candidate_applied and len(tests) > 2 and tests[1].passed and tests[2].passed:
                verification_status = "verified"
            elif candidate_applied:
                verification_status = "candidate_failed"
            elif patch:
                verification_status = "patch_rejected"
            else:
                verification_status = "no_patch"

    next_actions = [
        "人工确认代码证据与 Issue 是否对应。",
        "把复现测试模板改成真实输入，并确认原始版本先失败。",
        "在隔离分支生成补丁，运行复现测试、全量测试和安全扫描。",
        "通过 GitHub/Gitee Draft PR 提交给维护者审核。",
    ]
    if verification_status == "verified":
        next_actions.insert(0, "候选补丁已在临时副本通过验证，可生成 Draft PR 供维护者审核。")
    return AnalysisReport(
        str(repo), analysis, evidence, reproduction, patch_plan, patch, tests, next_actions,
        security_findings=security_findings, model_used=model_used, warnings=warnings,
        verification_status=verification_status, execution_mode=mode,
        snapshot_sha256=snapshot_sha256, patch_source=patch_source,
        security_findings_after=security_findings_after,
        languages=languages, primary_language=primary_language,
        evidence_confidence=evidence_confidence,
    )
