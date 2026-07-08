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
        self.assertNotIn("--max-rows", captured["args"])  # 0 omitted

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
        self.assertIn("0", args)
        self.assertIn("--keep-breaks", args)


if __name__ == "__main__":
    unittest.main(verbosity=2)
