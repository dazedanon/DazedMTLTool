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


if __name__ == "__main__":
    unittest.main()
