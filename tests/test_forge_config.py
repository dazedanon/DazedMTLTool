#!/usr/bin/env python3
"""Tests for install-time Forge plugin customization."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from util.forge.config import bundled_plugin_path, prepare_forge_js  # noqa: E402
from util.forge.installer import install  # noqa: E402


class ForgeConfigTests(unittest.TestCase):
    def test_modern_mz_hides_launcher_and_keeps_shortcut(self):
        output = prepare_forge_js(
            "MZ",
            cfg={"forgeHotkey": "F9", "uiScale": "auto"},
        )

        self.assertIn("favorites:{},showLauncher:!1,quickSaveSlot:1", output)
        self.assertIn("config.showLauncher = false;", output)
        self.assertIn("keyStr:`f9`", output)
        self.assertIn("saved.toggle_ui", output)
        self.assertIn("`.dazedtl/forge-config.json`", output)
        self.assertNotIn("bl=`forge-config.json`", output)

        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp)
            game.joinpath("js", "plugins").mkdir(parents=True)
            game.joinpath("js", "plugins.js").write_text(
                "var $plugins = [\n];\n", encoding="utf-8"
            )

            ok, message = install(game, cfg={"forgeHotkey": "F10"})

            self.assertTrue(ok, message)
            self.assertTrue(game.joinpath(".dazedtl").is_dir())
            ignore = game.joinpath(".gitignore").read_text(encoding="utf-8")
            self.assertIn("/.dazedtl/*", ignore.splitlines())
            self.assertNotIn(
                "!/.dazedtl/forge-config.json", ignore.splitlines()
            )
            installed = game.joinpath("js", "plugins", "Forge_MZ.js").read_text(
                encoding="utf-8"
            )
            self.assertIn("`.dazedtl/forge-config.json`", installed)

    def test_mv_uses_modern_bundle_and_keeps_legacy_fallback_available(self):
        self.assertEqual(bundled_plugin_path("MV"), bundled_plugin_path("MZ"))

        output = prepare_forge_js(
            "MV",
            cfg={"forgeHotkey": "F9", "uiScale": "auto"},
        )

        self.assertIn("favorites:{},showLauncher:!1,quickSaveSlot:1", output)
        self.assertIn("config.showLauncher = false;", output)
        self.assertIn("keyStr:`f9`", output)
        self.assertIn("saved.toggle_ui", output)

        legacy = ROOT / "util" / "forge" / "upstream" / "Forge_MV.js"
        self.assertTrue(legacy.is_file())
        self.assertNotEqual(bundled_plugin_path("MV"), legacy)

        fallback = prepare_forge_js(
            "MV",
            source=legacy,
            cfg={"forgeHotkey": "F9", "uiScale": "auto"},
        )
        self.assertIn("Floating launcher disabled", fallback)
        self.assertIn('window.Forge._hotkey = "F9";', fallback)

if __name__ == "__main__":
    unittest.main()
