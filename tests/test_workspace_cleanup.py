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
