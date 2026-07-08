#!/usr/bin/env python3
"""Unit tests for search-first wrap workflow (util/wolfdawn/wrap_search.py)."""

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

import util.dazedwrap as dazedwrap  # noqa: E402
from util.wolfdawn import wrap_search as ws  # noqa: E402

RUMOR_SHEET = "├■街の噂（MOB）"
GATEKEEPER_TEXT = (
    "That gatekeeper just randomly hits on any pretty woman he sees. "
    "They say he once tried to pick up a horned rabbit."
)
GATEKEEPER_ROW = 26
GATEKEEPER_FIELD = "ロ：町のウワサ0"

RUMOR_FIXTURE = {
    "file": "DataBase.project",
    "kind": "db",
    "groups": [
        {
            "type": 29,
            "typeName": RUMOR_SHEET,
            "lines": [
                {
                    "row": 25,
                    "field": 1,
                    "fieldName": "ロ：町のウワサ0",
                    "source": "別の噂",
                    "text": "Short rumor that fits fine.",
                },
                {
                    "row": GATEKEEPER_ROW,
                    "field": 1,
                    "fieldName": GATEKEEPER_FIELD,
                    "source": "門番",
                    "text": GATEKEEPER_TEXT,
                },
            ],
        }
    ],
}


class TestWolfVisibleLength(unittest.TestCase):
    def test_font_codes_do_not_count_toward_width(self):
        plain = "Hello world"
        coded = r"Hello \f[2]world"
        self.assertEqual(
            dazedwrap.max_line_visible_length(plain),
            dazedwrap.max_line_visible_length(coded),
        )

    def test_gatekeeper_line_is_overflow_at_bulletin_width(self):
        length = dazedwrap.max_line_visible_length(GATEKEEPER_TEXT)
        self.assertGreater(length, 40)
        self.assertGreater(length, 34)


class TestWrapSearch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.translated = Path(self.tmp.name) / "translated"
        self.translated.mkdir()
        self.work = Path(self.tmp.name) / "wolf_json"
        self.work.mkdir()
        path = self.translated / "DataBase.project.json"
        path.write_text(json.dumps(RUMOR_FIXTURE, ensure_ascii=False, indent=4), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_search_finds_gatekeeper_in_rumor_sheet(self):
        hits = ws.search_translated_text("gatekeeper just randomly", self.translated)
        self.assertEqual(len(hits), 1)
        hit = hits[0]
        self.assertEqual(hit.kind, "db")
        self.assertEqual(hit.sheet_name, RUMOR_SHEET)
        self.assertEqual(hit.row, GATEKEEPER_ROW)
        self.assertEqual(hit.field_name, GATEKEEPER_FIELD)
        self.assertEqual(hit.json_file, "DataBase.project.json")
        self.assertIn("gatekeeper", hit.text.lower())

    def test_search_finds_horned_rabbits_same_row(self):
        hits = ws.search_translated_text("horned rabbit", self.translated)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].row, GATEKEEPER_ROW)

    def test_wrap_overflow_in_sheet_changes_long_lines(self):
        path = self.translated / "DataBase.project.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        changed = ws.wrap_overflow_in_sheet(path, doc, RUMOR_SHEET, width=34)
        self.assertEqual(changed, 1)
        doc2 = json.loads(path.read_text(encoding="utf-8"))
        line = ws.locate_line(
            doc2,
            {
                "kind": "db",
                "sheet_name": RUMOR_SHEET,
                "row": GATEKEEPER_ROW,
                "field_name": GATEKEEPER_FIELD,
            },
        )
        self.assertIsNotNone(line)
        assert line is not None
        self.assertIn("\n", line["text"])
        self.assertLessEqual(dazedwrap.max_line_visible_length(line["text"]), 34)

    def test_wrap_profile_remembers_sheet_width(self):
        ws.set_sheet_width(self.work, RUMOR_SHEET, 34, json_file="DataBase.project.json")
        profile = ws.load_wrap_profile(self.work)
        self.assertEqual(ws.get_sheet_width(profile, RUMOR_SHEET), 34)
        entry = profile["sheets"][RUMOR_SHEET]
        self.assertEqual(entry["json_file"], "DataBase.project.json")

    def test_sheet_overflow_summary_counts_gatekeeper_row(self):
        summaries = ws.sheet_overflow_summaries(self.translated, width=34)
        rumor = [s for s in summaries if s.sheet_name == RUMOR_SHEET]
        self.assertEqual(len(rumor), 1)
        self.assertEqual(rumor[0].overflow_count, 1)
        self.assertEqual(rumor[0].line_count, 2)


