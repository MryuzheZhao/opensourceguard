"""Reproducible benchmark for OpenSourceGuard.

Runs every case in ``cases.json`` and reports quantitative metrics:

* ``top1_localisation``  – top evidence file matches the expected file
* ``top3_localisation``  – expected file appears in the top 3 evidence entries
* ``symbol_accuracy``    – top evidence symbol matches the expected symbol
* ``security_recall``    – expected security rules that actually fired
* ``false_positive_rate``– findings reported on the clean negative control
* ``issue_type_accuracy``– Issue classification matches the label
* ``patch_rate`` / ``verified_rate`` – candidate patch produced / verified by tests

Every metric is computed from a labelled fixture in ``examples/``, so the run is
fully offline and reproducible. These numbers describe this fixture set only and
are not comparable to public benchmarks such as SWE-bench.

Usage::

    python eval/run_eval.py                     # summary to stdout
    python eval/run_eval.py --output artifacts/benchmark.json
    python eval/run_eval.py --markdown artifacts/benchmark.md
    python eval/run_eval.py --execute local     # also run tests for verification
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from opensourceguard.pipeline import analyze  # noqa: E402


def _percentage(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def run_case(case: Dict[str, Any], execute: str, timeout: int) -> Dict[str, Any]:
    """Run one benchmark case and score it against its labels."""
    started = time.perf_counter()
    report = analyze(ROOT / case["repo"], case["issue"], mode=execute, timeout=timeout)
    elapsed = round(time.perf_counter() - started, 3)

    evidence_paths = [item.path for item in report.evidence]
    top_path = evidence_paths[0] if evidence_paths else None
    top_symbol = report.evidence[0].symbol if report.evidence else None
    expected_path = case.get("expected_path")

    top1 = top_path == expected_path
    top3 = expected_path in evidence_paths[:3] if expected_path else False
    expected_symbol = case.get("expected_symbol")
    symbol_hit = bool(expected_symbol) and top_symbol == expected_symbol

    fired_rules = sorted({finding.rule_id for finding in report.security_findings})
    expected_rules = case.get("expected_rules", [])
    matched_rules = [rule for rule in expected_rules if rule in fired_rules]

    # For the negative control any finding above "low" is a false positive.
    unexpected = [
        finding.rule_id for finding in report.security_findings
        if finding.severity in {"high", "medium"}
    ] if case.get("expect_no_findings") else []

    issue_type_hit = report.issue.issue_type == case.get("expected_issue_type")
    has_patch = bool(report.patch.strip())
    verified = report.verification_status == "verified"

    return {
        "id": case["id"],
        "category": case["category"],
        "language": case.get("language", ""),
        "issue": case["issue"],
        "expected_path": expected_path,
        "top_path": top_path,
        "evidence_paths": evidence_paths[:3],
        "expected_symbol": expected_symbol,
        "top_symbol": top_symbol,
        "top1_localisation": top1,
        "top3_localisation": top3,
        "symbol_hit": symbol_hit,
        "symbol_checked": bool(expected_symbol),
        "expected_rules": expected_rules,
        "fired_rules": fired_rules,
        "matched_rules": matched_rules,
        "unexpected_findings": unexpected,
        "issue_type": report.issue.issue_type,
        "expected_issue_type": case.get("expected_issue_type"),
        "issue_type_hit": issue_type_hit,
        "has_patch": has_patch,
        "expect_patch": case.get("expect_patch", False),
        "verification_status": report.verification_status,
        "verified": verified,
        "expect_verified": case.get("expect_verified", False),
        "evidence_confidence": report.evidence_confidence,
        "primary_language": report.primary_language,
        "model_used": report.model_used,
        "duration_seconds": elapsed,
    }


def summarise(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate per-case results into headline metrics."""
    localisation_rows = [row for row in rows if row["expected_path"]]
    symbol_rows = [row for row in rows if row["symbol_checked"]]
    security_rows = [row for row in rows if row["expected_rules"]]
    negative_rows = [row for row in rows if row["category"] == "negative"]
    patch_rows = [row for row in rows if row["expect_patch"]]
    verify_rows = [row for row in rows if row["expect_verified"]]

    expected_rule_total = sum(len(row["expected_rules"]) for row in security_rows)
    matched_rule_total = sum(len(row["matched_rules"]) for row in security_rows)
    false_positive_total = sum(len(row["unexpected_findings"]) for row in negative_rows)

    by_category: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        bucket = by_category.setdefault(row["category"], {"cases": 0, "top1": 0})
        bucket["cases"] += 1
        bucket["top1"] += int(row["top1_localisation"])
    for bucket in by_category.values():
        bucket["top1_localisation"] = _percentage(bucket.pop("top1"), bucket["cases"])

    by_language: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        language = row["language"] or "unknown"
        bucket = by_language.setdefault(language, {"cases": 0, "top1": 0})
        bucket["cases"] += 1
        bucket["top1"] += int(row["top1_localisation"])
    for bucket in by_language.values():
        bucket["top1_localisation"] = _percentage(bucket.pop("top1"), bucket["cases"])

    return {
        "cases": len(rows),
        "top1_localisation": _percentage(
            sum(row["top1_localisation"] for row in localisation_rows), len(localisation_rows)),
        "top3_localisation": _percentage(
            sum(row["top3_localisation"] for row in localisation_rows), len(localisation_rows)),
        "symbol_accuracy": _percentage(
            sum(row["symbol_hit"] for row in symbol_rows), len(symbol_rows)),
        "security_recall": _percentage(matched_rule_total, expected_rule_total),
        "issue_type_accuracy": _percentage(
            sum(row["issue_type_hit"] for row in rows), len(rows)),
        "false_positives_on_clean_repo": false_positive_total,
        "patch_rate": _percentage(sum(row["has_patch"] for row in patch_rows), len(patch_rows)),
        "verified_rate": _percentage(sum(row["verified"] for row in verify_rows), len(verify_rows)),
        "total_duration_seconds": round(sum(row["duration_seconds"] for row in rows), 3),
        "by_category": by_category,
        "by_language": by_language,
        "counts": {
            "localisation_cases": len(localisation_rows),
            "symbol_cases": len(symbol_rows),
            "security_cases": len(security_rows),
            "negative_cases": len(negative_rows),
            "expected_rules": expected_rule_total,
            "matched_rules": matched_rule_total,
        },
    }


