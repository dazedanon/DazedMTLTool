"""Regression tests for Translation-tab engine discovery."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
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
            "faceWidth",
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

    def test_selects_default_translation_mode_for_provider_routes(self) -> None:
        cases = (
            (
                "native OpenAI",
                ("gpt-5.2", "https://api.openai.com/v1"),
                BATCH_MODE_LABEL,
            ),
            (
                "native Anthropic",
                ("claude-sonnet-4-6", "https://api.anthropic.com/v1"),
                BATCH_MODE_LABEL,
            ),
            (
                "native Gemini",
                (
                    "gemini-3.1-pro",
                    "https://generativelanguage.googleapis.com/v1beta/openai/",
                    "gemini",
                ),
                BATCH_MODE_LABEL,
            ),
            (
                "Claude through custom provider",
                ("claude-sonnet-4-6", "https://openrouter.ai/api/v1"),
                "Translate",
            ),
        )
        for label, arguments, expected in cases:
            with self.subTest(label):
                self.assertEqual(default_translation_mode(*arguments), expected)

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


class ImageTextEngineTests(unittest.TestCase):
    """The engine the semi-manual image workflow hands its export to.

    Two things are easy to get wrong about it and expensive to get wrong: which
    files it offers, and which handler actually runs. It is declared by whole
    filename rather than by extension, and its display name contains another
    engine's name.
    """

    ENGINE = "Image Text"

    def _spec(self):
        from gui.translation_tab import TRANSLATION_MODULE_SPECS as specs

        for spec in specs:
            if spec[0] == self.ENGINE:
                return spec
        self.fail(f"{self.ENGINE} is not registered")

    @unittest.skipUnless(_HAS_QT, "PyQt5 not available")
    def test_it_is_registered_and_points_at_its_own_module(self):
        _name, patterns, module_path, handler = self._spec()
        self.assertEqual(patterns, ("image_text.json",))
        self.assertEqual(module_path, "modules.imagetext")
        self.assertEqual(handler, "handleImageText")

    @unittest.skipUnless(_HAS_QT, "PyQt5 not available")
    def test_it_offers_its_own_export_and_nothing_else(self):
        """Declared by filename so it can never offer up a data folder.

        The tab filters with ``name.endswith(pattern)``, and an RPG Maker
        project is full of .json files that would be destroyed by this engine.
        """
        _name, patterns, _module, _handler = self._spec()

        def accepted(filename):
            return any(filename.endswith(pattern) for pattern in patterns)

        self.assertTrue(accepted("image_text.json"))
        for other in ("Actors.json", "Map001.json", "System.json", "text.json"):
            with self.subTest(other):
                self.assertFalse(accepted(other))

    def test_the_runner_reaches_the_image_handler_and_not_the_text_one(self):
        """The dispatch chain matches substrings, and "Text" is inside "Image Text".

        Below the plain-text branch this engine's whole JSON export would be
        fed to ``handleText`` line by line, which silently destroys the file.
        Ordering is the only thing preventing that, so it is pinned here.

        Read rather than imported: ``util/subprocess_runner.py`` rebinds
        ``sys.stdout`` at import time, which fails outright under a test runner
        that has captured it.
        """
        from util.paths import PROJECT_ROOT

        source = (PROJECT_ROOT / "util" / "subprocess_runner.py").read_text(
            encoding="utf-8"
        )
        image = source.index('"Image Text" in module_name')
        text = source.index('"Text" in module_name', image + 1)
        self.assertLess(
            image,
            text,
            'the "Image Text" branch must come before the "Text" branch',
        )

    def test_the_image_handler_exists_under_the_name_the_registry_uses(self):
        """A registry row that names a handler nothing exports fails at run time.

        Imported with settings in place because every engine in this project
        reads the environment at import, which is also why the registry stores
        the handler's *name* and resolves it late.
        """
        import importlib

        settings = {"model": "gpt-4o-mini", "language": "English"}
        with patch.dict(os.environ, settings):
            module = importlib.import_module("modules.imagetext")
        self.assertTrue(callable(getattr(module, "handleImageText")))


if __name__ == "__main__":
    unittest.main()
