#!/usr/bin/env python3
"""Restore the ticket_hand runtime GDC overlay from the original unpack.

This is a narrow diagnostic/fix for the mouth/pose regression in the hand
interaction. It leaves scenario text and other translations alone.
"""

from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "unpacked_pck" / "assets" / "osawari" / "ticket_hand" / "ticket_hand.gdc"
TARGET = ROOT / "translated_assets" / "assets" / "osawari" / "ticket_hand" / "ticket_hand.gdc"
BACKUP_DIR = ROOT / "backups" / "overlay_ticket_hand_runtime"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Replace the overlay without saving the previous overlay first.",
    )
    args = parser.parse_args()

    if not SOURCE.is_file():
        raise FileNotFoundError(f"Missing original source: {SOURCE}")

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    if TARGET.exists() and not args.no_backup:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = BACKUP_DIR / f"ticket_hand.gdc.{stamp}.bak"
        shutil.copy2(TARGET, backup)
        print(f"backup: {backup}")

    shutil.copy2(SOURCE, TARGET)
    print(f"restored: {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
