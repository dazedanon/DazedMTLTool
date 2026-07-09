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
    def test_safe_is_translatable(self):
        self.assertTrue(wn.is_name_translatable({"safety": "safe"}))

    def test_refs_verify_and_missing_are_not_translatable(self):
        self.assertFalse(wn.is_name_translatable({"safety": "refs"}))
        self.assertFalse(wn.is_name_translatable({"safety": "verify"}))
        self.assertFalse(wn.is_name_translatable({}))
        self.assertFalse(wn.is_name_translatable({"safety": ""}))


class TestVocabHarvestCandidate(unittest.TestCase):
    def test_short_weapon_name_harvests(self):
        entry = {"source": "ダガー", "note": "武器", "safety": "safe"}
        self.assertTrue(wn.is_vocab_harvest_candidate(entry))

    def test_multiline_profile_skipped(self):
        entry = {
            "source": "セルリアと申します。\nよろしくお願いいたします。",
            "note": "├■プロフィール",
            "safety": "safe",
        }
        self.assertFalse(wn.is_vocab_harvest_candidate(entry))

    def test_profile_note_skipped_even_when_single_line(self):
        entry = {"source": "ローザだ。", "note": "├■プロフィール", "safety": "safe"}
        self.assertFalse(wn.is_vocab_harvest_candidate(entry))

    def test_resistance_label_still_harvests(self):
        entry = {"source": "物理50％軽減", "note": "┣ 属性耐性", "safety": "safe"}
        self.assertTrue(wn.is_vocab_harvest_candidate(entry))


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
    def test_static_fallback_is_bilingual(self):
        self.assertEqual(wn.note_header("武器"), "Weapon · 武器")

    def test_live_db_label_wins_over_static(self):
        labels = {"武器": "Blade"}
        self.assertEqual(wn.note_header("武器", labels), "Blade · 武器")

    def test_unknown_note_stays_japanese_only(self):
        self.assertEqual(wn.note_header("■MOBセリフ"), "■MOBセリフ")


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


if __name__ == "__main__":
    unittest.main()
