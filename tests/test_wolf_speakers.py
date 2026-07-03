#!/usr/bin/env python3
"""Unit tests for the WOLF first-line speaker reshaping in util/speakers.py."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from util import speakers as ws  # noqa: E402

ALL_ON = {"literal_line1": True, "literal_line1_lowconf": True}
ALL_OFF = {"literal_line1": False, "literal_line1_lowconf": False}


class TestSplitSource(unittest.TestCase):
    def test_splits_lowconf_when_enabled(self):
        out = ws.split_source("市民\nおはよう\n元気？", "literal_line1_lowconf", ALL_ON)
        self.assertEqual(out, ("", "市民", "おはよう\n元気？"))

    def test_splits_highconf_when_enabled(self):
        out = ws.split_source("セルリア\nふふふ", "literal_line1", ALL_ON)
        self.assertEqual(out, ("", "セルリア", "ふふふ"))

    def test_disabled_format_returns_none(self):
        self.assertIsNone(ws.split_source("市民\nおはよう", "literal_line1_lowconf", ALL_OFF))

    def test_non_firstline_src_returns_none(self):
        for src in ("narration", "ui", "choice", "string_var", ""):
            self.assertIsNone(ws.split_source("市民\nおはよう", src, ALL_ON))

    def test_no_body_returns_none(self):
        self.assertIsNone(ws.split_source("市民", "literal_line1", ALL_ON))

    def test_preserves_window_option_prefix(self):
        out = ws.split_source("@2\n市民\nおはよう", "literal_line1", ALL_ON)
        self.assertEqual(out, ("@2\n", "市民", "おはよう"))


class TestPrefixedRoundTrip(unittest.TestCase):
    def test_to_prefixed(self):
        self.assertEqual(ws.to_prefixed("市民", "おはよう"), "[市民]: おはよう")

    def test_parse_prefixed(self):
        self.assertEqual(ws.parse_prefixed("[Citizen]: Good morning"), ("Citizen", "Good morning"))

    def test_parse_prefixed_multiline_body(self):
        spk, body = ws.parse_prefixed("[Celria]: Wave.\nSmile.")
        self.assertEqual(spk, "Celria")
        self.assertEqual(body, "Wave.\nSmile.")

    def test_parse_prefixed_no_prefix(self):
        self.assertEqual(ws.parse_prefixed("Just narration"), (None, "Just narration"))

    def test_restore_source(self):
        self.assertEqual(ws.restore_source("", "Citizen", "Good morning"), "Citizen\nGood morning")

    def test_restore_source_with_window_prefix(self):
        self.assertEqual(
            ws.restore_source("@2\n", "Citizen", "Hi"), "@2\nCitizen\nHi"
        )

    def test_full_round_trip_structure_preserved(self):
        source = "市民\nおはよう\n元気？"
        prefix, speaker, body = ws.split_source(source, "literal_line1_lowconf", ALL_ON)
        transport = ws.to_prefixed(speaker, body)
        self.assertEqual(transport, "[市民]: おはよう\n元気？")
        # Simulate a translation that keeps the [Speaker]: format.
        spk_en, body_en = ws.parse_prefixed("[Citizen]: Morning\nDoing well?")
        restored = ws.restore_source(prefix, spk_en, body_en)
        self.assertEqual(restored, "Citizen\nMorning\nDoing well?")
        # Same number of newlines as the original layout (speaker on its own line).
        self.assertEqual(source.count("\n"), restored.count("\n"))


class TestConfigIO(unittest.TestCase):
    def test_load_defaults_when_missing(self):
        orig = ws.CONFIG_PATH
        try:
            ws.CONFIG_PATH = ROOT / "tests" / "_nonexistent_wolf_speakers.json"
            self.assertEqual(ws.load_config(), ws.DEFAULT_CONFIG)
        finally:
            ws.CONFIG_PATH = orig

    def test_save_and_load_roundtrip(self):
        import tempfile

        orig = ws.CONFIG_PATH
        try:
            with tempfile.TemporaryDirectory() as td:
                ws.CONFIG_PATH = Path(td) / "wolf_speakers.json"
                ws.save_config({"literal_line1": False, "literal_line1_lowconf": True})
                loaded = ws.load_config()
                self.assertFalse(loaded["literal_line1"])
                self.assertTrue(loaded["literal_line1_lowconf"])
        finally:
            ws.CONFIG_PATH = orig


if __name__ == "__main__":
    unittest.main(verbosity=2)
