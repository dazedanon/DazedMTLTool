#!/usr/bin/env python3
"""Restore exported scene overlays that contain pose/state keys.

Some exported scenes include Japanese strings that are not visible UI, but
lookup keys for pose parts and state machines. Translating those can break
limb/clothing visibility. This restores risky scene overlays from the original
unpacked PCK while leaving safer menu/UI overlays in place.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path


ORIGINAL_DEFAULT = Path("unpacked_pck") / ".godot" / "exported"
OVERLAY_DEFAULT = Path("translated_assets") / ".godot" / "exported"
REPORT_DEFAULT = Path("tooling") / "risky_scene_restore_report.json"
RISKY_ASSET_SCENE_RE = re.compile(
    r"(?:goal|novel_front|osawari_auto_panel|posure|sleep_day|sleep_night|statistics_modal|ticket_)",
    re.IGNORECASE,
)


def restore_tree(original_root: Path, overlay_root: Path) -> list[str]:
    restored: list[str] = []
    if not overlay_root.exists():
        return restored

    for overlay_path in sorted(overlay_root.rglob("*")):
        if not overlay_path.is_file() or overlay_path.suffix.lower() not in {".scn", ".res"}:
            continue
        if not RISKY_ASSET_SCENE_RE.search(overlay_path.name):
            continue

        rel = overlay_path.relative_to(overlay_root)
        original_path = original_root / rel
        if not original_path.exists():
            raise FileNotFoundError(f"Missing original scene for overlay: {original_path}")
        shutil.copy2(original_path, overlay_path)
        restored.append(rel.as_posix())

    return restored


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Restore risky exported scene overlays from originals.")
    parser.add_argument("--original-root", type=Path, default=ORIGINAL_DEFAULT)
    parser.add_argument("--overlay-root", type=Path, default=OVERLAY_DEFAULT)
    parser.add_argument("--report", type=Path, default=REPORT_DEFAULT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    restored = restore_tree(args.original_root, args.overlay_root)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(restored, ensure_ascii=False, indent=2), encoding="utf-8")
    print("restored risky scene overlays:", len(restored))
    print("report:", args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
