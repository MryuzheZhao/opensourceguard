from __future__ import annotations

import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler

from opensourceguard.cli import LocalHTTPServer
from opensourceguard.model import ModelClient
from opensourceguard.pipeline import analyze
from opensourceguard.cli import ROOT


class ModelEndpoint(BaseHTTPRequestHandler):
    last_auth = ""

    def log_message(self, *args):
        pass

    def do_POST(self):  # noqa: N802
        ModelEndpoint.last_auth = self.headers.get("Authorization", "")
        if self.path == "/slow":
            time.sleep(1.0)
        if self.path == "/error":
            self.send_response(500)
            self.end_headers()
            return
        if self.path == "/bad":
            payload = {"choices": [{"message": {"content": "not json"}}]}
        elif self.path == "/responses":
            payload = {"output_text": json.dumps({"patch": "", "warnings": []})}
        else:
            payload = {"choices": [{"message": {"content": json.dumps({
                "reproduction_test": "assert True", "patch_plan": "review", "patch": "", "warnings": []
            })}}]}
        raw = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        try:
            self.wfile.write(raw)
        except OSError:
            pass


class ModelClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = LocalHTTPServer(("127.0.0.1", 0), ModelEndpoint)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_chat_completions_normalises_and_hides_key(self):
        client = ModelClient(f"{self.base}/ok", "fixture", "super-secret")
        result = client.complete_json("system", "user")
        self.assertEqual(result["patch_plan"], "review")
        self.assertEqual(ModelEndpoint.last_auth, "Bearer super-secret")
        self.assertNotIn("super-secret", json.dumps(client.status()))

    def test_responses_shape(self):
        client = ModelClient(f"{self.base}/responses", "fixture", api_style="responses")
        self.assertEqual(client.complete_json("system", "user")["patch"], "")

    def test_bad_json_http_error_and_timeout_fall_back(self):
        for path, error in [("/bad", "invalid_json_result"), ("/error", "http_500")]:
            client = ModelClient(f"{self.base}{path}", "fixture", timeout=1)
            self.assertIsNone(client.complete_json("system", "user"))
            self.assertEqual(client.last_error, error)
        client = ModelClient(f"{self.base}/slow", "fixture", timeout=0.1)
        self.assertIsNone(client.complete_json("system", "user"))
        self.assertIn(client.last_error, {"connection_failed", "invalid_response"})

    def test_status_when_not_configured(self):
        client = ModelClient()
        self.assertFalse(client.status()["configured"])
        self.assertEqual(client.test_connection()["error"], "not_configured")

    def test_transient_connection_abort_is_retried_once(self):
        """A dropped connection is retried, because the request never ran.

        Regression guard: a transient WinError 10053 / ECONNRESET used to surface
        as a hard failure (last_error="invalid_response"), which made analysis
        randomly fall back to local rules even though the endpoint was healthy.
        """
        import urllib.error
        import urllib.request

        calls = []
        real_urlopen = urllib.request.urlopen

        def flaky_urlopen(request, timeout=None):
            calls.append(request.full_url)
            if len(calls) == 1:
                raise ConnectionAbortedError(10053, "connection aborted by host software")
            return real_urlopen(request, timeout=timeout)

        client = ModelClient(f"{self.base}/ok", "fixture", timeout=5)
        urllib.request.urlopen = flaky_urlopen
        try:
            result = client.complete_json("system", "user")
        finally:
            urllib.request.urlopen = real_urlopen

        self.assertEqual(len(calls), 2, "应当重试一次")
        self.assertIsNotNone(result, "重试后应当成功返回结果")
        self.assertEqual(result["patch_plan"], "review")

    def test_repeated_connection_abort_gives_up_with_clear_error(self):
        import urllib.request

        calls = []

        def always_abort(request, timeout=None):
            calls.append(request.full_url)
            raise ConnectionAbortedError(10053, "connection aborted")

        client = ModelClient(f"{self.base}/ok", "fixture", timeout=5)
        real_urlopen = urllib.request.urlopen
        urllib.request.urlopen = always_abort
        try:
            self.assertIsNone(client.complete_json("system", "user"))
        finally:
            urllib.request.urlopen = real_urlopen

        self.assertEqual(len(calls), 2, "最多只重试一次，不应无限重试")
        self.assertEqual(client.last_error, "connection_aborted")

    def test_http_error_is_not_retried(self):
        """HTTP errors mean the server processed the request; retrying is unsafe."""
        import urllib.error
        import urllib.request

        calls = []
        real_urlopen = urllib.request.urlopen

        def failing(request, timeout=None):
            calls.append(request.full_url)
            raise urllib.error.HTTPError(request.full_url, 500, "boom", {}, None)

        client = ModelClient(f"{self.base}/ok", "fixture", timeout=5)
        urllib.request.urlopen = failing
        try:
            self.assertIsNone(client.complete_json("system", "user"))
        finally:
            urllib.request.urlopen = real_urlopen

        self.assertEqual(len(calls), 1, "HTTP 错误不应重试")
        self.assertEqual(client.last_error, "http_500")

    def test_timeout_is_not_retried(self):
        """A timeout must respect the caller's latency budget, not double it."""
        import urllib.request

        calls = []

        def slow(request, timeout=None):
            calls.append(request.full_url)
            raise TimeoutError("timed out")

        client = ModelClient(f"{self.base}/ok", "fixture", timeout=5)
        real_urlopen = urllib.request.urlopen
        urllib.request.urlopen = slow
        try:
            self.assertIsNone(client.complete_json("system", "user"))
        finally:
            urllib.request.urlopen = real_urlopen

        self.assertEqual(len(calls), 1, "超时不应重试")
        self.assertEqual(client.last_error, "connection_failed")

    def test_pipeline_uses_model_and_keeps_verification_boundary(self):
        client = ModelClient(f"{self.base}/ok", "fixture", "secret")
        report = analyze(ROOT / "examples" / "buggy_csv", "读取空 CSV 文件时 parse_csv 崩溃", model=client)
        self.assertEqual(report.model_used, "fixture")
        self.assertEqual(report.patch_source, "none")
        self.assertEqual(report.verification_status, "skipped")
        self.assertNotIn("secret", json.dumps(report.to_dict(), ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
