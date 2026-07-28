#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for RPG Maker speaker nameplate normalization."""

import unittest

from modules.rpgmakermvmz import _normalize_speaker_nameplate


class SpeakerNameplateNormalizeTests(unittest.TestCase):
    def test_title_case_short_name(self):
        self.assertEqual(_normalize_speaker_nameplate("clerk"), "Clerk")

    def test_strips_speaker_prefix(self):
        self.assertEqual(_normalize_speaker_nameplate("Speaker: Townsman"), "Townsman")

    def test_collapses_descriptive_sentence(self):
        raw = "Just your average electrician guy, the kind you'd find anywhere."
        self.assertEqual(_normalize_speaker_nameplate(raw), "Electrician Guy")

    def test_truncates_long_phrase(self):
        self.assertEqual(
            _normalize_speaker_nameplate("ELECTRICIAN GUY FROM NEXT DOOR SHOP"),
            "Electrician Guy From",
        )

    def test_preserves_maam_casing(self):
        self.assertEqual(_normalize_speaker_nameplate("ma'am"), "Ma'am")


if __name__ == "__main__":
    unittest.main()
