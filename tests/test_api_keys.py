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
        self.env_path.write_text('key="sk-from-env"\n', encoding="utf-8")
        vault = api_keys.migrate_from_env_if_empty(
            vault_path=self.vault_path,
            env_path=self.env_path,
        )
        self.assertEqual(vault["active"], api_keys.DEFAULT_KEY_NAME)
        self.assertEqual(vault["keys"][api_keys.DEFAULT_KEY_NAME], "sk-from-env")

        # Second call must not overwrite existing vault entries.
        self.env_path.write_text('key="sk-other"\n', encoding="utf-8")
        vault2 = api_keys.migrate_from_env_if_empty(
            vault_path=self.vault_path,
            env_path=self.env_path,
        )
        self.assertEqual(vault2["keys"][api_keys.DEFAULT_KEY_NAME], "sk-from-env")

    def test_migrate_skips_placeholder_env_key(self):
        vault = api_keys.migrate_from_env_if_empty(
            vault_path=self.vault_path,
            env_key="<your-key-here>",
        )
        self.assertEqual(vault["keys"], {})

    def test_sync_active_to_env(self):
        api_keys.upsert_key("Work", "sk-work", path=self.vault_path)
        with patch.dict(os.environ, {}, clear=False):
            secret = api_keys.sync_active_to_env(
                vault_path=self.vault_path,
                env_path=self.env_path,
            )
            self.assertEqual(secret, "sk-work")
            self.assertEqual(os.environ.get("key"), "sk-work")
            text = self.env_path.read_text(encoding="utf-8")
            self.assertIn("sk-work", text)

    def test_save_writes_json_and_restrictive_mode(self):
        api_keys.upsert_key("X", "sk-x", path=self.vault_path)
        data = json.loads(self.vault_path.read_text(encoding="utf-8"))
        self.assertEqual(data["active"], "X")
        self.assertEqual(data["keys"]["X"], "sk-x")
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
