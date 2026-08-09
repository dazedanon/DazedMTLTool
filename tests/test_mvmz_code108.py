#!/usr/bin/env python3
"""Regression tests for translatable RPG Maker code-108 notetags."""

from __future__ import annotations

import copy
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

import modules.rpgmakermvmz as mvmz  # noqa: E402


class TestMVMZCode108(unittest.TestCase):
    def test_name_pop_notetag_translates_only_its_value(self):
        source = "階層移動"
        page = {
            "list": [
                {
                    "code": 108,
                    "indent": 0,
                    "parameters": [f" <namePop:{source}>"],
                }
            ]
        }
        captured = []

        def translate(text, history, batch=False):
            captured.append(copy.deepcopy(text))
            return [["Floor Movement"], [0, 0]]

        original_translate = mvmz.translateAI
        original_code108 = mvmz.CODE108
        mvmz.translateAI = translate
        mvmz.CODE108 = True
        try:
            translated_page = copy.deepcopy(page)
            mvmz.searchCodes(translated_page, None, [], "TestMap.json")
        finally:
            mvmz.translateAI = original_translate
            mvmz.CODE108 = original_code108

        self.assertEqual(captured, [[source]])
        self.assertEqual(
            translated_page["list"][0]["parameters"][0],
            " <namePop:Floor_Movement>",
        )
        with patch.object(mvmz, "CODE108", True):
            self.assertEqual(mvmz._code108_progress_units(page["list"]), 1)
            self.assertEqual(
                mvmz._code108_progress_units(
                    [
                        {
                            "code": 108,
                            "indent": 0,
                            "parameters": ["選択肢ヘルプ"],
                        }
                    ]
                ),
                0,
            )
        with patch.object(mvmz, "CODE108", False):
            self.assertEqual(mvmz._code108_progress_units(page["list"]), 0)


if __name__ == "__main__":
    unittest.main()
