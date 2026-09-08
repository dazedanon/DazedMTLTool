#!/usr/bin/env python3
"""
Merge strings learned by the BepInEx runtime harvester into the main text CSV.

Runtime harvesting catches composed strings that are assembled by game code after
static/bundle data loads, such as skill tips with cooldown and MP suffixes.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


CSV_FIELDS = ["category", "source_file", "line", "field", "context", "object_type", "object_id", "text"]
JAPANESE_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uff66-\uff9f]")


@dataclass(frozen=True)
class TextRow:
    category: str
    source_file: str
    line: int
    field: str
    context: str
    object_type: str
    object_id: str
    text: str


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def has_japanese(text: str) -> bool:
    return bool(JAPANESE_RE.search(text or ""))


def clean_text(text: str) -> str:
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").replace("\u200b", "").strip()


def unescape_tsv(value: str) -> str:
    sentinel = "\0"
    return (
        (value or "")
        .replace("\\\\", sentinel)
        .replace("\\t", "\t")
        .replace("\\n", "\n")
        .replace("\\r", "\r")
        .replace(sentinel, "\\")
    )


def category_for(source: str, text: str) -> str:
    lower = source.lower()
    if ".tip" in lower:
        return "player_text"
    if ".name" in lower:
        return "game_data_name"
    if "notpermit" in lower or "message" in lower:
        return "ui_message"
    if any(token in lower for token in ("talk", "dialog", "voice")):
        return "npc_ambient_dialogue"
    return "source_literal"


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv_rows(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in CSV_FIELDS})


def row_key(row: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(row.get(field, "")) for field in CSV_FIELDS)


def is_runtime_row(row: dict[str, Any]) -> bool:
    source = str(row.get("source_file", "")).replace("\\", "/").lower()
    return source.endswith("bepinex/plugins/loserlifeatest/runtime_harvested_texts.tsv")


def parse_runtime_log(path: Path, root: Path) -> list[dict[str, Any]]:
    rows: list[TextRow] = []
    seen: set[tuple[str, str]] = set()
    rel = path.resolve().relative_to(root.resolve()).as_posix()
    if not path.exists():
        return []

    for line_no, line in enumerate(path.read_text(encoding="utf-8-sig", errors="replace").splitlines(), start=1):
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        timestamp = unescape_tsv(parts[0])
        source = unescape_tsv(parts[1])
        text = clean_text(unescape_tsv(parts[2]))
        if not text or not has_japanese(text):
            continue
        key = (source, text)
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            TextRow(
                category=category_for(source, text),
                source_file=rel,
                line=line_no,
                field=source,
                context=f"runtime harvest {timestamp}",
                object_type="RuntimeHarvester",
                object_id=str(line_no),
                text=text,
            )
        )

    return [asdict(row) for row in rows]


def write_json(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.write_text(json.dumps(list(rows), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    root = repo_root()
    parser = argparse.ArgumentParser(description="Merge BepInEx runtime-harvested Japanese text into the main CSV.")
    parser.add_argument("--runtime-log", type=Path, default=root / "BepInEx" / "plugins" / "LoserLifeATest" / "runtime_harvested_texts.tsv")
    parser.add_argument("--outputs-dir", type=Path, default=root / "tooling" / "outputs")
    args = parser.parse_args()

    runtime_rows = parse_runtime_log(args.runtime_log, root)
    runtime_csv = args.outputs_dir / "runtime_harvested_text_all_occurrences.csv"
    runtime_json = args.outputs_dir / "runtime_harvested_text_all_occurrences.json"
    write_csv_rows(runtime_csv, runtime_rows)
    write_json(runtime_json, runtime_rows)
    print(f"Runtime rows written: {len(runtime_rows)}")
    print(f"Runtime unique strings: {len({row['text'] for row in runtime_rows})}")

    main_csv = args.outputs_dir / "japanese_text_all_occurrences.csv"
    main_json = args.outputs_dir / "japanese_text_all_occurrences.json"
    if main_csv.exists():
        backup = args.outputs_dir / f"japanese_text_all_occurrences.pre_runtime_harvest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        shutil.copy2(main_csv, backup)
        print(f"Backed up main CSV: {backup}")

    main_rows = read_csv_rows(main_csv)
    kept_rows = [row for row in main_rows if not is_runtime_row(row)]
    removed = len(main_rows) - len(kept_rows)
    if removed:
        print(f"Removed old runtime harvest rows before merge: {removed}")

    merged: dict[tuple[str, ...], dict[str, Any]] = {row_key(row): row for row in kept_rows}
    before = len(merged)
    for row in runtime_rows:
        merged[row_key(row)] = row
    merged_rows = sorted(merged.values(), key=row_key)
    write_csv_rows(main_csv, merged_rows)
    write_json(main_json, merged_rows)
    print(f"Merged main CSV rows: {len(merged_rows)} ({len(merged_rows) - before} added)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
