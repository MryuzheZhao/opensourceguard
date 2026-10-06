"""Execution adapters. 'local' is explicitly trusted execution, NOT a sandbox."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from .types import TestResult

WORKER = Path(__file__).with_name("_test_worker.py")
ENV_KEYS = {"SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "TEMP", "TMP", "LANG", "LC_ALL"}


def docker_command(repo: Path, name: str, target: str, framework: str, image: str) -> list[str]:
    return [
        "docker", "run", "--rm", "--name", name, "--network=none",
        "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
        "--pids-limit=64", "--memory=512m", "--cpus=1", "--user=65534:65534",
        "--tmpfs", "/tmp:rw,nosuid,size=64m",
        "--mount", f"type=bind,src={repo.resolve()},dst=/repo,readonly",
        "--mount", f"type=bind,src={WORKER.resolve()},dst=/runner.py,readonly",
        "--workdir=/repo", "-e", "PYTHONDONTWRITEBYTECODE=1",
        "-e", "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1", "--pull=never",
        image, "python", "/runner.py", target, framework,
    ]


def run_tests(repo: Path, test_path: str = "", timeout: int = 30,
              stage: str = "baseline", mode: str = "skip",
              framework: str = "unittest", image: str = "python:3.12-slim") -> TestResult:
    if mode not in {"skip", "local", "docker"} or framework not in {"unittest", "pytest"}:
        raise ValueError("不支持的测试执行配置。")
    if test_path and ("/" in test_path or "\\" in test_path or not test_path.endswith(".py")):
        raise ValueError("复现测试必须是仓库根目录下的 Python 文件。")
    label = [mode, framework, test_path or "discover"]
    if mode == "skip":
        return TestResult(label, -1, False, "", "当前只做静态分析，尚未执行测试。", stage,
                          infrastructure_error=False)
    name = "osg-" + uuid.uuid4().hex
    cmd = ([sys.executable, "-B", str(WORKER), test_path, framework] if mode == "local"
           else docker_command(repo, name, test_path, framework, image))
    env = {k: v for k, v in os.environ.items() if k.upper() in ENV_KEYS}
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8",
               PYTHONUTF8="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    timed_out = False
    try:
        # Stream to a temporary file instead of accumulating an unbounded pipe.
        with tempfile.TemporaryFile() as output:
            proc = subprocess.Popen(cmd, cwd=repo, stdout=output, stderr=subprocess.STDOUT,
                                    env=env, start_new_session=os.name != "nt")
            try:
                code = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                                   capture_output=True, timeout=10)
                else:
                    os.killpg(proc.pid, signal.SIGKILL)
                proc.kill()
                proc.wait(timeout=10)
                code = -1
            output.seek(0, 2)
            output.seek(max(0, output.tell() - 32000))
            log = output.read().decode("utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError) as exc:
        return TestResult(label, -1, False, "", f"测试环境不可用：{type(exc).__name__}", stage,
                          infrastructure_error=True)
    finally:
        if mode == "docker":
            try:
                subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=10)
            except (OSError, subprocess.SubprocessError):
                pass
    summary = {}
    for line in log.splitlines():
        if line.startswith("OSG_TEST_RESULT="):
            try:
                summary = json.loads(line.partition("=")[2])
            except ValueError:
                pass
    counts = {key: int(summary.get(key, 0)) for key in ("tests_run", "failures", "errors", "skipped")}
    infra = bool(summary.get("infrastructure_error", True)) or timed_out
    passed = (code == 0 and not infra and counts["tests_run"] > counts["skipped"]
              and not counts["failures"] and not counts["errors"])
    return TestResult(label, code, passed, log, "", stage, timed_out,
                      **counts, infrastructure_error=infra)
