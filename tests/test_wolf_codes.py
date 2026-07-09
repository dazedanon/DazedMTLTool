#!/usr/bin/env python3
"""Tests for WOLF inline control-code repair."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from util.wolfdawn import codes as wolf_codes  # noqa: E402


class WolfCodesRepairTests(unittest.TestCase):
    def test_fixes_spurious_space_before_caret(self):
        source = "占い師\nはぁ！\\^"
        text = "Fortune-teller\nHa!\\ ^"
        fixed = wolf_codes.rebuild_text_preserving_source_codes(source, text)
        self.assertEqual(fixed, "Fortune-teller\nHa!\\^")

    def test_rebuild_preserves_multiple_codes(self):
        source = "A\\c[1]B\\f[2]C"
        text = "A\\c[ 1]B\\f[ 2]C"
        fixed = wolf_codes.rebuild_text_preserving_source_codes(source, text)
        self.assertEqual(fixed, "A\\c[1]B\\f[2]C")

    def test_protect_and_restore_roundtrip(self):
        src = "Line with \\^ and \\cself[8]"
        protected, mapping = wolf_codes.protect_wolf_codes(src)
        self.assertNotIn("\\^", protected)
        restored = wolf_codes.restore_wolf_code_placeholders(protected, mapping)
        self.assertEqual(restored, src)

    def test_repair_document_updates_leaf(self):
        doc = {
            "kind": "map",
            "scenes": [
                {
                    "event": 374,
                    "lines": [
                        {
                            "cmd": 233,
                            "str": 0,
                            "source": "占い師\nはぁ！\\^",
                            "text": "Fortune-teller\nHa!\\ ^",
                        }
                    ],
                }
            ],
        }
        _doc, notes = wolf_codes.repair_document(doc)
        self.assertEqual(len(notes), 1)
        self.assertEqual(
            doc["scenes"][0]["lines"][0]["text"],
            "Fortune-teller\nHa!\\^",
        )

    def test_apply_font_size_replaces_existing_codes(self):
        text = r"Go to the \c[21]\f[20]tavern\c[19]\f[18]!"
        new_text, count = wolf_codes.apply_font_size(text, 16)
        self.assertEqual(count, 3)  # 2 replaced + leading body
        self.assertTrue(new_text.startswith(r"\f[16]"))
        self.assertIn(r"\f[16]", new_text)
        self.assertNotIn(r"\f[20]", new_text)
        self.assertNotIn(r"\f[18]", new_text)

    def test_apply_font_size_prepends_when_missing(self):
        text = "Plain text without font codes"
        new_text, count = wolf_codes.apply_font_size(text, 18)
        self.assertEqual(count, 1)
        self.assertTrue(new_text.startswith(r"\f[18]"))

    def test_infer_base_font_prefers_body_over_emphasis(self):
        text = r"So they even take worries\nlike this in the\n\c[21]\f[20]confessional\c[19]\f[18]..."
        self.assertEqual(wolf_codes.infer_base_font_size(text), 18)

    def test_scale_font_sizes_keeps_emphasis_ratio(self):
        text = (
            r"So they even take worries\nlike this in the\n"
            r"\c[21]\f[20]confessional\c[19]\f[18]..."
        )
        new_text, count = wolf_codes.scale_font_sizes(text, 14)
        self.assertEqual(count, 3)  # 2 scaled + leading body insert
        # 20 * 14/18 ≈ 15.56 → 16; 18 * 14/18 = 14
        self.assertTrue(new_text.startswith(r"\f[14]"))
        self.assertIn(r"\f[16]", new_text)
        self.assertIn(r"\f[14]", new_text)
        self.assertNotIn(r"\f[20]", new_text)
        self.assertNotIn(r"\f[18]", new_text)

    def test_scale_font_sizes_matches_names_wrap_style_shrink(self):
        source_style = r"\c[21]\f[20]Brothel\c[19]\f[18] doesn't get much use"
        new_text, _ = wolf_codes.scale_font_sizes(source_style, 17)
        # 20*17/18 ≈ 18.89 → 19; body 17
        self.assertTrue(new_text.startswith(r"\f[17]"))
        self.assertIn(r"\f[19]", new_text)
        self.assertIn(r"\f[17]", new_text)

    def test_scale_font_sizes_leads_with_body_for_midline_emphasis(self):
        # Cafe-style: body only appears after emphasis; Wolf needs \\f at start.
        text = (
            '"That \\c[21]\\f[14]cafe\\c[19]\\f[13] over there has been\n'
            'packed lately." "Apparently\n'
            "they're hiring waitresses.\""
        )
        new_text, count = wolf_codes.scale_font_sizes(text, 13)
        self.assertGreaterEqual(count, 2)
        self.assertTrue(new_text.startswith(r"\f[13]"))
        self.assertIn(r"\c[21]\f[14]cafe\c[19]\f[13]", new_text)

    def test_ensure_leading_font_size_idempotent(self):
        text = r'\f[13]"That \c[21]\f[14]cafe\c[19]\f[13] over there"'
        self.assertEqual(wolf_codes.ensure_leading_font_size(text, 13), text)

    def test_apply_font_size_also_leads(self):
        text = r'"That \c[21]\f[20]cafe\c[19]\f[18] over there"'
        new_text, _ = wolf_codes.apply_font_size(text, 13)
        self.assertTrue(new_text.startswith(r"\f[13]"))
        self.assertNotIn(r"\f[20]", new_text)

    def test_font_size_codes_differ_detects_names_wrap_shrink(self):
        source = (
            r"「おい！例の\c[21]\f[20]教会の特別奉仕活動\c[19]\f[18]があるってよ！」"
        )
        text = (
            r'\f[14]"Hey! Apparently there\'s one of those '
            r'\c[21]\f[16]Special Service Activities at the church\c[19]\f[14]!"'
        )
        self.assertTrue(wolf_codes.font_size_codes_differ(source, text))

    def test_font_size_codes_differ_false_when_color_missing(self):
        source = r"\c[21]\f[20]娼館\c[19]\f[18]"
        text = r"\f[14]Brothel"  # dropped colour codes
        self.assertFalse(wolf_codes.font_size_codes_differ(source, text))

    def test_names_doc_has_font_size_drift(self):
        doc = {
            "kind": "names",
            "names": [
                {
                    "source": r"\c[21]\f[20]娼館\c[19]\f[18]",
                    "text": r"\f[14]\c[21]\f[16]Brothel\c[19]\f[14]",
                }
            ],
        }
        self.assertTrue(wolf_codes.names_doc_has_font_size_drift(doc))


if __name__ == "__main__":
    unittest.main()
