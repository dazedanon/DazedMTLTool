"""Shared Len/Workflow guidance, conflict-safe imports, and project preservation."""

from contextlib import contextmanager, redirect_stdout
import copy
from dataclasses import replace
from io import StringIO
import json
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from util.len_translation import LenProject, import_glossary, load_project, prepare_project, request_context, shared_context
from util.reference_games import add_paired_reference
from util.skills import load_system_prompt
from util.vocab import read_game_vocab, write_game_vocab


def exercise_progress(test, project):
    """Protect counted completion, invalidation and atomic report replacement."""
    from scripts.len_translation import main
    from util.len_progress import metric_display, read_progress, review_fingerprint, update_progress

    unit = {"id": "Map001#1", "source": "はい。", "translation": "Yes."}
    unit["translated_from_sha256"] = hashlib.sha256(unit["source"].encode()).hexdigest()
    unit["reviewed_sha256"] = review_fingerprint(unit["source"].encode(), unit["translation"].encode())
    other = {"id": "Map001#2", "source": "待って。", "translation": "Wait.",
             "translated_from_sha256": hashlib.sha256("待って。".encode()).hexdigest()}
    stale = {"id": "Map001#3", "source": "新しい台詞。", "translation": "Old line.",
             "translated_from_sha256": hashlib.sha256("古い台詞。".encode()).hexdigest()}
    records = project.work_root / "progress-units.json"
    data = {"complete": True, "units": [unit, unit, other, stale]}
    records.write_text(json.dumps(data))
    image_source = project.work_root / "source-image.bin"
    image_output = project.work_root / "translated-image.bin"
    image_source.write_bytes(b"original image fixture")
    image_output.write_bytes(b"translated image fixture")
    relative = lambda path: path.relative_to(project.game_root).as_posix()
    images = project.work_root / "progress-images.json"
    images.write_text(json.dumps({"complete": True, "units": [{
        "id": "title", "source": relative(image_source), "translation": relative(image_output),
        "translated_from_sha256": hashlib.sha256(image_source.read_bytes()).hexdigest(),
    }]}))
    source = project.work_root / "source-manifest.json"
    source.write_text('{"version":"1.0"}')
    report = {"phase": "translation", "phases": {"preparation": "complete", "extraction": "complete"},
              "text": relative(records), "images": relative(images), "inputs": [relative(source)],
              "blocker": "", "next_action": "Translate the remaining dialogue."}
    report_file = project.work_root / "progress-report.json"
    report_file.write_text(json.dumps(report))
    with redirect_stdout(StringIO()):
        test.assertEqual(main(["progress-update", "--game-root", str(project.game_root), "--input", str(report_file)]), 0)
    snapshot = read_progress(project)
    test.assertEqual({key: snapshot["metrics"]["text"][key] for key in ("total", "translated", "reviewed", "discovered")},
                     {"total": 3, "translated": 2, "reviewed": 1, "discovered": 3})
    test.assertEqual(snapshot["metrics"]["images"]["translated"], 1)
    test.assertEqual(snapshot["warnings"], [])
    test.assertTrue(read_progress(replace(project, include_images=False))["warnings"])
    test.assertTrue(read_progress(replace(project, instructions="Different scope"))["warnings"])
    test.assertEqual(metric_display(snapshot["metrics"]["text"], "translated")[0], 66)
    test.assertEqual(update_progress(project, report)["metrics"], snapshot["metrics"])

    # Source edits invalidate the display. Even unchanged English needs review
    # again when its Japanese changes; re-exporting does not bless an old review.
    source.write_text('{"version":"1.1"}')
    test.assertTrue(read_progress(project)["warnings"])
    data["units"][0]["source"] = "はい！"
    records.write_text(json.dumps(data))
    test.assertEqual(update_progress(project, report)["metrics"]["text"]["translated"], 1)
    unit["translated_from_sha256"] = hashlib.sha256(unit["source"].encode()).hexdigest()
    records.write_text(json.dumps(data))
    test.assertEqual(update_progress(project, report)["metrics"]["text"]["reviewed"], 0)
    data["complete"] = False
    records.write_text(json.dumps(data))
    partial = update_progress(project, report)["metrics"]["text"]
    test.assertIsNone(partial["total"])
    test.assertEqual(partial["discovered"], 3)
    test.assertEqual(metric_display(partial, "translated")[0], 66)
    test.assertEqual(metric_display({"total": 0, "translated": 0, "reviewed": 0}, "translated"), (0, "No units", "0 / 0"))
    test.assertEqual(metric_display(partial, "translated", excluded=True), (0, "Out of scope", ""))
    data["complete"] = True
    records.write_text(json.dumps(data))
    update_progress(project, report)

    before = (project.workspace / "progress.json").read_bytes()
    invalid = (
        {**report, "phase": "unknown"}, {**report, "phase": []},
        {**report, "phases": {"qa": []}},
        {**report, "phase": None, "phases": {"translation": "complete"}},
        {**report, "text": "../outside.json"}, {**report, "text": "/absolute.json"},
        {**report, "next_action": "wordy\nreport"}, {**report, "text": "missing.json"},
        {**report, "metrics": {"text": {"translated": 999}}},
    )
    for bad in invalid:
        with test.subTest(report=bad), test.assertRaises(ValueError):
            update_progress(project, bad)
        test.assertEqual((project.workspace / "progress.json").read_bytes(), before)
    duplicate = copy.deepcopy(unit)
    duplicate["translation"] = "Conflicting output"
    records.write_text(json.dumps({"complete": True, "units": [unit, duplicate]}))
    with test.assertRaises(ValueError):
        update_progress(project, report)
    test.assertEqual((project.workspace / "progress.json").read_bytes(), before)
    records.write_text(json.dumps(data))
    image_output.unlink()
    test.assertTrue(read_progress(project)["warnings"])
    with test.assertRaises(ValueError):
        update_progress(project, report)
    test.assertEqual((project.workspace / "progress.json").read_bytes(), before)
    image_output.write_bytes(b"")
    test.assertEqual(update_progress(project, report)["metrics"]["images"]["translated"], 0)
    image_output.write_bytes(b"translated image fixture")
    update_progress(project, report)
    test.assertEqual(read_progress(project)["warnings"], [])
    progress_path = project.workspace / "progress.json"
    valid = progress_path.read_bytes()
    for metric in ({"total": 1, "translated": 2, "reviewed": 0},
                   {"total": 2, "translated": 1, "reviewed": 2},
                   {"total": True, "translated": 1, "reviewed": 0},
                   {"translated": 1, "reviewed": 0}):
        broken = json.loads(valid)
        broken["metrics"]["text"] = metric
        progress_path.write_text(json.dumps(broken))
        with test.subTest(metric=metric), test.assertRaises(ValueError):
            read_progress(project)
    broken = json.loads(valid)
    del broken["phase"]
    progress_path.write_text(json.dumps(broken))
    with test.assertRaises(ValueError):
        read_progress(project)
    progress_path.write_bytes(valid)

    # Same-size edits with restored mtime still invalidate the CLI's hash check.
    stat = source.stat()
    source.write_text('{"version":"9.9"}')
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    test.assertTrue(read_progress(project)["warnings"])
    source.write_text('{"version":"1.1"}')
    from util.len_progress import estimate_display
    data["units"] = [unit, other, {"id": "Map002#1", "source": "新しい行"}]
    data["complete"] = False
    other.pop("translated_from_sha256")
    records.write_text(json.dumps(data))
    update_progress(project, {**report, "timing": {"translated": 60}})
    other["translated_from_sha256"] = hashlib.sha256(other["source"].encode()).hexdigest()
    records.write_text(json.dumps(data))
    timed = update_progress(project, {**report, "timing": {"translated": 180},
                                    "phases": {"translation": "active", "qa": "active"}})
    test.assertEqual(len(timed["history"]), 2)
    test.assertIn("1–3", estimate_display(timed))
    test.assertIn("paused", estimate_display({**timed, "blocker": "Waiting for user scope"}))
    # New source units reset the throughput sample instead of extrapolating an old scope.
    data["units"].append({"id": "new", "source": "別の場面"})
    records.write_text(json.dumps(data))
    test.assertEqual(len(update_progress(project, {**report, "timing": {"translated": 240}})["history"]), 1)
    for addition in ({"timing": {"translated": float("nan")}},
                     {"estimates": {"qa": {"low_minutes": 5, "high_minutes": 1, "basis": "bad bounds"}}},
                     {"inputs": [".dazedtl/len-method/progress.json"]}):
        with test.assertRaises(ValueError):
            update_progress(project, {**report, **addition})
    # Leave a valid snapshot for the encompassing move/resume regression.
    update_progress(project, report)


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
            exercise_progress(self, project)
            saved_progress = (project.workspace / "progress.json").read_bytes()
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
            (jp / "Text.json").write_text(json.dumps({"line": "鍵", "other": "別", "name": "レオン"}))
            (en / "Text.json").write_text(json.dumps({"line": "Old Key", "other": "Other", "name": "Old Leon"}))
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

            # Speaker identity is necessary even when identical short dialogue
            # never names its speaker. Metadata must not alter the source body.
            dialogue = {"a": "はい。", "b": "はい。", "c": "鍵"}
            speakers = {"b": "ハイメ", "c": None, "a": "レオン"}
            bare = request_context(project, dialogue)
            from util.translation import build_sfx_reference_text
            with patch("util.translation.build_sfx_reference_text", wraps=build_sfx_reference_text) as sfx_matcher:
                spoken = request_context(project, dialogue, speakers=speakers)
            sfx_matcher.assert_called_once_with(json.dumps(dialogue, ensure_ascii=False), enabled=True)
            self.assertEqual(spoken["speakers"], speakers)
            self.assertTrue(spoken["user"].endswith(bare["user"]))
            self.assertIn(json.dumps(spoken["speakers"], ensure_ascii=False), spoken["user"])
            self.assertIn("レオン (Leon) - gender: unknown; register: formal", spoken["glossary"])
            self.assertIn("ハイメ (Jaime) - curated evidence", spoken["glossary"])
            self.assertNotIn("司祭 (Priest)", spoken["glossary"])
            self.assertNotIn("レオン (Leon)", bare["glossary"])
            self.assertEqual(spoken["sfx_reference"], bare["sfx_reference"])
            self.assertEqual(spoken["reference_translations"], bare["reference_translations"])
            swapped = request_context(project, dialogue, speakers={"a": "ハイメ", "b": "レオン", "c": None})
            self.assertEqual(spoken["glossary"], swapped["glossary"])
            self.assertNotEqual(spoken["request_sha256"], swapped["request_sha256"])
            normalized = request_context(project, ["待って。"], speakers=["ﾚｵﾝ"])
            self.assertIn("レオン (Leon)", normalized["glossary"])
            self.assertEqual(normalized["speakers"], ["ﾚｵﾝ"])
            unidentified = request_context(project, ["待って。"], speakers=[" "], source_context="レオンの前の台詞")
            self.assertEqual(unidentified["speakers"], [None])
            self.assertNotIn("レオン (Leon)", unidentified["glossary"])
            revised = replace(project, stage="continue", mode="local", include_images=False, include_glossary_base=False)
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
            speaker_file = root / "speakers.json"
            speaker_file.write_text(json.dumps({"line1": "レオン", "line2": None}))
            with redirect_stdout(StringIO()):
                self.assertEqual(main(["context", "--game-root", str(game), "--sources", str(source_file), "--speakers", str(speaker_file)]), 0)
            compiled = json.loads((project.workspace / "request-context.json").read_text())
            self.assertEqual(compiled["speakers"], {"line1": "レオン", "line2": None})
            self.assertIn("レオン (Leon)", compiled["glossary"])
            prepare_project(revised, skill)
            self.assertEqual(load_project(game), revised)
            self.assertEqual(custom.read_text(), "# adapted for this game\n")
            self.assertEqual(progress.read_text(), "Extraction reviewed; translation pending.\n")
            self.assertEqual((project.workspace / "progress.json").read_bytes(), saved_progress)
            self.assertEqual(original.read_bytes(), b"original game")
            moved = root / "Moved game"
            game.rename(moved)
            resumed = load_project(moved)
            self.assertEqual(resumed, replace(revised, game_root=moved))
            moved_prompt = prepare_project(resumed, skill).read_text()
            self.assertIn(json.dumps(str(skill / "SKILL.md")), moved_prompt)
            self.assertNotIn(str(game), moved_prompt)
            self.assertEqual(shared_context(resumed)["system"], load_system_prompt(moved))
            from util.len_progress import read_progress
            # Image scope changed earlier, but moved artifact paths still resolve.
            self.assertEqual(len(read_progress(resumed)["warnings"]), 1)

        # The same handoff lifecycle must bind bulk context and API preflight to current inputs.
        from util.len_translation import build_handoff, request_contexts
        from util.len_api import compile_plan, create_estimate, validate_estimate
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as raw, guidance_fixture(Path(raw)):
            root = Path(raw)
            game = root / "game"
            game.mkdir()
            project = LenProject(game, mode="api")
            prepare_project(replace(project, stage="prepare"), make_skill(root / "skill"))
            source = project.work_root / "sources.json"
            source.write_text('{"line":"鍵"}')
            batches = [{"id": "scene-a", "sources": {"a": "鍵"}, "speakers": {"a": "レオン"}},
                       {"id": "scene-b", "sources": ["待って。"], "speakers": [None]}]
            expected = [request_context(project, **{k: v for k, v in batch.items() if k != "id"}) for batch in batches]
            self.assertEqual([item["context"] for item in request_contexts(project, batches)], expected)
            # The fast path must remain identical when advisory reference matches exist.
            jp, en = root / "jp", root / "en"
            jp.mkdir(); en.mkdir()
            (jp / "Text.json").write_text('{"line":"鍵"}')
            (en / "Text.json").write_text('{"line":"Key"}')
            add_paired_reference(game, title="Earlier game", source_data=jp, translated_data=en)
            self.assertEqual([item["context"] for item in request_contexts(project, batches)],
                             [request_context(project, **{k: v for k, v in batch.items() if k != "id"}) for batch in batches])
            with self.assertRaises(ValueError):
                build_handoff(project)
            plan = {"complete": True, "inputs": [source.relative_to(game).as_posix()], "batches": batches}
            compiled = compile_plan(project, plan)
            path = project.workspace / "api-requests.json"
            path.write_text(json.dumps(compiled))
            settings = {"model": "gpt-4.1", "api": "", "API_PROVIDER": "openai"}
            with patch("util.len_api.api_settings", return_value=settings), \
                 patch("tiktoken.encoding_for_model", return_value=SimpleNamespace(encode=lambda value: list(value))), \
                 patch("util.translation.getPricingConfig", return_value={"inputAPICost": 2, "outputAPICost": 8}):
                estimate = create_estimate(project)
                self.assertGreater(estimate["input_tokens"], sum(len(json.dumps(b["sources"])) for b in batches))
                self.assertEqual(estimate["batch_cost"], estimate["live_cost"] / 2)
                with self.assertRaises(ValueError):
                    validate_estimate(project, estimate)
                estimate["approved"] = True
                validate_estimate(project, estimate)
                approved = replace(project, api_estimate=estimate)
                self.assertTrue(build_handoff(approved))
                with self.assertRaises(ValueError):
                    validate_estimate(project, estimate, settings={**settings, "model": "different"})
                source.write_text('{"line":"新しい鍵"}')
                with self.assertRaises(ValueError):
                    validate_estimate(project, estimate)
                source.write_text('{"line":"鍵"}')
                with patch("util.len_api._compiler_fingerprint", return_value="changed"):
                    with self.assertRaises(ValueError):
                        validate_estimate(project, estimate)
                (en / "Text.json").write_text('{"line":"Changed reference"}')
                with self.assertRaises(ValueError):
                    validate_estimate(project, estimate)
                (en / "Text.json").write_text('{"line":"Key"}')
                original_requests = path.read_bytes()
                tampered = json.loads(original_requests)
                tampered["batches"][0]["sources"]["a"] = "違う"
                path.write_text(json.dumps(tampered))
                with self.assertRaises(ValueError):
                    create_estimate(project)
                path.write_bytes(original_requests)
                write_game_vocab("# Game Terms\n鍵 (Different key)\n", game)
                with self.assertRaises(ValueError):
                    validate_estimate(project, estimate)
            # Changing dependencies mid-compilation aborts the set.
            shared = shared_context(project)
            with patch("util.len_translation.shared_context", side_effect=[shared, {**shared, "content_sha256": "changed"}]):
                with self.assertRaises(ValueError):
                    request_contexts(project, batches)

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
            for sources, speakers in (
                (["鍵"], []), (["鍵"], ["レオン", "ハイメ"]),
                (["鍵"], {"0": "レオン"}), ({"a": "鍵"}, ["レオン"]),
                ({"a": "鍵"}, {}), ({"a": "鍵"}, {"b": "レオン"}),
                ({"a": "鍵"}, {"a": "レオン", "extra": None}),
                (["鍵"], [3]), (["鍵"], [{"name": "レオン"}]),
                (["鍵"], ["レオン\nハイメ"]), (["鍵"], ["レオン\0"]),
            ):
                with self.subTest(speakers=speakers), self.assertRaises(ValueError):
                    request_context(project, sources, speakers=speakers)
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
