#!/usr/bin/env python3
"""Structural regression tests for deterministic RPG Maker QA inventory."""

from __future__ import annotations

import copy
from contextlib import redirect_stderr, redirect_stdout
import hashlib
from io import StringIO
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
                                "parameters": ["\n\\acWhat your partner wants to do is..."],
                                "_original": "\n\\ac相手がしたがっていることは……",
                            },
                            {
                                "code": 401,
                                "parameters": [
                                    "\\ac First centered line.\nSecond line lost centering."
                                ],
                                "_original": "\\ac中央揃え。",
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
        unsafe_center = next(
            record for record in records if "したがっている" in record["source"]
        )
        missing_center = next(
            record for record in records if "中央揃え" in record["source"]
        )

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
        self.assertIn(
            "unsafe-bare-center-code", unsafe_center["mechanical"]["flags"]
        )
        self.assertIn(
            "missing-center-alignment", missing_center["mechanical"]["flags"]
        )
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

    def test_tool_managed_game_title_is_excluded_without_hiding_system_text(self):
        _write_json(
            self.data / "System.json",
            {
                "gameTitle": "Localized Game | TL: Translator | Cheats: F8",
                "currencyUnit": "Gold",
                "_original": {
                    "gameTitle": "原題",
                    "currencyUnit": "金貨",
                },
            },
        )

        manifest = build_manifest(self.data, "database")
        system_records = [
            item for item in manifest["records"] if item["file"] == "System.json"
        ]

        self.assertEqual(
            [item["source_pointer"] for item in system_records],
            ["/_original/currencyUnit"],
        )
        self.assertEqual(system_records[0]["live"], "Gold")
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
        self.assertEqual(release["counts"]["records"], 19)
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

        # Len's staged writer must produce the same source/live contract that
        # Workflow QA reads, including reflowed runs and immutable rerun sources.
        from scripts.len_translation import main
        from util.len_originals import preserve_originals

        def command(code, parameters, **extra):
            return {"code": code, "indent": 0, "parameters": parameters, **extra}

        source = {"events": [None, {"id": 1, "pages": [{"list": [
            command(101, ["FaceJP", 0, 0, 2, "レオン"]),
            command(401, ["一行目。"]), command(401, ["二行目。"]),
            command(102, [["残る", "去る", "Cancel"], 0, 0, 2, 0]),
            command(402, [0, "残る"]),
            command(405, ["長い文。"]), command(405, ["次の文。"]),
            command(108, ["表示開始"]), command(408, ["表示終了"]),
            command(355, ['show("開始");']), command(655, ['show("終了");']),
            command(357, ["QuestSystem", "show", "表示", {"DetailNote": "鍵を探す", "id": "quest_a"}]),
            command(122, [1, 1, 0, 4, "'元の値'"]),
            command(111, [12, '$gameVariables.value(1) === "合言葉"']),
            command(320, [1, "新しい名前"]),
            command(0, []),
        ]}]}]}
        staged = copy.deepcopy(source)
        commands = staged["events"][1]["pages"][0]["list"]
        commands[0]["parameters"][0] = "FaceEN"  # Asset IDs are not nameplates.
        commands[0]["parameters"][4] = "Leon"
        translations = {1: "Both lines translated together.", 2: "", 5: "Long text.",
                        6: "Next text.", 7: "Start display", 8: "End display",
                        9: 'show("Start");', 10: 'show("End");'}
        for index, value in translations.items():
            commands[index]["parameters"][0] = value
        commands[3]["parameters"][0][:2] = ["Stay", "Leave"]
        commands[4]["parameters"][1] = "Stay"
        commands[11]["parameters"][3]["DetailNote"] = "Find the key"
        commands[12]["parameters"][4] = "'Original value'"
        commands[13]["parameters"][1] = '$gameVariables.value(1) === "Password"'
        commands[14]["parameters"][1] = "New name"
        untouched = copy.deepcopy(source)
        annotated = preserve_originals(source, staged, filename="Map001.json")
        self.assertEqual(source, untouched)
        self.assertNotIn("_original", commands[1])
        rows = annotated["events"][1]["pages"][0]["list"]
        self.assertEqual(rows[0]["_original"], "レオン")
        self.assertEqual(rows[1]["_original"], "一行目。\n二行目。")
        self.assertNotIn("_original", rows[2])
        self.assertEqual(rows[3]["_original"], ["残る", "去る", None])
        self.assertNotIn("_original", rows[4])
        self.assertEqual(rows[11]["_original"], {"parameters": {"3": {"DetailNote": "鍵を探す"}}})
        self.assertEqual(rows[12]["_original"], "元の値")

        data = Path(self.temporary.name) / "len-data"
        data.mkdir()
        source_file, staged_file = data.parent / "source.json", data.parent / "staged.json"
        output = data / "Map001.json"
        _write_json(source_file, source)
        staged_file.write_bytes(b"\xef\xbb\xbf" + json.dumps(staged, ensure_ascii=False).encode() + b"\r\n")
        arguments = ["write-rpgmaker-json", "--source", str(source_file),
                     "--translated", str(staged_file), "--output", str(output)]
        with redirect_stdout(StringIO()):
            self.assertEqual(main(arguments), 0)
        self.assertEqual(json.loads(output.read_bytes().decode("utf-8-sig")), annotated)
        self.assertTrue(output.read_bytes().startswith(b"\xef\xbb\xbf"))
        self.assertTrue(output.read_bytes().endswith(b"\r\n"))

        # Database/System shapes must match the reader, too (including a sparse
        # list and nested terms anchored on System's root rather than on terms).
        for filename, old, new in (
            ("Items.json", [None, {"id": 1, "name": "薬", "description": "回復する"}],
             [None, {"id": 1, "name": "Potion", "description": "Restores health"}]),
            ("System.json", {"locale": "ja_JP", "currencyUnit": "円", "armorTypes": ["", "服"], "terms": {"messages": {"win": "勝利"}}},
             {"locale": "ja_JP", "currencyUnit": "G", "armorTypes": ["", "Clothes"], "terms": {"messages": {"win": "Victory"}}}),
        ):
            preserved = preserve_originals(old, new, filename=filename)
            _write_json(data / filename, preserved)
            if filename == "System.json":
                self.assertEqual(preserved["locale"], "en_US")
                self.assertEqual(preserved["_original"]["locale"], "ja_JP")
                self.assertEqual(preserve_originals(preserved, preserved, filename=filename), preserved)
                self.assertEqual(preserved["_original"]["terms"], {"messages": {"win": "勝利"}})
                self.assertEqual(preserved["_original"]["armorTypes"], {"1": "服"})
                self.assertNotIn("_original", preserved["terms"])
        manifest = build_manifest(data, "release")
        report = verify_manifest(data, manifest)
        self.assertTrue(report["valid"], report["errors"])
        pairs = {row["source"]: row["live"] for row in manifest["records"]}
        self.assertEqual(pairs["一行目。\n二行目。"], "Both lines translated together.\n")
        self.assertEqual(pairs["表示開始\n表示終了"], "Start display\nEnd display")
        self.assertEqual(pairs['show("開始");\nshow("終了");'], 'show("Start");\nshow("End");')
        self.assertEqual(pairs["元の値"], "Original value")
        self.assertEqual(pairs["鍵を探す"], "Find the key")
        self.assertNotIn("FaceJP", pairs)
        self.assertEqual(set(pairs), {
            "レオン", "一行目。\n二行目。", "残る", "去る", "長い文。\n次の文。",
            "表示開始\n表示終了", 'show("開始");\nshow("終了");', "鍵を探す", "元の値",
            '$gameVariables.value(1) === "合言葉"', "新しい名前", "薬", "回復する", "円", "服", "勝利", "ja_JP",
        })

        # A clean-baseline reinjection must also keep metadata already in the game.
        saved = output.read_bytes()
        with redirect_stdout(StringIO()):
            self.assertEqual(main(arguments), 0)
        self.assertEqual(output.read_bytes(), saved)
        correction = copy.deepcopy(annotated)
        corrected_rows = correction["events"][1]["pages"][0]["list"]
        corrected_rows[1]["parameters"][0] = "A better translation."
        corrected_rows[3]["parameters"][0][1] = "Depart"
        corrected = preserve_originals(annotated, correction, filename=output.name)
        self.assertEqual(corrected["events"][1]["pages"][0]["list"][1]["_original"], "一行目。\n二行目。")
        self.assertEqual(corrected["events"][1]["pages"][0]["list"][3]["_original"], ["残る", "去る", None])

        # Existing adjacent source markers partition independently editable runs.
        separate = [command(401, ["First"], _original="最初"), command(401, ["Second"], _original="次")]
        revised = copy.deepcopy(separate)
        revised[0]["parameters"][0] = "Revised first"
        revised[1]["parameters"][0] = "Revised second"
        self.assertEqual([row["_original"] for row in preserve_originals(separate, revised, filename=output.name)], ["最初", "次"])
        legacy = command(357, ["QuestSystem", "show", "表示", {"DetailNote": "Find it"}], _original={"DetailNote": "探す"})
        revised = copy.deepcopy(legacy)
        revised["parameters"][3]["DetailNote"] = "Find the item"
        self.assertEqual(preserve_originals(legacy, revised, filename=output.name)["_original"], {"DetailNote": "探す"})

        # Refusals must leave the destination byte-for-byte intact.
        bad_cases = []
        for mutation in (
            lambda doc: doc["events"].pop(),
            lambda doc: doc["events"][1].update(id=2),
            lambda doc: doc["events"][1]["pages"][0]["list"][1].update(_original="Invented source"),
            lambda doc: doc["events"][1]["pages"][0]["list"][2].update(code=405),
            lambda doc: doc["events"][1]["pages"][0]["list"][12]["parameters"].__setitem__(4, "buildText()"),
            lambda doc: doc["events"][1]["pages"][0]["list"][12]["parameters"].__setitem__(4, "'First' + 'Second'"),
        ):
            bad = copy.deepcopy(staged)
            mutation(bad)
            bad_cases.append(bad)
        for bad in bad_cases:
            _write_json(staged_file, bad)
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(main(arguments), 1)
            self.assertEqual(output.read_bytes(), saved)


if __name__ == "__main__":
    unittest.main()
