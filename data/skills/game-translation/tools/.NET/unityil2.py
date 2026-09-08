#!/usr/bin/env python3
"""
Extract Japanese text occurrences from a Unity IL2CPP game export.

The script keeps both occurrence-level and unique-text outputs:
  - records.jsonl: every extracted occurrence with source metadata
  - records.tsv: same records in a spreadsheet-friendly form
  - unique_text.txt: unique strings in first-seen order
  - unique_text.tsv: unique strings with counts and first source
  - summary.md: source counts and caveats
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter, OrderedDict
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, Iterator


JP_RE = re.compile(
    r"[\u3040-\u309f\u30a0-\u30ff\u3400-\u4dbf\u4e00-\u9fff"
    r"\uf900-\ufaff\u3005\u3006\u3007\u303b\u303c\uff66-\uff9f]"
)
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]+")

TEXT_EXTENSIONS = {
    ".anim",
    ".asset",
    ".bytes",
    ".cginc",
    ".controller",
    ".cs",
    ".csv",
    ".inputactions",
    ".json",
    ".mat",
    ".meta",
    ".playable",
    ".prefab",
    ".shader",
    ".txt",
    ".unity",
    ".uss",
    ".uxml",
    ".yaml",
    ".yml",
}

BINARY_SCAN_SUFFIXES = {
    ".dll",
    ".dat",
    ".exe",
    ".assets",
    ".resource",
    ".ress",
}

DEFAULT_BINARY_NAMES = {
    "GameAssembly.dll",
    "global-metadata.dat",
    "resources.assets",
    "globalgamemanagers.assets",
    "sharedassets0.assets",
    "sharedassets1.assets",
    "sharedassets2.assets",
    "level0",
    "level1",
    "level2",
}


@dataclass(frozen=True)
class Record:
    text: str
    raw: str
    source_kind: str
    source: str
    line: int | None = None
    key: str | None = None
    detail: str | None = None


def has_japanese(text: str) -> bool:
    return bool(JP_RE.search(text))


def clean_text(text: str) -> str:
    text = text.replace("\ufeff", "")
    text = text.replace("\\n", "\n").replace("\\r", "\r").replace("\\t", "\t")
    text = CONTROL_RE.sub(" ", text)
    lines = [" ".join(part.strip().split()) for part in text.splitlines()]
    return "\n".join(part for part in lines if part).strip()


def maybe_unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        if value[0] == '"':
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value[1:-1]
        return value[1:-1].replace("''", "'")
    return value


def split_yaml_like_value(line: str, parent_key: str | None = None) -> tuple[str | None, str]:
    stripped = line.strip()
    key: str | None = None
    value = stripped

    if stripped.startswith("- "):
        key = parent_key
        value = stripped[2:].strip()
    elif ":" in stripped:
        possible_key, possible_value = stripped.split(":", 1)
        if re.fullmatch(r"[-A-Za-z0-9_ .]+", possible_key):
            key = possible_key.strip()
            value = possible_value.strip()

    return key, maybe_unquote(value)


def relpath(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base)).replace("\\", "/")
    except ValueError:
        return str(path)


def iter_files(root: Path) -> Iterator[Path]:
    if not root.exists():
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in {".git", "Library", "Temp", "Obj"}]
        for filename in filenames:
            yield Path(dirpath) / filename


def extract_from_filename(path: Path, base: Path, source_kind: str) -> Iterator[Record]:
    stem = path.stem
    if has_japanese(stem):
        yield Record(
            text=clean_text(stem),
            raw=stem,
            source_kind=source_kind,
            source=relpath(path, base),
            detail="filename",
        )


def extract_from_text_file(path: Path, base: Path, source_kind: str) -> Iterator[Record]:
    try:
        with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
            yaml_parent_stack: list[tuple[int, str]] = []
            for line_no, line in enumerate(handle, start=1):
                indent = len(line) - len(line.lstrip(" "))
                stripped = line.strip()
                if stripped.startswith("- "):
                    while yaml_parent_stack and yaml_parent_stack[-1][0] > indent:
                        yaml_parent_stack.pop()
                else:
                    while yaml_parent_stack and yaml_parent_stack[-1][0] >= indent:
                        yaml_parent_stack.pop()
                parent_key = yaml_parent_stack[-1][1] if yaml_parent_stack else None
                if stripped.endswith(":") and not stripped.startswith("- "):
                    possible_key = stripped[:-1].strip()
                    if re.fullmatch(r"[-A-Za-z0-9_ .]+", possible_key):
                        yaml_parent_stack.append((indent, possible_key))
                if not has_japanese(line):
                    continue
                key, value = split_yaml_like_value(line, parent_key=parent_key)
                cleaned = clean_text(value)
                if not cleaned or not has_japanese(cleaned):
                    continue
                yield Record(
                    text=cleaned,
                    raw=line.rstrip("\n\r"),
                    source_kind=source_kind,
                    source=relpath(path, base),
                    line=line_no,
                    key=key,
                )
    except (OSError, UnicodeError) as exc:
        print(f"[warn] Could not read text file {path}: {exc}", file=sys.stderr)


def iter_csharp_string_literals(line: str) -> Iterator[str]:
    index = 0
    while index < len(line):
        quote_index = line.find('"', index)
        if quote_index < 0:
            break
        is_verbatim = quote_index > 0 and line[quote_index - 1] == "@"
        index = quote_index + 1
        chars: list[str] = []
        while index < len(line):
            char = line[index]
            if char == '"':
                if is_verbatim and index + 1 < len(line) and line[index + 1] == '"':
                    chars.append('"')
                    index += 2
                    continue
                index += 1
                break
            if not is_verbatim and char == "\\" and index + 1 < len(line):
                escape = line[index + 1]
                chars.append(
                    {
                        "n": "\n",
                        "r": "\r",
                        "t": "\t",
                        '"': '"',
                        "\\": "\\",
                    }.get(escape, escape)
                )
                index += 2
                continue
            chars.append(char)
            index += 1
        yield "".join(chars)


def extract_from_dump_cs(path: Path, base: Path) -> Iterator[Record]:
    try:
        with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
            for line_no, line in enumerate(handle, start=1):
                if not has_japanese(line):
                    continue
                yielded = False
                for literal in iter_csharp_string_literals(line):
                    cleaned = clean_text(literal)
                    if cleaned and has_japanese(cleaned):
                        yielded = True
                        yield Record(
                            text=cleaned,
                            raw=line.rstrip("\n\r"),
                            source_kind="il2cpp_dump",
                            source=relpath(path, base),
                            line=line_no,
                            key="csharp_string",
                        )
                if yielded:
                    continue
                cleaned = clean_text(line.strip(" /\t\r\n"))
                if cleaned and has_japanese(cleaned):
                    yield Record(
                        text=cleaned,
                        raw=line.rstrip("\n\r"),
                        source_kind="il2cpp_dump",
                        source=relpath(path, base),
                        line=line_no,
                    )
    except (OSError, UnicodeError) as exc:
        print(f"[warn] Could not read dump.cs {path}: {exc}", file=sys.stderr)


def extract_from_json_strings(path: Path, base: Path, source_kind: str) -> Iterator[Record]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[warn] Could not parse JSON {path}: {exc}", file=sys.stderr)
        return

    def walk(value: object, pointer: str) -> Iterator[tuple[str, str]]:
        if isinstance(value, str):
            yield pointer, value
        elif isinstance(value, list):
            for index, item in enumerate(value):
                yield from walk(item, f"{pointer}/{index}")
        elif isinstance(value, dict):
            for key, item in value.items():
                yield from walk(item, f"{pointer}/{key}")

    for pointer, value in walk(data, ""):
        cleaned = clean_text(value)
        if cleaned and has_japanese(cleaned):
            yield Record(
                text=cleaned,
                raw=value,
                source_kind=source_kind,
                source=relpath(path, base),
                key=pointer or "/",
            )


def is_plausible_binary_text(text: str) -> bool:
    if not text or len(text) > 500 or not has_japanese(text):
        return False
    if len(text) == 1 and not re.search(r"[\u3040-\u30ff]", text):
        return False
    printable = sum(1 for char in text if char.isprintable() or char in "\r\n\t")
    if printable / max(len(text), 1) < 0.95:
        return False
    # Single stray CJK codepoints are common false positives in raw binary scans.
    japanese_count = len(JP_RE.findall(text))
    return japanese_count >= 2 or bool(re.search(r"[\u3040-\u30ff]", text))


def decode_null_terminated_runs(data: bytes, encoding: str) -> Iterable[str]:
    for segment in data.split(b"\x00"):
        if not 2 <= len(segment) <= 2000:
            continue
        try:
            value = segment.decode(encoding)
        except UnicodeDecodeError:
            continue
        value = clean_text(value)
        if is_plausible_binary_text(value):
            yield value


def decode_utf16le_runs(data: bytes) -> Iterable[str]:
    for alignment in (0, 1):
        chars: list[str] = []
        index = alignment
        while index + 1 < len(data):
            code_unit = data[index] | (data[index + 1] << 8)
            index += 2
            if code_unit == 0:
                value = clean_text("".join(chars))
                if is_plausible_binary_text(value):
                    yield value
                chars = []
                continue
            if code_unit < 0x20 or 0xD800 <= code_unit <= 0xDFFF or code_unit > 0xFFFD:
                chars = []
                continue
            chars.append(chr(code_unit))
            if len(chars) > 500:
                chars = []


def extract_from_binary_file(
    path: Path,
    base: Path,
    source_kind: str,
    include_extra_encodings: bool = False,
) -> Iterator[Record]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        print(f"[warn] Could not read binary file {path}: {exc}", file=sys.stderr)
        return

    seen: set[tuple[str, str]] = set()
    encodings = ("utf-8", "cp932") if include_extra_encodings else ("utf-8",)
    for encoding in encodings:
        for value in decode_null_terminated_runs(data, encoding):
            if len(value) == 1 and not re.search(r"[\u3040-\u30ff]", value):
                continue
            key = (encoding, value)
            if key in seen:
                continue
            seen.add(key)
            yield Record(
                text=value,
                raw=value,
                source_kind=source_kind,
                source=relpath(path, base),
                detail=f"binary-{encoding}",
            )
    if include_extra_encodings:
        for value in decode_utf16le_runs(data):
            key = ("utf-16le", value)
            if key in seen:
                continue
            seen.add(key)
            yield Record(
                text=value,
                raw=value,
                source_kind=source_kind,
                source=relpath(path, base),
                detail="binary-utf-16le",
            )


def extract_stringliteral_json(path: Path, base: Path) -> Iterator[Record]:
    try:
        entries = json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[warn] Could not parse stringliteral JSON {path}: {exc}", file=sys.stderr)
        return

    if not isinstance(entries, list):
        return
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        value = clean_text(str(entry.get("value", "")))
        if value and len(value) <= 500 and has_japanese(value):
            address = str(entry.get("address", ""))
            yield Record(
                text=value,
                raw=str(entry.get("value", "")),
                source_kind="il2cpp_stringliteral",
                source=relpath(path, base),
                key=f"/{index}",
                detail=address,
            )


def should_binary_scan(path: Path, include_large_unity: bool, scan_all_binaries: bool) -> bool:
    if path.name in {"GameAssembly.dll", "global-metadata.dat"}:
        return True
    if include_large_unity and path.name in DEFAULT_BINARY_NAMES:
        return True
    if scan_all_binaries and path.suffix.lower() in BINARY_SCAN_SUFFIXES:
        return True
    return False


def collect_records(args: argparse.Namespace) -> list[Record]:
    records: list[Record] = []

    roots: list[tuple[Path, str]] = []
    if args.exported_project:
        roots.append((args.exported_project, "asset_export"))
    if args.auxiliary_files:
        roots.append((args.auxiliary_files, "assetripper_auxiliary"))

    for root, source_kind in roots:
        for path in iter_files(root):
            records.extend(extract_from_filename(path, root, source_kind))
            if path.suffix.lower() in TEXT_EXTENSIONS:
                records.extend(extract_from_text_file(path, root, source_kind))

    if args.il2cpp_dump_dir and args.il2cpp_dump_dir.exists():
        dump_cs = args.il2cpp_dump_dir / "dump.cs"
        if dump_cs.exists():
            records.extend(extract_from_dump_cs(dump_cs, args.il2cpp_dump_dir))
        stringliteral_json = args.il2cpp_dump_dir / "stringliteral.json"
        if stringliteral_json.exists():
            records.extend(extract_stringliteral_json(stringliteral_json, args.il2cpp_dump_dir))

    if args.game_dir and args.game_dir.exists():
        for path in iter_files(args.game_dir):
            records.extend(extract_from_filename(path, args.game_dir, "game_filename"))
            if should_binary_scan(path, args.scan_large_unity_binaries, args.scan_all_binaries):
                records.extend(
                    extract_from_binary_file(
                        path,
                        args.game_dir,
                        "game_binary_scan",
                        include_extra_encodings=args.scan_extra_binary_encodings,
                    )
                )
            elif path.suffix.lower() in {".json", ".txt", ".info", ".config"}:
                records.extend(extract_from_text_file(path, args.game_dir, "game_text"))

    return records


def write_outputs(records: list[Record], output_dir: Path, args: argparse.Namespace) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    jsonl_path = output_dir / "records.jsonl"
    with jsonl_path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")

    tsv_path = output_dir / "records.tsv"
    with tsv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["text", "source_kind", "source", "line", "key", "detail", "raw"],
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        for record in records:
            writer.writerow(asdict(record))

    unique: OrderedDict[str, dict[str, object]] = OrderedDict()
    for record in records:
        entry = unique.setdefault(
            record.text,
            {
                "count": 0,
                "first_source_kind": record.source_kind,
                "first_source": record.source,
                "first_line": record.line,
                "first_key": record.key,
            },
        )
        entry["count"] = int(entry["count"]) + 1

    unique_txt_path = output_dir / "unique_text.txt"
    with unique_txt_path.open("w", encoding="utf-8-sig", newline="\n") as handle:
        for text in unique:
            handle.write(text.replace("\n", "\\n") + "\n")

    unique_tsv_path = output_dir / "unique_text.tsv"
    with unique_tsv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "text",
                "count",
                "first_source_kind",
                "first_source",
                "first_line",
                "first_key",
            ],
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        for text, entry in unique.items():
            writer.writerow({"text": text.replace("\n", "\\n"), **entry})

    categories = {
        "dialogue_text.tsv": [],
        "ui_general_text.tsv": [],
        "runtime_il2cpp_text.tsv": [],
        "asset_name_text.tsv": [],
        "other_text.tsv": [],
    }
    for record in records:
        filename = category_filename(record)
        categories[filename].append(record)

    for filename, category_records in categories.items():
        with (output_dir / filename).open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["text", "source_kind", "source", "line", "key", "detail", "raw"],
                delimiter="\t",
                lineterminator="\n",
            )
            writer.writeheader()
            for record in category_records:
                writer.writerow(asdict(record))

    source_counts = Counter(record.source_kind for record in records)
    category_counts = {filename: len(category_records) for filename, category_records in categories.items()}
    summary_path = output_dir / "summary.md"
    with summary_path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("# Japanese Text Extraction Summary\n\n")
        handle.write(f"- Total occurrence records: {len(records)}\n")
        handle.write(f"- Unique text entries: {len(unique)}\n")
        handle.write(f"- Exported project: `{args.exported_project}`\n")
        handle.write(f"- Game directory: `{args.game_dir}`\n")
        handle.write(f"- IL2CPP dump directory: `{args.il2cpp_dump_dir}`\n")
        handle.write(f"- Large Unity binary scan: `{args.scan_large_unity_binaries}`\n")
        handle.write(f"- All binary scan: `{args.scan_all_binaries}`\n")
        handle.write(f"- Extra binary encodings: `{args.scan_extra_binary_encodings}`\n\n")
        handle.write("## Records By Source Kind\n\n")
        for source_kind, count in source_counts.most_common():
            handle.write(f"- `{source_kind}`: {count}\n")
        handle.write("\n## Records By Category File\n\n")
        for filename, count in category_counts.items():
            handle.write(f"- `{filename}`: {count}\n")
        handle.write("\n## Output Files\n\n")
        handle.write("- `records.jsonl`: every occurrence with source metadata.\n")
        handle.write("- `records.tsv`: spreadsheet-friendly occurrence table.\n")
        handle.write("- `unique_text.txt`: unique strings in first-seen order.\n")
        handle.write("- `unique_text.tsv`: unique strings with occurrence counts and first source.\n")
        handle.write("- `dialogue_text.tsv`: likely dialogue/reaction lines from personality text arrays.\n")
        handle.write("- `ui_general_text.tsv`: visible UI labels and general display strings.\n")
        handle.write("- `runtime_il2cpp_text.tsv`: IL2CPP dump/string literal/binary scan hits.\n")
        handle.write("- `asset_name_text.tsv`: Japanese filenames/object/animation/material/mesh names.\n")
        handle.write("- `other_text.tsv`: remaining extracted text records.\n")
        handle.write("\n## Notes\n\n")
        handle.write(
            "- IL2CPP managed literals are taken from `stringliteral.json` when present, "
            "and `dump.cs` is scanned for Japanese metadata strings such as headers/tooltips.\n"
        )
        handle.write(
            "- Binary scanning is heuristic. Treat binary-only hits as leads to verify, "
            "while AssetRipper YAML/TextAsset hits are the primary extracted text.\n"
        )


def category_filename(record: Record) -> str:
    if record.source_kind in {"il2cpp_dump", "il2cpp_stringliteral", "game_binary_scan"}:
        return "runtime_il2cpp_text.tsv"

    key = (record.key or "").lower()
    source = record.source.lower()

    dialogue_markers = (
        "dialogue",
        "texts",
        "moaning",
        "vagina",
        "anal",
        "boob",
        "hip",
        "sex",
    )
    if any(marker in key for marker in dialogue_markers) or "personality_" in source:
        return "dialogue_text.tsv"

    if record.key in {
        "m_text",
        "buttonText",
        "displayName",
        "personalityName",
        "conciergeName",
        "characterName",
        "voiceName",
    }:
        return "ui_general_text.tsv"

    if record.detail == "filename" or record.key in {"m_Name", "attribute", "path"}:
        return "asset_name_text.tsv"

    return "other_text.tsv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--exported-project",
        type=Path,
        default=Path("AssetRipper_export_20260515_005738/ExportedProject"),
    )
    parser.add_argument(
        "--auxiliary-files",
        type=Path,
        default=Path("AssetRipper_export_20260515_005738/AuxiliaryFiles"),
    )
    parser.add_argument("--game-dir", type=Path, default=Path("Club"))
    parser.add_argument(
        "--il2cpp-dump-dir",
        type=Path,
        default=Path(r"C:\Users\sw\Desktop\Tools\.NET\Il2CppDumper-win-v6.7.46"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("ExtractedJapaneseText"),
    )
    parser.add_argument(
        "--scan-large-unity-binaries",
        action="store_true",
        help="Also scan raw Unity .assets/.resS/.resource/level files. Slower and noisier.",
    )
    parser.add_argument(
        "--scan-all-binaries",
        action="store_true",
        help="Scan every DLL/EXE/DAT/resource-like file, not just IL2CPP metadata targets.",
    )
    parser.add_argument(
        "--scan-extra-binary-encodings",
        action="store_true",
        help="Also try CP932 and UTF-16LE binary string scans. Useful as a lead finder, noisy by nature.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    records = collect_records(args)
    write_outputs(records, args.output_dir, args)
    unique_count = len({record.text for record in records})
    print(f"Wrote {len(records)} occurrence records and {unique_count} unique entries to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
