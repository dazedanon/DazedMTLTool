import unittest

from util.speakers import (
    SPEAKER_TAG_RE,
    extract_dialogue_after_speaker,
    strip_speaker_prefix,
)


class SpeakerPrefixTests(unittest.TestCase):
    def test_strips_supported_speaker_prefixes(self):
        cases = (
            ("plain", "[Kurone]: Hello", "Hello"),
            (
                "color coded",
                r"[\C[10]Hp Drink\C[0]]: Received item!",
                "Received item!",
            ),
            (
                "fullwidth colon",
                r"[\C[10]HPドリンク\C[0]]：をもらった！",
                "をもらった！",
            ),
        )
        for label, line, expected in cases:
            with self.subTest(label):
                self.assertEqual(strip_speaker_prefix(line), expected)

    def test_tag_captures_color_coded_speaker(self):
        line = r"[\C[10]Hp Drink\C[0]]: 【\c[10]HPドリンク\c[0]】をもらった！"
        m = SPEAKER_TAG_RE.match(line)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), r"\C[10]Hp Drink\C[0]")

    def test_extract_dialogue_skips_color_speaker(self):
        line = r"[\C[10]Hp Drink\C[0]]: 【\c[10]HPドリンク\c[0]】をもらった！"
        self.assertEqual(
            extract_dialogue_after_speaker(line),
            "【\\c[10]HPドリンク\\c[0]】をもらった！",
        )

    def test_actor_variable_in_speaker(self):
        line = r"[\n[1]]: Actor line"
        m = SPEAKER_TAG_RE.match(line)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), r"\n[1]")
        self.assertEqual(extract_dialogue_after_speaker(line), "Actor line")


if __name__ == "__main__":
    unittest.main()
