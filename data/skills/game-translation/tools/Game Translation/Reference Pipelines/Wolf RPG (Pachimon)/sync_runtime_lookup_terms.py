#!/usr/bin/env python3
import argparse
import csv
import json
import re
import shutil
from collections import Counter, OrderedDict, defaultdict
from datetime import datetime, timezone
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = (SCRIPT_DIR / ".." / "..").resolve()
DEFAULT_SOURCE_CSV = ROOT_DIR / "TextExport" / "strings_all.csv"
DEFAULT_TRANSLATIONS = ROOT_DIR / "TextExport" / "mistral_fullgame_translations.jsonl"
DEFAULT_SYNCED_OUTPUT = ROOT_DIR / "TextExport" / "mistral_fullgame_translations.synced.jsonl"
DEFAULT_PATCH_OUTPUT = ROOT_DIR / "TextExport" / "runtime_lookup_consistency_patch.jsonl"
DEFAULT_PROTECTED_IDENTIFIERS = SCRIPT_DIR / "protected_runtime_identifiers.jsonl"
DEFAULT_RUNTIME_LOOKUP_LOCKS = SCRIPT_DIR / "runtime_lookup_locks.jsonl"

DATABASE_DATA_FILES = {
    "BasicData/CDataBase.dat",
    "BasicData/DataBase.dat",
    "BasicData/SysDatabase.dat",
}
PROJECT_SCHEMA_SUFFIXES = {
    "CDataBase.project",
    "DataBase.project",
    "SysDatabase.project",
}
PLACEHOLDER_RE = re.compile(r"\{CTRL\d+\}")
RAW_WOLF_RE = re.compile(r"\\(?:[A-Za-z_][A-Za-z0-9_]*\[[^\]]*\]|[.!><^{}\\])")
ASSET_PATH_RE = re.compile(r"[A-Za-z0-9_./\\-]+\.(?:png|jpg|jpeg|bmp|webp|ogg|wav|mps|dat|ttf|txt|json|wolf)$", re.I)
JAPANESE_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]")
MOJIBAKE_MARKERS = ("\u00e3", "\u00e4", "\u00e5", "\u00e6", "\u00e7", "\u00ef\u00bc", "\u00ef\u00bd")


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def convert_export_text(value):
    if value is None:
        return ""
    s = str(value)
    out = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt == "\\":
                out.append("\\")
                i += 2
                continue
            if nxt == "r":
                out.append("\r")
                i += 2
                continue
            if nxt == "n":
                out.append("\n")
                i += 2
                continue
            if nxt == "t":
                out.append("\t")
                i += 2
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def normalize_file_key(value):
    key = str(value or "").replace("\\", "/").strip()
    if key in PROJECT_SCHEMA_SUFFIXES:
        return "BasicData/" + key
    return key


def has_japanese(text):
    return bool(JAPANESE_RE.search(text or ""))


def looks_like_mojibake(text):
    value = str(text or "")
    return any(marker in value for marker in MOJIBAKE_MARKERS)


def is_runtime_file(file_name):
    key = normalize_file_key(file_name)
    return key == "BasicData/CommonEvent.dat" or key.startswith("MapData/")


def is_database_data_file(file_name):
    return normalize_file_key(file_name) in DATABASE_DATA_FILES


def source_text_from_row(row):
    return convert_export_text(row.get("text", ""))


def context_from_row(row):
    return f"offset:{row.get('offset_hex', '')}"


def source_key(row):
    return (normalize_file_key(row.get("file", "")), str(row.get("offset_hex", "")))


def read_csv_rows(path):
    with Path(path).open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def iter_jsonl(path):
    path = Path(path)
    if not path.exists():
        return
    with path.open("r", encoding="utf-8-sig") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"bad JSONL at {path}:{line_no}: {exc}") from exc


def write_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    if path.exists():
        backup = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, backup)
    tmp.replace(path)


