#!/usr/bin/env python3
import argparse
import csv
import json
import re
import shutil
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = (SCRIPT_DIR / ".." / "..").resolve()
DEFAULT_SOURCE_CSV = ROOT_DIR / "TextExport_original_db_command_scan" / "strings_all.csv"
DEFAULT_COMMAND_STRINGS = ROOT_DIR / "TextExport_original_db_command_scan" / "command_strings.csv"
DEFAULT_TRANSLATIONS = ROOT_DIR / "TextExport" / "mistral_fullgame_translations.before_protected_filter_20260510T141817Z.jsonl"
DEFAULT_STRICT_SAFE = ROOT_DIR / "TextExport" / "strict_safe_dialogue_event_translations.recovered.jsonl"
DEFAULT_PROTECTED = SCRIPT_DIR / "protected_runtime_identifiers.jsonl"
DEFAULT_OUTPUT = ROOT_DIR / "TextExport" / "visible_db_ui_translations.jsonl"

DATABASE_DATA_FILES = {
    "BasicData/CDataBase.dat",
    "BasicData/DataBase.dat",
    "BasicData/SysDatabase.dat",
}
TRANSLATABLE_FILES = DATABASE_DATA_FILES | {"BasicData/Game.dat"}
PROJECT_SCHEMA_SUFFIXES = {
    "CDataBase.project",
    "DataBase.project",
    "SysDatabase.project",
}
ASSET_PATH_RE = re.compile(
    r"(^|[\\/A-Za-z0-9_ .()\\-])(?:[A-Za-z0-9_ .()\\-]+[\\/])*[A-Za-z0-9_ .()\\-]+\."
    r"(?:png|jpg|jpeg|bmp|webp|ogg|wav|mp3|mid|midi|mps|dat|ttf|txt|json|wolf)$",
    re.I,
)
RAW_WOLF_RE = re.compile(r"\\(?:[A-Za-z_][A-Za-z0-9_]*\[[^\]]*\]|[.!><^{}\\])")
PLACEHOLDER_RE = re.compile(r"\{CTRL\d+\}")
JAPANESE_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]")
MOJIBAKE_MARKERS = ("ã", "å", "æ", "ç", "è", "é", "ï¼", "ï½")
EDITOR_ONLY_MARKERS = (
    "自動ｼｽﾃﾑ初期化",
    "自動システム初期化",
    "サンプルゲーム用",
    "ここから下",
    "ここの値",
    "この値",
)


def normalize_file(value):
    key = str(value or "").replace("\\", "/").strip()
    if key in PROJECT_SCHEMA_SUFFIXES:
        return "BasicData/" + key
    return key


def read_csv_rows(path):
    with Path(path).open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def iter_jsonl(path):
    with Path(path).open("r", encoding="utf-8-sig") as f:
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
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    tmp.replace(path)


def convert_export_text(value):
    if value is None:
        return ""
    text = str(value)
    out = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            nxt = text[i + 1]
            if nxt == "\\":
                out.append("\\")
                i += 2
                continue
            if nxt == "n":
                out.append("\n")
                i += 2
                continue
            if nxt == "r":
                out.append("\r")
                i += 2
                continue
            if nxt == "t":
                out.append("\t")
                i += 2
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def maybe_repair_mojibake(text):
    value = str(text or "")
    if not any(marker in value for marker in MOJIBAKE_MARKERS):
        return value
    try:
        return value.encode("latin-1").decode("utf-8")
    except UnicodeError:
        return value


def restore_tokens(template, tokens):
    text = str(template or "")
    for key, value in sorted((tokens or {}).items(), key=lambda item: len(item[0]), reverse=True):
        key_text = str(key)
        value_text = str(value)
        if key_text.startswith("{") and key_text.endswith("}"):
            text = text.replace(key_text, value_text)
        else:
            text = text.replace("{" + key_text + "}", value_text)
            text = text.replace(key_text, value_text)
    return text


def has_japanese(text):
    return bool(JAPANESE_RE.search(str(text or "")))


def looks_like_mojibake(text):
    value = str(text or "")
    return any(marker in value for marker in MOJIBAKE_MARKERS)


def looks_like_asset(text):
    return bool(ASSET_PATH_RE.search(str(text or "").strip()))


def is_short_japanese_glyph_table_entry(text):
    value = str(text or "").strip()
    if len(value) != 1:
        return False
    return bool(re.match(r"^[\u3040-\u30ff\uff00-\uffefー～・？！]$", value))


def is_editor_only_text(text):
    value = str(text or "").strip()
    if not value:
        return True
    if value[0] in "×┣┗┏【":
        return True
    return any(marker in value for marker in EDITOR_ONLY_MARKERS)


