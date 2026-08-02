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

ALL_ON = {"literal_line1_lowconf": True}
ALL_OFF = {"literal_line1_lowconf": False}


class TestSplitSource(unittest.TestCase):
    def test_split_source_cases(self):
        cases = [
            (
                "enabled low confidence",
                "市民\nおはよう\n元気？",
                "literal_line1_lowconf",
                ALL_ON,
                ("", "市民", "おはよう\n元気？"),
            ),
            (
                "enabled high confidence",
                "セルリア\nふふふ",
                "literal_line1",
                ALL_ON,
                ("", "セルリア", "ふふふ"),
            ),
            (
                "disabled low confidence",
                "市民\nおはよう",
                "literal_line1_lowconf",
                ALL_OFF,
                None,
            ),
            (
                "high confidence ignores toggle",
                "セルリア\nふふふ",
                "literal_line1",
                ALL_OFF,
                ("", "セルリア", "ふふふ"),
            ),
            ("missing body", "市民", "literal_line1", ALL_ON, None),
            (
                "window option prefix",
                "@2\n市民\nおはよう",
                "literal_line1",
                ALL_ON,
                ("@2\n", "市民", "おはよう"),
            ),
        ]
        cases.extend(
            (f"unsupported {source_type}", "市民\nおはよう", source_type, ALL_ON, None)
            for source_type in ("narration", "ui", "choice", "string_var", "")
        )
        for label, source, source_type, config, expected in cases:
            with self.subTest(label):
                self.assertEqual(
                    ws.split_source(source, source_type, config),
                    expected,
                )


class TestPrefixedRoundTrip(unittest.TestCase):
    def test_to_prefixed(self):
        self.assertEqual(ws.to_prefixed("市民", "おはよう"), "[市民]: おはよう")

    def test_parse_prefixed_cases(self):
        cases = (
            ("single line", "[Citizen]: Good morning", ("Citizen", "Good morning")),
            ("multiline", "[Celria]: Wave.\nSmile.", ("Celria", "Wave.\nSmile.")),
            ("no prefix", "Just narration", (None, "Just narration")),
        )
        for label, text, expected in cases:
            with self.subTest(label):
                self.assertEqual(ws.parse_prefixed(text), expected)

    def test_restore_source_cases(self):
        cases = (
            ("plain", "", "Citizen", "Good morning", "Citizen\nGood morning"),
            ("window prefix", "@2\n", "Citizen", "Hi", "@2\nCitizen\nHi"),
        )
        for label, prefix, speaker, body, expected in cases:
            with self.subTest(label):
                self.assertEqual(ws.restore_source(prefix, speaker, body), expected)

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
                ws.save_config({"literal_line1_lowconf": False})
                self.assertFalse(ws.load_config()["literal_line1_lowconf"])
                ws.save_config({"literal_line1_lowconf": True})
                self.assertTrue(ws.load_config()["literal_line1_lowconf"])
        finally:
            ws.CONFIG_PATH = orig


if __name__ == "__main__":
    unittest.main(verbosity=2)
