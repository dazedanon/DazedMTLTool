#!/usr/bin/env python3
"""Regression tests for deterministic RPG Maker speaker glossary handling."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import modules.rpgmakermvmz as mvmz
from util.translation import buildMatchedVocabText, parseVocabWithCategories


VOCAB = (
    "# Game Characters\n"
    "ユウ (Yuu) - Male protagonist.\n"
    "ハルカ (Haruka) - Female heroine.\n\n"
    "# Terms\n"
    "教室 (Classroom)\n"
)


class MVMZSpeakerVocabTests(unittest.TestCase):
    def setUp(self):
        self.original_vocab = mvmz.VOCAB
        self.original_config_vocab = mvmz.TRANSLATION_CONFIG.vocab
        self.original_names = mvmz.NAMESLIST
        self.original_collected = mvmz.SPEAKER_COLLECTED
        self.original_parse_mode = mvmz.SPEAKER_PARSE_MODE
        self.original_preflight = mvmz.PREFLIGHT_COUNT_MODE
        mvmz.VOCAB = VOCAB
        mvmz.NAMESLIST = []
        mvmz.SPEAKER_COLLECTED = []
        mvmz.SPEAKER_PARSE_MODE = False
        mvmz.PREFLIGHT_COUNT_MODE = False
        with mvmz._speakerCacheLock:
            mvmz._speakerCache.clear()

    def tearDown(self):
        mvmz.VOCAB = self.original_vocab
        mvmz.TRANSLATION_CONFIG.vocab = self.original_config_vocab
        mvmz.NAMESLIST = self.original_names
        mvmz.SPEAKER_COLLECTED = self.original_collected
        mvmz.SPEAKER_PARSE_MODE = self.original_parse_mode
        mvmz.PREFLIGHT_COUNT_MODE = self.original_preflight
        with mvmz._speakerCacheLock:
            mvmz._speakerCache.clear()

    def test_exact_vocab_name_bypasses_model_and_stale_cache(self):
        with mvmz._speakerCacheLock:
            mvmz._speakerCache["ユウ"] = "Yu"

        with patch.object(mvmz, "translateAI") as translate:
            result = mvmz.getSpeaker("ユウ")

        self.assertEqual(result, ["Yuu", [0, 0]])
        translate.assert_not_called()

    def test_character_name_is_substituted_inside_compound_label(self):
        def translate(text, _context, _batch=False):
            self.assertEqual(text, "Yuuイベント5")
            return ["Yuu Event 5", [3, 2]]

        with patch.object(mvmz, "translateAI", side_effect=translate):
            result = mvmz.getSpeaker("ユウイベント5")

        self.assertEqual(result, ["Yuu Event 5", [3, 2]])

    def test_game_characters_override_generated_speaker_spelling(self):
        mvmz.VOCAB = (
            "# Game Characters\nユウ (Yuu) - Male protagonist.\n\n"
            "# Speakers\nユウ (Yu)\n"
        )

        with patch.object(mvmz, "translateAI") as translate:
            result = mvmz.getSpeaker("ユウ")

        self.assertEqual(result, ["Yuu", [0, 0]])
        translate.assert_not_called()

    def test_reload_vocab_updates_translation_config(self):
        with TemporaryDirectory() as tmp:
            vocab_path = Path(tmp) / "vocab.txt"
            vocab_path.write_text("# Game Characters\nユウ (You)\n", encoding="utf-8")
            with patch.object(mvmz, "VOCAB_PATH", vocab_path):
                mvmz._reload_vocab()

        self.assertIn("ユウ (You)", mvmz.VOCAB)
        self.assertEqual(mvmz.TRANSLATION_CONFIG.vocab, mvmz.VOCAB)

    def test_parse_speakers_reuses_curated_name(self):
        mvmz.SPEAKER_PARSE_MODE = True
        mvmz.SPEAKER_COLLECTED = ["ユウ"]
        with TemporaryDirectory() as tmp:
            vocab_path = Path(tmp) / "vocab.txt"
            vocab_path.write_text(VOCAB, encoding="utf-8")
            with (
                patch.object(mvmz, "VOCAB_PATH", vocab_path),
                patch.object(mvmz, "translateAI") as translate,
            ):
                mvmz.finalizeSpeakerParse()
            written = vocab_path.read_text(encoding="utf-8")

        translate.assert_not_called()
        self.assertIn("# Speakers\nユウ (Yuu)", written)


class CharacterCompoundMatchingTests(unittest.TestCase):
    def test_character_entry_matches_inside_katakana_compound(self):
        pairs = parseVocabWithCategories(VOCAB)
        matched = buildMatchedVocabText(pairs, "ユウイベント5")

        self.assertIn("Here are glossary entries", matched)
        self.assertNotIn("Here are some vocabulary", matched)
        self.assertIn("ユウ (Yuu)", matched)

    def test_non_character_short_term_keeps_script_boundaries(self):
        pairs = parseVocabWithCategories("# Terms\nキス (Kiss)\n")
        matched = buildMatchedVocabText(pairs, "テキスト")

        self.assertEqual(matched, "")

    def test_curated_character_spelling_suppresses_generated_conflict(self):
        pairs = parseVocabWithCategories(
            "# Game Characters\nユウ (Yuu)\n\n# Speakers\nユウ (Yu)\n"
        )
        matched = buildMatchedVocabText(pairs, "ユウイベント5")

        self.assertIn("ユウ (Yuu)", matched)
        self.assertNotIn("ユウ (Yu)", matched)


if __name__ == "__main__":
    unittest.main()
