#!/usr/bin/env python3
import argparse
import csv
import json
import re
import shutil
from collections import OrderedDict
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = (SCRIPT_DIR / ".." / "..").resolve()
DEFAULT_COMMAND_STRINGS = ROOT_DIR / "TextExport_original_db_command_scan" / "command_strings.csv"
DEFAULT_DIALOGUES = ROOT_DIR / "TextExport_original_db_command_scan" / "dialogues.csv"
DEFAULT_SOURCE_CSV = ROOT_DIR / "TextExport_original_db_command_scan" / "strings_all.csv"
DEFAULT_TRANSLATIONS = ROOT_DIR / "TextExport" / "mistral_fullgame_translations.synced.jsonl"
DEFAULT_OUTPUT = ROOT_DIR / "TextExport" / "strict_safe_event_translations.jsonl"

ASSET_PATH_RE = re.compile(
    r"^[A-Za-z0-9_./\\ \-()]+\.(?:png|jpg|jpeg|bmp|webp|ogg|wav|mp3|mid|midi|mps|dat|ttf|txt)$",
    re.I,
)
ASSET_PREFIX_RE = re.compile(
    r"^(?:Picture|SystemFile|CharaChip|EnemyGraphic|BattleEffect|MapChip|SE|BGM|window|Icon|animation|Fog_BackGround)/",
    re.I,
)
ENGINE_MARKER_RE = re.compile(r"^<(?:SQUARE|SCREENSHOT|NONE)>$")
MOJIBAKE_MARKERS = ("ã", "å", "æ", "ç", "è", "é", "ï¼", "ï½")


def normalize_file(value):
    return str(value or "").replace("\\", "/")


