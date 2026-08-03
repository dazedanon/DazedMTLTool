from __future__ import annotations

import os
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from PyQt5.QtWidgets import QApplication

from util.version_update import (
    GitWorkflowError,
    abort_update,
    apply_official_update,
    apply_registered_original,
    bootstrap_repository,
    checkout_translation_branch,
    inspect_repository,
    preview_official_update,
    register_translation_branch,
)


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
        self.assertEqual(self.git(self.translated, "show", "translation:game.txt"), "English")
        self.assertEqual(status.current_branch, "translation")
        self.assertEqual(status.original_version, "1.00")
        self.assertEqual(status.translation_version, "1.00")
        self.assertTrue(status.worktree_clean)
        self.assertEqual(result.repo_root, self.translated)
        self.assertTrue(result.gitignore_installed)
        self.assertTrue(self.translated.joinpath(".gitignore").is_file())

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
        for ref in ("original", "translation"):
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

        bootstrap_repository(self.translated, self.old, "1.00")

        self.assertTrue(legacy.joinpath("project.json").exists())
        self.assertTrue(inspect_repository(self.translated).worktree_clean)
        tracked = self.git(self.translated, "ls-tree", "-r", "--name-only", "translation")
        self.assertNotIn(".dazedtl/version_update", tracked)

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
            self.git(self.translated, "show", "translation:data.json"),
            expected_translation,
        )
        tracked = self.git(self.translated, "ls-tree", "-r", "--name-only", "translation")
        self.assertNotIn("save/slot.dat", tracked)
        self.assertNotIn("debug.log", tracked)
        self.assertTrue(self.translated.joinpath("save/slot.dat").exists())
        self.assertTrue(self.translated.joinpath("debug.log").exists())
        self.assertIn("save/slot.dat", result.ignored_paths)
        self.assertIn("debug.log", result.ignored_paths)
        self.assertIn("data.json", result.formatted_json_paths)
        combined_ignore = self.translated.joinpath(".gitignore").read_text()
        self.assertIn("# Ignore all files", combined_ignore)
        self.assertTrue(combined_ignore.endswith("save/\n*.log\n"))
        diff = self.git(self.translated, "diff", "original", "translation", "--", "data.json")
        self.assertIn('"name": "Japanese"', diff)
        self.assertIn('"name": "English"', diff)
        self.assertNotIn('{"name":', diff)

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

    def test_conflicting_file_uses_normalized_new_official_copy_and_is_reported(self):
        self.write_versions(
            '{"name":"Japanese","value":1}\n',
            '{"name":"English","value":1}\n',
            '{"name":"Changed Japanese","value":2}\n',
            "data.json",
        )
        bootstrap_repository(self.translated, self.old, "1.00")

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
            self.git(self.translated, "rev-parse", "translation:plugins.js"),
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
            folder.joinpath(".gitignore").write_text("cache/\n")
        self.old.joinpath("data.json").write_text('{"name":"Japanese","value":1}')
        self.translated.joinpath("data.json").write_text(
            json.dumps({"name": "English", "value": 1}, indent=4, ensure_ascii=False)
        )
        self.new.joinpath("data.json").write_text('{"name":"Japanese","value":2}')
        self.old.joinpath("removed.txt").write_text("old\n")
        self.translated.joinpath("removed.txt").write_text("old\n")
        self.new.joinpath("added.txt").write_text("new\n")
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

        self.new.joinpath("added.txt").write_text("changed after preview\n")
        with self.assertRaisesRegex(GitWorkflowError, "changed after preview"):
            apply_official_update(
                self.translated,
                self.new,
                "1.03",
                expected_tree=preview.proposed_tree,
            )

    def test_update_explicitly_records_when_official_patch_is_already_present(self):
        self.write_versions("old official\n", "new official\n", "new official\n")
        bootstrap_repository(self.translated, self.old, "1.00")
        translation_before = self.git(self.translated, "rev-parse", "translation")

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
        bootstrap_repository(self.translated, self.old, "1.00")

        pending = apply_official_update(
            self.translated, self.new, "1.03", auto_resolve=False
        )
        self.assertFalse(pending.complete)
        self.assertEqual(pending.pending_conflicts, ("game.txt",))
        self.assertTrue(inspect_repository(self.translated).pending_cherry_pick)

        aborted = abort_update(self.translated)
        self.assertFalse(aborted.pending_cherry_pick)
        self.assertEqual(self.translated.joinpath("game.txt").read_text(), "translated\n")
        self.assertEqual(aborted.original_version, "1.03")
        self.assertEqual(aborted.translation_version, "1.00")

        applied = apply_registered_original(self.translated)
        self.assertEqual(applied.official_won_paths, ("game.txt",))
        self.assertEqual(self.translated.joinpath("game.txt").read_text(), "new official\n")

    def test_existing_repository_without_original_is_reconciled_in_place(self):
        self.write_versions("Japanese\n", "English\n", "New\n")
        self.git(self.translated, "init", "-b", "main")
        self.git(self.translated, "config", "user.name", "Test")
        self.git(self.translated, "config", "user.email", "test@example.invalid")
        self.git(self.translated, "add", ".")
        self.git(self.translated, "commit", "-m", "existing translation")

        bootstrap_repository(self.translated, self.old, "1.00")
        status = inspect_repository(self.translated)

        self.assertEqual(status.current_branch, "translation")
        self.assertTrue(status.original_exists)
        self.assertTrue(status.translation_exists)
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
        self.assertEqual(self.git(self.translated, "rev-parse", "translation^1"), translated_head)
        self.assertEqual(registered.version, "1.00")
        self.git(self.translated, "checkout", "main")
        switched = checkout_translation_branch(self.translated)
        self.assertEqual(switched.current_branch, "translation")

    def test_nested_game_folder_updates_only_its_repository_prefix(self):
        repo = self.translated
        game = repo / "game"
        game.mkdir()
        game.joinpath("dialogue.txt").write_text("English\n")
        repo.joinpath("README.md").write_text("keep me\n")
        self.old.joinpath("dialogue.txt").write_text("Japanese\n")
        self.new.joinpath("dialogue.txt").write_text("New Japanese\n")
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

    def test_sidebar_page_exposes_git_bootstrap_and_update_actions(self):
        from gui.version_update_tab import VersionUpdateTab

        tab = VersionUpdateTab()
        try:
            self.assertIn("original branch", tab.bootstrap_explanation.text())
            self.assertEqual(tab.bootstrap_btn.text(), "Create original + translation branches")
            self.assertEqual(tab.preview_btn.text(), "Preview changes")
            self.assertEqual(tab.update_btn.text(), "Approve and apply")
            self.assertFalse(tab.update_btn.isEnabled())
            self.assertFalse(tab.update_card.isEnabled())
        finally:
            tab.close()

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
            bootstrap_repository(translated, old, "1.00")
            tab = VersionUpdateTab()
            try:
                tab.current_edit.setText(str(translated))
                tab.refresh_status()
                self.assertIn("Original version: 1.00", tab.version_status.text())
                self.assertIn("Translation version: 1.00", tab.version_status.text())
                self.assertTrue(tab.bootstrap_card.isHidden())
                self.assertTrue(tab.update_card.isEnabled())
                preview = preview_official_update(translated, new, "1.03")
                tab._show_preview(preview)
                self.assertIn("Modified: 1", tab.preview_details.toPlainText())
                self.assertIn(
                    "Potential translation overlaps", tab.preview_details.toPlainText()
                )
                self.assertTrue(tab.update_btn.isEnabled())

                new.joinpath("game.txt").write_text("English\n")
                no_op_preview = preview_official_update(translated, new, "1.03")
                tab._show_preview(no_op_preview)
                self.assertIn(
                    "No translated-game content changes are expected",
                    tab.preview_details.toPlainText(),
                )
                self.assertIn(
                    "Official release delta (previous original → new original):",
                    tab.preview_details.toPlainText(),
                )
                self.assertIn(
                    "Translation impact:\nFiles that would change: 0",
                    tab.preview_details.toPlainText(),
                )
                self.assertEqual(
                    tab.update_btn.text(), "Record version (no content changes)"
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
                self.assertIn("game.txt", tab.conflict_summary.toPlainText())
                self.assertEqual(
                    tab.continue_btn.text(), "Use official conflicts and continue"
                )
            finally:
                tab.close()
                abort_update(translated)
