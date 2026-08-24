#!/usr/bin/env python3
"""Regression tests for safe RPG Maker plugin registry edits."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from util.forge.installer import install as install_forge  # noqa: E402
from util.forge.installer import uninstall as uninstall_forge  # noqa: E402
from util.rpgmaker_plugin_registry import (  # noqa: E402
    format_plugins_js,
    plugin_names,
)
from util.tl_inspector.installer import install as install_inspector  # noqa: E402
from util.tl_inspector.installer import uninstall as uninstall_inspector  # noqa: E402


class PluginInstallerRegistryTests(unittest.TestCase):
    def _game(self, root: Path, registry: str, engine: str = "MZ") -> Path:
        js = root.joinpath("www", "js") if engine == "MV" else root / "js"
        js.joinpath("plugins").mkdir(parents=True)
        js.joinpath("plugins.js").write_text(registry, encoding="utf-8")
        return root

    def test_both_plugins_install_into_empty_registry_and_uninstall_cleanly(self):
        with tempfile.TemporaryDirectory() as temporary:
            game = self._game(
                Path(temporary),
                "var $plugins = [\n];\n",
            )
            registry = game / "js" / "plugins.js"

            ok, message = install_inspector(game, cfg={"hotkey": "F9"})
            self.assertTrue(ok, message)
            ok, message = install_forge(game, cfg={"forgeHotkey": "F10"})
            self.assertTrue(ok, message)
            self.assertEqual(
                plugin_names(registry.read_text(encoding="utf-8")),
                ("TLInspector", "Forge_MZ"),
            )
            installed_registry = registry.read_text(encoding="utf-8")
            self.assertEqual(installed_registry, format_plugins_js(installed_registry))

            ok, message = uninstall_forge(game)
            self.assertTrue(ok, message)
            ok, message = uninstall_inspector(game)
            self.assertTrue(ok, message)
            self.assertEqual(
                plugin_names(registry.read_text(encoding="utf-8")), ()
            )

    def test_install_repairs_legacy_leading_comma(self):
        installers = (
            ("Forge_MZ", "Forge_MZ.js", install_forge, {"forgeHotkey": "F10"}),
            ("TLInspector", "TLInspector.js", install_inspector, {"hotkey": "F9"}),
        )
        broken = (
            "var $plugins = [,\n"
            '{"name":"Existing","status":true,"description":"kept",'
            '"parameters":{"sample":"brace } and comma ,"}}\n'
            "];\n"
        )
        for plugin_name, filename, installer, config in installers:
            with self.subTest(plugin=plugin_name), tempfile.TemporaryDirectory() as temporary:
                game = self._game(Path(temporary), broken)
                ok, message = installer(game, cfg=config)
                self.assertTrue(ok, message)
                registry = game.joinpath("js", "plugins.js").read_text(
                    encoding="utf-8"
                )
                self.assertEqual(plugin_names(registry), ("Existing", plugin_name))
                self.assertTrue(game.joinpath("js", "plugins", filename).is_file())

    def test_mv_installers_preserve_legacy_javascript_parameter_escapes(self):
        legacy_value = "Value: \\V[1] / \\N[2] / \\C[3]"
        existing_entry = (
            '{"name":"Existing","status":true,"description":"kept",'
            f'"parameters":{{"Text":"{legacy_value}"}}}}'
        )
        with tempfile.TemporaryDirectory() as temporary:
            game = self._game(
                Path(temporary),
                f"var $plugins = [\n{existing_entry}\n];\n",
                engine="MV",
            )
            registry_path = game / "www" / "js" / "plugins.js"

            ok, message = install_inspector(game, cfg={"hotkey": "F9"})
            self.assertTrue(ok, message)
            ok, message = install_forge(game, cfg={"forgeHotkey": "F10"})
            self.assertTrue(ok, message)
            registry = registry_path.read_text(encoding="utf-8")
            self.assertEqual(
                plugin_names(registry),
                ("Existing", "TLInspector", "Forge_MV"),
            )
            self.assertIn(legacy_value, registry)

            ok, message = uninstall_forge(game)
            self.assertTrue(ok, message)
            ok, message = uninstall_inspector(game)
            self.assertTrue(ok, message)
            registry = registry_path.read_text(encoding="utf-8")
            self.assertEqual(plugin_names(registry), ("Existing",))
            self.assertIn(legacy_value, registry)

    def test_invalid_registry_is_unchanged_and_no_plugin_is_written(self):
        installers = (
            ("Forge_MZ.js", install_forge, {"forgeHotkey": "F10"}),
            ("TLInspector.js", install_inspector, {"hotkey": "F9"}),
        )
        invalid = b'var $plugins = [\n{"name":"Broken",}\n];\n'
        for filename, installer, config in installers:
            with self.subTest(plugin=filename), tempfile.TemporaryDirectory() as temporary:
                game = self._game(Path(temporary), invalid.decode("utf-8"))
                registry = game / "js" / "plugins.js"
                ok, _message = installer(game, cfg=config)
                self.assertFalse(ok)
                self.assertEqual(registry.read_bytes(), invalid)
                self.assertFalse(game.joinpath("js", "plugins", filename).exists())

    def test_registry_write_failure_rolls_back_existing_plugin_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            game = self._game(Path(temporary), "var $plugins = [\n];\n")
            target = game / "js" / "plugins" / "TLInspector.js"
            target.write_bytes(b"previous plugin")
            registry = game / "js" / "plugins.js"
            registry_before = registry.read_bytes()

            from util import rpgmaker_plugin_registry as registry_module

            real_write = registry_module.atomic_write_text
            calls = 0

            def fail_registry_write(path: Path, content: str) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("simulated registry write failure")
                real_write(path, content)

            with patch.object(
                registry_module,
                "atomic_write_text",
                side_effect=fail_registry_write,
            ):
                ok, _message = install_inspector(game, cfg={"hotkey": "F9"})

            self.assertFalse(ok)
            self.assertEqual(target.read_bytes(), b"previous plugin")
            self.assertEqual(registry.read_bytes(), registry_before)


if __name__ == "__main__":
    unittest.main()
