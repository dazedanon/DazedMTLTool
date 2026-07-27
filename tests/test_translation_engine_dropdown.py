"""Regression tests for Translation-tab engine discovery."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt5.QtWidgets import QApplication

    from gui.translation_tab import (
        BATCH_MODE_LABEL,
        TRANSLATION_MODULE_SPECS,
        TranslationTab,
        default_translation_mode,
    )

    _HAS_QT = True
except Exception:  # pragma: no cover - PyQt5 not installed
    _HAS_QT = False


@unittest.skipUnless(_HAS_QT, "PyQt5 not available")
class TranslationEngineDropdownTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_all_engines_are_listed_without_environment_configuration(self) -> None:
        required_settings = (
            "model",
            "language",
            "timeout",
            "width",
            "listWidth",
            "noteWidth",
        )
        without_settings = {
            key: value
            for key, value in os.environ.items()
            if key not in required_settings
        }

        with patch.dict(os.environ, without_settings, clear=True):
            tab = TranslationTab()

        expected = [
            f"{name} ({', '.join(extensions)})"
            for name, extensions, _module, _handler in TRANSLATION_MODULE_SPECS
        ]
        actual = [
            tab.module_combo.itemText(index)
            for index in range(tab.module_combo.count())
        ]
        self.assertEqual(actual, expected)
        self.assertTrue(all(callable(module[2]) for module in tab.modules))

    def test_normal_translate_is_default_for_non_claude_models(self) -> None:
        self.assertEqual(
            default_translation_mode("gpt-5.2", "https://api.openai.com/v1"),
            "Translate",
        )

    def test_batch_translate_is_default_for_native_claude(self) -> None:
        self.assertEqual(
            default_translation_mode("claude-sonnet-4-6", "https://api.anthropic.com/v1"),
            BATCH_MODE_LABEL,
        )

    def test_claude_through_custom_provider_defaults_to_normal(self) -> None:
        self.assertEqual(
            default_translation_mode("claude-sonnet-4-6", "https://openrouter.ai/api/v1"),
            "Translate",
        )

    def test_translation_tab_applies_detected_default(self) -> None:
        with patch("gui.translation_tab.default_translation_mode", return_value="Translate"):
            normal_tab = TranslationTab()
        self.assertEqual(normal_tab.mode_combo.currentText(), "Translate")

        with patch(
            "gui.translation_tab.default_translation_mode",
            return_value=BATCH_MODE_LABEL,
        ):
            claude_tab = TranslationTab()
        self.assertEqual(claude_tab.mode_combo.currentText(), BATCH_MODE_LABEL)


if __name__ == "__main__":
    unittest.main()
