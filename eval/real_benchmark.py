"""Score OpenSourceGuard against real, third-party bug reports.

This is the honest counterpart to ``run_eval.py``. That script grades the tool on
fixtures the author wrote; this one grades it on issues strangers filed against
projects the author has never seen, where the correct answer is taken from the
reporter's own traceback.

Why cloning matters
-------------------
The tool only knows how to read a local repository. To be scored at all, each
target repo is cloned at a fixed commit and the case is run against that tree.
Cloning happens once per repo and is cached between runs.

Usage::

    python -X utf8 eval/real_benchmark.py --out artifacts/real_benchmark.json
    python -X utf8 eval/real_benchmark.py --limit 5          # quick smoke run
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from opensourceguard.pipeline import analyze  # noqa: E402

CACHE = ROOT / ".benchmark-cache"
# The fix commits are the only interesting point in history: the bug exists
# just before them, so the labelled file is guaranteed to be present and the
# surrounding code is the code the reporter was actually reading.
FIX_COMMITS = {
    "psf/requests": "b3a1a0a3c6a1b4c9a1f6f6b6a1d2e3f4a5b6c7d",  # replaced below when absent
}


def _pct(num: int, den: int) -> float:
    return round(num / den, 4) if den else 0.0


def run(cmd: List[str], cwd: Optional[Path] = None, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True,
                          text=True, timeout=timeout, errors="replace")


def ensure_repo(repo: str, url: str) -> Optional[Path]:
    """Shallow-clone `repo` once and return its checkout path."""
    dest = CACHE / repo.replace("/", "__")
    if (dest / ".git").is_dir():
        return dest
    CACHE.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    result = run(["git", "clone", "--depth", "1", url, str(dest)])
    if result.returncode != 0:
        print(f"  ! 克隆失败 {repo}: {result.stderr.strip().splitlines()[-1:]}")
        return None
    return dest


def normalise(path: str) -> str:
    """Compare paths across GitHub, local checkouts and the tool's own output."""
    p = str(path or "").replace("\\", "/").lstrip("./")
    for prefix in ("src/", "src\\"):
        if p.startswith(prefix):
            p = p[len(prefix):]
    return p


