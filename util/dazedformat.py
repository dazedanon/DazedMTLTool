"""Bundled JSON formatter (dazedformat).

Normalises all .json files in a directory tree by round-tripping them
through json.load / json.dump with indent=4, which ensures consistent
formatting before importing into files/.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable


def format_json_files(
    directory: str | Path,
    log: Callable[[str], None] | None = None,
) -> tuple[int, list[str]]:
    """Format every .json file found under *directory* in-place.

    Returns (formatted_count, error_list).
    """
    directory = Path(directory)
    formatted = 0
    errors: list[str] = []

    for root, _, files in os.walk(directory):
        for name in files:
            if not name.lower().endswith(".json"):
                continue
            fp = Path(root) / name
            try:
                text = fp.read_text(encoding="utf-8")
                data = json.loads(text)
                pretty = json.dumps(data, indent=4, ensure_ascii=False)
                # Only write if the content actually changed
                if pretty != text:
                    fp.write_text(pretty, encoding="utf-8")
                formatted += 1
                if log:
                    log(f"  Formatted: {fp.relative_to(directory)}")
            except Exception as exc:
                msg = f"Error in {fp}: {exc}"
                errors.append(msg)
                if log:
                    log(f"  ⚠  {msg}")

    return formatted, errors
