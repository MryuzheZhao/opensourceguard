"""Benchmark fixture: a clean module with no intentional findings.

This is the negative control. A scanner that reports problems here is producing
false positives, which the benchmark measures explicitly.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from typing import Iterable, List, Sequence


def content_digest(payload: bytes) -> str:
    """Return a SHA-256 digest of a byte payload."""
    return hashlib.sha256(payload).hexdigest()


def read_token() -> str:
    """Read the API token from the environment, never from source."""
    return os.environ.get("DEMO_API_TOKEN", "")


def run_formatter(paths: Sequence[str]) -> int:
    """Run an external formatter without invoking a shell."""
    completed = subprocess.run(
        ["python", "-m", "json.tool", *paths],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode


def normalise(values: Iterable[str]) -> List[str]:
    """Trim and drop empty entries."""
    return [value.strip() for value in values if value and value.strip()]


def chunk(values: Sequence[int], size: int) -> List[List[int]]:
    """Split a sequence into fixed-size chunks."""
    if size <= 0:
        raise ValueError("size must be positive")
    return [list(values[index:index + size]) for index in range(0, len(values), size)]
