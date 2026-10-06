"""Strict unified-diff application: existing Python implementation files only."""
from __future__ import annotations

import ast
import re
from pathlib import Path, PurePosixPath


def apply_patch(repo: Path, diff: str) -> list[str]:
    if not diff or len(diff) > 100_000:
        raise ValueError("补丁为空或超过大小限制。")
    lines = diff.splitlines(keepends=True)
    cursor, edits = 0, 0
    staged = {}
    while cursor < len(lines):
        if not lines[cursor].startswith("--- a/") or cursor + 1 >= len(lines):
            raise ValueError("仅支持带 --- a/ 和 +++ b/ 标头的 unified diff。")
        name = lines[cursor][6:].rstrip("\r\n")
        if lines[cursor + 1].rstrip("\r\n") != "+++ b/" + name:
            raise ValueError("不允许重命名或新建源文件。")
        rel = PurePosixPath(name)
        if (not name or "\\" in name or ":" in name or rel.is_absolute()
                or ".." in rel.parts or any(x.startswith(".") for x in rel.parts)
                or rel.suffix != ".py" or any(x in {"tests", "test"} for x in rel.parts)
                or rel.name.startswith("test_") or rel.name.endswith("_test.py")
                or rel.name in {"conftest.py", "setup.py"}):
            raise ValueError("补丁只能修改仓库内现有的 Python 实现文件，不能修改测试或配置。")
        target = repo / name
        if not target.resolve().is_relative_to(repo.resolve()) or target.is_symlink() or not target.is_file():
            raise ValueError("补丁路径越界或目标不存在。")
        if name in staged or len(staged) >= 3:
            raise ValueError("补丁最多修改三个文件，且不允许重复文件段。")
        original = target.read_text(encoding="utf-8").splitlines(keepends=True)
        result, consumed, hunks = [], 0, 0
        cursor += 2
        while cursor < len(lines) and lines[cursor].startswith("@@"):
            match = re.fullmatch(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@[^\n]*\n?", lines[cursor])
            if not match:
                raise ValueError("补丁 hunk 标头无效。")
            start, old_count = int(match[1]), int(match[2] or 1)
            new_start, new_count = int(match[3]), int(match[4] or 1)
            offset = start - 1 if old_count else start
            if not consumed <= offset <= len(original):
                raise ValueError("补丁行号重叠或越界。")
            result.extend(original[consumed:offset])
            if new_start != (len(result) + 1 if new_count else len(result)):
                raise ValueError("补丁目标行号不一致。")
            consumed = offset
            cursor += 1
            seen_old = seen_new = 0
            while cursor < len(lines) and not lines[cursor].startswith(("@@", "--- a/")):
                line = lines[cursor]
                if not line or line[0] not in " +-":
                    raise ValueError("补丁包含不支持的格式。")
                if line[0] in " -":
                    if consumed >= len(original) or original[consumed] != line[1:]:
                        raise ValueError("补丁上下文与仓库快照不匹配。")
                    consumed += 1
                    seen_old += 1
                if line[0] in " +":
                    result.append(line[1:])
                    seen_new += 1
                if line[0] in "+-":
                    edits += 1
                cursor += 1
            if (seen_old, seen_new) != (old_count, new_count):
                raise ValueError("补丁行数不匹配。")
            hunks += 1
        if not hunks or edits > 200:
            raise ValueError("补丁缺少 hunk 或超过 200 行修改限制。")
        result.extend(original[consumed:])
        source = "".join(result)
        if source == "".join(original):
            raise ValueError("补丁没有修改源代码。")
        ast.parse(source, filename=name)
        staged[name] = source
    for name, source in staged.items():
        (repo / name).write_text(source, encoding="utf-8", newline="\n")
    return list(staged)
