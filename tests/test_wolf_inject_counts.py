#!/usr/bin/env python3
"""Unit tests for WolfDawn inject stdout parsers."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from util import wolfdawn  # noqa: E402


class WolfInjectCountsTests(unittest.TestCase):
    def test_parse_names_inject_counts(self):
        out = (
            "applied 2336 name change(s) (0 drifted/unmatched); "
            "wrote 78 file(s) in place\n"
            "WARNING: 2 line(s) left UNTRANSLATED by a safety guard\n"
        )
        applied, drifted = wolfdawn.parse_names_inject_counts(out)
        self.assertEqual(applied, 2336)
        self.assertEqual(drifted, 0)
        self.assertTrue(wolfdawn.inject_had_applied(applied))

    def test_parse_names_inject_dry_run_counts(self):
        out = "would apply 0 name change(s) (0 drifted/unmatched); dry run — did NOT write"
        applied, drifted = wolfdawn.parse_names_inject_counts(out)
        self.assertEqual(applied, 0)
        self.assertEqual(drifted, 0)
        self.assertFalse(wolfdawn.inject_had_applied(applied))

    def test_parse_strings_inject_counts(self):
        out = "applied 91 translation(s) (3 drifted); wrote Map001.mps\n"
        applied, drifted = wolfdawn.parse_strings_inject_counts(out)
        self.assertEqual(applied, 91)
        self.assertEqual(drifted, 3)

    def test_parse_strings_inject_counts_with_untranslated_on_stderr(self):
        stderr = (
            "event 374 cmd 233 str 0: control-code mismatch - source has [\"\\\\^\"], "
            "translation has [\"\\\\ \"]\n"
            "applied 24547 translation(s) (37 untranslated, 0 drifted); wrote CommonEvent.dat\n"
            "WARNING: 1 line(s) left UNTRANSLATED by a safety guard - "
            "1 control-code mismatch, 0 not encodable\n"
        )
        applied, drifted = wolfdawn.parse_strings_inject_counts("", stderr)
        self.assertEqual(applied, 24547)
        self.assertEqual(drifted, 0)
        self.assertEqual(wolfdawn.parse_strings_inject_untranslated("", stderr), 37)
        self.assertEqual(wolfdawn.parse_strings_inject_safety_count("", stderr), 1)
        mismatches = wolfdawn.parse_strings_inject_mismatches("", stderr)
        self.assertEqual(len(mismatches), 1)
        self.assertIn("control-code mismatch", mismatches[0])

    def test_inject_had_applied_rejects_zero(self):
        self.assertFalse(wolfdawn.inject_had_applied(0))
        self.assertFalse(wolfdawn.inject_had_applied(None))

    def test_parse_inject_cli_error(self):
        err = wolfdawn.parse_inject_cli_error(
            "", "strings-inject: cannot read input or DB pair\n"
        )
        self.assertEqual(err, "cannot read input or DB pair")

    def test_db_dat_sibling(self):
        self.assertEqual(
            wolfdawn.db_dat_sibling("BasicData/DataBase.project").name,
            "DataBase.dat",
        )


if __name__ == "__main__":
    unittest.main()
