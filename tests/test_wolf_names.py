#!/usr/bin/env python3
"""Unit tests for the WOLF names safe-note config in util/wolf_names.py."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from util import wolf_names as wn  # noqa: E402


class TestSafeNotesIO(unittest.TestCase):
    def setUp(self):
        self._orig = wn.SAFE_NOTES_PATH
        self._tmp = tempfile.TemporaryDirectory()
        wn.SAFE_NOTES_PATH = Path(self._tmp.name) / "wolf_safe_notes.json"

    def tearDown(self):
        wn.SAFE_NOTES_PATH = self._orig
        self._tmp.cleanup()

    def test_default_is_empty(self):
        self.assertEqual(wn.load_safe_notes(), [])

    def test_round_trip_preserves_order_and_unicode(self):
        wn.save_safe_notes(["武器", "技能", "アイテム"])
        self.assertEqual(wn.load_safe_notes(), ["武器", "技能", "アイテム"])

    def test_save_dedupes(self):
        wn.save_safe_notes(["武器", "武器", "技能"])
        self.assertEqual(wn.load_safe_notes(), ["武器", "技能"])

    def test_ignores_non_list_payload(self):
        wn.SAFE_NOTES_PATH.write_text('{"武器": true}', encoding="utf-8")
        self.assertEqual(wn.load_safe_notes(), [])


class TestIsNoteSafe(unittest.TestCase):
    def test_membership(self):
        safe = ["武器", "技能"]
        self.assertTrue(wn.is_note_safe("武器", safe))
        self.assertFalse(wn.is_note_safe("通常変数名", safe))

    def test_empty_list_is_never_safe(self):
        self.assertFalse(wn.is_note_safe("武器", []))
        self.assertFalse(wn.is_note_safe("", []))


if __name__ == "__main__":
    unittest.main()
