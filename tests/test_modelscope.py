from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from opensourceguard.modelscope import prepare, publish


class ModelScopeTests(unittest.TestCase):
    def test_prepare_blocks_secrets_and_limits_model_id(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            (repo / "README.md").write_text("demo", encoding="utf-8")
            (repo / ".env").write_text("MODELSCOPE_TOKEN=secret", encoding="utf-8")
            result = prepare(repo, "builder/demo")
            self.assertFalse(result["safe_to_upload"])
            self.assertEqual(result["blocked_files"], [".env"])
            with self.assertRaises(ValueError):
                prepare(repo, "bad id")

    def test_space_uses_dedicated_gradio_bundle(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            (repo / "README.md").write_text("source", encoding="utf-8")
            (repo / "space").mkdir()
            (repo / "space" / "app.py").write_text("import gradio", encoding="utf-8")
            result = prepare(repo, "builder/guard-space", kind="space")
            self.assertEqual(result["kind"], "space")
            self.assertEqual(result["repo"], str((repo / "space").resolve()))
            self.assertEqual([item["path"] for item in result["files"]], ["app.py"])

    def test_publish_never_writes_without_confirmation_or_token(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.assertTrue(publish(repo, "builder/demo")["requires_confirmation"])
            old = os.environ.pop("OSG_MODELSCOPE_TOKEN", None)
            try:
                result = publish(repo, "builder/demo", confirm=True)
                self.assertEqual(result["error"], "token_missing")
                self.assertNotIn("OSG_MODELSCOPE_TOKEN", json.dumps(result))
            finally:
                if old is not None:
                    os.environ["OSG_MODELSCOPE_TOKEN"] = old


if __name__ == "__main__":
    unittest.main()
