from __future__ import annotations

import os
import json
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from PyQt5.QtWidgets import QApplication, QLineEdit, QMessageBox, QWidget

from util.paths import (
    GAME_IMAGE_PATCH_GITIGNORE_COMMENT,
    GAME_TOOL_GITIGNORE_BEGIN,
    GAME_TOOL_GITIGNORE_END,
    ensure_game_tool_gitignore,
)
from util.version_update import (
    GitWorkflowError,
    abort_update,
    apply_official_update,
    apply_registered_original,
    bootstrap_repository,
    checkout_translation_branch,
    inspect_repository,
    preview_official_update,
    record_version_metadata,
    register_translation_branch,
)
from util.version_update.git_workflow import _install_gameupdate_gitignore


class GitVersionUpdateTests(unittest.TestCase):
    """Protect exact Git transport, bootstrap, and official-first conflicts."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.old = self.root / "Original v1.00"
        self.translated = self.root / "Translated v1.00"
        self.new = self.root / "Original v1.03"
        for folder in (self.old, self.translated, self.new):
            folder.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def git(repo: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return result.stdout.strip()

    def write_versions(self, old: str, translated: str, new: str, name="game.txt"):
        self.old.joinpath(name).write_text(old, encoding="utf-8")
        self.translated.joinpath(name).write_text(translated, encoding="utf-8")
        self.new.joinpath(name).write_text(new, encoding="utf-8")

    def test_bootstrap_constructs_exact_branches_without_rewriting_translation(self):
        self.write_versions("Japanese\n", "English\n", "New Japanese\n")
        translated_before = self.translated.joinpath("game.txt").read_bytes()

        result = bootstrap_repository(self.translated, self.old, "1.00")
        status = inspect_repository(self.translated)

        self.assertEqual(self.translated.joinpath("game.txt").read_bytes(), translated_before)
        self.assertEqual(self.git(self.translated, "show", "original:game.txt"), "Japanese")
        self.assertEqual(self.git(self.translated, "show", "main:game.txt"), "English")
        self.assertEqual(status.current_branch, "main")
        self.assertEqual(status.translation_branch, "main")
        self.assertEqual(status.original_version, "1.00")
        self.assertEqual(status.translation_version, "1.00")
        self.assertTrue(status.worktree_clean)
        self.assertTrue(status.asset_manifest_available)
        self.assertEqual(result.repo_root, self.translated)
        self.assertTrue(result.gitignore_installed)
        self.assertTrue(self.translated.joinpath(".gitignore").is_file())

    def test_bootstrap_same_folder_creates_identical_baselines(self):
        """Prepare uses one pre-translation game as both original and translation."""
        game = self.translated
        game.joinpath("game.txt").write_text("Japanese\n", encoding="utf-8")
        game.joinpath("data.json").write_text('{"name":"Hero","v":1}')

        result = bootstrap_repository(game, game, "1.00")
        status = inspect_repository(game)

        expected_json = json.dumps(
            {"name": "Hero", "v": 1}, indent=4, ensure_ascii=False
        )
        self.assertEqual(self.git(game, "show", "original:game.txt"), "Japanese")
        self.assertEqual(self.git(game, "show", "main:game.txt"), "Japanese")
        self.assertEqual(self.git(game, "show", "original:data.json"), expected_json)
        self.assertEqual(self.git(game, "show", "main:data.json"), expected_json)
        self.assertEqual(game.joinpath("data.json").read_text(encoding="utf-8"), expected_json)
        self.assertEqual(status.current_branch, "main")
        self.assertEqual(status.translation_branch, "main")
        self.assertEqual(status.original_version, "1.00")
        self.assertEqual(status.translation_version, "1.00")
        self.assertTrue(status.worktree_clean)
        self.assertIn("data.json", result.formatted_json_paths)

    def test_bootstrap_formats_worktree_before_git_init(self):
        """Formatting must hit disk before repository creation."""
        game = self.translated
        game.joinpath("data.json").write_text('{"name":"Hero","v":1}')
        events: list[str] = []
        real_prepare = __import__(
            "util.version_update.git_workflow", fromlist=["_prepare_worktree_formatting"]
        )._prepare_worktree_formatting
        real_run_git = __import__(
            "util.version_update.git_workflow", fromlist=["_run_git"]
        )._run_git

        def tracking_prepare(source):
            events.append("format")
            self.assertFalse((Path(source) / ".git").exists())
            return real_prepare(source)

        def tracking_run_git(cwd, *args, **kwargs):
            if args and args[0] == "init":
                events.append("init")
                self.assertIn("format", events)
            return real_run_git(cwd, *args, **kwargs)

        with (
            patch(
                "util.version_update.git_workflow._prepare_worktree_formatting",
                side_effect=tracking_prepare,
            ),
            patch(
                "util.version_update.git_workflow._run_git",
                side_effect=tracking_run_git,
            ),
        ):
            bootstrap_repository(game, game, "1.00")

        self.assertEqual(events[0], "format")
        self.assertIn("init", events)
        self.assertLess(events.index("format"), events.index("init"))

    def test_bootstrap_installs_bundled_gitignore_before_building_branches(self):
        self.write_versions("Japanese\n", "English\n", "New Japanese\n")
        for folder in (self.old, self.translated):
            folder.joinpath("debug.log").write_text("runtime log\n")
            folder.joinpath("picture.png").write_bytes(b"runtime image")
            folder.joinpath("data.json").write_text('{"value":1}')

        result = bootstrap_repository(self.translated, self.old, "1.00")

        ignore = self.translated.joinpath(".gitignore").read_text()
        self.assertIn("# Ignore all files", ignore)
        self.assertIn("!*.json", ignore)
        self.assertTrue(result.gitignore_installed)
        for ref in ("original", "main"):
            tracked = self.git(self.translated, "ls-tree", "-r", "--name-only", ref)
            self.assertIn(".gitignore", tracked)
            self.assertIn("data.json", tracked)
            self.assertNotIn("debug.log", tracked)
            self.assertNotIn("picture.png", tracked)
        self.assertIn("debug.log", result.ignored_paths)
        self.assertIn("picture.png", result.ignored_paths)

    def test_bootstrap_ignores_legacy_updater_metadata_without_deleting_it(self):
        self.write_versions("Japanese\n", "English\n", "New Japanese\n")
        legacy = self.translated / ".dazedtl" / "version_update"
        legacy.mkdir(parents=True)
        legacy.joinpath("project.json").write_text('{"legacy":true}\n')
        portable = {
            ".dazedtl/glossary.txt": "Hero (Hero)\n",
            ".dazedtl/settings.json": '{"version":1}\n',
            ".dazedtl/skills/game.md": "# Translation Frame\n",
        }
        for relative, body in portable.items():
            path = self.translated / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
        ensure_game_tool_gitignore(self.translated)

        bootstrap_repository(self.translated, self.old, "1.00")

        self.assertTrue(legacy.joinpath("project.json").exists())
        self.assertTrue(inspect_repository(self.translated).worktree_clean)
        tracked = self.git(self.translated, "ls-tree", "-r", "--name-only", "main")
        self.assertNotIn(".dazedtl/version_update", tracked)
        for relative in portable:
            self.assertIn(relative, tracked)
        self.assertEqual(
            self.translated.joinpath(".gitignore")
            .read_text(encoding="utf-8")
            .count(GAME_TOOL_GITIGNORE_BEGIN),
            1,
        )

    def test_bootstrap_formats_both_json_baselines_and_respects_gitignore(self):
        self.old.joinpath("data.json").write_text('{"name":"Japanese","items":[null,1]}')
        self.translated.joinpath("data.json").write_text(
            '{"name":"English","items":[null,1]}'
        )
        self.new.joinpath("data.json").write_text('{"name":"New","items":[null,1]}')
        for folder in (self.old, self.translated, self.new):
            folder.joinpath(".gitignore").write_text("save/\n*.log\n")
            folder.joinpath("save").mkdir()
            folder.joinpath("save/slot.dat").write_bytes(b"user save")
            folder.joinpath("debug.log").write_text("runtime log\n")

        current_policy = (
            Path(__file__).resolve().parents[1]
            .joinpath("gameupdate", ".gitignore")
            .read_text(encoding="utf-8")
        )
        block_start = current_policy.index(GAME_TOOL_GITIGNORE_BEGIN)
        block_end = (
            current_policy.index(GAME_TOOL_GITIGNORE_END, block_start)
            + len(GAME_TOOL_GITIGNORE_END)
        )
        previous_policy = (
            current_policy[:block_start].rstrip()
            + "\n\n"
            + current_policy[block_end:].lstrip()
        )
        self.translated.joinpath(".gitignore").write_text(
            previous_policy.rstrip()
            + "\n\n# Existing project rules\nsave/\n*.log\n\n"
            + GAME_IMAGE_PATCH_GITIGNORE_COMMENT
            + "\n!/www/img/pictures/menu.png\n",
            encoding="utf-8",
        )

        result = bootstrap_repository(self.translated, self.old, "1.00")

        expected_original = json.dumps(
            {"name": "Japanese", "items": [None, 1]}, indent=4, ensure_ascii=False
        )
        expected_translation = json.dumps(
            {"name": "English", "items": [None, 1]}, indent=4, ensure_ascii=False
        )
        self.assertEqual(self.git(self.translated, "show", "original:data.json"), expected_original)
        self.assertEqual(
            self.translated.joinpath("data.json").read_text(), expected_translation
        )
        self.assertEqual(
            self.git(self.translated, "show", "main:data.json"),
            expected_translation,
        )
        tracked = self.git(self.translated, "ls-tree", "-r", "--name-only", "main")
        self.assertNotIn("save/slot.dat", tracked)
        self.assertNotIn("debug.log", tracked)
        self.assertTrue(self.translated.joinpath("save/slot.dat").exists())
        self.assertTrue(self.translated.joinpath("debug.log").exists())
        self.assertIn("save/slot.dat", result.ignored_paths)
        self.assertIn("debug.log", result.ignored_paths)
        self.assertIn("data.json", result.formatted_json_paths)
        combined_ignore = self.translated.joinpath(".gitignore").read_text()
        self.assertEqual(combined_ignore.count("# Ignore all files"), 1)
        self.assertEqual(combined_ignore.count(GAME_TOOL_GITIGNORE_BEGIN), 1)
        self.assertIn("# Existing project rules\nsave/\n*.log\n", combined_ignore)
        self.assertEqual(combined_ignore.count(GAME_IMAGE_PATCH_GITIGNORE_COMMENT), 1)
        self.assertGreater(
            combined_ignore.index(GAME_TOOL_GITIGNORE_BEGIN),
            combined_ignore.index("# Existing project rules"),
        )
        self.assertGreater(
            combined_ignore.index(GAME_IMAGE_PATCH_GITIGNORE_COMMENT),
            combined_ignore.index(GAME_TOOL_GITIGNORE_END),
        )
        self.assertEqual(
            combined_ignore.splitlines()[-1], "!/www/img/pictures/menu.png"
        )
        diff = self.git(self.translated, "diff", "original", "main", "--", "data.json")
        self.assertIn('"name": "Japanese"', diff)
        self.assertIn('"name": "English"', diff)
        self.assertNotIn('{"name":', diff)

        image_only = self.root / "Installed Template With Image Patch"
        image_only.mkdir()
        image_only.joinpath(".gitignore").write_text(
            current_policy.rstrip()
            + "\n\n"
            + GAME_IMAGE_PATCH_GITIGNORE_COMMENT
            + "\n!/www/img/pictures/title.png\n",
            encoding="utf-8",
        )
        ensure_game_tool_gitignore(image_only)

        _install_gameupdate_gitignore(image_only)

        image_only_ignore = image_only.joinpath(".gitignore").read_text()
        self.assertEqual(image_only_ignore.count("# Ignore all files"), 1)
        self.assertEqual(image_only_ignore.count(GAME_TOOL_GITIGNORE_BEGIN), 1)
        self.assertEqual(
            image_only_ignore.splitlines()[-1], "!/www/img/pictures/title.png"
        )

        malformed_cases = {
            "missing end": (
                "custom-rule/\n\n"
                f"{GAME_TOOL_GITIGNORE_BEGIN}\n"
                "!/.dazedtl/settings.json\n"
            ),
            "nested begin": (
                "custom-before/\n"
                f"{GAME_TOOL_GITIGNORE_BEGIN}\n"
                "keep-me/\n"
                f"{GAME_TOOL_GITIGNORE_BEGIN}\n"
                "!/.dazedtl/settings.json\n"
                f"{GAME_TOOL_GITIGNORE_END}\n"
                "custom-after/\n"
            ),
        }
        for label, malformed_text in malformed_cases.items():
            with self.subTest(label=label):
                malformed = self.root / f"Malformed managed block {label}"
                malformed.mkdir()
                malformed_ignore = malformed / ".gitignore"
                malformed_before = malformed_text.encode("utf-8")
                malformed_ignore.write_bytes(malformed_before)
                with self.assertRaisesRegex(
                    GitWorkflowError, "managed .gitignore block"
                ):
                    _install_gameupdate_gitignore(malformed)
                self.assertEqual(malformed_ignore.read_bytes(), malformed_before)

    def test_bootstrap_normalizes_crlf_so_eol_noise_cannot_wipe_translations(self):
        # Pretty JSON that only differs by CRLF must become LF in Git. Otherwise a
        # later LF official release conflicts on every line and replaces translations.
        self.old.joinpath("data.json").write_bytes(
            b'{\r\n    "name": "Japanese",\r\n    "value": 1\r\n}'
        )
        self.translated.joinpath("data.json").write_bytes(
            b'{\r\n    "name": "English",\r\n    "value": 1\r\n}'
        )
        self.old.joinpath("game.txt").write_bytes(b"Japanese source\r\nshared line\r\n")
        self.translated.joinpath("game.txt").write_bytes(b"English source\r\nshared line\r\n")
        self.old.joinpath("payload").write_bytes(b"keep\r\nnull\x00byte")
        self.translated.joinpath("payload").write_bytes(b"keep\r\nnull\x00byte")
        self.old.joinpath("GameUpdate.bat").write_bytes(b"@echo off\r\necho keep-crlf\r\n")
        self.translated.joinpath("GameUpdate.bat").write_bytes(
            b"@echo off\r\necho keep-crlf\r\n"
        )
        self.new.joinpath("data.json").write_bytes(
            b'{"name":"Japanese","value":1}\n'
        )
        self.new.joinpath("game.txt").write_bytes(
            b"Japanese source\nshared line\nnew official feature\n"
        )
        self.new.joinpath("payload").write_bytes(b"keep\r\nnull\x00byte")
        self.new.joinpath("GameUpdate.bat").write_bytes(b"@echo off\r\necho keep-crlf\r\n")

        result = bootstrap_repository(self.translated, self.old, "1.00")

        expected_translation = json.dumps(
            {"name": "English", "value": 1}, indent=4, ensure_ascii=False
        )
        self.assertEqual(
            self.translated.joinpath("data.json").read_bytes(),
            expected_translation.encode("utf-8"),
        )
        self.assertEqual(
            self.git(self.translated, "show", "original:data.json"),
            json.dumps({"name": "Japanese", "value": 1}, indent=4, ensure_ascii=False),
        )
        self.assertEqual(
            self.translated.joinpath("game.txt").read_bytes(),
            b"English source\nshared line\n",
        )
        self.assertEqual(
            self.git(self.translated, "show", "original:game.txt"),
            "Japanese source\nshared line",
        )
        binary = subprocess.run(
            ["git", "-C", str(self.translated), "show", "original:payload"],
            check=True,
            capture_output=True,
        ).stdout
        self.assertEqual(binary, b"keep\r\nnull\x00byte")
        self.assertEqual(
            self.translated.joinpath("payload").read_bytes(),
            b"keep\r\nnull\x00byte",
        )
        bat = subprocess.run(
            ["git", "-C", str(self.translated), "show", "original:GameUpdate.bat"],
            check=True,
            capture_output=True,
        ).stdout
        self.assertEqual(bat, b"@echo off\r\necho keep-crlf\r\n")
        self.assertIn("data.json", result.formatted_json_paths)
        self.assertIn("game.txt", result.formatted_json_paths)
        self.assertNotIn("GameUpdate.bat", result.formatted_json_paths)

        # Minified LF official JSON matches the normalized original blob, so it is
        # not an official delta. The text update must still apply cleanly.
        update = apply_official_update(self.translated, self.new, "1.02")

        self.assertTrue(update.complete)
        self.assertEqual(update.official_won_paths, ())
        self.assertEqual(
            self.translated.joinpath("game.txt").read_bytes(),
            b"English source\nshared line\nnew official feature\n",
        )
        self.assertEqual(
            self.translated.joinpath("data.json").read_bytes(),
            expected_translation.encode("utf-8"),
        )

    def test_run_git_sends_stdin_as_lf_bytes(self):
        """Windows text-mode pipes must not rewrite LF before Git sees stdin."""
        self.write_versions("Japanese\n", "English\n", "New Japanese\n")
        bootstrap_repository(self.translated, self.old, "1.00")
        captured: list[bytes | None] = []
        real_run = subprocess.run

        def capture_run(*args, **kwargs):
            captured.append(kwargs.get("input"))
            return real_run(*args, **kwargs)

        with patch("util.version_update.git_workflow.subprocess.run", side_effect=capture_run):
            from util.version_update.git_workflow import _run_git

            _run_git(
                self.translated,
                "hash-object",
                "-w",
                "--no-filters",
                "--stdin",
                input_text="line-one\nline-two\n",
            )

        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0], b"line-one\nline-two\n")

    def test_bootstrap_survives_windows_text_mode_stdin_translation(self):
        """Normalize JSON/text even when a host would CRLF-translate text pipes."""
        self.old.joinpath("data.json").write_text('{"name":"Jp","v":1}', encoding="utf-8")
        self.translated.joinpath("data.json").write_text(
            '{"name":"En","v":1}', encoding="utf-8"
        )
        self.old.joinpath("note.txt").write_bytes(b"hello\r\nworld\r\n")
        self.translated.joinpath("note.txt").write_bytes(b"hello\r\nworld\r\n")
        self.old.joinpath("GameUpdate.bat").write_bytes(b"@echo off\r\n")
        self.translated.joinpath("GameUpdate.bat").write_bytes(b"@echo off\r\n")

        real_run = subprocess.run

        def windows_text_pipe_run(*args, **kwargs):
            inp = kwargs.get("input")
            # Only text-mode string input is rewritten on Windows. Binary stdin
            # from _run_git must stay byte-exact.
            if isinstance(inp, str) and kwargs.get("text"):
                kwargs = dict(kwargs)
                kwargs["input"] = inp.replace("\n", "\r\n")
            return real_run(*args, **kwargs)

        with patch(
            "util.version_update.git_workflow.subprocess.run",
            side_effect=windows_text_pipe_run,
        ):
            result = bootstrap_repository(self.translated, self.old, "1.00")

        status = inspect_repository(self.translated)
        self.assertTrue(status.worktree_clean)
        self.assertEqual(
            self.translated.joinpath("data.json").read_bytes(),
            b'{\n    "name": "En",\n    "v": 1\n}',
        )
        self.assertEqual(
            self.translated.joinpath("note.txt").read_bytes(),
            b"hello\nworld\n",
        )
        bat = subprocess.run(
            ["git", "-C", str(self.translated), "show", "main:GameUpdate.bat"],
            check=True,
            capture_output=True,
        ).stdout
        self.assertEqual(bat, b"@echo off\r\n")
        self.assertIn("data.json", result.formatted_json_paths)

    def test_preview_reapplies_exact_eol_config_on_existing_repo(self):
        """Clones do not inherit local autocrlf=false; preview must restore it."""
        self.write_versions("Japanese\n", "English\n", "Japanese\nnew line\n")
        bootstrap_repository(self.translated, self.old, "1.00")
        self.git(self.translated, "config", "core.autocrlf", "true")
        self.git(self.translated, "config", "core.eol", "crlf")

        preview_official_update(self.translated, self.new, "1.02")

        self.assertEqual(
            self.git(self.translated, "config", "--local", "--get", "core.autocrlf"),
            "false",
        )
        self.assertEqual(
            self.git(self.translated, "config", "--local", "--get", "core.eol"),
            "lf",
        )

    def test_update_preserves_nonconflicting_translation_and_applies_official_patch(self):
        self.write_versions("Japanese\n", "English\n", "Japanese\n", "dialogue.txt")
        self.old.joinpath("engine.txt").write_text("engine=1\n")
        self.translated.joinpath("engine.txt").write_text("engine=1\n")
        self.new.joinpath("engine.txt").write_text("engine=2\nnew-feature=yes\n")
        bootstrap_repository(self.translated, self.old, "1.00")

        result = apply_official_update(self.translated, self.new, "1.03")

        self.assertTrue(result.complete)
        self.assertEqual(result.official_won_paths, ())
        self.assertEqual(
            self.translated.joinpath("dialogue.txt").read_text("utf-8"),
            "English\n",
        )
        self.assertEqual(
            self.translated.joinpath("engine.txt").read_text("utf-8"),
            "engine=2\nnew-feature=yes\n",
        )
        status = inspect_repository(self.translated)
        self.assertEqual(status.original_version, "1.03")
        self.assertEqual(status.translation_version, "1.03")

    def test_copy_over_patch_preserves_omitted_files_and_updates_supplied_assets(self):
        self.write_versions("old dialogue\n", "English dialogue\n", "unused\n")
        for folder in (self.old, self.translated):
            folder.joinpath("data").mkdir()
            folder.joinpath("movies").mkdir()
            folder.joinpath("data/System.json").write_text(
                '{"version":1}', encoding="utf-8"
            )
            folder.joinpath("data/Unchanged.json").write_text(
                '{"keep":true}', encoding="utf-8"
            )
            folder.joinpath("movies/ending.gdat").write_bytes(b"old movie")
            folder.joinpath("movies/unchanged.gdat").write_bytes(b"keep movie")
            folder.joinpath("eol.txt").write_bytes(b"same text\r\n")
        patch_folder = self.root / "Ver.1.1_patch"
        patch_folder.joinpath("data").mkdir(parents=True)
        patch_folder.joinpath("movies").mkdir()
        patch_folder.joinpath("data/System.json").write_text(
            '{"version":2}', encoding="utf-8"
        )
        patch_folder.joinpath("data/Unchanged.json").write_text(
            '{"keep":true}', encoding="utf-8"
        )
        patch_folder.joinpath("eol.txt").write_bytes(b"same text\r\n")
        patch_folder.joinpath("movies/ending.gdat").write_bytes(b"new movie")
        bootstrap_repository(self.translated, self.old, "1.00")

        preview = preview_official_update(
            self.translated, patch_folder, "1.10", patch_overlay=True
        )

        self.assertTrue(preview.patch_overlay)
        self.assertEqual(preview.deleted_paths, ())
        self.assertIn("data/System.json", preview.modified_paths)
        self.assertNotIn("data/Unchanged.json", preview.changed_paths)
        self.assertNotIn("eol.txt", preview.changed_paths)
        external = {change.path: change for change in preview.external_changes}
        self.assertEqual(external["movies/ending.gdat"].change, "Replaced")
        self.assertNotIn("movies/unchanged.gdat", external)

        apply_official_update(
            self.translated,
            patch_folder,
            "1.10",
            expected_tree=preview.proposed_tree,
            expected_asset_manifest=preview.proposed_asset_manifest,
            patch_overlay=True,
        )

        self.assertEqual(
            self.translated.joinpath("data/System.json").read_text(encoding="utf-8"),
            '{\n    "version": 2\n}',
        )
        self.assertTrue(self.translated.joinpath("data/Unchanged.json").is_file())
        self.assertTrue(self.translated.joinpath("game.txt").is_file())
        self.assertEqual(
            self.translated.joinpath("movies/ending.gdat").read_bytes(), b"new movie"
        )
        self.assertEqual(
            self.translated.joinpath("movies/unchanged.gdat").read_bytes(), b"keep movie"
        )

    def test_copy_over_patch_rejects_a_data_folder_selected_as_the_game_root(self):
        self.write_versions("old\n", "translated\n", "unused\n")
        for folder in (self.old, self.translated):
            folder.joinpath("data").mkdir()
            for name in ("Actors.json", "Items.json", "System.json"):
                folder.joinpath("data", name).write_text("[]", encoding="utf-8")
        patch_folder = self.root / "Ver.1.1_patch"
        patch_folder.joinpath("data").mkdir(parents=True)
        for name in ("Actors.json", "Items.json", "System.json"):
            patch_folder.joinpath("data", name).write_text("[]", encoding="utf-8")
        bootstrap_repository(self.translated, self.old, "1.00")

        with self.assertRaisesRegex(
            GitWorkflowError, "Select the game root instead"
        ):
            preview_official_update(
                self.translated / "data",
                patch_folder,
                "1.10",
                patch_overlay=True,
            )

    def test_conflicting_file_uses_normalized_new_official_copy_and_is_reported(self):
        self.write_versions(
            '{"name":"Japanese","value":1}\n',
            '{"name":"English","value":1}\n',
            '{"name":"Changed Japanese","value":2}\n',
            "data.json",
        )
        bootstrap_repository(self.translated, self.old, "1.00")

        preview = preview_official_update(self.translated, self.new, "1.03")
        self.assertTrue(preview.file_changes[0].whole_file_replaced)
        result = apply_official_update(self.translated, self.new, "1.03")

        self.assertEqual(result.official_won_paths, ("data.json",))
        expected = json.dumps(
            json.loads(self.new.joinpath("data.json").read_text()),
            indent=4,
            ensure_ascii=False,
        ).encode("utf-8")
        self.assertEqual(
            self.translated.joinpath("data.json").read_bytes(), expected
        )

    def test_conflict_uses_official_hunk_without_discarding_other_translations(self):
        old_lines = [f"unchanged {index}\n" for index in range(20)]
        translated_lines = old_lines.copy()
        official_lines = old_lines.copy()
        old_lines[1] = "Japanese source\n"
        translated_lines[1] = "English replaced source\n"
        official_lines[1] = "Changed Japanese source\n"
        translated_lines[10] = "English translation must remain\n"
        official_lines[17] = "New official feature\n"
        self.write_versions(
            "".join(old_lines),
            "".join(translated_lines),
            "".join(official_lines),
        )
        bootstrap_repository(self.translated, self.old, "1.00")

        preview = preview_official_update(self.translated, self.new, "1.03")
        self.assertFalse(preview.file_changes[0].whole_file_replaced)
        self.assertEqual(
            preview.file_changes[0].result, "Merged with translation edits"
        )
        result = apply_official_update(self.translated, self.new, "1.03")

        self.assertEqual(result.official_won_paths, ("game.txt",))
        merged = self.translated.joinpath("game.txt").read_text()
        self.assertIn("Changed Japanese source", merged)
        self.assertNotIn("English replaced source", merged)
        self.assertIn("English translation must remain", merged)
        self.assertIn("New official feature", merged)

    def test_plugins_js_formatting_preserves_translation_plugins_during_update(self):
        old = (
            '// Generated by RPG Maker.\nvar $plugins = '
            '[{"name":"Base","status":true,"description":"Japanese",'
            '"parameters":{"version":"1"}}];\n'
        )
        translated = (
            '// Generated by RPG Maker.\nvar $plugins = '
            '[{"name":"Base","status":true,"description":"English",'
            '"parameters":{"version":"1"}},'
            '{"name":"TLInspector","status":true,"description":"Tool",'
            '"parameters":{}}];\n'
        )
        new = (
            '// Generated by RPG Maker.\nvar $plugins = '
            '[{"name":"Base","status":true,"description":"Japanese",'
            '"parameters":{"version":"2"}}];\n'
        )
        self.write_versions(old, translated, new, "plugins.js")
        bootstrap_repository(self.translated, self.old, "1.00")

        result = apply_official_update(self.translated, self.new, "1.03")

        merged = self.translated.joinpath("plugins.js").read_text()
        self.assertIn('"description": "English"', merged)
        self.assertIn('"version": "2"', merged)
        self.assertIn('"name": "TLInspector"', merged)
        self.assertNotEqual(
            self.git(self.translated, "rev-parse", "main:plugins.js"),
            self.git(self.translated, "rev-parse", "original:plugins.js"),
        )
        self.assertTrue(result.complete)

    def test_sparse_engine_data_is_never_parsed_or_compacted(self):
        old = b'[null,{"id":1},null,null,{"id":4}]\n'
        new = b'[null,{"id":1},null,{"id":3},null,{"id":5}]\n'
        self.old.joinpath("Map008.json").write_bytes(old)
        self.translated.joinpath("Map008.json").write_bytes(old)
        self.new.joinpath("Map008.json").write_bytes(new)
        self.old.joinpath("dialogue.txt").write_text("Japanese\n")
        self.translated.joinpath("dialogue.txt").write_text("English\n")
        self.new.joinpath("dialogue.txt").write_text("Japanese\n")
        bootstrap_repository(self.translated, self.old, "1.00")

        apply_official_update(self.translated, self.new, "1.03")

        expected = json.dumps(json.loads(new), indent=4, ensure_ascii=False).encode("utf-8")
        self.assertEqual(self.translated.joinpath("Map008.json").read_bytes(), expected)
        parsed = json.loads(expected)
        self.assertIsNone(parsed[0])
        self.assertIsNone(parsed[2])
        self.assertIsNone(parsed[4])
        self.assertEqual(parsed[3]["id"], 3)
        self.assertEqual(parsed[5]["id"], 5)
        original_blob = subprocess.run(
            ["git", "-C", str(self.translated), "show", "original:Map008.json"],
            check=True,
            capture_output=True,
        ).stdout
        self.assertEqual(original_blob, expected)

    def test_preview_reports_file_changes_formatting_overlap_and_json_warnings(self):
        for folder in (self.old, self.translated, self.new):
            folder.joinpath(".gitignore").write_text("cache/\n!*.png\n")
        self.old.joinpath("data.json").write_text('{"name":"Japanese","value":1}')
        self.translated.joinpath("data.json").write_text(
            json.dumps({"name": "English", "value": 1}, indent=4, ensure_ascii=False)
        )
        self.new.joinpath("data.json").write_text('{"name":"Japanese","value":2}')
        self.old.joinpath("removed.txt").write_text("old\n")
        self.translated.joinpath("removed.txt").write_text("old\n")
        self.new.joinpath("added.txt").write_text("new\n")
        base_lines = [f"line {index}" for index in range(10)]
        translated_lines = list(base_lines)
        translated_lines[1] = "translated line"
        official_lines = list(base_lines)
        official_lines[8] = "updated official line"
        self.old.joinpath("mergeable.txt").write_text("\n".join(base_lines) + "\n")
        self.translated.joinpath("mergeable.txt").write_text(
            "\n".join(translated_lines) + "\n"
        )
        self.new.joinpath("mergeable.txt").write_text(
            "\n".join(official_lines) + "\n"
        )
        self.old.joinpath("portrait.png").write_bytes(b"\x89PNG\x00old")
        self.translated.joinpath("portrait.png").write_bytes(b"\x89PNG\x00translated")
        self.new.joinpath("portrait.png").write_bytes(b"\x89PNG\x00official")
        for folder in (self.old, self.translated):
            folder.joinpath("broken.json").write_text('{"duplicate":1,"duplicate":2}')
        self.new.joinpath("broken.json").write_text('{"duplicate":3,"duplicate":4}')
        self.new.joinpath("cache").mkdir()
        self.new.joinpath("cache/generated.bin").write_bytes(b"ignored")
        bootstrap_repository(self.translated, self.old, "1.00")

        preview = preview_official_update(self.translated, self.new, "1.03")

        self.assertEqual(preview.added_paths, ("added.txt",))
        self.assertEqual(preview.deleted_paths, ("removed.txt",))
        self.assertIn("data.json", preview.modified_paths)
        self.assertIn("data.json", preview.overlapping_paths)
        self.assertIn("data.json", preview.formatted_json_paths)
        self.assertTrue(
            any(
                "broken.json" in warning and "duplicate object key" in warning
                for warning in preview.json_warnings
            )
        )
        self.assertIn("cache/generated.bin", preview.ignored_paths)
        self.assertNotIn("cache/generated.bin", preview.added_paths)
        changes = {change.path: change for change in preview.file_changes}
        self.assertEqual(changes["added.txt"].added_lines, 1)
        self.assertEqual(changes["removed.txt"].deleted_lines, 1)
        self.assertTrue(changes["data.json"].whole_file_replaced)
        self.assertFalse(changes["mergeable.txt"].whole_file_replaced)
        self.assertEqual(
            changes["mergeable.txt"].result, "Merged with translation edits"
        )
        self.assertTrue(changes["portrait.png"].is_image)
        self.assertTrue(changes["portrait.png"].whole_file_replaced)
        self.assertIn("image replaced", changes["portrait.png"].result)
        image = next(
            change for change in preview.image_changes if change.path == "portrait.png"
        )
        self.assertEqual(image.change, "Replaced")
        self.assertTrue(image.tracked)
        self.assertTrue(image.warning)

        self.new.joinpath("added.txt").write_text("changed after preview\n")
        with self.assertRaisesRegex(GitWorkflowError, "changed after preview"):
            apply_official_update(
                self.translated,
                self.new,
                "1.03",
                expected_tree=preview.proposed_tree,
            )

    def test_ignored_official_assets_are_previewed_and_synchronized_outside_git(self):
        self.write_versions("old\n", "translated\n", "translated\n")
        self.old.joinpath("replaced.png").write_bytes(b"old image")
        self.translated.joinpath("replaced.png").write_bytes(b"old image")
        self.new.joinpath("replaced.png").write_bytes(b"new image")
        self.old.joinpath("removed.png").write_bytes(b"removed image")
        self.translated.joinpath("removed.png").write_bytes(b"removed image")
        self.new.joinpath("added.png").write_bytes(b"added image")
        self.old.joinpath("theme.ogg").write_bytes(b"old audio")
        self.translated.joinpath("theme.ogg").write_bytes(b"old audio")
        self.new.joinpath("theme.ogg").write_bytes(b"new audio")
        self.old.joinpath("unchanged.png").write_bytes(b"official image")
        self.translated.joinpath("unchanged.png").write_bytes(b"local image")
        self.new.joinpath("unchanged.png").write_bytes(b"official image")
        self.old.joinpath("Save01.dat").write_bytes(b"bundled save")
        self.translated.joinpath("Save01.dat").write_bytes(b"player save")
        self.new.joinpath("Save01.dat").write_bytes(b"changed bundled save")
        bootstrap_repository(self.translated, self.old, "1.00")

        preview = preview_official_update(self.translated, self.new, "1.03")
        self.assertTrue(preview.content_change_expected)

        images = {change.path: change for change in preview.image_changes}
        self.assertEqual(images["added.png"].change, "Added")
        self.assertEqual(images["removed.png"].change, "Removed")
        self.assertEqual(images["replaced.png"].change, "Replaced")
        self.assertTrue(all(not change.tracked for change in images.values()))
        self.assertTrue(all(not change.warning for change in images.values()))
        self.assertTrue(
            all("outside Git" in change.result for change in images.values())
        )
        self.assertTrue(all(not change.is_image for change in preview.file_changes))
        audio = next(
            change
            for change in preview.external_changes
            if change.path == "theme.ogg"
        )
        self.assertEqual(audio.category, "Audio")
        self.assertEqual(audio.change, "Replaced")
        self.assertNotIn(
            "unchanged.png", {change.path for change in preview.external_changes}
        )

        self.new.joinpath("theme.ogg").write_bytes(b"changed after preview")
        with self.assertRaisesRegex(GitWorkflowError, "assets changed after preview"):
            apply_official_update(
                self.translated,
                self.new,
                "1.03",
                expected_tree=preview.proposed_tree,
                expected_asset_manifest=preview.proposed_asset_manifest,
            )
        self.new.joinpath("theme.ogg").write_bytes(b"new audio")

        result = apply_official_update(
            self.translated,
            self.new,
            "1.03",
            expected_tree=preview.proposed_tree,
            expected_asset_manifest=preview.proposed_asset_manifest,
        )

        self.assertEqual(self.translated.joinpath("replaced.png").read_bytes(), b"new image")
        self.assertEqual(self.translated.joinpath("added.png").read_bytes(), b"added image")
        self.assertFalse(self.translated.joinpath("removed.png").exists())
        self.assertEqual(self.translated.joinpath("theme.ogg").read_bytes(), b"new audio")
        self.assertEqual(self.translated.joinpath("unchanged.png").read_bytes(), b"local image")
        self.assertEqual(self.translated.joinpath("Save01.dat").read_bytes(), b"player save")
        self.assertTrue(result.external_changes)
        self.assertTrue(result.content_changed)

    def test_update_explicitly_records_when_official_patch_is_already_present(self):
        self.write_versions("old official\n", "new official\n", "new official\n")
        bootstrap_repository(self.translated, self.old, "1.00")
        translation_before = self.git(self.translated, "rev-parse", "main")

        preview = preview_official_update(self.translated, self.new, "1.03")

        self.assertEqual(preview.already_present_paths, ("game.txt",))
        self.assertEqual(preview.translation_change_paths, ())
        self.assertFalse(preview.content_change_expected)
        result = apply_official_update(
            self.translated,
            self.new,
            "1.03",
            expected_tree=preview.proposed_tree,
            expected_original_commit=preview.original_commit,
            expected_translation_commit=preview.translation_commit,
        )

        self.assertFalse(result.content_changed)
        self.assertEqual(result.already_present_paths, ("game.txt",))
        self.assertEqual(
            self.translated.joinpath("game.txt").read_text(), "new official\n"
        )
        self.assertEqual(
            self.git(
                self.translated,
                "diff-tree",
                "--no-commit-id",
                "--name-only",
                "-r",
                result.translation_commit,
            ),
            "",
        )
        self.assertEqual(
            self.git(self.translated, "rev-parse", f"{result.translation_commit}^"),
            translation_before,
        )
        self.assertIn(
            "record already-present original game version 1.03",
            self.git(self.translated, "show", "-s", "--format=%s", result.translation_commit),
        )
        self.assertEqual(inspect_repository(self.translated).translation_version, "1.03")

    def test_pending_conflict_can_abort_then_apply_registered_original(self):
        self.write_versions("old\n", "translated\n", "new official\n")
        self.old.joinpath("theme.ogg").write_bytes(b"old audio")
        self.translated.joinpath("theme.ogg").write_bytes(b"old audio")
        self.new.joinpath("theme.ogg").write_bytes(b"new audio")
        bootstrap_repository(self.translated, self.old, "1.00")

        pending = apply_official_update(
            self.translated, self.new, "1.03", auto_resolve=False
        )
        self.assertFalse(pending.complete)
        self.assertEqual(pending.pending_conflicts, ("game.txt",))
        self.assertTrue(inspect_repository(self.translated).pending_cherry_pick)
        self.assertEqual(self.translated.joinpath("theme.ogg").read_bytes(), b"old audio")

        aborted = abort_update(self.translated)
        self.assertFalse(aborted.pending_cherry_pick)
        self.assertEqual(self.translated.joinpath("game.txt").read_text(), "translated\n")
        self.assertEqual(aborted.original_version, "1.03")
        self.assertEqual(aborted.translation_version, "1.00")
        self.assertTrue(aborted.asset_sync_pending)

        applied = apply_registered_original(self.translated)
        self.assertEqual(applied.official_won_paths, ("game.txt",))
        self.assertEqual(self.translated.joinpath("game.txt").read_text(), "new official\n")
        self.assertEqual(self.translated.joinpath("theme.ogg").read_bytes(), b"new audio")
        self.assertFalse(inspect_repository(self.translated).asset_sync_pending)

    def test_existing_repository_without_original_is_reconciled_in_place(self):
        self.write_versions("Japanese\n", "English\n", "New\n")
        self.git(self.translated, "init", "-b", "main")
        self.git(self.translated, "config", "user.name", "Test")
        self.git(self.translated, "config", "user.email", "test@example.invalid")
        self.git(self.translated, "add", ".")
        self.git(self.translated, "commit", "-m", "existing translation")

        bootstrap_repository(self.translated, self.old, "1.00")
        status = inspect_repository(self.translated)

        self.assertEqual(status.current_branch, "main")
        self.assertEqual(status.translation_branch, "main")
        self.assertTrue(status.original_exists)
        self.assertTrue(status.translation_exists)
        self.assertFalse(self.git(self.translated, "branch", "--list", "translation"))
        self.assertEqual(self.translated.joinpath("game.txt").read_text(), "English\n")
        self.assertTrue(status.worktree_clean)

    def test_existing_original_can_register_and_switch_translation_branch(self):
        self.write_versions("Japanese\n", "English\n", "New\n")
        self.git(self.translated, "init", "-b", "main")
        self.git(self.translated, "config", "user.name", "Test")
        self.git(self.translated, "config", "user.email", "test@example.invalid")
        self.git(self.translated, "add", ".")
        self.git(self.translated, "commit", "-m", "translated game")
        translated_head = self.git(self.translated, "rev-parse", "HEAD")
        original_blob = self.git(self.translated, "hash-object", "-w", str(self.old / "game.txt"))
        tree_input = f"100644 blob {original_blob}\tgame.txt\n"
        original_tree = subprocess.run(
            ["git", "-C", str(self.translated), "mktree"],
            input=tree_input,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        original_commit = subprocess.run(
            ["git", "-C", str(self.translated), "commit-tree", original_tree, "-m", "original v1.00"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.git(self.translated, "branch", "original", original_commit)

        registered = register_translation_branch(self.translated, "1.00")
        self.assertEqual(self.git(self.translated, "rev-parse", "main^1"), translated_head)
        self.assertEqual(registered.version, "1.00")
        self.assertEqual(
            self.git(self.translated, "config", "--local", "dazedtl.translationBranch"),
            "main",
        )
        self.assertFalse(self.git(self.translated, "branch", "--list", "translation"))
        self.git(self.translated, "checkout", "original")
        switched = checkout_translation_branch(self.translated)
        self.assertEqual(switched.current_branch, "main")
        self.assertEqual(switched.translation_branch, "main")
        self.assertFalse(switched.asset_manifest_available)

        self.git(self.translated, "branch", "translation", "main")
        self.git(
            self.translated,
            "config",
            "--local",
            "dazedtl.translationBranch",
            "translation",
        )
        self.git(self.translated, "checkout", "translation")
        register_translation_branch(
            self.translated,
            "1.00",
            branch="main",
            replace=True,
        )
        reselected = inspect_repository(self.translated)
        self.assertEqual(reselected.current_branch, "main")
        self.assertEqual(reselected.translation_branch, "main")
        self.assertEqual(
            self.git(self.translated, "config", "--local", "dazedtl.translationBranch"),
            "main",
        )
        self.assertTrue(self.git(self.translated, "branch", "--list", "translation"))

        self.old.joinpath("unchanged.png").write_bytes(b"official image")
        self.translated.joinpath("unchanged.png").write_bytes(b"translated image")
        self.new.joinpath("unchanged.png").write_bytes(b"official image")
        self.new.joinpath("theme.ogg").write_bytes(b"new audio")
        with self.assertRaisesRegex(
            GitWorkflowError, r"does not match.*M game\.txt"
        ):
            preview_official_update(
                self.translated,
                self.new,
                "1.03",
                previous_official_game=self.new,
            )
        preview = preview_official_update(
            self.translated,
            self.new,
            "1.03",
            previous_official_game=self.old,
        )
        self.assertFalse(preview.asset_manifest_available)
        self.assertEqual(preview.external_changes[0].path, "theme.ogg")
        self.assertNotIn(
            "unchanged.png", {change.path for change in preview.external_changes}
        )
        apply_official_update(
            self.translated,
            self.new,
            "1.03",
            expected_tree=preview.proposed_tree,
            expected_asset_manifest=preview.proposed_asset_manifest,
            previous_official_game=self.old,
            expected_baseline_asset_manifest=preview.baseline_asset_manifest,
        )
        self.assertEqual(self.translated.joinpath("theme.ogg").read_bytes(), b"new audio")
        self.assertEqual(
            self.translated.joinpath("unchanged.png").read_bytes(), b"translated image"
        )
        self.assertTrue(inspect_repository(self.translated).asset_manifest_available)

    def test_legacy_baseline_preserves_updater_files_and_normalizes_asset_exceptions(self):
        self.write_versions("old official\n", "translated\n", "new official\n")
        ignore = "*.png_\n!translated-image.png_\n"
        self.translated.joinpath(".gitignore").write_text(ignore, encoding="utf-8")
        self.translated.joinpath("translated-image.png_").write_bytes(b"translated image")
        self.old.joinpath("translated-image.png_").write_bytes(b"official image")
        self.new.joinpath("translated-image.png_").write_bytes(b"official image")
        updater = self.root / "GameUpdate.bat"
        updater.write_text("legacy updater\n", encoding="utf-8")

        self.git(self.translated, "init", "-b", "main")
        self.git(self.translated, "config", "user.name", "Test")
        self.git(self.translated, "config", "user.email", "test@example.invalid")
        self.git(self.translated, "add", ".")
        self.git(self.translated, "commit", "-m", "translated game")

        tree_lines = []
        for name, source in (
            (".gitignore", self.translated / ".gitignore"),
            ("GameUpdate.bat", updater),
            ("game.txt", self.old / "game.txt"),
        ):
            blob = self.git(self.translated, "hash-object", "-w", str(source))
            tree_lines.append(f"100644 blob {blob}\t{name}")
        original_tree = subprocess.run(
            ["git", "-C", str(self.translated), "mktree"],
            input="\n".join(tree_lines) + "\n",
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        original_commit = subprocess.run(
            [
                "git",
                "-C",
                str(self.translated),
                "commit-tree",
                original_tree,
                "-m",
                "legacy original",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.git(self.translated, "branch", "original", original_commit)
        register_translation_branch(self.translated, "1.00")

        self.new.joinpath("translated-image.png_").write_bytes(
            b"changed official image"
        )
        changed_image_preview = preview_official_update(
            self.translated,
            self.new,
            "1.10",
            previous_official_game=self.old,
        )
        self.assertEqual(
            [
                (change.path, change.change, change.warning)
                for change in changed_image_preview.image_changes
            ],
            [("translated-image.png_", "Replaced", True)],
        )
        self.new.joinpath("translated-image.png_").write_bytes(b"official image")
        preview = preview_official_update(
            self.translated,
            self.new,
            "1.10",
            previous_official_game=self.old,
        )

        self.assertEqual(preview.changed_paths, ("game.txt",))
        self.assertEqual(preview.image_changes, ())

        apply_official_update(
            self.translated,
            self.new,
            "1.10",
            expected_tree=preview.proposed_tree,
            expected_original_commit=preview.original_commit,
            expected_translation_commit=preview.translation_commit,
            expected_asset_manifest=preview.proposed_asset_manifest,
            previous_official_game=self.old,
            expected_baseline_asset_manifest=preview.baseline_asset_manifest,
        )

        self.assertEqual(
            self.translated.joinpath("translated-image.png_").read_bytes(),
            b"translated image",
        )
        self.assertEqual(
            self.git(self.translated, "show", "original:translated-image.png_"),
            "official image",
        )
        normalized_paths = self.git(
            self.translated, "ls-tree", "-r", "--name-only", "original^"
        ).splitlines()
        self.assertIn("translated-image.png_", normalized_paths)
        self.assertIn("GameUpdate.bat", normalized_paths)

    def test_stored_baseline_excludes_tool_owned_files_from_official_patch(self):
        self.write_versions("old official\n", "translated\n", "new official\n")
        tool_files = {
            "GameUpdate.bat": b"registered launcher",
            "GameUpdate_linux.sh": b"registered launcher",
            "README.md": b"registered updater readme",
            "UberWolfCli.exe": b"registered helper",
            "UberWolfCli.LICENSE.txt": b"registered license",
            "gameupdate/patch-config.example.txt": b"registered example",
            "gameupdate/patch-config.txt": b"registered config",
            "gameupdate/patch.ps1": b"registered powershell",
            "gameupdate/patch.sh": b"registered shell",
            "gameupdate/helper.bin": b"registered ignored helper",
        }
        for relative, contents in tool_files.items():
            for folder in (self.old, self.translated):
                destination = folder / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(contents)

        self.new.joinpath("GameUpdate.bat").write_bytes(b"official collision")
        new_config = self.new / "gameupdate" / "patch-config.txt"
        new_config.parent.mkdir(parents=True)
        new_config.write_bytes(b"official collision")
        self.new.joinpath("gameupdate/new-tool.txt").write_bytes(b"new collision")
        self.new.joinpath("gameupdate/new-helper.bin").write_bytes(
            b"new ignored collision"
        )

        bootstrap_repository(self.translated, self.old, "1.00")
        self.assertTrue(inspect_repository(self.translated).asset_manifest_available)

        preview = preview_official_update(self.translated, self.new, "1.10")

        self.assertEqual(preview.changed_paths, ("game.txt",))
        self.assertEqual(preview.external_changes, ())
        preview_paths = {change.path for change in preview.file_changes}
        self.assertFalse(
            preview_paths
            & {
                ".gitignore",
                "GameUpdate.bat",
                "GameUpdate_linux.sh",
                "README.md",
                "UberWolfCli.exe",
                "UberWolfCli.LICENSE.txt",
                "gameupdate/patch-config.example.txt",
                "gameupdate/patch-config.txt",
                "gameupdate/patch.ps1",
                "gameupdate/patch.sh",
                "gameupdate/new-tool.txt",
                "gameupdate/new-helper.bin",
            }
        )

        apply_official_update(
            self.translated,
            self.new,
            "1.10",
            expected_tree=preview.proposed_tree,
            expected_original_commit=preview.original_commit,
            expected_translation_commit=preview.translation_commit,
            expected_asset_manifest=preview.proposed_asset_manifest,
        )

        for relative, contents in tool_files.items():
            self.assertEqual(self.translated.joinpath(relative).read_bytes(), contents)
        self.assertFalse(self.translated.joinpath("gameupdate/new-tool.txt").exists())
        self.assertFalse(
            self.translated.joinpath("gameupdate/new-helper.bin").exists()
        )
        self.assertEqual(
            self.git(self.translated, "show", "original:GameUpdate.bat"),
            "registered launcher",
        )

    def test_existing_original_uses_current_ignored_assets_without_clean_folder(self):
        self.write_versions("old official\n", "translated\n", "new official\n")
        self.translated.joinpath(".gitignore").write_text(
            "*.*\n!*.txt\n!.gitignore\n!tracked.png_\n", encoding="utf-8"
        )
        self.translated.joinpath("theme.ogg").write_bytes(b"current audio")
        self.translated.joinpath("tracked.png_").write_bytes(b"current image")
        self.translated.joinpath("PROJECT_PLAN.md").write_text(
            "translation workspace plan\n", encoding="utf-8"
        )
        for relative in ("Dictionaries/en-US.bdic", "skills/game.md"):
            resource = self.translated / relative
            resource.parent.mkdir(parents=True, exist_ok=True)
            resource.write_text("translation tool resource\n", encoding="utf-8")
        self.new.joinpath("theme.ogg").write_bytes(b"new official audio")
        self.new.joinpath("tracked.png_").write_bytes(b"new official image")

        self.git(self.translated, "init", "-b", "main")
        self.git(self.translated, "config", "user.name", "Test")
        self.git(self.translated, "config", "user.email", "test@example.invalid")
        self.git(self.translated, "add", ".")
        self.git(self.translated, "commit", "-m", "translated game")
        original_blob = self.git(
            self.translated, "hash-object", "-w", str(self.old / "game.txt")
        )
        ignore_blob = self.git(
            self.translated,
            "rev-parse",
            "HEAD:.gitignore",
        )
        original_tree = subprocess.run(
            ["git", "-C", str(self.translated), "mktree"],
            input=(
                f"100644 blob {ignore_blob}\t.gitignore\n"
                f"100644 blob {original_blob}\tgame.txt\n"
            ),
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        original_commit = subprocess.run(
            [
                "git",
                "-C",
                str(self.translated),
                "commit-tree",
                original_tree,
                "-m",
                "legacy original",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.git(self.translated, "branch", "original", original_commit)
        register_translation_branch(self.translated, "1.00")

        preview = preview_official_update(self.translated, self.new, "1.10")

        self.assertIsNone(preview.baseline_source_root)
        self.assertEqual(
            [(change.path, change.change) for change in preview.external_changes],
            [("theme.ogg", "Replaced")],
        )
        self.assertEqual(
            preview.preserved_translation_asset_paths,
            ("tracked.png_",),
        )
        self.assertEqual(preview.image_changes, ())

        apply_official_update(
            self.translated,
            self.new,
            "1.10",
            expected_tree=preview.proposed_tree,
            expected_original_commit=preview.original_commit,
            expected_translation_commit=preview.translation_commit,
            expected_asset_manifest=preview.proposed_asset_manifest,
            expected_baseline_asset_manifest=preview.baseline_asset_manifest,
        )

        self.assertEqual(
            self.translated.joinpath("theme.ogg").read_bytes(),
            b"new official audio",
        )
        self.assertEqual(
            self.translated.joinpath("tracked.png_").read_bytes(),
            b"current image",
        )
        self.assertNotIn(
            "tracked.png_",
            self.git(
                self.translated, "ls-tree", "-r", "--name-only", "original"
            ).splitlines(),
        )
        self.assertTrue(self.translated.joinpath("PROJECT_PLAN.md").is_file())
        self.assertTrue(self.translated.joinpath("Dictionaries/en-US.bdic").is_file())
        self.assertTrue(self.translated.joinpath("skills/game.md").is_file())
        self.assertTrue(inspect_repository(self.translated).asset_manifest_available)

    def test_repair_fallback_baseline_with_previous_official(self):
        self.write_versions("old official\n", "translated\n", "new official\n")
        self.translated.joinpath(".gitignore").write_text(
            "*.*\n!*.txt\n!.gitignore\n!tracked.png_\n", encoding="utf-8"
        )
        self.translated.joinpath("tracked.png_").write_bytes(b"translated image")
        self.new.joinpath("tracked.png_").write_bytes(b"new official image")

        bootstrap_repository(self.translated, self.old, "1.00")

        initial_preview = preview_official_update(
            self.translated,
            self.new,
            "1.10",
        )
        self.assertEqual(
            initial_preview.preserved_translation_asset_paths,
            ("tracked.png_",),
        )
        apply_official_update(
            self.translated,
            self.new,
            "1.10",
            expected_tree=initial_preview.proposed_tree,
            expected_original_commit=initial_preview.original_commit,
            expected_translation_commit=initial_preview.translation_commit,
            expected_asset_manifest=initial_preview.proposed_asset_manifest,
            expected_baseline_asset_manifest=initial_preview.baseline_asset_manifest,
        )

        fallback_status = inspect_repository(self.translated)
        self.assertTrue(fallback_status.asset_manifest_available)
        self.assertTrue(fallback_status.asset_baseline_repair_needed)

        newer = self.root / "Original v1.20"
        newer.mkdir()
        newer.joinpath("game.txt").write_text("newer official\n", encoding="utf-8")
        newer.joinpath("tracked.png_").write_bytes(b"newer official image")

        repaired_preview = preview_official_update(
            self.translated,
            newer,
            "1.20",
            previous_official_game=self.new,
        )
        self.assertIn(
            ("tracked.png_", "Replaced", True),
            [
                (change.path, change.change, change.warning)
                for change in repaired_preview.image_changes
                if change.tracked
            ],
        )

        apply_official_update(
            self.translated,
            newer,
            "1.20",
            expected_tree=repaired_preview.proposed_tree,
            expected_original_commit=repaired_preview.original_commit,
            expected_translation_commit=repaired_preview.translation_commit,
            expected_asset_manifest=repaired_preview.proposed_asset_manifest,
            previous_official_game=self.new,
            expected_baseline_asset_manifest=repaired_preview.baseline_asset_manifest,
        )

        self.assertEqual(
            self.translated.joinpath("tracked.png_").read_bytes(),
            b"newer official image",
        )
        self.assertFalse(
            inspect_repository(self.translated).asset_baseline_repair_needed
        )

    def test_nested_game_folder_updates_only_its_repository_prefix(self):
        repo = self.translated
        game = repo / "game"
        game.mkdir()
        game.joinpath("dialogue.txt").write_text("English\n")
        repo.joinpath("README.md").write_text("keep me\n")
        self.old.joinpath("dialogue.txt").write_text("Japanese\n")
        self.new.joinpath("dialogue.txt").write_text("New Japanese\n")
        self.old.joinpath("theme.ogg").write_bytes(b"old audio")
        game.joinpath("theme.ogg").write_bytes(b"old audio")
        self.new.joinpath("theme.ogg").write_bytes(b"new audio")
        self.git(repo, "init", "-b", "main")
        self.git(repo, "config", "user.name", "Test")
        self.git(repo, "config", "user.email", "test@example.invalid")
        self.git(repo, "add", ".")
        self.git(repo, "commit", "-m", "translation workspace")
        bootstrap_repository(game, self.old, "1.00")

        result = apply_official_update(game, self.new, "1.03")

        self.assertTrue(result.complete)
        self.assertEqual(repo.joinpath("README.md").read_text(), "keep me\n")
        self.assertEqual(game.joinpath("dialogue.txt").read_text(), "New Japanese\n")
        self.assertEqual(game.joinpath("theme.ogg").read_bytes(), b"new audio")

    def test_complete_legacy_branches_can_record_missing_version_metadata(self):
        self.write_versions("Japanese\n", "English\n", "New\n")
        self.git(self.translated, "init", "-b", "translation")
        self.git(self.translated, "config", "user.name", "Test")
        self.git(self.translated, "config", "user.email", "test@example.invalid")
        self.git(self.translated, "add", ".")
        self.git(self.translated, "commit", "-m", "legacy translated game")
        translation_tree = self.git(self.translated, "rev-parse", "HEAD^{tree}")
        original_blob = self.git(
            self.translated, "hash-object", "-w", str(self.old / "game.txt")
        )
        original_tree = subprocess.run(
            ["git", "-C", str(self.translated), "mktree"],
            input=f"100644 blob {original_blob}\tgame.txt\n",
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        original_commit = subprocess.run(
            [
                "git",
                "-C",
                str(self.translated),
                "commit-tree",
                original_tree,
                "-m",
                "legacy original",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.git(self.translated, "branch", "original", original_commit)

        result = record_version_metadata(self.translated, "1.00")
        status = inspect_repository(self.translated)

        self.assertEqual(status.original_version, "1.00")
        self.assertEqual(status.translation_version, "1.00")
        self.assertEqual(
            self.git(self.translated, "rev-parse", "translation^{tree}"),
            translation_tree,
        )
        self.assertEqual(
            self.git(self.translated, "rev-parse", "original^{tree}"),
            original_tree,
        )
        self.assertEqual(result.version, "1.00")
        self.assertTrue(status.worktree_clean)

    @unittest.skipUnless(hasattr(os, "symlink"), "symbolic links unavailable")
    def test_bootstrap_rejects_symbolic_links_in_official_tree(self):
        self.write_versions("old\n", "translated\n", "new\n")
        os.symlink(self.old / "game.txt", self.old / "linked.txt")
        with self.assertRaisesRegex(GitWorkflowError, "Symbolic links"):
            bootstrap_repository(self.translated, self.old, "1.00")


class VersionUpdateUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_prepare_card_recognizes_a_legacy_main_and_original_layout(self):
        from gui.git_prepare import GitPreparationCard

        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary)
            game.joinpath("game.txt").write_text("English\n")
            subprocess.run(
                ["git", "-C", str(game), "init", "-b", "main"], check=True,
                capture_output=True,
            )
            for key, value in (
                ("user.name", "Test"),
                ("user.email", "test@example.invalid"),
            ):
                subprocess.run(
                    ["git", "-C", str(game), "config", key, value], check=True
                )
            subprocess.run(["git", "-C", str(game), "add", "."], check=True)
            subprocess.run(
                ["git", "-C", str(game), "commit", "-m", "translated game"],
                check=True,
                capture_output=True,
            )
            original_file = game / "original.txt"
            original_file.write_text("Japanese\n")
            original_blob = subprocess.run(
                ["git", "-C", str(game), "hash-object", "-w", str(original_file)],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            original_file.unlink()
            original_tree = subprocess.run(
                ["git", "-C", str(game), "mktree"],
                input=f"100644 blob {original_blob}\tgame.txt\n",
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            original_commit = subprocess.run(
                [
                    "git", "-C", str(game), "commit-tree", original_tree,
                    "-m", "original v1.00",
                ],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            subprocess.run(
                ["git", "-C", str(game), "branch", "original", original_commit],
                check=True,
            )
            card = GitPreparationCard()
            try:
                card.set_game_root(game)
                self.assertEqual(card._action_kind, "register")
                self.assertEqual(card.action_btn.text(), "Register translated game")
                self.assertIn("Register main as the translated branch", card.status_label.text())
                self.assertTrue(card.original_row.isHidden())

                card.version_edit.setText("1.00")
                with (
                    patch(
                        "gui.git_prepare.QMessageBox.question",
                        return_value=QMessageBox.No,
                    ),
                    patch.object(card, "_run") as run,
                ):
                    card._start_action()
                    run.assert_not_called()

                with (
                    patch(
                        "gui.git_prepare.QMessageBox.question",
                        return_value=QMessageBox.Yes,
                    ),
                    patch.object(card, "_run") as run,
                ):
                    card._start_action()
                    operation = run.call_args.args[0]
                operation()
                card.refresh_status()
                self.assertEqual(card._action_kind, "")
                self.assertIn("Ready", card.status_label.text())
                status = inspect_repository(game)
                self.assertEqual(status.current_branch, "main")
                self.assertEqual(status.translation_branch, "main")
                self.assertFalse(
                    subprocess.run(
                        ["git", "-C", str(game), "branch", "--list", "translation"],
                        check=True,
                        capture_output=True,
                        text=True,
                    ).stdout.strip()
                )
            finally:
                card.close()

    def test_prepare_card_bootstraps_from_selected_game_without_original_browse(self):
        from gui.git_prepare import GitPreparationCard

        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary)
            game.joinpath("game.txt").write_text("Japanese\n")
            card = GitPreparationCard()
            try:
                card.set_game_root(game)
                self.assertEqual(card._action_kind, "bootstrap")
                self.assertEqual(card.action_btn.text(), "Create version tracking")
                self.assertTrue(card.original_row.isHidden())
                self.assertIn("this game folder", card.status_label.text())

                card.version_edit.setText("1.00")
                with patch.object(card, "_run") as run:
                    card._start_action()
                    operation = run.call_args.args[0]
                operation()
                card.refresh_status()
                self.assertEqual(card._action_kind, "")
                self.assertIn("Ready", card.status_label.text())
                status = inspect_repository(game)
                self.assertEqual(status.original_version, "1.00")
                self.assertEqual(status.translation_version, "1.00")
                self.assertEqual(status.current_branch, "main")
                self.assertEqual(
                    subprocess.run(
                        ["git", "-C", str(game), "show", "original:game.txt"],
                        check=True,
                        capture_output=True,
                        text=True,
                    ).stdout,
                    "Japanese\n",
                )
            finally:
                card.close()

    def test_sidebar_page_exposes_git_bootstrap_and_update_actions(self):
        from gui.version_update_tab import VersionUpdateTab

        tab = VersionUpdateTab()
        try:
            self.assertEqual(tab.preview_btn.text(), "Preview update")
            self.assertEqual(tab.update_btn.text(), "Apply update")
            self.assertFalse(tab.patch_overlay_check.isChecked())
            self.assertIn("copy its files", tab.patch_overlay_check.text())
            tab.new_edit.setText("/tmp/Ver.1.1_patch")
            self.assertEqual(tab.new_version_edit.text(), "1.1")
            self.assertTrue(tab.patch_overlay_check.isChecked())
            self.assertFalse(tab.update_btn.isEnabled())
            self.assertTrue(tab.bootstrap_card.isHidden())
            self.assertTrue(tab.update_card.isHidden())
            self.assertTrue(tab.refresh_btn.isHidden())

            with tempfile.TemporaryDirectory() as temporary:
                tab.current_edit.setText(temporary)
                tab.refresh_status()
                self.assertFalse(tab.bootstrap_card.isHidden())
                self.assertTrue(tab.update_card.isHidden())
                self.assertFalse(tab.show_bootstrap_btn.isHidden())
                self.assertTrue(tab.bootstrap_fields.isHidden())

                tab._show_bootstrap_fields()
                self.assertFalse(tab.bootstrap_fields.isHidden())
                self.assertTrue(tab.show_bootstrap_btn.isHidden())
        finally:
            tab.close()

        with tempfile.TemporaryDirectory() as temporary:
            parent = QWidget()
            workflow_tab = QWidget(parent)
            workflow_tab.folder_edit = QLineEdit(workflow_tab)
            workflow_tab.folder_edit.setText(temporary)
            parent.workflow_tab = workflow_tab
            parent.wolf_workflow_tab = None
            synced = VersionUpdateTab(parent)
            try:
                self.assertEqual(synced.current_edit.text(), temporary)
                self.assertFalse(synced.bootstrap_card.isHidden())
            finally:
                parent.close()

    def test_already_applied_versions_are_detected_from_git_history(self):
        from gui.version_update_tab import VersionUpdateTab

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old, translated = root / "Original v1.00", root / "Translated v1.00"
            new = root / "Original v1.03"
            old.mkdir()
            translated.mkdir()
            new.mkdir()
            old.joinpath("game.txt").write_text("Japanese\n")
            translated.joinpath("game.txt").write_text("English\n")
            new.joinpath("game.txt").write_text("New Japanese\n")
            for folder in (old, translated, new):
                folder.joinpath(".gitignore").write_text("!*.png\n")
            old.joinpath("portrait.png").write_bytes(b"\x89PNG\x00old")
            translated.joinpath("portrait.png").write_bytes(
                b"\x89PNG\x00translated"
            )
            new.joinpath("portrait.png").write_bytes(b"\x89PNG\x00official")
            old.joinpath("theme.ogg").write_bytes(b"old audio")
            translated.joinpath("theme.ogg").write_bytes(b"old audio")
            new.joinpath("theme.ogg").write_bytes(b"new audio")
            bootstrap_repository(translated, old, "1.00")
            tab = VersionUpdateTab()
            try:
                tab.current_edit.setText(str(translated))
                tab.refresh_status()
                self.assertIn("Original 1.00", tab.version_status.text())
                self.assertIn("Translated main 1.00", tab.version_status.text())
                self.assertTrue(tab.bootstrap_card.isHidden())
                self.assertFalse(tab.update_card.isHidden())
                self.assertTrue(tab.update_card.isEnabled())
                self.assertTrue(tab.baseline_panel.isHidden())
                registered_status = tab._status
                tab._status = replace(
                    registered_status, asset_manifest_available=False
                )
                tab._render_status(tab._status)
                self.assertFalse(tab.baseline_panel.isHidden())
                tab.new_edit.setText(str(new))
                tab.new_version_edit.setText("1.03")
                with (
                    patch.object(tab, "_run") as run,
                    patch("gui.version_update_tab.QMessageBox.warning") as warning,
                ):
                    tab._preview_update()
                    run.assert_called_once()
                    warning.assert_not_called()
                tab._status = registered_status
                tab._render_status(tab._status)
                preview = preview_official_update(translated, new, "1.03")
                tab._show_preview(preview)
                self.assertFalse(tab.preview_panel.isHidden())
                self.assertIn("2 warning", tab.preview_summary.text())
                self.assertIn("Git-tracked patch", tab.preview_expected.text())
                self.assertIn(
                    "images, audio, video, fonts, and other packaged files",
                    tab.preview_expected.text(),
                )
                replacement_group = tab.preview_changes.topLevelItem(0)
                self.assertTrue(
                    replacement_group.text(0).startswith(
                        "Warnings — entire file replaced"
                    )
                )
                replacement = replacement_group.child(0)
                self.assertEqual(replacement.text(0), "game.txt")
                self.assertEqual(replacement.text(2), "+1 / −1")
                self.assertIn("Entire translated file", replacement.text(3))
                image_warning_group = tab.preview_changes.topLevelItem(1)
                self.assertTrue(
                    image_warning_group.text(0).startswith(
                        "⚠ Warnings — tracked images"
                    )
                )
                self.assertIn(
                    "will be replaced", image_warning_group.child(0).text(3)
                )
                asset_groups = [
                    tab.preview_changes.topLevelItem(index)
                    for index in range(tab.preview_changes.topLevelItemCount())
                ]
                audio_group = next(
                    group
                    for group in asset_groups
                    if group.text(0).startswith("Other game assets replaced")
                )
                self.assertEqual(audio_group.child(0).text(0), "theme.ogg")
                self.assertEqual(audio_group.child(0).text(2), "Audio")
                self.assertIn("outside Git", audio_group.child(0).text(3))
                self.assertTrue(tab.update_btn.isEnabled())

                protected_preview = replace(
                    preview,
                    added_paths=(),
                    modified_paths=(),
                    deleted_paths=(),
                    overlapping_paths=(),
                    already_present_paths=(),
                    file_changes=(),
                    image_changes=(),
                    external_changes=(),
                    preserved_translation_asset_paths=("img/translated.png_",),
                )
                tab._show_preview(protected_preview)
                self.assertIn("Protected: 1 tracked", tab.preview_notice.text())
                self.assertTrue(
                    tab.preview_changes.topLevelItem(0)
                    .text(0)
                    .startswith("Preserved tracked translation assets")
                )
                self.assertEqual(
                    tab.preview_changes.topLevelItem(0).child(0).text(1),
                    "Preserved",
                )
                tab._status = replace(
                    registered_status, asset_manifest_available=False
                )
                with (
                    patch.object(tab, "_run") as run,
                    patch("gui.version_update_tab.QMessageBox.warning") as warning,
                ):
                    tab._apply_update()
                    run.assert_called_once()
                    warning.assert_not_called()
                tab._status = registered_status
                repaired_status = replace(
                    registered_status,
                    asset_manifest_available=True,
                    asset_baseline_repair_needed=True,
                )
                tab._render_status(repaired_status)
                self.assertFalse(tab.baseline_panel.isHidden())

                new.joinpath("game.txt").write_text("English\n")
                new.joinpath("portrait.png").write_bytes(
                    b"\x89PNG\x00translated"
                )
                new.joinpath("theme.ogg").write_bytes(b"old audio")
                no_op_preview = preview_official_update(translated, new, "1.03")
                tab._show_preview(no_op_preview)
                self.assertIn("only the version", tab.preview_summary.text())
                self.assertIn("already present", tab.preview_expected.text())
                self.assertIn("No full-file", tab.preview_notice.text())
                self.assertEqual(
                    tab.update_btn.text(), "Record version (no content changes)"
                )

                new.joinpath(".gitignore").write_text("cache/\n")
                new.joinpath("cache").mkdir()
                new.joinpath("cache/generated.bin").write_bytes(b"ignored")
                ignored_preview = preview_official_update(translated, new, "1.03")
                tab._show_preview(ignored_preview)
                self.assertIn("No full-file", tab.preview_notice.text())
                tree_rows = []
                for index in range(tab.preview_changes.topLevelItemCount()):
                    group = tab.preview_changes.topLevelItem(index)
                    tree_rows.append(group.text(0))
                    tree_rows.extend(
                        group.child(child).text(0)
                        for child in range(group.childCount())
                    )
                tree_text = "\n".join(tree_rows)
                self.assertNotIn("excluded", tree_text.casefold())
                self.assertNotIn("generated.bin", tree_text)

                new.joinpath("broken.json").write_text(
                    '{"duplicate":1,"duplicate":2}'
                )
                warning_preview = preview_official_update(translated, new, "1.03")
                tab._show_preview(warning_preview)
                self.assertIn("warning", tab.preview_summary.text())
                self.assertTrue(
                    tab.preview_changes.topLevelItem(0)
                    .text(0)
                    .startswith("Warnings — structured files")
                )
            finally:
                tab.close()

    def test_review_queue_shows_pending_git_conflicts(self):
        from gui.version_update_tab import VersionUpdateTab

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old, translated, new = root / "old", root / "translated", root / "new"
            for folder, text in ((old, "old\n"), (translated, "translated\n"), (new, "new\n")):
                folder.mkdir()
                folder.joinpath("game.txt").write_text(text)
            bootstrap_repository(translated, old, "1.00")
            apply_official_update(translated, new, "1.03", auto_resolve=False)
            tab = VersionUpdateTab()
            try:
                tab.current_edit.setText(str(translated))
                tab.refresh_status()
                self.assertFalse(tab.recovery_card.isHidden())
                self.assertTrue(tab.update_card.isHidden())
                self.assertIn("game.txt", tab.conflict_summary.toPlainText())
                self.assertEqual(
                    tab.continue_btn.text(), "Use official conflicts and continue"
                )
                abort_update(translated)
                tab.refresh_status()
                self.assertFalse(tab.finish_assets_btn.isHidden())
                self.assertEqual(
                    tab.finish_assets_btn.text(), "Apply registered update"
                )
            finally:
                tab.close()
                if inspect_repository(translated).pending_cherry_pick:
                    abort_update(translated)
