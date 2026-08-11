#!/usr/bin/env python3
"""Build the frozen deterministic inventory used by RPG Maker QA passes."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from util.rpgmaker_qa_manifest import FOCUSES, build_manifest, write_manifest  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, type=Path, help="RPG Maker data folder")
    parser.add_argument("--game-root", required=True, type=Path)
    parser.add_argument("--focus", required=True, choices=sorted(FOCUSES))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    data = args.data.expanduser().resolve()
    game_root = args.game_root.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if not game_root.is_dir() or not data.is_dir() or game_root not in data.parents:
        parser.error("--data must be a folder inside --game-root")
    if output == game_root or game_root in output.parents:
        parser.error("--output must be outside the game folder")
    manifest = build_manifest(data, args.focus)
    write_manifest(manifest, output)
    print(
        f"wrote {output}: {manifest['counts']['records']} records, "
        f"{manifest['counts']['clusters']} clusters, "
        f"{manifest['counts']['unresolved']} unresolved, "
        f"sha256 {manifest['content_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