def regressions(rows: List[Dict[str, Any]], execute: str = "skip") -> List[str]:
    """List cases that failed their own expectations.

    Patch-verification expectations only apply when the run actually executes
    tests; in ``skip`` mode no verification can happen by design.
    """
    failures = []
    for row in rows:
        if row["expected_path"] and not row["top3_localisation"]:
            failures.append(f"{row['id']}：预期文件 {row['expected_path']} 未出现在前 3 条证据中")
        missing = [rule for rule in row["expected_rules"] if rule not in row["fired_rules"]]
        if missing:
            failures.append(f"{row['id']}：安全规则未命中 {', '.join(missing)}")
        if row["unexpected_findings"]:
            failures.append(
                f"{row['id']}：干净仓库上报出 {len(row['unexpected_findings'])} 个中/高风险误报")
        if row["expect_patch"] and not row["has_patch"]:
            failures.append(f"{row['id']}：预期生成候选补丁但结果为空")
        if execute != "skip" and row["expect_verified"] and not row["verified"]:
            failures.append(
                f"{row['id']}：预期验证通过，实际为 {row['verification_status']}")
    return failures


def to_markdown(result: Dict[str, Any]) -> str:
    summary = result["summary"]
    lines = [
        "# OpenSourceGuard 评测基准报告",
        "",
        f"- 运行时间：{result['generated_at']}",
        f"- 执行模式：`{result['execute_mode']}`",
        f"- Python：{result['python_version']}（{result['platform']}）",
        f"- 用例数量：{summary['cases']}",
        f"- 总耗时：{summary['total_duration_seconds']} 秒",
        "",
        "## 核心指标",
        "",
        "| 指标 | 数值 | 说明 |",
        "|---|---|---|",
        f"| Top-1 定位准确率 | {summary['top1_localisation']:.0%} | 首条证据文件与标注一致 |",
        f"| Top-3 定位准确率 | {summary['top3_localisation']:.0%} | 标注文件出现在前 3 条证据 |",
        f"| 符号级准确率 | {summary['symbol_accuracy']:.0%} | 首条证据的函数/方法名与标注一致 |",
        f"| 安全规则召回率 | {summary['security_recall']:.0%} | "
        f"{summary['counts']['matched_rules']}/{summary['counts']['expected_rules']} 条预期规则命中 |",
        f"| Issue 分类准确率 | {summary['issue_type_accuracy']:.0%} | bug / security / feature 判定 |",
        f"| 干净仓库误报数 | {summary['false_positives_on_clean_repo']} | 负对照组上的中/高风险误报 |",
        f"| 补丁生成率 | {summary['patch_rate']:.0%} | 标注可修复的用例中产出候选补丁 |",
        f"| 补丁验证通过率 | {summary['verified_rate']:.0%} | 复现测试与全量测试同时通过 |",
        "",
        "## 分语言表现",
        "",
        "| 语言 | 用例数 | Top-1 定位 |",
        "|---|---|---|",
    ]
    for language, bucket in sorted(result["summary"]["by_language"].items()):
        lines.append(f"| {language} | {bucket['cases']} | {bucket['top1_localisation']:.0%} |")
    lines += [
        "",
        "## 分类表现",
        "",
        "| 类别 | 用例数 | Top-1 定位 |",
        "|---|---|---|",
    ]
    for category, bucket in sorted(result["summary"]["by_category"].items()):
        lines.append(f"| {category} | {bucket['cases']} | {bucket['top1_localisation']:.0%} |")
    lines += ["", "## 逐用例明细", "",
              "| 用例 | 语言 | 定位 | 符号 | 命中规则 | 验证状态 | 耗时(s) |", "|---|---|---|---|---|---|---|"]
    for row in result["rows"]:
        localisation = "✅" if row["top1_localisation"] else ("△" if row["top3_localisation"] else "❌")
        symbol = "—" if not row["symbol_checked"] else ("✅" if row["symbol_hit"] else "❌")
        rules = ", ".join(row["matched_rules"]) or "—"
        lines.append(f"| {row['id']} | {row['language'] or '—'} | {localisation} | {symbol} "
                     f"| {rules} | {row['verification_status']} | {row['duration_seconds']} |")
    if result["regressions"]:
        lines += ["", "## 未达预期的用例", ""] + [f"- {item}" for item in result["regressions"]]
    else:
        lines += ["", "## 未达预期的用例", "", "全部用例均满足标注预期。"]
    lines += [
        "",
        "## 边界说明",
        "",
        "- 本基准使用 `examples/` 下的自建标注用例，衡量的是本工具在这些用例上的表现，"
        "不能与 SWE-bench 等公开基准直接比较。",
        "- 非 Python 语言使用启发式符号定位，证据位置可能存在偏移。",
        "- 未配置模型 API 时全部走本地规则；配置模型后指标会随模型能力变化。",
        "- `--execute skip`（默认）不运行仓库代码，因此补丁验证通过率为 0；"
        "需要验证请使用 `--execute local` 或 `--execute docker`。",
        "",
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="运行 OpenSourceGuard 评测基准")
    parser.add_argument("--cases", type=Path, default=Path(__file__).parent / "cases.json")
    parser.add_argument("--output", type=Path, help="写入 JSON 结果")
    parser.add_argument("--markdown", type=Path, help="写入 Markdown 报告")
    parser.add_argument("--execute", choices=["skip", "local", "docker"], default="skip",
                        help="是否实际运行测试来验证补丁（默认 skip）")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--fail-on-regression", action="store_true",
                        help="存在未达预期的用例时返回非零退出码，便于 CI 使用")
    args = parser.parse_args(argv)

    try:
        cases = json.loads(args.cases.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"无法读取用例文件 {args.cases}：{exc}")
        return 2
    if not isinstance(cases, list) or not cases:
        print("用例文件必须是非空 JSON 数组")
        return 2

    rows = [run_case(case, args.execute, args.timeout) for case in cases]
    result = {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "execute_mode": args.execute,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "summary": summarise(rows),
        "regressions": regressions(rows, args.execute),
        "rows": rows,
    }

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON 结果已写入：{args.output}")
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(to_markdown(result), encoding="utf-8")
        print(f"Markdown 报告已写入：{args.markdown}")
    if not args.output and not args.markdown:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        summary = result["summary"]
        print(f"用例 {summary['cases']} 个｜Top-1 定位 {summary['top1_localisation']:.0%}"
              f"｜Top-3 定位 {summary['top3_localisation']:.0%}"
              f"｜安全召回 {summary['security_recall']:.0%}"
              f"｜误报 {summary['false_positives_on_clean_repo']}")
        for item in result["regressions"]:
            print(f"  未达预期：{item}")

    if args.fail_on_regression and result["regressions"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
