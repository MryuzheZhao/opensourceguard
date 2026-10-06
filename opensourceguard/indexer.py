from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Dict, Iterable, List

from .languages import extract_symbols, is_test_path, language_of
from .types import CodeSymbol


STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "when", "should",
    "have", "has", "into", "return", "file", "error", "issue", "please",
    "读取", "应该", "发生", "导致", "一个", "这个", "时报", "崩溃",
}

SKIP_PARTS = {
    ".git", ".venv", "venv", "__pycache__", "node_modules", ".pytest_cache",
    "dist", "build", "target", "vendor", ".next", ".nuxt", "coverage",
    ".mypy_cache", ".tox", "bin", "obj",
}

# Bounded index so a large monorepo cannot stall the analysis.
MAX_FILES = 1200
MAX_SYMBOLS = 6000


def issue_keywords(text: str) -> List[str]:
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", text.lower())
    seen = []
    for token in tokens:
        if token not in STOPWORDS and token not in seen:
            seen.append(token)
    return seen[:20]


def _symbol_text(lines: List[str], start: int, end: int) -> str:
    return "".join(lines[start - 1:end])[:8000]


def _keywords(text: str) -> List[str]:
    return issue_keywords(text)


def _iter_source_files(repo: Path) -> Iterable[Path]:
    count = 0
    for path in sorted(repo.rglob("*")):
        if count >= MAX_FILES:
            return
        if not path.is_file() or path.is_symlink():
            continue
        if any(part in SKIP_PARTS for part in path.parts):
            continue
        if language_of(path) is None:
            continue
        try:
            if path.stat().st_size > 800_000:
                continue
        except OSError:
            continue
        count += 1
        yield path


def _index_python(repo: Path, path: Path, rel: str, source: str) -> List[CodeSymbol]:
    try:
        tree = ast.parse(source, filename=str(path))
    except (SyntaxError, ValueError):
        return []
    lines = source.splitlines(keepends=True)
    symbols = [CodeSymbol(rel, "<module>", "module", 1, max(1, len(lines)),
                          keywords=_keywords(source), text=source[:8000],
                          language="python", confidence="parsed")]
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        start = getattr(node, "lineno", 1)
        end = getattr(node, "end_lineno", start)
        text = _symbol_text(lines, start, end)
        kind = "class" if isinstance(node, ast.ClassDef) else "function"
        signature = text.splitlines()[0].strip() if text else node.name
        symbols.append(CodeSymbol(rel, node.name, kind, start, end, signature, text,
                                  _keywords(text), language="python", confidence="parsed"))
    return symbols


def _index_other(rel: str, source: str, language: str) -> List[CodeSymbol]:
    lines = source.splitlines(keepends=True)
    symbols = [CodeSymbol(rel, "<module>", "module", 1, max(1, len(lines)),
                          keywords=_keywords(source), text=source[:8000],
                          language=language, confidence="heuristic")]
    for raw in extract_symbols(source, language):
        text = _symbol_text(lines, raw.start_line, raw.end_line)
        symbols.append(CodeSymbol(rel, raw.name, raw.kind, raw.start_line, raw.end_line,
                                  raw.signature, text, _keywords(text),
                                  language=language, confidence=raw.confidence))
    return symbols


def index_repository(repo: Path) -> List[CodeSymbol]:
    """Build a dependency-free multi-language symbol index.

    Python uses the stdlib AST and is marked ``parsed``; every other language
    uses bounded regex scanners and is marked ``heuristic`` so downstream
    reports never overstate the confidence of a match.
    """
    symbols: List[CodeSymbol] = []
    for path in _iter_source_files(repo):
        language = language_of(path)
        if language is None:
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        rel = str(path.relative_to(repo)).replace("\\", "/")
        if language == "python":
            symbols.extend(_index_python(repo, path, rel, source))
        else:
            symbols.extend(_index_other(rel, source, language))
        if len(symbols) >= MAX_SYMBOLS:
            break
    return symbols[:MAX_SYMBOLS]


def language_breakdown(symbols: Iterable[CodeSymbol]) -> Dict[str, int]:
    """Count indexed files per language (module symbols represent whole files)."""
    counts: Dict[str, int] = {}
    for symbol in symbols:
        if symbol.kind != "module":
            continue
        counts[symbol.language] = counts.get(symbol.language, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def rank_symbols(symbols: Iterable[CodeSymbol], keywords: List[str], issue: str) -> List[CodeSymbol]:
    issue_lower = issue.lower()
    security_issue = any(word in issue_lower for word in ("security", "漏洞", "注入", "凭据", "硬编码", "命令"))
    ranked = []
    for symbol in symbols:
        haystack = " ".join([symbol.path, symbol.name, symbol.signature, symbol.text, *symbol.keywords]).lower()
        hits = sum(1 for key in keywords if key.lower() in haystack)
        exact_name = sum(2 for key in keywords if key.lower() == symbol.name.lower())
        # Tests are valuable corroborating evidence, but implementation symbols
        # should rank first when the same keywords appear in both places.
        is_test = is_test_path(symbol.path) or symbol.name.lower().startswith("test")
        test_bonus = -3 if is_test else 0
        error_bonus = 1 if any(word in issue_lower and word in haystack for word in ("crash", "error", "exception", "崩溃", "报错")) else 0
        risky_impl_bonus = 0
        if security_issue and not is_test and any(marker in haystack for marker in ("subprocess", "shell=true", "api_token", "password", "secret", "token")):
            risky_impl_bonus = 3
        # A precise declaration beats a whole-file match of the same strength.
        precision_bonus = 0.5 if symbol.kind != "module" else 0.0
        # Parsed symbols are more trustworthy than regex matches at equal score.
        confidence_bonus = 0.25 if symbol.confidence == "parsed" else 0.0
        score = hits + exact_name + test_bonus + error_bonus + risky_impl_bonus + precision_bonus + confidence_bonus
        if score > 0:
            ranked.append((score, symbol))
    ranked.sort(key=lambda item: (-item[0], item[1].path, item[1].start_line))
    return [symbol for _, symbol in ranked]
