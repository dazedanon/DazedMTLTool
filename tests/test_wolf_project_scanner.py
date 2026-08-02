"""Tests for WOLF project layout helpers in util.project_scanner."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from util.project_scanner import (  # noqa: E402
    detect_wolf_layout,
    find_wolf_text_archives,
    find_wolf_unpack_gaps,
    wolf_has_maps,
    wolf_maps_dir,
    wolf_maps_packed,
    wolf_repair_nested_data_dir,
    wolf_unpack_out_dir,
    wolf_unpack_target_dir,
)


class WolfProjectScannerTests(unittest.TestCase):
    def test_wolf_maps_dir_cases(self):
        for label, has_mapdata in (("MapData subfolder", True), ("Data root", False)):
            with self.subTest(label), tempfile.TemporaryDirectory() as raw:
                data = Path(raw) / "Data"
                data.mkdir()
                if has_mapdata:
                    (data / "MapData").mkdir()
                expected = data / "MapData" if has_mapdata else data
                self.assertEqual(wolf_maps_dir(data), expected)

    def test_wolf_has_maps(self):
        with tempfile.TemporaryDirectory() as raw:
            data = Path(raw) / "Data"
            maps = data / "MapData"
            maps.mkdir(parents=True)
            self.assertFalse(wolf_has_maps(data))
            (maps / "town.mps").write_bytes(b"")
            self.assertTrue(wolf_has_maps(data))

    def test_find_wolf_text_archives_in_data_dir(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            data = base / "Data"
            data.mkdir()
            (data / "MapData.wolf").write_bytes(b"")
            (data / "BasicData.wolf").write_bytes(b"")
            found = find_wolf_text_archives(base, data)
            self.assertEqual(found["MapData"], data / "MapData.wolf")
            self.assertEqual(found["BasicData"], data / "BasicData.wolf")

    def test_wolf_maps_packed_when_archive_present(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            data = base / "Data"
            (data / "BasicData" / "CommonEvent.dat").mkdir(parents=True)
            (data / "MapData.wolf").write_bytes(b"")
            self.assertTrue(wolf_maps_packed(base, data))

    def test_wolf_maps_packed_false_when_loose_maps_exist(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            data = base / "Data"
            maps = data / "MapData"
            maps.mkdir(parents=True)
            (maps / "field.mps").write_bytes(b"")
            (data / "MapData.wolf").write_bytes(b"")
            self.assertFalse(wolf_maps_packed(base, data))

    def test_wolf_unpack_out_dir_cases(self):
        cases = (
            ("root Data.wolf", Path("Data.wolf"), Path(".")),
            ("nested text archive", Path("Data/MapData.wolf"), Path("Data")),
        )
        for label, archive_relative, expected_relative in cases:
            with self.subTest(label), tempfile.TemporaryDirectory() as raw:
                base = Path(raw)
                archive = base / archive_relative
                archive.parent.mkdir(parents=True, exist_ok=True)
                archive.write_bytes(b"")
                self.assertEqual(
                    wolf_unpack_out_dir(base, archive),
                    base / expected_relative,
                )

    def test_wolf_repair_nested_data_dir(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            outer = base / "Data"
            inner = outer / "Data"
            basic = inner / "BasicData"
            basic.mkdir(parents=True)
            (basic / "CommonEvent.dat").write_bytes(b"")
            self.assertTrue(wolf_repair_nested_data_dir(base))
            self.assertTrue((outer / "BasicData" / "CommonEvent.dat").is_file())
            self.assertFalse(inner.exists())

    def test_detect_wolf_layout_after_nested_repair(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            outer = base / "Data"
            inner = outer / "Data"
            basic = inner / "BasicData"
            basic.mkdir(parents=True)
            (basic / "CommonEvent.dat").write_bytes(b"")
            (base / "Data.wolf").write_bytes(b"")
            info = detect_wolf_layout(base)
            self.assertTrue(info["unpacked"])
            self.assertEqual(info["data_dir"], outer)

    def test_find_wolf_unpack_gaps_when_mapdata_missing(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            data = base / "Data"
            basic = data / "BasicData"
            basic.mkdir(parents=True)
            (basic / "CommonEvent.dat").write_bytes(b"")
            (data / "BasicData.wolf").write_bytes(b"")
            (data / "MapData.wolf").write_bytes(b"")
            gaps = find_wolf_unpack_gaps(base)
            self.assertEqual(gaps, [data / "MapData.wolf"])

    def test_find_wolf_unpack_gaps_empty_when_split_archives_unpacked(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            data = base / "Data"
            basic = data / "BasicData"
            maps = data / "MapData"
            basic.mkdir(parents=True)
            maps.mkdir(parents=True)
            (basic / "CommonEvent.dat").write_bytes(b"")
            (maps / "town.mps").write_bytes(b"")
            (data / "BasicData.wolf").write_bytes(b"")
            (data / "MapData.wolf").write_bytes(b"")
            self.assertEqual(find_wolf_unpack_gaps(base), [])

    def test_detect_wolf_layout_reports_unpack_gaps(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            data = base / "Data"
            basic = data / "BasicData"
            basic.mkdir(parents=True)
            (basic / "CommonEvent.dat").write_bytes(b"")
            map_arc = data / "MapData.wolf"
            map_arc.write_bytes(b"")
            info = detect_wolf_layout(base)
            self.assertFalse(info["unpack_complete"])
            self.assertEqual(info["unpack_gaps"], [map_arc])
            self.assertTrue(info["unpacked"])

    def test_wolf_unpack_target_dir(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            data = base / "Data"
            data.mkdir()
            arc = data / "MapData.wolf"
            arc.write_bytes(b"")
            self.assertEqual(wolf_unpack_target_dir(base, arc), data / "MapData")


if __name__ == "__main__":
    unittest.main()
