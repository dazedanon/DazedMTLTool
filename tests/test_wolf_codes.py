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

    def test_rebuild_repairs_whitespace_in_shrunken_font(self):
        source = r"\f[18]文字"
        text = r"\f[ 14]Text"
        fixed = wolf_codes.rebuild_text_preserving_source_codes(source, text)
        self.assertEqual(fixed, r"\f[14]Text")

    def test_rebuild_does_not_duplicate_font_after_prefix_control_code(self):
        source = r"\>\f[5]レベル\cself[30]"
        text = r"\>\f[5]Level\cself[30]"
        fixed = wolf_codes.rebuild_text_preserving_source_codes(source, text)
        self.assertEqual(fixed, text)

    def test_rebuild_removes_old_duplicate_font_before_prefix_control_code(self):
        source = r"\>\f[5]レベル\cself[30]"
        text = r"\f[5]\>\f[5]Level\cself[30]"
        fixed = wolf_codes.rebuild_text_preserving_source_codes(source, text)
        self.assertEqual(fixed, r"\>\f[5]Level\cself[30]")

    def test_rebuild_keeps_distinct_manual_body_font_before_prefix(self):
        source = r"\>\f[5]レベル\cself[30]"
        text = r"\f[14]\>\f[5]Level\cself[30]"
        fixed = wolf_codes.rebuild_text_preserving_source_codes(source, text)
        self.assertEqual(fixed, text)

    def test_rebuild_preserves_valid_moved_variable_code(self):
        source = r"\v[24]Day        "
        text = "Day \\v[24]\n        "
        fixed = wolf_codes.rebuild_text_preserving_source_codes(source, text)
        self.assertEqual(fixed, text)

    def test_rebuild_does_not_guess_reordered_variable_codes(self):
        source = r"\v[1] vs \v[2]"
        text = r"\v[2] versus \v[1]"
        fixed = wolf_codes.rebuild_text_preserving_source_codes(source, text)
        self.assertEqual(fixed, text)
        self.assertTrue(wolf_codes.non_font_code_sequences_differ(source, text))

    def test_rebuild_does_not_guess_missing_color_code(self):
        source = r"\c[1]赤\c[0]"
        text = r"Red \c[1]"
        fixed = wolf_codes.rebuild_text_preserving_source_codes(source, text)
        self.assertEqual(fixed, text)
        self.assertTrue(wolf_codes.non_font_code_sequences_differ(source, text))

    def test_rebuild_keeps_nameplate_body_font_with_other_inline_codes(self):
        source = "市民\n赤い\\c[1]花"
        text = "Citizen\n\\f[14]Red \\c[1]flower"
        fixed = wolf_codes.rebuild_text_preserving_source_codes(source, text)
        self.assertEqual(fixed, text)
        self.assertFalse(wolf_codes.non_font_code_sequences_differ(source, text))

    def test_rebuild_keeps_extra_midline_font(self):
        source = r"\c[1]赤い花"
        text = r"\c[1]Red \f[14]flower"
        fixed = wolf_codes.rebuild_text_preserving_source_codes(source, text)
        self.assertEqual(fixed, text)

    def test_rebuild_does_not_strip_literal_backslash_n(self):
        source = r"\c[1]一行"
        text = r"\c[1]One\nline"
        fixed = wolf_codes.rebuild_text_preserving_source_codes(source, text)
        self.assertEqual(fixed, text)
        self.assertTrue(wolf_codes.non_font_code_sequences_differ(source, text))

    def test_rebuild_restores_literal_newline_when_source_has_one(self):
        source = "既に見たことのあるイベントです。\nスキップしますか？"
        text = r"This is an event you've already seen.\nWould you like to skip it?"
        fixed = wolf_codes.rebuild_text_preserving_source_codes(source, text)
        self.assertEqual(
            fixed,
            "This is an event you've already seen.\nWould you like to skip it?",
        )

    def test_rebuild_does_not_guess_ambiguous_literal_newlines(self):
        source = "一行だけ"
        text = r"One\nline"
        fixed = wolf_codes.rebuild_text_preserving_source_codes(source, text)
        self.assertEqual(fixed, text)

    def test_protect_and_restore_roundtrip(self):
        src = "Line with \\^ and \\cself[8]"
        protected, mapping = wolf_codes.protect_wolf_codes(src)
        self.assertNotIn("\\^", protected)
        restored = wolf_codes.restore_wolf_code_placeholders(protected, mapping)
        self.assertEqual(restored, src)

    def test_ruby_exposes_base_spelling_and_is_not_restored(self):
        src = r"もう\r[射精,だ]してしまう"
        protected, mapping = wolf_codes.protect_wolf_codes(src)

        self.assertIn("射精", protected)
        self.assertNotIn(r"\r[射精,だ]", protected)
        self.assertEqual(mapping, {})
        translated = protected.replace("射精", "ejaculate")
        self.assertEqual(
            wolf_codes.restore_wolf_code_placeholders(translated, mapping),
            "もうejaculateしてしまう",
        )

    def test_ruby_removal_is_safe_only_when_other_codes_match(self):
        source = r"\c[1]\r[彼女,イア]の目\i[200]"
        self.assertTrue(
            wolf_codes.ruby_codes_removed_safely(
                source, r"\c[1]Her eyes\i[200]"
            )
        )
        self.assertFalse(
            wolf_codes.non_font_code_sequences_differ(
                source, r"\c[1]Her eyes\i[200]"
            )
        )
        self.assertFalse(
            wolf_codes.ruby_codes_removed_safely(source, r"Her eyes\i[200]")
        )

    def test_cdb_exposes_resolved_value_then_restores_exact_code(self):
        src = r"こんにちは、\cdb[0:12:0]さん"
        protected, mapping = wolf_codes.protect_wolf_codes(
            src, {"0:12:0": "ウルファール"}
        )

        self.assertIn("ウルファール", protected)
        self.assertNotIn(r"\cdb[0:12:0]", protected)
        translated = protected.replace("ウルファール", "Ulfar")
        self.assertEqual(
            wolf_codes.restore_wolf_code_placeholders(translated, mapping),
            src,
        )

    def test_context_marker_validation_rejects_dropped_or_duplicated_markers(self):
        protected, mapping = wolf_codes.protect_wolf_codes(
            r"\cdb[0:12:0]の目", {"0:12:0": "ウルファール"}
        )
        self.assertTrue(
            wolf_codes.wolf_code_placeholders_preserved(protected, mapping)
        )
        self.assertFalse(
            wolf_codes.wolf_code_placeholders_preserved(
                protected.replace("_END__", ""), mapping
            )
        )
        self.assertFalse(
            wolf_codes.wolf_code_placeholders_preserved(protected + protected, mapping)
        )

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

    def test_repair_document_fixes_safe_duplicate_font_and_literal_newline(self):
        doc = {
            "kind": "common",
            "scenes": [
                {
                    "event": 74,
                    "lines": [
                        {
                            "cmd": 200,
                            "str": 0,
                            "source": r"\>\f[5]レベル\cself[30]",
                            "text": r"\f[5]\>\f[5]Level\cself[30]",
                        }
                    ],
                },
                {
                    "event": 245,
                    "lines": [
                        {
                            "cmd": 31,
                            "str": 0,
                            "source": "既に見たイベントです。\nスキップしますか？",
                            "text": r"This event was already seen.\nSkip it?",
                        }
                    ],
                },
            ],
        }

        _doc, notes = wolf_codes.repair_document(doc)

        self.assertEqual(len(notes), 2)
        self.assertEqual(
            doc["scenes"][0]["lines"][0]["text"],
            r"\>\f[5]Level\cself[30]",
        )
        self.assertEqual(
            doc["scenes"][1]["lines"][0]["text"],
            "This event was already seen.\nSkip it?",
        )


    def test_rebuild_preserves_translated_font_sizes(self):
        """Fix-wrap Manual shrink must survive repair before inject."""
        source = r"「\c[21]\f[20]富裕層\c[19]\f[18]の人手」"
        text = r'\f[12]"\c[21]\f[13]Wealthy\c[19]\f[12] staff"'
        fixed = wolf_codes.rebuild_text_preserving_source_codes(source, text)
        self.assertEqual(
            fixed,
            r'\f[12]"\c[21]\f[13]Wealthy\c[19]\f[12] staff"',
        )
        self.assertNotIn(r"\f[20]", fixed)
        self.assertNotIn(r"\f[18]", fixed)

    def test_repair_document_leaves_common_event_font_sequence_unchanged(self):
        text = r"\>\f[5]Level\cself[30]"
        doc = {
            "kind": "common",
            "scenes": [
                {
                    "event": 30,
                    "lines": [
                        {
                            "cmd": 101,
                            "str": 0,
                            "source": r"\>\f[5]レベル\cself[30]",
                            "text": text,
                        }
                    ],
                }
            ],
        }
        _doc, notes = wolf_codes.repair_document(doc)
        self.assertEqual(notes, [])
        self.assertEqual(doc["scenes"][0]["lines"][0]["text"], text)

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

    def test_non_font_drift_blocks_document_font_only_classification(self):
        doc = {
            "kind": "db",
            "groups": [
                {
                    "typeName": "mixed",
                    "lines": [
                        {
                            "source": r"\f[18]文字",
                            "text": r"\f[14]Text",
                        },
                        {
                            "source": r"\c[1]赤\c[0]",
                            "text": r"Red \c[1]",
                        },
                    ],
                }
            ],
        }
        self.assertTrue(wolf_codes.document_has_font_size_drift(doc))
        self.assertTrue(wolf_codes.document_has_non_font_code_drift(doc))

    def test_translation_can_safely_close_unclosed_source_code(self):
        source = (
            "レイ\n「はい\\i[200] text\\i[200\n"
            "　source suffix\\i[200]」"
        )
        text = (
            'Rey\n"Okay \\i[200] text\\i[200]\n'
            '　translated suffix\\i[200]"'
        )
        doc = {
            "kind": "map",
            "scenes": [{"lines": [{"source": source, "text": text}]}],
        }

        self.assertTrue(wolf_codes.safely_closes_unclosed_source_codes(source, text))
        self.assertTrue(wolf_codes.document_has_safe_unclosed_source_repairs(doc))
        self.assertFalse(wolf_codes.non_font_code_sequences_differ(source, text))
        self.assertFalse(wolf_codes.document_has_non_font_code_drift(doc))

    def test_unclosed_source_repair_rejects_other_code_changes(self):
        source = "A\\i[200\nB\\i[31]"
        missing_other_code = "A\\i[200]\nB"

        self.assertFalse(
            wolf_codes.safely_closes_unclosed_source_codes(
                source, missing_other_code
            )
        )
        self.assertTrue(
            wolf_codes.non_font_code_sequences_differ(source, missing_other_code)
        )

    def test_escaped_quotes_are_non_font_code_drift(self):
        self.assertTrue(
            wolf_codes.non_font_code_sequences_differ(
                "Japanese quotes", r'English \"quotes\"'
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
