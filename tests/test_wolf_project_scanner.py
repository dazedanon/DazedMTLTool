"""Tests for WOLF project layout helpers in util.project_scanner."""

from __future__ import annotations

from pathlib import Path

from util.project_scanner import (
    find_wolf_text_archives,
    wolf_has_maps,
    wolf_maps_dir,
    wolf_maps_packed,
)


def test_wolf_maps_dir_prefers_mapdata_subfolder(tmp_path: Path):
    data = tmp_path / "Data"
    (data / "MapData").mkdir(parents=True)
    assert wolf_maps_dir(data) == data / "MapData"


def test_wolf_maps_dir_falls_back_to_data_root(tmp_path: Path):
    data = tmp_path / "Data"
    data.mkdir()
    assert wolf_maps_dir(data) == data


def test_wolf_has_maps(tmp_path: Path):
    data = tmp_path / "Data"
    maps = data / "MapData"
    maps.mkdir(parents=True)
    assert not wolf_has_maps(data)
    (maps / "town.mps").write_bytes(b"")
    assert wolf_has_maps(data)


def test_find_wolf_text_archives_in_data_dir(tmp_path: Path):
    data = tmp_path / "Data"
    data.mkdir()
    (data / "MapData.wolf").write_bytes(b"")
    (data / "BasicData.wolf").write_bytes(b"")
    found = find_wolf_text_archives(tmp_path, data)
    assert found["MapData"] == data / "MapData.wolf"
    assert found["BasicData"] == data / "BasicData.wolf"


def test_wolf_maps_packed_when_archive_present(tmp_path: Path):
    data = tmp_path / "Data"
    data.mkdir()
    (data / "BasicData" / "CommonEvent.dat").mkdir(parents=True)
    (data / "MapData.wolf").write_bytes(b"")
    assert wolf_maps_packed(tmp_path, data)


def test_wolf_maps_packed_false_when_loose_maps_exist(tmp_path: Path):
    data = tmp_path / "Data"
    maps = data / "MapData"
    maps.mkdir(parents=True)
    (maps / "field.mps").write_bytes(b"")
    (data / "MapData.wolf").write_bytes(b"")
    assert not wolf_maps_packed(tmp_path, data)
