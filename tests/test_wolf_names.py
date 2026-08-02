#!/usr/bin/env python3
"""Unit tests for WolfDawn names.json helpers in util/wolfdawn/names.py."""

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

from util.wolfdawn import names as wn  # noqa: E402


class TestNameTranslatable(unittest.TestCase):
    def test_name_translatable_cases(self):
        cases = (
            ("safe", {"safety": "safe"}, True),
            ("references", {"safety": "refs"}, False),
            ("verify", {"safety": "verify"}, False),
            ("missing", {}, False),
            ("blank", {"safety": ""}, False),
        )
        for label, entry, expected in cases:
            with self.subTest(label):
                self.assertEqual(wn.is_name_translatable(entry), expected)


class TestVocabHarvestCandidate(unittest.TestCase):
    def test_vocab_harvest_candidate_cases(self):
        cases = (
            (
                "short weapon name",
                {"source": "ダガー", "note": "武器", "safety": "safe"},
                True,
            ),
            (
                "multiline profile",
                {
                    "source": "セルリアと申します。\nよろしくお願いいたします。",
                    "note": "├■プロフィール",
                    "safety": "safe",
                },
                False,
            ),
            (
                "single-line profile",
                {"source": "ローザだ。", "note": "├■プロフィール", "safety": "safe"},
                False,
            ),
            (
                "resistance label",
                {"source": "物理50％軽減", "note": "┣ 属性耐性", "safety": "safe"},
                True,
            ),
        )
        for label, entry, expected in cases:
            with self.subTest(label):
                self.assertEqual(wn.is_vocab_harvest_candidate(entry), expected)


class TestCountNameSafety(unittest.TestCase):
    DOC = {
        "kind": "names",
        "names": [
            {"source": "a", "safety": "safe"},
            {"source": "b", "safety": "refs"},
            {"source": "c", "safety": "verify"},
            {"source": "d"},
        ],
    }

    def test_counts_badges(self):
        counts = wn.count_name_safety(self.DOC)
        self.assertEqual(counts["safe"], 1)
        self.assertEqual(counts["refs"], 1)
        self.assertEqual(counts["verify"], 1)
        self.assertEqual(counts["unknown"], 1)
        self.assertEqual(counts["translatable"], 1)

    def test_summary_mentions_translatable_count(self):
        summary = wn.format_name_safety_summary(self.DOC)
        self.assertIn("1 of 4", summary)
        self.assertIn("verify", summary)


class TestNoteHeader(unittest.TestCase):
    def test_note_header_cases(self):
        cases = (
            ("static fallback", "武器", None, "Weapon · 武器"),
            ("live label", "武器", {"武器": "Blade"}, "Blade · 武器"),
            ("unknown note", "■MOBセリフ", None, "■MOBセリフ"),
        )
        for label, note, labels, expected in cases:
            with self.subTest(label):
                self.assertEqual(wn.note_header(note, labels), expected)


class TestCollectNameNotes(unittest.TestCase):
    DOC = {
        "kind": "names",
        "names": [
            {"source": "a", "note": "武器"},
            {"source": "b", "note": "技能"},
            {"source": "c", "note": "武器"},
            {"source": "d"},
        ],
    }

    def test_collects_unique_sorted_notes(self):
        self.assertEqual(wn.collect_name_notes(self.DOC), ["技能", "武器"])

class TestDeriveDbLabels(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_parses_bilingual_typenames_from_db_files(self):
        (self.dir / "DataBase.project.json").write_text(
            json.dumps({
                "kind": "db",
                "groups": [
                    {"typeName": "Weapon · 武器", "lines": []},
                    {"typeName": "Skill · 技能", "lines": []},
                ],
            }),
            encoding="utf-8",
        )
        labels = wn.derive_db_labels(self.dir)
        self.assertEqual(labels, {"武器": "Weapon", "技能": "Skill"})

    def test_missing_dir_returns_empty(self):
        self.assertEqual(wn.derive_db_labels(self.dir / "nope"), {})


class TestNameWrapRoles(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.names = self.dir / "names.json"
        self.names.write_text("{}", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_upsert_load_and_update_name_wrap_role(self):
        roles_path = wn.roles_json_path_for_names(self.names)
        self.assertEqual(roles_path, self.dir / "wolfdawn-roles.json")
        wn.upsert_name_wrap_role(roles_path, "説明", width=40, font=14)
        wn.upsert_name_wrap_role(roles_path, "説明", width=52, max_lines=4)
        role = wn.get_name_wrap_role(wn.load_name_wrap_roles(roles_path), "説明")
        self.assertEqual(role["width"], 52)
        self.assertEqual(role["maxLines"], 4)
        self.assertEqual(role["font"], 14)


class TestNameReconcile(unittest.TestCase):
    def test_glossary_wins_over_divergent_extracts(self):
        names = {
            "kind": "names",
            "names": [{"source": "牧場主", "text": "Rancher", "safety": "safe"}],
        }
        db = {
            "kind": "db",
            "groups": [
                {
                    "type": 1,
                    "lines": [
                        {"source": "牧場主", "text": "Ranch Owner"},
                        {"source": "牧場主", "text": "Rancher"},
                        {"source": "牧場主", "text": "牧場主"},
                    ],
                }
            ],
        }
        report = wn.reconcile_names_to_glossary(names, {"DataBase.project.json": db})
        self.assertEqual(report.changed, 2)  # Owner + identity → Rancher
        texts = [ln["text"] for ln in db["groups"][0]["lines"]]
        self.assertEqual(texts, ["Rancher", "Rancher", "Rancher"])
        self.assertTrue(all(c.reason == "glossary" for c in report.changes))

    def test_majority_when_glossary_still_japanese(self):
        names = {
            "kind": "names",
            "names": [{"source": "魔獣マニア", "text": "魔獣マニア", "safety": "refs"}],
        }
        db = {
            "kind": "db",
            "groups": [
                {
                    "type": 1,
                    "lines": [
                        {"source": "魔獣マニア", "text": "Beast Maniac"},
                        {"source": "魔獣マニア", "text": "Monster Beast Maniac"},
                        {"source": "魔獣マニア", "text": "Monster Beast Maniac"},
                    ],
                }
            ],
        }
        report = wn.reconcile_names_to_glossary(names, {"DataBase.project.json": db})
        self.assertEqual(report.changed, 1)
        self.assertEqual(report.changes[0].new_text, "Monster Beast Maniac")
        self.assertEqual(report.changes[0].reason, "majority")
        texts = [ln["text"] for ln in db["groups"][0]["lines"]]
        self.assertEqual(
            texts,
            ["Monster Beast Maniac", "Monster Beast Maniac", "Monster Beast Maniac"],
        )

    def test_tie_breaks_lexicographically(self):
        chosen, reason = wn.choose_canonical(
            "牧場主",
            "牧場主",
            {"Ranch Owner": 4, "Rancher": 4},
        )
        self.assertEqual(reason, "majority")
        self.assertEqual(chosen, "Ranch Owner")


if __name__ == "__main__":
    unittest.main()