def load_project_schema_sources(path):
    sources = set()
    if not path:
        return sources
    path = Path(path)
    if not path.exists():
        return sources
    for item in iter_jsonl(path):
        if item.get("reason") != "database_project_schema_identifier":
            continue
        file_key = normalize_file_key(item.get("file", ""))
        if not any(file_key.endswith(suffix) for suffix in PROJECT_SCHEMA_SUFFIXES):
            continue
        text = convert_export_text(item.get("source_text", item.get("text", ""))).strip()
        if text and has_japanese(text):
            sources.add(text)
    return sources


def load_exact_protected_rows(path):
    protected = {
        "by_file_id": set(),
        "by_file_offset": set(),
    }
    if not path:
        return protected
    path = Path(path)
    if not path.exists():
        return protected
    for item in iter_jsonl(path):
        match_mode = str(item.get("match", "")).strip().lower()
        reason = str(item.get("reason", "")).strip().lower()
        exact_reason = any(
            marker in reason
            for marker in (
                "db_operation_lookup_key",
                "common_event_call_key",
                "runtime_command",
                "runtime_value",
                "runtime_key",
                "string_variable",
                "string_condition",
                "lookup_key",
            )
        )
        if match_mode not in {"id", "offset", "id_or_offset"} and not exact_reason:
            continue
        file_value = item.get("file", "")
        row_id = str(item.get("id", "")).strip()
        offset_hex = str(item.get("offset_hex", item.get("offset", ""))).strip().lower()
        for file_key in protected_file_keys(file_value):
            if row_id:
                protected["by_file_id"].add((file_key, row_id))
            if offset_hex:
                protected["by_file_offset"].add((file_key, offset_hex))
    return protected


def protected_file_keys(value):
    key = normalize_file_key(value)
    keys = {key}
    if key.startswith("BasicData/") and key.endswith(".project"):
        keys.add(key.split("/", 1)[1])
    return keys


def exact_protected_row(row, protected):
    if not protected:
        return False
    row_id = str(row.get("id", "")).strip()
    offset_hex = str(row.get("offset_hex", "")).strip().lower()
    for file_key in protected_file_keys(row.get("file", "")):
        if row_id and (file_key, row_id) in protected.get("by_file_id", set()):
            return True
        if offset_hex and (file_key, offset_hex) in protected.get("by_file_offset", set()):
            return True
    return False


def load_runtime_lookup_locks(path):
    locks = []
    if not path:
        return locks
    path = Path(path)
    if not path.exists():
        return locks
    for item in iter_jsonl(path):
        source = convert_export_text(item.get("source_text", item.get("text", ""))).strip()
        if not source:
            continue
        locks.append(
            {
                "source": source,
                "file": normalize_file_key(item.get("file", "")),
                "file_prefix": normalize_file_key(item.get("file_prefix", "")),
                "reason": str(item.get("reason", "runtime lookup lock")),
            }
        )
    return locks


def locked_runtime_source(source, file_name, runtime_locks):
    source = str(source or "").strip()
    file_key = normalize_file_key(file_name)
    for lock in runtime_locks or []:
        if source != lock["source"]:
            continue
        if lock["file"] and file_key == lock["file"]:
            return lock["reason"]
        if lock["file_prefix"] and file_key.startswith(lock["file_prefix"]):
            return lock["reason"]
        if not lock["file"] and not lock["file_prefix"]:
            return lock["reason"]
    return ""


def is_identifierish(text, max_len=80):
    value = str(text or "").strip()
    if not value:
        return False
    if "\n" in value or "\r" in value:
        return False
    if len(value) > max_len:
        return False
    if PLACEHOLDER_RE.search(value) or RAW_WOLF_RE.search(value):
        return False
    if ASSET_PATH_RE.search(value):
        return False
    return True


def is_db_name_candidate(source, target):
    source = str(source or "").strip()
    target = str(target or "").strip()
    if not source or not target or source == target:
        return False
    if len(source) < 2:
        return False
    if not is_identifierish(source) or not is_identifierish(target, max_len=120):
        return False
    if not has_japanese(source):
        return False
    if has_japanese(target) or looks_like_mojibake(target):
        return False
    if not re.search(r"[A-Za-z0-9]", target):
        return False
    return True


