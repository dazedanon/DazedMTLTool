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

    def test_env_migration_ignores_placeholders_and_preserves_existing_credentials(self):
        for placeholder in (True, False):
            with self.subTest(placeholder=placeholder):
                self.vault_path.unlink(missing_ok=True)
                if placeholder:
                    vault = api_keys.migrate_from_env_if_empty(vault_path=self.vault_path, env_key="<your-key-here>")
                    self.assertEqual(vault['keys'], {})
                    continue
                self.env_path.write_text('key="sk-from-env"\napi="https://api.example.com/v1"\n', encoding='utf-8')
                vault = api_keys.migrate_from_env_if_empty(vault_path=self.vault_path, env_path=self.env_path)
                self.assertEqual(vault['active'], api_keys.DEFAULT_KEY_NAME)
                entry = vault['keys'][api_keys.DEFAULT_KEY_NAME]
                self.assertEqual(entry['secret'], 'sk-from-env')
                self.assertEqual(entry['endpoint'], 'https://api.example.com/v1')
                self.env_path.write_text('key="sk-other"\n', encoding='utf-8')
                again = api_keys.migrate_from_env_if_empty(vault_path=self.vault_path, env_path=self.env_path)
                self.assertEqual(again['keys'][api_keys.DEFAULT_KEY_NAME]['secret'], 'sk-from-env')

    def test_sync_active_credential_replaces_only_a_configured_endpoint(self):
        for endpoint in ('https://api.work.test/v1', ''):
            with self.subTest(endpoint=endpoint):
                self.vault_path.unlink(missing_ok=True)
                self.env_path.write_text('api="https://keep.me/v1"\nkey="old"\n', encoding='utf-8')
                api_keys.upsert_key('Work', 'sk-work', endpoint=endpoint, path=self.vault_path)
                with patch.dict(os.environ, {'api': 'https://keep.me/v1'}, clear=False):
                    secret = api_keys.sync_active_to_env(vault_path=self.vault_path, env_path=self.env_path)
                    self.assertEqual(secret, 'sk-work')
                    self.assertEqual(os.environ.get('key'), 'sk-work')
                    self.assertEqual(os.environ.get('API_KEY_OPTIONAL'), 'false')
                    self.assertEqual(os.environ.get('api'), endpoint or 'https://keep.me/v1')
                    text = self.env_path.read_text(encoding='utf-8')
                    self.assertIn('sk-work', text)
                    self.assertIn(endpoint or 'https://keep.me/v1', text)

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
        for name, secret, keyless in (("", "sk", False), ("Name", "  ", False), ("Local", "", True)):
            with self.subTest(name=name, keyless=keyless), self.assertRaises(ValueError):
                api_keys.upsert_key(name, secret, keyless=keyless, path=self.vault_path)

    def test_keyless_local_endpoint_roundtrip_and_sync(self):
        api_keys.upsert_key(
            "Local",
            "",
            endpoint="http://127.0.0.1:1234/v1",
            keyless=True,
            path=self.vault_path,
        )

        self.assertEqual(api_keys.list_names(self.vault_path), ["Local"])
        self.assertEqual(api_keys.get_active_secret(self.vault_path), "")
        self.assertTrue(api_keys.is_keyless("Local", self.vault_path))
        self.assertTrue(api_keys.is_active_keyless(self.vault_path))

        with patch.dict(os.environ, {}, clear=False):
            api_keys.sync_active_to_env(
                vault_path=self.vault_path,
                env_path=self.env_path,
            )
            self.assertEqual(os.environ.get("key"), "")
            self.assertEqual(os.environ.get("API_KEY_OPTIONAL"), "true")
            text = self.env_path.read_text(encoding="utf-8")
            self.assertIn("API_KEY_OPTIONAL='true'", text)

    def test_desktop_vault_roundtrip_redacts_secrets_and_preserves_legacy_installation(self):
        from desktop.backend.settings import SettingsStore
        store = SettingsStore(self.base / "desktop", code_root=self.base)
        visible = store.key_action("save", "Cloud", "unique-test-secret", "https://api.example.test/v1")
        self.assertNotIn("unique-test-secret", json.dumps(visible))
        self.assertEqual(store.runtime()["key"], "unique-test-secret")
        store.key_action("save", "Cloud", endpoint="https://updated.example.test/v1")
        self.assertEqual(store.runtime()["key"], "unique-test-secret")
        self.assertEqual(store.runtime()["api"], "https://updated.example.test/v1")
        store.key_action("save", "Local", endpoint="http://127.0.0.1:1234/v1", keyless=True)
        self.assertEqual(store.runtime()["API_KEY_OPTIONAL"], "true")
        self.assertEqual(store.runtime()["key"], "")
        legacy = self.base / "legacy"
        legacy.mkdir()
        contents = 'key="legacy-test-secret"\napi="https://legacy.test/v1"\nmodel="imported-model"\n'
        (legacy / ".env").write_text(contents)
        environment = dict(os.environ)
        imported = store.import_legacy(str(legacy), 0)
        self.assertEqual(imported["values"]["model"], "imported-model")
        self.assertEqual(imported["active_key"], "Local")
        self.assertNotIn("legacy-test-secret", json.dumps(imported))
        self.assertEqual((legacy / ".env").read_text(), contents)
        self.assertEqual(dict(os.environ), environment)
        store.key_action("select", "Imported")
        self.assertEqual(store.runtime()["key"], "legacy-test-secret")
        store.key_action("delete", "Imported")
        self.assertNotIn("Imported", [key["name"] for key in store.describe()["keys"]])


if __name__ == "__main__":
    unittest.main(verbosity=2)
