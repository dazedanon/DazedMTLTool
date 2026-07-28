#!/usr/bin/env python3
"""Tests for whole-folder translated game version migration."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QMessageBox,
    QScrollArea,
    QTreeWidgetItem,
)

from util.version_update import (
    ConflictResolution,
    FileKind,
    RecoveryStatus,
    UpdateAction,
    UpdateDecision,
    VersionUpdateError,
    apply_in_place_update,
    apply_staged_update,
    detect_update_profile,
    scan_version_update,
)


class VersionUpdateTestBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.old = self.base / "old"
        self.current = self.base / "translated"
        self.new = self.base / "new"
        for root in (self.old, self.current, self.new):
            root.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def write(root: Path, relative: str, content: bytes | str) -> Path:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            path.write_text(content, encoding="utf-8")
        else:
            path.write_bytes(content)
        return path

    def write_all(self, relative: str, content: bytes | str):
        for root in (self.old, self.current, self.new):
            self.write(root, relative, content)


class GenericVersionUpdateTests(VersionUpdateTestBase):
    @staticmethod
    def git(repo: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def test_whole_folder_rules_cover_plugins_and_media(self):
        self.write_all("Game.exe", b"runtime-v1")
        self.write_all("img/title.png", b"official-image")
        self.current.joinpath("img/title.png").write_bytes(b"translated-image")
        self.write_all("audio/bgm/theme.ogg", b"old-audio")
        self.new.joinpath("audio/bgm/theme.ogg").write_bytes(b"new-audio")
        self.write(self.new, "js/plugins/NewFeature.js", "new plugin\n")
        self.write(self.current, "translator/readme.txt", "translation notes\n")

        plan = scan_version_update(
            self.current,
            self.new,
            old_root=self.old,
            old_version="1.00",
            new_version="1.03",
        )
        actions = {decision.relative_path: decision.action for decision in plan.decisions}

        self.assertEqual(actions["img/title.png"], UpdateAction.PRESERVE_TRANSLATED)
        self.assertEqual(actions["audio/bgm/theme.ogg"], UpdateAction.USE_NEW)
        self.assertEqual(actions["js/plugins/NewFeature.js"], UpdateAction.ADD_NEW)
        self.assertEqual(actions["translator/readme.txt"], UpdateAction.PRESERVE_ADDED)
        self.assertEqual(plan.profile_id, "generic")

        output = self.base / "updated"
        result = apply_staged_update(plan, output)

        self.assertEqual(output.joinpath("img/title.png").read_bytes(), b"translated-image")
        self.assertEqual(output.joinpath("audio/bgm/theme.ogg").read_bytes(), b"new-audio")
        self.assertEqual(
            output.joinpath("js/plugins/NewFeature.js").read_text(encoding="utf-8"),
            "new plugin\n",
        )
        self.assertTrue(result.report_path.is_file())

    def test_audio_always_follows_new_official_when_both_changed(self):
        self.write_all("audio/voice.ogg", b"old")
        self.current.joinpath("audio/voice.ogg").write_bytes(b"translated")
        self.new.joinpath("audio/voice.ogg").write_bytes(b"upstream")
        plan = scan_version_update(self.current, self.new, old_root=self.old)
        decision = plan.decisions[0]

        self.assertEqual(decision.action, UpdateAction.USE_NEW)
        apply_staged_update(plan, self.base / "audio-updated")
        self.assertEqual(
            self.base.joinpath("audio-updated/audio/voice.ogg").read_bytes(),
            b"upstream",
        )

    def test_audio_removed_from_new_official_is_deleted(self):
        self.write(self.old, "audio/obsolete.ogg", b"old")
        self.write(self.current, "audio/obsolete.ogg", b"current")

        plan = scan_version_update(self.current, self.new, old_root=self.old)

        self.assertEqual(plan.decisions[0].action, UpdateAction.DELETE)
        apply_staged_update(plan, self.base / "audio-removed")
        self.assertFalse(self.base.joinpath("audio-removed/audio/obsolete.ogg").exists())

    def test_non_audio_both_changed_binary_still_requires_resolution(self):
        self.write_all("archives/game.bin", b"old")
        self.current.joinpath("archives/game.bin").write_bytes(b"translated")
        self.new.joinpath("archives/game.bin").write_bytes(b"upstream")
        plan = scan_version_update(self.current, self.new, old_root=self.old)
        conflict = plan.decisions[0]

        self.assertEqual(conflict.action, UpdateAction.CONFLICT)
        self.assertEqual(conflict.recommended_resolution, ConflictResolution.USE_NEW)
        self.assertEqual(conflict.resolution, ConflictResolution.USE_NEW)
        self.assertTrue(conflict.resolution_is_automatic)
        self.assertTrue(conflict.translation_at_risk)
        self.assertFalse(conflict.blocking)
        apply_staged_update(plan, self.base / "resolved")
        self.assertEqual(
            self.base.joinpath("resolved/archives/game.bin").read_bytes(), b"upstream"
        )

    def test_repository_and_workspace_metadata_is_outside_game_scope(self):
        self.write_all("Game.exe", b"runtime")
        self.write(self.old, ".gitignore", "old rules\n")
        self.write(self.current, ".gitignore", "translation rules\n")
        self.write(self.new, ".gitignore", "new rules\n")
        self.write(self.current, "skills/game.md", "translation context\n")
        self.write(self.old, "gameupdate/patch-config.txt", "repo=old\n")
        self.write(self.current, "gameupdate/patch-config.txt", "repo=translation\n")
        self.write(self.new, "gameupdate/patch-config.txt", "repo=new-official\n")
        self.write(self.old, "GameUpdate.bat", "old launcher\n")
        self.write(self.current, "GameUpdate.bat", "translation launcher\n")
        self.write(self.new, "GameUpdate.bat", "new launcher\n")

        plan = scan_version_update(self.current, self.new, old_root=self.old)

        paths = {decision.relative_path for decision in plan.decisions}
        self.assertNotIn(".gitignore", paths)
        self.assertNotIn("skills/game.md", paths)
        self.assertNotIn("gameupdate/patch-config.txt", paths)
        self.assertNotIn("GameUpdate.bat", paths)
        apply_staged_update(plan, self.base / "metadata-updated")
        self.assertEqual(
            self.base.joinpath("metadata-updated/.gitignore").read_text("utf-8"),
            "translation rules\n",
        )
        self.assertEqual(
            self.base.joinpath(
                "metadata-updated/gameupdate/patch-config.txt"
            ).read_text("utf-8"),
            "repo=translation\n",
        )
        self.assertEqual(
            self.base.joinpath("metadata-updated/GameUpdate.bat").read_text("utf-8"),
            "translation launcher\n",
        )

    def test_non_overlapping_plugin_edits_merge_cleanly(self):
        old = "const title = 'Japanese';\nconst version = 1;\nconst enabled = false;\n"
        current = "const title = 'English';\nconst version = 1;\nconst enabled = false;\n"
        new = "const title = 'Japanese';\nconst version = 2;\nconst enabled = false;\n"
        self.write(self.old, "js/plugins/Core.js", old)
        self.write(self.current, "js/plugins/Core.js", current)
        self.write(self.new, "js/plugins/Core.js", new)

        plan = scan_version_update(self.current, self.new, old_root=self.old)
        decision = plan.decisions[0]

        self.assertEqual(decision.action, UpdateAction.MERGE_TEXT)
        self.assertTrue(decision.needs_review)
        apply_staged_update(plan, self.base / "merged")
        merged = self.base.joinpath("merged/js/plugins/Core.js").read_text(encoding="utf-8")
        self.assertIn("title = 'English'", merged)
        self.assertIn("version = 2", merged)

    def test_in_place_update_stages_then_keeps_complete_rollback_backup(self):
        self.write_all("Game.exe", b"runtime-v1")
        self.write_all("data.txt", "old\n")
        self.current.joinpath("data.txt").write_text("translated\n", encoding="utf-8")
        self.write(self.current, ".git/config", "repository metadata\n")
        self.new.joinpath("Game.exe").write_bytes(b"runtime-v2")
        plan = scan_version_update(
            self.current,
            self.new,
            old_root=self.old,
            old_version="v1/00",
            new_version="v1.03",
        )

        result = apply_in_place_update(plan)

        self.assertEqual(result.output_root, self.current.resolve())
        self.assertEqual(self.current.joinpath("Game.exe").read_bytes(), b"runtime-v2")
        self.assertEqual(
            self.current.joinpath("data.txt").read_text(encoding="utf-8"),
            "translated\n",
        )
        self.assertIsNotNone(result.backup_root)
        self.assertTrue(result.backup_root.is_dir())
        self.assertEqual(result.backup_root.joinpath("Game.exe").read_bytes(), b"runtime-v1")
        self.assertEqual(
            self.current.joinpath(".git/config").read_text(encoding="utf-8"),
            "repository metadata\n",
        )
        self.assertTrue(result.backup_root.joinpath(".git/config").is_file())
        self.assertNotIn("/", result.backup_root.name)
        report = json.loads(
            result.report_path.with_suffix(".json").read_text(encoding="utf-8")
        )
        self.assertEqual(report["apply"]["mode"], "in_place")
        self.assertEqual(report["apply"]["backup_root"], str(result.backup_root))
        self.assertEqual(report["output_root"], str(self.current.resolve()))

    def test_in_place_swap_failure_restores_original_translated_folder(self):
        from util.version_update import service as update_service

        self.write_all("Game.exe", b"runtime-v1")
        self.new.joinpath("Game.exe").write_bytes(b"runtime-v2")
        plan = scan_version_update(self.current, self.new, old_root=self.old)
        real_replace = update_service.os.replace
        failed = False

        def fail_live_swap(source, destination):
            nonlocal failed
            source_path = Path(source)
            destination_path = Path(destination)
            if (
                not failed
                and destination_path == self.current.resolve()
                and source_path.name.startswith(".translated.in-place-update-")
            ):
                failed = True
                raise OSError("simulated live swap failure")
            return real_replace(source, destination)

        with patch("util.version_update.service.os.replace", side_effect=fail_live_swap):
            with self.assertRaisesRegex(VersionUpdateError, "original translation was restored"):
                apply_in_place_update(plan)

        self.assertEqual(self.current.joinpath("Game.exe").read_bytes(), b"runtime-v1")
        self.assertFalse(list(self.base.glob(".translated.in-place-update-*")))
        self.assertFalse(list(self.base.glob("translated Backup *")))

    def test_saved_baseline_allows_future_two_folder_scan(self):
        self.write_all("Game.exe", b"v1")
        first = scan_version_update(
            self.current,
            self.new,
            old_root=self.old,
            old_version="1.00",
            new_version="1.03",
        )
        updated = self.base / "updated"
        apply_staged_update(first, updated)
        newer = self.base / "newer"
        newer.mkdir()
        self.write(newer, "Game.exe", b"v1")
        self.write(newer, "bonus.dat", b"new")

        second = scan_version_update(
            updated,
            newer,
            old_version="1.03",
            new_version="1.04",
        )

        self.assertTrue(second.used_saved_baseline)
        self.assertEqual(
            next(d.action for d in second.decisions if d.relative_path == "bonus.dat"),
            UpdateAction.ADD_NEW,
        )

    def test_matching_saved_baseline_automatically_runs_recovery_audit(self):
        self.write_all("Game.exe", b"v1")
        self.new.joinpath("Game.exe").write_bytes(b"v2")
        first = scan_version_update(
            self.current,
            self.new,
            old_root=self.old,
            old_version="1.00",
            new_version="1.10",
        )
        updated = self.base / "updated"
        apply_staged_update(first, updated)

        repeated = scan_version_update(updated, self.new)

        self.assertTrue(repeated.official_version_already_applied)
        self.assertTrue(repeated.audit_reapply)
        self.assertEqual(repeated.decisions[0].action, UpdateAction.KEEP)
        self.assertEqual(
            repeated.decisions[0].recovery_status,
            RecoveryStatus.ALREADY_PRESENT,
        )

        inspection_only = scan_version_update(
            updated, self.new, audit_reapply=False
        )
        self.assertFalse(inspection_only.audit_reapply)
        with self.assertRaisesRegex(VersionUpdateError, "already applied"):
            apply_staged_update(inspection_only, self.base / "should-not-apply")

    def test_automatic_recovery_gracefully_reports_missing_history(self):
        self.write_all("Game.exe", b"v1")
        self.new.joinpath("Game.exe").write_bytes(b"v2")
        first = scan_version_update(self.current, self.new, old_root=self.old)
        updated = self.base / "updated"
        apply_staged_update(first, updated)
        shutil.rmtree(updated / ".dazedtl" / "version_update" / "runs")

        repeated = scan_version_update(updated, self.new)

        self.assertTrue(repeated.official_version_already_applied)
        self.assertFalse(repeated.audit_reapply)
        self.assertIn("needs the report", repeated.recovery_error)
        with self.assertRaisesRegex(VersionUpdateError, "needs the report"):
            scan_version_update(updated, self.new, audit_reapply=True)

    def test_recovery_does_not_claim_later_local_edits_are_definite_reverts(self):
        self.write_all("Game.exe", b"v1")
        self.write(self.old, "js/plugins/Core.js", "title=jp\nversion=1\n")
        self.write(self.current, "js/plugins/Core.js", "title=en\nversion=1\n")
        self.write(self.new, "js/plugins/Core.js", "title=jp\nversion=2\n")
        first = scan_version_update(self.current, self.new, old_root=self.old)
        updated = self.base / "updated"
        apply_staged_update(first, updated)

        audit = scan_version_update(updated, self.new)
        decision = next(
            item for item in audit.decisions if item.relative_path == "js/plugins/Core.js"
        )

        self.assertEqual(decision.recovery_status, RecoveryStatus.POSSIBLE_REVERT)
        self.assertEqual(audit.summary()["possible_reverts"], 1)

    def test_audit_reapply_restores_reverted_update_from_retained_baseline(self):
        self.write_all("Game.exe", b"v1")
        self.write_all("js/plugins/Feature.js", "const enabled = false;\n")
        self.new.joinpath("Game.exe").write_bytes(b"v2")
        self.new.joinpath("js/plugins/Feature.js").write_text(
            "const enabled = true;\n", encoding="utf-8"
        )
        first = scan_version_update(
            self.current,
            self.new,
            old_root=self.old,
            old_version="1.00",
            new_version="1.10",
        )
        updated = self.base / "updated"
        apply_staged_update(first, updated)

        updated.joinpath("Game.exe").write_bytes(b"v1")
        updated.joinpath("js/plugins/Feature.js").write_text(
            "const enabled = false;\n", encoding="utf-8"
        )
        audit = scan_version_update(updated, self.new)
        decisions = {item.relative_path: item for item in audit.decisions}

        self.assertTrue(audit.official_version_already_applied)
        self.assertTrue(audit.audit_reapply)
        self.assertTrue(audit.used_saved_baseline)
        self.assertIn("prior official baseline", audit.old_source_label)
        self.assertEqual(audit.old_version, "1.00")
        self.assertEqual(audit.new_version, "1.10")
        self.assertEqual(decisions["Game.exe"].action, UpdateAction.USE_NEW)
        self.assertEqual(
            decisions["Game.exe"].recovery_status,
            RecoveryStatus.DEFINITE_REVERT,
        )
        self.assertEqual(
            decisions["js/plugins/Feature.js"].action,
            UpdateAction.USE_NEW,
        )

        recovered = self.base / "recovered"
        apply_staged_update(audit, recovered)
        self.assertEqual(recovered.joinpath("Game.exe").read_bytes(), b"v2")
        self.assertEqual(
            recovered.joinpath("js/plugins/Feature.js").read_text(encoding="utf-8"),
            "const enabled = true;\n",
        )

    def test_audit_reapply_can_fall_back_to_matching_git_original(self):
        repo = self.base / "audit-repository"
        repo.mkdir()
        self.git(repo, "init")
        self.git(repo, "config", "user.email", "tests@example.invalid")
        self.git(repo, "config", "user.name", "Version Update Tests")
        self.git(repo, "checkout", "-b", "original")
        game = repo / "game"
        self.write(game, "Game.exe", b"v1")
        self.git(repo, "add", "game")
        self.git(repo, "commit", "-m", "original game")
        self.git(repo, "checkout", "-b", "translation")
        self.write(game, "img/pictures/translated.png_", b"translated-image")
        self.write(
            game,
            ".dazedtl/image_backups/img/pictures/translated.png_",
            b"old-image",
        )
        self.write(self.new, "Game.exe", b"v2")
        self.write(self.new, "img/pictures/translated.png_", b"old-image")

        first = scan_version_update(
            game,
            self.new,
            old_version="1.00",
            new_version="1.10",
        )
        old_fingerprint = first.to_dict()["fingerprints"]["old_official"]
        apply_in_place_update(first)
        shutil.rmtree(
            game / ".dazedtl" / "version_update" / "baselines" / old_fingerprint
        )
        game.joinpath("Game.exe").write_bytes(b"v1")

        audit = scan_version_update(game, self.new)
        try:
            decision = next(
                item for item in audit.decisions if item.relative_path == "Game.exe"
            )
            self.assertTrue(audit.audit_reapply)
            self.assertTrue(audit.used_git_original)
            self.assertIn("audit/reapply", audit.old_source_label)
            self.assertEqual(decision.action, UpdateAction.USE_NEW)
        finally:
            audit.cleanup_temporary_resources()

    def test_corrupted_retained_baseline_source_is_rejected(self):
        from util.version_update.baseline import load_baseline

        self.write_all("Game.exe", b"v1")
        self.write_all("js/plugins/Feature.js", "const version = 1;\n")
        self.new.joinpath("js/plugins/Feature.js").write_text(
            "const version = 2;\n", encoding="utf-8"
        )
        plan = scan_version_update(self.current, self.new, old_root=self.old)
        updated = self.base / "updated"
        apply_staged_update(plan, updated)
        project = json.loads(
            updated.joinpath(".dazedtl/version_update/project.json").read_text("utf-8")
        )
        source = updated / ".dazedtl" / "version_update" / "baselines"
        source = source / project["active_source_fingerprint"]
        source = source / "mergeable" / "js" / "plugins" / "Feature.js"
        source.write_text("corrupted\n", encoding="utf-8")

        with self.assertRaisesRegex(Exception, "source is corrupted"):
            load_baseline(updated)

    def test_unsafe_retained_baseline_manifest_path_is_rejected(self):
        from util.version_update.baseline import load_baseline

        self.write_all("Game.exe", b"v1")
        plan = scan_version_update(self.current, self.new, old_root=self.old)
        updated = self.base / "updated"
        apply_staged_update(plan, updated)
        project = json.loads(
            updated.joinpath(".dazedtl/version_update/project.json").read_text("utf-8")
        )
        manifest_path = (
            updated
            / ".dazedtl"
            / "version_update"
            / "baselines"
            / project["active_source_fingerprint"]
            / "manifest.json"
        )
        manifest = json.loads(manifest_path.read_text("utf-8"))
        manifest["entries"][0]["path"] = "../../outside"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        with self.assertRaisesRegex(Exception, "unsafe path"):
            load_baseline(updated)

    def test_damaged_registered_baseline_rejects_unrelated_git_original(self):
        repo = self.base / "damaged-baseline-repository"
        repo.mkdir()
        self.git(repo, "init")
        self.git(repo, "config", "user.email", "tests@example.invalid")
        self.git(repo, "config", "user.name", "Version Update Tests")
        self.git(repo, "checkout", "-b", "original")
        game = repo / "game"
        self.write(game, "Game.exe", b"v1")
        self.write(game, "js/plugins/Core.js", "version=1\n")
        self.git(repo, "add", "game")
        self.git(repo, "commit", "-m", "original game")
        self.git(repo, "checkout", "-b", "translation")
        self.write(self.new, "Game.exe", b"v2")
        self.write(self.new, "js/plugins/Core.js", "version=2\n")
        first = scan_version_update(game, self.new)
        apply_in_place_update(first)
        project = json.loads(
            game.joinpath(".dazedtl/version_update/project.json").read_text("utf-8")
        )
        saved_source = (
            game
            / ".dazedtl"
            / "version_update"
            / "baselines"
            / project["active_source_fingerprint"]
            / "mergeable"
            / "js"
            / "plugins"
            / "Core.js"
        )
        saved_source.write_text("damaged\n", encoding="utf-8")
        newer = self.base / "newer"
        newer.mkdir()
        self.write(newer, "Game.exe", b"v3")
        self.write(newer, "js/plugins/Core.js", "version=3\n")

        with self.assertRaisesRegex(
            VersionUpdateError, "does not match the registered active official version"
        ):
            scan_version_update(game, newer)

    def test_history_pruning_retains_eight_reports_and_referenced_baselines(self):
        from util.version_update import service as update_service

        metadata = self.current / ".dazedtl" / "version_update"
        runs = metadata / "runs"
        baselines = metadata / "baselines"
        runs.mkdir(parents=True)
        baselines.mkdir(parents=True)
        fingerprints = [f"{index:064x}" for index in range(11)]
        metadata.joinpath("project.json").write_text(
            json.dumps({"active_source_fingerprint": fingerprints[-1]}),
            encoding="utf-8",
        )
        run_dirs = []
        for index in range(10):
            baselines.joinpath(fingerprints[index]).mkdir()
            run_dir = runs / f"run-{index:02d}"
            run_dir.mkdir()
            run_dir.joinpath("report.json").write_text(
                json.dumps(
                    {
                        "applied_at": f"2026-01-{index + 1:02d}T00:00:00+00:00",
                        "fingerprints": {
                            "old_official": fingerprints[index],
                            "new_official": fingerprints[index + 1],
                        },
                    }
                ),
                encoding="utf-8",
            )
            run_dirs.append(run_dir)
        baselines.joinpath(fingerprints[-1]).mkdir()

        update_service._prune_update_history(
            self.current,
            keep_run=run_dirs[-1],
        )

        self.assertEqual(len(list(runs.iterdir())), 8)
        self.assertEqual(
            {path.name for path in baselines.iterdir()},
            set(fingerprints[2:]),
        )

    def test_report_directories_remain_unique_on_timestamp_collision(self):
        from util.version_update import service as update_service

        real_datetime = update_service.datetime

        class FixedDatetime:
            @staticmethod
            def now(tz=None):
                return real_datetime(2026, 1, 2, 3, 4, 5, 678901, tzinfo=tz)

        metadata = self.current / ".dazedtl" / "version_update"
        with patch.object(update_service, "datetime", FixedDatetime):
            first = update_service._new_run_directory(metadata)
            second = update_service._new_run_directory(metadata)

        self.assertNotEqual(first, second)
        self.assertTrue(second.name.endswith("-1"))

    def test_staged_copy_is_verified_before_publish(self):
        self.write_all("Game.exe", b"v1")
        self.new.joinpath("Game.exe").write_bytes(b"v2")
        plan = scan_version_update(self.current, self.new, old_root=self.old)

        def corrupt_copy(_entry, target):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"corrupt")

        with patch("util.version_update.service._copy_entry", side_effect=corrupt_copy):
            with self.assertRaisesRegex(VersionUpdateError, "does not match"):
                apply_staged_update(plan, self.base / "corrupt-output")
        self.assertFalse(self.base.joinpath("corrupt-output").exists())

    def test_apply_rejects_current_folder_changed_since_scan(self):
        self.write_all("Game.exe", b"v1")
        plan = scan_version_update(self.current, self.new, old_root=self.old)
        self.current.joinpath("Game.exe").write_bytes(b"external edit")

        with self.assertRaisesRegex(Exception, "changed after the scan"):
            apply_staged_update(plan, self.base / "stale")

    def test_scan_rejects_nested_input_folders(self):
        nested = self.current / "new"
        nested.mkdir()
        with self.assertRaisesRegex(VersionUpdateError, "cannot be nested"):
            scan_version_update(self.current, nested, old_root=self.old)

    def test_scan_rejects_symbolic_links(self):
        self.write_all("Game.exe", b"v1")
        outside = self.base / "outside.dat"
        outside.write_bytes(b"outside")
        try:
            self.current.joinpath("linked.dat").symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("symbolic links are unavailable")

        with self.assertRaisesRegex(Exception, "Symbolic-link files"):
            scan_version_update(self.current, self.new, old_root=self.old)

    def test_report_records_fingerprints_and_readable_decisions(self):
        self.write_all("Game.exe", b"v1")
        self.write(self.new, "bonus.dat", b"new")
        plan = scan_version_update(
            self.current,
            self.new,
            old_root=self.old,
            old_version="v1.00",
            new_version="v1.03",
        )
        result = apply_staged_update(plan, self.base / "updated")
        report_text = result.report_path.read_text(encoding="utf-8")
        json_report = json.loads(
            result.report_path.with_suffix(".json").read_text(encoding="utf-8")
        )

        self.assertIn("v1.00 → v1.03", report_text)
        self.assertIn("bonus.dat", report_text)
        self.assertEqual(set(json_report["fingerprints"]), {
            "old_official", "current_translated", "new_official"
        })

    def test_cross_version_case_only_path_change_is_rejected(self):
        self.write(self.old, "img/Menu.png", b"old")
        self.write(self.current, "img/Menu.png", b"old")
        self.write(self.new, "img/menu.png", b"new")

        with self.assertRaisesRegex(VersionUpdateError, "changed only by case"):
            scan_version_update(self.current, self.new, old_root=self.old)

    def test_packed_wolf_cannot_be_forced_through_generic_mode(self):
        for root in (self.old, self.current, self.new):
            self.write(root, "Data.wolf", b"packed")

        with self.assertRaisesRegex(VersionUpdateError, "cannot use Generic"):
            scan_version_update(
                self.current,
                self.new,
                old_root=self.old,
                profile_id="generic",
            )

    def test_original_branch_is_used_without_checkout_and_json_format_is_ignored(self):
        repo = self.base / "repository"
        repo.mkdir()
        self.git(repo, "init")
        self.git(repo, "config", "user.email", "tests@example.invalid")
        self.git(repo, "config", "user.name", "Version Update Tests")
        self.git(repo, "checkout", "-b", "original")
        game = repo / "game"
        old_system = {"gameTitle": "日本語", "versionId": 1}
        old_maps = [None, {"id": 1, "name": "マップ"}]
        self.write(
            game,
            "data/System.json",
            json.dumps(old_system, ensure_ascii=False, indent=4),
        )
        self.write(
            game,
            "data/MapInfos.json",
            json.dumps(old_maps, ensure_ascii=False, indent=4),
        )
        self.write(game, "Game.exe", b"runtime")
        self.git(repo, "add", "game")
        self.git(repo, "commit", "-m", "original game")
        original_commit = self.git(repo, "rev-parse", "original")

        self.git(repo, "checkout", "-b", "translation")
        translated_system = {
            "gameTitle": "English title",
            "versionId": 1,
            "_original": {"gameTitle": "日本語"},
        }
        self.write(
            game,
            "data/System.json",
            json.dumps(translated_system, ensure_ascii=False, indent=2),
        )
        self.write(
            game,
            "data/MapInfos.json",
            json.dumps(old_maps, ensure_ascii=False, indent=2),
        )
        self.write(game, "img/pictures/translated.png_", b"translated-image")
        self.write(
            game,
            ".dazedtl/image_backups/img/pictures/translated.png_",
            b"old-image",
        )
        self.write(game, "img/pictures/changed.png_", b"translated-changed-image")
        self.write(
            game,
            ".dazedtl/image_backups/img/pictures/changed.png_",
            b"old-changed-image",
        )
        self.write(game, "img/pictures/untranslated.png_", b"old-runtime-image")

        new_system = {"gameTitle": "日本語", "versionId": 2}
        self.write(
            self.new,
            "data/System.json",
            json.dumps(new_system, ensure_ascii=False, separators=(",", ":")),
        )
        self.write(
            self.new,
            "data/MapInfos.json",
            json.dumps(old_maps, ensure_ascii=False, separators=(",", ":")),
        )
        self.write(self.new, "Game.exe", b"runtime")
        self.write(self.new, "img/pictures/translated.png_", b"old-image")
        self.write(self.new, "img/pictures/changed.png_", b"new-changed-image")
        self.write(self.new, "img/pictures/untranslated.png_", b"new-runtime-image")

        plan = scan_version_update(game, self.new)
        decisions = {item.relative_path: item for item in plan.decisions}

        self.assertEqual(self.git(repo, "branch", "--show-current"), "translation")
        self.assertTrue(plan.used_git_original)
        self.assertFalse(plan.used_saved_baseline)
        self.assertIn(original_commit[:10], plan.old_source_label)
        self.assertEqual(
            decisions["data/System.json"].action,
            UpdateAction.MERGE_SEMANTIC,
        )
        self.assertEqual(decisions["data/MapInfos.json"].action, UpdateAction.KEEP)
        self.assertEqual(
            decisions["img/pictures/translated.png_"].action,
            UpdateAction.PRESERVE_TRANSLATED,
        )
        self.assertEqual(
            decisions["img/pictures/changed.png_"].action,
            UpdateAction.CONFLICT,
        )
        self.assertEqual(
            decisions["img/pictures/untranslated.png_"].action,
            UpdateAction.USE_NEW,
        )
        decisions["img/pictures/changed.png_"].resolution = (
            ConflictResolution.USE_NEW
        )

        output = self.base / "git-updated"
        apply_staged_update(plan, output)
        merged = json.loads(output.joinpath("data/System.json").read_text("utf-8"))
        self.assertEqual(merged["gameTitle"], "English title")
        self.assertEqual(merged["versionId"], 2)
        self.assertEqual(
            output.joinpath("img/pictures/translated.png_").read_bytes(),
            b"translated-image",
        )
        self.assertEqual(
            output.joinpath("img/pictures/changed.png_").read_bytes(),
            b"new-changed-image",
        )
        self.assertEqual(
            output.joinpath("img/pictures/untranslated.png_").read_bytes(),
            b"new-runtime-image",
        )


class RPGMakerVersionUpdateTests(VersionUpdateTestBase):
    def _write_json(self, root: Path, relative: str, value):
        self.write(root, relative, json.dumps(value, ensure_ascii=False, indent=4))

    def test_detects_mvmz_only_with_real_game_data_markers(self):
        self._write_json(self.current, "data/System.json", {"gameTitle": "ゲーム"})

        profile, reason = detect_update_profile(self.current)

        self.assertEqual(profile, "rpgmaker-mvmz")
        self.assertIn("System.json", reason)

    def test_invalid_generated_rpgmaker_json_is_rejected_before_publish(self):
        old = {"gameTitle": "ゲーム", "versionId": 1}
        current = {
            "gameTitle": "Game",
            "versionId": 1,
            "_original": {"gameTitle": "ゲーム"},
        }
        new = {"gameTitle": "ゲーム", "versionId": 2}
        self._write_json(self.old, "data/System.json", old)
        self._write_json(self.current, "data/System.json", current)
        self._write_json(self.new, "data/System.json", new)
        plan = scan_version_update(self.current, self.new, old_root=self.old)
        decision = plan.decisions[0]
        self.assertEqual(decision.action, UpdateAction.MERGE_SEMANTIC)
        decision.generated_content = b"{"

        with self.assertRaisesRegex(VersionUpdateError, "JSON is invalid"):
            apply_staged_update(plan, self.base / "invalid-json-output")
        self.assertFalse(self.base.joinpath("invalid-json-output").exists())

    def test_preserves_unchanged_translation_and_imports_new_record(self):
        old_data = [None, {"id": 1, "name": "勇者", "description": "主人公"}]
        translated_data = [
            None,
            {
                "id": 1,
                "name": "Hero",
                "description": "Protagonist",
                "_original": {"name": "勇者", "description": "主人公"},
            },
        ]
        new_data = old_data + [{"id": 2, "name": "魔法使い", "description": "仲間"}]
        self._write_json(self.old, "data/Actors.json", old_data)
        self._write_json(self.current, "data/Actors.json", translated_data)
        self._write_json(self.new, "data/Actors.json", new_data)
        for root in (self.old, self.current, self.new):
            self._write_json(root, "data/System.json", {"gameTitle": "ゲーム"})

        plan = scan_version_update(self.current, self.new, old_root=self.old)
        decision = next(d for d in plan.decisions if d.relative_path == "data/Actors.json")

        self.assertEqual(decision.action, UpdateAction.MERGE_SEMANTIC)
        self.assertGreaterEqual(decision.preserved_translations, 2)
        self.assertGreaterEqual(decision.needs_translation, 2)
        apply_staged_update(plan, self.base / "updated")
        result = json.loads(
            self.base.joinpath("updated/data/Actors.json").read_text(encoding="utf-8")
        )
        self.assertEqual(result[1]["name"], "Hero")
        self.assertEqual(result[1]["description"], "Protagonist")
        self.assertEqual(result[2]["name"], "魔法使い")

    def test_changed_source_replaces_stale_translation_and_original(self):
        old_data = [None, {"id": 1, "name": "勇者"}]
        translated_data = [
            None,
            {"id": 1, "name": "Hero", "_original": {"name": "勇者"}},
        ]
        new_data = [None, {"id": 1, "name": "新しい勇者"}]
        self._write_json(self.old, "data/Actors.json", old_data)
        self._write_json(self.current, "data/Actors.json", translated_data)
        self._write_json(self.new, "data/Actors.json", new_data)
        for root in (self.old, self.current, self.new):
            self._write_json(root, "data/System.json", {"gameTitle": "ゲーム"})

        plan = scan_version_update(self.current, self.new, old_root=self.old)
        apply_staged_update(plan, self.base / "updated")
        result = json.loads(
            self.base.joinpath("updated/data/Actors.json").read_text(encoding="utf-8")
        )

        self.assertEqual(result[1]["name"], "新しい勇者")
        self.assertEqual(result[1]["_original"]["name"], "新しい勇者")
        decision = next(d for d in plan.decisions if d.relative_path == "data/Actors.json")
        self.assertEqual(decision.needs_translation, 1)

    def test_new_rpgmaker_json_file_counts_text_for_translation(self):
        system = {"gameTitle": "ゲーム"}
        for root in (self.old, self.current, self.new):
            self._write_json(root, "data/System.json", system)
        self._write_json(
            self.new,
            "data/Map002.json",
            {
                "events": [
                    None,
                    {
                        "id": 1,
                        "pages": [
                            {
                                "list": [
                                    {"code": 401, "indent": 0, "parameters": ["新しい台詞"]},
                                    {"code": 0, "indent": 0, "parameters": []},
                                ]
                            }
                        ],
                    },
                ]
            },
        )

        plan = scan_version_update(self.current, self.new, old_root=self.old)
        decision = next(d for d in plan.decisions if d.relative_path == "data/Map002.json")

        self.assertEqual(decision.action, UpdateAction.ADD_NEW)
        self.assertEqual(decision.needs_translation, 1)

    def test_event_command_insertion_preserves_aligned_dialogue(self):
        old_map = {
            "events": [
                None,
                {
                    "id": 1,
                    "pages": [
                        {
                            "list": [
                                {"code": 401, "indent": 0, "parameters": ["こんにちは"]},
                                {"code": 0, "indent": 0, "parameters": []},
                            ]
                        }
                    ],
                },
            ]
        }
        translated_map = json.loads(json.dumps(old_map, ensure_ascii=False))
        translated_command = translated_map["events"][1]["pages"][0]["list"][0]
        translated_command["parameters"][0] = "Hello"
        translated_command["_original"] = "こんにちは"
        new_map = json.loads(json.dumps(old_map, ensure_ascii=False))
        new_map["events"][1]["pages"][0]["list"].insert(
            0, {"code": 121, "indent": 0, "parameters": [3, 3, 0]}
        )
        for root in (self.old, self.current, self.new):
            self._write_json(root, "data/System.json", {"gameTitle": "ゲーム"})
        self._write_json(self.old, "data/Map001.json", old_map)
        self._write_json(self.current, "data/Map001.json", translated_map)
        self._write_json(self.new, "data/Map001.json", new_map)

        plan = scan_version_update(self.current, self.new, old_root=self.old)
        decision = next(d for d in plan.decisions if d.relative_path == "data/Map001.json")

        self.assertEqual(decision.action, UpdateAction.MERGE_SEMANTIC)
        apply_staged_update(plan, self.base / "updated")
        merged = json.loads(
            self.base.joinpath("updated/data/Map001.json").read_text(encoding="utf-8")
        )
        commands = merged["events"][1]["pages"][0]["list"]
        self.assertEqual([command["code"] for command in commands], [121, 401, 0])
        self.assertEqual(commands[1]["parameters"][0], "Hello")

    def test_changed_second_dialogue_line_refreshes_group_original(self):
        old_map = {
            "events": [
                None,
                {
                    "id": 1,
                    "pages": [
                        {
                            "list": [
                                {"code": 401, "indent": 0, "parameters": ["一行目"]},
                                {"code": 401, "indent": 0, "parameters": ["二行目"]},
                                {"code": 0, "indent": 0, "parameters": []},
                            ]
                        }
                    ],
                },
            ]
        }
        translated_map = json.loads(json.dumps(old_map, ensure_ascii=False))
        commands = translated_map["events"][1]["pages"][0]["list"]
        commands[0]["parameters"][0] = "First line"
        commands[0]["_original"] = "一行目\n二行目"
        commands[1]["parameters"][0] = "Second line"
        new_map = json.loads(json.dumps(old_map, ensure_ascii=False))
        new_map["events"][1]["pages"][0]["list"][1]["parameters"][0] = "変更した二行目"
        for root in (self.old, self.current, self.new):
            self._write_json(root, "data/System.json", {"gameTitle": "ゲーム"})
        self._write_json(self.old, "data/Map001.json", old_map)
        self._write_json(self.current, "data/Map001.json", translated_map)
        self._write_json(self.new, "data/Map001.json", new_map)

        plan = scan_version_update(self.current, self.new, old_root=self.old)
        apply_staged_update(plan, self.base / "updated")
        merged = json.loads(
            self.base.joinpath("updated/data/Map001.json").read_text(encoding="utf-8")
        )
        merged_commands = merged["events"][1]["pages"][0]["list"]

        self.assertEqual(merged_commands[0]["parameters"][0], "First line")
        self.assertEqual(merged_commands[1]["parameters"][0], "変更した二行目")
        self.assertEqual(merged_commands[0]["_original"], "一行目\n変更した二行目")

    def test_changed_choice_list_uses_hashable_command_alignment_key(self):
        old_map = {
            "events": [
                None,
                {
                    "id": 1,
                    "pages": [
                        {
                            "list": [
                                {
                                    "code": 102,
                                    "indent": 0,
                                    "parameters": [["はい", "いいえ"], 0, 0, 2, 0],
                                },
                                {"code": 0, "indent": 0, "parameters": []},
                            ]
                        }
                    ],
                },
            ]
        }
        translated_map = json.loads(json.dumps(old_map, ensure_ascii=False))
        choice = translated_map["events"][1]["pages"][0]["list"][0]
        choice["parameters"][0] = ["Yes", "No"]
        choice["_original"] = ["はい", "いいえ"]
        new_map = json.loads(json.dumps(old_map, ensure_ascii=False))
        new_map["events"][1]["pages"][0]["list"][0]["parameters"][0].append(
            "たぶん"
        )
        for root in (self.old, self.current, self.new):
            self._write_json(root, "data/System.json", {"gameTitle": "ゲーム"})
        self._write_json(self.old, "data/Map001.json", old_map)
        self._write_json(self.current, "data/Map001.json", translated_map)
        self._write_json(self.new, "data/Map001.json", new_map)

        plan = scan_version_update(self.current, self.new, old_root=self.old)
        apply_staged_update(plan, self.base / "updated")
        merged = json.loads(
            self.base.joinpath("updated/data/Map001.json").read_text(encoding="utf-8")
        )
        merged_choice = merged["events"][1]["pages"][0]["list"][0]

        self.assertEqual(merged_choice["parameters"][0], ["Yes", "No", "たぶん"])
        self.assertEqual(merged_choice["_original"], ["はい", "いいえ", "たぶん"])

    def test_plugins_manifest_merges_by_name_and_preserves_nested_translation(self):
        def plugins_js(plugins):
            return "var $plugins = " + json.dumps(plugins, ensure_ascii=False) + ";\n"

        old_plugins = [
            {
                "name": "Core",
                "status": True,
                "description": "基本",
                "parameters": {
                    "Config": json.dumps(
                        {"label": "日本語", "speed": 1}, ensure_ascii=False
                    )
                },
            },
            {"name": "Menu", "status": True, "description": "", "parameters": {}},
        ]
        current_plugins = json.loads(json.dumps(old_plugins, ensure_ascii=False))
        current_config = json.loads(current_plugins[0]["parameters"]["Config"])
        current_config["label"] = "English"
        current_plugins[0]["parameters"]["Config"] = json.dumps(
            current_config, ensure_ascii=False
        )
        current_plugins.append(
            {
                "name": "TranslatorHelper",
                "status": True,
                "description": "local",
                "parameters": {},
            }
        )
        new_plugins = [
            old_plugins[1],
            json.loads(json.dumps(old_plugins[0], ensure_ascii=False)),
            {
                "name": "NewFeature",
                "status": True,
                "description": "新機能",
                "parameters": {},
            },
        ]
        new_config = json.loads(new_plugins[1]["parameters"]["Config"])
        new_config["speed"] = 2
        new_plugins[1]["parameters"]["Config"] = json.dumps(
            new_config, ensure_ascii=False
        )

        for root in (self.old, self.current, self.new):
            self._write_json(root, "data/System.json", {"gameTitle": "ゲーム"})
        self.write(self.old, "js/plugins.js", plugins_js(old_plugins))
        self.write(self.current, "js/plugins.js", plugins_js(current_plugins))
        self.write(self.new, "js/plugins.js", plugins_js(new_plugins))

        plan = scan_version_update(self.current, self.new, old_root=self.old)
        decision = next(d for d in plan.decisions if d.relative_path == "js/plugins.js")

        self.assertEqual(decision.action, UpdateAction.MERGE_SEMANTIC)
        apply_staged_update(plan, self.base / "plugins-updated")
        text = self.base.joinpath("plugins-updated/js/plugins.js").read_text("utf-8")
        merged_plugins = json.loads(text.split("var $plugins =", 1)[1].strip().rstrip(";"))
        self.assertEqual(
            [plugin["name"] for plugin in merged_plugins],
            ["Menu", "Core", "NewFeature", "TranslatorHelper"],
        )
        merged_config = json.loads(merged_plugins[1]["parameters"]["Config"])
        self.assertEqual(merged_config["label"], "English")
        self.assertEqual(merged_config["speed"], 2)

    def test_ambiguous_semantic_merge_defaults_to_upstream_first_proposal(self):
        old = {"gameTitle": "ゲーム", "versionId": 1}
        current = {"gameTitle": "ゲーム", "versionId": 2}
        new = {"gameTitle": "ゲーム", "versionId": 3}
        self._write_json(self.old, "data/System.json", old)
        self._write_json(self.current, "data/System.json", current)
        self._write_json(self.new, "data/System.json", new)

        plan = scan_version_update(self.current, self.new, old_root=self.old)
        decision = plan.decisions[0]

        self.assertEqual(decision.action, UpdateAction.CONFLICT)
        self.assertEqual(
            decision.recommended_resolution, ConflictResolution.USE_PROPOSED
        )
        self.assertEqual(decision.resolution, ConflictResolution.USE_PROPOSED)
        self.assertTrue(decision.resolution_is_automatic)
        self.assertFalse(decision.translation_at_risk)
        apply_staged_update(plan, self.base / "semantic-updated")
        merged = json.loads(
            self.base.joinpath("semantic-updated/data/System.json").read_text("utf-8")
        )
        self.assertEqual(merged["versionId"], 3)


class VersionUpdateUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_sidebar_page_exposes_safe_staged_workflow(self):
        from gui.version_update_tab import VersionUpdateTab

        tab = VersionUpdateTab()
        try:
            self.assertEqual(tab.scan_btn.text(), "Preview update")
            self.assertEqual(tab.apply_btn.text(), "Create recommended update")
            self.assertEqual(
                tab.custom_apply_btn.text(), "Create with review choices"
            )
            self.assertFalse(tab.apply_btn.isEnabled())
            self.assertFalse(tab.custom_apply_btn.isEnabled())
            self.assertTrue(tab.review_card.isHidden())
            self.assertTrue(tab.create_card.isHidden())
            self.assertTrue(tab.progress.isHidden())
            self.assertTrue(tab.progress_label.isHidden())
            self.assertTrue(tab.cancel_scan_btn.isHidden())
            self.assertTrue(tab.options_widget.isHidden())
            tab.options_toggle.setChecked(True)
            self.assertFalse(tab.options_widget.isHidden())
            self.assertEqual(tab.options_toggle.text(), "Hide update options")
            self.assertIn("original folders are never modified", tab.safety_label.text())
            self.assertTrue(tab.copy_mode_radio.isChecked())
            tab.in_place_mode_radio.setChecked(True)
            self.assertEqual(tab.apply_btn.text(), "Update translated game")
            self.assertEqual(
                tab.custom_apply_btn.text(), "Update with review choices"
            )
            self.assertTrue(tab.output_edit.isHidden())
            self.assertIn("rollback backup", tab.safety_label.text())
            tab.copy_mode_radio.setChecked(True)
            self.assertFalse(tab.output_edit.isHidden())
            self.assertFalse(tab.continue_workflow_btn.isEnabled())
            self.assertFalse(tab.open_images_btn.isEnabled())
            self.assertIsNotNone(
                tab.findChild(QScrollArea, "versionUpdateScroll")
            )
            self.assertGreaterEqual(tab.tree.minimumHeight(), 250)
            self.assertEqual(tab.tree.header().stretchSectionCount(), 1)
            self.assertEqual(
                tab.tree.selectionMode(), QAbstractItemView.ExtendedSelection
            )
            self.assertEqual(tab.review_filter.currentData(), "review")
            self.assertEqual(tab.use_proposed_btn.text(), "Merge new and local changes")
            self.assertFalse(hasattr(tab, "audit_reapply_check"))
        finally:
            tab.close()

    def test_already_applied_scan_offers_recovery_instead_of_an_empty_update(self):
        from gui.version_update_tab import VersionUpdateTab

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            old = base / "old"
            current = base / "current"
            new = base / "new"
            for root in (old, current, new):
                root.mkdir()
            old.joinpath("Game.exe").write_bytes(b"v1")
            current.joinpath("Game.exe").write_bytes(b"v1")
            new.joinpath("Game.exe").write_bytes(b"v2")
            first = scan_version_update(
                current,
                new,
                old_root=old,
                old_version="1.00",
                new_version="1.10",
            )
            updated = base / "updated"
            apply_staged_update(first, updated)

            repeated = scan_version_update(updated, new)
            tab = VersionUpdateTab()
            try:
                tab.current_edit.setText(str(updated))
                tab._refresh_detection()
                self.assertIn("runs automatically", tab.baseline_label.text())
                tab._on_scan_done(repeated)
                self.assertFalse(tab.review_card.isHidden())
                self.assertFalse(tab.create_card.isHidden())
                self.assertIn("Recovery audit", tab.summary_label.text())
                self.assertEqual(tab.review_filter.currentData(), "recovery")
                self.assertEqual(
                    sum(not item.isHidden() for item in tab._items.values()), 0
                )
                self.assertEqual(
                    tab.apply_btn.text(), "Reapply recovered changes"
                )
                self.assertEqual(
                    tab.custom_apply_btn.text(), "Reapply with review choices"
                )
                self.assertTrue(tab.apply_btn.isEnabled())
                self.assertTrue(tab.custom_apply_btn.isEnabled())

                updated.joinpath("Game.exe").write_bytes(b"v1")
                audit = scan_version_update(updated, new)
                tab._on_scan_done(audit)
                self.assertIn("Recovery audit", tab.summary_label.text())
                self.assertIn("1 definite full-file revert", tab.summary_label.text())
                self.assertEqual(
                    sum(not item.isHidden() for item in tab._items.values()), 1
                )
                self.assertIn("Definite revert", next(iter(tab._items.values())).text(3))
                self.assertTrue(tab.apply_btn.isEnabled())
                self.assertTrue(tab.custom_apply_btn.isEnabled())
                tab.output_edit.setText(str(base / "recovered"))
                with patch.object(
                    QMessageBox, "question", return_value=QMessageBox.No
                ) as question:
                    tab._apply(recommended=True)
                self.assertEqual(question.call_args.args[1], "Reapply recovered changes")
                self.assertIn(
                    "no files change unless you confirm this reapply",
                    question.call_args.args[2],
                )
            finally:
                tab.close()

    def test_file_details_explain_consequences_and_hide_engine_log(self):
        from gui.version_update_tab import VersionUpdateTab, _format_decision_details

        merged_map = {
            "events": [
                None,
                {
                    "id": 1,
                    "name": "Exit",
                    "pages": [
                        {
                            "list": [
                                {
                                    "code": 401,
                                    "indent": 0,
                                    "parameters": ["The stairs are clear."],
                                },
                                {
                                    "code": 401,
                                    "indent": 0,
                                    "parameters": ["Head to the barracks."],
                                },
                            ]
                        }
                    ],
                },
            ]
        }
        decision = UpdateDecision(
            relative_path="data/Map002.json",
            action=UpdateAction.CONFLICT,
            kind=FileKind.JSON,
            reason="RPG Maker data has ambiguous both-changed values",
            generated_content=(
                json.dumps(merged_map, ensure_ascii=False).encode("utf-8")
            ),
            needs_review=True,
            preserved_translations=1,
            details=[
                "$.events.id=1.pages[0].list[0].parameters[0]: "
                "source text is unchanged",
                "$.events.id=1.pages[0].list[1]: an upstream command matches a "
                "command removed by the translator",
            ],
            resolution=ConflictResolution.USE_PROPOSED,
            recommended_resolution=ConflictResolution.USE_PROPOSED,
            resolution_is_automatic=True,
            recovery_status=RecoveryStatus.POSSIBLE_REVERT,
        )

        summary, technical = _format_decision_details(decision)

        self.assertIn("What will happen", summary)
        self.assertIn("Recovery finding", summary)
        self.assertIn("matches neither official version", summary)
        self.assertIn("Keep 1 existing translation", summary)
        self.assertIn("Restore 1 event command that was removed locally", summary)
        self.assertIn("What needs your attention", summary)
        self.assertIn('Event 1 “Exit” · Page 1 · Dialogue 2', summary)
        self.assertIn("Result: Head to the barracks.", summary)
        self.assertIn("Selected automatically: Merge New + Local Changes", summary)
        self.assertNotIn("$.events", summary)
        self.assertNotIn("source text is unchanged", summary)
        self.assertIn("$.events.id=1.pages[0].list[1]", technical)

        tab = VersionUpdateTab()
        try:
            tab._plan = type("Plan", (), {"decisions": [decision]})()
            item = QTreeWidgetItem()
            item.setData(0, Qt.UserRole, 0)
            tab._show_selected(item, None)
            self.assertIn("What will happen", tab.details.toPlainText())
            self.assertTrue(tab.technical_details.isHidden())
            self.assertEqual(tab.technical_toggle.text(), "Show technical merge log")
            tab.technical_toggle.setChecked(True)
            self.assertFalse(tab.technical_details.isHidden())
            self.assertIn("Action id: conflict", tab.technical_details.toPlainText())
            self.assertEqual(tab.technical_toggle.text(), "Hide technical merge log")
        finally:
            tab.close()

    def test_review_queue_bulk_override_is_clear_and_multi_select(self):
        from gui.version_update_tab import VersionUpdateTab

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            roots = [base / name for name in ("old", "current", "new")]
            for root in roots:
                root.mkdir()
            old, current, new = roots
            for relative in ("one.bin", "two.bin"):
                old.joinpath(relative).write_bytes(b"old")
                current.joinpath(relative).write_bytes(b"local")
                new.joinpath(relative).write_bytes(b"new")
            plan = scan_version_update(current, new, old_root=old)
            tab = VersionUpdateTab()
            try:
                tab._plan = plan
                tab._populate_plan()
                self.assertEqual(
                    sum(not item.isHidden() for item in tab._items.values()), 2
                )
                items = list(tab._items.values())
                tab.tree.clearSelection()
                for item in items:
                    item.setSelected(True)
                tab._resolve_selected(ConflictResolution.KEEP_CURRENT)
                self.assertTrue(
                    all(
                        decision.resolution == ConflictResolution.KEEP_CURRENT
                        and not decision.resolution_is_automatic
                        for decision in plan.decisions
                    )
                )
                self.assertIn("Current wins", items[0].text(3))
                with patch.object(tab, "_apply") as apply:
                    tab._apply_recommended()
                self.assertTrue(
                    all(
                        decision.resolution == decision.recommended_resolution
                        and decision.resolution_is_automatic
                        for decision in plan.decisions
                    )
                )
                apply.assert_called_once_with(recommended=True)
            finally:
                tab.close()

    def test_main_sidebar_wires_version_update_without_moving_images_page(self):
        from gui.main import DazedMTLGUI
        from gui.version_update_tab import VersionUpdateTab

        with patch("gui.main.QTimer.singleShot"):
            window = DazedMTLGUI()
        try:
            self.assertEqual(window.PAGE_IMAGES, 2)
            self.assertEqual(window.PAGE_VERSION_UPDATE, 3)
            self.assertEqual(window.PAGE_TRANSLATION, 4)
            self.assertIsInstance(
                window.content_stack.widget(window.PAGE_VERSION_UPDATE),
                VersionUpdateTab,
            )
            self.assertEqual(len(window.nav_buttons), 8)
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
