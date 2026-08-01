from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from gui.config_integration import ConfigIntegration


class ConfigIntegrationRuntimeTests(unittest.TestCase):
    def test_rpgmaker_updates_refresh_an_already_imported_module(self):
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


if __name__ == "__main__":
    unittest.main()
