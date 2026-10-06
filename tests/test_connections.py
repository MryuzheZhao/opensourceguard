from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from opensourceguard.connections import begin_oauth, finish_oauth, list_connections


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = {
            "OSG_CONNECTION_STORE": os.environ.get("OSG_CONNECTION_STORE"),
            "OSG_GITHUB_CLIENT_ID": os.environ.get("OSG_GITHUB_CLIENT_ID"),
            "OSG_GITHUB_CLIENT_SECRET": os.environ.get("OSG_GITHUB_CLIENT_SECRET"),
        }
        os.environ["OSG_CONNECTION_STORE"] = str(Path(self.temp.name) / "connections.json")
        os.environ["OSG_GITHUB_CLIENT_ID"] = "client-id"
        os.environ["OSG_GITHUB_CLIENT_SECRET"] = "client-secret"

    def tearDown(self):
        for name, value in self.env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        self.temp.cleanup()

    def test_oauth_start_uses_pkce_and_local_callback(self):
        result = begin_oauth("github", "http://127.0.0.1:8787/oauth/callback/github")
        self.assertTrue(result["ok"])
        self.assertIn("code_challenge=", result["authorization_url"])
        self.assertIn("state=", result["authorization_url"])
        self.assertNotIn("client-secret", result["authorization_url"])

    def test_invalid_state_never_stores_token(self):
        result = finish_oauth("github", "code", "invalid-state")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "oauth_state_invalid")
        self.assertFalse(Path(os.environ["OSG_CONNECTION_STORE"]).exists())

    def test_connection_metadata_never_exposes_token(self):
        Path(os.environ["OSG_CONNECTION_STORE"]).write_text(json.dumps({
            "github": {"account": "demo", "scopes": ["read:user"], "token": "secret-token"}
        }), encoding="utf-8")
        data = list_connections()
        self.assertTrue(data["connections"][0]["connected"])
        self.assertNotIn("secret-token", json.dumps(data))
        self.assertFalse(data["token_exposed"])

    def test_unconfigured_oauth_returns_actionable_setup_message(self):
        os.environ.pop("OSG_GITHUB_CLIENT_ID")
        result = begin_oauth("github", "http://127.0.0.1:8787/oauth/callback/github")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "oauth_app_not_configured")
        self.assertIn("OSG_GITHUB_CLIENT_ID", result["message"])


if __name__ == "__main__":
    unittest.main()
