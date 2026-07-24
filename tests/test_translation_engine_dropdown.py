"""Regression tests for Translation-tab engine discovery."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt5.QtWidgets import QApplication

    from gui.translation_tab import TRANSLATION_MODULE_SPECS, TranslationTab

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


if __name__ == "__main__":
    unittest.main()
