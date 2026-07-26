#!/usr/bin/env python3
"""Tests for install-time Forge plugin customization."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from util.forge.config import prepare_forge_js  # noqa: E402


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

    def test_legacy_mv_omits_launcher_and_keeps_shortcut(self):
        output = prepare_forge_js(
            "MV",
            cfg={"forgeHotkey": "F9", "uiScale": "auto"},
        )

        self.assertNotIn("rootEl.appendChild(launcher);", output)
        self.assertIn("Floating launcher disabled", output)
        self.assertIn('window.Forge._hotkey = "F9";', output)
        self.assertIn("if (key === (API._hotkey || 'F10'))", output)


if __name__ == "__main__":
    unittest.main()
