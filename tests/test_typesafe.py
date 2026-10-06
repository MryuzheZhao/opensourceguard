from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from opensourceguard.typesafe import recommend, status


class TypeSafeTests(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("TYPESAFE_API_KEY", None)

    def test_local_ranker_is_available_without_key(self):
        projects = [
            {"id": "a/ops", "name": "ops", "description": "Python 运维工具"},
            {"id": "b/agent", "name": "agent", "description": "Python AI agent toolkit"},
        ]
        result = recommend(projects, "AI agent", "运维")
        self.assertEqual(result["mode"], "local_ranker")
        self.assertEqual(result["projects"][0]["id"], "b/agent")
        self.assertGreater(result["projects"][0]["relevance_score"], result["projects"][1]["relevance_score"])
        self.assertNotIn("TYPESAFE_API_KEY", str(result))

    def test_typesafe_batch_scores_are_combined(self):
        os.environ["TYPESAFE_API_KEY"] = "server-only-secret"
        projects = [
            {"id": "a/first", "name": "first", "description": "one"},
            {"id": "b/second", "name": "second", "description": "two"},
        ]
        with patch("opensourceguard.typesafe._post", return_value={"answers": {
            "project_0": {"type": "score", "score": 0, "confidence": 0.9},
            "project_1": {"type": "score", "score": 3, "confidence": 0.9},
        }}) as call:
            result = recommend(projects, "agent")
        self.assertEqual(result["mode"], "typesafe")
        self.assertEqual(result["projects"][0]["id"], "b/second")
        payload = call.call_args.args[0]
        self.assertEqual(payload["model"], "jev-latest")
        self.assertNotIn("server-only-secret", str(payload))

    def test_status_never_exposes_key(self):
        os.environ["TYPESAFE_API_KEY"] = "server-only-secret"
        data = status()
        self.assertTrue(data["ready"])
        self.assertNotIn("server-only-secret", str(data))


if __name__ == "__main__":
    unittest.main()
