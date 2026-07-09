#!/usr/bin/env python3
"""Unit tests for WolfDawn relayout / names-wrap CLI wrappers."""

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
    def test_relayout_auto_metrics(self):
        captured = {}

        def fake_run(args, log_fn=None):
            captured["args"] = list(args)
            return wolfdawn.WolfResult(0, "", "", [str(a) for a in args])

        with patch.object(wolfdawn, "_run", side_effect=fake_run):
            wolfdawn.relayout("/game/Data", width="auto", max_rows=0, out_dir="/tmp/out")
        args = captured["args"]
        self.assertEqual(args[:2], ["relayout", "/game/Data"])
        self.assertIn("-o", args)
        self.assertIn("/tmp/out", args)
        self.assertIn("--width", args)
        self.assertIn("auto", args)
        self.assertIn("--max-rows", args)
        # max_rows=0 becomes auto
        self.assertEqual(args[args.index("--max-rows") + 1], "auto")

    def test_desc_relayout_auto_max_lines(self):
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
        self.assertIn("--max-lines", args)
        self.assertEqual(args[args.index("--max-lines") + 1], "auto")
        self.assertIn("--keep-breaks", args)

    def test_names_wrap_flags_and_parsers(self):
        captured = {}

        def fake_run(args, log_fn=None):
            captured["args"] = list(args)
            return wolfdawn.WolfResult(
                0,
                '  shrunk to \\f[14] to fit its slot: "Hey! ..."\n'
                '  shrunk to \\f[12] to fit its slot: "That sister..."\n'
                "names-wrap: 7 entry(ies) re-wrapped",
                "",
                [str(a) for a in args],
            )

        with patch.object(wolfdawn, "_run", side_effect=fake_run):
            res = wolfdawn.names_wrap(
                "/tmp/names.json",
                note="説明",
                width=50,
                lines=3,
                dry_run=True,
            )
        self.assertEqual(
            captured["args"],
            [
                "names-wrap",
                "/tmp/names.json",
                "--width",
                "50",
                "--lines",
                "3",
                "--note",
                "説明",
                "--dry-run",
            ],
        )
        self.assertEqual(wolfdawn.parse_names_wrap_counts(res.stdout), 7)
        self.assertEqual(wolfdawn.parse_names_wrap_shrink_count(res.stdout), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
