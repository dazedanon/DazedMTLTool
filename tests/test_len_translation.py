"""Shared Len/Workflow guidance, conflict-safe imports, and project preservation."""

from contextlib import contextmanager, redirect_stdout
from dataclasses import replace
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from util.len_translation import LenProject, import_glossary, load_project, prepare_project, request_context, shared_context
from util.reference_games import add_paired_reference
from util.skills import load_system_prompt
from util.vocab import read_game_vocab, write_game_vocab


def make_skill(root: Path) -> Path:
    for name, content in {
        "SKILL.md": "---\nname: game-translation\ndescription: Translate games.\n---\n",
        "scripts/check_tools.py": "# miniature tool check\n",
        "references/engine.md": "Engine reference\n",
        "tools/THIRD-PARTY.md": "Optional dependencies\n",
    }.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


@contextmanager
def guidance_fixture(root: Path):
    data = root / "defaults"
    data.mkdir()
    base = data / "glossary_base.txt"
    base.write_text("# Base\n魔法 (Magic)\n", encoding="utf-8")
    system = data / "system.md"
    system.write_text("Translate into English.\n", encoding="utf-8")
    with (
        patch("util.paths.glossary_base_path", return_value=base),
        patch("util.vocab.glossary_base_path", return_value=base),
        patch("util.len_translation.DATA_DIR", data),
        patch("util.skills.system.PROMPT_PATH", system),
        patch("dotenv.load_dotenv"),
        patch.dict(os.environ, {"DAZED_GAME_ROOT": str(root / "unrelated-game")}),
    ):
        yield


