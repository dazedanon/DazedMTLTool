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

# WOLF RPG Editor markers. Games ship data inside .wolf archives (one Data.wolf,
# or split BasicData/MapData/... .wolf files), or as a loose Data/ folder holding
# the unpacked binaries (CommonEvent.dat, *.mps maps, *.project databases).
_WOLF_LOOSE_MARKERS = ("BasicData/CommonEvent.dat", "CommonEvent.dat")

_WOLF_TEXT_ARCHIVE_STEMS = ("BasicData", "MapData")


def wolf_maps_dir(data_dir: str | Path) -> Path:
    """Return the folder that holds map ``.mps`` files (``MapData/`` or flat ``Data/``)."""
    data_dir = Path(data_dir)
    nested = data_dir / "MapData"
    return nested if nested.is_dir() else data_dir


def wolf_has_maps(data_dir: str | Path) -> bool:
    """True when loose ``.mps`` map files are present under *data_dir*."""
    return any(wolf_maps_dir(data_dir).glob("*.mps"))


def find_wolf_text_archives(
    game_root: str | Path,
    data_dir: str | Path | None = None,
) -> dict[str, Path]:
    """Return ``{BasicData|MapData: archive_path}`` for text-relevant ``.wolf`` files."""
    game_root = Path(game_root)
    data_dir = Path(data_dir) if data_dir else None
    found: dict[str, Path] = {}
    bases: list[Path] = [game_root]
    if data_dir is not None:
        bases.append(data_dir)
    if (game_root / "Data").is_dir():
        bases.append(game_root / "Data")
    for base in bases:
        if not base.is_dir():
            continue
        for stem in _WOLF_TEXT_ARCHIVE_STEMS:
            if stem in found:
                continue
            for name in (f"{stem}.wolf", f"{stem}.wolf.bak"):
                arc = base / name
                if arc.is_file():
                    found[stem] = arc
                    break
    return found


