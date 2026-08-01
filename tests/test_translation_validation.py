#!/usr/bin/env python3
"""Regression tests for shared translation safety validation."""

from __future__ import annotations

import unittest

from util import translation as tr


class ControlCodeProtectionTests(unittest.TestCase):
    def test_general_rpgmaker_controls_round_trip_exactly(self):
        source = r"\SHADOW[3]試練\SHADOW[0] \I[14]\>文字\}\C[0]"

        protected, replacements = tr.protect_script_codes(source)

        self.assertNotIn(r"\SHADOW[3]", protected)
        self.assertNotIn(r"\I[14]", protected)
        self.assertEqual(tr.restore_script_codes(protected, replacements), source)

    def test_control_validation_rejects_changed_parameter_and_added_escape(self):
        source = r"\SHADOW[3]Trial \I[14]"
        translated = r"\SHADOW[08]Trial \I[14]\Coming"

        valid, reasons = tr.validate_control_codes(source, translated)

        self.assertFalse(valid)
        self.assertIn(r"\SHADOW[3]", reasons[0])
        self.assertIn(r"\SHADOW[08]", reasons[0])
        self.assertIn(r"\Coming", reasons[0])

    def test_control_validation_preserves_duplicate_counts(self):
        valid, _ = tr.validate_control_codes(r"\I[14]a\I[14]", r"\I[14]a")
        self.assertFalse(valid)

    def test_control_validation_allows_complete_scope_to_move_with_grammar(self):
        valid, reasons = tr.validate_control_codes(
            r"\C[2]Name\C[0] \I[14]", r"\I[14] \C[2]Name\C[0]"
        )
        self.assertTrue(valid, reasons)

    def test_control_validation_rejects_reversed_formatting_scope(self):
        valid, reasons = tr.validate_control_codes(
            r"\C[2]Name\C[0]", r"\C[0]\C[2]Name"
        )

        self.assertFalse(valid)
        self.assertIn("formatting scope order changed", reasons[0])

    def test_mapped_value_code_can_move_with_translated_subject(self):
        source = (
            r"\I[275]\C[17]蜘蛛の糸\C[0] を \V[302]束 売却した。 "
            r"\V[303]Ｇ を手に入れた！"
        )
        _, replacements = tr.protect_script_codes(source)
        translated = (
            r"Sold \V[302] bundles of \I[275]\C[17]Spider Thread\C[0]. "
            r"Received \V[303]G!"
        )

        valid, reasons = tr.validate_control_codes(
            source, translated, {0: replacements}
        )

        self.assertTrue(valid, reasons)

    def test_restored_bare_code_does_not_consume_adjacent_english(self):
        source = r"\vcそう…、あれは父さんが死んで間もない頃――"
        protected, replacements = tr.protect_script_codes(source)
        translated = tr.restore_script_codes(
            protected.replace("そう…、あれは父さんが死んで間もない頃――", "That's right..."),
            replacements,
        )

        valid, reasons = tr.validate_control_codes(
            source, translated, {0: replacements}
        )

        self.assertTrue(valid, reasons)

    def test_mapped_control_validation_still_rejects_missing_code(self):
        source = r"\vcそう"
        _, replacements = tr.protect_script_codes(source)

        valid, reasons = tr.validate_control_codes(
            source, "That's right...", {0: replacements}
        )

        self.assertFalse(valid)
        self.assertIn("missing protected codes", reasons[0])


class TranslationContentValidationTests(unittest.TestCase):
    def test_allows_ideographic_space_used_as_choice_padding(self):
        valid, indices, reasons = tr.validate_translation_content(
            ["‣モラル崩壊　　　　　必要な欠片：10"],
            ["‣Moral Collapse　　　　　Fragments Required: 10"],
            r"[\u3000一-龠ぁ-ゔァ-ヴー]+",
        )

        self.assertTrue(valid, reasons)
        self.assertEqual(indices, [])

    def test_rejects_source_language_residue(self):
        valid, indices, reasons = tr.validate_translation_content(
            ["そのとおり"], ["Exactly(そのとおり)!!"], r"[一-龠ぁ-ゔァ-ヴー]+"
        )
        self.assertFalse(valid)
        self.assertEqual(indices, [0])
        self.assertIn("Source-language text remains", reasons[0])

    def test_rejects_japanese_prolonged_sound_mark(self):
        valid, indices, reasons = tr.validate_translation_content(
            ["ほげぇぇぇーーっ！！"], ["Hrooooghhhhhーー!!"],
            r"[一-龠ぁ-ゔァ-ヴー]+",
        )

        self.assertFalse(valid)
        self.assertEqual(indices, [0])
        self.assertIn("Source-language text remains", reasons[0])

    def test_short_translation_is_hard_failure(self):
        source = "これはとても長い日本語の文章です"
        valid, indices, reasons = tr.validate_translation_content(
            [source], ["!"], r"[一-龠ぁ-ゔァ-ヴー]+"
        )
        warning_indices, warnings = tr.translation_content_warnings(
            [source], ["!"], r"[一-龠ぁ-ゔァ-ヴー]+"
        )

        self.assertFalse(valid)
        self.assertEqual(indices, [0])
        self.assertIn("unusually short", reasons[0])
        self.assertEqual(warning_indices, [0])
        self.assertIn("unusually short", warnings[0])

    def test_repeated_punctuation_is_hard_failure(self):
        source = "[ルシア]: ………………………………………………………………。"
        translated = "[Lucia]: " + "." * 50
        valid, indices, reasons = tr.validate_translation_content(
            [source], [translated], r"[一-龠ぁ-ゔァ-ヴー]+"
        )
        warning_indices, warnings = tr.translation_content_warnings(
            [source], [translated], r"[一-龠ぁ-ゔァ-ヴー]+"
        )

        self.assertFalse(valid)
        self.assertEqual(indices, [0])
        self.assertIn("Excessive character repetition", reasons[0])
        self.assertEqual(warning_indices, [0])
        self.assertIn("Excessive character repetition", warnings[0])

    def test_rejects_leaked_line_marker(self):
        valid, indices, reasons = tr.validate_translation_content(
            ["役人"], ["}Line1:"], r"[一-龠ぁ-ゔァ-ヴー]+"
        )
        self.assertFalse(valid)
        self.assertEqual(indices, [0])
        self.assertIn("Structured response marker", reasons[0])


if __name__ == "__main__":
    unittest.main()
