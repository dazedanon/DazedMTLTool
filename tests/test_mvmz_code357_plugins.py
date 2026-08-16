#!/usr/bin/env python3
"""Regression tests for RPG Maker MZ code-357 plugin commands."""

from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

import modules.rpgmakermvmz as mvmz


class TestMVMZCode357Plugins(unittest.TestCase):
    def test_log_message_remains_in_enabled_plugin_filter(self):
        self.assertIn("LogMessage", mvmz.ENABLED_PLUGINS_357)

    def test_log_message_text_is_collected_and_written_back(self):
        source = "ドキドキしちゃう♡"
        translation = "My heart is pounding♡"
        page = {
            "list": [
                {
                    "code": 357,
                    "indent": 0,
                    "parameters": [
                        "LogMessage",
                        "add",
                        "メッセージ追加",
                        {"text": source},
                    ],
                }
            ]
        }
        captured = []

        def translate(text, history, batch=False):
            captured.append(copy.deepcopy(text))
            return [[translation], [0, 0]]

        with (
            patch.object(mvmz, "CODE357", True),
            patch.object(mvmz, "ENABLED_PLUGINS_357", {"LogMessage"}),
            patch.object(mvmz, "PRESERVEORIGINAL", True),
            patch.object(mvmz, "translateAI", side_effect=translate),
        ):
            translated_page = copy.deepcopy(page)
            mvmz.searchCodes(translated_page, None, [], "TestMap.json")

        self.assertEqual(captured, [[source]])
        self.assertEqual(
            translated_page["list"][0]["parameters"][3]["text"],
            translation,
        )
        self.assertEqual(
            translated_page["list"][0]["parameters"][:3],
            page["list"][0]["parameters"][:3],
        )
        self.assertEqual(
            translated_page["list"][0]["_original"],
            {"parameters": {"3": {"text": source}}},
        )

        # The metadata is inert on a normal rerun: current English controls the
        # skip decision, while the Japanese source remains unchanged for QA.
        captured.clear()
        with (
            patch.object(mvmz, "CODE357", True),
            patch.object(mvmz, "ENABLED_PLUGINS_357", {"LogMessage"}),
            patch.object(mvmz, "PRESERVEORIGINAL", True),
            patch.object(mvmz, "IGNORETLTEXT", True),
            patch.object(mvmz, "translateAI", side_effect=translate),
        ):
            rerun_page = copy.deepcopy(translated_page)
            mvmz.searchCodes(rerun_page, None, [], "TestMap.json")

        self.assertEqual(captured, [])
        self.assertEqual(rerun_page, translated_page)

        with (
            patch.object(mvmz, "CODE357", True),
            patch.object(mvmz, "ENABLED_PLUGINS_357", {"LogMessage"}),
            patch.object(mvmz, "PRESERVEORIGINAL", False),
            patch.object(mvmz, "translateAI", side_effect=translate),
        ):
            preservation_disabled_page = copy.deepcopy(page)
            mvmz.searchCodes(
                preservation_disabled_page,
                None,
                [],
                "TestMap.json",
            )

        self.assertNotIn("_original", preservation_disabled_page["list"][0])

    def test_ultimate_text_animation_translates_only_display_text(self):
        source = "「あの胸で勇者なのか」"
        translation = '"Is she really the hero with breasts like those?"'
        page = {
            "list": [
                {
                    "code": 357,
                    "indent": 0,
                    "parameters": [
                        "MM_UltimateTextAnimation",
                        "ShowPresetText",
                        "プリセットテキスト表示",
                        {
                            "id": "",
                            "presetId": "ええ",
                            "text": source,
                            "x": r"\ev[7]",
                            "y": r"\ev[7]",
                            "styleParams": "",
                            "autoRemove": '{"removeDelay":"70","exitPresetId":""}',
                        },
                    ],
                }
            ]
        }

        def translate(text, history, batch=False):
            return [[translation], [0, 0]]

        with (
            patch.object(mvmz, "CODE357", True),
            patch.object(
                mvmz,
                "ENABLED_PLUGINS_357",
                {"MM_UltimateTextAnimation"},
            ),
            patch.object(mvmz, "PRESERVEORIGINAL", True),
            patch.object(mvmz, "translateAI", side_effect=translate),
        ):
            translated_page = copy.deepcopy(page)
            mvmz.searchCodes(translated_page, None, [], "TestMap.json")

        command = translated_page["list"][0]
        arguments = command["parameters"][3]
        self.assertEqual(arguments["text"], translation.replace('"', ""))
        self.assertEqual(arguments["presetId"], "ええ")
        self.assertEqual(arguments["x"], r"\ev[7]")
        self.assertEqual(arguments["y"], r"\ev[7]")
        self.assertEqual(
            arguments["autoRemove"],
            '{"removeDelay":"70","exitPresetId":""}',
        )
        self.assertEqual(
            command["_original"],
            {"parameters": {"3": {"text": source}}},
        )


if __name__ == "__main__":
    unittest.main()