class TestNamesSearch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.translated = Path(self.tmp.name) / "translated"
        self.translated.mkdir()
        fixture = {
            "kind": "names",
            "count": 1,
            "names": [
                {
                    "source": "ブロthel scout line",
                    "text": (
                        "Maybe I'll go scout out some newcomers at the brothel.\n"
                        "\u3000Hope there's a pure-looking girl with big boobs..."
                    ),
                    "note": "Profile · プロフィール",
                    "safety": "safe",
                }
            ],
        }
        (self.translated / "names.json").write_text(
            json.dumps(fixture, ensure_ascii=False, indent=4),
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_search_finds_names_json_profile_text(self):
        hits = ws.search_translated_text("there's a pure", self.translated)
        self.assertEqual(len(hits), 1)
        hit = hits[0]
        self.assertEqual(hit.kind, "names")
        self.assertEqual(hit.json_file, "names.json")
        self.assertIn("pure-looking", hit.text)

    def test_load_hit_from_names_index(self):
        hits = ws.search_translated_text("pure-looking", self.translated)
        self.assertEqual(len(hits), 1)
        path, doc, line = ws.load_hit_from_id(self.translated, hits[0].hit_id)
        self.assertIsNotNone(path)
        assert path is not None and line is not None
        self.assertEqual(path.name, "names.json")
        self.assertIn("pure-looking", line["text"])


class TestWrapPreview(unittest.TestCase):
    SAMPLE = (
        '"Apparently there\'s a super hot female adventurer who just '
        'came to town!? Maybe I can meet her if I head to the '
        r'\c[21]\f[20]tavern\c[19]\f[18]!"'
    )

    def test_preview_detects_wrap_needed(self):
        info = ws.wrap_preview_info(self.SAMPLE, 40)
        self.assertTrue(info["needs_wrap"])
        self.assertGreater(info["longest"], 40)
        self.assertGreater(info["output_line_count"], 1)

    def test_format_preview_shows_line_counts(self):
        preview = ws.format_wrap_preview(self.SAMPLE, 40)
        self.assertIn("(40)", preview)
        self.assertIn("Apparently", preview)

    def test_split_line_at_visible_width(self):
        line = "Apparently there's a super hot female adventurer who just"
        fit_end, line_len = ws.split_line_at_visible_width(line, 40)
        self.assertEqual(line_len, len(line))
        self.assertGreater(fit_end, 0)
        self.assertLess(fit_end, line_len)
        self.assertLessEqual(
            dazedwrap.max_line_visible_length(line[:fit_end]),
            40,
        )

    def test_codes_do_not_inflate_visible_counts(self):
        text = r'See the \c[21]\f[20]tavern\c[19]\f[18] on Main Street'
        info = ws.wrap_preview_info(text, 30)
        self.assertLess(info["longest"], len(text))
        self.assertLessEqual(info["longest"], 30 + 10)


class TestNamesCategoryWrap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.translated = Path(self.tmp.name) / "translated"
        self.translated.mkdir()
        self.category = "├■街の噂（MOB）"
        fixture = {
            "kind": "names",
            "count": 2,
            "names": [
                {
                    "source": "短い",
                    "text": "Short line.",
                    "note": self.category,
                },
                {
                    "source": "長い",
                    "text": (
                        "This is a very long English rumor that should definitely "
                        "wrap when the width is set to thirty-four characters."
                    ),
                    "note": self.category,
                },
            ],
        }
        self.path = self.translated / "names.json"
        self.path.write_text(json.dumps(fixture, ensure_ascii=False, indent=4), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_names_categories_in_sheet_summaries(self):
        summaries = ws.sheet_overflow_summaries(self.translated, width=34)
        names_rows = [s for s in summaries if s.kind == "names" and s.sheet_name == self.category]
        self.assertEqual(len(names_rows), 1)
        self.assertEqual(names_rows[0].line_count, 2)
        self.assertEqual(names_rows[0].overflow_count, 1)

    def test_wrap_all_in_names_category(self):
        doc = json.loads(self.path.read_text(encoding="utf-8"))
        changed = ws.wrap_overflow_in_sheet(
            self.path, doc, self.category, 34, kind="names",
        )
        self.assertEqual(changed, 1)
        doc2 = json.loads(self.path.read_text(encoding="utf-8"))
        long_entry = doc2["names"][1]["text"]
        self.assertIn("\n", long_entry)


class TestEventScopeWrap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.translated = Path(self.tmp.name) / "translated"
        self.translated.mkdir()
        self.path = self.translated / "Map001.mps.json"
        self.path.write_text(
            json.dumps(
                {
                    "kind": "map",
                    "file": "Map001.mps",
                    "scenes": [
                        {
                            "event": 1,
                            "lines": [
                                {
                                    "text": (
                                        "This is a very long line of dialogue that "
                                        "should wrap at thirty four visible chars."
                                    ),
                                },
                                {"text": "Short line."},
                            ],
                        }
                    ],
                },
                ensure_ascii=False,
                indent=4,
            ),
            encoding="utf-8",
        )
        self.hit = ws.WrapHit(
            json_file="Map001.mps.json",
            kind="map",
            sheet_name="Map001.mps",
            row=1,
            field_name="scene 0 line 0",
            text="very long line",
            max_line_len=80,
            scene_index=0,
            line_index=0,
            map_file="Map001.mps",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_scope_stats_for_map_file(self):
        doc = json.loads(self.path.read_text(encoding="utf-8"))
        stats = ws.scope_stats(doc, self.hit, 34)
        self.assertEqual(stats.total, 2)
        self.assertEqual(stats.overflow, 1)

    def test_wrap_all_in_map_file(self):
        doc = json.loads(self.path.read_text(encoding="utf-8"))
        changed = ws.wrap_overflow_in_scope(self.path, doc, self.hit, 34)
        self.assertEqual(changed, 1)


if __name__ == "__main__":
    unittest.main()
