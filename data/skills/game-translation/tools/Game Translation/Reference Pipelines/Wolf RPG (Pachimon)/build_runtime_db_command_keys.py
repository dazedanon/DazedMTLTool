#!/usr/bin/env python3
import argparse
import csv
import json
import shutil
from collections import OrderedDict
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = (SCRIPT_DIR / ".." / "..").resolve()
DEFAULT_EXPORT_DIR = ROOT_DIR / "TextExport"
DEFAULT_OUTPUT = SCRIPT_DIR / "runtime_command_keys.jsonl"
DEFAULT_PROTECTED = SCRIPT_DIR / "protected_runtime_identifiers.jsonl"


def read_csv(path):
    with Path(path).open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def append_unique_jsonl(path, rows):
    path = Path(path)
    existing_lines = []
    existing_keys = set()
    if path.exists():
        existing_lines = path.read_text(encoding="utf-8-sig").splitlines()
        for line in existing_lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = (
                str(item.get("reason", "")),
                str(item.get("file", "")),
                str(item.get("id", "")),
                str(item.get("offset_hex", item.get("offset", ""))),
                str(item.get("source_text", item.get("text", ""))),
            )
            existing_keys.add(key)

    to_add = []
    for row in rows:
        key = (
            str(row.get("reason", "")),
            str(row.get("file", "")),
            str(row.get("id", "")),
            str(row.get("offset_hex", row.get("offset", ""))),
            str(row.get("source_text", row.get("text", ""))),
        )
        if key in existing_keys:
            continue
        existing_keys.add(key)
        to_add.append(row)

    if not to_add:
        return 0
    backup = path.with_suffix(path.suffix + ".bak")
    if path.exists():
        shutil.copy2(path, backup)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        if existing_lines and existing_lines[-1].strip():
            f.write("\n")
        for row in to_add:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    return len(to_add)


def normalize_file(value):
    return str(value or "").replace("\\", "/")


def runtime_key_reason(command_id, string_index):
    if command_id == "122" and string_index == "0":
        return "wolf_string_variable_runtime_value"
    if command_id in {"212", "213"} and string_index == "0":
        return "wolf_string_condition_runtime_key"
    if command_id == "250" and string_index in {"1", "3"}:
        return "wolf_db_operation_lookup_key"
    if command_id == "300" and string_index == "0":
        return "wolf_common_event_call_key"
    return ""


def build_rows(strings_csv, command_strings_csv):
    strings = read_csv(strings_csv)
    commands = read_csv(command_strings_csv)
    strings_by_slot = {}
    for row in strings:
        key = (normalize_file(row.get("file", "")), str(row.get("offset_hex", "")).lower())
        strings_by_slot[key] = row

    out = []
    seen = set()
    for command in commands:
        command_id = str(command.get("command_id", ""))
        string_index = str(command.get("string_index", ""))
        reason = runtime_key_reason(command_id, string_index)
        if not reason:
            continue
        text = str(command.get("text", ""))
        if not text:
            continue
        file_key = normalize_file(command.get("file", ""))
        offset_hex = str(command.get("string_offset_hex", "")).lower()
        source_row = strings_by_slot.get((file_key, offset_hex))
        if not source_row:
            continue
        row_id = str(source_row.get("id", ""))
        key = (file_key, offset_hex, row_id, text)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            OrderedDict(
                [
                    ("file", file_key),
                    ("id", row_id),
                    ("offset_hex", offset_hex),
                    ("source_text", text),
                    ("match", "id_or_offset"),
                    ("reason", reason),
                    ("command_id", command_id),
                    ("string_index", string_index),
                    ("command_offset_hex", str(command.get("command_offset_hex", ""))),
                ]
            )
        )
    return out


def parse_args():
    parser = argparse.ArgumentParser(description="Build exact protected rows for WOLF runtime command lookup keys.")
    parser.add_argument("--export-dir", default=str(DEFAULT_EXPORT_DIR))
    parser.add_argument("--strings-csv", default="")
    parser.add_argument("--command-strings-csv", default="")
    parser.add_argument("--output-jsonl", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--append-to-protected", action="store_true")
    parser.add_argument("--protected-identifiers-path", default=str(DEFAULT_PROTECTED))
    return parser.parse_args()


def main():
    args = parse_args()
    export_dir = Path(args.export_dir)
    strings_csv = Path(args.strings_csv) if args.strings_csv else export_dir / "strings_all.csv"
    command_strings_csv = Path(args.command_strings_csv) if args.command_strings_csv else export_dir / "command_strings.csv"
    rows = build_rows(strings_csv, command_strings_csv)
    write_jsonl(args.output_jsonl, rows)
    print(f"runtime command key rows: {len(rows)}")
    print(f"wrote: {args.output_jsonl}")
    if args.append_to_protected:
        added = append_unique_jsonl(args.protected_identifiers_path, rows)
        print(f"appended to protected identifiers: {added}")


if __name__ == "__main__":
    main()
