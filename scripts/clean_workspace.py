#!/usr/bin/env python3
"""Safely report or remove regenerable DazedTL workspace artifacts."""

from __future__ import annotations

import argparse
import os
import shutil
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEBUG_LOG_NAMES = (
    "request_debug.log",
    "request_debug.log.1",
    "request_debug.log.2",
    "debug.log",
    "debug.log.1",
    "debug.log.2",
)


class CleanupSafetyError(RuntimeError):
    """Raised when a cleanup target cannot be deleted safely."""


@dataclass(frozen=True)
class CleanupTarget:
    path: Path
    category: str
    size: int


def _inside_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return path != root


def _tree_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for current, directories, files in os.walk(path, followlinks=False):
        current_path = Path(current)
        for name in directories:
            candidate = current_path / name
            if candidate.is_symlink():
                raise CleanupSafetyError(f"refusing directory containing symlink: {candidate}")
        for name in files:
            candidate = current_path / name
            if candidate.is_symlink():
                raise CleanupSafetyError(f"refusing directory containing symlink: {candidate}")
            total += candidate.stat().st_size
    return total


def _target(path: Path, category: str, root: Path) -> CleanupTarget | None:
    if not path.exists():
        return None
    if path.is_symlink():
        raise CleanupSafetyError(f"refusing symlink cleanup target: {path}")
    resolved = path.resolve()
    if not _inside_root(resolved, root):
        raise CleanupSafetyError(f"cleanup target escaped repository: {path}")
    return CleanupTarget(resolved, category, _tree_size(resolved))


def capture_targets(root: Path, keep: int) -> list[CleanupTarget]:
    if keep < 0:
        raise ValueError("keep must be non-negative")
    capture_root = root / ".tmp-ui"
    if not capture_root.exists():
        return []
    if capture_root.is_symlink():
        raise CleanupSafetyError(f"refusing symlink capture root: {capture_root}")
    entries = list(capture_root.iterdir())
    linked = [path for path in entries if path.is_symlink()]
    if linked:
        raise CleanupSafetyError(f"refusing symlink below capture root: {linked[0]}")
    runs = sorted(
        (path for path in entries if path.is_dir()),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
        reverse=True,
    )
    targets = []
    for path in runs[keep:]:
        candidate = _target(path, "capture", root)
        if candidate:
            targets.append(candidate)
    return targets


def debug_log_targets(root: Path) -> list[CleanupTarget]:
    targets = []
    for name in DEBUG_LOG_NAMES:
        candidate = _target(root / "log" / name, "debug-log", root)
        if candidate:
            targets.append(candidate)
    return targets


def stale_tool_targets(root: Path) -> list[CleanupTarget]:
    targets = []
    cli = root / "util" / "ace" / "RPGMakerDecrypter-cli.exe"
    legacy_decrypter = root / "util" / "ace" / "RPGMakerDecrypter.exe"
    if cli.is_file():
        candidate = _target(legacy_decrypter, "stale-tool", root)
        if candidate:
            targets.append(candidate)

    forge = root / "util" / "forge"
    if (forge / "Forge_MV.js").is_file() and (forge / "upstream" / "Forge_MV.js").is_file():
        candidate = _target(forge / "legacy", "stale-tool", root)
        if candidate:
            targets.append(candidate)
    return targets


def remove_targets(targets: list[CleanupTarget], root: Path) -> None:
    for target in targets:
        if not _inside_root(target.path, root) or target.path.is_symlink():
            raise CleanupSafetyError(f"cleanup target failed final validation: {target.path}")
        if target.path.is_dir():
            _tree_size(target.path)
            shutil.rmtree(target.path)
        elif target.path.is_file():
            target.path.unlink()


def _format_size(size: int) -> str:
    value = float(size)
    for suffix in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or suffix == "GiB":
            return f"{value:.1f} {suffix}"
        value /= 1024
    return f"{size} B"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--captures", action="store_true", help="remove old .tmp-ui capture runs")
    parser.add_argument("--debug-logs", action="store_true", help="remove request/token debug logs")
    parser.add_argument("--stale-tools", action="store_true", help="remove verified redundant tool copies")
    parser.add_argument("--all", action="store_true", help="select every cleanup category")
    parser.add_argument("--keep-captures", type=int, default=5, help="newest capture runs to retain (default: 5)")
    parser.add_argument("--apply", action="store_true", help="perform deletion; otherwise only report")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    selected = args.all or args.captures or args.debug_logs or args.stale_tools
    if not selected:
        print("Nothing selected. Use --all or choose a cleanup category.")
        return 2

    root = PROJECT_ROOT.resolve()
    targets: list[CleanupTarget] = []
    if args.all or args.captures:
        targets.extend(capture_targets(root, args.keep_captures))
    if args.all or args.debug_logs:
        targets.extend(debug_log_targets(root))
    if args.all or args.stale_tools:
        targets.extend(stale_tool_targets(root))

    for target in targets:
        print(f"{target.category:10} {_format_size(target.size):>10}  {target.path.relative_to(root)}")
    total = sum(target.size for target in targets)
    action = "Removed" if args.apply else "Would remove"
    if args.apply:
        remove_targets(targets, root)
    print(f"{action} {len(targets)} target(s), {_format_size(total)} total.")
    if not args.apply and targets:
        print("Dry run only; repeat with --apply after reviewing every target.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
