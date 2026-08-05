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

    def test_control_validation_cases(self):
        cases = (
            (
                "changed parameter and added escape",
                r"\SHADOW[3]Trial \I[14]",
                r"\SHADOW[08]Trial \I[14]\Coming",
                False,
                (r"\SHADOW[3]", r"\SHADOW[08]", r"\Coming"),
            ),
            (
                "duplicate count",
                r"\I[14]a\I[14]",
                r"\I[14]a",
                False,
                (),
            ),
            (
                "complete scope moves with grammar",
                r"\C[2]Name\C[0] \I[14]",
                r"\I[14] \C[2]Name\C[0]",
                True,
                (),
            ),
            (
                "reversed formatting scope",
                r"\C[2]Name\C[0]",
                r"\C[0]\C[2]Name",
                False,
                ("formatting scope order changed",),
            ),
        )
        for label, source, translated, expected_valid, reason_parts in cases:
            with self.subTest(label):
                valid, reasons = tr.validate_control_codes(source, translated)
                self.assertEqual(valid, expected_valid, reasons)
                for part in reason_parts:
                    self.assertIn(part, reasons[0])

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
    def test_translation_content_validation_cases(self):
        language_regex = r"[\u3000一-龠ぁ-ゔァ-ヴー]+"
        cases = (
            (
                "ideographic choice padding",
                "‣モラル崩壊　　　　　必要な欠片：10",
                "‣Moral Collapse　　　　　Fragments Required: 10",
                None,
                True,
                None,
            ),
            (
                "source-language residue",
                "そのとおり",
                "Exactly(そのとおり)!!",
                None,
                False,
                "Source-language text remains",
            ),
            (
                "gloss leaves source word",
                "鉱山って、英語でMineって 言うらしいわよ",
                'Apparently, 鉱山 is called "Mine" in English.',
                None,
                False,
                "Source-language text remains",
            ),
            (
                "gloss translates the explained word",
                "鉱山って、英語でMineって 言うらしいわよ",
                'Apparently, a mine is called "Mine" in English.',
                None,
                True,
                None,
            ),
            ("Chinese CJK", "騎士", "骑士", "Chinese", True, None),
            (
                "Japanese kana in Chinese",
                "こんにちは",
                "こんにちは",
                "Chinese",
                False,
                "Japanese kana remains",
            ),
            (
                "Japanese prolonged sound mark",
                "ほげぇぇぇーーっ！！",
                "Hrooooghhhhhーー!!",
                None,
                False,
                "Source-language text remains",
            ),
            (
                "leaked line marker",
                "役人",
                "}Line1:",
                None,
                False,
                "Structured response marker",
            ),
        )
        for label, source, translated, language, expected_valid, reason in cases:
            with self.subTest(label):
                kwargs = {"target_language": language} if language else {}
                valid, indices, reasons = tr.validate_translation_content(
                    [source], [translated], language_regex, **kwargs
                )
                self.assertEqual(valid, expected_valid, reasons)
                self.assertEqual(indices, [] if expected_valid else [0])
                if reason:
                    self.assertIn(reason, reasons[0])

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


if __name__ == "__main__":
    unittest.main()
