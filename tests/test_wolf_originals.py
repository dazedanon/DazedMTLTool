"""Regression tests for WOLF pristine-original discovery and rebuilds."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from util.wolfdawn import WolfResult
from util.wolfdawn import originals as wolf_originals


class WolfOriginalsTests(unittest.TestCase):
    def test_monolithic_data_archive_is_discovered(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            data = root / "Data"
            data.mkdir()
            archive = root / "Data.wolf.bak"
            archive.write_bytes(b"archive")
            (root / "Datatemp.wolf").write_bytes(b"not the baseline")

            self.assertEqual(
                wolf_originals.find_data_archives(root, data),
                [archive],
            )

    def test_split_archives_take_precedence_over_monolithic_archive(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            data = root / "Data"
            data.mkdir()
            (root / "Data.wolf.bak").write_bytes(b"all")
            basic = root / "BasicData.wolf.bak"
            maps = root / "MapData.wolf"
            basic.write_bytes(b"basic")
            maps.write_bytes(b"maps")

            self.assertEqual(
                wolf_originals.find_data_archives(root, data),
                [basic, maps],
            )

    def test_backup_archive_is_preferred_as_the_pristine_baseline(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            data = root / "Data"
            data.mkdir()
            translated_archive = root / "Data.wolf"
            pristine_archive = root / "Data.wolf.bak"
            translated_archive.write_bytes(b"translated")
            pristine_archive.write_bytes(b"pristine")

            self.assertEqual(
                wolf_originals.find_data_archives(root, data),
                [pristine_archive],
            )

    def test_monolithic_rebuild_normalizes_data_directory(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            data = root / "Data"
            data.mkdir()
            (root / "Data.wolf.bak").write_bytes(b"archive")
            originals = root / "wolf_json" / "originals"
            originals.mkdir(parents=True)
            (originals / "stale.txt").write_text("stale", encoding="utf-8")

            def fake_unpack(_inputs, output, **_kwargs):
                unpacked = Path(output) / "Data"
                (unpacked / "BasicData").mkdir(parents=True)
                (unpacked / "MapData").mkdir()
                (unpacked / "BasicData" / "CommonEvent.dat").write_bytes(b"jp")
                return WolfResult(0, "ok", "", ["wolf", "unpack"])

            with patch.object(
                wolf_originals.wolfdawn, "unpack_all", side_effect=fake_unpack
            ):
                rebuilt = wolf_originals.rebuild_originals_from_archives(
                    root, originals, force=True
                )

            self.assertTrue(rebuilt)
            self.assertEqual(
                (originals / "BasicData" / "CommonEvent.dat").read_bytes(),
                b"jp",
            )
            self.assertFalse((originals / "Data").exists())
            self.assertFalse((originals / "stale.txt").exists())

    def test_failed_force_rebuild_preserves_existing_originals(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            data = root / "Data"
            data.mkdir()
            (root / "Data.wolf").write_bytes(b"archive")
            originals = root / "wolf_json" / "originals"
            originals.mkdir(parents=True)
            marker = originals / "keep.dat"
            marker.write_bytes(b"keep")

            failure = WolfResult(4, "", "bad archive", ["wolf", "unpack"])
            with patch.object(
                wolf_originals.wolfdawn, "unpack_all", return_value=failure
            ):
                rebuilt = wolf_originals.rebuild_originals_from_archives(
                    root, originals, force=True
                )

            self.assertFalse(rebuilt)
            self.assertEqual(marker.read_bytes(), b"keep")

    def test_extract_path_prefers_mirrored_pristine_file(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            data = root / "Data"
            live = data / "BasicData" / "CommonEvent.dat"
            pristine = root / "originals" / "BasicData" / "CommonEvent.dat"
            live.parent.mkdir(parents=True)
            pristine.parent.mkdir(parents=True)
            live.write_bytes(b"english")
            pristine.write_bytes(b"japanese")

            self.assertEqual(
                wolf_originals.preferred_extract_path(
                    live, data, root / "originals"
                ),
                pristine,
            )


if __name__ == "__main__":
    unittest.main()