def read_csv(path):
    with Path(path).open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def iter_jsonl(path):
    with Path(path).open("r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


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


def looks_like_asset_or_engine_marker(text):
    value = str(text or "").strip()
    return bool(ASSET_PATH_RE.search(value) or ASSET_PREFIX_RE.search(value) or ENGINE_MARKER_RE.search(value))


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


def maybe_repair_mojibake(text):
    value = str(text or "")
    if not any(marker in value for marker in MOJIBAKE_MARKERS):
        return value
    try:
        repaired = value.encode("latin-1").decode("utf-8")
    except UnicodeError:
        return value
    return repaired


def safe_command_slot(row):
    command_id = str(row.get("command_id", ""))
    string_index = str(row.get("string_index", ""))
    text = str(row.get("text", ""))
    if command_id == "101":
        return True
    if command_id == "102":
        return True
    # WOLF versions/tools disagree on Picture's exact numeric CID. Keep only
    # obvious non-resource picture text, never asset paths or engine markers.
    if command_id in {"140", "150"} and string_index == "0":
        return not looks_like_asset_or_engine_marker(text)
    return False


def command_key(row):
    return (normalize_file(row.get("file", "")), str(row.get("string_offset_hex", "")).lower())


def translation_key(row):
    context = str(row.get("context", ""))
    if not context.startswith("offset:"):
        return None
    return (normalize_file(row.get("file", "")), context.split(":", 1)[1].lower())


def source_key(row):
    return (normalize_file(row.get("file", "")), str(row.get("offset_hex", "")).lower())


def build_safe_keys(command_rows):
    return {command_key(row) for row in command_rows if safe_command_slot(row)}


def build_dialogue_keys(dialogue_rows):
    keys = set()
    for row in dialogue_rows:
        offset = str(row.get("string_offset_hex", "")).lower()
        if offset:
            keys.add((normalize_file(row.get("file", "")), offset))
    return keys


def load_source_rows(path):
    rows = {}
    for row in read_csv(path):
        key = source_key(row)
        rows[key] = row
    return rows


def load_translation_memory(paths):
    by_exact = {}
    by_file_source = OrderedDict()
    by_source = OrderedDict()
    total = 0
    for path in paths:
        for row in iter_jsonl(path):
            total += 1
            key = translation_key(row)
            tokens = row.get("tokens") if isinstance(row.get("tokens"), dict) else {}
            raw_source = restore_tokens(row.get("source_template", ""), tokens)
            source_variants = [raw_source]
            repaired_source = maybe_repair_mojibake(raw_source)
            if repaired_source != raw_source:
                source_variants.append(repaired_source)
            if key and key not in by_exact:
                by_exact[key] = row
            for source_variant in source_variants:
                file_source_key = (normalize_file(row.get("file", "")), source_variant)
                if source_variant and file_source_key not in by_file_source:
                    by_file_source[file_source_key] = row
                if source_variant and source_variant not in by_source:
                    by_source[source_variant] = row
    return by_exact, by_file_source, by_source, total


def make_output_row(source_row, translation_row):
    out = OrderedDict(translation_row)
    out["id"] = str(source_row.get("id", out.get("id", "")))
    out["file"] = normalize_file(source_row.get("file", out.get("file", "")))
    out["context"] = f"offset:{str(source_row.get('offset_hex', '')).lower()}"
    out["source_template"] = convert_export_text(source_row.get("text", ""))
    return out


def parse_args():
    parser = argparse.ArgumentParser(
        description="Filter a WOLF translation JSONL down to only strict-safe event text commands."
    )
    parser.add_argument("--command-strings-csv", default=str(DEFAULT_COMMAND_STRINGS))
    parser.add_argument("--dialogues-csv", default=str(DEFAULT_DIALOGUES))
    parser.add_argument("--source-csv", default=str(DEFAULT_SOURCE_CSV))
    parser.add_argument(
        "--translation-jsonl",
        action="append",
        default=[],
        help="Translation JSONL to draw from. Can be passed multiple times.",
    )
    parser.add_argument(
        "--extra-translation-jsonl",
        action="append",
        default=[],
        help="Additional translation JSONL to draw from. This is an alias for passing --translation-jsonl again.",
    )
    parser.add_argument("--output-jsonl", default=str(DEFAULT_OUTPUT))
    return parser.parse_args()


def main():
    args = parse_args()
    command_rows = read_csv(args.command_strings_csv)
    dialogue_rows = read_csv(args.dialogues_csv) if args.dialogues_csv else []
    source_rows = load_source_rows(args.source_csv)
    translation_paths = args.translation_jsonl or [str(DEFAULT_TRANSLATIONS)]
    translation_paths.extend(args.extra_translation_jsonl)
    safe_keys = build_safe_keys(command_rows)
    dialogue_keys = build_dialogue_keys(dialogue_rows)
    safe_keys.update(dialogue_keys)
    by_exact, by_file_source, by_source, total = load_translation_memory(translation_paths)
    kept = []
    missing = 0
    exact_kept = 0
    file_source_kept = 0
    global_source_kept = 0
    for key in sorted(safe_keys):
        source_row = source_rows.get(key)
        if not source_row:
            missing += 1
            continue
        source_text = convert_export_text(source_row.get("text", ""))
        row = by_exact.get(key)
        if row is not None:
            tokens = row.get("tokens") if isinstance(row.get("tokens"), dict) else {}
            if maybe_repair_mojibake(restore_tokens(row.get("source_template", ""), tokens)) != source_text:
                row = None
        if row is None:
            row = by_file_source.get((key[0], source_text))
            if row is not None:
                file_source_kept += 1
        else:
            exact_kept += 1
        if row is None:
            row = by_source.get(source_text)
            if row is not None:
                global_source_kept += 1
        if row is None:
            missing += 1
            continue
        kept.append(make_output_row(source_row, row))
    write_jsonl(args.output_jsonl, kept)
    print(f"translation rows scanned: {total}")
    print(f"safe command slots: {len(build_safe_keys(command_rows))}")
    print(f"dialogue slots: {len(dialogue_keys)}")
    print(f"combined safe slots: {len(safe_keys)}")
    print(f"strict safe rows kept: {len(kept)}")
    print(f"  exact offset matches: {exact_kept}")
    print(f"  file+source matches: {file_source_kept}")
    print(f"  global source matches: {global_source_kept}")
    print(f"safe rows missing translations: {missing}")
    print(f"wrote: {args.output_jsonl}")


if __name__ == "__main__":
    main()
