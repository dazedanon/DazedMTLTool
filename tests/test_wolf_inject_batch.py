#!/usr/bin/env python3
"""Unit tests for util/wolfdawn/inject.py orchestration."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from util.wolfdawn import inject as wi  # noqa: E402


class ListInjectableTests(unittest.TestCase):
    def test_lists_translated_files_with_manifest_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            translated = root / "translated"
            translated.mkdir()
            (translated / "names.json").write_text("{}", encoding="utf-8")
            (translated / "Map001.mps.json").write_text("{}", encoding="utf-8")
            (translated / "orphan.json").write_text("{}", encoding="utf-8")
            entries = [
                {"json": "names.json", "kind": "names", "base": "/data"},
                {"json": "Map001.mps.json", "kind": "map", "base": "/data/Map001.mps"},
            ]
            self.assertEqual(
                wi.list_injectable(translated, entries),
                ["Map001.mps.json", "names.json"],
            )


class InjectOrderTests(unittest.TestCase):
    def test_names_runs_before_strings(self):
        calls: list[str] = []

        def fake_names(*_a, **_k):
            calls.append("names")
            return mock.Mock(
                ok=True,
                returncode=0,
                stdout="applied 2 name change(s) (0 drifted/unmatched)",
                stderr="",
            )

        def fake_strings(*_a, **_k):
            calls.append("strings")
            return mock.Mock(
                ok=True,
                returncode=0,
                stdout="applied 1 translation(s) (0 drifted)",
                stderr="",
            )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            translated = root / "translated"
            originals = root / "originals"
            data = root / "data"
            translated.mkdir()
            originals.mkdir()
            data.mkdir()
            (translated / "names.json").write_text("{}", encoding="utf-8")
            (translated / "Map001.mps.json").write_text(
                '{"kind":"map","scenes":[]}', encoding="utf-8"
            )
            map_live = data / "Map001.mps"
            map_orig = originals / "Map001.mps"
            map_live.write_bytes(b"live")
            map_orig.write_bytes(b"orig")

            entries = [
                {"json": "names.json", "kind": "names", "base": str(data)},
                {"json": "Map001.mps.json", "kind": "map", "base": str(map_live)},
            ]

            def would_apply_counts():
                yield 1  # prepare: after restore
                yield 1  # _inject_names: preflight
                yield 0  # _inject_names: post-check

            counts = would_apply_counts()

            def next_would_apply(*_a, **_k):
                return next(counts, 0)

            with mock.patch.object(wi.wolf_originals, "names_inject_would_apply", side_effect=next_would_apply), \
                 mock.patch.object(wi.wolfdawn, "names_inject", side_effect=fake_names), \
                 mock.patch.object(wi.wolfdawn, "strings_inject", side_effect=fake_strings):
                report = wi.inject_selected(
                    ["Map001.mps.json", wi.NAMES_JSON],
                    manifest_entries=entries,
                    data_dir=data,
                    originals_dir=originals,
                    translated_dir=translated,
                    game_root=data.parent,
                )

            self.assertEqual(calls, ["names", "strings"])
            self.assertTrue(report.ok)
            self.assertEqual(len(report.succeeded), 2)


class ReportDialogTests(unittest.TestCase):
    def test_failure_dialog_lists_every_problem(self):
        report = wi.InjectReport(
            files=[
                wi.FileInjectResult("a.json", True, "applied 3 line(s)"),
                wi.FileInjectResult("b.json", False, "0 applied, 2 drifted", detail="stderr"),
            ],
            sync_failures=[("c.json", "permission denied")],
        )
        title, body = wi.format_report_dialog(report)
        self.assertIn("errors", title)
        self.assertIn("✗ b.json", body)
        self.assertIn("✗ sync c.json", body)
        self.assertIn("✓ a.json", body)


if __name__ == "__main__":
    unittest.main()