def is_identifierish(source, target):
    source = str(source or "").strip()
    target = str(target or "").strip()
    if not source or not target or source == target:
        return False
    if "\n" in source or "\r" in source or "\n" in target or "\r" in target:
        return False
    if len(source) > 80 or len(target) > 120:
        return False
    if RAW_WOLF_RE.search(source) or RAW_WOLF_RE.search(target):
        return False
    if looks_like_asset(source) or looks_like_asset(target):
        return False
    if has_japanese(target) or looks_like_mojibake(target):
        return False
    return bool(has_japanese(source) and re.search(r"[A-Za-z0-9]", target))


def source_key(row):
    return (normalize_file(row.get("file", "")), str(row.get("offset_hex", "")).lower())


def translation_key(row):
    context = str(row.get("context", ""))
    if not context.startswith("offset:"):
        return None
    return (normalize_file(row.get("file", "")), context.split(":", 1)[1].lower())


def load_source_rows(path):
    rows = {}
    for row in read_csv_rows(path):
        rows[source_key(row)] = row
    return rows


def load_translations(paths):
    by_exact = OrderedDict()
    for path in paths:
        for row in iter_jsonl(path):
            key = translation_key(row)
            if key and key not in by_exact:
                by_exact[key] = row
    return by_exact


def load_schema_sources(path):
    sources = set()
    path = Path(path)
    if not path.exists():
        return sources
    for item in iter_jsonl(path):
        if item.get("reason") != "database_project_schema_identifier":
            continue
        file_key = normalize_file(item.get("file", ""))
        if not any(file_key.endswith(suffix) for suffix in PROJECT_SCHEMA_SUFFIXES):
            continue
        text = convert_export_text(item.get("source_text", item.get("text", ""))).strip()
        if text:
            sources.add(text)
    return sources


def command_string_key(row):
    return (normalize_file(row.get("file", "")), str(row.get("string_offset_hex", "")).lower())


def load_command_key_sources(command_rows):
    non_data = defaultdict(Counter)
    data = defaultdict(Counter)
    for row in command_rows:
        if str(row.get("command_id", "")) != "250":
            continue
        text = convert_export_text(row.get("text", "")).strip()
        if not text:
            continue
        idx = str(row.get("string_index", ""))
        if idx == "2":
            data[text][normalize_file(row.get("file", ""))] += 1
        elif idx in {"1", "3"}:
            non_data[text][normalize_file(row.get("file", ""))] += 1
    return set(non_data), set(data)


def restored_translation(row):
    tokens = row.get("tokens") if isinstance(row.get("tokens"), dict) else {}
    return restore_tokens(row.get("translation_template", ""), tokens)


def row_translation_matches_source(source_text, translation_row):
    tokens = translation_row.get("tokens") if isinstance(translation_row.get("tokens"), dict) else {}
    restored_source = maybe_repair_mojibake(restore_tokens(translation_row.get("source_template", ""), tokens))
    return restored_source == source_text


def is_candidate(source_row, target, schema_sources, command_non_data_keys):
    file_key = normalize_file(source_row.get("file", ""))
    source = convert_export_text(source_row.get("text", "")).strip()
    target = str(target or "").strip()
    if file_key not in TRANSLATABLE_FILES:
        return False, "not-translatable-file"
    if not source or not target or source == target:
        return False, "empty-or-unchanged"
    if has_japanese(target) or looks_like_mojibake(target):
        return False, "bad-target"
    if looks_like_asset(source) or looks_like_asset(target):
        return False, "asset"
    if file_key == "BasicData/Game.dat":
        if "font" in target.lower() or "M+" in source or "ノスタル" in source:
            return False, "game-font"
        return True, "game-title"
    if source in command_non_data_keys:
        return False, "db-type-or-field-key"
    # The protected schema list can also include DB data names from project
    # metadata. The real runtime danger here is type/field lookup strings,
    # which are identified from CID 250 non-data slots and handled above.
    if is_short_japanese_glyph_table_entry(source):
        return False, "glyph-table"
    if is_editor_only_text(source):
        return False, "editor-only"
    return True, "db-visible"


def make_output_entry(source_row, target, note, prefix, index):
    return OrderedDict(
        [
            ("id", f"{prefix}-{index}"),
            ("file", normalize_file(source_row.get("file", ""))),
            ("source", "string"),
            ("context", f"offset:{str(source_row.get('offset_hex', '')).lower()}"),
            ("event", OrderedDict([("id", ""), ("name", ""), ("page", "")])),
            ("speaker", ""),
            ("speaker_translation", ""),
            ("source_template", convert_export_text(source_row.get("text", ""))),
            ("translation_template", target),
            ("tokens", {}),
            ("model", "visible-db-ui-builder"),
            ("batch_id", prefix),
            ("usage", {}),
            ("note", note),
        ]
    )


