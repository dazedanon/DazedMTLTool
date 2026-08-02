#!/usr/bin/env python3
"""Unit tests for WolfDawn database classification in util/wolfdawn/db_classify.py."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from util.wolfdawn import db_classify as wdb  # noqa: E402


STANDARD_DB = {
    "file": "DataBase.project",
    "kind": "db",
    "groups": [
        {
            "type": 0,
            "typeName": "Skill · 技能",
            "lines": [
                {
                    "row": 2,
                    "field": 1,
                    "fieldName": "Description · 説明",
                    "source": "味方一人のHPを回復",
                    "text": "味方一人のHPを回復",
                },
            ],
        },
        {
            "type": 1,
            "typeName": "Item · アイテム",
            "lines": [
                {
                    "row": 0,
                    "field": 1,
                    "fieldName": "Description · 説明",
                    "source": "HPを回復",
                    "text": "HPを回復",
                },
            ],
        },
    ],
}

NARRATIVE_DB = {
    "file": "DataBase.project",
    "kind": "db",
    "groups": [
        {
            "type": 10,
            "typeName": "■イベント(セルリア)",
            "lines": [
                {
                    "row": 0,
                    "field": 3,
                    "fieldName": "セリフ_メッセージ",
                    "source": "こんにちは",
                    "text": "こんにちは",
                },
                {
                    "row": 0,
                    "field": 4,
                    "fieldName": "直前の相手_コメント",
                    "source": "誰か",
                    "text": "誰か",
                },
            ],
        },
        {
            "type": 11,
            "typeName": "├■プロフィール（元数値）",
            "lines": [
                {
                    "row": 1,
                    "field": 2,
                    "fieldName": "好きなもの_コメント",
                    "source": "甘いもの",
                    "text": "甘いもの",
                },
            ],
        },
    ],
}


class TestClassifyGroupTier(unittest.TestCase):
    def test_classify_group_tier_cases(self):
        cases = (
            (
                "standard skill",
                "Skill · 技能",
                STANDARD_DB["groups"][0]["lines"],
                wdb.TIER_FOUNDATION,
            ),
            (
                "custom event",
                "■イベント(セルリア)",
                NARRATIVE_DB["groups"][0]["lines"],
                wdb.TIER_NARRATIVE,
            ),
            (
                "profile",
                "├■プロフィール（元数値）",
                NARRATIVE_DB["groups"][1]["lines"],
                wdb.TIER_NARRATIVE,
            ),
        )
        for label, name, lines, expected in cases:
            with self.subTest(label):
                self.assertEqual(wdb.classify_group_tier(name, lines), expected)


class TestClassifyDbDocument(unittest.TestCase):
    def test_classify_db_document_cases(self):
        cases = (
            ("standard", STANDARD_DB, wdb.TIER_FOUNDATION, True),
            ("narrative", NARRATIVE_DB, wdb.TIER_NARRATIVE, False),
        )
        for label, document, expected_tier, expected_checked in cases:
            with self.subTest(label):
                groups = wdb.classify_db_document(document)
                self.assertEqual(len(groups), 2)
                self.assertTrue(all(group.tier == expected_tier for group in groups))
                self.assertTrue(
                    all(group.default_checked == expected_checked for group in groups)
                )


class TestContentDistribution(unittest.TestCase):
    def test_analyze_mixed_files_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "DataBase.project.json").write_text(
                json.dumps({**STANDARD_DB, **NARRATIVE_DB, "groups": (
                    STANDARD_DB["groups"] + NARRATIVE_DB["groups"]
                )}, ensure_ascii=False),
                encoding="utf-8",
            )
            (base / "OP.mps.json").write_text(
                json.dumps({
                    "file": "OP.mps",
                    "kind": "map",
                    "scenes": [{"lines": [{"source": "a", "text": "a"}]}],
                }),
                encoding="utf-8",
            )
            dist = wdb.analyze_content_distribution(base)
            self.assertGreater(dist.db_lines, 0)
            self.assertGreater(dist.db_foundation_lines, 0)
            self.assertGreater(dist.db_narrative_lines, 0)
            self.assertEqual(dist.map_files, 1)
            self.assertEqual(dist.map_lines, 1)

    def test_skips_rpgmaker_array_json(self):
        """files/ may hold RPGMaker list JSON; must not crash Wolf discovery."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "Actors.json").write_text(
                json.dumps([{"id": 1, "name": "Hero"}]),
                encoding="utf-8",
            )
            (base / "DataBase.project.json").write_text(
                json.dumps(NARRATIVE_DB, ensure_ascii=False),
                encoding="utf-8",
            )
            dist = wdb.analyze_content_distribution(base)
            self.assertGreater(dist.db_lines, 0)

    def test_discovery_summary_mentions_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "DataBase.project.json").write_text(
                json.dumps(NARRATIVE_DB, ensure_ascii=False),
                encoding="utf-8",
            )
            dist = wdb.analyze_content_distribution(base)
            summary = wdb.format_discovery_summary(dist)
            self.assertIn("Database:", summary)
            self.assertIn("Recommended order:", summary)