def wolf_maps_packed(game_root: str | Path, data_dir: str | Path) -> bool:
    """True when map ``.mps`` are not loose but a ``MapData`` archive exists."""
    if wolf_has_maps(data_dir):
        return False
    return "MapData" in find_wolf_text_archives(game_root, data_dir)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def find_data_folder(game_root: str | Path) -> tuple[Optional[Path], str]:
    """Return (data_path, engine_name) for *game_root*.

    engine_name is one of: "MVMZ", "ACE", "WOLF", "UNKNOWN".
    data_path is None when nothing is found.

    For "WOLF" the data_path is the loose Data/ folder when already unpacked, or
    the game root when only .wolf archives are present (still packed).
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

    # ---- WOLF RPG Editor: loose Data/ or .wolf archives ----
    wolf = detect_wolf_layout(root)
    if wolf["engine"] == "WOLF":
        return (wolf["data_dir"] or root), "WOLF"

    # ---- Fallback: any sub-directory that holds .json files ----
    for child in root.iterdir():
        if child.is_dir() and _has_json_data(child):
            return child, "UNKNOWN"

    return None, "UNKNOWN"


def find_wolf_archives(game_root: str | Path) -> list[Path]:
    """Return .wolf archive files in the game root (and its Data/ subfolder)."""
    root = Path(game_root)
    archives: list[Path] = []
    for base in (root, root / "Data"):
        if base.is_dir():
            archives.extend(sorted(base.glob("*.wolf")))
    # De-dupe while preserving order.
    seen: set[Path] = set()
    unique: list[Path] = []
    for a in archives:
        rp = a.resolve()
        if rp not in seen:
            seen.add(rp)
            unique.append(a)
    return unique


def _wolf_dir_has_loose_data(data_dir: Path) -> bool:
    """True when *data_dir* looks like an unpacked WOLF Data folder."""
    if not data_dir.is_dir():
        return False
    for marker in _WOLF_LOOSE_MARKERS:
        if (data_dir / marker).is_file():
            return True
    if list(data_dir.glob("*.mps")) or list((data_dir / "MapData").glob("*.mps")):
        return True
    return False


def wolf_unpack_out_dir(game_root: str | Path, archive: str | Path) -> Path:
    """Return the ``-o`` directory for ``wolf unpack-all`` on *archive*.

    ``wolf`` unpacks ``Name.wolf`` to ``<out>/Name/``. A root-level ``Data.wolf``
    must therefore unpack to the game root (yielding ``Data/``), not into an
    existing ``Data/`` folder (which would incorrectly create ``Data/Data/``).
    """
    game_root = Path(game_root).resolve()
    archive = Path(archive).resolve()
    if archive.stem == "Data" and archive.parent == game_root:
        return game_root
    data_dir = game_root / "Data"
    if data_dir.is_dir() and archive.parent == data_dir:
        return data_dir
    return archive.parent


def wolf_repair_nested_data_dir(game_root: str | Path) -> bool:
    """Hoist ``Data/Data/`` to ``Data/`` after a mistaken ``Data.wolf`` unpack.

    Returns True when the nested layout was repaired.
    """
    outer = Path(game_root) / "Data"
    inner = outer / "Data"
    if not inner.is_dir() or not _wolf_dir_has_loose_data(inner):
        return False
    if any(p.name != "Data" for p in outer.iterdir()):
        return False
    for child in list(inner.iterdir()):
        dest = outer / child.name
        if dest.exists():
            if dest.is_dir():
                shutil.rmtree(dest)
            else:
                dest.unlink()
        shutil.move(str(child), str(dest))
    try:
        inner.rmdir()
    except OSError:
        return False
    return True


def _wolf_loose_data_dir(root: Path) -> Optional[Path]:
    """Return the loose (unpacked) WOLF Data/ folder if it looks unpacked."""
    wolf_repair_nested_data_dir(root)
    for data_dir in (root / "Data", root):
        if _wolf_dir_has_loose_data(data_dir):
            return data_dir
    return None


def detect_wolf_layout(game_root: str | Path) -> dict:
    """Inspect *game_root* for a WOLF RPG Editor game.

    Returns a dict:
        engine     : "WOLF" or "UNKNOWN"
        root       : Path to the game root
        archives   : list[Path] of .wolf archives found (may be empty)
        data_dir   : Path to the loose/unpacked Data/ folder, or None
        unpacked   : bool - True when a usable loose Data/ folder exists
        basic_data : Path to Data/BasicData (or Data/ when flattened), or None
        map_data   : Path to Data/MapData (or Data/ when flattened), or None
    """
    root = Path(game_root)
    result = {
        "engine": "UNKNOWN",
        "root": root,
        "archives": [],
        "data_dir": None,
        "unpacked": False,
        "basic_data": None,
        "map_data": None,
    }
    if not root.is_dir():
        return result

    archives = find_wolf_archives(root)
    loose = _wolf_loose_data_dir(root)

    if not archives and loose is None:
        return result

    result["engine"] = "WOLF"
    result["archives"] = archives
    if loose is not None:
        result["data_dir"] = loose
        result["unpacked"] = True
        basic = loose / "BasicData"
        result["basic_data"] = basic if basic.is_dir() else loose
        result["map_data"] = wolf_maps_dir(loose)
    return result


_WOLF_CORE_JSON = frozenset({
    "names.json",
    "CommonEvent.dat.json",
    "Game.dat.json",
    "DataBase.project.json",
    "CDataBase.project.json",
    "SysDatabase.project.json",
    "Evtext.json",
})

_WOLF_CORE_KINDS = frozenset({"names", "common", "db", "gamedat", "txt-dir"})


def list_wolf_json_files(
    work_dir: str | Path,
    manifest: dict | None = None,
) -> list[dict]:
    """Return importable WolfDawn JSON descriptors from a game's wolf_json/ folder.

    Each item matches :func:`list_data_files` (name, path, size_kb, category, default).
    Uses ``manifest.json`` entries when present; otherwise scans ``*.json`` in *work_dir*.
    """
    work_dir = Path(work_dir)
    rows: list[tuple[str, Path, str]] = []

    if manifest and manifest.get("entries"):
        for entry in manifest["entries"]:
            json_name = entry.get("json")
            if not json_name:
                continue
            fp = work_dir / json_name
            if fp.is_file():
                rows.append((json_name, fp, str(entry.get("kind") or "")))
    elif work_dir.is_dir():
        for fp in sorted(work_dir.glob("*.json")):
            if fp.name == "manifest.json":
                continue
            rows.append((fp.name, fp, ""))

    results: list[dict] = []
    for name, fp, kind in rows:
        size_kb = fp.stat().st_size / 1024
        if name in _WOLF_CORE_JSON or kind in _WOLF_CORE_KINDS:
            cat = "core"
            default = True
        elif name.endswith(".mps.json") or kind == "map":
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

    def _sort_key(item):
        if item["category"] == "core":
            return (0, item["name"])
        if item["category"] == "map":
            stem = item["name"].removesuffix(".mps.json")
            return (1, stem)
        return (2, item["name"])

    results.sort(key=_sort_key)
    return results


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