def build_db_name_map(translations, source_rows_by_id, source_rows=None, canonical_rows=None):
    candidates = defaultdict(Counter)
    for item in translations:
        row = source_rows_by_id.get(str(item.get("id", "")))
        file_value = row.get("file", "") if row else item.get("file", "")
        if not is_database_data_file(file_value):
            continue
        source = str(item.get("source_template") or (source_text_from_row(row) if row else "")).strip()
        target = str(item.get("translation_template") or "").strip()
        if is_db_name_candidate(source, target):
            candidates[source][target] += 1

    if source_rows and canonical_rows:
        source_by_file = defaultdict(list)
        canonical_by_file = defaultdict(list)
        for row in source_rows:
            if is_database_data_file(row.get("file", "")):
                source_by_file[normalize_file_key(row.get("file", ""))].append(row)
        for row in canonical_rows:
            if is_database_data_file(row.get("file", "")):
                canonical_by_file[normalize_file_key(row.get("file", ""))].append(row)
        for file_key, rows in source_by_file.items():
            translated_rows = canonical_by_file.get(file_key, [])
            for source_row, translated_row in zip(rows, translated_rows):
                source = source_text_from_row(source_row).strip()
                target = source_text_from_row(translated_row).strip()
                if is_db_name_candidate(source, target):
                    candidates[source][target] += 100

    mapping = {}
    conflicts = {}
    for source, counts in candidates.items():
        target, _count = counts.most_common(1)[0]
        mapping[source] = target
        if len(counts) > 1:
            conflicts[source] = dict(counts)
    return mapping, conflicts


def expected_for_source(source, db_name_map, schema_sources, file_name="", runtime_locks=None):
    source = str(source or "").strip()
    file_key = normalize_file_key(file_name)
    if not source:
        return None, ""
    lock_reason = locked_runtime_source(source, file_key, runtime_locks)
    if lock_reason:
        return source, lock_reason
    if file_key == "BasicData/CommonEvent.dat" and source in schema_sources and is_identifierish(source):
        return source, "preserve WOLF database schema/runtime lookup identifier"
    if source in db_name_map:
        return db_name_map[source], "sync DataBase.dat data-name reference to canonical translated DB name"
    if source in schema_sources and is_identifierish(source):
        return source, "preserve WOLF database schema/runtime lookup identifier"
    return None, ""


def make_output_entry(row, expected, note, prefix, index):
    return OrderedDict(
        [
            ("id", f"{prefix}-{index}"),
            ("file", normalize_file_key(row.get("file", ""))),
            ("source", "string"),
            ("context", context_from_row(row)),
            ("event", OrderedDict([("id", ""), ("name", ""), ("page", "")])),
            ("speaker", ""),
            ("speaker_translation", ""),
            ("source_template", source_text_from_row(row)),
            ("translation_template", expected),
            ("tokens", {}),
            ("model", "runtime-lookup-sync"),
            ("batch_id", prefix),
            ("translated_at_utc", utc_now()),
            ("usage", {}),
            ("note", note),
        ]
    )


