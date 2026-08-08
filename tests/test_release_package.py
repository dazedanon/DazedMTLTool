#!/usr/bin/env python3
"""Tests for player-ready public release archives and workflow buttons."""

from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from util.release_package import ReleasePackageError, create_release_zip


class ReleasePackageTests(unittest.TestCase):
    def _write(self, root: Path, relative: str, content: bytes = b"content") -> Path:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def test_release_keeps_game_and_updater_but_omits_tool_artifacts(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            game = base / "Translated Game"
            game.mkdir()

            self._write(game, "Game.exe", b"game")
            self._write(game, "Data.wolf", b"translated archive")
            self._write(game, "Data.wolf.bak", b"original backup")
            self._write(game, "Data/manual.txt", b"runtime text")
            self._write(game, "Save01.sav", b"translator save")
            self._write(game, "Save/Slot1.rpgsave", b"translator save")
            nested_save = self._write(
                game, "www/save/file1.rpgsave", b"nested translator save"
            )
            nested_sav = self._write(
                game, "runtime/profile.sav", b"nested translator save"
            )
            self._write(game, ".git/config")
            self._write(game, ".dazedtl/images/menu.png")
            self._write(game, "wolf_json/manifest.json")
            self._write(game, "ace_json/Actors.json")
            self._write(game, "scripts/release.py")
            self._write(game, "docs/translation-notes.md")
            self._write(game, "skills/game.md")
            self._write(game, "glossary.txt")
            self._write(game, "vocab.txt")
            self._write(game, "README.md")
            self._write(game, ".gitignore")
            self._write(game, ".env", b"key=secret")

            self._write(game, "GameUpdate.bat", b"launcher")
            self._write(game, "GameUpdate_linux.sh", b"launcher")
            self._write(game, "UberWolfCli.exe", b"wolf updater")
            self._write(game, "UberWolfCli.LICENSE.txt", b"license")
            self._write(game, "gameupdate/patch.ps1", b"patch")
            self._write(game, "gameupdate/patch-config.txt", b"repo=game")
            self._write(game, "gameupdate/previous_patch_sha.txt", b"private state")

            plugins_js = b"""var $plugins =
[
  {"name":"CorePlugin","status":true,"parameters":{"label":"keep"}},
  {"name":"TLInspector","status":true,"parameters":{}},
  {"name":"Forge_MZ","status":true,"parameters":{}}
];
"""
            source_plugins = self._write(game, "js/plugins.js", plugins_js)
            self._write(game, "js/plugins/CorePlugin.js", b"core")
            self._write(game, "js/plugins/TLInspector.js", b"inspector")
            self._write(game, "js/plugins/Forge_MZ.js", b"forge")

            output = base / "release.zip"
            progress = []
            result = create_release_zip(
                game,
                output,
                progress=lambda current, total, label: progress.append(
                    (current, total, label)
                ),
            )

            prefix = "Translated Game/"
            with zipfile.ZipFile(output) as archive:
                names = set(archive.namelist())
                archived_plugin_bytes = archive.read(prefix + "js/plugins.js")
                archived_plugins = archived_plugin_bytes.decode("utf-8")

            for relative in (
                "Game.exe",
                "Data.wolf",
                "Data/manual.txt",
                "GameUpdate.bat",
                "GameUpdate_linux.sh",
                "UberWolfCli.exe",
                "UberWolfCli.LICENSE.txt",
                "gameupdate/patch.ps1",
                "gameupdate/patch-config.txt",
                "js/plugins/CorePlugin.js",
                "js/plugins/TLInspector.js",
                "js/plugins/Forge_MZ.js",
            ):
                self.assertIn(prefix + relative, names)

            for relative in (
                "Data.wolf.bak",
                "Save01.sav",
                "Save/Slot1.rpgsave",
                "www/save/file1.rpgsave",
                "runtime/profile.sav",
                ".git/config",
                ".dazedtl/images/menu.png",
                "wolf_json/manifest.json",
                "ace_json/Actors.json",
                "scripts/release.py",
                "docs/translation-notes.md",
                "skills/game.md",
                "glossary.txt",
                "vocab.txt",
                "README.md",
                ".gitignore",
                ".env",
                "gameupdate/previous_patch_sha.txt",
            ):
                self.assertNotIn(prefix + relative, names)

            self.assertEqual(nested_save.read_bytes(), b"nested translator save")
            self.assertEqual(nested_sav.read_bytes(), b"nested translator save")

            self.assertIn('"name":"CorePlugin"', archived_plugins)
            self.assertIn("TLInspector", archived_plugins)
            self.assertIn("Forge_MZ", archived_plugins)
            self.assertEqual(archived_plugin_bytes, plugins_js)
            self.assertEqual(source_plugins.read_bytes(), plugins_js)
            self.assertEqual(result.output_path, output.resolve())
            self.assertEqual(progress[-1][:2], (result.files_added, result.files_added))

    def test_release_path_must_be_outside_game_folder(self):
        with tempfile.TemporaryDirectory() as raw:
            game = Path(raw) / "Game"
            game.mkdir()
            self._write(game, "Game.exe")
            output = game / "release.zip"

            with self.assertRaisesRegex(ReleasePackageError, "outside the game folder"):
                create_release_zip(game, output)

            self.assertFalse(output.exists())

    def test_zip_suffix_is_added(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            game = base / "Game"
            game.mkdir()
            self._write(game, "Game.exe")

            result = create_release_zip(game, base / "release")

            self.assertEqual(result.output_path.name, "release.zip")
            self.assertTrue(result.output_path.is_file())


if __name__ == "__main__":
    unittest.main()
