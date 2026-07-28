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

    def test_control_validation_rejects_reordered_scopes(self):
        valid, reasons = tr.validate_control_codes(
            r"\C[2]Name\C[0] \I[14]", r"\I[14] \C[2]Name\C[0]"
        )
        self.assertFalse(valid)
        self.assertIn("order changed", reasons[0])


class TranslationContentValidationTests(unittest.TestCase):
    def test_rejects_source_language_residue(self):
        valid, indices, reasons = tr.validate_translation_content(
            ["そのとおり"], ["Exactly(そのとおり)!!"], r"[一-龠ぁ-ゔァ-ヴー]+"
        )
        self.assertFalse(valid)
        self.assertEqual(indices, [0])
        self.assertIn("Source-language text remains", reasons[0])

    def test_rejects_leaked_line_marker(self):
        valid, indices, reasons = tr.validate_translation_content(
            ["役人"], ["}Line1:"], r"[一-龠ぁ-ゔァ-ヴー]+"
        )
        self.assertFalse(valid)
        self.assertEqual(indices, [0])
        self.assertIn("Structured response marker", reasons[0])


if __name__ == "__main__":
    unittest.main()
