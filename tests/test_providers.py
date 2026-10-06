from __future__ import annotations

import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler

from opensourceguard.cli import LocalHTTPServer
from opensourceguard.providers import add_issue_comment, list_issues, list_projects


class ProviderEndpoint(BaseHTTPRequestHandler):
    auth = ""

    def log_message(self, *args):
        pass

    def do_GET(self):  # noqa: N802
        ProviderEndpoint.auth = self.headers.get("Authorization", "")
        if self.path.startswith("/user/repos"):
            data = [{"full_name": "builder/demo", "name": "demo", "html_url": "https://github.com/builder/demo", "open_issues_count": 2}]
        else:
            data = [{"number": 7, "title": "Fix input", "body": "Please validate input", "state": "open", "user": {"login": "builder"}}]
        raw = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):  # noqa: N802
        ProviderEndpoint.auth = self.headers.get("Authorization", "")
        raw = json.dumps({"html_url": "https://github.com/builder/demo/issues/7#issuecomment-1"}).encode()
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class ProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = LocalHTTPServer(("127.0.0.1", 0), ProviderEndpoint)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.old = {key: os.environ.get(key) for key in ("OSG_GITHUB_API_URL", "OSG_GITHUB_TOKEN")}
        os.environ["OSG_GITHUB_API_URL"] = self.base
        os.environ["OSG_GITHUB_TOKEN"] = "provider-secret"

    def tearDown(self):
        for key, value in self.old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_projects_and_issues_are_normalised_without_exposing_token(self):
        projects = list_projects("github")
        self.assertEqual(projects["projects"][0]["id"], "builder/demo")
        self.assertFalse(projects["demo"])
        issues = list_issues("github", "builder/demo")
        self.assertEqual(issues["issues"][0]["number"], 7)
        self.assertEqual(ProviderEndpoint.auth, "Bearer provider-secret")
        self.assertNotIn("provider-secret", json.dumps(projects))

    def test_remote_write_requires_confirmation_and_can_add_comment(self):
        preview = add_issue_comment("github", "builder/demo", 7, "hello", confirm=False)
        self.assertTrue(preview["requires_confirmation"])
        result = add_issue_comment("github", "builder/demo", 7, "hello", confirm=True)
        self.assertTrue(result["ok"])
        self.assertIn("issuecomment", result["url"])


if __name__ == "__main__":
    unittest.main()
