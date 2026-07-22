"""Unit tests for the named API key vault."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from util import api_keys


class ApiKeyVaultTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.vault_path = self.base / "api_keys.json"
        self.env_path = self.base / ".env"

    def tearDown(self):
        self._tmp.cleanup()

    def test_upsert_list_and_active(self):
        api_keys.upsert_key("OpenAI", "sk-openai", path=self.vault_path)
        api_keys.upsert_key("DeepSeek", "sk-deep", make_active=True, path=self.vault_path)

        self.assertEqual(api_keys.list_names(self.vault_path), ["DeepSeek", "OpenAI"])
        self.assertEqual(api_keys.get_active_name(self.vault_path), "DeepSeek")
        self.assertEqual(api_keys.get_active_secret(self.vault_path), "sk-deep")
        self.assertEqual(api_keys.get_secret("OpenAI", self.vault_path), "sk-openai")

    def test_set_active_and_delete(self):
        api_keys.upsert_key("A", "secret-a", path=self.vault_path)
        api_keys.upsert_key("B", "secret-b", make_active=False, path=self.vault_path)
        api_keys.set_active("B", path=self.vault_path)
        self.assertEqual(api_keys.get_active_secret(self.vault_path), "secret-b")

        api_keys.delete_key("B", path=self.vault_path)
        self.assertEqual(api_keys.get_active_name(self.vault_path), "A")
        self.assertEqual(api_keys.list_names(self.vault_path), ["A"])

        api_keys.delete_key("A", path=self.vault_path)
        self.assertEqual(api_keys.list_names(self.vault_path), [])
        self.assertEqual(api_keys.get_active_name(self.vault_path), "")
        self.assertEqual(api_keys.get_active_secret(self.vault_path), "")

    def test_migrate_from_env_when_vault_empty(self):
        self.env_path.write_text(
            'key="sk-from-env"\napi="https://api.example.com/v1"\n',
            encoding="utf-8",
        )
        vault = api_keys.migrate_from_env_if_empty(
            vault_path=self.vault_path,
            env_path=self.env_path,
        )
        self.assertEqual(vault["active"], api_keys.DEFAULT_KEY_NAME)
        entry = vault["keys"][api_keys.DEFAULT_KEY_NAME]
        self.assertEqual(entry["secret"], "sk-from-env")
        self.assertEqual(entry["endpoint"], "https://api.example.com/v1")

        # Second call must not overwrite existing vault entries.
        self.env_path.write_text('key="sk-other"\n', encoding="utf-8")
        vault2 = api_keys.migrate_from_env_if_empty(
            vault_path=self.vault_path,
            env_path=self.env_path,
        )
        self.assertEqual(
            vault2["keys"][api_keys.DEFAULT_KEY_NAME]["secret"], "sk-from-env"
        )

    def test_migrate_skips_placeholder_env_key(self):
        vault = api_keys.migrate_from_env_if_empty(
            vault_path=self.vault_path,
            env_key="<your-key-here>",
        )
        self.assertEqual(vault["keys"], {})

    def test_sync_active_to_env(self):
        api_keys.upsert_key(
            "Work",
            "sk-work",
            endpoint="https://api.work.test/v1",
            path=self.vault_path,
        )
        with patch.dict(os.environ, {}, clear=False):
            secret = api_keys.sync_active_to_env(
                vault_path=self.vault_path,
                env_path=self.env_path,
            )
            self.assertEqual(secret, "sk-work")
            self.assertEqual(os.environ.get("key"), "sk-work")
            self.assertEqual(os.environ.get("api"), "https://api.work.test/v1")
            text = self.env_path.read_text(encoding="utf-8")
            self.assertIn("sk-work", text)
            self.assertIn("https://api.work.test/v1", text)

    def test_sync_without_endpoint_leaves_api_alone(self):
        self.env_path.write_text('api="https://keep.me/v1"\nkey="old"\n', encoding="utf-8")
        api_keys.upsert_key("Local", "sk-local", path=self.vault_path)
        with patch.dict(os.environ, {"api": "https://keep.me/v1"}, clear=False):
            api_keys.sync_active_to_env(
                vault_path=self.vault_path,
                env_path=self.env_path,
            )
            text = self.env_path.read_text(encoding="utf-8")
            self.assertIn("https://keep.me/v1", text)
            self.assertEqual(os.environ.get("api"), "https://keep.me/v1")

    def test_endpoint_roundtrip_and_legacy_string_entries(self):
        self.vault_path.write_text(
            json.dumps({"active": "Legacy", "keys": {"Legacy": "sk-legacy"}}),
            encoding="utf-8",
        )
        self.assertEqual(api_keys.get_secret("Legacy", self.vault_path), "sk-legacy")
        self.assertEqual(api_keys.get_endpoint("Legacy", self.vault_path), "")

        api_keys.upsert_key(
            "Claude",
            "sk-claude",
            endpoint="https://api.anthropic.com/v1",
            path=self.vault_path,
        )
        self.assertEqual(
            api_keys.get_endpoint("Claude", self.vault_path),
            "https://api.anthropic.com/v1",
        )
        data = json.loads(self.vault_path.read_text(encoding="utf-8"))
        self.assertEqual(data["keys"]["Claude"]["endpoint"], "https://api.anthropic.com/v1")
        # Legacy string entry is normalized on next save.
        api_keys.set_active("Legacy", path=self.vault_path)
        data2 = json.loads(self.vault_path.read_text(encoding="utf-8"))
        self.assertEqual(data2["keys"]["Legacy"]["secret"], "sk-legacy")

    def test_keep_secret_if_blank_updates_endpoint(self):
        api_keys.upsert_key("A", "sk-a", path=self.vault_path)
        api_keys.upsert_key(
            "A",
            "",
            endpoint="https://api.a.test/v1",
            path=self.vault_path,
            keep_secret_if_blank=True,
        )
        self.assertEqual(api_keys.get_secret("A", self.vault_path), "sk-a")
        self.assertEqual(
            api_keys.get_endpoint("A", self.vault_path), "https://api.a.test/v1"
        )

    def test_save_writes_json_and_restrictive_mode(self):
        api_keys.upsert_key("X", "sk-x", path=self.vault_path)
        data = json.loads(self.vault_path.read_text(encoding="utf-8"))
        self.assertEqual(data["active"], "X")
        self.assertEqual(data["keys"]["X"]["secret"], "sk-x")
        mode = self.vault_path.stat().st_mode & 0o777
        # Best-effort: owner read/write only when chmod is honored.
        self.assertEqual(mode & 0o077, 0)

    def test_upsert_rejects_blank(self):
        with self.assertRaises(ValueError):
            api_keys.upsert_key("", "sk", path=self.vault_path)
        with self.assertRaises(ValueError):
            api_keys.upsert_key("Name", "  ", path=self.vault_path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
