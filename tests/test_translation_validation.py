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

    def test_orphan_backslash_cannot_become_translated_control_code(self):
        source = r"\C[1]\ヘレンの体力－100"
        protected, replacements = tr.protect_script_codes(source)
        raw_translation = protected.replace(
            "ヘレンの体力－100", "Helen's Stamina -100"
        )

        self.assertEqual(tr.restore_script_codes(protected, replacements), source)
        self.assertIn("\\", replacements.values())

        restored_for_validation = tr.restore_script_codes(
            raw_translation, replacements
        )
        valid, reasons = tr.validate_control_codes(
            source, restored_for_validation, {0: replacements}
        )
        self.assertTrue(valid, reasons)

        safe_translation = tr.restore_script_codes(
            raw_translation,
            replacements,
            escape_orphan_backslashes=True,
        )
        self.assertEqual(safe_translation, r"\C[1]\\Helen's Stamina -100")
        valid, reasons = tr.validate_control_codes(
            source, safe_translation, {0: replacements}
        )
        self.assertTrue(valid, reasons)
        self.assertEqual(
            tr._reprotect_cached_codes(safe_translation, replacements),
            raw_translation,
        )

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
        # Broader class matching MV/MZ-style CJK punctuation (includes 〝〟).
        cjk_punct_regex = (
            r"[\u3000\u3002-\u3009\u300C-\u303F\u3040-\u309A\u309C-\u30FA"
            r"\u31F0-\u31FF\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\uFF61-\uFF9F]+"
        )
        cases = (
            (
                "ideographic choice padding",
                "‣モラル崩壊　　　　　必要な欠片：10",
                "‣Moral Collapse　　　　　Fragments Required: 10",
                None,
                language_regex,
                True,
                None,
            ),
            (
                "cjk quote wrappers around english",
                'This one uses something called 〝phytoncide〟.',
                'This one uses something called 〝phytoncide〟.',
                None,
                cjk_punct_regex,
                True,
                None,
            ),
            (
                "source-language residue",
                "そのとおり",
                "Exactly(そのとおり)!!",
                None,
                language_regex,
                False,
                "Source-language text remains",
            ),
            (
                "gloss leaves source word",
                "鉱山って、英語でMineって 言うらしいわよ",
                'Apparently, 鉱山 is called "Mine" in English.',
                None,
                language_regex,
                False,
                "Source-language text remains",
            ),
            (
                "gloss translates the explained word",
                "鉱山って、英語でMineって 言うらしいわよ",
                'Apparently, a mine is called "Mine" in English.',
                None,
                language_regex,
                True,
                None,
            ),
            ("Chinese CJK", "騎士", "骑士", "Chinese", language_regex, True, None),
            (
                "Japanese kana in Chinese",
                "こんにちは",
                "こんにちは",
                "Chinese",
                language_regex,
                False,
                "Japanese kana remains",
            ),
            (
                "Japanese prolonged sound mark",
                "ほげぇぇぇーーっ！！",
                "Hrooooghhhhhーー!!",
                None,
                language_regex,
                False,
                "Source-language text remains",
            ),
            (
                "leaked line marker",
                "役人",
                "}Line1:",
                None,
                language_regex,
                False,
                "Structured response marker",
            ),
        )
        for label, source, translated, language, regex, expected_valid, reason in cases:
            with self.subTest(label):
                kwargs = {"target_language": language} if language else {}
                valid, indices, reasons = tr.validate_translation_content(
                    [source], [translated], regex, **kwargs
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


class TranslationResponseSchemaTests(unittest.TestCase):
    def test_schema_pins_positional_translations_array(self):
        schema = tr.createTranslationSchema(3)
        translations = schema["properties"]["translations"]
        self.assertEqual(schema["required"], ["translations"])
        self.assertEqual(translations["minItems"], 3)
        self.assertEqual(translations["maxItems"], 3)
        self.assertEqual(translations["items"], {"type": "string"})

    def test_extract_and_log_keep_numeric_line_order(self):
        # Provider may emit LineN keys lexically (Line1, Line10, Line2).
        raw = (
            '{"Line1":"One","Line10":"Ten","Line2":"Two","Line3":"Three",'
            '"Line4":"Four","Line5":"Five","Line6":"Six","Line7":"Seven",'
            '"Line8":"Eight","Line9":"Nine"}'
        )
        self.assertEqual(
            tr.extractTranslation(raw, True),
            [
                "One", "Two", "Three", "Four", "Five",
                "Six", "Seven", "Eight", "Nine", "Ten",
            ],
        )
        logged = tr.format_translation_response_for_log(raw)
        self.assertLess(logged.index('"Line2"'), logged.index('"Line10"'))
        self.assertEqual(
            tr.extractTranslation(
                '{"translations":["A","B","C"]}', True
            ),
            ["A", "B", "C"],
        )
        array_logged = tr.format_translation_response_for_log(
            '{"translations":["A","B","C"]}'
        )
        self.assertIn('"Line1": "A"', array_logged)
        self.assertIn('"Line3": "C"', array_logged)


if __name__ == "__main__":
    unittest.main()
