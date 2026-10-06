"""End-to-end check of the draft PR flow against a local fake GitHub API.

Verifies the full HTTP path the browser uses: analyze -> draft-pr dry run ->
confirm -> real POST to /repos/{repo}/pulls, and that a missing token refuses to
write instead of silently pretending it worked.
"""
from __future__ import annotations

import json
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from opensourceguard.cli import Handler, LocalHTTPServer  # noqa: E402

received: list[dict] = []


class FakeGitHub(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _json(self, code, data):
        raw = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        received.append({"path": self.path, "body": body,
                         "auth": self.headers.get("Authorization", "")})
        if self.path.endswith("/pulls"):
            self._json(201, {"number": 77,
                             "html_url": "https://github.com/builder/demo/pull/77",
                             "state": "open", "draft": body.get("draft")})
        else:
            self._json(404, {"message": "Not Found"})

    def do_GET(self):  # noqa: N802
        if "/pulls" in self.path:
            self._json(200, [{"number": 77, "title": body_title(), "html_url": "https://github.com/builder/demo/pull/77",
                              "draft": True, "state": "open",
                              "head": {"ref": "opensourceguard/fix"}, "base": {"ref": "main"}}])
        else:
            self._json(200, [])


def body_title() -> str:
    return received[-1]["body"].get("title", "") if received else ""


def post(base: str, path: str, payload: dict) -> dict:
    req = urllib.request.Request(base + path, data=json.dumps(payload).encode(),
                                 method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    gh = HTTPServer(("127.0.0.1", 0), FakeGitHub)
    threading.Thread(target=gh.serve_forever, daemon=True).start()
    gh_base = f"http://127.0.0.1:{gh.server_address[1]}"
    import os
    os.environ["OSG_GITHUB_API_URL"] = gh_base
    os.environ["OSG_GITHUB_TOKEN"] = "local-test-token"

    class Quiet(Handler):
        repo = ROOT / "examples" / "buggy_csv"

        def log_message(self, *a):
            pass

    srv = LocalHTTPServer(("127.0.0.1", 0), Quiet)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    print(f"service={base}  fake-gh={gh_base}")

    results = []

    def check(name, ok, detail=""):
        results.append((name, ok))
        print(("PASS  " if ok else "FAIL  ") + name + (f"  |  {detail}" if detail else ""))

    issue = "读取空 CSV 文件时 parse_csv 崩溃，应该返回空列表"

    # 1) dry run must not write
    before = len(received)
    d = post(base, "/draft-pr", {"issue": issue, "head": "opensourceguard/fix", "base": "main"})
    check("dry-run 标记正确", d.get("dry_run") is True)
    check("dry-run 不发网络写请求", len(received) == before, f"收到 {len(received) - before} 个请求")
    check("dry-run 返回 draft:true", d.get("draft") is True)
    check("PR 正文含工具署名", "OpenSourceGuard" in (d.get("body") or ""))

    # 2) confirmed write hits the platform
    d = post(base, "/draft-pr", {"issue": issue, "platform": "github", "repo": "builder/demo",
                                 "head": "opensourceguard/fix", "base": "main", "confirm": True})
    check("确认后创建成功", d.get("ok") is True, str(d.get("message")))
    check("返回 PR 链接", "pull/77" in (d.get("url") or ""), d.get("url", ""))
    check("发出 1 次真实写请求", len(received) == before + 1, f"{len(received) - before} 个")
    sent = received[-1]
    check("路径正确", sent["path"] == "/repos/builder/demo/pulls", sent["path"])
    check("draft 标志为 true", sent["body"].get("draft") is True)
    check("head/base 正确", sent["body"].get("head") == "opensourceguard/fix" and sent["body"].get("base") == "main")
    check("Bearer Token 正确", sent["auth"] == "Bearer local-test-token", sent["auth"])
    check("PR 正文非空", len(sent["body"].get("body") or "") > 50)

    # 3) missing repo must refuse instead of pretending
    d = post(base, "/draft-pr", {"issue": issue, "platform": "github", "repo": "",
                                 "head": "a", "base": "main", "confirm": True})
    check("缺 repo 时拒绝创建", d.get("ok") is not True, str(d.get("message"))[:40])
    check("缺 repo 时未发写请求", len(received) == before + 1)

    # 4) read back the PR list
    d = post(base, "/projects/pulls", {"platform": "github", "repo": "builder/demo"})
    check("可读回 PR 列表", len(d.get("pulls") or []) == 1, json.dumps(d.get("pulls"), ensure_ascii=False)[:80])

    gh.shutdown()
    srv.shutdown()
    os.environ.pop("OSG_GITHUB_API_URL", None)
    os.environ.pop("OSG_GITHUB_TOKEN", None)

    passed = sum(1 for _, ok in results if ok)
    print(f"\n===== {passed}/{len(results)} 通过 =====")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