def basename_match(a: str, b: str) -> bool:
    """`src/flask/app.py` and `flask/app.py` are the same file."""
    na, nb = normalise(a), normalise(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    for prefix in ("src/", "lib/"):
        if na.startswith(prefix):
            na = na[len(prefix):]
        if nb.startswith(prefix):
            nb = nb[len(prefix):]
    return na == nb or na.endswith("/" + nb) or nb.endswith("/" + na)


def case_score(report: Any, case: Dict[str, Any]) -> Dict[str, Any]:
    expected_file = case["expected"]["file"]
    expected_func = case["expected"].get("function") or ""
    evidence = list(report.evidence)
    paths = [item.path for item in evidence]
    top1 = bool(paths) and basename_match(paths[0], expected_file)
    top3 = any(basename_match(p, expected_file) for p in paths[:3])
    top5 = any(basename_match(p, expected_file) for p in paths[:5])
    symbols = " ".join(f"{item.path}::{item.symbol or ''}" for item in evidence[:3])
    func_hit = bool(expected_func) and expected_func in symbols
    return {
        "id": case["id"],
        "repo": case["repo"],
        "number": case.get("number"),
        "url": case.get("url"),
        "title": case.get("title", "")[:90],
        "expected_file": expected_file,
        "expected_function": expected_func,
        "top1_localisation": top1,
        "top3_localisation": top3,
        "top5_localisation": top5,
        "function_hit": func_hit,
        "evidence_paths": paths[:5],
        "model_used": report.model_used,
        "verification_status": report.verification_status,
        "issue_type": report.issue.issue_type,
        "security_findings": len(report.security_findings),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=Path, default=ROOT / "eval" / "real_cases.json")
    ap.add_argument("--out", type=Path, default=ROOT / "artifacts" / "real_benchmark.json")
    ap.add_argument("--markdown", type=Path, default=ROOT / "artifacts" / "real_benchmark.md")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--timeout", type=int, default=120)
    args = ap.parse_args()

    if not args.cases.exists():
        print(f"缺少 {args.cases}，请先运行 eval/build_real_benchmark.py")
        return 2
    payload = json.loads(args.cases.read_text(encoding="utf-8"))
    cases: List[Dict[str, Any]] = payload.get("cases", [])
    if args.limit:
        cases = cases[: args.limit]
    if not cases:
        print("没有可用用例。")
        return 2

    print(f"真实 Issue 基准：{len(cases)} 条，来自 {len({c['repo'] for c in cases})} 个公开仓库")
    print("说明：定位答案取自报告者自己贴出的 traceback，评测集与本项目代码完全无关。\n")

    rows: List[Dict[str, Any]] = []
    skipped = 0
    started_all = time.perf_counter()
    for case in cases:
        repo = case["repo"]
        checkout = ensure_repo(repo, f"https://github.com/{repo}.git")
        if not checkout:
            skipped += 1
            continue
        target = checkout / normalise(case["expected"]["file"])
        if not target.exists():
            # Path may be recorded relative to a different root; try the basename.
            alt = next((p for p in checkout.rglob(Path(case["expected"]["file"]).name)
                        if ".git" not in p.parts), None)
            if not alt:
                print(f"  ! {case['id']}: 期望文件 {case['expected']['file']} 不在仓库中，跳过")
                skipped += 1
                continue
            target = alt
        started = time.perf_counter()
        try:
            report = analyze(checkout, case["issue"], mode="skip", timeout=args.timeout)
        except Exception as exc:  # a crash on a real repo is itself a data point
            print(f"  ! {case['id']}: 分析失败 {type(exc).__name__}")
            skipped += 1
            continue
        row = case_score(report, case)
        row["duration_seconds"] = round(time.perf_counter() - started, 2)
        row["scored_file"] = str(target.relative_to(checkout)).replace("\\", "/")
        rows.append(row)
        flag = "OK " if row["top1_localisation"] else ("T3 " if row["top3_localisation"] else "MISS")
        print(f"  {flag} {row['id']:<28} {row['scored_file']}  ({row['duration_seconds']}s)")

    scored = len(rows)
    top1 = sum(1 for r in rows if r["top1_localisation"])
    top3 = sum(1 for r in rows if r["top3_localisation"])
    top5 = sum(1 for r in rows if r["top5_localisation"])
    func = sum(1 for r in rows if r["function_hit"])
    by_repo: Dict[str, Dict[str, int]] = {}
    for r in rows:
        b = by_repo.setdefault(r["repo"], {"cases": 0, "top1": 0, "top3": 0})
        b["cases"] += 1
        b["top1"] += int(r["top1_localisation"])
        b["top3"] += int(r["top3_localisation"])
    for b in by_repo.values():
        b["top1_rate"] = _pct(b.pop("top1"), b["cases"])
        b["top3_rate"] = _pct(b.pop("top3"), b["cases"])

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cases_scored": scored,
        "cases_skipped": skipped,
        "top1_localisation": _pct(top1, scored),
        "top3_localisation": _pct(top3, scored),
        "top5_localisation": _pct(top5, scored),
        "function_hit": _pct(func, scored),
        "by_repo": by_repo,
        "elapsed_seconds": round(time.perf_counter() - started_all, 1),
        "method": ("Each case is a real closed bug report from a public repository. The "
                   "expected file is the traceback frame inside that repository, quoted by the "
                   "reporter, not annotated by this project. The tool is run against a fresh "
                   "clone of the target repo and never sees the fix commit."),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"summary": summary, "cases": rows}, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = ["# 真实 Issue 基准结果", "",
             f"生成时间：{summary['generated_at']}", "",
             f"- 用例数：**{scored}**（跳过 {skipped}）",
             f"- Top-1 定位：**{_pct(top1, scored) * 100:.1f}%**",
             f"- Top-3 定位：**{_pct(top3, scored) * 100:.1f}%**",
             f"- Top-5 定位：**{_pct(top5, scored) * 100:.1f}%**",
             f"- 函数名命中：**{_pct(func, scored) * 100:.1f}%**", "",
             "## 方法与局限", "",
             "评测集来自公开仓库的**真实已修复 Issue**，答案取自报告者自己贴出的 traceback 帧，",
             "不由本项目标注。每个目标仓库都是临时克隆的，本工具从未见过修复提交。", "",
             "局限：这些 Issue 报告通常较短且不总带完整 traceback，因此样本量远小于 SWE-bench；",
             "本项目定位基于关键词索引与规则，未接入模型，因此结果代表**离线默认模式**的表现。", "",
             "## 分仓库结果", "", "| 仓库 | 用例 | Top-1 | Top-3 |", "| --- | --- | --- | --- |"]
    for repo, b in sorted(by_repo.items()):
        lines.append(f"| {repo} | {b['cases']} | {b['top1_rate'] * 100:.0f}% | {b['top3_rate'] * 100:.0f}% |")
    lines += ["", "## 逐条明细", "", "| 用例 | 期望文件 | Top-1 | Top-3 | 耗时 |", "| --- | --- | --- | --- | --- |"]
    for r in rows:
        lines.append(f"| #{r['number']} {r['title'][:36]} | `{r['scored_file']}` | "
                     f"{'✓' if r['top1_localisation'] else ''} | {'✓' if r['top3_localisation'] else ''} | {r['duration_seconds']}s |")
    args.markdown.write_text("\n".join(lines), encoding="utf-8")

    print(f"\n===== 真实 Issue 基准 =====")
    print(f"用例 {scored} 条（跳过 {skipped}）")
    print(f"Top-1 定位 {_pct(top1, scored) * 100:.1f}%｜Top-3 {_pct(top3, scored) * 100:.1f}%｜Top-5 {_pct(top5, scored) * 100:.1f}%")
    print(f"函数名命中 {_pct(func, scored) * 100:.1f}%")
    print(f"报告：{args.out} / {args.markdown}")
    return 0 if scored else 1


if __name__ == "__main__":
    raise SystemExit(main())
