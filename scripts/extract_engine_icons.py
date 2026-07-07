#!/usr/bin/env python3
"""Extract engine icons from Game.exe files into assets/engine_icons/.

Default search paths cover common locations on this machine; override with flags:

    python scripts/extract_engine_icons.py
    python scripts/extract_engine_icons.py --ace /path/to/ace/Game.exe --srpg /path/to/srpg/Game.exe
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from util.pe_icon import extract_best_icon_png  # noqa: E402
from util.paths import ENGINE_ICONS_DIR  # noqa: E402

# Known-good sources for bundled engine artwork (first existing path wins).
_DEFAULT_SOURCES: dict[str, list[Path]] = {
    "mvmz": [
        Path.home() / "DazedTranslations/Games/Shrift II/Game.exe",
    ],
    "wolf": [
        Path.home() / "DazedTranslations/Tools/WOLF/Editor/Editor 2.24Z.exe",
        Path.home() / "DazedTranslations/Tools/WOLF/Editor/Game.exe",
        Path.home()
        / "DazedTranslations/Games/[Ryuugames] RY-RJ01633249/RJ01633249/銀眼のライトナ/Game.exe",
    ],
    "ace": [
        # VX Ace Game.exe (RGSS3 player) - no default install on this machine.
    ],
    "srpg": [
        # SRPG Studio Game.exe - no default install on this machine.
    ],
}


def _resolve_source(engine: str, overrides: dict[str, Path | None]) -> Path | None:
    if overrides.get(engine):
        return overrides[engine]
    for candidate in _DEFAULT_SOURCES.get(engine, []):
        if candidate.is_file():
            return candidate
    return None


def extract_engine_icons(
  overrides: dict[str, Path | None] | None = None,
  *,
  dest_dir: Path | None = None,
) -> dict[str, str]:
    """Extract icons for each engine; return ``{engine: status_message}``."""
    overrides = overrides or {}
    dest_dir = dest_dir or ENGINE_ICONS_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, str] = {}

    for engine in ("mvmz", "wolf", "ace", "srpg"):
        src = _resolve_source(engine, overrides)
        out = dest_dir / f"{engine}.png"
        if src is None:
            results[engine] = "skipped (no source .exe; pass --{0} PATH)".format(engine)
            continue
        size = extract_best_icon_png(src, out, min_size=64 if engine == "wolf" else 0)
        if size is None:
            results[engine] = f"failed (no icon in {src})"
        else:
            results[engine] = f"ok {size[0]}x{size[1]} from {src}"
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mvmz", type=Path, help="RPG Maker MV/MZ Game.exe")
    parser.add_argument("--wolf", type=Path, help="Wolf RPG Editor or game Game.exe")
    parser.add_argument("--ace", type=Path, help="RPG Maker VX Ace Game.exe")
    parser.add_argument("--srpg", type=Path, help="SRPG Studio Game.exe")
    parser.add_argument("--dest", type=Path, default=ENGINE_ICONS_DIR, help="Output directory")
    args = parser.parse_args(argv)

    overrides = {
        "mvmz": args.mvmz,
        "wolf": args.wolf,
        "ace": args.ace,
        "srpg": args.srpg,
    }
    results = extract_engine_icons(overrides, dest_dir=args.dest)
    failed = 0
    for engine, msg in results.items():
        print(f"{engine}: {msg}")
        if msg.startswith("failed") or (msg.startswith("skipped") and engine in ("mvmz", "wolf")):
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
