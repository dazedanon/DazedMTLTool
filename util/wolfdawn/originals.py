"""Pristine binary snapshots for idempotent WolfDawn inject."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Callable

from util import wolfdawn

ProgressFn = Callable[[int, int, str], None]


def find_data_archives(game_root: Path, data_dir: Path) -> list[Path]:
    """Return MapData / BasicData ``.wolf`` or ``.wolf.bak`` archives."""
    archives: list[Path] = []
    for base in (game_root, data_dir):
        if not base.is_dir():
            continue
        for pat in ("*.wolf", "*.wolf.bak"):
            archives.extend(base.glob(pat))
    return [a for a in archives if a.name.lower().startswith(("mapdata", "basicdata"))]


def rebuild_originals_from_archives(
    game_root: Path,
    originals_dir: Path,
    *,
    force: bool = False,
    log_fn: Callable[[str], None] | None = None,
    progress_fn: ProgressFn | None = None,
) -> bool:
    """Unpack ``BasicData`` / ``MapData`` archives into *originals_dir*.

    When *force* is true, the entire *originals_dir* tree is removed first so
    stale flat snapshots from an old extract cannot survive beside rebuilt data.
    """
    emit = log_fn or (lambda _msg: None)
    data_dir = game_root / "Data"
    archives = find_data_archives(game_root, data_dir)
    if not archives:
        emit("  ⚠ no BasicData/MapData .wolf archives found to rebuild originals")
        return False

    if force and originals_dir.exists():
        shutil.rmtree(originals_dir)
    originals_dir.mkdir(parents=True, exist_ok=True)

    emit("Rebuilding pristine originals from the game's .wolf archives…")
    with tempfile.TemporaryDirectory() as tmp:
        inputs: list[str] = []
        for arc in archives:
            if arc.suffix == ".bak":
                staged = Path(tmp) / arc.with_suffix("").name
                shutil.copy2(arc, staged)
                inputs.append(str(staged))
            else:
                inputs.append(str(arc))
        res = wolfdawn.unpack_all(
            inputs,
            str(originals_dir),
            log_fn=log_fn,
            progress_fn=progress_fn,
            progress_total=len(inputs),
        )
    if not res.ok:
        emit(f"  ⚠ could not rebuild originals (unpack exit {res.returncode})")
        return False
    return True


def names_inject_would_apply(names_json: Path, data_dir: Path) -> int | None:
    """Return how many name changes wolf would apply (dry run), or None if unknown."""
    res = wolfdawn.names_inject(
        str(names_json), str(data_dir), dry_run=True, log_fn=None
    )
    applied, _drifted = wolfdawn.parse_names_inject_counts(res.stdout, res.stderr)
    return applied
