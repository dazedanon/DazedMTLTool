#!/usr/bin/env python3
"""Regression tests for RPG Maker code-355/655 script patterns."""

from __future__ import annotations

import copy
import os
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

import modules.rpgmakermvmz as mvmz  # noqa: E402


class TestMVMZScriptPatterns(unittest.TestCase):
    def test_cbr_erotic_status_pattern_definition(self):
        regex, multiline = mvmz.PATTERNS_355655["CBR-エロステータス"]

        self.assertEqual(regex, r"テキスト-(.+)")
        self.assertTrue(multiline)

    def test_cbr_erotic_status_multiline_integration(self):
        source_statuses = ["回", "人"]
        translated_statuses = ["times", "people"]
        page = {
            "list": [
                {
                    "code": 355,
                    "indent": 0,
                    "parameters": ["CBR-エロステータス"],
                },
                {
                    "code": 655,
                    "indent": 0,
                    "parameters": ["コマンド-表示"],
                },
                *[
                    {
                        "code": 655,
                        "indent": 0,
                        "parameters": [f"テキスト-{status}"],
                    }
                    for status in source_statuses
                ],
                {
                    "code": 655,
                    "indent": 0,
                    "parameters": ["テキスト-％"],
                },
            ]
        }
        captured = []

        def translate(text, history, batch=False):
            captured.append(copy.deepcopy(text))
            return [copy.deepcopy(translated_statuses), [0, 0]]

        original_translate = mvmz.translateAI
        original_code355655 = mvmz.CODE355655
        original_enabled = mvmz.ENABLED_PATTERNS_355655
        mvmz.translateAI = translate
        mvmz.CODE355655 = True
        mvmz.ENABLED_PATTERNS_355655 = {"CBR-エロステータス"}
        try:
            translated_page = copy.deepcopy(page)
            mvmz.searchCodes(translated_page, None, [], "TestMap.json")
        finally:
            mvmz.translateAI = original_translate
            mvmz.CODE355655 = original_code355655
            mvmz.ENABLED_PATTERNS_355655 = original_enabled

        self.assertEqual(captured, [source_statuses])
        self.assertEqual(translated_page["list"][0], page["list"][0])
        self.assertEqual(translated_page["list"][1], page["list"][1])
        self.assertEqual(
            [entry["parameters"][0] for entry in translated_page["list"][2:4]],
            [f"テキスト-{status}" for status in translated_statuses],
        )
        self.assertEqual(translated_page["list"][4], page["list"][4])

    def test_cbr_text_replacement_does_not_modify_matching_marker_text(self):
        page = {
            "list": [
                {
                    "code": 355,
                    "indent": 0,
                    "parameters": ["CBR-エロステータス"],
                },
                {
                    "code": 655,
                    "indent": 0,
                    "parameters": ["テキスト-キス"],
                },
            ]
        }

        def translate(text, history, batch=False):
            self.assertEqual(text, ["キス"])
            return [["Kiss"], [0, 0]]

        original_translate = mvmz.translateAI
        original_code355655 = mvmz.CODE355655
        original_enabled = mvmz.ENABLED_PATTERNS_355655
        mvmz.translateAI = translate
        mvmz.CODE355655 = True
        mvmz.ENABLED_PATTERNS_355655 = {"CBR-エロステータス"}
        try:
            translated_page = copy.deepcopy(page)
            mvmz.searchCodes(translated_page, None, [], "TestMap.json")
        finally:
            mvmz.translateAI = original_translate
            mvmz.CODE355655 = original_code355655
            mvmz.ENABLED_PATTERNS_355655 = original_enabled

        self.assertEqual(
            translated_page["list"][1]["parameters"][0],
            "テキスト-Kiss",
        )

    def test_battle_manager_can_escape_pattern_definition(self):
        regex, multiline = mvmz.PATTERNS_355655["if (BattleManager.canEscape())"]

        self.assertEqual(
            regex,
            r'\$gameMessage\.add\(\s*"((?:\\.|[^"\\])*)"\s*\)',
        )
        self.assertTrue(multiline)

    def test_battle_manager_can_escape_extracts_only_message_text(self):
        regex, _ = mvmz.PATTERNS_355655["if (BattleManager.canEscape())"]
        script = r'$gameMessage.add("この戦闘では逃げることはできない！")'

        match = re.search(regex, script)

        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "この戦闘では逃げることはできない！")

    def test_battle_manager_can_escape_multiline_integration(self):
        source_message = "この戦闘では逃げることはできない！"
        translated_message = "You cannot escape from this battle!"
        page = {
            "list": [
                {
                    "code": 355,
                    "indent": 0,
                    "parameters": ["if (BattleManager.canEscape()) {"],
                },
                {
                    "code": 655,
                    "indent": 0,
                    "parameters": ["// このコメントは翻訳しない"],
                },
                {
                    "code": 655,
                    "indent": 0,
                    "parameters": [f'$gameMessage.add("{source_message}");'],
                },
                {
                    "code": 655,
                    "indent": 0,
                    "parameters": ['const command = "内部CBRコマンド";'],
                },
                {
                    "code": 655,
                    "indent": 0,
                    "parameters": ['const filename = "日本語画像.png";'],
                },
                {"code": 655, "indent": 0, "parameters": ["}"]},
            ]
        }
        captured = []

        def translate(text, history, batch=False):
            captured.append(copy.deepcopy(text))
            if isinstance(text, list):
                return [[translated_message for _ in text], [0, 0]]
            return [translated_message, [0, 0]]

        original_translate = mvmz.translateAI
        original_code355655 = mvmz.CODE355655
        original_enabled = mvmz.ENABLED_PATTERNS_355655
        mvmz.translateAI = translate
        mvmz.CODE355655 = True
        mvmz.ENABLED_PATTERNS_355655 = {"if (BattleManager.canEscape())"}
        try:
            translated_page = copy.deepcopy(page)
            mvmz.searchCodes(translated_page, None, [], "TestMap.json")
        finally:
            mvmz.translateAI = original_translate
            mvmz.CODE355655 = original_code355655
            mvmz.ENABLED_PATTERNS_355655 = original_enabled

        self.assertEqual(captured, [[source_message]])
        self.assertEqual(
            translated_page["list"][2]["parameters"][0],
            f'$gameMessage.add("{translated_message}");',
        )
        self.assertEqual(translated_page["list"][1], page["list"][1])
        self.assertEqual(translated_page["list"][3], page["list"][3])
        self.assertEqual(translated_page["list"][4], page["list"][4])


if __name__ == "__main__":
    unittest.main()
