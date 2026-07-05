"""Tests for WolfDawn unpack progress helpers."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from util.wolfdawn import (
    _UNPACK_ARCHIVE_DONE_RE,
    _UNPACK_SUMMARY_RE,
    _run_streaming,
    count_unpack_archives,
)


class WolfUnpackProgressTests(unittest.TestCase):
    def test_unpack_archive_line_regex(self):
        line = "  MapData.wolf -> /tmp/out/MapData (74 files)"
        match = _UNPACK_ARCHIVE_DONE_RE.match(line)
        self.assertIsNotNone(match)
        self.assertEqual(match.group("name"), "MapData.wolf")
        self.assertEqual(match.group("files"), "74")

    def test_unpack_summary_regex(self):
        line = "unpack-all: 24 archive(s), 60265 files"
        match = _UNPACK_SUMMARY_RE.match(line)
        self.assertIsNotNone(match)
        self.assertEqual(match.group("archives"), "24")
        self.assertEqual(match.group("files"), "60265")

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
