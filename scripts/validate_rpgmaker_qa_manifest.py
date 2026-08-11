#!/usr/bin/env python3
"""Independently validate a frozen RPG Maker QA inventory manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from util.rpgmaker_qa_verify import verify_manifest  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--game-root", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    game_root = args.game_root.expanduser().resolve()
    data = args.data.expanduser().resolve()
    if not game_root.is_dir() or not data.is_dir() or game_root not in data.parents:
        parser.error("--data must be a folder inside --game-root")
    manifest_path = args.manifest.expanduser().resolve()
    if manifest_path == game_root or game_root in manifest_path.parents:
        parser.error("--manifest must be outside the game folder")
    if args.report:
        report_path = args.report.expanduser().resolve()
        if report_path == game_root or game_root in report_path.parents:
            parser.error("--report must be outside the game folder")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    report = verify_manifest(data, manifest)
    rendered = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.report:
        destination = args.report.expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".tmp")
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(destination)
    print(rendered, end="")
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
