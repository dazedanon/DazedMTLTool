#!/usr/bin/env python3
"""
Extract Japanese text from runtime-decrypted Unity bundles.

The AssetRipper export misses encrypted bundle content until the game decrypts
it at runtime. The BepInEx test plugin dumps those decrypted streams as
*.decrypted.full.bundle; this script turns their typetrees into the same CSV
shape used by the main Loser Life text tooling.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import UnityPy


CSV_FIELDS = ["category", "source_file", "line", "field", "context", "object_type", "object_id", "text"]
JAPANESE_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uff66-\uff9f]")
ASSET_PATH_RE = re.compile(
    r"(?i)(^assets[\\/]|^resources[\\/]|[\\/].*\.(?:anim|asset|bundle|controller|jpeg|jpg|mat|mp3|ogg|png|prefab|shader|tga|wav)$)"
)

BINARY_HEAVY_TYPE_NAMES = {
    "AudioClip",
    "Cubemap",
    "Font",
    "Material",
    "Mesh",
    "MovieTexture",
    "Shader",
    "Texture2D",
    "Texture3D",
}

SKIP_FIELD_NAMES = {
    "m_atlastextures",
    "m_characterlookupdictionary",
    "m_charactertable",
    "m_component",
    "m_creationsettings",
    "m_fontfeaturetable",
    "m_glyphtable",
    "m_kerningtable",
    "m_material",
    "m_script",
    "serializedversion",
    "charactersequence",
}

PLACEHOLDER_TEXT = {
    "Close",
    "Clear",
    "Enter command...",
    "New Text",
    "None",
    "Submit",
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
    return bool(JAPANESE_RE.search(text or ""))


def clean_text(text: str) -> str:
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").replace("\u200b", "").strip()


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def normalized_rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def looks_like_character_table(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    if len(compact) < 320:
        return False
    unique_ratio = len(set(compact)) / max(len(compact), 1)
    sentence_marks = sum(compact.count(mark) for mark in ("。", "．", "、", "！", "？", "…"))
    has_dialogue_separators = compact.count("@") > 3 or "\n" in text
    if unique_ratio > 0.38 and sentence_marks == 0:
        return True
    return len(compact) > 2000 and unique_ratio > 0.16 and sentence_marks / len(compact) < 0.004 and not has_dialogue_separators


def looks_like_asset_path(text: str) -> bool:
    normalized = text.strip().replace("\\", "/")
    if ASSET_PATH_RE.search(normalized):
        return True
    if "/" not in normalized:
        return False
    suffix = Path(normalized).suffix.lower()
    return suffix in {".anim", ".asset", ".bundle", ".controller", ".jpeg", ".jpg", ".mat", ".mp3", ".ogg", ".png", ".prefab", ".shader", ".tga", ".wav"}


def should_skip(field_path: str, text: str) -> bool:
    if not text or not has_japanese(text):
        return True
    if looks_like_asset_path(text):
        return True
    if text in PLACEHOLDER_TEXT:
        return True
    if looks_like_character_table(text):
        return True
    lower_parts = [part.lower() for part in split_field_path(field_path)]
    if any(part in SKIP_FIELD_NAMES for part in lower_parts):
        return True
    return False


def should_scan_type(type_name: str) -> bool:
    return type_name not in BINARY_HEAVY_TYPE_NAMES


def split_field_path(field_path: str) -> list[str]:
    return [part for part in re.split(r"[.\[\]]+", field_path) if part and not part.isdigit()]


def field_base(field_path: str) -> str:
    parts = split_field_path(field_path)
    return parts[-1].lower() if parts else field_path.lower()


def category_for(object_type: str, field_path: str, context: str) -> str:
    lower_path = field_path.lower()
    lower_context = context.lower()
    base = field_base(field_path)

    if object_type == "AnimationClip" and "m_events" in lower_path and base in {"data", "stringparameter"}:
        return "voice_line"
    if "shop" in lower_path or "shop" in lower_context:
        return "shop_text"
    if base == "m_text" or base == "text" or lower_path.endswith(".m_text"):
        return "ui_text"
    if any(token in lower_path for token in ("dialog", "talk", "serif", "voice", "subtitle")):
        return "npc_ambient_dialogue"
    if any(token in lower_path for token in ("tip", "info", "desc", "description", "explain", "effect", "progress")):
        return "player_text"
    if base in {"name", "m_name", "subname", "displayname", "productname", "title"}:
        return "game_data_name" if object_type != "GameObject" else "asset_name"
    if "skill" in lower_path or "skill" in lower_context:
        return "player_text"
    return "bundle_text"


def type_name_for(obj: Any) -> str:
    try:
        return obj.type.name
    except Exception:
        return str(getattr(obj, "type", ""))


def ptr_path_id(value: Any) -> int | None:
    if isinstance(value, dict):
        for key in ("m_PathID", "path_id", "PathID"):
            if key in value:
                try:
                    return int(value[key])
                except Exception:
                    return None
    return None


def walk_strings(value: Any, field_path: str) -> Iterable[tuple[str, str]]:
    if isinstance(value, str):
        text = clean_text(value)
        if not should_skip(field_path, text):
            yield field_path, text
        return

    if isinstance(value, (bytes, bytearray, memoryview)):
        return

    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            if key_text.lower() in SKIP_FIELD_NAMES:
                continue
            next_path = f"{field_path}.{key_text}" if field_path else key_text
            yield from walk_strings(child, next_path)
        return

    if isinstance(value, (list, tuple)):
        if len(value) > 512:
            sample = value[:64]
            if not any(isinstance(item, (dict, list, tuple, str)) for item in sample):
                return
        for index, child in enumerate(value):
            yield from walk_strings(child, f"{field_path}[{index}]")


def tree_name(tree: dict[str, Any]) -> str:
    for key in ("m_Name", "name", "Name"):
        value = tree.get(key)
        if isinstance(value, str):
            return clean_text(value)
    return ""


def game_object_path_id(tree: dict[str, Any]) -> int | None:
    for key in ("m_GameObject", "gameObject", "GameObject"):
        path_id = ptr_path_id(tree.get(key))
        if path_id is not None:
            return path_id
    return None


def read_typetree(obj: Any) -> dict[str, Any] | None:
    try:
        tree = obj.read_typetree()
        return tree if isinstance(tree, dict) else None
    except Exception:
        return None


def bytes_from_value(value: Any) -> bytes | None:
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, memoryview):
        return value.tobytes()
    if isinstance(value, list) and value and all(isinstance(item, int) and 0 <= item <= 255 for item in value[:2048]):
        try:
            return bytes(value)
        except Exception:
            return None
    return None


def decode_text_asset_payload(value: Any) -> list[str]:
    if isinstance(value, str):
        return [clean_text(value)] if has_japanese(value) else []

    payload = bytes_from_value(value)
    if not payload:
        return []

    decoded: list[str] = []
    for encoding in ("utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", "shift_jis", "cp932"):
        try:
            text = payload.decode(encoding)
        except Exception:
            continue
        text = clean_text(text.replace("\x00", ""))
        if has_japanese(text) and text not in decoded:
            decoded.append(text)
    return decoded


def text_asset_payloads(tree: dict[str, Any]) -> Iterable[tuple[str, str]]:
    for key in ("m_Script", "script", "text", "bytes", "data"):
        if key not in tree:
            continue
        for text in decode_text_asset_payload(tree[key]):
            if not should_skip(key, text):
                yield key, text


def extract_bundle(bundle_path: str, root_text: str) -> tuple[list[dict[str, str | int]], dict[str, Any]]:
    root = Path(root_text)
    path = Path(bundle_path)
    source_file = normalized_rel(path, root)
    rows: list[TextRow] = []
    errors: list[str] = []
    object_counts: Counter[str] = Counter()
    extracted_by_type: Counter[str] = Counter()

    env = UnityPy.load(str(path))
    objects = list(env.objects)
    name_by_path_id: dict[int, str] = {}
    type_by_path_id: dict[int, str] = {}
    tree_by_path_id: dict[int, dict[str, Any]] = {}

    for obj in objects:
        type_name = type_name_for(obj)
        object_counts[type_name] += 1
        type_by_path_id[int(obj.path_id)] = type_name
        if not should_scan_type(type_name):
            continue
        tree = read_typetree(obj)
        if tree is None:
            continue
        tree_by_path_id[int(obj.path_id)] = tree
        name = tree_name(tree)
        if name:
            name_by_path_id[int(obj.path_id)] = name

    for path_id, tree in tree_by_path_id.items():
        type_name = type_by_path_id.get(path_id, "")
        object_name = name_by_path_id.get(path_id, "")
        linked_game_object = game_object_path_id(tree)
        game_object_name = name_by_path_id.get(linked_game_object or -1, "")

        context_parts = []
        if object_name:
            context_parts.append(f"object={object_name}")
        if game_object_name and game_object_name != object_name:
            context_parts.append(f"gameObject={game_object_name}")
        context_base = "; ".join(context_parts)

        if type_name == "TextAsset":
            for field_path, text in text_asset_payloads(tree):
                context = context_base
                if field_path:
                    context = f"{context}; field_path={field_path}" if context else f"field_path={field_path}"
                category = category_for(type_name, field_path, context)
                rows.append(
                    TextRow(
                        category=category,
                        source_file=source_file,
                        line=path_id,
                        field=field_path,
                        context=context,
                        object_type=type_name,
                        object_id=str(path_id),
                        text=text,
                    )
                )
                extracted_by_type[type_name] += 1

        for field_path, text in walk_strings(tree, ""):
            context = context_base
            if field_path and field_path not in {"m_Name", "name", "Name"}:
                context = f"{context}; field_path={field_path}" if context else f"field_path={field_path}"
            category = category_for(type_name, field_path, context)
            rows.append(
                TextRow(
                    category=category,
                    source_file=source_file,
                    line=path_id,
                    field=field_path,
                    context=context,
                    object_type=type_name,
                    object_id=str(path_id),
                    text=text,
                )
            )
            extracted_by_type[type_name] += 1

    rows = sorted(
        rows,
        key=lambda row: (row.source_file, row.line, row.field, row.object_type, row.object_id, row.text),
    )
    summary = {
        "bundle": source_file,
        "objects": len(objects),
        "object_counts": dict(object_counts),
        "extracted_occurrences": len(rows),
        "extracted_unique": len({row.text for row in rows}),
        "extracted_by_type": dict(extracted_by_type),
        "errors": errors,
    }
    return [asdict(row) for row in rows], summary


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


def write_json_rows(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(list(rows), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def row_key(row: dict[str, Any]) -> tuple[str, str, str, str, str, str, str, str]:
    return tuple(str(row.get(field, "")) for field in CSV_FIELDS)  # type: ignore[return-value]


def is_decrypted_bundle_row(row: dict[str, Any]) -> bool:
    source = str(row.get("source_file", "")).replace("\\", "/").lower()
    return "/decrypted_bundles/" in f"/{source}" and source.endswith(".decrypted.full.bundle")


def write_text_dump(path: Path, rows: list[dict[str, Any]]) -> None:
    unique_by_category: dict[str, dict[str, int]] = {}
    for row in rows:
        text = clean_text(str(row.get("text", "")))
        if not has_japanese(text):
            continue
        category = str(row.get("category", "") or "japanese_text")
        unique_by_category.setdefault(category, {})
        unique_by_category[category][text] = unique_by_category[category].get(text, 0) + 1

    lines: list[str] = []
    lines.append("# Japanese Text Dump")
    lines.append("")
    lines.append(f"Generated: {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"Categories: {len(unique_by_category)}")
    lines.append(f"Unique strings: {sum(len(items) for items in unique_by_category.values())}")
    lines.append("")
    for category in sorted(unique_by_category):
        lines.append(f"## {category} ({len(unique_by_category[category])} unique)")
        for text in sorted(unique_by_category[category]):
            count = unique_by_category[category][text]
            suffix = f"  [x{count}]" if count > 1 else ""
            lines.append(f"- {text}{suffix}")
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8", newline="\n")


def write_summary(path: Path, rows: list[dict[str, Any]], bundle_summaries: list[dict[str, Any]]) -> None:
    category_counts = Counter(str(row.get("category", "") or "japanese_text") for row in rows)
    source_counts = Counter(str(row.get("source_file", "")) for row in rows)
    unique_texts = {clean_text(str(row.get("text", ""))) for row in rows if has_japanese(str(row.get("text", "")))}

    lines = [
        "Loser Life Japanese Text Extraction Summary",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        f"Occurrences: {len(rows)}",
        f"Unique strings: {len(unique_texts)}",
        "",
        "Categories:",
    ]
    lines.extend(f"- {category}: {count}" for category, count in category_counts.most_common())
    lines.extend(["", "Top sources:"])
    lines.extend(f"- {source}: {count}" for source, count in source_counts.most_common(30))
    lines.extend(["", "Decrypted bundle scan:"])
    for summary in sorted(bundle_summaries, key=lambda item: str(item.get("bundle", ""))):
        lines.append(
            f"- {summary['bundle']}: {summary['extracted_occurrences']} occurrences, "
            f"{summary['extracted_unique']} unique, {summary['objects']} objects"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract Japanese text from Loser Life decrypted Unity bundles.")
    parser.add_argument("--bundle-dir", type=Path, default=repo_root() / "BepInEx" / "plugins" / "LoserLifeATest" / "decrypted_bundles")
    parser.add_argument("--outputs-dir", type=Path, default=repo_root() / "tooling" / "outputs")
    parser.add_argument("--merge-main", action="store_true", help="Merge bundle rows into japanese_text_all_occurrences.csv.")
    parser.add_argument("--max-workers", type=int, default=max(1, min(4, os.cpu_count() or 1)))
    args = parser.parse_args()

    root = repo_root()
    bundle_paths = sorted(args.bundle_dir.glob("*.decrypted.full.bundle"))
    if not bundle_paths:
        raise FileNotFoundError(f"No *.decrypted.full.bundle files found in {args.bundle_dir}")

    all_bundle_rows: list[dict[str, Any]] = []
    bundle_summaries: list[dict[str, Any]] = []
    worker_count = max(1, min(args.max_workers, len(bundle_paths)))
    if worker_count == 1:
        for path in bundle_paths:
            rows, summary = extract_bundle(str(path), str(root))
            all_bundle_rows.extend(rows)
            bundle_summaries.append(summary)
            print(
                f"{summary['bundle']}: {summary['extracted_occurrences']} occurrences, "
                f"{summary['extracted_unique']} unique"
            )
    else:
        try:
            with ProcessPoolExecutor(max_workers=worker_count) as executor:
                futures = {executor.submit(extract_bundle, str(path), str(root)): path for path in bundle_paths}
                for future in as_completed(futures):
                    rows, summary = future.result()
                    all_bundle_rows.extend(rows)
                    bundle_summaries.append(summary)
                    print(
                        f"{summary['bundle']}: {summary['extracted_occurrences']} occurrences, "
                        f"{summary['extracted_unique']} unique"
                    )
        except PermissionError:
            print("Multiprocessing was blocked; retrying bundle scan sequentially.")
            all_bundle_rows.clear()
            bundle_summaries.clear()
            for path in bundle_paths:
                rows, summary = extract_bundle(str(path), str(root))
                all_bundle_rows.extend(rows)
                bundle_summaries.append(summary)
                print(
                    f"{summary['bundle']}: {summary['extracted_occurrences']} occurrences, "
                    f"{summary['extracted_unique']} unique"
                )

    all_bundle_rows.sort(key=lambda row: row_key(row))
    bundle_csv = args.outputs_dir / "decrypted_bundle_text_all_occurrences.csv"
    bundle_json = args.outputs_dir / "decrypted_bundle_text_all_occurrences.json"
    bundle_txt = args.outputs_dir / "decrypted_bundle_text_dump.txt"
    bundle_summary = args.outputs_dir / "decrypted_bundle_text_summary.json"

    write_csv_rows(bundle_csv, all_bundle_rows)
    write_json_rows(bundle_json, all_bundle_rows)
    write_text_dump(bundle_txt, all_bundle_rows)
    bundle_summary.write_text(json.dumps(bundle_summaries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"Bundle rows written: {len(all_bundle_rows)}")
    print(f"Bundle unique strings: {len({clean_text(str(row.get('text', ''))) for row in all_bundle_rows})}")

    if args.merge_main:
        main_csv = args.outputs_dir / "japanese_text_all_occurrences.csv"
        main_json = args.outputs_dir / "japanese_text_all_occurrences.json"
        main_txt = args.outputs_dir / "japanese_text_dump.txt"
        main_summary = args.outputs_dir / "japanese_text_summary.txt"
        if main_csv.exists():
            backup = args.outputs_dir / f"japanese_text_all_occurrences.pre_decrypted_bundles_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            shutil.copy2(main_csv, backup)
            print(f"Backed up main CSV: {backup}")
        main_rows = read_csv_rows(main_csv)
        kept_main_rows = [row for row in main_rows if not is_decrypted_bundle_row(row)]
        removed_bundle_rows = len(main_rows) - len(kept_main_rows)
        if removed_bundle_rows:
            print(f"Removed old decrypted bundle rows before merge: {removed_bundle_rows}")
        merged: dict[tuple[str, ...], dict[str, Any]] = {row_key(row): row for row in kept_main_rows}
        before = len(merged)
        for row in all_bundle_rows:
            merged[row_key(row)] = row
        merged_rows = sorted(merged.values(), key=lambda row: row_key(row))
        write_csv_rows(main_csv, merged_rows)
        write_json_rows(main_json, merged_rows)
        write_text_dump(main_txt, merged_rows)
        write_summary(main_summary, merged_rows, bundle_summaries)
        print(f"Merged main CSV rows: {len(merged_rows)} ({len(merged_rows) - before} added)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
