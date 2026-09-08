#!/usr/bin/env python3
"""Restore scenario speaker/control prefixes from the original scripts.

Scenario prefixes such as `me:`, `usa00@rt:`, and `システム:` are parser tokens.
They may be displayed as names, but translating the token itself can change game
behavior. This preserves translated dialogue bodies while restoring the original
prefix token at the same line position.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ORIGINAL_DEFAULT = ROOT / "unpacked_pck" / "assets" / "scenarios"
OVERLAY_DEFAULT = ROOT / "translated_assets" / "scenarios"
REPORT_DEFAULT = ROOT / "tooling" / "scenario_prefix_restore_report.json"
BACKUP_ROOT = ROOT / "backups" / "scenario_prefix_restore"

PREFIX_RE = re.compile(r"^(?P<prefix>[^:#\s][^:]*?)(?P<colon>\s*:)")
DISPLAY_PREFIX_REWRITES = {
    "おっさん": "Old Man",
    "屋台のおっさん": "Stall Owner",
    "システム": "System",
    "道具屋さん": "Shopkeeper",
}


def prefix_match(line: str) -> re.Match[str] | None:
    if line.startswith("\ufeff"):
        line = line[1:]
        match = PREFIX_RE.match(line)
        return match
    return PREFIX_RE.match(line)


def restore_file(original_path: Path, overlay_path: Path) -> dict[str, object]:
    original_text = original_path.read_text(encoding="utf-8")
    overlay_text = overlay_path.read_text(encoding="utf-8")
    original_lines = original_text.splitlines(keepends=True)
    overlay_lines = overlay_text.splitlines(keepends=True)

    if len(original_lines) != len(overlay_lines):
        return {
            "status": "skipped_line_count_mismatch",
            "original_lines": len(original_lines),
            "overlay_lines": len(overlay_lines),
        }

    changed: list[dict[str, object]] = []
    out: list[str] = []
    for index, (original_line, overlay_line) in enumerate(zip(original_lines, overlay_lines), start=1):
        original_body = original_line.rstrip("\r\n")
        overlay_body = overlay_line.rstrip("\r\n")
        newline = overlay_line[len(overlay_body) :]

        original_bom = original_body.startswith("\ufeff")
        overlay_bom = overlay_body.startswith("\ufeff")
        original_for_match = original_body[1:] if original_bom else original_body
        overlay_for_match = overlay_body[1:] if overlay_bom else overlay_body

        original_match = PREFIX_RE.match(original_for_match)
        overlay_match = PREFIX_RE.match(overlay_for_match)

        if original_bom != overlay_bom:
            overlay_body = (("\ufeff" if original_bom else "") + overlay_for_match)
            overlay_bom = original_bom
            overlay_for_match = overlay_body[1:] if overlay_bom else overlay_body

        if original_match and overlay_match:
            original_prefix = original_match.group("prefix")
            overlay_prefix = overlay_match.group("prefix")
            if DISPLAY_PREFIX_REWRITES.get(original_prefix) == overlay_prefix:
                out.append(overlay_body + newline)
                continue
            if original_prefix != overlay_prefix:
                patched_body = (
                    ("\ufeff" if overlay_bom else "")
                    + original_prefix
                    + overlay_for_match[overlay_match.start("colon") :]
                )
                out.append(patched_body + newline)
                changed.append(
                    {
                        "line": index,
                        "from": overlay_prefix,
                        "to": original_prefix,
                    }
                )
                continue

        if overlay_body + newline != overlay_line:
            changed.append(
                {
                    "line": index,
                    "from": "BOM" if not original_bom else "no BOM",
                    "to": "no BOM" if not original_bom else "BOM",
                }
            )
            out.append(overlay_body + newline)
        else:
            out.append(overlay_line)

    if changed:
        overlay_path.write_text("".join(out), encoding="utf-8", newline="")

    return {"status": "patched" if changed else "unchanged", "changes": changed}


def restore_tree(original_root: Path, overlay_root: Path, backup: bool) -> dict[str, dict[str, object]]:
    report: dict[str, dict[str, object]] = {}
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    for overlay_path in sorted(overlay_root.rglob("*.txt")):
        rel = overlay_path.relative_to(overlay_root)
        original_path = original_root / rel
        if not original_path.exists():
            continue

        if backup:
            backup_path = BACKUP_ROOT / stamp / rel
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(overlay_path, backup_path)

        result = restore_file(original_path, overlay_path)
        if result["status"] != "unchanged":
            report[rel.as_posix()] = result

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original-root", type=Path, default=ORIGINAL_DEFAULT)
    parser.add_argument("--overlay-root", type=Path, default=OVERLAY_DEFAULT)
    parser.add_argument("--report", type=Path, default=REPORT_DEFAULT)
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args()

    report = restore_tree(args.original_root, args.overlay_root, backup=not args.no_backup)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    patched = sum(
        len(item.get("changes", []))
        for item in report.values()
        if item.get("status") == "patched"
    )
    print(f"files touched/skipped: {len(report)}")
    print(f"prefixes restored: {patched}")
    print(f"report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
