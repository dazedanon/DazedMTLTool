"""Tests for util.vocab (game-specific glossary helpers)."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import util.vocab as vocab


class TestUpdateVocabSection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vocab_path = Path(self.tmp.name) / "vocab.txt"
        self.base_path = Path(self.tmp.name) / "vocab_base.txt"
        self.base_path.write_text("# Base\nhello (hello)\n", encoding="utf-8")
        self.vocab_path.write_text(
            "# Game Characters\nAlice (Alice)\n\n"
            + vocab.BASE_SEPARATOR
            + "# Base\nhello (hello)\n",
            encoding="utf-8",
        )

        self._p_vocab = patch.object(vocab, "VOCAB_PATH", self.vocab_path)
        self._p_base = patch.object(vocab, "VOCAB_BASE_PATH", self.base_path)
        self._p_vocab.start()
        self._p_base.start()

    def tearDown(self):
        self._p_vocab.stop()
        self._p_base.stop()
        self.tmp.cleanup()

    def test_inserts_section_above_base_separator(self):
        vocab.update_vocab_section("Weapon · 武器", [("剣", "Sword")])

        text = self.vocab_path.read_text(encoding="utf-8")
        self.assertIn("# Weapon · 武器\n剣 (Sword)", text)
        self.assertIn(vocab.BASE_SEPARATOR, text)
        self.assertIn("# Base\nhello (hello)", text)
        # Game section must precede the base separator.
        self.assertLess(text.index("# Weapon · 武器"), text.index(vocab.BASE_SEPARATOR))

    def test_replaces_existing_section(self):
        vocab.update_vocab_section("Game Characters", [("Bob (Bob)", "Robert")])
        vocab.update_vocab_section("Game Characters", [("Alice", "Alicia")])

        text = self.vocab_path.read_text(encoding="utf-8")
        self.assertIn("Alice (Alicia)", text)
        self.assertNotIn("Bob (Robert)", text)
        self.assertEqual(text.count("# Game Characters"), 1)

    def test_skips_noop_pairs(self):
        before = self.vocab_path.read_text(encoding="utf-8")
        vocab.update_vocab_section("Items", [("Potion", "Potion"), ("", "X")])
        after = self.vocab_path.read_text(encoding="utf-8")
        self.assertEqual(before, after)

    def test_dedupes_by_source_last_wins(self):
        vocab.update_vocab_section("Skill · 技能", [("ヒール", "Heal"), ("ヒール", "Cure")])

        text = self.vocab_path.read_text(encoding="utf-8")
        self.assertIn("ヒール (Cure)", text)
        self.assertNotIn("ヒール (Heal)", text)


if __name__ == "__main__":
    unittest.main()
