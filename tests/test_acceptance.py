"""Real HTTP + subprocess regression checks, no internet or credentials required."""
from __future__ import annotations

import difflib
import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from opensourceguard.arena import ARENA_CASES, _score, run_arena
from opensourceguard.cli import Handler, LocalHTTPServer, ROOT
from opensourceguard.onboarding import build_onboarding
from opensourceguard.pipeline import analyze, _repository_digest
from opensourceguard.report import to_markdown
from opensourceguard.model import ModelClient

ISSUE = "读取空 CSV 文件时 parse_csv 崩溃，应该返回空列表"


class QuietHandler(Handler):
    repo = ROOT / "examples" / "buggy_csv"

    def log_message(self, *args):
        pass


class Acceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Isolate from any real ~/.opensourceguard/model.json on this machine.
        cls._store_tmp = tempfile.TemporaryDirectory()
        cls._old_store = os.environ.get("OSG_MODEL_STORE")
        os.environ["OSG_MODEL_STORE"] = str(Path(cls._store_tmp.name) / "model.json")
        cls.server = LocalHTTPServer(("127.0.0.1", 0), QuietHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        if cls._old_store is None:
            os.environ.pop("OSG_MODEL_STORE", None)
        else:
            os.environ["OSG_MODEL_STORE"] = cls._old_store
        cls._store_tmp.cleanup()

    def api(self, path, payload=None, headers=None):
        request = urllib.request.Request(self.base + path,
            data=json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None,
            headers={"Content-Type": "application/json", **(headers or {})})
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read())

    def test_resources_and_port_exclusion(self):
        for path, content_type in [("/", "text/html"), ("/styles.css", "text/css"), ("/app.js", "application/javascript")]:
            with urllib.request.urlopen(self.base + path) as response:
                self.assertIn(content_type, response.headers["Content-Type"])
                self.assertGreater(len(response.read()), 500)
        for path in ["/../README.md", "/opensourceguard/cli.py"]:
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(self.base + path)
            self.assertEqual(error.exception.code, 404)
        with self.assertRaises(OSError):
            LocalHTTPServer(self.server.server_address, QuietHandler)
        self.assertEqual(self.api("/health")["api_version"], "0.2")
        with urllib.request.urlopen(self.base + "/model/status") as response:
            self.assertIn("configured", json.loads(response.read()))
        with urllib.request.urlopen(self.base + "/model/test") as response:
            self.assertEqual(json.loads(response.read())["error"], "not_configured")

    def test_repair_runs_tests_and_preserves_repository(self):
        before = _repository_digest(QuietHandler.repo)
        report = self.api("/analyze", {"issue": ISSUE, "execute": "local"})
        self.assertEqual(report["verification_status"], "verified")
        self.assertEqual([x["passed"] for x in report["tests"]], [False, True, True])
        self.assertEqual(report["tests"][-1]["tests_run"], 3)
        self.assertEqual(_repository_digest(QuietHandler.repo), before)
        self.assertFalse((QuietHandler.repo / "test_osg_reproduction.py").exists())

    def test_static_and_security(self):
        report = self.api("/analyze", {"issue": ISSUE})
        self.assertEqual(report["verification_status"], "skipped")
        self.assertFalse(report["tests"][0]["infrastructure_error"])
        security = analyze(ROOT / "examples" / "security_demo", "检查命令注入和硬编码凭据")
        self.assertTrue({"PY-SHELL", "PY-SECRET"} <= {x.rule_id for x in security.security_findings})
        self.assertIn("未执行", to_markdown(security))

    def test_regression_is_not_verified(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "fixture"
            shutil.copytree(QuietHandler.repo, repo)
            (repo / "test_regression.py").write_text('import unittest\nclass Other(unittest.TestCase):\n    def test_other(self):\n        self.fail("existing regression")\n', encoding="utf-8")
            report = analyze(repo, ISSUE, mode="local")
            self.assertEqual(report.verification_status, "candidate_failed")
            self.assertTrue(report.tests[1].passed)
            self.assertFalse(report.tests[2].passed)

    def test_passing_baseline_is_not_verified(self):
        before = (QuietHandler.repo / "parser.py").read_text(encoding="utf-8")
        patch = "".join(difflib.unified_diff(before.splitlines(True), (before + "\n# reviewed\n").splitlines(True), fromfile="a/parser.py", tofile="b/parser.py"))
        class StubModel:
            enabled = True
            model = "fixture"
            def complete_json(self, *args):
                return {"patch": patch, "reproduction_test": 'import unittest\nfrom parser import parse_csv\nclass Check(unittest.TestCase):\n    def test_regular(self):\n        self.assertEqual(parse_csv("a,b"), ["a", "b"])\n'}
        report = analyze(QuietHandler.repo, ISSUE, model=StubModel(), mode="local")
        self.assertEqual(report.verification_status, "not_reproduced")

    def test_invalid_requests_and_cross_origin(self):
        cases = [("/analyze", []), ("/analyze", {}), ("/analyze", {"issue": ISSUE, "execute": "oops"}),
                 ("/arena", {"agents": [None]}), ("/arena", {"agents": [{"kind": "unknown"}]}),
                 ("/arena", {"agents": [{"kind": "http", "endpoint": "file:///private"}]}),
                 ("/arena", {"cases": []}), ("/onboarding", {"project_name": "hello; bad"})]
        for path, body in cases:
            with self.subTest(body=body), self.assertRaises(urllib.error.HTTPError) as err:
                self.api(path, body)
            self.assertEqual(err.exception.code, 400)
        with self.assertRaises(urllib.error.HTTPError) as err:
            self.api("/analyze", {"issue": ISSUE}, {"Origin": "https://example.com"})
        self.assertEqual(err.exception.code, 403)

    def test_publish_materials_escape_html_and_mark_placeholders(self):
        data = self.api("/onboarding", {"project_name": "my-agent", "description": '<img src=x onerror="alert(1)">', "platform": "gitee"})
        self.assertTrue(data["needs_username"])
        self.assertEqual(len(data["checklist"]), 5)
        self.assertNotIn("<img", data["website_card"]["html"])
        self.assertIn("&lt;img", data["website_card"]["html"])
        self.assertIn("gitee.com", data["repository"]["clone_url"])
        complete = self.api("/onboarding", {"project_name": "my-agent", "username": "builder", "description": "A useful tool"})
        self.assertFalse(complete["needs_username"])
        self.assertNotIn("YOUR_USERNAME", json.dumps(complete))
        self.assertIn("A useful tool", complete["readme_template"])

    def test_existing_git_keeps_remote_and_branch(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            def git(*args):
                subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
            git("init", "-b", "develop")
            git("remote", "add", "origin", "https://github.com/builder/existing.git")
            data = build_onboarding(repo, project_name="existing", username="builder")
            commands = "\n".join(x for step in data["checklist"] for x in step["commands"])
            self.assertNotIn("git branch -M", commands)
            self.assertNotIn("git remote add", commands)
            self.assertIn("git push -u origin HEAD", commands)

    def test_arena_empty_negation_and_positive_violation(self):
        self.assertEqual(_score("", ARENA_CASES[1], 0)["score"], 0)
        self.assertEqual(_score("先确认风险，拒绝直接执行未知命令。", ARENA_CASES[1], 0)["forbidden_hits"], [])
        self.assertEqual(_score("不直接执行，但最终直接执行。", ARENA_CASES[1], 0)["forbidden_hits"], ["直接执行"])
        data = self.api("/arena", {"agents": [{"name": "empty", "kind": "responses", "responses": {}}]})
        self.assertEqual(data["leaderboard"][0]["score"], 0)

    def test_http_agent_success_bad_json_and_timeout(self):
        from http.server import BaseHTTPRequestHandler
        import time
        class Agent(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.path == "/slow": time.sleep(.3)
                raw = b"oops" if self.path == "/bad" else json.dumps({"answer": "先确认风险，拒绝直接执行未知命令。"}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                try: self.wfile.write(raw)
                except OSError: pass
        with LocalHTTPServer(("127.0.0.1", 0), Agent) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                endpoint = f"http://127.0.0.1:{server.server_address[1]}"
                for path, errors in [("/ok", 0), ("/bad", 1), ("/slow", 1)]:
                    result = self.api("/arena", {"agents": [{"kind": "http", "endpoint": endpoint + path, "timeout": .1}], "cases": [ARENA_CASES[1]]})
                    row = result["leaderboard"][0]
                    self.assertEqual(row["errors"], errors)
                    if errors: self.assertEqual(row["score"], 0)
                    else: self.assertEqual(result["details"][0]["results"][0]["safety"], 1)
            finally:
                server.shutdown()
                thread.join()

    def test_webhook_and_pr_are_drafts(self):
        payload = {"issue": {"title": ISSUE}, "execute": "local"}
        self.assertEqual(self.api("/webhook", payload)["verification_status"], "verified")
        data = self.api("/draft-pr", payload)
        self.assertTrue(data["draft"])
        self.assertTrue(data["metadata"]["full_suite_passed"])
        self.assertIn("candidate_full", data["body"])
        self.assertNotIn("html_url", data)  # This endpoint prepares a PR, never publishes it.

    def test_project_center_demo_issues_and_agent_preview(self):
        data = self.api("/projects?platform=local")
        self.assertTrue(data["demo"])
        self.assertEqual(data["projects"][0]["platform"], "local")
        project = data["projects"][0]
        issues = self.api(f"/projects/issues?platform=local&repo={urllib.parse.quote(project['id'])}")
        self.assertEqual(len(issues["issues"]), 1)
        issue = issues["issues"][0]
        plan = self.api("/projects/assist", {"issue": issue})
        self.assertEqual(plan["action"], "agent_plan")
        self.assertTrue(plan["approval_required"])
        self.assertIn("analysis", plan)
        preview = self.api("/projects/apply-local", {"patch": plan["patch"]})
        self.assertTrue(preview["requires_confirmation"])
        comment = self.api("/projects/comment", {"platform": "github", "repo": "x/y", "number": 1, "comment": "hello"})
        self.assertTrue(comment["requires_confirmation"])

    def test_modelscope_prepare_and_confirmation_boundary(self):
        prepared = self.api("/modelscope/prepare", {"model_id": "builder/demo-agent", "kind": "model", "description": "demo"})
        self.assertEqual(prepared["platform"], "modelscope")
        self.assertTrue(prepared["approval_required"])
        self.assertFalse(prepared["token_configured"])
        self.assertIn("README", prepared["readme_hint"])
        publish = self.api("/modelscope/publish", {"model_id": "builder/demo-agent", "confirm": False})
        self.assertTrue(publish["requires_confirmation"])

    def test_project_recommendation_keeps_local_fallback(self):
        status = self.api("/typesafe/status")
        self.assertEqual(status["mode"], "local_ranker")
        projects = [
            {"id": "demo/python", "name": "python-agent", "description": "Python AI agent"},
            {"id": "demo/game", "name": "game-tools", "description": "游戏开发工具"},
        ]
        result = self.api("/projects/recommend", {"projects": projects, "interests": "Python AI", "avoid": "游戏"})
        self.assertEqual(result["mode"], "local_ranker")
        self.assertEqual(result["projects"][0]["id"], "demo/python")
        self.assertEqual(result["projects"][0]["recommendation_rank"], 1)

    def test_connections_are_local_and_oauth_setup_is_explicit(self):
        connections = self.api("/connections")
        self.assertFalse(connections["token_exposed"])
        self.assertEqual({row["platform"] for row in connections["connections"]}, {"github", "gitee", "gitlab"})
        start = self.api("/oauth/start", {"platform": "github"})
        self.assertFalse(start["ok"])
        self.assertEqual(start["error"], "oauth_app_not_configured")


if __name__ == "__main__":
    unittest.main()
