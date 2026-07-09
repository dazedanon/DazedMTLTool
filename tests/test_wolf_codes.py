#!/usr/bin/env python3
"""Tests for WOLF inline control-code repair and font scaling."""

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


    def test_rebuild_preserves_translated_font_sizes(self):
        """Fix-wrap Manual shrink must survive repair before inject."""
        source = r"「\c[21]\f[20]富裕層\c[19]\f[18]の人手」"
        text = r'\f[12]"\c[21]\f[13]Wealthy\c[19]\f[12] staff"'
        fixed = wolf_codes.rebuild_text_preserving_source_codes(source, text)
        self.assertTrue(fixed.startswith(r"\f[12]"))
        self.assertIn(r"\f[13]", fixed)
        self.assertIn(r"\c[21]", fixed)
        self.assertIn(r"\c[19]", fixed)
        self.assertNotIn(r"\f[20]", fixed)
        self.assertNotIn(r"\f[18]", fixed)

    def test_rebuild_keeps_leading_body_font_absent_from_source(self):
        source = "これは説明文です。"
        text = r"\f[14]This is a description."
        fixed = wolf_codes.rebuild_text_preserving_source_codes(source, text)
        self.assertEqual(fixed, text)

    def test_rebuild_keeps_nameplate_body_font(self):
        """Spoken ``Name\\n\\f[N]body`` must not become ``\\f[N]Name\\n`` on inject repair."""
        source = (
            "市民\n俺達の税金で好き放題しやがって……、\n"
            "王子が代行として実権を握ってからは\n"
            "毎晩毎晩パーティー三昧だって話じゃねえか……。"
        )
        text = (
            "Citizen\n\\f[21]Spending our tax money however he\n"
            "pleases...... ever since the Prince\n"
            "took over as regent, it's been\n"
            "nothing but parties every single\n"
            "night, I tell you......"
        )
        fixed = wolf_codes.rebuild_text_preserving_source_codes(source, text)
        self.assertEqual(fixed, text)
        self.assertIn("Spending our tax money", fixed)
        self.assertFalse(fixed.rstrip().endswith("Citizen"))

    def test_document_has_font_size_drift_for_db(self):
        doc = {
            "kind": "db",
            "groups": [
                {
                    "typeName": "噂",
                    "lines": [
                        {
                            "source": r"\c[21]\f[20]娼館\c[19]\f[18]",
                            "text": r"\f[14]\c[21]\f[16]Brothel\c[19]\f[14]",
                        }
                    ],
                }
            ],
        }
        self.assertTrue(wolf_codes.document_has_font_size_drift(doc))
        self.assertFalse(
            wolf_codes.document_has_font_size_drift(
                {
                    "kind": "db",
                    "groups": [
                        {
                            "typeName": "x",
                            "lines": [{"source": "あ", "text": "A"}],
                        }
                    ],
                }
            )
        )


class WolfFontScaleTests(unittest.TestCase):
    def test_scale_keeps_emphasis_ratio_and_leads_with_body(self):
        # Cafe-style mid-line emphasis: body must lead so Wolf sets line height.
        text = (
            '"That \\c[21]\\f[20]cafe\\c[19]\\f[18] over there has been\n'
            "packed lately.\""
        )
        new_text, _ = wolf_codes.scale_font_sizes(text, 13)
        self.assertTrue(new_text.startswith(r"\f[13]"))
        # 20 * 13/18 ≈ 14.4 → 14; body 13
        self.assertIn(r"\c[21]\f[14]cafe\c[19]\f[13]", new_text)
        self.assertNotIn(r"\f[20]", new_text)
        self.assertNotIn(r"\f[18]", new_text)
        self.assertEqual(wolf_codes.infer_base_font_size(text), 18)

    def test_font_size_codes_differ_only_for_size_drift(self):
        source = r"\c[21]\f[20]娼館\c[19]\f[18]"
        shrunk = r"\f[14]\c[21]\f[16]Brothel\c[19]\f[14]"
        dropped_color = r"\f[14]Brothel"
        self.assertTrue(wolf_codes.font_size_codes_differ(source, shrunk))
        self.assertFalse(wolf_codes.font_size_codes_differ(source, dropped_color))
        self.assertTrue(
            wolf_codes.names_doc_has_font_size_drift(
                {"kind": "names", "names": [{"source": source, "text": shrunk}]}
            )
        )


if __name__ == "__main__":
    unittest.main()
