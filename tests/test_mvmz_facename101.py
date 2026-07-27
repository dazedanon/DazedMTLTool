#!/usr/bin/env python3
"""Regression tests for code-101 face filename speaker mappings."""

import unittest

import modules.rpgmakermvmz as mvmz


class FaceName101Tests(unittest.TestCase):
    def test_recurring_character_faces_resolve_to_speakers(self):
        expected = {
            "__HA": "Count Bampton",
            "___Nimurda": "Nimurda",
            "___Ren": "Ren",
            "___prince": "Prince Elliot",
            "___princess1": "Lilifa",
            "___princess2": "Lilifa",
            "___princess2_2": "Lilifa",
            "___princess3": "Lilifa",
            "___princess4": "Lilifa",
            "___princess5": "Lilifa",
            "__opHA": "Count Bampton",
            "__opRen": "Ren",
            "__opλ": "Lambda",
            "__λ": "Lambda",
        }

        for face_name, speaker in expected.items():
            with self.subTest(face_name=face_name):
                command = {"parameters": [face_name, 0, 0, 2, ""]}
                self.assertEqual(mvmz._facename101_speaker(command), speaker)

    def test_all_detected_face_filenames_are_mapped(self):
        detected = {
            "_Daijin",
            "__HA",
            "__Labyrinth",
            "___Nimurda",
            "___Ren",
            "___prince",
            "___princess1",
            "___princess2",
            "___princess2_2",
            "___princess3",
            "___princess4",
            "___princess5",
            "__opHA",
            "__opRen",
            "__opλ",
            "__λ",
            "_girl",
            "_guard_F",
            "_guard_M",
            "_guard_M1",
            "_guard_M10",
            "_king",
            "_knight",
            "_made1",
            "_made2",
            "_made3",
            "_queen",
            "_toy",
            "made2",
        }

        self.assertEqual(set(mvmz.FACENAME101_MAP), detected)

    def test_longest_prefix_wins_for_overlapping_face_names(self):
        command = {"parameters": ["___princess2_2_smile", 0, 0, 2, ""]}

        self.assertEqual(mvmz._facename101_speaker(command), "Lilifa")

    def test_explicit_code101_name_takes_precedence(self):
        command = {"parameters": ["___prince", 1, 0, 2, "リリファ"]}

        self.assertIsNone(mvmz._facename101_speaker(command))


if __name__ == "__main__":
    unittest.main()