def sync_translation_jsonl(args):
    source_rows = read_csv_rows(args.source_csv)
    source_rows_by_id = {str(row.get("id", "")): row for row in source_rows}
    translations = list(iter_jsonl(args.translation_jsonl))
    schema_sources = load_project_schema_sources(args.protected_identifiers_path)
    exact_protected = load_exact_protected_rows(args.protected_identifiers_path)
    runtime_locks = load_runtime_lookup_locks(args.runtime_lookup_locks_path)
    canonical_rows = read_csv_rows(args.canonical_csv) if args.canonical_csv else None
    db_name_map, conflicts = build_db_name_map(translations, source_rows_by_id, source_rows, canonical_rows)

    synced = []
    seen_ids = set()
    changed = 0
    schema_preserved = 0
    db_synced = 0

    for item in translations:
        row_id = str(item.get("id", ""))
        seen_ids.add(row_id)
        row = source_rows_by_id.get(row_id)
        file_value = row.get("file", "") if row else item.get("file", "")
        if is_runtime_file(file_value):
            source = str(item.get("source_template") or (source_text_from_row(row) if row else "")).strip()
            if row and exact_protected_row(row, exact_protected):
                expected, note = source, "preserve WOLF runtime command lookup key"
            else:
                expected, note = expected_for_source(source, db_name_map, schema_sources, file_value, runtime_locks)
            if expected is not None and str(item.get("translation_template", "")).strip() != expected:
                item = OrderedDict(item)
                item["translation_template"] = expected
                item["speaker_translation"] = ""
                item["runtime_lookup_consistency"] = note
                changed += 1
                if "DataBase.dat" in note:
                    db_synced += 1
                else:
                    schema_preserved += 1
        synced.append(item)

    added = 0
    for row in source_rows:
        row_id = str(row.get("id", ""))
        file_key = normalize_file_key(row.get("file", ""))
        if row_id in seen_ids or not is_runtime_file(file_key):
            continue
        if exact_protected_row(row, exact_protected):
            expected, note = source_text_from_row(row), "preserve WOLF runtime command lookup key"
        else:
            expected, note = expected_for_source(source_text_from_row(row), db_name_map, schema_sources, file_key, runtime_locks)
        if expected is None:
            continue
        added += 1
        if "DataBase.dat" in note:
            db_synced += 1
        else:
            schema_preserved += 1
        synced.append(make_output_entry(row, expected, note, "runtime-lookup-sync", added))

    write_jsonl(args.output_jsonl, synced)
    print(f"source rows: {len(source_rows)}")
    print(f"input translations: {len(translations)}")
    print(f"canonical DB data-name terms: {len(db_name_map)}")
    print(f"project schema protected terms: {len(schema_sources)}")
    print(f"changed existing rows: {changed}")
    print(f"added missing rows: {added}")
    print(f"DB-name refs synced: {db_synced}")
    print(f"schema refs preserved: {schema_preserved}")
    if conflicts:
        print(f"warning: DB canonical conflicts resolved by most common target: {len(conflicts)}")
    print(f"wrote: {args.output_jsonl}")


