#!/usr/bin/env python3
"""Structural regression tests for deterministic RPG Maker QA inventory."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from modules.rpgmakermvmz import HEADER_MAPPINGS_357  # noqa: E402
from util.rpgmaker_qa_manifest import (  # noqa: E402
    CODE357_TEXT_ARGUMENTS,
    build_manifest,
    write_manifest,
)
from util.rpgmaker_qa_verify import (  # noqa: E402
    CODE357_TEXT_ARGUMENTS as VERIFIED_CODE357_TEXT_ARGUMENTS,
    verify_manifest,
)


def _write_json(path: Path, value) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def _rehash(manifest) -> None:
    unhashed = dict(manifest)
    unhashed.pop("content_sha256", None)
    manifest["content_sha256"] = hashlib.sha256(
        json.dumps(
            unhashed,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _map_fixture():
    return {
        "events": [
            None,
            {
                "id": 1,
                "pages": [
                    {
                        "list": [
                            {
                                "code": 101,
                                "parameters": ["SunFace", 0, 0, 2, "【Sun】"],
                            },
                            {
                                "code": 401,
                                "parameters": ["First translated line."],
                                "_original": "一行目。\n二行目。",
                            },
                            {"code": 401, "parameters": ["Second translated line."]},
                            {"code": 0, "parameters": []},
                            {
                                "code": 101,
                                "parameters": ["AnaFace", 0, 0, 2, "【Ana】"],
                            },
                            {"code": 355, "parameters": ["doSomething()"]},
                            None,
                            {
                                "code": 401,
                                "parameters": ["Must have no speaker."],
                                "_original": "話者なし。",
                            },
                            {
                                "code": 401,
                                "parameters": ["\\C[2]Danger"],
                                "_original": "\\C[2]危険\\C[0]",
                            },
                            {
                                "code": 101,
                                "parameters": ["PlotFace", 0, 0, 2, "\\C[2]【Intrigue】"],
                            },
                            {
                                "code": 401,
                                "parameters": ["Choose now."],
                                "_original": "今選べ。",
                            },
                            {
                                "code": 102,
                                "parameters": [["Stay", "Leave"], -1, 0, 2, 0],
                                "_original": ["残る", "去る"],
                            },
                            {"code": 402, "parameters": [0, "Stay"]},
                            {"code": 402, "parameters": [1, "Leave"]},
                            {"code": 404, "parameters": []},
                            {
                                "code": 405,
                                "parameters": ["First scrolling line."],
                                "_original": "スクロール一。\nスクロール二。",
                            },
                            {"code": 405, "parameters": ["Second scrolling line."]},
                            {
                                "code": 122,
                                "parameters": [1, 1, 0, 0, "`Current value`"],
                                "_original": "元の値",
                            },
                            {
                                "code": 357,
                                "parameters": [
                                    "TorigoyaMZ_NotifyMessage",
                                    "notify",
                                    "Show notification",
                                    {"message": "Health restored", "icon": "72"},
                                ],
                                "_original": "体力回復",
                            },
                            {
                                "code": 357,
                                "parameters": [
                                    "QuestSystem",
                                    "show",
                                    "Quest detail",
                                    {"DetailNote": "Find the key", "VariableId": "1"},
                                ],
                                "_original": {"DetailNote": "鍵を探す"},
                            },
                            {
                                "code": 108,
                                "parameters": ["Translated comment header"],
                                "_original": "コメント一。\nコメント二。",
                            },
                            {"code": 408, "parameters": ["Translated continuation"]},
                            {
                                "code": 355,
                                "parameters": ["showText('First')"],
                                "_original": "スクリプト一。\nスクリプト二。",
                            },
                            {"code": 655, "parameters": ["showText('Second')"]},
                            {"code": 0, "parameters": []},
                            {
                                "code": 101,
                                "parameters": ["VariableName"],
                                "_original": "変数名",
                            },
                            {
                                "code": 401,
                                "parameters": ["Variable speaker line."],
                                "_original": "変数話者。",
                            },
                            {
                                "code": 999,
                                "parameters": ["Unknown live"],
                                "_original": "未知形状",
                            },
                            {"code": 0, "parameters": []},
                        ]
                    }
                ],
            },
        ]
    }


class TestRPGMakerQAManifest(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.data = Path(self.temporary.name) / "data"
        self.data.mkdir()
        _write_json(self.data / "Map001.json", _map_fixture())
        _write_json(
            self.data / "Items.json",
            [
                None,
                {
                    "id": 1,
                    "name": "Potion",
                    "description": "Restores health.",
                    "_original": {"name": "薬", "description": "体力を回復する。"},
                },
            ],
        )
        nested = self.data / "nested"
        nested.mkdir()
        _write_json(
            nested / "Other.json",
            {
                "name": "Nested live text",
                "_original": {"name": "入れ子"},
                "unsupported": {"name": "live", "_original": {"name": 123}},
            },
        )

    def test_raw_topology_prevents_speaker_state_leak_and_joins_401(self):
        manifest = build_manifest(self.data, "dialogue")
        records = manifest["records"]
        first = next(record for record in records if record["source"] == "一行目。\n二行目。")
        orphan = next(record for record in records if record["source"] == "話者なし。")
        choices = [record for record in records if record["source"] in {"残る", "去る"}]
        scrolling = next(
            record for record in records if record["source"].startswith("スクロール")
        )
        control = next(record for record in records if "危険" in record["source"])
        variable_name = next(record for record in records if record["source"] == "変数名")
        variable_line = next(record for record in records if record["source"] == "変数話者。")

        self.assertEqual(first["live"], "First translated line.\nSecond translated line.")
        self.assertEqual(len(first["live_pointers"]), 2)
        self.assertEqual(first["speaker"]["display_name"], "Sun")
        self.assertEqual(orphan["speaker"]["provenance"], "none")
        self.assertEqual(orphan["speaker"]["display_name"], "")
        self.assertEqual({item["speaker"]["display_name"] for item in choices}, {"Intrigue"})
        self.assertEqual(
            scrolling["live"], "First scrolling line.\nSecond scrolling line."
        )
        self.assertEqual(scrolling["speaker"]["provenance"], "none")
        self.assertIn("runtime-token-mismatch", control["mechanical"]["flags"])
        self.assertEqual(
            choices[0]["choice_context"]["branches"],
            [{"index": 0, "label": "Stay"}, {"index": 1, "label": "Leave"}],
        )
        self.assertEqual(variable_name["speaker"]["display_name"], "VariableName")
        self.assertEqual(variable_name["speaker"]["face_name"], "")
        self.assertEqual(variable_line["speaker"]["display_name"], "VariableName")
        self.assertTrue(verify_manifest(self.data, manifest)["valid"])

    def test_code357_inventory_schema_tracks_the_translation_schema(self):
        translator_schema = {
            plugin: tuple(arguments)
            for plugin, (arguments, _font) in HEADER_MAPPINGS_357.items()
        }
        self.assertEqual(CODE357_TEXT_ARGUMENTS, translator_schema)
        self.assertEqual(VERIFIED_CODE357_TEXT_ARGUMENTS, translator_schema)

    def test_visible_numbers_ignore_ascii_and_fullwidth_digit_width(self):
        items_path = self.data / "Items.json"
        items = json.loads(items_path.read_text(encoding="utf-8"))
        items.append({
            "id": 2,
            "name": "Pattern 1",
            "_original": {"name": "パターン１"},
        })
        _write_json(items_path, items)

        manifest = build_manifest(self.data, "database")
        record = next(
            item for item in manifest["records"] if item["source"] == "パターン１"
        )

        self.assertEqual(record["mechanical"]["source_visible_numbers"], ["1"])
        self.assertEqual(record["mechanical"]["live_visible_numbers"], ["1"])
        self.assertNotIn("visible-number-mismatch", record["mechanical"]["flags"])
        self.assertTrue(verify_manifest(self.data, manifest)["valid"])

    def test_focus_partition_and_risky_inner_string(self):
        database = build_manifest(self.data, "database")
        risky = build_manifest(self.data, "risky-codes")
        release = build_manifest(self.data, "release")

        self.assertEqual(database["counts"]["records"], 2)
        self.assertEqual({item["classification"] for item in database["records"]}, {"database"})
        self.assertEqual({item["database_entity"]["id"] for item in database["records"]}, {1})
        self.assertEqual(risky["counts"]["records"], 5)
        variable = next(item for item in risky["records"] if item["event_code"] == 122)
        notification = next(item for item in risky["records"] if item["source"] == "体力回復")
        quest = next(item for item in risky["records"] if item["source"] == "鍵を探す")
        comment = next(item for item in risky["records"] if item["event_code"] == 108)
        script = next(item for item in risky["records"] if item["event_code"] == 355)
        self.assertEqual(variable["source"], "元の値")
        self.assertEqual(variable["live"], "Current value")
        self.assertEqual(variable["live_transform"], "quoted-string")
        self.assertEqual(notification["live"], "Health restored")
        self.assertEqual(notification["mapping"], "code-357-argument")
        self.assertEqual(
            notification["risky_context"]["visibility"], "requires-runtime-evidence"
        )
        self.assertEqual(quest["live"], "Find the key")
        self.assertEqual(quest["live_pointers"][0].rsplit("/", 2)[-2:], ["3", "DetailNote"])
        self.assertEqual(comment["live"], "Translated comment header\nTranslated continuation")
        self.assertEqual(script["live"], "showText('First')\nshowText('Second')")
        self.assertEqual(release["counts"]["records"], 17)
        self.assertEqual(release["counts"]["unresolved"], 2)
        nested_record = next(item for item in release["records"] if item["source"] == "入れ子")
        self.assertEqual(nested_record["file"], "nested/Other.json")
        self.assertEqual(nested_record["classification"], "other")
        self.assertEqual(release["normalization"], "exact-utf8-no-normalization-v1")
        self.assertEqual(release["length_thresholds"], {"short_max": 20, "medium_max": 60})
        self.assertTrue(verify_manifest(self.data, database)["valid"])
        self.assertTrue(verify_manifest(self.data, risky)["valid"])
        release_report = verify_manifest(self.data, release)
        self.assertFalse(release_report["valid"])
        self.assertIn("manifest contains unresolved source shapes", release_report["errors"])
        hidden_empty = copy.deepcopy(release)
        hidden_empty["unresolved"] = [
            item
            for item in hidden_empty["unresolved"]
            if item["reason"] != "empty-or-non-string-original"
        ]
        hidden_empty["counts"]["unresolved"] = len(hidden_empty["unresolved"])
        _rehash(hidden_empty)
        hidden_report = verify_manifest(self.data, hidden_empty)
        self.assertFalse(hidden_report["valid"])
        self.assertIn(
            "empty/non-string original inventory mismatch", hidden_report["errors"]
        )

    def test_independent_verifier_rejects_omissions_and_wrong_speaker(self):
        manifest = build_manifest(self.data, "dialogue")
        omitted = copy.deepcopy(manifest)
        omitted["records"].pop()
        omitted["content_sha256"] = manifest["content_sha256"]
        report = verify_manifest(self.data, omitted)
        self.assertFalse(report["valid"])
        self.assertTrue(any("coverage mismatch" in error for error in report["errors"]))

        wrong_speaker = copy.deepcopy(manifest)
        wrong_speaker["records"][0]["speaker"]["display_name"] = "Leaked"
        # Even if a producer recomputed the outer checksum, the raw-topology
        # verifier independently rejects the false facet.
        _rehash(wrong_speaker)
        report = verify_manifest(self.data, wrong_speaker)
        self.assertFalse(report["valid"])
        self.assertTrue(any("speaker facet mismatch" in error for error in report["errors"]))

        all_unresolved = copy.deepcopy(manifest)
        all_unresolved["unresolved"] = [
            {
                "file": item["file"],
                "source_pointer": item["source_pointer"],
                "classification": item["classification"],
                "reason": "forged-unresolved",
            }
            for item in all_unresolved["records"]
        ]
        all_unresolved["records"] = []
        all_unresolved["clusters"] = []
        all_unresolved["review_sequence"] = []
        all_unresolved["counts"].update(
            {"records": 0, "clusters": 0, "unresolved": len(all_unresolved["unresolved"])}
        )
        _rehash(all_unresolved)
        report = verify_manifest(self.data, all_unresolved)
        self.assertFalse(report["valid"])
        self.assertIn("manifest contains unresolved source shapes", report["errors"])

        forged_code = copy.deepcopy(manifest)
        forged_code["records"][0]["event_code"] = 408
        forged_code["records"][0]["mapping"] = "joined-contiguous-408"
        _rehash(forged_code)
        report = verify_manifest(self.data, forged_code)
        self.assertFalse(report["valid"])
        self.assertTrue(any("event code mismatch" in error for error in report["errors"]))

    def test_manifest_round_trip_is_byte_deterministic(self):
        first = build_manifest(self.data, "dialogue")
        second = build_manifest(self.data, "dialogue")
        self.assertEqual(first, second)
        one = Path(self.temporary.name) / "one.json"
        two = Path(self.temporary.name) / "two.json"
        write_manifest(first, one)
        write_manifest(second, two)
        self.assertEqual(one.read_bytes(), two.read_bytes())


if __name__ == "__main__":
    unittest.main()
