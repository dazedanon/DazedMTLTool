"""
Project Scanner - Detect game engine and import/export data files.

RPGMaker layouts scanned (in priority order):
  MV/MZ  : <root>/www/data/   or  <root>/data/
  Ace    : <root>/Data/
  XP/VX  : <root>/Data/  (rvdata/rxdata - not currently handled)
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# File categories used to decide what to import by default
# ---------------------------------------------------------------------------

# Core name/database files – almost always needed
CORE_FILES = {
    "Actors.json",
    "Armors.json",
    "Classes.json",
    "Enemies.json",
    "Items.json",
    "MapInfos.json",
    "Skills.json",
    "States.json",
    "System.json",
    "Troops.json",
    "Weapons.json",
    "CommonEvents.json",
    "Animations.json",
    "Tilesets.json",
}

# Map files – large but contain the bulk of dialogue
MAP_PATTERN = "Map[0-9]*.json"

# Engine detection markers
_MVMZ_MARKERS = {           # files / dirs that hint at MV or MZ
    "www",                  # MV web build
    "package.json",         # MZ desktop
    "Game.rpgproject",      # MV
    "game.rmmzproject",     # MZ
}
_ACE_MARKERS = {
    "Game.rgss3a",
    "Game.exe",             # not conclusive but common
}
_ACE_DATA_SCRIPTS = {".rvdata2", ".rvdata"}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def find_data_folder(game_root: str | Path) -> tuple[Optional[Path], str]:
    """Return (data_path, engine_name) for *game_root*.

    engine_name is one of: "MVMZ", "ACE", "UNKNOWN".
    data_path is None when nothing is found.
    """
    root = Path(game_root)
    if not root.is_dir():
        return None, "UNKNOWN"

    # ---- RPGMaker MV/MZ: www/data or data ----
    for candidate in (root / "www" / "data", root / "data", root / "Data"):
        if candidate.is_dir() and _has_json_data(candidate):
            # Confirm engine variant
            engine = "MVMZ"
            for m in _MVMZ_MARKERS:
                if (root / m).exists():
                    engine = "MVMZ"
                    break
            return candidate, engine

    # ---- RPGMaker Ace: Data/ with .rvdata2 ----
    ace_data = root / "Data"
    if ace_data.is_dir():
        rvdata = list(ace_data.glob("*.rvdata2")) + list(ace_data.glob("*.rvdata"))
        if rvdata:
            return ace_data, "ACE"

    # ---- Fallback: any sub-directory that holds .json files ----
    for child in root.iterdir():
        if child.is_dir() and _has_json_data(child):
            return child, "UNKNOWN"

    return None, "UNKNOWN"


def list_data_files(data_path: str | Path, engine: str = "MVMZ") -> list[dict]:
    """Return a sorted list of importable file descriptors.

    Each item: {"name": str, "path": Path, "size_kb": float,
                "category": "core" | "map" | "other", "default": bool}
    """
    data_path = Path(data_path)
    results: list[dict] = []

    if engine == "ACE":
        # Ace uses binary rvdata2; not JSON-based, skip for now
        return results

    seen: set[str] = set()
    for fp in sorted(data_path.iterdir()):
        if not fp.is_file():
            continue
        if fp.suffix.lower() != ".json":
            continue
        name = fp.name
        if name in seen:
            continue
        seen.add(name)

        size_kb = fp.stat().st_size / 1024
        if name in CORE_FILES:
            cat = "core"
            default = True
        elif fp.match(MAP_PATTERN):
            cat = "map"
            default = True
        else:
            cat = "other"
            default = False

        results.append({
            "name": name,
            "path": fp,
            "size_kb": round(size_kb, 1),
            "category": cat,
            "default": default,
        })

    # Sort: core first, then maps (numeric), then other
    def _sort_key(item):
        if item["category"] == "core":
            return (0, item["name"])
        if item["category"] == "map":
            # extract numeric part for natural order
            digits = "".join(c for c in item["name"] if c.isdigit()) or "0"
            return (1, int(digits))
        return (2, item["name"])

    results.sort(key=_sort_key)
    return results


def import_to_files(
    file_items: list[dict],
    dest_dir: str | Path = "files",
    overwrite: bool = True,
) -> tuple[int, list[str]]:
    """Copy *file_items* (from list_data_files) into *dest_dir*.

    Returns (count_copied, list_of_errors).
    """
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    copied = 0
    errors: list[str] = []

    for item in file_items:
        src: Path = item["path"]
        dst = dest / item["name"]
        try:
            if not overwrite and dst.exists():
                continue
            shutil.copy2(src, dst)
            copied += 1
        except Exception as exc:
            errors.append(f"{item['name']}: {exc}")

    return copied, errors


def export_to_game(
    translated_dir: str | Path,
    game_data_path: str | Path,
    filenames: Optional[list[str]] = None,
    overwrite: bool = True,
) -> tuple[int, list[str]]:
    """Copy translated files back into the game's data folder.

    If *filenames* is None, all .json files in *translated_dir* are copied.
    Returns (count_copied, list_of_errors).
    """
    src_dir = Path(translated_dir)
    dst_dir = Path(game_data_path)
    copied = 0
    errors: list[str] = []

    if not src_dir.is_dir():
        return 0, [f"Translated folder not found: {src_dir}"]
    if not dst_dir.is_dir():
        return 0, [f"Game data folder not found: {dst_dir}"]

    candidates = (
        [src_dir / fn for fn in filenames]
        if filenames
        else list(src_dir.glob("*.json"))
    )

    for fp in candidates:
        if not fp.is_file():
            continue
        dst = dst_dir / fp.name
        try:
            if not overwrite and dst.exists():
                continue
            shutil.copy2(fp, dst)
            copied += 1
        except Exception as exc:
            errors.append(f"{fp.name}: {exc}")

    return copied, errors


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has_json_data(folder: Path) -> bool:
    """Return True if the folder contains at least one .json data file."""
    try:
        for p in folder.iterdir():
            if p.suffix.lower() == ".json":
                return True
    except PermissionError:
        pass
    return False
