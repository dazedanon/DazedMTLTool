from __future__ import annotations

import sys
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from util.config_integration import ConfigIntegration
from util.id_ranges import id_in_ranges, normalize_id_ranges, parse_id_ranges
from util.runtime_profile import (
    apply_batch_runtime_profile,
    capture_batch_runtime_profile,
)


class ConfigIntegrationRuntimeTests(unittest.TestCase):
    def test_compact_id_ranges_are_inclusive_normalized_and_reject_bad_input(self):
        value = "35, 37-40, 402, 408, 412, 418, 422, 428, 432, 438"

        self.assertTrue(id_in_ranges(35, value))
        self.assertTrue(id_in_ranges(40, value))
        self.assertFalse(id_in_ranges(36, value))
        self.assertEqual(parse_id_ranges("40, 37-39, 35, 39"), ((35, 35), (37, 40)))
        self.assertEqual(normalize_id_ranges("40, 37-39, 35, 39"), "35, 37-40")
        with self.assertRaisesRegex(ValueError, "Range end"):
            parse_id_ranges("40-37")

    def test_code122_range_string_is_quoted_persisted_and_read(self):
        with tempfile.TemporaryDirectory() as temporary:
            modules_dir = Path(temporary) / "modules"
            modules_dir.mkdir()
            module_path = modules_dir / "rpgmakermvmz.py"
            module_path.write_text(
                'CODE122_VAR_RANGES = ""\nCODE122_VAR_MIN = 0\nCODE122_VAR_MAX = 2000\n',
                encoding="utf-8",
            )
            integration = ConfigIntegration()
            integration.modules_dir = modules_dir

            integration.update_rpgmaker_config(
                {"CODE122_VAR_RANGES": "35, 37-40, 402"}
            )

            self.assertIn(
                "CODE122_VAR_RANGES = '35, 37-40, 402'",
                module_path.read_text(encoding="utf-8"),
            )
            self.assertEqual(
                integration.read_current_config()["CODE122_VAR_RANGES"],
                "35, 37-40, 402",
            )

    def test_rpgmaker_live_updates_and_batch_profiles_survive_runtime_drift(self):
        self.assertIsNone(capture_batch_runtime_profile("RPG Maker Plugin"))
        with tempfile.TemporaryDirectory() as temporary:
            modules_dir = Path(temporary) / "modules"
            modules_dir.mkdir()
            modules_dir.joinpath("rpgmakermvmz.py").write_text(
                "FIRSTLINESPEAKERS = False\nFACENAME101 = False\n",
                encoding="utf-8",
            )
            integration = ConfigIntegration()
            integration.modules_dir = modules_dir
            live_module = SimpleNamespace(
                FIRSTLINESPEAKERS=False,
                FACENAME101=False,
            )

            with patch.dict(
                sys.modules, {"modules.rpgmakermvmz": live_module}
            ):
                integration.update_rpgmaker_config({
                    "FIRSTLINESPEAKERS": True,
                    "FACENAME101": True,
                })

            written = modules_dir.joinpath("rpgmakermvmz.py").read_text(
                encoding="utf-8"
            )

        self.assertTrue(live_module.FIRSTLINESPEAKERS)
        self.assertTrue(live_module.FACENAME101)
        self.assertIn("FIRSTLINESPEAKERS = True", written)
        self.assertIn("FACENAME101 = True", written)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            modules_dir = root / "modules"
            modules_dir.mkdir()
            modules_dir.joinpath("rpgmakermvmz.py").write_text(
                "CODE101 = True\n"
                "CODE401 = True\n"
                "CODE405 = True\n"
                "CODE102 = True\n"
                'CODE122_VAR_RANGES = "35, 37-40, 402"\n'
                'ENABLED_PLUGINS_357: set = {"QuestSystem"}\n'
                'ENABLED_PATTERNS_355655: set = {"D_TEXT"}\n',
                encoding="utf-8",
            )
            profile = capture_batch_runtime_profile(
                "RPG Maker MV/MZ", root
            )

        drifted_module = SimpleNamespace(
            CODE101=False,
            CODE401=False,
            CODE405=False,
            CODE102=False,
            CODE122_VAR_RANGES="",
            ENABLED_PLUGINS_357=set(),
            ENABLED_PATTERNS_355655=set(),
        )
        apply_batch_runtime_profile(drifted_module, profile)

        self.assertTrue(drifted_module.CODE101)
        self.assertTrue(drifted_module.CODE401)
        self.assertTrue(drifted_module.CODE405)
        self.assertTrue(drifted_module.CODE102)
        self.assertEqual(drifted_module.CODE122_VAR_RANGES, "35, 37-40, 402")
        self.assertEqual(drifted_module.ENABLED_PLUGINS_357, {"QuestSystem"})
        self.assertEqual(drifted_module.ENABLED_PATTERNS_355655, {"D_TEXT"})

    def test_desktop_settings_freeze_engine_values_validate_and_recover_drafts(self):
        from desktop.backend.settings import SettingsStore
        from util.engine_options import apply_engine_options
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "modules").mkdir()
            engine = root / "modules/rpgmakermvmz.py"
            original = ('CODE401 = True\nCODE122_VAR_RANGES = ""\n'
                        'HEADER_MAPPINGS_357 = {"QuestSystem": (["text"], None)}\n'
                        'ENABLED_PLUGINS_357: set = set()\nENABLED_PATTERNS_355655: set = set()\n')
            engine.write_text(original)
            store = SettingsStore(root / "workspace", code_root=root)
            initial = store.describe()
            engines = initial["engines"]
            engines["rpgmakermvmz"].update(CODE401=False, CODE122_VAR_RANGES="3, 5-7", ENABLED_PLUGINS_357=["QuestSystem"])
            values = {**initial["values"], "width": 40, "faceWidth": 50}
            saved = store.save(0, values, engines)
            self.assertEqual(saved["values"]["faceWidth"], 40)
            frozen = saved["engines"]
            drifted = SimpleNamespace(__name__="modules.rpgmakermvmz", CODE401=True, CODE122_VAR_RANGES="", ENABLED_PLUGINS_357=set(), ENABLED_PATTERNS_355655=set())
            apply_engine_options(drifted, frozen)
            self.assertFalse(drifted.CODE401)
            self.assertEqual(drifted.ENABLED_PLUGINS_357, {"QuestSystem"})
            self.assertEqual(drifted.CODE122_VAR_RANGES, "3, 5-7")
            self.assertEqual(engine.read_text(), original)
            with self.assertRaisesRegex(ValueError, "changed elsewhere"):
                store.save(0, values, engines)
            for invalid in ({"CODE401": "false"}, {"ENABLED_PLUGINS_357": ["unknown"]}, {"MODEL": "changed"}):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    store.save(1, values, {"rpgmakermvmz": invalid})
            with self.assertRaises(ValueError):
                store.save(1, {**values, "width": True}, engines)
            draft = {**values, "width": ""}
            store.save_draft(1, draft, engines)
            reopened = SettingsStore(root / "workspace", code_root=root)
            self.assertEqual(reopened.describe()["draft"]["values"]["width"], "")
            self.assertEqual(reopened.read()["values"]["width"], 40)
            with self.assertRaises(ValueError):
                store.save_draft(1, {"key": "must-not-be-in-draft"}, engines)
            saved = reopened.save(1, values, engines)
            self.assertIsNone(saved["draft"])
            # Portable settings transfer must omit credentials and remain a
            # preview until the user saves; a .env import cannot expose a key.
            reopened.key_action("save", "Fixture", "test-private-key", "https://example.invalid/v1")
            exported = Path(reopened.transfer("export")["path"])
            self.assertNotIn("test-private-key", exported.read_text())
            imported = reopened.transfer("import", str(exported))
            self.assertEqual(imported["values"], saved["values"])
            self.assertEqual(imported["engines"], saved["engines"])
            env = root / "legacy.env"
            env.write_text("width=55\nkey=private-import-key\n")
            imported = reopened.transfer("import", str(env))
            self.assertEqual(imported["values"]["width"], 55)
            self.assertNotIn("private-import-key", json.dumps(imported))
            self.assertEqual(reopened.read()["values"]["width"], 40)
            self.assertEqual(reopened.runtime()["key"], "test-private-key")
            self.assertEqual(env.read_text(), "width=55\nkey=private-import-key\n")
            legacy = root / "project.json"
            legacy.write_text(json.dumps({"model": "fixture-model", "width": 58, "key": "legacy-project-secret"}))
            imported = reopened.transfer("import", str(legacy))
            self.assertEqual(imported["values"]["width"], 58)
            self.assertEqual(imported["values"]["model"], "fixture-model")
            self.assertNotIn("legacy-project-secret", json.dumps(imported))
            self.assertEqual(reopened.runtime()["key"], "test-private-key")


if __name__ == "__main__":
    unittest.main()
