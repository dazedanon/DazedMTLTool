#!/usr/bin/env python3
"""
Extract Japanese/player-facing text from the local Loser Life export.

The extractor is intentionally AssetRipper-first because the YAML project export
keeps MonoBehaviour field names, scene UI text, Dialogue System database fields,
and custom shop/NPC/tutorial fields readable. It writes all occurrences to CSV
and JSON, plus a deduped human-readable text dump.
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import re
import warnings
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


JAPANESE_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
SCALAR_RE = re.compile(r"^(\s*)(?:-\s+)?([A-Za-z_][\w$<>.\-]*):(?:\s*(.*))?$")
LIST_ITEM_RE = re.compile(r"^(\s*)-\s+(.*)$")
OBJECT_RE = re.compile(r"^--- !u!(\d+) &(-?\d+)")

TEXT_EXTENSIONS = {
    ".anim",
    ".asset",
    ".controller",
    ".json",
    ".overridecontroller",
    ".prefab",
    ".txt",
    ".unity",
    ".yaml",
    ".yml",
}

NOISE_PATH_PARTS = {
    "/font/",
    "/fonts/",
    "/textmesh pro/",
    "/textmeshpro/",
    "/tmp/",
}

NOISE_FIELD_NAMES = {
    "m_atlastextures",
    "m_characterlookupdictionary",
    "m_charactertable",
    "m_creationsettings",
    "m_fallbackfontassettable",
    "m_fontasset",
    "m_fontfeaturetable",
    "m_fontinfo",
    "m_glyphtable",
    "m_kerningtable",
    "m_material",
    "m_script",
    "serializedversion",
}

TITLE_FIELDS = {
    "title",
    "name",
    "m_name",
    "fieldname",
    "label",
    "displayname",
}

PLAYER_TEXT_FIELDS = {
    "m_text",
    "text",
    "value",
    "dialogtitle",
    "dialogtitlewhenlock",
    "fixedtext",
    "fixedtext_1",
    "fixedtext_2",
    "fixedtext_3",
    "fixedtext_4",
    "talk_1",
    "talk_2",
    "talk_3",
    "lookboobstalk_1",
    "lookboobstalk_2",
    "lookboobstalk_3",
    "lookvagtalk_1",
    "lookvagtalk_2",
    "lookvagtalk_3",
    "ejatalk_1",
    "ejatalk_2",
    "ejatalk_3",
    "shopname",
    "preshoptext",
    "aftershoptext",
    "cancelshoptext",
    "preshoppewtext",
    "aftershoppewtext",
    "cancelshoppewtext",
    "playershowshoptext",
    "playercancelshoptext",
    "playershowshoppewtext",
    "playercancelshoppewtext",
    "girlshoptext_1",
    "girlshoptext_2",
    "girlshoptext_3",
    "salecostumes",
    "itemname",
    "infoname",
    "mainname",
    "subname",
    "dungeonname",
    "tip",
    "tiptext",
    "itemtip",
    "iteminfotiptext",
    "dungeiontiptext",
    "message",
    "alert",
    "clearmessage",
    "notpermitmessage",
    "startalertmessage",
    "productname",
}

PLACEHOLDER_TEXT = {
    "New Text",
    "None",
    "Close",
    "Clear",
    "Submit",
    "Enter command...",
}


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


def has_japanese(text: str) -> bool:
    return bool(JAPANESE_RE.search(text))


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def normalized_rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def find_exported_project(root: Path) -> Path:
    candidates = sorted(root.glob("AssetRipper_export_*/ExportedProject"))
    if not candidates:
        raise FileNotFoundError("No AssetRipper ExportedProject folder found.")
    return candidates[-1]


def iter_scan_roots(exported_project: Path) -> Iterable[Path]:
    for name in ("Assets", "ProjectSettings"):
        path = exported_project / name
        if path.exists():
            yield path


def is_text_file(path: Path) -> bool:
    if path.suffix.lower() == ".meta":
        return False
    return path.suffix.lower() in TEXT_EXTENSIONS


def parse_scalar(raw_value: str | None) -> str:
    if raw_value is None:
        return ""
    raw = raw_value.strip()
    if not raw:
        return ""
    if raw in {"|", "|-", "|+", ">", ">-", ">+"}:
        return raw
    if raw[0] in {"'", '"'}:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                value = ast.literal_eval(raw)
            return str(value)
        except Exception:
            quote = raw[0]
            if raw.endswith(quote):
                raw = raw[1:-1]
            return raw.replace("\\n", "\n").replace("\\r", "\r").replace('\\"', '"')
    hash_pos = raw.find(" #")
    if hash_pos >= 0:
        raw = raw[:hash_pos].rstrip()
    return raw


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u200b", "")
    return text.strip()


def looks_like_character_table(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    if len(compact) < 320:
        return False
    unique_ratio = len(set(compact)) / max(len(compact), 1)
    has_sentence_marks = any(mark in compact for mark in ("。", "．", "、", "！", "？"))
    return unique_ratio > 0.38 and not has_sentence_marks


def should_skip(path: Path, rel_path: str, field: str, text: str) -> bool:
    if not text or not has_japanese(text):
        return True
    lower_rel = "/" + rel_path.lower()
    lower_field = field.lower()
    if "linebreaking" in lower_rel:
        return True
    if any(part in lower_rel for part in NOISE_PATH_PARTS):
        return True
    if lower_field in NOISE_FIELD_NAMES:
        return True
    if looks_like_character_table(text):
        return True
    if path.suffix.lower() == ".cs" and "header(" in text.lower():
        return True
    if text in PLACEHOLDER_TEXT:
        return True
    return False


def category_for(path: Path, rel_path: str, field: str, label: str, context: str) -> str:
    rel_lower = rel_path.lower()
    field_lower = field.lower()
    label_lower = label.lower()
    context_lower = context.lower()

    if "dialogue database.asset" in rel_lower or label_lower in {
        "dialogue text",
        "menu text",
        "sequence",
        "conditions",
        "user script",
    }:
        return "dialogue_database"
    if "tutorial.unity" in rel_lower:
        return "tutorial_ui"
    if field_lower in {
        "talk_1",
        "talk_2",
        "talk_3",
        "lookboobstalk_1",
        "lookboobstalk_2",
        "lookboobstalk_3",
        "lookvagtalk_1",
        "lookvagtalk_2",
        "lookvagtalk_3",
        "ejatalk_1",
        "ejatalk_2",
        "ejatalk_3",
    }:
        return "npc_ambient_dialogue"
    if "shop" in field_lower or "shop" in context_lower:
        return "shop_text"
    if field_lower == "m_text":
        return "ui_text"
    if any(token in field_lower for token in ("tip", "message", "alert")):
        return "ui_message"
    if any(token in field_lower for token in ("item", "dungeon", "costume", "name")):
        return "game_data_name"
    if field_lower == "m_name":
        return "asset_name"
    if field_lower in PLAYER_TEXT_FIELDS:
        return "player_text"
    return "japanese_text"


def best_label(label_by_indent: dict[int, str], indent: int) -> str:
    for candidate in (indent, indent - 2, indent - 4, indent - 6):
        if candidate in label_by_indent:
            return label_by_indent[candidate]
    lower_keys = [key for key in label_by_indent if key <= indent]
    if not lower_keys:
        return ""
    return label_by_indent[max(lower_keys)]


def best_container(container_by_indent: dict[int, str], indent: int) -> str:
    lower_keys = [key for key in container_by_indent if key < indent]
    if not lower_keys:
        return "list_item"
    return container_by_indent[max(lower_keys)]


def add_row(
    rows: list[TextRow],
    root: Path,
    path: Path,
    line_no: int,
    field: str,
    value: str,
    context: str,
    object_type: str,
    object_id: str,
    label: str = "",
) -> None:
    rel_path = normalized_rel(path, root)
    text = clean_text(value)
    if should_skip(path, rel_path, field, text):
        return
    display_field = field
    if field == "value" and label:
        display_field = f"value[{label}]"
    category = category_for(path, rel_path, field, label, context)
    rows.append(
        TextRow(
            category=category,
            source_file=rel_path,
            line=line_no,
            field=display_field,
            context=clean_text(context),
            object_type=object_type,
            object_id=object_id,
            text=text,
        )
    )


def flush_block(
    rows: list[TextRow],
    root: Path,
    path: Path,
    block: dict[str, object] | None,
    current_context: str,
    current_object_type: str,
    current_object_id: str,
) -> None:
    if not block:
        return
    value = "\n".join(str(part) for part in block["parts"])
    add_row(
        rows,
        root,
        path,
        int(block["line"]),
        str(block["field"]),
        value,
        current_context,
        current_object_type,
        current_object_id,
        str(block.get("label", "")),
    )


def scan_file(root: Path, path: Path) -> list[TextRow]:
    rows: list[TextRow] = []
    current_context = ""
    current_object_type = ""
    current_object_id = ""
    label_by_indent: dict[int, str] = {}
    container_by_indent: dict[int, str] = {}
    block: dict[str, object] | None = None

    try:
        stream = path.open("r", encoding="utf-8-sig", errors="replace")
    except OSError:
        return rows

    with stream:
        for line_no, raw_line in enumerate(stream, start=1):
            line = raw_line.rstrip("\n\r")

            if block:
                block_indent = int(block["indent"])
                indent = len(line) - len(line.lstrip(" "))
                if not line.strip() or indent > block_indent:
                    block["parts"].append(line[block_indent + 1 :] if len(line) > block_indent else "")
                    continue
                flush_block(rows, root, path, block, current_context, current_object_type, current_object_id)
                block = None

            object_match = OBJECT_RE.match(line)
            if object_match:
                current_object_type = object_match.group(1)
                current_object_id = object_match.group(2)
                current_context = ""
                label_by_indent.clear()
                container_by_indent.clear()
                continue

            scalar_match = SCALAR_RE.match(line)
            if scalar_match:
                indent = len(scalar_match.group(1).replace("\t", "    "))
                field = scalar_match.group(2)
                raw_value = scalar_match.group(3)
                field_lower = field.lower()
                label = best_label(label_by_indent, indent)

                if raw_value is None or raw_value.strip() == "":
                    container_by_indent[indent] = field
                    continue

                parsed = parse_scalar(raw_value)
                if parsed in {"|", "|-", "|+", ">", ">-", ">+"}:
                    block = {
                        "field": field,
                        "line": line_no,
                        "indent": indent,
                        "parts": [],
                        "label": label,
                    }
                    continue

                if field_lower == "m_name":
                    current_context = parsed
                if field_lower in TITLE_FIELDS and parsed:
                    label_by_indent[indent] = parsed

                add_row(
                    rows,
                    root,
                    path,
                    line_no,
                    field,
                    parsed,
                    current_context,
                    current_object_type,
                    current_object_id,
                    label,
                )
                continue

            list_match = LIST_ITEM_RE.match(line)
            if list_match:
                indent = len(list_match.group(1).replace("\t", "    "))
                parsed = parse_scalar(list_match.group(2))
                field = best_container(container_by_indent, indent)
                add_row(
                    rows,
                    root,
                    path,
                    line_no,
                    field,
                    parsed,
                    current_context,
                    current_object_type,
                    current_object_id,
                )
                continue

            if path.suffix.lower() in {".txt", ".json"} and has_japanese(line):
                add_row(
                    rows,
                    root,
                    path,
                    line_no,
                    "line",
                    line,
                    current_context,
                    current_object_type,
                    current_object_id,
                )

    if block:
        flush_block(rows, root, path, block, current_context, current_object_type, current_object_id)
    return rows


def scan_roots(scan_roots: Iterable[Path]) -> list[TextRow]:
    all_rows: list[TextRow] = []
    for root in scan_roots:
        for path in root.rglob("*"):
            if not path.is_file() or not is_text_file(path):
                continue
            all_rows.extend(scan_file(root.parent, path))
    return sorted(all_rows, key=lambda row: (row.source_file.lower(), row.line, row.field, row.text))


def write_csv(path: Path, rows: list[TextRow]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(rows[0]).keys()) if rows else list(TextRow.__annotations__))
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def write_json(path: Path, rows: list[TextRow]) -> None:
    with path.open("w", encoding="utf-8-sig") as handle:
        json.dump([asdict(row) for row in rows], handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def source_ref(row: TextRow) -> str:
    context = f" [{row.context}]" if row.context else ""
    field = f" {row.field}" if row.field else ""
    return f"{row.source_file}:{row.line}{field}{context}"


def write_text_dump(path: Path, rows: list[TextRow], exported_project: Path) -> None:
    category_counts = Counter(row.category for row in rows)
    file_counts = Counter(row.source_file for row in rows)
    unique_by_category: dict[str, dict[str, list[TextRow]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        unique_by_category[row.category][row.text].append(row)

    unique_total = sum(len(items) for items in unique_by_category.values())
    generated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with path.open("w", encoding="utf-8-sig", newline="\n") as handle:
        handle.write("Loser Life Japanese Text Dump\n")
        handle.write(f"Generated: {generated}\n")
        handle.write(f"AssetRipper project: {exported_project}\n\n")

        handle.write("Summary\n")
        handle.write(f"- Occurrences: {len(rows)}\n")
        handle.write(f"- Unique strings: {unique_total}\n")
        handle.write(f"- Source files: {len(file_counts)}\n")
        handle.write("- Categories:\n")
        for category, count in category_counts.most_common():
            handle.write(f"  - {category}: {count}\n")

        handle.write("\nCoverage Checks\n")
        coverage_terms = {
            "Dialogue Database.asset": any("Dialogue Database.asset" in row.source_file for row in rows),
            "Tutorial scene UI": any("01_Scenes/Tutorial.unity" in row.source_file for row in rows),
            "Tutorial dialogue database entries": any(
                "Dialogue Database.asset" in row.source_file and ("Tutorial" in row.context or "Tutorial" in row.source_file)
                for row in rows
            ),
            "DefaultVillagerTalk fields": any(row.category == "npc_ambient_dialogue" for row in rows),
            "Shop/Costume shop fields": any(row.category == "shop_text" for row in rows),
            "Project productName": any(row.field.lower() == "productname" for row in rows),
        }
        for name, ok in coverage_terms.items():
            handle.write(f"- {name}: {'yes' if ok else 'no'}\n")

        for category in sorted(unique_by_category):
            texts = unique_by_category[category]
            handle.write(f"\n## {category} ({len(texts)} unique)\n")
            for index, text in enumerate(sorted(texts), start=1):
                handle.write(f"\n[{index:04d}]\n")
                text_lines = text.split("\n") or [""]
                for i, text_line in enumerate(text_lines):
                    prefix = "text: " if i == 0 else "      "
                    handle.write(f"{prefix}{text_line}\n")
                sources = texts[text]
                handle.write(f"occurrences: {len(sources)}\n")
                handle.write("sources:\n")
                for row in sources[:10]:
                    handle.write(f"- {source_ref(row)}\n")
                if len(sources) > 10:
                    handle.write(f"- ... {len(sources) - 10} more occurrence(s)\n")


def write_summary(path: Path, rows: list[TextRow]) -> None:
    category_counts = Counter(row.category for row in rows)
    file_counts = Counter(row.source_file for row in rows)
    with path.open("w", encoding="utf-8-sig", newline="\n") as handle:
        handle.write("Japanese text extraction summary\n\n")
        handle.write(f"Occurrences: {len(rows)}\n")
        handle.write(f"Unique strings: {len(set(row.text for row in rows))}\n")
        handle.write(f"Source files: {len(file_counts)}\n\n")
        handle.write("Categories\n")
        for category, count in category_counts.most_common():
            handle.write(f"- {category}: {count}\n")
        handle.write("\nTop source files\n")
        for source_file, count in file_counts.most_common(30):
            handle.write(f"- {source_file}: {count}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract Japanese/player-facing text from the AssetRipper export.")
    parser.add_argument(
        "--exported-project",
        type=Path,
        default=None,
        help="Path to AssetRipper ExportedProject. Defaults to the newest AssetRipper_export_*/ExportedProject.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory. Defaults to tooling/outputs.",
    )
    args = parser.parse_args()

    root = repo_root()
    exported_project = args.exported_project or find_exported_project(root)
    output_dir = args.output_dir or (root / "tooling" / "outputs")
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = scan_roots(iter_scan_roots(exported_project))

    csv_path = output_dir / "japanese_text_all_occurrences.csv"
    json_path = output_dir / "japanese_text_all_occurrences.json"
    txt_path = output_dir / "japanese_text_dump.txt"
    summary_path = output_dir / "japanese_text_summary.txt"

    write_csv(csv_path, rows)
    write_json(json_path, rows)
    write_text_dump(txt_path, rows, exported_project)
    write_summary(summary_path, rows)

    print(f"Occurrences: {len(rows)}")
    print(f"Unique strings: {len(set(row.text for row in rows))}")
    print(f"Wrote: {txt_path}")
    print(f"Wrote: {csv_path}")
    print(f"Wrote: {json_path}")
    print(f"Wrote: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