class TestGroupFilter(unittest.TestCase):
    def test_group_key_format(self):
        key = wdb.group_key("DataBase.project.json", "Skill · 技能")
        self.assertEqual(key, "DataBase.project.json|Skill · 技能")

    def test_filter_by_groups(self):
        groups = frozenset({"DataBase.project.json|Skill · 技能"})
        self.assertTrue(
            wdb.group_matches_filter(
                "DataBase.project.json", "Skill · 技能", frozenset(), groups
            )
        )
        self.assertFalse(
            wdb.group_matches_filter(
                "DataBase.project.json", "■イベント(セルリア)", frozenset(), groups
            )
        )

    def test_empty_filter_matches_all(self):
        self.assertTrue(
            wdb.group_matches_filter(
                "DataBase.project.json", "■イベント(セルリア)", frozenset(), frozenset()
            )
        )


class TestDbProfile(unittest.TestCase):
    def test_save_and_load_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            profile = {
                "archetype": "simulation_db_heavy",
                "foundation_groups": ["DataBase.project.json|Skill · 技能"],
                "narrative_groups": ["DataBase.project.json|■イベント(セルリア)"],
                "defer_groups": [],
                "notes": "Test note",
            }
            wdb.save_db_profile(work, profile)
            loaded = wdb.load_db_profile(work)
            self.assertEqual(loaded["archetype"], "simulation_db_heavy")
            self.assertEqual(len(loaded["foundation_groups"]), 1)

    def test_import_ai_profile_strips_fences(self):
        raw = '```json\n{"archetype": "hybrid", "foundation_groups": []}\n```'
        data = wdb.import_ai_profile(raw)
        self.assertEqual(data["archetype"], "hybrid")

    def test_merge_profile_checks(self):
        groups = wdb.classify_db_document(NARRATIVE_DB)
        checks = wdb.merge_profile_with_groups(
            {"narrative_groups": [groups[0].key]},
            groups,
        )
        self.assertTrue(checks[groups[0].key])
        self.assertFalse(checks[groups[1].key])


class TestDbVocabHarvest(unittest.TestCase):
    def test_map_name_is_candidate(self):
        line = {"fieldName": "マップ名", "source": "礼拝堂", "text": "Chapel"}
        self.assertTrue(
            wdb.is_db_vocab_harvest_candidate(
                line,
                type_name="Map Setting · マップ設定",
                tier=wdb.TIER_UNKNOWN,
            )
        )

    def test_description_is_not_candidate(self):
        line = {
            "fieldName": "Description · 説明",
            "source": "味方一人のHPを回復",
            "text": "Restores one ally's HP",
        }
        self.assertFalse(
            wdb.is_db_vocab_harvest_candidate(
                line,
                type_name="Skill · 技能",
                tier=wdb.TIER_FOUNDATION,
            )
        )

    def test_usage_message_with_name_placeholder_is_not_candidate(self):
        line = {
            "fieldName": "Usage Message [Battle] (Name~ · 使用時文章[戦闘](人名~",
            "source": "の攻撃！",
            "text": "'s attack!",
        }
        self.assertFalse(
            wdb.is_db_vocab_harvest_candidate(
                line,
                type_name="Skill · 技能",
                tier=wdb.TIER_FOUNDATION,
            )
        )

    def test_narrative_sheet_is_not_candidate(self):
        line = {"fieldName": "マップ名", "source": "礼拝堂", "text": "Chapel"}
        self.assertFalse(
            wdb.is_db_vocab_harvest_candidate(
                line,
                type_name="■イベント(セルリア)",
                tier=wdb.TIER_NARRATIVE,
            )
        )

    def test_collect_pairs_groups_by_sheet(self):
        doc = {
            "file": "SysDatabase.project",
            "kind": "db",
            "groups": [
                {
                    "typeName": "Map Setting · マップ設定",
                    "lines": [
                        {
                            "fieldName": "マップ名",
                            "source": "礼拝堂",
                            "text": "Chapel",
                        },
                        {
                            "fieldName": "Description · 説明",
                            "source": "静かな礼拝堂",
                            "text": "A quiet chapel",
                        },
                    ],
                },
                {
                    "typeName": "■イベント(セルリア)",
                    "lines": [
                        {
                            "fieldName": "現在の行動",
                            "source": "礼拝堂で黙とう中",
                            "text": "Praying in the chapel",
                        },
                    ],
                },
            ],
        }
        pairs = wdb.collect_db_vocab_pairs(doc)
        self.assertEqual(
            pairs,
            {"Map Setting · マップ設定": [("礼拝堂", "Chapel")]},
        )


if __name__ == "__main__":
    unittest.main()
