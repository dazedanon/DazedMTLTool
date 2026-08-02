from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import clean_workspace


class WorkspaceCleanupTests(unittest.TestCase):
    """Cleanup remains dry-run-first and cannot traverse links to user data."""

    def test_dry_run_preserves_targets_until_apply_is_explicit(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            capture = root / ".tmp-ui" / "old-run"
            capture.mkdir(parents=True)
            (capture / "capture.png").write_bytes(b"capture")
            protected = root / "files" / "Map001.json"
            protected.parent.mkdir()
            protected.write_text("private project", encoding="utf-8")

            with (
                mock.patch.object(clean_workspace, "PROJECT_ROOT", root),
                mock.patch("sys.argv", ["clean_workspace.py", "--captures", "--keep-captures", "0"]),
            ):
                self.assertEqual(clean_workspace.main(), 0)
            self.assertTrue(capture.exists())
            self.assertTrue(protected.exists())

            with (
                mock.patch.object(clean_workspace, "PROJECT_ROOT", root),
                mock.patch(
                    "sys.argv",
                    ["clean_workspace.py", "--captures", "--keep-captures", "0", "--apply"],
                ),
            ):
                self.assertEqual(clean_workspace.main(), 0)
            self.assertFalse(capture.exists())
            self.assertTrue(protected.exists())

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_cleanup_refuses_symlink_targets(self):
        with tempfile.TemporaryDirectory() as raw, tempfile.TemporaryDirectory() as outside:
            root = Path(raw)
            capture_root = root / ".tmp-ui"
            capture_root.mkdir()
            link = capture_root / "linked-run"
            link.symlink_to(Path(outside), target_is_directory=True)

            with self.assertRaisesRegex(clean_workspace.CleanupSafetyError, "symlink"):
                clean_workspace.capture_targets(root.resolve(), keep=0)

    def test_runtime_cleanup_keeps_newest_histories_and_only_stale_temp_files(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            history = root / "log" / "history"
            history.mkdir(parents=True)
            histories = []
            for index in range(4):
                path = history / f"translationHistory_2026080{index}_120000.txt"
                path.write_text(str(index), encoding="utf-8")
                os.utime(path, (100 + index, 100 + index))
                histories.append(path)

            stale_tmp = root / "log" / "translation_cache.json.1.thread.tmp"
            stale_tmp.write_text("interrupted", encoding="utf-8")
            os.utime(stale_tmp, (100, 100))
            recent_tmp = root / "log" / "batch_requests.json.1.thread.tmp"
            recent_tmp.write_text("active", encoding="utf-8")
            os.utime(recent_tmp, (950, 950))
            cache = root / "log" / "translation_cache.json"
            cache.write_text("{}", encoding="utf-8")
            evaluation = root / "log" / "evaluations" / "saved" / "state.json"
            evaluation.parent.mkdir(parents=True)
            evaluation.write_text("{}", encoding="utf-8")

            targets = clean_workspace.runtime_targets(
                root,
                keep_history=2,
                stale_tmp_seconds=100,
                now=1000,
            )
            selected = {target.path for target in targets}

            self.assertEqual(
                selected,
                {histories[0].resolve(), histories[1].resolve(), stale_tmp.resolve()},
            )
            self.assertNotIn(recent_tmp.resolve(), selected)
            self.assertNotIn(cache.resolve(), selected)
            self.assertNotIn(evaluation.resolve(), selected)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_runtime_cleanup_refuses_links_below_log(self):
        with tempfile.TemporaryDirectory() as raw, tempfile.TemporaryDirectory() as outside:
            root = Path(raw).resolve()
            log_root = root / "log"
            log_root.mkdir()
            (log_root / "linked").symlink_to(Path(outside), target_is_directory=True)

            with self.assertRaisesRegex(clean_workspace.CleanupSafetyError, "symlink"):
                clean_workspace.runtime_targets(
                    root,
                    keep_history=10,
                    stale_tmp_seconds=3600,
                )
