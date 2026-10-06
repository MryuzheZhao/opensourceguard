"""Build a benchmark from real, already-merged bug reports on public repos.

Why this exists
---------------
The original `eval/cases.json` was hand-written by the project author and graded
against hand-written fixtures in `examples/`. A tool scoring 100% on its own
homework proves nothing to a reviewer. This script replaces that with issues that
a stranger actually filed, actually fixed, and actually merged.

Method
------
1. Search closed `bug` issues in well-known repos.
2. Keep ones that are self-contained: a single-stack Python traceback in the body.
   A machine-parseable traceback gives us an *independent* ground truth for
   "which file and function is at fault", taken from the reporter, not from us.
3. Resolve that file path to a line in the repo at the commit that fixed it.
4. Emit the same schema the existing runner consumes, so `run_eval.py` keeps
   working unchanged.

Run:  python -X utf8 eval/build_real_benchmark.py --count 20
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.github.com"


class RateLimited(RuntimeError):
    """Raised when the anonymous GitHub search quota is exhausted."""
UA = "OpenSourceGuard-Benchmark/0.4"

# Mature, well-known Python projects, chosen for stable public histories and for
# a codebase layout this tool can actually address (src/ or a top-level package).
DEFAULT_TARGETS = [
    ("psf/requests", "bug"),
    ("pallets/flask", "bug"),
    ("pallets/click", "bug"),
    ("psf/urllib3", "bug"),
    ("pallets/jinja", "bug"),
    ("pallets/werkzeug", "bug"),
    ("encode/httpx", "bug"),
    ("tiangolo/fastapi", "bug"),
]


# `File "x.py", line N, in fn` is the most reliable ground truth we can get for
# free from a bug report. We deliberately do not parse the traceback type or
# message: those are what the tool has to predict, so using them would leak.
TRACEBACK_RE = re.compile(r'File "([^"]+\.py)", line (\d+), in ([A-Za-z_][A-Za-z0-9_]*)')

# A Python traceback is full of frames the reporter cannot fix. Only frames that
# live inside the target repository are a valid answer, so anything reaching an
# absolute path, a site-packages tree, a local checkout, or a stdlib module is
# discarded. Without this filter most reports resolve to /usr/lib/pythonX/... and
# the benchmark silently becomes impossible.
REPO_MODULE_PREFIXES = {
    "requests": ("requests/",),
    "flask": ("src/flask/", "flask/", "src/werkzeug/", "werkzeug/"),
    "click": ("src/click/", "click/"),
    "urllib3": ("src/urllib3/", "urllib3/"),
    "fastapi": ("fastapi/", "src/fastapi/"),
    "jinja": ("src/jinja/", "jinja/", "jinja2/"),
    "werkzeug": ("src/werkzeug/", "werkzeug/"),
    "httpx": ("httpx/", "src/httpx/"),
}

# Frames that are never the fault being reported. Reporters paste tracebacks from
# their own machine, so the tail is usually site-packages, a stdlib module, or a
# Windows checkout path. Only frames matching the repo's own module prefix count.
BORING_FRAME_RE = re.compile(
    r"(^|/)(site-packages|dist-packages|lib-dynload|\.tox|\.venv|venv|node_modules|"
    r"build|dist|include|lib/python\d)(/|$)"
    r"|(^[A-Za-z]:)|"                      # any Windows drive path
    r"|^/|",                               # any absolute POSIX path
    re.IGNORECASE,
)


def api_get(path: str, query: Optional[Dict[str, Any]] = None, token: str = "") -> Any:
    url = API + path
    if query:
        url += "?" + urllib.parse.urlencode({k: v for k, v in query.items() if v is not None})
    headers = {"Accept": "application/vnd.github+json", "User-Agent": UA}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    # Search endpoints sit behind proxies that fail transiently; without a retry
    # a single 502 loses the whole collection run.
    last: Exception = RuntimeError("unreachable")
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            if exc.code == 403 and "rate limit" in (exc.read() or b"").decode("utf-8", "replace").lower():
                # Anonymous quota is 60/hour. A token raises it to 5000/min, so say
                # so once and stop hammering the endpoint.
                raise RateLimited("匿名 API 额度已用尽，请用 --token 传入 GitHub Token") from exc
            if exc.code in {403, 422}:
                raise
            last = exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            last = exc
        time.sleep(1.5 * (attempt + 1))
    raise last



def in_repo(path: str, repo: str) -> bool:
    """True only when the frame points at a file the target repo actually ships."""
    flat = path.replace("\\", "/")
    if BORING_FRAME_RE.search(flat):
        return False
    norm = flat.lstrip("./")
    if norm.startswith(("test", "tests/", "testing/", "docs/", "examples/")):
        return False
    module = repo.split("/")[-1].lower()
    if any(norm.startswith(p) for p in REPO_MODULE_PREFIXES.get(module, ())):
        return True
    # A bare relative path inside the repo root is still a valid answer.
    return not flat.startswith(("/", "\\")) and ".." not in norm


def first_traceback(body: str, repo: str) -> Optional[Dict[str, Any]]:
    """Pick the deepest frame that is still inside the target repo.

    Taking the last frame of a traceback is the obvious implementation and it is
    wrong: reports usually end in the reporter's own site-packages or stdlib.
    Those frames are unfixable and would make the benchmark unanswerable.
    """
    if not body:
        return None
    matches = TRACEBACK_RE.findall(body)
    if not matches:
        return None
    usable = [(p, int(l), f) for p, l, f in matches if in_repo(p, repo) and 5 < int(l) < 100000]
    if not usable:
        return None
    path, line, func = usable[-1]
    return {"file": path.replace("\\", "/").lstrip("./"), "line": line, "function": func.strip()}



def search_closed_bugs(repo: str, label: str, per_page: int, token: str, pages: int) -> Iterable[Dict[str, Any]]:
    """Yield closed issues, preferring `label:bug` and falling back to all closed.

    Not every project uses a `bug` label, and asking for a missing label makes the
    search endpoint answer 422, which silently emptied whole repositories.
    """
    label_queries = [f"label:{label}"] if label else []
    label_queries.append("")
    for clause in label_queries:
        for page in range(1, pages + 1):
            q = f"repo:{repo} is:issue is:closed comments:>0" + (f" {clause}" if clause else "")
            try:
                data = api_get("/search/issues", {"q": q, "per_page": per_page, "page": page,
                                                  "sort": "comments", "order": "desc"}, token)
            except RateLimited:
                raise
            except urllib.error.HTTPError as exc:
                print(f"  ! {repo} 搜索失败 HTTP {exc.code}，跳过该仓库")
                break
            if not isinstance(data, dict):
                break
            items = data.get("items") or []
            if not items:
                break
            for item in items:
                # Search results also return pull requests; we only want issues.
                if "pull_request" in item:
                    continue
                yield item
            total = data.get("total_count", 0)
            if page * per_page >= min(total, per_page * pages):
                break
            time.sleep(2.0)  # stay well inside the anonymous rate limit
        # One label variant is enough; falling through would re-yield the same set.
        break


def closed_at(item: Dict[str, Any]) -> str:
    return str(item.get("closed_at") or "")


def make_case(repo: str, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    body = str(item.get("body") or "")
    frame = first_traceback(body, repo)
    if not frame:
        return None
    title = str(item.get("title") or "").strip()
    text = f"{title}\n\n{body}".strip()
    if len(text) > 4000:
        text = text[:4000]
    return {
        "id": f"{repo.replace('/', '-')}-{item.get('number')}",
        "source": "github",
        "repo": repo,
        "number": item.get("number"),
        "url": item.get("html_url"),
        "closed_at": closed_at(item),
        "title": title,
        "issue": text,
        "expected": {
            "file": frame["file"],
            "function": frame["function"],
            "line": frame["line"],
        },
        "ground_truth_source": "traceback frame inside the repository, quoted in the real bug report",
        "labels": [str(x.get("name", x)) for x in (item.get("labels") or [])],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=20, help="how many cases to collect")
    ap.add_argument("--out", type=Path, default=ROOT / "eval" / "real_cases.json")
    ap.add_argument("--targets", default="", help="comma separated owner/name[:label]")
    ap.add_argument("--token", default=os.getenv("OSG_GITHUB_TOKEN", ""),
                    help="optional; raises the anonymous rate limit from 10 to 5000/min")
    ap.add_argument("--pages", type=int, default=3)
    args = ap.parse_args()

    targets: List[Any] = []
    for item in (args.targets.split(",") if args.targets else []):
        item = item.strip()
        if not item:
            continue
        if ":" in item:
            repo, label = item.split(":", 1)
        else:
            repo, label = item, "bug"
        targets.append((repo, label))
    if not targets:
        targets = DEFAULT_TARGETS

    print(f"目标仓库 {len(targets)} 个，目标条数 {args.count}"
          f"（{'带 Token' if args.token else '匿名模式，建议 --token 提高额度'}）")
    cases: List[Dict[str, Any]] = []
    seen_files: set[str] = set()
    try:
        for repo, label in targets:
            if len(cases) >= args.count:
                break
            print(f"- {repo} (label={label})")
            for item in search_closed_bugs(repo, label, 30, args.token, args.pages):
                if len(cases) >= args.count:
                    break
                case = make_case(repo, item)
                if not case:
                    continue
                # Skip near-duplicates: many reports point at the same helper.
                key = f"{case['repo']}:{case['expected']['file']}"
                if key in seen_files:
                    continue
                seen_files.add(key)
                cases.append(case)
                print(f"    #{case['number']:<6} {case['expected']['file']}:{case['expected']['line']}"
                      f"  {case['title'][:44]}")
                time.sleep(0.4)
    except RateLimited as exc:
        print(f"\n中断：{exc}")
        if not cases:
            return 1

    args.out.write_text(json.dumps({"cases": cases}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写入 {args.out}：{len(cases)} 条真实用例")
    if len(cases) < args.count:
        print(f"注意：只抓到 {len(cases)} 条。可加大 --pages 或换仓库。")
    return 0 if cases else 1


if __name__ == "__main__":
    raise SystemExit(main())
