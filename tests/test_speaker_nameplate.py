#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for RPG Maker speaker nameplate normalization."""

import unittest

from modules.rpgmakermvmz import _normalize_speaker_nameplate


class SpeakerNameplateNormalizeTests(unittest.TestCase):
    def test_normalizes_speaker_nameplate_cases(self):
        cases = (
            ("title case", "clerk", "Clerk"),
            ("speaker prefix", "Speaker: Townsman", "Townsman"),
            (
                "descriptive sentence",
                "Just your average electrician guy, the kind you'd find anywhere.",
                "Electrician Guy",
            ),
            (
                "long phrase",
                "ELECTRICIAN GUY FROM NEXT DOOR SHOP",
                "Electrician Guy From",
            ),
            ("ma'am casing", "ma'am", "Ma'am"),
        )
        for label, raw, expected in cases:
            with self.subTest(label):
                self.assertEqual(_normalize_speaker_nameplate(raw), expected)


if __name__ == "__main__":
    unittest.main()
