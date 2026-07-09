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

    def test_search_and_wrap_db_sheet(self):
        hits = ws.search_translated_text("gatekeeper just randomly", self.translated)
        self.assertEqual(len(hits), 1)
        hit = hits[0]
        self.assertEqual(hit.sheet_name, RUMOR_SHEET)
        self.assertEqual(hit.row, GATEKEEPER_ROW)

        path = self.translated / "DataBase.project.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        changed = ws.wrap_overflow_in_sheet(path, doc, RUMOR_SHEET, width=34)
        self.assertEqual(changed, 1)
        line = ws.locate_line(doc, hit.hit_id)
        assert line is not None
        self.assertIn("\n", line["text"])
        self.assertLessEqual(dazedwrap.max_line_visible_length(line["text"]), 34)

        ws.set_sheet_width(self.work, RUMOR_SHEET, 34, json_file="DataBase.project.json")
        self.assertEqual(
            ws.get_sheet_width(ws.load_wrap_profile(self.work), RUMOR_SHEET), 34
        )


class TestNamesSearchAndWrap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.translated = Path(self.tmp.name) / "translated"
        self.translated.mkdir()
        self.category = "├■街の噂（MOB）"
        fixture = {
            "kind": "names",
            "names": [
                {
                    "source": "「メイドがどんどん辞めていく」",
                    "text": '"Yeah, maids keep quitting one after another."',
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

    def test_search_summary_shows_translated_text(self):
        hits = ws.search_translated_text("maids", self.translated)
        self.assertEqual(len(hits), 1)
        summary = hits[0].summary(40)
        self.assertTrue(summary.split("\n", 1)[0].startswith('"Yeah, maids'))
        self.assertNotIn("メイド", summary)
        path, _doc, line = ws.load_hit_from_id(self.translated, hits[0].hit_id)
        assert path is not None and line is not None
        self.assertEqual(path.name, "names.json")
        self.assertIn("maids", line["text"])

    def test_wrap_overflow_in_names_category(self):
        doc = json.loads(self.path.read_text(encoding="utf-8"))
        changed = ws.wrap_overflow_in_sheet(
            self.path, doc, self.category, 34, kind="names",
        )
        self.assertGreaterEqual(changed, 1)
        long_text = json.loads(self.path.read_text(encoding="utf-8"))["names"][1]["text"]
        self.assertIn("\n", long_text)
        self.assertLessEqual(dazedwrap.max_line_visible_length(long_text), 34)


class TestWrapPreviewHtml(unittest.TestCase):
    def test_html_preview_hides_codes_and_simulates_body_font(self):
        text = r'That \c[21]\f[20]cafe\c[19]\f[18] over there'
        html = ws.format_wrap_preview_html(text, 40, body_font=13)
        self.assertNotIn(r"\c[", html)
        self.assertNotIn(r"\f[", html)
        self.assertIn("cafe", html)
        self.assertIn("font-size:14px", html)  # 20*13/18
        self.assertIn("font-size:13px", html)
        self.assertIn(ws.wolf_preview_color(21), html)
        info = ws.wrap_preview_info(text, 40)
        self.assertLess(info["longest"], len(text))


class TestManualFontAndWrap(unittest.TestCase):
    def test_manual_scales_emphasis_wraps_and_skips_short_plain(self):
        text = (
            r"So they even take worries like this in the "
            r"\c[21]\f[20]confessional\c[19]\f[18] booth every day."
        )
        new_text, changed = ws.apply_manual_font_and_wrap(text, 40, font=14)
        self.assertTrue(changed)
        self.assertIn(r"\f[16]", new_text)
        self.assertIn(r"\f[14]", new_text)
        self.assertLessEqual(dazedwrap.max_line_visible_length(new_text), 40)

        short, skipped = ws.apply_manual_font_and_wrap(
            "Short.", 40, font=14, only_overflow_or_fonts=True
        )
        self.assertFalse(skipped)
        self.assertEqual(short, "Short.")

    def test_manual_font_zero_or_none_does_not_add_font(self):
        text = "A short line that needs wrapping because it is quite long for width thirty."
        for font in (None, 0):
            new_text, changed = ws.apply_manual_font_and_wrap(text, 30, font=font)
            self.assertTrue(changed)
            self.assertNotIn(r"\f[", new_text)
            self.assertLessEqual(dazedwrap.max_line_visible_length(new_text), 30)

        # Existing fonts stay put when font is disabled.
        with_f = r"\f[18]Hello there this is a longer line for wrapping please."
        kept, changed = ws.apply_manual_font_and_wrap(with_f, 20, font=None)
        self.assertTrue(changed)
        self.assertTrue(kept.startswith(r"\f[18]"))
        self.assertNotIn(r"\f[14]", kept)

    def test_manual_reflows_soft_breaks_that_already_fit(self):
        """Hard \\n lines can each fit width while the preview still reflows."""
        text = (
            '\\f[13]"I heard there\'s a super hot female\n'
            "adventurer who came to town recently!?\n"
            "Maybe I'll catch a glimpse of her at the\n"
            r'\c[21]\f[14]tavern\c[19]\f[13]!"'
        )
        # Per-line lengths are under 55, so the old overflow check skipped wrap.
        self.assertFalse(ws.line_needs_wrap(text, 55))
        new_text, changed = ws.apply_manual_font_and_wrap(text, 55, font=13)
        self.assertTrue(changed)
        self.assertEqual(new_text, ws.wrap_line_text(text, 55))
        self.assertIn("female adventurer who came", new_text.replace("\n", " "))
        # Already at the target layout → no-op.
        again, changed_again = ws.apply_manual_font_and_wrap(new_text, 55, font=13)
        self.assertFalse(changed_again)
        self.assertEqual(again, new_text)

    def test_wrap_overflow_manual_in_names_category(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "names.json"
            doc = {
                "kind": "names",
                "names": [
                    {
                        "note": "噂",
                        "source": "a",
                        "text": (
                            r"So they even take worries like this in the "
                            r"\c[21]\f[20]confessional\c[19]\f[18] booth."
                        ),
                    },
                    {"note": "噂", "source": "b", "text": "OK"},
                    {"note": "other", "source": "c", "text": "x" * 80},
                ],
            }
            path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            hit = ws.WrapHit(
                json_file="names.json",
                kind="names",
                sheet_name="噂",
                row=0,
                field_name="name",
                text=doc["names"][0]["text"],
                max_line_len=80,
            )
            changed = ws.wrap_overflow_manual_in_scope(path, doc, hit, 36, font=14)
            self.assertEqual(changed, 1)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn(r"\f[14]", saved["names"][0]["text"])
            self.assertEqual(saved["names"][1]["text"], "OK")
            self.assertEqual(saved["names"][2]["text"], "x" * 80)


class TestEventScopeWrap(unittest.TestCase):
    def test_wrap_all_in_map_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Map001.mps.json"
            doc = {
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
            }
            path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            hit = ws.WrapHit(
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
            self.assertEqual(ws.scope_stats(doc, hit, 34).overflow, 1)
            self.assertEqual(ws.wrap_overflow_in_scope(path, doc, hit, 34), 1)


class TestFitTextToBox(unittest.TestCase):
    """DB Relayout: wrap + font shrink until soft line count fits."""

    RUMOR = (
        '\\f[14]"I heard there\'s a super hot female adventurer who\n'
        "came to town recently!? Maybe I'll catch a glimpse\n"
        'of her at the \\c[21]\\f[15]tavern\\c[19]\\f[14]!"'
    )

    def test_count_soft_lines(self):
        self.assertEqual(ws.count_soft_lines("a\nb\nc"), 3)
        self.assertEqual(ws.count_soft_lines("one line"), 1)
        self.assertEqual(ws.count_soft_lines(""), 0)

    def test_max_lines_zero_wraps_only(self):
        fitted, changed = ws.fit_text_to_box(self.RUMOR, 44, max_lines=0)
        self.assertTrue(changed)
        self.assertEqual(ws.count_soft_lines(fitted), 3)
        self.assertIn(r"\f[14]", fitted)

    def test_max_lines_shrinks_font_and_fits(self):
        fitted, changed = ws.fit_text_to_box(self.RUMOR, 44, max_lines=2)
        self.assertTrue(changed)
        self.assertLessEqual(ws.count_soft_lines(fitted), 2)
        from util.wolfdawn import codes as wolf_codes

        self.assertLess(wolf_codes.infer_base_font_size(fitted), 14)
        self.assertIn("tavern", fitted)

    def test_box_font_from_jp_source_scales_width(self):
        """Native box px from JP source lets more cells fit when \\f shrinks."""
        from util.wolfdawn import codes as wolf_codes

        fitted, changed = ws.fit_text_to_box(
            self.RUMOR, 44, max_lines=2, box_font=18
        )
        self.assertTrue(changed)
        self.assertLessEqual(ws.count_soft_lines(fitted), 2)
        # With box_font=18, body can stay larger than when native=14.
        self.assertGreaterEqual(wolf_codes.infer_base_font_size(fitted), 12)
        fitted2, changed2 = ws.fit_text_to_box(
            fitted, 44, max_lines=2, box_font=18
        )
        self.assertFalse(changed2)
        self.assertEqual(fitted2, fitted)

    def test_wrap_hit_in_file_honors_max_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "DataBase.project.json"
            source = (
                "「最近町に来た女冒険者が激マブらしいぞ！？\n"
                "　\\c[21]\\f[20]酒場\\c[19]\\f[18]に行ったら会えるかな！」"
            )
            doc = {
                "kind": "db",
                "file": "DataBase.project",
                "groups": [
                    {
                        "typeName": RUMOR_SHEET,
                        "lines": [
                            {
                                "row": 21,
                                "field": 25,
                                "fieldName": GATEKEEPER_FIELD,
                                "source": source,
                                "text": self.RUMOR,
                            }
                        ],
                    }
                ],
            }
            path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            hit_id = {
                "kind": "db",
                "sheet_name": RUMOR_SHEET,
                "row": 21,
                "field_name": GATEKEEPER_FIELD,
            }
            self.assertTrue(
                ws.wrap_hit_in_file(path, doc, hit_id, 44, max_lines=2)
            )
            line = ws.locate_line(doc, hit_id)
            self.assertIsNotNone(line)
            self.assertLessEqual(ws.count_soft_lines(str(line["text"])), 2)
            from util.wolfdawn import codes as wolf_codes

            # JP body is \\f[18]; shrink should land near 12, not floor at 8.
            self.assertGreaterEqual(
                wolf_codes.infer_base_font_size(str(line["text"])), 12
            )


if __name__ == "__main__":
    unittest.main()