def append_unique(rows, row, seen):
    key = (normalize_file(row.get("file", "")), str(row.get("context", "")).lower())
    existing = seen.get(key)
    if existing:
        old_src = existing.get("source_template", "")
        old_dst = existing.get("translation_template", "")
        if old_src != row.get("source_template", "") or old_dst != row.get("translation_template", ""):
            raise RuntimeError(
                f"conflicting patch for {key}: {old_src!r}->{old_dst!r} vs "
                f"{row.get('source_template', '')!r}->{row.get('translation_template', '')!r}"
            )
        return False
    seen[key] = row
    rows.append(row)
    return True


def build(args):
    source_rows = load_source_rows(args.source_csv)
    command_rows = read_csv_rows(args.command_strings_csv)
    schema_sources = load_schema_sources(args.protected_identifiers_path)
    command_non_data_keys, command_data_keys = load_command_key_sources(command_rows)
    translations = load_translations(args.translation_jsonl)

    rows = []
    seen = {}
    strict_rows = 0
    if args.strict_safe_jsonl:
        for row in iter_jsonl(args.strict_safe_jsonl):
            if append_unique(rows, row, seen):
                strict_rows += 1

    db_name_targets = {}
    db_rows = 0
    skipped = Counter()
    for key, source_row in source_rows.items():
        file_key = normalize_file(source_row.get("file", ""))
        if file_key not in TRANSLATABLE_FILES:
            continue
        translation_row = translations.get(key)
        if not translation_row:
            skipped["missing-translation"] += 1
            continue
        source_text = convert_export_text(source_row.get("text", ""))
        if not row_translation_matches_source(source_text, translation_row):
            skipped["source-mismatch"] += 1
            continue
        target = restored_translation(translation_row).strip()
        ok, reason = is_candidate(source_row, target, schema_sources, command_non_data_keys)
        if not ok:
            skipped[reason] += 1
            continue
        entry = make_output_entry(source_row, target, reason, "visible-db-ui", db_rows + 1)
        if append_unique(rows, entry, seen):
            db_rows += 1
        if file_key in DATABASE_DATA_FILES and is_identifierish(source_text, target):
            # Only data-name lookup slots get synced. Type names and field names stay original.
            db_name_targets.setdefault(source_text.strip(), target)

    lookup_rows = 0
    lookup_skipped = Counter()
    for row in command_rows:
        if str(row.get("command_id", "")) != "250" or str(row.get("string_index", "")) != "2":
            continue
        source = convert_export_text(row.get("text", "")).strip()
        target = db_name_targets.get(source)
        if not target:
            continue
        if source not in command_data_keys:
            lookup_skipped["not-data-key"] += 1
            continue
        entry = make_output_entry(
            {
                "file": row.get("file", ""),
                "offset_hex": str(row.get("string_offset_hex", "")).lower(),
                "text": row.get("text", ""),
            },
            target,
            "sync DB data-name lookup key to translated DB data name",
            "visible-db-lookup-sync",
            lookup_rows + 1,
        )
        if append_unique(rows, entry, seen):
            lookup_rows += 1

    write_jsonl(args.output_jsonl, rows)
    print(f"strict safe rows included: {strict_rows}")
    print(f"DB/title/UI rows added: {db_rows}")
    print(f"DB data-name lookup rows added: {lookup_rows}")
    print(f"DB data-name mapping terms: {len(db_name_targets)}")
    print(f"project schema source terms: {len(schema_sources)}")
    print(f"command non-data key terms: {len(command_non_data_keys)}")
    print(f"command data key terms: {len(command_data_keys)}")
    if skipped:
        print("skipped DB rows:")
        for reason, count in skipped.most_common():
            print(f"  {reason}: {count}")
    if lookup_skipped:
        print("skipped lookup rows:")
        for reason, count in lookup_skipped.most_common():
            print(f"  {reason}: {count}")
    print(f"total output rows: {len(rows)}")
    print(f"wrote: {args.output_jsonl}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Build a WOLF patch for visible DB/title/UI text plus synced DB data-name lookup slots."
    )
    parser.add_argument("--source-csv", default=str(DEFAULT_SOURCE_CSV))
    parser.add_argument("--command-strings-csv", default=str(DEFAULT_COMMAND_STRINGS))
    parser.add_argument("--translation-jsonl", action="append", default=[str(DEFAULT_TRANSLATIONS)])
    parser.add_argument("--strict-safe-jsonl", default=str(DEFAULT_STRICT_SAFE))
    parser.add_argument("--protected-identifiers-path", default=str(DEFAULT_PROTECTED))
    parser.add_argument("--output-jsonl", default=str(DEFAULT_OUTPUT))
    return parser.parse_args()


def main():
    build(parse_args())


if __name__ == "__main__":
    main()
