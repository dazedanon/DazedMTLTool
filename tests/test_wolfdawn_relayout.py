#!/usr/bin/env python3
"""Unit tests for WolfDawn relayout / desc_relayout CLI wrappers."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from util import wolfdawn  # noqa: E402


class TestRelayoutWrappers(unittest.TestCase):
    def test_relayout_dry_run_args(self):
        captured = {}

        def fake_run(args, log_fn=None):
            captured["args"] = list(args)
            return wolfdawn.WolfResult(0, "", "", [str(a) for a in args])

        with patch.object(wolfdawn, "_run", side_effect=fake_run):
            wolfdawn.relayout("/game/Data", width=55, max_rows=0)
        self.assertEqual(captured["args"][:2], ["relayout", "/game/Data"])
        self.assertIn("--width", captured["args"])
        self.assertIn("55", captured["args"])
        self.assertNotIn("-o", captured["args"])
        self.assertIn("--max-rows", captured["args"])
        self.assertIn("auto", captured["args"])

    def test_relayout_write_args(self):
        captured = {}

        def fake_run(args, log_fn=None):
            captured["args"] = list(args)
            return wolfdawn.WolfResult(0, "", "", [str(a) for a in args])

        with patch.object(wolfdawn, "_run", side_effect=fake_run):
            wolfdawn.relayout(
                "/game/Data",
                out_dir="/tmp/out",
                width=60,
                max_rows=4,
                no_resolve=True,
            )
        args = captured["args"]
        self.assertEqual(args[0], "relayout")
        self.assertIn("-o", args)
        self.assertIn("/tmp/out", args)
        self.assertIn("--width", args)
        self.assertIn("60", args)
        self.assertIn("--max-rows", args)
        self.assertIn("4", args)
        self.assertIn("--no-resolve", args)

    def test_desc_relayout_args(self):
        captured = {}

        def fake_run(args, log_fn=None):
            captured["args"] = list(args)
            return wolfdawn.WolfResult(0, "", "", [str(a) for a in args])

        with patch.object(wolfdawn, "_run", side_effect=fake_run):
            wolfdawn.desc_relayout(
                "/game/Data/BasicData/DataBase.project",
                "/tmp/DataBase.project",
                width=75,
                max_lines=0,
                keep_breaks=True,
            )
        args = captured["args"]
        self.assertEqual(args[0], "desc-relayout")
        self.assertIn("-o", args)
        self.assertIn("/tmp/DataBase.project", args)
        self.assertIn("--width", args)
        self.assertIn("75", args)
        self.assertIn("--max-lines", args)
        self.assertIn("auto", args)
        self.assertIn("--keep-breaks", args)

    def test_relayout_auto_width(self):
        captured = {}

        def fake_run(args, log_fn=None):
            captured["args"] = list(args)
            return wolfdawn.WolfResult(0, "", "", [str(a) for a in args])

        with patch.object(wolfdawn, "_run", side_effect=fake_run):
            wolfdawn.relayout("/game/Data", width="auto", max_rows="auto")
        args = captured["args"]
        self.assertIn("--width", args)
        self.assertIn("auto", args)
        self.assertIn("--max-rows", args)

    def test_names_wrap_args(self):
        captured = {}

        def fake_run(args, log_fn=None):
            captured["args"] = list(args)
            return wolfdawn.WolfResult(
                0,
                "names-wrap: 3 entry(ies) re-wrapped",
                "",
                [str(a) for a in args],
            )

        with patch.object(wolfdawn, "_run", side_effect=fake_run):
            res = wolfdawn.names_wrap("/tmp/names.json")
        self.assertEqual(captured["args"], ["names-wrap", "/tmp/names.json"])
        self.assertEqual(wolfdawn.parse_names_wrap_counts(res.stdout), 3)

    def test_names_wrap_dry_run(self):
        captured = {}

        def fake_run(args, log_fn=None):
            captured["args"] = list(args)
            return wolfdawn.WolfResult(
                0,
                "names-wrap: 2 entry(ies) WOULD be re-wrapped",
                "",
                [str(a) for a in args],
            )

        with patch.object(wolfdawn, "_run", side_effect=fake_run):
            wolfdawn.names_wrap("/tmp/names.json", dry_run=True)
        self.assertEqual(captured["args"], ["names-wrap", "/tmp/names.json", "--dry-run"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
