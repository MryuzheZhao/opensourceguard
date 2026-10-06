"""Bounded snapshots; symlinks, credentials and build caches are never copied."""
from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

EXCLUDED = {".git", ".venv", "venv", "__pycache__", "node_modules", ".pytest_cache",
            "artifacts", "dist", "build", ".idea"}


def repository_files(repo: Path):
    count, total = 0, 0
    for directory, dirs, files in os.walk(repo, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED
                         and not (Path(directory) / d).is_symlink()
                         and not (getattr(Path(directory) / d, "is_junction", lambda: False)()))
        for name in sorted(files):
            path = Path(directory) / name
            if path.is_symlink() or name.startswith(".env") or path.suffix.lower() in {".pem", ".key", ".p12"}:
                continue
            if path.stat().st_size > 1_000_000:
                continue
            count += 1
            total += path.stat().st_size
            if count > 2000 or total > 30_000_000:
                raise ValueError("MVP 仓库上限为 2000 个文件、30 MB；请缩小输入范围。")
            yield path


def snapshot(repo: Path, destination: Path) -> str:
    destination.mkdir(parents=True)
    digest = hashlib.sha256()
    for path in repository_files(repo):
        rel = path.relative_to(repo)
        raw = path.read_bytes()
        digest.update(rel.as_posix().encode() + b"\0" + raw + b"\0")
        target = destination / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    return digest.hexdigest()
