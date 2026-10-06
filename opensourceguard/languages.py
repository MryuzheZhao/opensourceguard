"""Dependency-free multi-language symbol extraction.

Python keeps using the stdlib AST (exact). Other languages use bounded regex
scanners that are deliberately conservative: they report a symbol only when the
declaration line is unambiguous, and every symbol carries a ``confidence`` so
reports never present a heuristic match as if it were parsed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Pattern, Tuple

# Suffix -> language id. Keep this the single source of truth so the indexer,
# the security scanner and the health dashboard always agree on language names.
LANGUAGE_BY_SUFFIX: Dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
    ".kt": "kotlin",
    ".swift": "swift",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".sh": "shell",
    ".bash": "shell",
}

LANGUAGE_LABELS: Dict[str, str] = {
    "python": "Python",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "java": "Java",
    "go": "Go",
    "rust": "Rust",
    "ruby": "Ruby",
    "php": "PHP",
    "csharp": "C#",
    "kotlin": "Kotlin",
    "swift": "Swift",
    "c": "C",
    "cpp": "C++",
    "shell": "Shell",
}

# Test-file conventions per language, used to down-rank corroborating evidence.
TEST_MARKERS: Tuple[str, ...] = (
    "test_", "_test.", ".test.", ".spec.", "_spec.", "-test.", "-spec.",
    "__tests__", "__test__",
)

# Directory names that mark a whole subtree as tests.
TEST_DIRECTORIES: Tuple[str, ...] = ("tests", "test", "spec", "specs", "__tests__", "testing")


def language_of(path: Path) -> Optional[str]:
    """Return the canonical language id for a path, or None when unsupported."""
    return LANGUAGE_BY_SUFFIX.get(path.suffix.lower())


def language_label(language: str) -> str:
    return LANGUAGE_LABELS.get(language, language or "unknown")


def is_test_path(relative_path: str) -> bool:
    """Detect test files across language conventions.

    Handles filename markers (``test_a.py``, ``a.spec.ts``, ``a_spec.rb``),
    suffix conventions (``FooTest.java``, ``FooTests.cs``) and directory
    conventions (``tests/``, ``spec/``) including the first path segment.
    """
    normalized = relative_path.replace("\\", "/")
    lowered = normalized.lower()
    filename = lowered.rsplit("/", 1)[-1]
    stem = filename.rsplit(".", 1)[0]
    if stem.endswith(("test", "tests", "spec", "specs")) and stem not in {"test", "spec"}:
        return True
    if any(marker in filename for marker in TEST_MARKERS):
        return True
    segments = lowered.split("/")[:-1]
    return any(segment in TEST_DIRECTORIES for segment in segments)


@dataclass
class RawSymbol:
    """A declaration found by a language scanner, before ranking."""

    name: str
    kind: str
    start_line: int
    end_line: int
    signature: str
    confidence: str = "heuristic"


# Each entry: (kind, compiled pattern, group index holding the symbol name).
_DECLARATION_RULES: Dict[str, List[Tuple[str, Pattern[str], int]]] = {
    "javascript": [
        ("function", re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)"), 1),
        ("class", re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)"), 1),
        ("function", re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:function\b|\([^)]*\)\s*=>|[A-Za-z_$][\w$]*\s*=>)"), 1),
        ("method", re.compile(r"^\s{2,}(?:static\s+)?(?:async\s+)?(?:get\s+|set\s+)?([A-Za-z_$][\w$]*)\s*\([^;{]*\)\s*\{"), 1),
    ],
    "java": [
        ("class", re.compile(r"^\s*(?:public|protected|private|\s)*(?:final\s+|abstract\s+|static\s+)*(?:class|interface|enum|record)\s+([A-Za-z_$][\w$]*)"), 1),
        ("method", re.compile(r"^\s*(?:public|protected|private)\s+(?:static\s+|final\s+|synchronized\s+|abstract\s+|native\s+)*(?:<[^>]+>\s*)?[\w$<>\[\],.?\s]+\s+([A-Za-z_$][\w$]*)\s*\([^;)]*\)\s*(?:throws\s[\w$.,\s]+)?\{"), 1),
    ],
    "go": [
        ("function", re.compile(r"^func\s+([A-Za-z_][\w]*)\s*\("), 1),
        ("method", re.compile(r"^func\s*\([^)]*\)\s*([A-Za-z_][\w]*)\s*\("), 1),
        ("type", re.compile(r"^type\s+([A-Za-z_][\w]*)\s+(?:struct|interface|func|map|\[|\*|[A-Za-z_])"), 1),
    ],
    "rust": [
        ("function", re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:const\s+|async\s+|unsafe\s+|extern\s+\"[^\"]*\"\s+)*fn\s+([A-Za-z_][\w]*)"), 1),
        ("type", re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:struct|enum|trait|union)\s+([A-Za-z_][\w]*)"), 1),
        ("impl", re.compile(r"^\s*impl(?:<[^>]*>)?\s+(?:[\w:<>, ]+\s+for\s+)?([A-Za-z_][\w]*)"), 1),
    ],
    "ruby": [
        ("class", re.compile(r"^\s*(?:class|module)\s+([A-Z][\w:]*)"), 1),
        ("function", re.compile(r"^\s*def\s+(?:self\.)?([A-Za-z_][\w]*[?!=]?)"), 1),
    ],
    "php": [
        ("class", re.compile(r"^\s*(?:abstract\s+|final\s+)?(?:class|interface|trait|enum)\s+([A-Za-z_][\w]*)"), 1),
        ("function", re.compile(r"^\s*(?:(?:public|protected|private)\s+)?(?:static\s+)?function\s+&?([A-Za-z_][\w]*)\s*\("), 1),
    ],
    "csharp": [
        ("class", re.compile(r"^\s*(?:public|internal|protected|private|\s)*(?:sealed\s+|abstract\s+|static\s+|partial\s+)*(?:class|interface|struct|enum|record)\s+([A-Za-z_][\w]*)"), 1),
        ("method", re.compile(r"^\s*(?:public|internal|protected|private)\s+(?:static\s+|virtual\s+|override\s+|async\s+|sealed\s+)*[\w<>\[\],.?]+\s+([A-Za-z_][\w]*)\s*\([^;)]*\)\s*\{?"), 1),
    ],
    "kotlin": [
        ("function", re.compile(r"^\s*(?:(?:public|internal|private|protected)\s+)?(?:suspend\s+|inline\s+|open\s+|override\s+)*fun\s+(?:<[^>]+>\s*)?([A-Za-z_][\w]*)"), 1),
        ("class", re.compile(r"^\s*(?:(?:public|internal|private|protected)\s+)?(?:data\s+|sealed\s+|open\s+|abstract\s+|enum\s+)*(?:class|object|interface)\s+([A-Za-z_][\w]*)"), 1),
    ],
    "swift": [
        ("function", re.compile(r"^\s*(?:(?:public|private|internal|fileprivate|open)\s+)?(?:static\s+|class\s+|mutating\s+|override\s+)*func\s+([A-Za-z_][\w]*)"), 1),
        ("class", re.compile(r"^\s*(?:(?:public|private|internal|fileprivate|open)\s+)?(?:final\s+)?(?:class|struct|enum|protocol|actor)\s+([A-Za-z_][\w]*)"), 1),
    ],
    "c": [
        ("function", re.compile(r"^[A-Za-z_][\w\s\*]*?\b([A-Za-z_][\w]*)\s*\([^;)]*\)\s*\{"), 1),
        ("type", re.compile(r"^\s*typedef\s+(?:struct|union|enum)?\s*[\w\s\*]*?\b([A-Za-z_][\w]*)\s*;"), 1),
    ],
    "shell": [
        ("function", re.compile(r"^\s*(?:function\s+)?([A-Za-z_][\w-]*)\s*\(\s*\)\s*\{"), 1),
    ],
}

# TypeScript reuses the JavaScript rules plus its own declaration forms.
_DECLARATION_RULES["typescript"] = _DECLARATION_RULES["javascript"] + [
    ("type", re.compile(r"^\s*(?:export\s+)?(?:declare\s+)?(?:interface|type|enum)\s+([A-Za-z_$][\w$]*)"), 1),
]
_DECLARATION_RULES["cpp"] = _DECLARATION_RULES["c"] + [
    ("class", re.compile(r"^\s*(?:class|struct)\s+([A-Za-z_][\w]*)\s*(?:final\s*)?(?::|\{)"), 1),
    ("namespace", re.compile(r"^\s*namespace\s+([A-Za-z_][\w]*)"), 1),
]

# Lines that look like declarations but are control flow or noise.
# Kept language-aware: ``new`` is noise in C++/Java but a real constructor name
# in Rust, and ``print`` is a builtin in Python but a valid method name elsewhere.
_NOISE_NAMES = {
    "if", "for", "while", "switch", "catch", "return", "else", "do", "try",
    "case", "sizeof", "typedef", "struct", "union", "enum",
    "function", "class", "import", "export", "require",
}

_LANGUAGE_NOISE: Dict[str, set[str]] = {
    "javascript": {"constructor", "new", "delete", "await", "yield", "typeof"},
    "typescript": {"constructor", "new", "delete", "await", "yield", "typeof"},
    "java": {"new", "this", "super", "synchronized", "instanceof"},
    "csharp": {"new", "this", "base", "using", "lock"},
    "cpp": {"new", "delete", "operator", "template", "namespace", "using"},
    "c": {"new", "goto", "static", "extern", "const", "inline"},
    "go": {"range", "defer", "go", "select", "chan", "map"},
    "php": {"new", "echo", "print", "isset", "unset"},
    "ruby": {"end", "begin", "rescue", "ensure", "yield"},
    "shell": {"then", "fi", "esac", "done", "elif"},
    # Rust deliberately has no "new" entry: Config::new is a real constructor.
    "rust": {"match", "loop", "where", "mod", "use", "crate"},
    "kotlin": {"when", "companion", "init", "constructor"},
    "swift": {"guard", "defer", "init", "deinit", "subscript"},
}

_MAX_BYTES = 800_000
_MAX_LINES = 20_000


def _strip_comment(line: str, language: str) -> str:
    """Remove trailing line comments so declarations inside comments are skipped."""
    if language in {"python", "ruby", "shell"}:
        marker = "#"
    else:
        marker = "//"
    index = line.find(marker)
    if index == -1:
        return line
    # Keep the line when the marker is inside a quoted string.
    prefix = line[:index]
    if prefix.count('"') % 2 or prefix.count("'") % 2:
        return line
    return prefix


def _block_end(lines: List[str], start_index: int, language: str) -> int:
    """Estimate the end line of a brace- or indentation-delimited block."""
    if language in {"ruby", "shell"}:
        # Both use keyword/brace terminators; fall back to a bounded window.
        return min(len(lines), start_index + 40)
    opened = 0
    seen_brace = False
    for offset in range(start_index, min(len(lines), start_index + 400)):
        stripped = _strip_comment(lines[offset], language)
        opened += stripped.count("{") - stripped.count("}")
        if "{" in stripped:
            seen_brace = True
        if seen_brace and opened <= 0:
            return offset + 1
    return min(len(lines), start_index + 40)


def extract_symbols(source: str, language: str) -> List[RawSymbol]:
    """Extract declarations for a non-Python language.

    Returns an empty list for unsupported languages and for files large enough
    that scanning them would dominate the analysis budget.
    """
    rules = _DECLARATION_RULES.get(language)
    if not rules or len(source) > _MAX_BYTES:
        return []
    noise = _NOISE_NAMES | _LANGUAGE_NOISE.get(language, set())
    lines = source.splitlines()
    if len(lines) > _MAX_LINES:
        return []
    found: List[RawSymbol] = []
    seen: set[Tuple[str, int]] = set()
    in_block_comment = False
    for index, raw_line in enumerate(lines):
        stripped = raw_line.strip()
        if in_block_comment:
            if "*/" in stripped:
                in_block_comment = False
            continue
        if stripped.startswith("/*") and "*/" not in stripped:
            in_block_comment = True
            continue
        if not stripped or stripped.startswith(("//", "#", "*", "/*")):
            continue
        line = _strip_comment(raw_line, language)
        for kind, pattern, group in rules:
            match = pattern.match(line)
            if not match:
                continue
            name = match.group(group)
            if not name or name in noise:
                continue
            key = (name, index + 1)
            if key in seen:
                continue
            seen.add(key)
            found.append(RawSymbol(
                name=name,
                kind=kind,
                start_line=index + 1,
                end_line=_block_end(lines, index, language),
                signature=stripped[:200],
                confidence="heuristic",
            ))
            break
    return found


def detect_languages(files: List[str]) -> Dict[str, int]:
    """Count supported source files per language from relative paths."""
    counts: Dict[str, int] = {}
    for relative in files:
        language = LANGUAGE_BY_SUFFIX.get(Path(relative).suffix.lower())
        if language:
            counts[language] = counts.get(language, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))
