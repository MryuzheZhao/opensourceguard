"""Workspace repo switching and UI model configuration checks.

Hermetic: OSG_MODEL_STORE is redirected to a temporary directory so the real
~/.opensourceguard/model.json is never read or written, and no test performs
network access (example.invalid is never actually called).
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from opensourceguard import cli
from opensourceguard.cli import Handler, LocalHTTPServer, ROOT


class WorkspaceHandler(Handler):
    repo = ROOT / "examples" / "buggy_csv"

    def log_message(self, *args):
        pass


class WorkspaceApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._store_tmp = tempfile.TemporaryDirectory()
        cls._old_store = os.environ.get("OSG_MODEL_STORE")
        os.environ["OSG_MODEL_STORE"] = str(Path(cls._store_tmp.name) / "model.json")
        cls.server = LocalHTTPServer(("127.0.0.1", 0), WorkspaceHandler)
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

    def setUp(self):
        with self.server.state_lock:
            self.server.repo = WorkspaceHandler.repo.resolve()
            self.server.model_config = {}
        store = Path(os.environ["OSG_MODEL_STORE"])
        if store.exists():
            store.unlink()

    def api(self, path, payload=None):
        request = urllib.request.Request(self.base + path,
            data=json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read())

    def api_error(self, path, payload):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.api(path, payload)
        body = ctx.exception.read().decode("utf-8", "replace")
        return ctx.exception, body

    def test_repo_select_switches_server_state(self):
        target = (ROOT / "examples" / "security_demo").resolve()
        data = self.api("/repo/select", {"path": str(target)})
        self.assertTrue(data["ok"])
        self.assertEqual(Path(data["repo"]), target)
        self.assertEqual(data["name"], "security_demo")
        self.assertEqual(self.server.repo, target)
        health = self.api("/health")
        self.assertEqual(Path(health["repo"]), target)
        # The class-level fallback repo is never mutated.
        self.assertEqual(WorkspaceHandler.repo, ROOT / "examples" / "buggy_csv")

    def test_repo_select_rejects_missing_and_blocked_paths(self):
        error, _ = self.api_error("/repo/select", {})
        self.assertEqual(error.code, 400)
        error, _ = self.api_error("/repo/select", {"path": str(ROOT / "examples" / "no_such_dir_xyz")})
        self.assertEqual(error.code, 400)
        with tempfile.TemporaryDirectory() as temp:
            ssh = Path(temp) / ".ssh"
            ssh.mkdir()
            error, body = self.api_error("/repo/select", {"path": str(ssh)})
            self.assertEqual(error.code, 400)
            self.assertIn(".ssh", body)
        self.assertEqual(self.server.repo, WorkspaceHandler.repo.resolve())

    def test_repo_clone_rejects_invalid_urls_without_touching_git(self):
        before = self.server.repo
        cases = [
            {},
            {"url": "git@github.com:owner/repo.git"},
            {"url": "ssh://git@github.com/owner/repo.git"},
            {"url": "file:///c:/owner/repo"},
            {"url": "http://github.com/owner/repo"},
            {"url": "https://evil.example.com/owner/repo"},
            {"url": "https://github.com/only-one-segment"},
            {"url": "https://gitee.com/owner/repo with space"},
            {"url": "https://github.com/" + "a" * 600},
        ]
        for payload in cases:
            with self.subTest(payload=payload):
                error, _ = self.api_error("/repo/clone", payload)
                self.assertEqual(error.code, 400)
        self.assertEqual(self.server.repo, before)

    def test_repo_clone_reuses_existing_checkout(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "github.com-owner-demo"
            (target / ".git").mkdir(parents=True)
            # Windows TEMP sits under AppData, which _repo_block_reason blocks by
            # design; this test exercises the reuse path, so bypass that one check.
            with mock.patch.object(cli, "_clone_root", return_value=Path(temp)), \
                    mock.patch.object(cli, "_repo_block_reason", return_value=""):
                data = self.api("/repo/clone", {"url": "https://github.com/owner/demo"})
            self.assertTrue(data["ok"])
            self.assertTrue(data["reused"])
            self.assertEqual(Path(data["repo"]), target)
            self.assertEqual(self.server.repo, target)

    def test_model_config_save_status_reuse_and_clear(self):
        data = self.api("/model/config", {"base_url": "https://example.invalid/v1",
            "model": "demo-model", "api_key": "sk-test-secret-123", "api_style": "chat_completions"})
        self.assertTrue(data["ok"])
        self.assertTrue(data["persisted"])
        self.assertNotIn("sk-test-secret-123", json.dumps(data))
        status = self.api("/model/status")
        self.assertTrue(status["configured"])
        self.assertEqual(status["model"], "demo-model")
        self.assertEqual(status["base_url"], "https://example.invalid/v1")
        self.assertTrue(status["api_key_configured"])
        self.assertNotIn("sk-test-secret-123", json.dumps(status))
        health = self.api("/health")
        self.assertTrue(health["model_configured"])
        store = Path(os.environ["OSG_MODEL_STORE"])
        self.assertTrue(store.exists())
        saved = json.loads(store.read_text(encoding="utf-8"))
        self.assertEqual(saved["api_key"], "sk-test-secret-123")
        self.assertEqual(self.server.model_config["model"], "demo-model")
        # An empty api_key field reuses the previously saved key.
        again = self.api("/model/config", {"base_url": "https://example.invalid/v1", "model": "demo-model-2", "api_key": ""})
        self.assertTrue(again["ok"])
        self.assertEqual(self.server.model_config["api_key"], "sk-test-secret-123")
        self.assertNotIn("sk-test-secret-123", json.dumps(again))
        cleared = self.api("/model/config", {})
        self.assertTrue(cleared["cleared"])
        self.assertFalse(store.exists())
        self.assertEqual(self.server.model_config, {})
        self.assertFalse(self.api("/model/status")["configured"])
        self.assertFalse(self.api("/health")["model_configured"])

    def test_model_config_validation_keeps_state_clean(self):
        error, _ = self.api_error("/model/config", {"base_url": "ftp://example", "model": "m"})
        self.assertEqual(error.code, 400)
        error, _ = self.api_error("/model/config", {"base_url": "https://example.invalid/v1", "model": "m", "api_style": "weird"})
        self.assertEqual(error.code, 400)
        error, _ = self.api_error("/model/config", {"base_url": "https://example.invalid/v1"})
        self.assertEqual(error.code, 400)
        error, _ = self.api_error("/model/config", {"base_url": "https://example.invalid/v1", "model": "m", "api_key": "x" * 501})
        self.assertEqual(error.code, 400)
        self.assertEqual(self.server.model_config, {})
        self.assertFalse(self.api("/model/status")["configured"])

    def test_model_test_stays_offline_when_not_configured(self):
        data = self.api("/model/test", {})
        self.assertEqual(data["error"], "not_configured")


if __name__ == "__main__":
    unittest.main()
