#!/usr/bin/env python3
"""Regression tests for shared DazedWrap control-code handling."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

import util.dazedwrap as dazedwrap  # noqa: E402


class TestDazedWrapControlCodes(unittest.TestCase):
    def test_shadow_codes_do_not_count_toward_visible_width(self):
        self.assertEqual(dazedwrap._get_visible_length(r"\SHADOW[3]alpha"), 5)
        self.assertEqual(dazedwrap._get_visible_length(r"\\SHADOW[3]alpha"), 5)

    def test_doubled_shadow_code_does_not_hide_first_visible_character(self):
        text = r"\\SHADOW[3]alpha beta"

        wrapped = dazedwrap.wrapText(text, width=9)

        self.assertEqual(wrapped, "\\\\SHADOW[3]alpha\nbeta")


if __name__ == "__main__":
    unittest.main()
