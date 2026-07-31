"""Tests for the shared qtawesome icon helpers."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt5.QtWidgets import QApplication, QPushButton

    _HAS_QT = True
except Exception:  # pragma: no cover - PyQt5 not installed
    _HAS_QT = False


@unittest.skipUnless(_HAS_QT, "PyQt5 not available")
class TestQtIcons(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_split_leading_symbol(self) -> None:
        from gui.qt_icons import split_leading_symbol

        self.assertEqual(split_leading_symbol("🔑 API Configuration"),
                         ("mdi6.key-variant", "API Configuration"))
        self.assertEqual(split_leading_symbol("►►  Run Both"),
                         ("mdi6.fast-forward", "Run Both"))
        self.assertEqual(split_leading_symbol("Next →"), (None, "Next →"))
        # Unmapped leading symbol: emoji is stripped, no icon returned.
        name, rest = split_leading_symbol("Plain label")
        self.assertIsNone(name)
        self.assertEqual(rest, "Plain label")

    def test_file_category_icon_non_null(self) -> None:
        from gui.qt_icons import HAS_QTA, file_category_icon

        for category in ("core", "map", "other", "unknown-category"):
            icon = file_category_icon(category)
            if HAS_QTA:
                self.assertFalse(icon.isNull(), category)

    def test_apply_button_icon_strips_emoji(self) -> None:
        from gui.qt_icons import HAS_QTA, apply_button_icon

        btn = QPushButton()
        apply_button_icon(btn, "💾 Save glossary.txt", color="#cccccc")
        if HAS_QTA:
            self.assertEqual(btn.text(), "Save glossary.txt")
            self.assertFalse(btn.icon().isNull())

    def test_make_section_header_returns_widget(self) -> None:
        from gui.qt_icons import make_section_header

        w = make_section_header("🌐 Translation Settings", "color:#007acc;")
        self.assertIsNotNone(w)


if __name__ == "__main__":
    unittest.main()