def make_current_patch(args):
    source_rows = read_csv_rows(args.source_csv)
    current_rows = read_csv_rows(args.current_csv)
    source_rows_by_id = {str(row.get("id", "")): row for row in source_rows}
    translations = list(iter_jsonl(args.translation_jsonl))
    schema_sources = load_project_schema_sources(args.protected_identifiers_path)
    exact_protected = load_exact_protected_rows(args.protected_identifiers_path)
    runtime_locks = load_runtime_lookup_locks(args.runtime_lookup_locks_path)
    canonical_rows = read_csv_rows(args.canonical_csv) if args.canonical_csv else current_rows
    db_name_map, conflicts = build_db_name_map(translations, source_rows_by_id, source_rows, canonical_rows)

    source_counts = Counter(normalize_file_key(row.get("file", "")) for row in source_rows)
    current_counts = Counter(normalize_file_key(row.get("file", "")) for row in current_rows)
    current_by_occurrence = {}
    current_seen = Counter()
    for row in current_rows:
        file_key = normalize_file_key(row.get("file", ""))
        index = current_seen[file_key]
        current_seen[file_key] += 1
        current_by_occurrence[(file_key, index)] = row

    patch_rows = []
    schema_patches = 0
    db_patches = 0
    source_seen = Counter()
    skipped_mismatch_files = set()
    for row in source_rows:
        file_key = normalize_file_key(row.get("file", ""))
        index = source_seen[file_key]
        source_seen[file_key] += 1
        if not is_runtime_file(file_key):
            continue
        if source_counts[file_key] != current_counts[file_key]:
            skipped_mismatch_files.add(file_key)
            continue
        if exact_protected_row(row, exact_protected):
            expected, note = source_text_from_row(row), "preserve WOLF runtime command lookup key"
        else:
            expected, note = expected_for_source(source_text_from_row(row), db_name_map, schema_sources, file_key, runtime_locks)
        if expected is None:
            continue
        current = current_by_occurrence.get((file_key, index))
        if not current:
            continue
        current_text = source_text_from_row(current)
        if current_text == expected:
            continue
        patch = make_output_entry(current, expected, note, "runtime-lookup-current-patch", len(patch_rows) + 1)
        patch["source_template"] = current_text
        patch_rows.append(patch)
        if "DataBase.dat" in note:
            db_patches += 1
        else:
            schema_patches += 1

    write_jsonl(args.output_jsonl, patch_rows)
    print(f"source rows: {len(source_rows)}")
    print(f"current rows: {len(current_rows)}")
    print(f"canonical DB data-name terms: {len(db_name_map)}")
    print(f"project schema protected terms: {len(schema_sources)}")
    print(f"patch rows: {len(patch_rows)}")
    print(f"DB-name patches: {db_patches}")
    print(f"schema patches: {schema_patches}")
    if skipped_mismatch_files:
        print(f"skipped runtime files with changed string counts: {len(skipped_mismatch_files)}")
    if conflicts:
        print(f"warning: DB canonical conflicts resolved by most common target: {len(conflicts)}")
    print(f"wrote: {args.output_jsonl}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Sync translated WOLF DB data names with runtime lookup references, while preserving executable command/schema identifiers."
    )
    parser.add_argument("--mode", choices=["sync-jsonl", "patch-current"], default="sync-jsonl")
    parser.add_argument("--source-csv", default=str(DEFAULT_SOURCE_CSV), help="Original extraction strings_all.csv.")
    parser.add_argument("--translation-jsonl", default=str(DEFAULT_TRANSLATIONS), help="AI translation JSONL used to build canonical DB data-name translations.")
    parser.add_argument("--canonical-csv", default="", help="Optional translated/current strings_all.csv used to learn canonical DB data names by DB row order.")
    parser.add_argument("--current-csv", default="", help="Current translated extraction strings_all.csv, required for --mode patch-current.")
    parser.add_argument("--output-jsonl", default="", help="Output JSONL. Defaults depend on mode.")
    parser.add_argument("--protected-identifiers-path", default=str(DEFAULT_PROTECTED_IDENTIFIERS))
    parser.add_argument("--runtime-lookup-locks-path", default=str(DEFAULT_RUNTIME_LOOKUP_LOCKS), help="Optional JSONL source terms that must remain original in runtime lookup contexts.")
    return parser.parse_args()


def main():
    args = parse_args()
    args.source_csv = str(Path(args.source_csv).resolve())
    args.translation_jsonl = str(Path(args.translation_jsonl).resolve())
    args.canonical_csv = str(Path(args.canonical_csv).resolve()) if args.canonical_csv else ""
    args.protected_identifiers_path = str(Path(args.protected_identifiers_path).resolve()) if args.protected_identifiers_path else ""
    args.runtime_lookup_locks_path = str(Path(args.runtime_lookup_locks_path).resolve()) if args.runtime_lookup_locks_path else ""
    if not args.output_jsonl:
        args.output_jsonl = str((DEFAULT_SYNCED_OUTPUT if args.mode == "sync-jsonl" else DEFAULT_PATCH_OUTPUT).resolve())
    else:
        args.output_jsonl = str(Path(args.output_jsonl).resolve())

    if args.mode == "patch-current":
        if not args.current_csv:
            raise RuntimeError("--current-csv is required for --mode patch-current")
        args.current_csv = str(Path(args.current_csv).resolve())
        make_current_patch(args)
    else:
        sync_translation_jsonl(args)


if __name__ == "__main__":
    main()
