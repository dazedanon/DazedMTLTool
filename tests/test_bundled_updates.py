"""Integration tests for bundled-only utility updates and tool-only auto-update checks.

These tests use temporary directories and mocks — no live network or GUI window.
They guard the security model: third-party utilities must not fetch upstream unless
a maintainer explicitly uses --force / --refresh-offline / --refresh-all.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from util.wolfdawn import WolfDawnError, bundled_binary_path, ensure_wolf_binary


class UpdateThreadInstallFilterTests(unittest.TestCase):
    """Tool update must refresh shipped data/ assets while protecting user state."""

    def test_installs_translation_contexts_and_skills(self):
        from gui.main import UpdateThread

        for rel in (
            "data/translation_contexts.json",
            "data/skills/system.md",
            "data/skills/project_setup.md",
            "data/help/index.json",
            "data/help/00-welcome.md",
            "data/vocab_base.txt",
            "gui/main.py",
            "gameupdate/GameUpdate.bat",
            "gameupdate/gameupdate/patch.ps1",
        ):
            with self.subTest(rel=rel):
                self.assertTrue(UpdateThread.should_install(Path(rel)))

    def test_skips_user_local_data_and_workdir(self):
        from gui.main import UpdateThread

        for rel in (
            "data/vocab.txt",
            "data/last_update_sha.txt",
            "data/wolf_speakers.json",
            "data/wolf_safe_notes.json",
            ".env",
            "venv/pyvenv.cfg",
            "log/translations.txt",
            "files/Map001.json",
            "translated/Map001.json",
        ):
            with self.subTest(rel=rel):
                self.assertFalse(UpdateThread.should_install(Path(rel)))


class CheckToolUpdateTests(unittest.TestCase):
    """Tool update check compares remote SHA to data/last_update_sha.txt only."""

    def test_returns_sha_when_remote_differs(self):
        with tempfile.TemporaryDirectory() as raw:
            sha_file = Path(raw) / "last_update_sha.txt"
            sha_file.write_text("aaaaaaaa", encoding="utf-8")
            from gui.main import UpdateThread, check_tool_update

            with patch.object(UpdateThread, "SHA_FILE", str(sha_file)):
                with patch.object(
                    UpdateThread, "fetch_latest_sha", return_value="bbbbbbbb"
                ):
                    self.assertEqual(check_tool_update(), "bbbbbbbb")

    def test_returns_none_when_up_to_date(self):
        with tempfile.TemporaryDirectory() as raw:
            sha_file = Path(raw) / "last_update_sha.txt"
            sha_file.write_text("same1234", encoding="utf-8")
            from gui.main import UpdateThread, check_tool_update

            with patch.object(UpdateThread, "SHA_FILE", str(sha_file)):
                with patch.object(
                    UpdateThread, "fetch_latest_sha", return_value="same1234"
                ):
                    self.assertIsNone(check_tool_update())

    def test_returns_none_on_fetch_failure(self):
        from gui.main import UpdateThread, check_tool_update

        with patch.object(
            UpdateThread, "fetch_latest_sha", side_effect=OSError("offline")
        ):
            self.assertIsNone(check_tool_update())


class AceBundledOnlyTests(unittest.TestCase):
    def _ace_paths(self, base: Path) -> dict:
        offline = base / "offline"
        offline.mkdir(parents=True, exist_ok=True)
        return {
            "OFFLINE_DIR": offline,
            "RV2JSON_LOCAL": base / "RV2JSON.exe",
            "DECRYPTER_LOCAL": base / "RPGMakerDecrypter-cli.exe",
            "DECRYPTER_LEGACY": base / "RPGMakerDecrypter.exe",
            "VERSION_FILE": base / ".tools_version.json",
        }

    def test_seed_overwrites_stale_runtime_copy(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            paths = self._ace_paths(base)
            (paths["OFFLINE_DIR"] / "RV2JSON.exe").write_bytes(b"OFFLINE")
            paths["RV2JSON_LOCAL"].write_bytes(b"STALE")

            import util.ace.update_tools as ace

            with patch.multiple("util.ace.update_tools", **paths):
                ace._seed_from_offline(paths["RV2JSON_LOCAL"], "RV2JSON.exe", None)
            self.assertEqual(paths["RV2JSON_LOCAL"].read_bytes(), b"OFFLINE")

    def test_ensure_rv2json_does_not_contact_upstream(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            paths = self._ace_paths(base)
            (paths["OFFLINE_DIR"] / "RV2JSON.exe").write_bytes(b"OK")

            import util.ace.update_tools as ace

            with patch.multiple("util.ace.update_tools", **paths):
                with patch.object(
                    ace,
                    "_rv2json_upstream",
                    side_effect=AssertionError("must not fetch upstream"),
                ):
                    self.assertTrue(ace.ensure_rv2json(force=False))
            self.assertEqual(paths["RV2JSON_LOCAL"].read_bytes(), b"OK")

    def test_ensure_rv2json_fails_when_nothing_bundled(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            paths = self._ace_paths(base)

            import util.ace.update_tools as ace

            with patch.multiple("util.ace.update_tools", **paths):
                with patch.object(
                    ace,
                    "_rv2json_upstream",
                    side_effect=AssertionError("must not fetch upstream"),
                ):
                    self.assertFalse(ace.ensure_rv2json(force=False))

    def test_force_delegates_to_upstream_fetch(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            paths = self._ace_paths(base)

            import util.ace.update_tools as ace

            with patch.multiple("util.ace.update_tools", **paths):
                with patch.object(ace, "_fetch_rv2json_upstream", return_value=True) as fetch:
                    self.assertTrue(ace.ensure_rv2json(force=True))
            fetch.assert_called_once()


class ForgeBundledOnlyTests(unittest.TestCase):
    def _forge_paths(self, base: Path, *, with_plugins: bool) -> dict:
        upstream = base / "upstream"
        upstream.mkdir(parents=True, exist_ok=True)
        plugin_body = b"// forge plugin\n"
        paths = {
            "_PKG_ROOT": base,
            "UPSTREAM_DIR": upstream,
            "VERSION_FILE": base / ".forge_version.json",
        }
        if with_plugins:
            for name in ("Forge_MV.js", "Forge_MZ.js"):
                (base / name).write_bytes(plugin_body)
                (upstream / name).write_bytes(plugin_body)
        return paths

    def test_ensure_forge_plugins_does_not_contact_upstream(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            paths = self._forge_paths(base, with_plugins=True)

            import util.forge.update_tools as forge

            with patch.multiple("util.forge.update_tools", **paths):
                with patch.object(
                    forge,
                    "_upstream_commit",
                    side_effect=AssertionError("must not fetch upstream"),
                ):
                    with patch.object(
                        forge,
                        "refresh_forge_plugins",
                        side_effect=AssertionError("must not refresh upstream"),
                    ):
                        self.assertTrue(forge.ensure_forge_plugins(force=False))

    def test_ensure_forge_plugins_seeds_from_upstream_folder(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            paths = self._forge_paths(base, with_plugins=False)
            (paths["UPSTREAM_DIR"] / "Forge_MV.js").write_bytes(b"// mv")
            (paths["UPSTREAM_DIR"] / "Forge_MZ.js").write_bytes(b"// mz")

            import util.forge.update_tools as forge

            with patch.multiple("util.forge.update_tools", **paths):
                self.assertTrue(forge.ensure_forge_plugins(force=False))
            self.assertTrue((base / "Forge_MV.js").is_file())
            self.assertTrue((base / "Forge_MZ.js").is_file())

    def test_ensure_forge_plugins_fails_when_missing_everywhere(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            paths = self._forge_paths(base, with_plugins=False)

            import util.forge.update_tools as forge

            with patch.multiple("util.forge.update_tools", **paths):
                self.assertFalse(forge.ensure_forge_plugins(force=False))

    def test_force_calls_refresh_forge_plugins(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            paths = self._forge_paths(base, with_plugins=True)

            import util.forge.update_tools as forge

            with patch.multiple("util.forge.update_tools", **paths):
                with patch.object(forge, "refresh_forge_plugins", return_value=True) as refresh:
                    self.assertTrue(forge.ensure_forge_plugins(force=True))
            refresh.assert_called_once()


class WolfBundledOnlyTests(unittest.TestCase):
    def test_ensure_wolf_binary_uses_bundled_path(self):
        with tempfile.TemporaryDirectory() as raw:
            wolf = Path(raw) / "wolf"
            wolf.write_bytes(b"\x7fELF")
            with patch("util.wolfdawn.bundled_binary_path", return_value=wolf):
                self.assertEqual(ensure_wolf_binary(), wolf)

    def test_ensure_wolf_binary_makes_bundled_copy_executable(self):
        with tempfile.TemporaryDirectory() as raw:
            wolf = Path(raw) / "wolf"
            wolf.write_bytes(b"\x7fELF")
            wolf.chmod(0o644)
            with patch("util.wolfdawn.bundled_binary_path", return_value=wolf):
                with patch("util.wolfdawn._platform_dir", return_value="linux"):
                    ensure_wolf_binary()
            self.assertTrue(wolf.stat().st_mode & 0o111)

    def test_ensure_wolf_binary_raises_when_missing(self):
        missing = Path("/nonexistent/wolf/missing")
        with patch("util.wolfdawn.bundled_binary_path", return_value=missing):
            with self.assertRaises(WolfDawnError) as ctx:
                ensure_wolf_binary()
        self.assertIn("Update DazedMTLTool", str(ctx.exception))

    def test_ensure_wolf_binary_never_downloads(self):
        missing = Path("/nonexistent/wolf/missing")
        with patch("util.wolfdawn.bundled_binary_path", return_value=missing):
            with patch(
                "util.wolfdawn.download_wolf_binary",
                side_effect=AssertionError("must not download at runtime"),
            ):
                with self.assertRaises(WolfDawnError):
                    ensure_wolf_binary()

    def test_ensure_wolfdawn_binary_does_not_refresh_by_default(self):
        import util.wolfdawn.update_tools as wd_update

        wolf = bundled_binary_path()
        if not wolf.is_file():
            self.skipTest(f"no bundled wolf binary at {wolf}")

        with patch.object(
            wd_update,
            "refresh_wolfdawn_binary",
            side_effect=AssertionError("must not refresh upstream"),
        ):
            self.assertTrue(wd_update.ensure_wolfdawn_binary(force=False))

    def test_ensure_wolfdawn_binary_force_calls_refresh(self):
        import util.wolfdawn.update_tools as wd_update

        with patch.object(wd_update, "refresh_wolfdawn_binary", return_value=True) as refresh:
            with patch.object(wd_update, "bundled_binary_path", return_value=Path("/wolf")):
                with patch("pathlib.Path.is_file", return_value=True):
                    self.assertTrue(wd_update.ensure_wolfdawn_binary(force=True))
        refresh.assert_called_once()


class MaintainerRefreshTests(unittest.TestCase):
    """Maintainer CLI paths should still wire upstream fetch when explicitly invoked."""

    def test_refresh_offline_bundle_downloads_into_offline_dir(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            offline = base / "offline"
            offline.mkdir()

            import util.ace.update_tools as ace

            paths = {
                "OFFLINE_DIR": offline,
                "RV2JSON_LOCAL": base / "RV2JSON.exe",
                "DECRYPTER_LOCAL": base / "RPGMakerDecrypter-cli.exe",
                "DECRYPTER_LEGACY": base / "RPGMakerDecrypter.exe",
                "VERSION_FILE": base / ".tools_version.json",
            }

            def fake_download(url: str, dest: Path) -> None:
                dest.write_bytes(b"downloaded")

            with patch.multiple("util.ace.update_tools", **paths):
                with patch.object(
                    ace,
                    "_rv2json_upstream",
                    return_value=("sha1", "https://example/rv2json"),
                ):
                    with patch.object(
                        ace,
                        "_decrypter_upstream",
                        return_value=("v1", "https://example/dec"),
                    ):
                        with patch.object(ace, "_download", side_effect=fake_download):
                            self.assertTrue(ace.refresh_offline_bundle(log_fn=None))

            self.assertEqual((offline / "RV2JSON.exe").read_bytes(), b"downloaded")
            self.assertEqual(
                (offline / ace.DECRYPTER_ASSET).read_bytes(), b"downloaded"
            )

    def test_refresh_forge_plugins_installs_downloaded_bytes(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            upstream = base / "upstream"
            upstream.mkdir()

            import util.forge.update_tools as forge

            paths = {
                "_PKG_ROOT": base,
                "UPSTREAM_DIR": upstream,
                "VERSION_FILE": base / ".forge_version.json",
            }
            plugin = b"// downloaded forge\n"

            with patch.multiple("util.forge.update_tools", **paths):
                with patch.object(forge, "_upstream_commit", return_value="abc123"):
                    with patch.object(forge, "_fetch_plugins", return_value=plugin):
                        self.assertTrue(forge.refresh_forge_plugins(log_fn=None))

            self.assertEqual((base / "Forge_MV.js").read_bytes(), plugin)
            self.assertEqual((upstream / "Forge_MZ.js").read_bytes(), plugin)


if __name__ == "__main__":
    unittest.main(verbosity=2)
