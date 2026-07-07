"""Tests for PE executable icon extraction."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from util.pe_icon import extract_best_icon_png, extract_icon_blobs

_MVMZ_EXE = Path.home() / "DazedTranslations/Games/Shrift II/Game.exe"
_WOLF_EXE = Path.home() / "DazedTranslations/Tools/WOLF/Editor/Editor 2.24Z.exe"


@unittest.skipUnless(_MVMZ_EXE.is_file(), "Shrift II Game.exe not available")
class TestPeIconExtraction(unittest.TestCase):
    def test_extract_mvmz_icon(self) -> None:
        blobs = extract_icon_blobs(_MVMZ_EXE)
        self.assertGreater(len(blobs), 0)

    def test_extract_mvmz_png(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "mvmz.png"
            size = extract_best_icon_png(_MVMZ_EXE, out)
            self.assertIsNotNone(size)
            assert size is not None
            self.assertGreaterEqual(size[0], 32)
            self.assertTrue(out.is_file())


@unittest.skipUnless(_WOLF_EXE.is_file(), "Wolf Editor not available")
class TestWolfIconExtraction(unittest.TestCase):
    def test_extract_wolf_png(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "wolf.png"
            size = extract_best_icon_png(_WOLF_EXE, out)
            self.assertIsNotNone(size)
            assert size is not None
            self.assertGreaterEqual(size[0], 16)
            self.assertTrue(out.is_file())


if __name__ == "__main__":
    unittest.main()
