from __future__ import annotations

import json
import os
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler

from opensourceguard.providers import create_draft_pr, list_pull_requests


class PullRequestEndpoint(BaseHTTPRequestHandler):
    """Minimal stand-in for api.github.com covering the calls we make."""

    auth = ""
    last_path = ""
    last_payload: dict = {}

    def log_message(self, *args):
        pass

    def _json(self, code: int, data) -> None:
        raw = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):  # noqa: N802
        PullRequestEndpoint.auth = self.headers.get("Authorization", "")
        PullRequestEndpoint.last_path = self.path
        length = int(self.headers.get("Content-Length") or 0)
        PullRequestEndpoint.last_payload = json.loads(self.rfile.read(length) or b"{}")
        if PullRequestEndpoint.last_path.startswith("/repos/builder/demo/pulls"):
            self._json(201, {"number": 42, "html_url": "https://github.com/builder/demo/pull/42",
                             "state": "open", "draft": PullRequestEndpoint.last_payload.get("draft")})
        else:
            self._json(404, {"message": "Not Found"})

    def do_GET(self):  # noqa: N802
        PullRequestEndpoint.auth = self.headers.get("Authorization", "")
        PullRequestEndpoint.last_path = self.path
        self._json(200, [{"number": 42, "title": "AI 候选修复", "html_url": "https://github.com/builder/demo/pull/42",
                          "draft": True, "state": "open", "head": {"ref": "fix"}, "base": {"ref": "main"}}])


class DraftPullRequestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = threading.Thread(target=lambda: None, daemon=True)
        from http.server import HTTPServer
        cls.httpd = HTTPServer(("127.0.0.1", 0), PullRequestEndpoint)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        os.environ["OSG_GITHUB_API_URL"] = cls.base
        os.environ["OSG_GITHUB_TOKEN"] = "test-token"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        os.environ.pop("OSG_GITHUB_API_URL", None)
        os.environ.pop("OSG_GITHUB_TOKEN", None)

    def setUp(self):
        # last_path is class-level state on the fake endpoint, so it must be
        # reset per test; otherwise a write from an earlier test makes a
        # later "nothing was sent" assertion fail for the wrong reason.
        PullRequestEndpoint.last_path = ""
        PullRequestEndpoint.last_payload = {}
        PullRequestEndpoint.auth = ""

    def test_dry_run_never_writes(self):
        result = create_draft_pr("github", "builder/demo", "t", "b", "fix", "main", confirm=False)
        self.assertFalse(result["ok"])
        self.assertTrue(result["requires_confirmation"])
        self.assertEqual(PullRequestEndpoint.last_path, "", "未确认时不应发出任何网络写入")

    def test_creates_draft_pr_with_token(self):
        result = create_draft_pr("github", "builder/demo", "AI 候选修复", "body", "fix", "main", confirm=True)
        self.assertTrue(result["ok"], result.get("message"))
        self.assertEqual(result["number"], 42)
        self.assertEqual(result["url"], "https://github.com/builder/demo/pull/42")
        self.assertTrue(PullRequestEndpoint.last_payload["draft"])
        self.assertEqual(PullRequestEndpoint.last_payload["head"], "fix")
        self.assertEqual(PullRequestEndpoint.last_payload["base"], "main")
        self.assertEqual(PullRequestEndpoint.auth, "Bearer test-token")

    def test_rejects_same_head_and_base(self):
        with self.assertRaises(ValueError):
            create_draft_pr("github", "builder/demo", "t", "b", "main", "main", confirm=True)

    def test_rejects_empty_title_and_head(self):
        with self.assertRaises(ValueError):
            create_draft_pr("github", "builder/demo", "  ", "b", "fix", "main", confirm=True)
        with self.assertRaises(ValueError):
            create_draft_pr("github", "builder/demo", "t", "b", " ", "main", confirm=True)

    def test_rejects_unsupported_platform(self):
        with self.assertRaises(ValueError):
            create_draft_pr("generic", "builder/demo", "t", "b", "fix", "main", confirm=True)

    def test_missing_branch_returns_actionable_error(self):
        result = create_draft_pr("github", "builder/absent", "t", "b", "nope", "main", confirm=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], 404)
        self.assertIn("head", result["message"])

    def test_requires_token(self):
        saved = os.environ.pop("OSG_GITHUB_TOKEN")
        try:
            with self.assertRaises(ValueError):
                create_draft_pr("github", "builder/demo", "t", "b", "fix", "main", confirm=True)
        finally:
            os.environ["OSG_GITHUB_TOKEN"] = saved

    def test_list_pull_requests_reads_drafts(self):
        result = list_pull_requests("github", "builder/demo")
        self.assertEqual(result["errors"], [])
        self.assertEqual(len(result["pulls"]), 1)
        self.assertTrue(result["pulls"][0]["draft"])


if __name__ == "__main__":
    unittest.main()


class PublicBodyRedactionTests(unittest.TestCase):
    """A pull request is public: the report body must not carry local paths."""

    def _report(self, repo: str):
        from opensourceguard.types import AnalysisReport, Evidence, IssueAnalysis
        return AnalysisReport(
            repo=repo,
            issue=IssueAnalysis(issue="空 CSV 崩溃", issue_type="bug", severity="medium",
                                keywords=[], expected_behavior="返回空列表", actual_behavior="崩溃"),
            evidence=[Evidence(path="src/parse.py", start_line=1, end_line=2, score=1.0, reason="r")],
            reproduction_test="def test_x(): pass",
            patch_plan="plan", patch="", tests=[], next_actions=[],
        )

    def test_pr_body_never_contains_absolute_path(self):
        from opensourceguard.integrations import draft_pr_payload, to_public_markdown
        report = self._report("C:/Users/someone/Documents/private-project")
        for body in (to_public_markdown(report), draft_pr_payload(report)["body"]):
            self.assertNotIn("someone", body)
            self.assertNotIn("Documents", body)
            self.assertNotIn("Users", body)
            self.assertIn("private-project", body)

    def test_windows_and_posix_paths_are_both_reduced(self):
        from opensourceguard.integrations import _public_repo_label
        self.assertEqual(_public_repo_label("C:////Users////a////b////proj"), "proj")
        self.assertEqual(_public_repo_label("/home/a/proj/"), "proj")
        self.assertEqual(_public_repo_label(""), "unknown")
        self.assertEqual(_public_repo_label("proj"), "proj")

    def test_local_markdown_still_has_full_path(self):
        """The local report keeps the full path; only the published body is redacted."""
        from opensourceguard.integrations import to_public_markdown
        from opensourceguard.report import to_markdown
        report = self._report("C:/Users/someone/Documents/private-project")
        self.assertIn("someone", to_markdown(report))
        self.assertNotIn("someone", to_public_markdown(report))
