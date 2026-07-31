"""Tests for util.vocab (game-specific glossary helpers)."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import util.vocab as vocab
import util.paths as paths


class TestGameGlossaryPaths(unittest.TestCase):
    def test_each_game_gets_an_independent_seeded_glossary(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            base = root / "glossary_base.txt"
            base.write_text("# Base\nさん (san)\n", encoding="utf-8")
            game_a = root / "Game A"
            game_b = root / "Game B"
            game_a.mkdir()
            game_b.mkdir()

            with patch.object(paths, "glossary_base_path", return_value=base):
                path_a = paths.ensure_game_glossary(game_a)
                path_b = paths.ensure_game_glossary(game_b)

            path_a.write_text("Alice (Alice)\n", encoding="utf-8")
            self.assertEqual(path_a.name, "glossary.txt")
            self.assertEqual(path_b.name, "glossary.txt")
            self.assertIn("さん (san)", path_b.read_text(encoding="utf-8"))
            self.assertNotIn("Alice", path_b.read_text(encoding="utf-8"))

    def test_legacy_game_vocab_is_migrated_and_preserved(self):
        with tempfile.TemporaryDirectory() as raw:
            game = Path(raw)
            legacy = game / "vocab.txt"
            legacy.write_text(
                "# Game Characters\nユウ (Yuu)\n\n"
                + paths.LEGACY_GLOSSARY_BASE_SEPARATOR
                + "# Base\nさん (san)\n",
                encoding="utf-8",
            )

            glossary = paths.ensure_game_glossary(game)

            self.assertFalse(legacy.exists())
            self.assertTrue(glossary.is_file())
            self.assertIn("ユウ (Yuu)", vocab.read_game_vocab(game))


class TestUpdateVocabSection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vocab_path = Path(self.tmp.name) / "glossary.txt"
        self.base_path = Path(self.tmp.name) / "glossary_base.txt"
        self.base_path.write_text("# Base\nhello (hello)\n", encoding="utf-8")
        self.vocab_path.write_text(
            "# Game Characters\nAlice (Alice)\n\n"
            + vocab.BASE_SEPARATOR
            + "# Base\nhello (hello)\n",
            encoding="utf-8",
        )

        self._p_base = patch.object(vocab, "glossary_base_path", return_value=self.base_path)
        self._p_base.start()

    def tearDown(self):
        self._p_base.stop()
        self.tmp.cleanup()

    def test_inserts_section_above_base_separator(self):
        vocab.update_vocab_section("Weapon · 武器", [("剣", "Sword")], game_root=self.tmp.name)

        text = self.vocab_path.read_text(encoding="utf-8")
        self.assertIn("# Weapon · 武器\n剣 (Sword)", text)
        self.assertIn(vocab.BASE_SEPARATOR, text)
        self.assertIn("# Base\nhello (hello)", text)
        # Game section must precede the base separator.
        self.assertLess(text.index("# Weapon · 武器"), text.index(vocab.BASE_SEPARATOR))

    def test_replaces_existing_section(self):
        vocab.update_vocab_section("Game Characters", [("Bob (Bob)", "Robert")], game_root=self.tmp.name)
        vocab.update_vocab_section("Game Characters", [("Alice", "Alicia")], game_root=self.tmp.name)

        text = self.vocab_path.read_text(encoding="utf-8")
        self.assertIn("Alice (Alicia)", text)
        self.assertNotIn("Bob (Robert)", text)
        self.assertEqual(text.count("# Game Characters"), 1)

    def test_skips_noop_pairs(self):
        before = self.vocab_path.read_text(encoding="utf-8")
        vocab.update_vocab_section("Items", [("Potion", "Potion"), ("", "X")], game_root=self.tmp.name)
        after = self.vocab_path.read_text(encoding="utf-8")
        self.assertEqual(before, after)

    def test_dedupes_by_source_last_wins(self):
        vocab.update_vocab_section("Skill · 技能", [("ヒール", "Heal"), ("ヒール", "Cure")], game_root=self.tmp.name)

        text = self.vocab_path.read_text(encoding="utf-8")
        self.assertIn("ヒール (Cure)", text)
        self.assertNotIn("ヒール (Heal)", text)

    def test_merge_keeps_existing_and_adds_new(self):
        vocab.update_vocab_section("Map Setting · マップ設定", [("礼拝堂", "Chapel")], game_root=self.tmp.name)
        vocab.update_vocab_section(
            "Map Setting · マップ設定",
            [("礼拝堂", "Chapel Hall"), ("大通り", "Main Street")],
            merge=True,
            game_root=self.tmp.name,
        )

        text = self.vocab_path.read_text(encoding="utf-8")
        self.assertIn("礼拝堂 (Chapel)", text)
        self.assertNotIn("礼拝堂 (Chapel Hall)", text)
        self.assertIn("大通り (Main Street)", text)
        self.assertEqual(text.count("# Map Setting · マップ設定"), 1)


if __name__ == "__main__":
    unittest.main()