class LenTranslationTests(unittest.TestCase):
    def test_prepare_resume_and_move_preserve_game_and_adapted_tools(self):
        with tempfile.TemporaryDirectory() as raw, guidance_fixture(Path(raw)):
            root = Path(raw)
            game = root / 'Game 日本語 "quoted"'
            game.mkdir()
            original = game / "Game.dat"
            original.write_bytes(b"original game")
            skill = make_skill(root / "skill")
            project = LenProject(game, instructions="Keep the existing glossary.")
            handoff = prepare_project(project, skill)
            self.assertEqual(load_project(game), project)
            self.assertIn(json.dumps(str(game), ensure_ascii=False), handoff.read_text())
            self.assertIn(project.instructions, handoff.read_text())
            self.assertFalse(project.legacy_skill_root.exists())
            custom = project.legacy_skill_root / "tools/extract.py"
            custom.parent.mkdir(parents=True)
            custom.write_text("# adapted for this game\n")
            progress = project.workspace / "status.md"
            progress.write_text("Extraction reviewed; translation pending.\n")
            overlays = game / ".dazedtl/skills"
            overlays.mkdir(exist_ok=True)
            for name, body in {"game": "Space opera.", "quirks": "Keep rhetorical questions.", "battle": "Short battle labels."}.items():
                (overlays / f"{name}.md").write_text(body)
            write_game_vocab("# Game Characters\nハイメ (Jaime) - curated evidence\n", game)
            imported = {
                "names": {
                    "ハイメ": {"en": "Jaime", "aliases": ["レオン"]},
                    "レオン": {"en": "Leon", "gender": "unknown", "register": "formal", "aliases": ["若様"]},
                },
                "terms": {"鍵": "Key"}, "do_not_merge": [["ハイメ", "レオン"]],
                "do_not_translate": ["asset_id"],
            }
            result = import_glossary(project, imported)
            self.assertEqual((result["added"], result["preserved"]), (3, 1))
            self.assertEqual(import_glossary(project, imported)["added"], 0)
            vocabulary = read_game_vocab(game)
            self.assertIn("ハイメ (Jaime) - curated evidence", vocabulary)
            self.assertIn("レオン (Leon) - gender: unknown; register: formal", vocabulary)
            self.assertNotIn("asset_id", vocabulary)
            self.assertEqual(result["extraction_metadata"], ["asset_id"])
            self.assertEqual(import_glossary(project, {"characters": {"司祭": {"name": "Priest", "speech": "polite"}}})["added"], 1)

            jp, en = root / "jp", root / "en"
            jp.mkdir()
            en.mkdir()
            (jp / "Text.json").write_text(json.dumps({"line": "鍵", "other": "別"}))
            (en / "Text.json").write_text(json.dumps({"line": "Old Key", "other": "Other"}))
            add_paired_reference(game, "Earlier Game", jp, en)
            sources = {"line1": "若様、鍵と魔法。" , "line2": "鍵"}
            batch = request_context(project, sources, instruction_key="events.choice_with_context", source_context="前の台詞")
            self.assertEqual(batch["system"], load_system_prompt(game))
            self.assertIn("Short battle labels.", batch["system"])
            self.assertIn("若様 (Leon)", batch["glossary"])
            self.assertIn("魔法 (Magic)", batch["glossary"])
            self.assertEqual(batch["reference_translations"]["matches"]["鍵"][0]["translation"], "Old Key")
            self.assertNotIn("別", batch["reference_translations"]["matches"])
            self.assertIn("前の台詞", batch["request_instructions"])
            self.assertEqual(json.loads(batch["user"].removeprefix("```json\n").removesuffix("\n```")), sources)
            self.assertEqual(os.environ["DAZED_GAME_ROOT"], str(root / "unrelated-game"))
            revised = replace(project, stage="continue", mode="api", include_images=False, include_glossary_base=False)
            self.assertNotIn("魔法 (Magic)", request_context(revised, sources)["glossary"])
            (overlays / "quirks.md").write_text("Keep pauses.")
            updated = request_context(project, sources)
            self.assertIn("Keep pauses.", updated["system"])
            self.assertNotEqual(batch["context_sha256"], updated["context_sha256"])
            self.assertNotEqual(updated["request_sha256"], request_context(project, ["鍵"])["request_sha256"])
            # Exercise CLI serialization at the in-process boundary without spawning a GUI/provider.
            from scripts.len_translation import main
            source_file = root / "sources.json"
            source_file.write_text(json.dumps(sources))
            with redirect_stdout(StringIO()):
                self.assertEqual(main(["context", "--game-root", str(game), "--sources", str(source_file)]), 0)
            self.assertEqual(json.loads((project.workspace / "request-context.json").read_text())["system"], updated["system"])
            prepare_project(revised, skill)
            self.assertEqual(load_project(game), revised)
            self.assertEqual(custom.read_text(), "# adapted for this game\n")
            self.assertEqual(progress.read_text(), "Extraction reviewed; translation pending.\n")
            self.assertEqual(original.read_bytes(), b"original game")
            moved = root / "Moved game"
            game.rename(moved)
            resumed = load_project(moved)
            self.assertEqual(resumed, replace(revised, game_root=moved))
            moved_prompt = prepare_project(resumed, skill).read_text()
            self.assertIn(json.dumps(str(skill / "SKILL.md")), moved_prompt)
            self.assertNotIn(str(game), moved_prompt)
            self.assertEqual(shared_context(resumed)["system"], load_system_prompt(moved))

    def test_invalid_import_or_workspace_preserves_existing_work(self):
        with tempfile.TemporaryDirectory() as raw, guidance_fixture(Path(raw)):
            root = Path(raw)
            game = root / "game"
            game.mkdir()
            project = LenProject(game)
            skill = make_skill(root / "skill")
            write_game_vocab("# Game Characters\nレオン / 若様 (Leon) - keep\n", game)
            before = (game / ".dazedtl/glossary.txt").read_bytes()
            cases = (
                {"terms": {"新語": "New", "若様": "Leo"}},
                {"names": {"ハイメ": {"en": "Jaime", "aliases": ["レオン"]}}},
                {"names": {"レオン / 若様": {"en": "Leo"}}},
                {"names": {"ハイメ": {"en": "Jaime", "aliases": ["謎"]}}, "do_not_merge": [["ハイメ", "謎"]]},
                {"names": {"ハイメ / レオン": {"en": "Jaime"}}, "do_not_merge": [["ハイメ", "レオン"]]},
                {"terms": {"鍵": "Key\nInjected"}},
                {"terms": {"鍵": "Key (Item)"}},
                {"names": {"ハイメ": {"en": "Jaime", "aliases": "謎"}}},
                {"terms": {"鍵": "Key"}, "do_not_merge": None},
                {"names": {}, "characters": {"司祭": {"name": "Priest"}}},
            )
            for document in cases:
                with self.subTest(document=document), self.assertRaises(ValueError):
                    import_glossary(project, document)
                self.assertEqual((game / ".dazedtl/glossary.txt").read_bytes(), before)
            for sources in ([], {}, [None], [""], {"": "鍵"}, "鍵"):
                with self.subTest(sources=sources), self.assertRaises(ValueError):
                    request_context(project, sources)
            for invalid in (replace(project, mode="unknown"), replace(project, include_images="false")):
                with self.assertRaises(ValueError):
                    prepare_project(invalid, skill)
            with self.assertRaises(ValueError):
                prepare_project(project, root / "missing-skill")
            self.assertFalse(project.workspace.exists())
            outside = root / "outside"
            outside.mkdir()
            sentinel = outside / "keep.txt"
            sentinel.write_text("keep")
            try:
                project.workspace.symlink_to(outside, target_is_directory=True)
            except OSError:
                return  # Symlinks may require privileges on Windows.
            with self.assertRaises(ValueError):
                prepare_project(project, skill)
            self.assertEqual(sentinel.read_text(), "keep")
            self.assertFalse((outside / "handoff.md").exists())
