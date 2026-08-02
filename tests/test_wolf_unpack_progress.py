"""Tests for WolfDawn unpack progress helpers."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from util.wolfdawn import (
    WolfResult,
    _UNPACK_ARCHIVE_DONE_RE,
    _UNPACK_ONE_DONE_RE,
    _UNPACK_SUMMARY_RE,
    _run_streaming,
    count_unpack_archives,
    unpack_all,
)


class WolfUnpackProgressTests(unittest.TestCase):
    def test_unpack_progress_regex_cases(self):
        cases = (
            (
                "archive",
                _UNPACK_ARCHIVE_DONE_RE,
                "  MapData.wolf -> /tmp/out/MapData (74 files)",
                {"name": "MapData.wolf", "files": "74"},
            ),
            (
                "summary",
                _UNPACK_SUMMARY_RE,
                "unpack-all: 24 archive(s), 60265 files",
                {"archives": "24", "files": "60265"},
            ),
            (
                "single archive",
                _UNPACK_ONE_DONE_RE,
                "unpacked 74 files -> /tmp/out/MapData",
                {"files": "74"},
            ),
        )
        for label, pattern, line, expected_groups in cases:
            with self.subTest(label):
                match = pattern.match(line)
                self.assertIsNotNone(match)
                for group, expected in expected_groups.items():
                    self.assertEqual(match.group(group), expected)

    def test_count_unpack_archives_explicit_list(self):
        import tempfile

        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            (base / "A.wolf").write_bytes(b"")
            (base / "B.wolf").write_bytes(b"")
            self.assertEqual(count_unpack_archives([base / "A.wolf", base / "B.wolf"]), 2)

    def test_count_unpack_archives_directory(self):
        import tempfile

        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            (base / "MapData.wolf").write_bytes(b"")
            (base / "BasicData.wolf").write_bytes(b"")
            self.assertEqual(count_unpack_archives([base]), 2)

    def test_unpack_all_uses_separate_subprocess_per_archive(self):
        import tempfile

        calls: list[list[str]] = []

        def fake_run(args, log_fn=None):
            calls.append(list(args))
            name = Path(args[1]).name
            files = "10" if name.startswith("Basic") else "5"
            return WolfResult(
                returncode=0,
                stdout=f"unpacked {files} files -> /tmp/out\n",
                stderr="",
                argv=["wolf", *args],
            )

        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            a = base / "BasicData.wolf"
            b = base / "MapData.wolf"
            a.write_bytes(b"x")
            b.write_bytes(b"x")
            out = base / "out"
            with patch("util.wolfdawn._run", side_effect=fake_run):
                result = unpack_all([a, b], out, progress_total=2)

        self.assertTrue(result.ok)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][:2], ["unpack", str(a)])
        self.assertEqual(calls[1][:2], ["unpack", str(b)])
        self.assertTrue(str(out / "BasicData") in calls[0][3])
        self.assertTrue(str(out / "MapData") in calls[1][3])

    def test_run_streaming_emits_unpack_progress(self):
        events: list[tuple[int, int, str]] = []

        def fake_popen(argv, **kwargs):
            class FakeProc:
                stdout = [
                    "  BasicData.wolf -> /tmp/BasicData (10 files)\n",
                    "  MapData.wolf -> /tmp/MapData (5 files)\n",
                    "unpack-all: 2 archive(s), 15 files\n",
                ]

                def __init__(self):
                    self._idx = 0

                def readline(self):
                    if self._idx >= len(self.stdout):
                        return ""
                    line = self.stdout[self._idx]
                    self._idx += 1
                    return line

                def wait(self):
                    return 0

            return FakeProc()

        with patch("util.wolfdawn.ensure_wolf_binary", return_value=Path("/wolf")):
            with patch("util.wolfdawn.subprocess.Popen", side_effect=fake_popen):
                result = _run_streaming(
                    ["unpack-all", "A.wolf", "-o", "/tmp/out"],
                    progress_fn=lambda c, t, l: events.append((c, t, l)),
                    progress_total=2,
                )

        self.assertTrue(result.ok)
        self.assertEqual(events[0], (0, 2, "Unpacking archive 1 of 2 …"))
        self.assertEqual(events[-1][0], 2)
        self.assertEqual(events[-1][1], 2)


if __name__ == "__main__":
    unittest.main()
