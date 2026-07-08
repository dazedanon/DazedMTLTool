#!/usr/bin/env python3
"""Unit tests for selective DB wrap in util/wolfdawn/selective_wrap.py."""

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

from util.wolfdawn import selective_wrap as sw  # noqa: E402
import util.dazedwrap as dazedwrap  # noqa: E402


SAMPLE = {
    "file": "DataBase.project",
    "kind": "db",
    "groups": [
        {
            "type": 10,
            "typeName": "■イベント(テスト)",
            "lines": [
                {
                    "row": 0,
                    "field": 1,
                    "fieldName": "好きなもの_コメント",
                    "source": "短い",
                    "text": "Short text that fits",
                },
                {
                    "row": 1,
                    "field": 1,
                    "fieldName": "好きなもの_コメント",
                    "source": "長い",
                    "text": (
                        "This is a very long English comment that definitely "
                        "exceeds forty characters in a single line"
                    ),
                },
            ],
        },
        {
            "type": 0,
            "typeName": "Item · アイテム",
            "lines": [
                {
                    "row": 0,
                    "field": 1,
                    "fieldName": "Description · 説明",
                    "source": "x",
                    "text": "Also a long item description that should wrap when selected",
                },
            ],
        },
    ],
}


class TestLineNeedsWrap(unittest.TestCase):
    def test_short_line_skipped(self):
        self.assertFalse(sw.line_needs_wrap("Short", 40, min_visible=20))

    def test_long_line_needs_wrap(self):
        text = "A" * 50
        self.assertTrue(sw.line_needs_wrap(text, 40))

    def test_color_and_font_codes_do_not_count_toward_width(self):
        text = r"Hello \c[21]\f[20]tavern\c[19] end"
        self.assertFalse(sw.line_needs_wrap(text, 20))
        self.assertTrue(sw.line_needs_wrap(text, 10))

    def test_wrap_preserves_inline_codes(self):
        text = r"Go to the \c[21]\f[20]tavern\c[19]\f[18] tonight for fun"
        wrapped = sw.wrap_line_text(text, 18)
        self.assertIn(r"\c[21]", wrapped)
        self.assertIn(r"\f[20]", wrapped)
        for line in wrapped.split("\n"):
            self.assertLessEqual(dazedwrap._get_visible_length(line), 18)


class TestWrapDbDocument(unittest.TestCase):
    def test_only_checked_sheet_and_field(self):
        keys = frozenset({"DataBase.project.json|■イベント(テスト)"})
        pattern = sw.FIELD_PRESET_COMMENTS
        doc = json.loads(json.dumps(SAMPLE))
        wrapped, skipped = sw.wrap_db_document(
            doc,
            group_keys=keys,
            field_pattern=pattern,
            width=30,
            min_visible=0,
        )
        self.assertEqual(wrapped, 1)
        long_line = doc["groups"][0]["lines"][1]["text"]
        self.assertIn("\n", long_line)
        short_line = doc["groups"][0]["lines"][0]["text"]
        self.assertNotIn("\n", short_line)

    def test_group_type_indices(self):
        keys = frozenset({"DataBase.project.json|■イベント(テスト)"})
        self.assertEqual(sw.group_type_indices(SAMPLE, keys), [10])


class TestWrapTranslatedDir(unittest.TestCase):
    def test_writes_touched_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "DataBase.project.json"
            path.write_text(json.dumps(SAMPLE), encoding="utf-8")
            result = sw.wrap_db_translated_dir(
                tmp,
                group_keys=frozenset({"DataBase.project.json|■イベント(テスト)"}),
                field_presets=frozenset({"comments"}),
                width=30,
                min_visible=0,
            )
            self.assertEqual(result.lines_wrapped, 1)
            self.assertEqual(result.files_touched, 1)


if __name__ == "__main__":
    unittest.main()
