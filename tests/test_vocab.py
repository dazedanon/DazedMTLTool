"""Tests for util.vocab (game-specific glossary helpers)."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import util.vocab as vocab
import util.paths as paths
from util.game_settings import load_translation_runtime_environment
from util.skills import game_skill_path_for_game, load_system_prompt


class TestGameGlossaryPaths(unittest.TestCase):
    def setUp(self):
        self._legacy_global = tempfile.TemporaryDirectory()
        self._legacy_global_patch = patch.object(
            paths,
            "LEGACY_GLOBAL_GLOSSARY_PATH",
            Path(self._legacy_global.name) / "missing-vocab.txt",
        )
        self._legacy_global_patch.start()

    def tearDown(self):
        self._legacy_global_patch.stop()
        self._legacy_global.cleanup()

    def test_each_game_gets_independent_portable_translation_files(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            base = root / "glossary_base.txt"
            base.write_text("# Base\nさん (san)\n", encoding="utf-8")
            game_a = root / "Game A"
            game_b = root / "Game B"
            game_a.mkdir()
            game_b.mkdir()
            legacy_glossary = game_a / "glossary.txt"
            legacy_glossary.write_text("Alice (Alice)\n", encoding="utf-8")
            legacy_skill = game_a / "skills" / "game.md"
            legacy_skill.parent.mkdir()
            legacy_skill.write_text("# Translation Frame\n", encoding="utf-8")
            legacy_skill.with_name("quirks.md").write_text(
                "- Keep Alice formal.\n", encoding="utf-8"
            )
            legacy_skill.with_name("battle.md").write_text(
                "Keep battle labels terse.\n", encoding="utf-8"
            )

            with patch.object(paths, "glossary_base_path", return_value=base):
                path_a = paths.ensure_game_glossary(game_a)
                path_b = paths.ensure_game_glossary(game_b)

            skill_a = game_skill_path_for_game(game_a)
            self.assertEqual(path_a.relative_to(game_a), Path(".dazedtl/glossary.txt"))
            self.assertEqual(path_b.relative_to(game_b), Path(".dazedtl/glossary.txt"))
            self.assertEqual(
                skill_a.relative_to(game_a), Path(".dazedtl/skills/game.md")
            )
            self.assertFalse(legacy_glossary.exists())
            self.assertFalse(legacy_skill.parent.exists())
            self.assertIn("Alice", path_a.read_text(encoding="utf-8"))
            self.assertIn("Translation Frame", skill_a.read_text(encoding="utf-8"))
            prompt = load_system_prompt(game_a)
            self.assertIn("Keep Alice formal.", prompt)
            self.assertIn("Keep battle labels terse.", prompt)
            self.assertIn("さん (san)", path_b.read_text(encoding="utf-8"))
            self.assertNotIn("Alice", path_b.read_text(encoding="utf-8"))

            conflict = root / "Conflict"
            conflict.joinpath(".dazedtl").mkdir(parents=True)
            conflict.joinpath("glossary.txt").write_text("old\n", encoding="utf-8")
            conflict.joinpath(".dazedtl/glossary.txt").write_text(
                "new\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(paths.GameProjectPathError, "Both the legacy"):
                paths.game_glossary_path(conflict)

            duplicate = root / "Identical Duplicate"
            duplicate.joinpath(".dazedtl").mkdir(parents=True)
            duplicate.joinpath("glossary.txt").write_text(
                "Alice (Alice)\n", encoding="utf-8"
            )
            duplicate.joinpath(".dazedtl/glossary.txt").write_text(
                "Alice (Alice)\n", encoding="utf-8"
            )

            resolved = paths.prepare_game_translation_context(duplicate)

            self.assertEqual(resolved, duplicate / ".dazedtl/glossary.txt")
            self.assertEqual(
                resolved.read_text(encoding="utf-8"), "Alice (Alice)\n"
            )
            self.assertFalse(duplicate.joinpath("glossary.txt").exists())

            preview_game = root / "Preview"
            preview_game.mkdir()
            preview_legacy = preview_game / "glossary.txt"
            preview_legacy.write_text("Preview (Preview)\n", encoding="utf-8")
            self.assertIn(
                "Preview (Preview)",
                vocab.read_game_vocab(preview_game, create=False),
            )
            self.assertTrue(preview_legacy.is_file())
            self.assertFalse(preview_game.joinpath(".gitignore").exists())
            self.assertFalse(
                preview_game.joinpath(".dazedtl", "glossary.txt").exists()
            )

            outside = root / "outside.md"
            outside.write_text("External prompt content\n", encoding="utf-8")
            custom_link = game_a / ".dazedtl" / "skills" / "linked.md"
            custom_link.symlink_to(outside)
            with self.assertRaisesRegex(
                paths.GameProjectPathError, "not a regular file"
            ):
                load_system_prompt(game_a)

    def test_context_preparation_never_leaves_partial_guidance_moves(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)

            conflict = root / "Preflight Conflict"
            conflict.joinpath("skills").mkdir(parents=True)
            conflict.joinpath("skills", "game.md").write_text(
                "legacy skill\n", encoding="utf-8"
            )
            conflict.joinpath("glossary.txt").write_text(
                "legacy glossary\n", encoding="utf-8"
            )
            conflict.joinpath(".dazedtl").mkdir()
            conflict.joinpath(".dazedtl", "glossary.txt").write_text(
                "portable glossary\n", encoding="utf-8"
            )

            with self.assertRaises(paths.GameProjectPathError):
                paths.prepare_game_translation_context(conflict)
            self.assertTrue(conflict.joinpath("skills", "game.md").is_file())
            self.assertFalse(conflict.joinpath(".dazedtl", "skills").exists())

            rollback = root / "Rename Failure"
            rollback.joinpath("skills").mkdir(parents=True)
            rollback.joinpath("skills", "translation.md").write_text(
                "legacy skill\n", encoding="utf-8"
            )
            rollback.joinpath("translation_quirks.txt").write_text(
                "legacy quirks\n", encoding="utf-8"
            )
            rollback.joinpath("glossary.txt").write_text(
                "legacy glossary\n", encoding="utf-8"
            )
            original_rename = Path.rename

            def fail_quirks_move(source, target):
                if source == rollback / "translation_quirks.txt":
                    raise OSError("simulated rename failure")
                return original_rename(source, target)

            with (
                patch.object(Path, "rename", fail_quirks_move),
                self.assertRaisesRegex(
                    paths.GameProjectPathError, "simulated rename failure"
                ),
            ):
                paths.prepare_game_translation_context(rollback)

            self.assertTrue(rollback.joinpath("glossary.txt").is_file())
            self.assertTrue(rollback.joinpath("skills", "translation.md").is_file())
            self.assertTrue(rollback.joinpath("translation_quirks.txt").is_file())
            self.assertFalse(rollback.joinpath(".dazedtl", "glossary.txt").exists())
            self.assertFalse(rollback.joinpath(".dazedtl", "skills").exists())

    def test_subprocess_environment_restores_portable_widths_after_dotenv(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            game = root / "Game"
            game.joinpath(".dazedtl").mkdir(parents=True)
            game.joinpath(".dazedtl", "settings.json").write_text(
                '{"rpgmaker":{"wrapWidths":{'
                '"width":81,"faceWidth":67,"listWidth":103,"noteWidth":92}}}',
                encoding="utf-8",
            )
            env_file = root / "global.env"
            env_file.write_text(
                "DAZED_GAME_ROOT=/stale/dotenv/game\n"
                "width=44\nfaceWidth=40\nlistWidth=70\nnoteWidth=65\n",
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {"DAZED_GAME_ROOT": str(game)},
                clear=False,
            ):
                loaded = load_translation_runtime_environment(env_file)
                self.assertEqual(
                    loaded,
                    {
                        "width": 81,
                        "faceWidth": 67,
                        "listWidth": 103,
                        "noteWidth": 92,
                    },
                )
                self.assertEqual(os.environ["width"], "81")
                self.assertEqual(os.environ["faceWidth"], "67")
                self.assertEqual(os.environ["DAZED_GAME_ROOT"], str(game))

    def test_legacy_game_vocab_is_copied_and_preserved_as_backup(self):
        with tempfile.TemporaryDirectory() as raw:
            game = Path(raw)
            legacy = game / "vocab.txt"
            legacy.write_text(
                "# Game Characters\nユウ (Yuu)\n\n"
                + paths.LEGACY_GLOSSARY_BASE_SEPARATOR
                + "# Base\nさん (san)\n",
                encoding="utf-8",
            )

            preview = vocab.read_game_vocab(game, create=False)

            self.assertIn("ユウ (Yuu)", preview)
            self.assertFalse(game.joinpath("glossary.txt").exists())

            glossary = paths.ensure_game_glossary(game)

            self.assertTrue(legacy.exists())
            self.assertTrue(glossary.is_file())
            self.assertIn("ユウ (Yuu)", vocab.read_game_vocab(game))

    def test_unmarked_game_vocab_is_not_treated_as_dazedtl_data(self):
        with tempfile.TemporaryDirectory() as raw:
            game = Path(raw)
            legacy = game / "vocab.txt"
            legacy.write_text("game-owned vocabulary\n", encoding="utf-8")
            base = game / "base.txt"
            base.write_text("# Base\nさん (san)\n", encoding="utf-8")

            with patch.object(paths, "glossary_base_path", return_value=base):
                glossary = paths.ensure_game_glossary(game)

            self.assertEqual(
                legacy.read_text(encoding="utf-8"),
                "game-owned vocabulary\n",
            )
            self.assertIn("さん (san)", glossary.read_text(encoding="utf-8"))
            self.assertNotIn(
                "game-owned vocabulary", glossary.read_text(encoding="utf-8")
            )

    def test_global_legacy_vocab_seeds_new_game_with_current_base(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            game = root / "Game"
            game.mkdir()
            legacy = root / "data" / "vocab.txt"
            legacy.parent.mkdir()
            legacy.write_text(
                "# Characters\n勇者 (Hero)\n\n"
                + paths.LEGACY_GLOSSARY_BASE_SEPARATOR
                + "outdated base\n",
                encoding="utf-8",
            )
            current_base = root / "glossary_base.txt"
            current_base.write_text("さん (san)\n", encoding="utf-8")

            with (
                patch.object(paths, "LEGACY_GLOBAL_GLOSSARY_PATH", legacy),
                patch.object(paths, "glossary_base_path", return_value=current_base),
            ):
                glossary = paths.ensure_game_glossary(game)

            text = glossary.read_text(encoding="utf-8")
            self.assertIn("勇者 (Hero)", text)
            self.assertIn("さん (san)", text)
            self.assertNotIn("outdated base", text)
            self.assertTrue(legacy.exists())


class TestUpdateVocabSection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vocab_path = Path(self.tmp.name) / ".dazedtl" / "glossary.txt"
        self.base_path = Path(self.tmp.name) / "glossary_base.txt"
        self.freeze_path = Path(self.tmp.name) / "batch_glossary_freeze.txt"
        self.vocab_path.parent.mkdir()
        self.base_path.write_text("# Base\nhello (hello)\n", encoding="utf-8")
        self.vocab_path.write_text(
            "# Game Characters\nAlice (Alice)\n\n"
            + vocab.BASE_SEPARATOR
            + "# Base\nhello (hello)\n",
            encoding="utf-8",
        )

        self._p_base = patch.object(vocab, "glossary_base_path", return_value=self.base_path)
        self._p_freeze = patch.object(
            vocab, "BATCH_GLOSSARY_FREEZE_FILE", self.freeze_path
        )
        self._p_base.start()
        self._p_freeze.start()

    def tearDown(self):
        self._p_freeze.stop()
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
        vocab.update_vocab_section(
            "Skill · 技能",
            [
                ("ヒール", "Heal"),
                ("ヒール", "Cure"),
                ("▼ルドゥレンス", "▼Ludurens"),
                ("※注意", "※Note"),
                ("カフェ", "Café"),
                ("成功率%", "Success Rate %"),
            ],
            game_root=self.tmp.name,
        )

        text = self.vocab_path.read_text(encoding="utf-8")
        self.assertIn("ヒール (Cure)", text)
        self.assertNotIn("ヒール (Heal)", text)
        self.assertIn("ルドゥレンス (Ludurens)", text)
        self.assertIn("注意 (Note)", text)
        self.assertIn("カフェ (Café)", text)
        self.assertIn("成功率% (Success Rate %)", text)
        self.assertNotIn("▼", text)
        self.assertNotIn("※", text)

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

    def test_batch_consume_writes_glossary_immediately(self):
        """Sequential Pass 2 writes harvests so later files can load them."""
        with patch.dict(os.environ, {"BATCH_PHASE": "consume"}):
            vocab.update_vocab_section(
                "Armors", [("ミサンガ", "Friendship Bracelet")], game_root=self.tmp.name
            )
        after = self.vocab_path.read_text(encoding="utf-8")
        self.assertIn("# Armors\nミサンガ (Friendship Bracelet)", after)

    def test_batch_collect_skips_glossary_writes(self):
        before = self.vocab_path.read_text(encoding="utf-8")
        with patch.dict(os.environ, {"BATCH_PHASE": "collect"}):
            vocab.update_vocab_section(
                "Armors", [("ミサンガ", "Friendship Bracelet")], game_root=self.tmp.name
            )
        self.assertEqual(before, self.vocab_path.read_text(encoding="utf-8"))

    def test_batch_glossary_freeze_is_used_for_translation_reads(self):
        """Collect still pins to the freeze; consume reads live harvests."""
        vocab.clear_batch_glossary_freeze()
        self.vocab_path.write_text(
            "# Game Characters\nカイン (Cain)\n",
            encoding="utf-8",
        )
        with patch("util.vocab.read_active_glossary", return_value=self.vocab_path.read_text(encoding="utf-8")):
            freeze_path = vocab.freeze_batch_glossary()
        self.assertTrue(freeze_path.is_file())
        self.assertIn("カイン (Cain)", freeze_path.read_text(encoding="utf-8"))

        self.vocab_path.write_text(
            "# Game Characters\nカイン (Cain)\n# Armors\n帽子 (Hat)\n",
            encoding="utf-8",
        )
        with patch.dict(os.environ, {"BATCH_PHASE": "collect"}):
            with patch(
                "util.vocab.read_active_glossary",
                return_value=self.vocab_path.read_text(encoding="utf-8"),
            ):
                frozen = vocab.read_translation_glossary()
        self.assertIn("カイン (Cain)", frozen)
        self.assertNotIn("# Armors", frozen)

        with patch.dict(os.environ, {"BATCH_PHASE": "consume"}):
            with patch(
                "util.vocab.read_active_glossary",
                return_value=self.vocab_path.read_text(encoding="utf-8"),
            ):
                live = vocab.read_translation_glossary()
        self.assertIn("# Armors", live)
        vocab.clear_batch_glossary_freeze()


if __name__ == "__main__":
    unittest.main()
