"""Regression tests for shared engine dispatch and input ownership."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

class ImageTextEngineTests(unittest.TestCase):
    """The engine the semi-manual image workflow hands its export to.

    Two things are easy to get wrong about it and expensive to get wrong: which
    files it offers, and which handler actually runs. It is declared by whole
    filename rather than by extension, and its display name contains another
    engine's name.
    """

    ENGINE = "Image Text"

    def _spec(self):
        from util.translation_task import TRANSLATION_MODULE_SPECS as specs

        for spec in specs:
            if spec[0] == self.ENGINE:
                return spec
        self.fail(f"{self.ENGINE} is not registered")

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

    def test_runner_dispatches_exact_engine_names_without_substring_collisions(self):
        """Image Text and Aquedi4 JSON must reach their own file handlers."""
        from types import SimpleNamespace
        from unittest.mock import Mock
        from util.translation_task import translation_module

        for name, module_name, handler_name in (
            ("Image Text", "modules.imagetext", "handleImageText"),
            ("Text", "modules.text", "handleText"),
            ("Aquedi4 Prepared JSON", "modules.aquedi4", "handleAquedi4"),
            ("JSON", "modules.json", "handleJSON"),
        ):
            with self.subTest(name=name):
                handler = Mock(return_value="Success")
                module = SimpleNamespace(**{handler_name: handler})
                with patch("util.translation_task.import_module", return_value=module) as load:
                    selected = translation_module(name)
                    load.assert_not_called()
                    self.assertEqual(selected[2]("fixture.json", True), "Success")
                    load.assert_called_once_with(module_name)
                    handler.assert_called_once_with("fixture.json", True)
        with self.assertRaises(ValueError):
            translation_module("Unknown JSON")

    def test_the_image_handler_exists_under_the_name_the_registry_uses(self):
        """A registry row that names a handler nothing exports fails at run time.

        Imported with settings in place because every engine in this project
        reads the environment at import, which is also why the registry stores
        the handler's *name* and resolves it late.
        """
        import importlib

        settings = {"model": "gpt-4o-mini", "language": "English"}
        with patch.dict(os.environ, settings):
            _name, _patterns, module_path, handler = self._spec()
            module = importlib.import_module(module_path)
        self.assertTrue(callable(getattr(module, handler)))


if __name__ == "__main__":
    unittest.main()
