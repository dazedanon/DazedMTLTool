from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from gui.config_integration import ConfigIntegration
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


if __name__ == "__main__":
    unittest.main()
