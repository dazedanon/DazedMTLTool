#!/usr/bin/env python3
import argparse
import csv
import json
import math
import os
import re
import shutil
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from collections import OrderedDict, deque
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from openai import APIConnectionError, APIStatusError, OpenAI, RateLimitError


def configure_console():
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)
            mode = ctypes.c_uint32()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | 0x0004)
        except Exception:
            pass


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = (SCRIPT_DIR / ".." / ".." / "TextExport" / "strings_japanese.csv").resolve()
DEFAULT_OUTPUT = (SCRIPT_DIR / ".." / ".." / "TextExport" / "mistral_fullgame_translations.jsonl").resolve()
DEFAULT_FAILED = (SCRIPT_DIR / ".." / ".." / "TextExport" / "mistral_fullgame_translations.failed.jsonl").resolve()
DEFAULT_PROMPT = SCRIPT_DIR / "prompt.md"
DEFAULT_GLOSSARY = SCRIPT_DIR / "glossary.md"
DEFAULT_TERM_LOCKS = ""
DEFAULT_PROTECTED_IDENTIFIERS = SCRIPT_DIR / "protected_runtime_identifiers.jsonl"
TRANSLATABLE_DATABASE_DATA_FILES = {
    "BasicData/CDataBase.dat",
    "BasicData/DataBase.dat",
    "BasicData/SysDatabase.dat",
}

JAPANESE_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]")
MOJIBAKE_MARKERS = ("\u00e3", "\u00e4", "\u00e5", "\u00e6", "\u00e7", "\u00ef\u00bc", "\u00ef\u00bd")
PROTECT_RE = re.compile(
    r"(__PROTECTED_\d+__|#[0-9A-Fa-f]{6}|\\(?:[A-Za-z_][A-Za-z0-9_]*(?:\[[^\]]*\])?|[.!|><^{}\\])|@\d+|[A-Za-z0-9_./\\-]+\.(?:png|jpg|jpeg|bmp|webp|ogg|wav|mps|dat|ttf|txt|json|wolf))"
)
PLACEHOLDER_RE = re.compile(r"\{CTRL\d+\}")
RAW_WOLF_RE = re.compile(r"\\(?:[A-Za-z_][A-Za-z0-9_]*\[[^\]]*\]|[.!><^])")

MODEL_PRICES_PER_1M = {
    "mistral-medium-3-5": (1.50, 7.50),
    "mistral-large-2512": (0.50, 1.50),
    "mistral-large-latest": (0.50, 1.50),
    "mistral-small-latest": (0.20, 0.60),
}
REQUEST_INTERVAL_SECONDS = 1.0
RPM_WINDOW_SECONDS = 60.0
RPM_WINDOW_MARGIN_SECONDS = 1.0
RUN_ID = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + f"-pid{os.getpid()}"


class ApiRequestFailure(RuntimeError):
    def __init__(self, reason, message, status_code=None, headers=None, retry_after_seconds=None):
        super().__init__(message)
        self.reason = reason
        self.status_code = status_code
        self.headers = headers or {}
        self.retry_after_seconds = retry_after_seconds


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


def normalize_translation_template(text):
    normalized = (
        str(text or "")
        .replace("・", ".")
        .replace("･", ".")
        .replace("～", "-")
        .replace("　", " ")
    )
    leftover_fixes = {
        "あいうえお": "abcde",
        "人生": "life",
        "じんせい": "life",
        "ウルファール": "Wolfarl",
        "エディ": "Edi",
        "本": "Book",
    }
    for source, replacement in leftover_fixes.items():
        normalized = normalized.replace(source, replacement)
    normalized = re.sub(r"\bP\.G\.Edi\b", "P.G. Edi", normalized)
    return normalized


def normalize_file_key(value):
    key = str(value or "").replace("\\", "/").strip()
    if key in {"CDataBase.project", "DataBase.project", "SysDatabase.project"}:
        return "BasicData/" + key
    return key


def protected_file_keys(value):
    key = normalize_file_key(value)
    keys = {key}
    if key.startswith("BasicData/") and key.endswith(".project"):
        keys.add(key.split("/", 1)[1])
    return keys


def should_load_protected_identifier(item):
    file_key = normalize_file_key(item.get("file", ""))
    reason = str(item.get("reason", "")).lower()
    if file_key in TRANSLATABLE_DATABASE_DATA_FILES and "runtime database structure" in reason:
        return False
    return True


def has_japanese(text):
    return bool(JAPANESE_RE.search(text or ""))


def looks_like_mojibake(text):
    value = str(text or "")
    return any(marker in value for marker in MOJIBAKE_MARKERS)


def protect_source_text(text):
    source = convert_export_text(text)
    tokens = OrderedDict()
    index = 1

    def repl(match):
        nonlocal index
        token = match.group(0)
        if token.startswith("\\r[") and has_japanese(token):
            return token
        key = f"CTRL{index}"
        tokens[key] = token
        index += 1
        return "{" + key + "}"

    template = PROTECT_RE.sub(repl, source)
    return template, tokens


def get_token_map(tokens_text):
    tokens = OrderedDict()
    if not tokens_text or not str(tokens_text).strip():
        return tokens
    parts = re.split(r"\s+\|\s+", str(tokens_text))
    for index, part in enumerate(parts, start=1):
        tokens[f"CTRL{index}"] = convert_export_text(part)
    return tokens


def placeholder_counts(text):
    counts = {}
    for match in PLACEHOLDER_RE.findall(text or ""):
        counts[match] = counts.get(match, 0) + 1
    return counts


def placeholder_sort_key(placeholder):
    match = re.search(r"\d+", str(placeholder or ""))
    return int(match.group(0)) if match else 0


def is_safe_auto_repair_token(token):
    return str(token or "") in {"\\", "\\\\", "\\.", "\\!", "\\^", "\\|", "\\>"}


def source_placeholders_are_adjacent(source, left_placeholder, right_placeholder):
    if not left_placeholder or not right_placeholder:
        return False
    pattern = re.escape(left_placeholder) + r"\s*" + re.escape(right_placeholder)
    return bool(re.search(pattern, source or ""))


def repair_missing_placeholders(source, translation, tokens):
    repaired = str(translation or "")
    source_counts = placeholder_counts(source)
    translation_counts = placeholder_counts(repaired)
    source_order = PLACEHOLDER_RE.findall(source or "")
    tokens = tokens or {}

    for placeholder in sorted(source_counts, key=placeholder_sort_key):
        missing_count = source_counts.get(placeholder, 0) - translation_counts.get(placeholder, 0)
        if missing_count <= 0:
            continue

        token_key = placeholder.strip("{}")
        if not is_safe_auto_repair_token(tokens.get(token_key, "")):
            continue

        for _ in range(missing_count):
            source_index = source_order.index(placeholder) if placeholder in source_order else -1
            next_anchor = ""
            previous_anchor = ""
            if source_index >= 0:
                for later in source_order[source_index + 1 :]:
                    if later in repaired:
                        next_anchor = later
                        break
                for earlier in reversed(source_order[:source_index]):
                    if earlier in repaired:
                        previous_anchor = earlier
                        break

            if next_anchor and source_placeholders_are_adjacent(source, placeholder, next_anchor):
                repaired = repaired.replace(next_anchor, placeholder + next_anchor, 1)
            elif previous_anchor and source_placeholders_are_adjacent(source, previous_anchor, placeholder):
                repaired = repaired.replace(previous_anchor, previous_anchor + placeholder, 1)
            else:
                continue
            translation_counts[placeholder] = translation_counts.get(placeholder, 0) + 1

    return repaired


def restore_placeholders(text, tokens):
    restored = str(text or "")
    for key, value in (tokens or {}).items():
        restored = restored.replace("{" + str(key) + "}", str(value))
    return restored


def normalize_lock_text(text):
    return unicodedata.normalize("NFKC", str(text or "")).strip()


def load_term_locks(path):
    lock_path = Path(path)
    if not lock_path.exists():
        return []
    data = json.loads(lock_path.read_text(encoding="utf-8"))
    raw_locks = data.get("locks", data if isinstance(data, list) else [])
    locks = []
    for item in raw_locks:
        target = str(item.get("target", "")).strip()
        sources = item.get("sources", [])
        if isinstance(sources, str):
            sources = [sources]
        normalized_sources = {normalize_lock_text(source) for source in sources if str(source).strip()}
        if target and normalized_sources:
            locks.append({"sources": normalized_sources, "target": target})
    return locks


def validate_term_locks(source, translation, term_locks):
    source_norm = normalize_lock_text(source)
    translation_text = str(translation or "").strip()
    for lock in term_locks or []:
        if source_norm in lock["sources"] and translation_text != lock["target"]:
            return False, f"term lock mismatch: expected {lock['target']!r}"
    return True, ""


def validate_translation(source, translation, tokens=None, term_locks=None):
    source_counts = placeholder_counts(source)
    translation_counts = placeholder_counts(translation)
    for key in sorted(set(source_counts) | set(translation_counts)):
        source_count = source_counts.get(key, 0)
        translation_count = translation_counts.get(key, 0)
        if source_count != translation_count:
            return False, f"placeholder {key} count mismatch: source={source_count} translation={translation_count}"
    ok, reason = validate_term_locks(source, translation, term_locks)
    if not ok:
        return False, reason
    if RAW_WOLF_RE.search(translation or "") and not RAW_WOLF_RE.search(source or ""):
        return False, "raw WOLF control code leaked into translation"
    if has_japanese(translation or ""):
        return False, "Japanese text remains in translation"
    if looks_like_mojibake(translation):
        return False, "mojibake text remains in translation"
    restored = restore_placeholders(translation, tokens)
    if has_japanese(restored):
        return False, "Japanese text remains after restoring placeholders"
    if looks_like_mojibake(restored):
        return False, "mojibake text remains after restoring placeholders"
    return True, ""


def line_purpose(file_name, text):
    lower = (file_name or "").lower()
    plain = (text or "").strip()
    char_count = len(plain)
    if lower.endswith("game.dat"):
        return "game_title_or_global_config"
    if "database" in lower or "sysdatabase" in lower or "cdatabase" in lower:
        if char_count <= 28 and "\n" not in plain:
            return "database_name_or_ui_label"
        return "database_description_or_system_text"
    if "mapdata/" in lower or "mapdata\\" in lower:
        if char_count <= 28 and "\n" not in plain:
            return "map_label_sign_or_choice"
        return "map_event_text"
    if char_count <= 28 and "\n" not in plain:
        return "short_name_or_ui_label"
    return "generic_game_text"


def row_to_line(row, input_kind):
    if input_kind == "dialogue":
        template = convert_export_text(row.get("dialogue_template", ""))
        if not template.strip():
            template = convert_export_text(row.get("dialogue", ""))
        return OrderedDict(
            [
                ("id", str(row.get("id", ""))),
                ("file", str(row.get("file", ""))),
                ("source", str(row.get("source", ""))),
                ("context", str(row.get("context", ""))),
                ("kind", "dialogue"),
                ("purpose", "dialogue_or_message"),
                (
                    "event",
                    OrderedDict(
                        [
                            ("id", str(row.get("event_id", ""))),
                            ("name", str(row.get("event_name", ""))),
                            ("page", str(row.get("page_id", ""))),
                        ]
                    ),
                ),
                ("command_index", str(row.get("command_index", ""))),
                (
                    "offset",
                    OrderedDict(
                        [
                            ("command", str(row.get("command_offset_hex", ""))),
                            ("string", str(row.get("string_offset_hex", ""))),
                        ]
                    ),
                ),
                ("speaker", str(row.get("speaker", ""))),
                ("visible_source", convert_export_text(row.get("dialogue", ""))),
                ("source_template", template),
                ("tokens", get_token_map(row.get("tokens", ""))),
            ]
        )

    template, tokens = protect_source_text(row.get("text", ""))
    visible_source = convert_export_text(row.get("text", ""))
    return OrderedDict(
        [
            ("id", str(row.get("id", ""))),
            ("file", str(row.get("file", ""))),
            ("source", "string"),
            ("context", f"offset:{row.get('offset_hex', '')}"),
            ("kind", str(row.get("kind", ""))),
            ("purpose", line_purpose(str(row.get("file", "")), visible_source)),
            ("event", OrderedDict([("id", ""), ("name", ""), ("page", "")])),
            ("command_index", ""),
            ("offset", OrderedDict([("command", ""), ("string", str(row.get("offset_hex", "")))])),
            ("speaker", ""),
            ("visible_source", visible_source),
            ("source_template", template),
            ("tokens", tokens),
        ]
    )


def translation_key(row, input_kind):
    line = row_to_line(row, input_kind)
    token_json = json.dumps(line["tokens"], ensure_ascii=False, separators=(",", ":"))
    return f"{line['speaker']}\t{line['source_template']}\t{token_json}"


def translation_memory_key(source_template, tokens=None, speaker="", input_kind="strings"):
    token_json = json.dumps(tokens or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    source_norm = normalize_lock_text(source_template)
    if input_kind == "dialogue":
        return f"{normalize_lock_text(speaker)}\t{source_norm}\t{token_json}"
    return f"{source_norm}\t{token_json}"


def line_memory_key(line, input_kind):
    return translation_memory_key(
        line.get("source_template", ""),
        line.get("tokens", {}),
        line.get("speaker", ""),
        input_kind,
    )


def output_item_memory_key(item, input_kind):
    tokens = item.get("tokens", {})
    if isinstance(tokens, str):
        tokens = get_token_map(tokens)
    return translation_memory_key(
        item.get("source_template", ""),
        tokens,
        item.get("speaker", ""),
        input_kind,
    )


def read_translation_memory(path, input_kind):
    grouped = OrderedDict()
    memory = {}
    conflicts = []
    path = Path(path)
    if not path.exists():
        return memory, conflicts

    with path.open("r", encoding="utf-8") as f:
        for line_number, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                print(f"warning: skipping malformed existing JSONL line while loading translation memory from {path}")
                continue
            source_template = str(item.get("source_template", ""))
            translation_template = normalize_translation_template(item.get("translation_template", ""))
            if not source_template.strip() or not translation_template.strip():
                continue
            key = output_item_memory_key(item, input_kind)
            entry = {
                "id": str(item.get("id", "")),
                "line": line_number,
                "speaker_translation": str(item.get("speaker_translation", "")),
                "source_template": source_template,
                "translation_template": translation_template,
            }
            grouped.setdefault(key, []).append(entry)

    for key, entries in grouped.items():
        counts = Counter((entry["speaker_translation"], entry["translation_template"]) for entry in entries)
        first_index = {}
        representative = {}
        for index, entry in enumerate(entries):
            pair = (entry["speaker_translation"], entry["translation_template"])
            first_index.setdefault(pair, index)
            representative.setdefault(pair, entry)
        best_pair = min(counts, key=lambda pair: (-counts[pair], first_index[pair]))
        memory[key] = representative[best_pair]
        if len(counts) > 1:
            alternatives = [
                OrderedDict(
                    [
                        ("count", count),
                        ("translation", pair[1]),
                        ("speaker_translation", pair[0]),
                        ("first_id", representative[pair].get("id", "")),
                    ]
                )
                for pair, count in sorted(counts.items(), key=lambda item: (-item[1], first_index[item[0]]))
            ]
            conflicts.append(
                OrderedDict(
                    [
                        ("key", key),
                        ("chosen_translation", memory[key].get("translation_template", "")),
                        ("alternatives", alternatives),
                    ]
                )
            )
    return memory, conflicts


def remember_translation(memory, line, translation, input_kind):
    key = line_memory_key(line, input_kind)
    if key in memory:
        return
    memory[key] = {
        "id": str(line.get("id", "")),
        "line": "",
        "speaker_translation": str(translation.get("speaker_translation", "")),
        "source_template": str(line.get("source_template", "")),
        "translation_template": str(translation.get("translation_template", "")),
    }


STRICT_MEMORY_PURPOSES = {
    "database_name_or_ui_label",
    "game_title_or_global_config",
    "short_name_or_ui_label",
}


def is_strict_memory_line(line, input_kind):
    if input_kind != "strings":
        return False
    source = normalize_lock_text(line.get("source_template", ""))
    if line.get("purpose") not in STRICT_MEMORY_PURPOSES:
        return False
    if "\n" in source or "\r" in source:
        return False
    if not source:
        return False
    return True


def is_source_term_candidate(line, input_kind):
    if not is_strict_memory_line(line, input_kind):
        return False
    source = normalize_lock_text(line.get("source_template", ""))
    if PLACEHOLDER_RE.search(source):
        return False
    if not has_japanese(source):
        return False
    return 2 <= len(source) <= 32


def is_term_memory_candidate(line, translation_template, input_kind):
    if not is_source_term_candidate(line, input_kind):
        return False
    source = normalize_lock_text(line.get("source_template", ""))
    target = normalize_lock_text(translation_template)
    if not source or not target:
        return False
    if "\n" in target or "\r" in target:
        return False
    if PLACEHOLDER_RE.search(target):
        return False
    if not has_japanese(source) or has_japanese(target) or looks_like_mojibake(target):
        return False
    if len(target) > 80:
        return False
    if not re.search(r"[A-Za-z]", target):
        return False
    return True


def build_dynamic_term_memory(rows, input_kind, translation_memory):
    term_memory = OrderedDict()
    if not translation_memory:
        return term_memory
    for row in rows:
        line = row_to_line(row, input_kind)
        entry = translation_memory.get(line_memory_key(line, input_kind))
        if not entry:
            continue
        target = entry.get("translation_template", "")
        if is_term_memory_candidate(line, target, input_kind):
            source_norm = normalize_lock_text(line.get("source_template", ""))
            term_memory.setdefault(source_norm, {"source": str(line.get("source_template", "")), "target": normalize_lock_text(target)})
    return term_memory


def remember_dynamic_term(term_memory, line, translation, input_kind):
    target = translation.get("translation_template", "")
    if not is_term_memory_candidate(line, target, input_kind):
        return
    source_norm = normalize_lock_text(line.get("source_template", ""))
    term_memory.setdefault(source_norm, {"source": str(line.get("source_template", "")), "target": normalize_lock_text(target)})


def relevant_dynamic_terms(lines, term_memory):
    result = []
    seen = set()
    terms = sorted(term_memory.items(), key=lambda item: len(item[0]), reverse=True)
    for line in lines:
        source_norm = normalize_lock_text(line.get("source_template", ""))
        for term_source, term in terms:
            if term_source == source_norm or term_source not in source_norm:
                continue
            if term_source in seen:
                continue
            seen.add(term_source)
            result.append(OrderedDict([("source", term["source"]), ("target", term["target"])]))
    return result[:40]


def validate_dynamic_terms(source, translation, term_memory):
    source_norm = normalize_lock_text(source)
    translation_norm = normalize_lock_text(translation)
    terms = sorted(term_memory.items(), key=lambda item: len(item[0]), reverse=True)
    for term_source, term in terms:
        if term_source == source_norm or term_source not in source_norm:
            continue
        target = term["target"]
        if target and target not in translation_norm:
            return False, f"translation memory term mismatch: {term['source']!r} must stay {target!r}"
    return True, ""


def make_output_entry(alias_line, translation, args, batch_id, request_id, representative_id, usage_dict):
    return OrderedDict(
        [
            ("id", str(alias_line["id"])),
            ("file", str(alias_line["file"])),
            ("source", str(alias_line["source"])),
            ("context", str(alias_line["context"])),
            ("event", alias_line["event"]),
            ("speaker", str(alias_line["speaker"])),
            ("speaker_translation", str(translation.get("speaker_translation", ""))),
            ("source_template", str(alias_line["source_template"])),
            ("translation_template", str(translation.get("translation_template", ""))),
            ("tokens", alias_line["tokens"]),
            ("model", args.model),
            ("batch_id", str(batch_id)),
            ("request_id", request_id),
            ("representative_id", str(representative_id)),
            ("translated_at_utc", utc_now()),
            ("usage", usage_dict),
        ]
    )


def apply_translation_memory(rows, input_kind, args, done, memory):
    filled = 0
    if not memory:
        return filled
    request_id = f"{RUN_ID}-translation-memory"
    for row in rows:
        row_id = str(row.get("id", ""))
        if row_id in done:
            continue
        alias_line = row_to_line(row, input_kind)
        if not is_strict_memory_line(alias_line, input_kind):
            continue
        entry = memory.get(line_memory_key(alias_line, input_kind))
        if not entry:
            continue
        translation = {
            "speaker_translation": entry.get("speaker_translation", ""),
            "translation_template": entry.get("translation_template", ""),
        }
        ok, reason = validate_translation(str(alias_line["source_template"]), str(translation["translation_template"]), alias_line["tokens"])
        if not ok:
            print(f"warning: skipped translation-memory row {row_id}: {reason}")
            continue
        output_entry = make_output_entry(
            alias_line,
            translation,
            args,
            "translation-memory",
            request_id,
            entry.get("id", ""),
            {},
        )
        append_json_line(args.output_jsonl, output_entry)
        done.add(row_id)
        filled += 1
    return filled


def sort_translation_jobs(jobs, input_kind):
    if input_kind != "strings":
        return jobs

    def key(item):
        index, job = item
        line = row_to_line(job["row"], input_kind)
        term_priority = 0 if is_source_term_candidate(line, input_kind) else 1
        source_len = len(normalize_lock_text(line.get("source_template", "")))
        return (term_priority, str(line.get("file", "")), source_len if term_priority == 0 else index, index)

    return [job for _, job in sorted(enumerate(jobs), key=key)]


def new_translation_jobs(rows, input_kind, no_dedupe):
    jobs = []
    if no_dedupe:
        for row in rows:
            jobs.append({"row": row, "rows": [row]})
        return sort_translation_jobs(jobs, input_kind)

    by_key = {}
    for row in rows:
        line = row_to_line(row, input_kind)
        if not is_strict_memory_line(line, input_kind):
            jobs.append({"row": row, "rows": [row]})
            continue
        key = translation_key(row, input_kind)
        if key not in by_key:
            job = {"row": row, "rows": [row]}
            by_key[key] = job
            jobs.append(job)
        else:
            by_key[key]["rows"].append(row)
    return sort_translation_jobs(jobs, input_kind)


def new_batches(jobs, size):
    batches = []
    current = []
    current_key = None
    for job in jobs:
        row = job["row"]
        key = f"{row.get('file', '')}|{row.get('context', '')}"
        if current and (len(current) >= size or key != current_key):
            batches.append(current)
            current = []
        current.append(job)
        current_key = key
    if current:
        batches.append(current)
    return batches


def append_json_line(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n")


def read_done_ids(path):
    done = set()
    path = Path(path)
    if not path.exists():
        return done
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                print(f"warning: skipping malformed existing JSONL line in {path}")
                continue
            if item.get("id") is not None:
                done.add(str(item["id"]))
    return done


def read_translation_history(path, limit):
    history = deque(maxlen=max(0, limit))
    path = Path(path)
    if limit <= 0 or not path.exists():
        return history
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                print(f"warning: skipping malformed existing JSONL line while loading history from {path}")
                continue
            if item.get("source_template") and item.get("translation_template"):
                history.append(
                    OrderedDict(
                        [
                            ("speaker", str(item.get("speaker", ""))),
                            ("source_template", str(item.get("source_template", ""))),
                            ("translation_template", str(item.get("translation_template", ""))),
                        ]
                    )
                )
    return history


def response_content(response):
    if hasattr(response, "choices"):
        choices = response.choices or []
    else:
        choices = response.get("choices") or []
    if not choices:
        raise ValueError("API response has no choices")
    choice = choices[0]
    if hasattr(choice, "message"):
        message = choice.message
        content = getattr(message, "content", None)
    else:
        message = choice.get("message") or {}
        content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                if "text" in part:
                    parts.append(str(part["text"]))
                elif "content" in part:
                    parts.append(str(part["content"]))
            else:
                parts.append(str(part))
        return "".join(parts)
    return json.dumps(content, ensure_ascii=False)


def retry_delay_ms(base_ms, attempt):
    if base_ms <= 0:
        return 0
    return int(min(base_ms * (2 ** max(0, attempt - 1)), 300000))


def headers_to_dict(headers):
    if not headers:
        return {}
    try:
        return {str(k).lower(): str(v) for k, v in dict(headers).items()}
    except Exception:
        return {}


def header_value(headers, *names):
    headers = headers_to_dict(headers)
    for name in names:
        value = headers.get(str(name).lower())
        if value:
            return value
    return ""


def parse_retry_after_header(value):
    value = str(value or "").strip()
    if not value:
        return None
    try:
        seconds = float(value)
        return max(0.0, seconds)
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None


def parse_reset_header(value):
    value = str(value or "").strip()
    if not value:
        return None
    try:
        number = float(value)
    except ValueError:
        return parse_retry_after_header(value)
    now_epoch = time.time()
    if number > 1_000_000_000_000:
        return max(0.0, (number / 1000.0) - now_epoch)
    if number > 1_000_000_000:
        return max(0.0, number - now_epoch)
    return max(0.0, number)


def rate_limit_header_delay(headers):
    retry_after = header_value(headers, "retry-after")
    delay = parse_retry_after_header(retry_after)
    if delay is not None:
        return delay

    retry_after_ms = header_value(headers, "retry-after-ms", "x-retry-after-ms")
    if retry_after_ms:
        try:
            return max(0.0, float(retry_after_ms) / 1000.0)
        except ValueError:
            pass

    candidates = [
        "x-ratelimit-reset",
        "x-ratelimit-reset-requests",
        "x-ratelimit-reset-tokens",
        "ratelimit-reset",
    ]
    delays = []
    for name in candidates:
        reset = header_value(headers, name)
        parsed = parse_reset_header(reset)
        if parsed is not None:
            delays.append(parsed)
    return max(delays) if delays else None


def short_error_reason(message):
    if isinstance(message, ApiRequestFailure):
        return message.reason
    text = str(message or "").strip()
    lower = text.lower()
    if not text:
        return "unknown"
    http_match = re.search(r"http\s+(\d+)", lower)
    if http_match:
        code = http_match.group(1)
        if code == "429":
            return "rate limit"
        return f"HTTP {code}"
    if "rate limit" in lower or "too many requests" in lower:
        return "rate limit"
    if "timeout" in lower or "timed out" in lower:
        return "timeout"
    if "connection" in lower or "connect" in lower or "network" in lower:
        return "connection"
    if "api response has no choices" in lower:
        return "no choices"
    if "not valid json" in lower or "json" in lower:
        return "bad JSON"
    if "translation count mismatch" in lower:
        return "count mismatch"
    if "missing id" in lower:
        match = re.search(r"missing id\s+([^\s;]+)", text, re.IGNORECASE)
        return f"missing id {match.group(1)}" if match else "missing id"
    if "unexpected id" in lower:
        return "unexpected id"
    if "placeholder" in lower:
        return "placeholder mismatch"
    if "japanese text remains" in lower:
        return "JP remains"
    if "raw wolf" in lower:
        return "raw code"
    if "empty translation" in lower:
        return "empty output"
    return text[:48] + ("..." if len(text) > 48 else "")


def resolve_base_url(endpoint):
    endpoint = (endpoint or "").strip().rstrip("/")
    suffix = "/chat/completions"
    if endpoint.endswith(suffix):
        return endpoint[: -len(suffix)]
    return endpoint


def model_prices(args):
    in_price, out_price = MODEL_PRICES_PER_1M.get(args.model, (1.50, 7.50))
    if args.input_cost_per_1m is not None:
        in_price = args.input_cost_per_1m
    if args.output_cost_per_1m is not None:
        out_price = args.output_cost_per_1m
    return float(in_price), float(out_price)


def calculate_cost(input_tokens, output_tokens, args):
    in_price, out_price = model_prices(args)
    return ((input_tokens or 0) * in_price / 1_000_000.0) + ((output_tokens or 0) * out_price / 1_000_000.0)


def result_line(filename, input_tokens, output_tokens, seconds, args, total_cost=None, ok=True, error=""):
    cost = calculate_cost(input_tokens, output_tokens, args)
    check = "✓" if ok else "✗"
    check = "\u2713" if ok else "\u2717"
    line = (
        f"{filename}: "
        f"[Input: {input_tokens}]"
        f"[Output: {output_tokens}]"
        f"[Cost: ${cost:,.4f}]"
    )
    if total_cost is not None:
        line += f"[Total: ${total_cost:,.4f}]"
    line += f"[{seconds:.1f}s] {check}"
    if error:
        line += f" {error}"
    return line


def usage_to_dict(usage):
    if usage is None:
        return None
    if isinstance(usage, dict):
        return dict(usage)
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    if hasattr(usage, "dict"):
        return usage.dict()
    result = {}
    for name in (
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "input_tokens",
        "output_tokens",
    ):
        value = getattr(usage, name, None)
        if value is not None:
            result[name] = value
    return result or None


def response_usage(response):
    if hasattr(response, "usage"):
        return response.usage
    if isinstance(response, dict):
        return response.get("usage")
    return None


def usage_token_pair(usage):
    data = usage_to_dict(usage) or {}
    input_tokens = data.get("prompt_tokens", data.get("input_tokens", 0)) or 0
    output_tokens = data.get("completion_tokens", data.get("output_tokens", 0)) or 0
    return int(input_tokens), int(output_tokens)


def read_output_usage_totals(path):
    total_input = 0
    total_output = 0
    request_count = 0
    seen_request_ids = set()
    last_legacy_key = None
    path = Path(path)
    if not path.exists():
        return total_input, total_output, request_count

    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                last_legacy_key = None
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                last_legacy_key = None
                continue

            usage = item.get("usage")
            if not usage:
                last_legacy_key = None
                continue

            input_tokens, output_tokens = usage_token_pair(usage)
            if input_tokens <= 0 and output_tokens <= 0:
                continue

            request_id = str(item.get("request_id") or "")
            if request_id:
                last_legacy_key = None
                if request_id in seen_request_ids:
                    continue
                seen_request_ids.add(request_id)
            else:
                usage_key = json.dumps(usage_to_dict(usage) or {}, sort_keys=True, separators=(",", ":"))
                legacy_key = (str(item.get("model", "")), str(item.get("batch_id", "")), usage_key)
                if legacy_key == last_legacy_key:
                    continue
                last_legacy_key = legacy_key

            total_input += input_tokens
            total_output += output_tokens
            request_count += 1

    return total_input, total_output, request_count


def total_translation_line(label, input_tokens, output_tokens, seconds, args, request_count=0):
    cost = calculate_cost(input_tokens, output_tokens, args)
    line = (
        f"{label}: "
        f"[Input: {input_tokens}]"
        f"[Output: {output_tokens}]"
        f"[Cost: ${cost:,.4f}]"
    )
    if request_count:
        line += f"[Requests: {request_count}]"
    line += f"[{format_duration(seconds)}] \u2713"
    return line
    line += f"[{seconds:.1f}s] âœ“"
    return line


def format_duration(seconds):
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        return "--"
    if seconds < 0 or math.isnan(seconds) or math.isinf(seconds):
        return "--"
    total = int(math.ceil(seconds))
    if total < 60:
        return f"{total}s"
    minutes, sec = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m {sec:02d}s"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes:02d}m"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours:02d}h"


class Progress:
    def __init__(self, total, completed, file_totals=None, file_completed=None, total_batches=0):
        self.total = total
        self.completed = completed
        self.file_totals = file_totals or Counter()
        self.file_completed = file_completed or Counter()
        self.total_batches = total_batches
        self.completed_batches = 0
        self.cycle_seconds_total = 0.0
        self.line_active = False

    def percent(self, label=None):
        current, total = self.file_counts(label)
        if total <= 0:
            return 100.0
        return min(100.0, (current * 100.0) / total)

    def file_counts(self, label):
        label = label or ""
        total = self.file_totals.get(label, 0)
        current = self.file_completed.get(label, 0)
        if total <= 0:
            total = self.total
            current = self.completed
        return current, total

    def eta(self):
        if self.completed_batches <= 0 or self.cycle_seconds_total <= 0:
            return "--"
        remaining_batches = max(0, self.total_batches - self.completed_batches)
        if remaining_batches <= 0:
            return "0s"
        observed_cycle_seconds = self.cycle_seconds_total / self.completed_batches
        return format_duration(remaining_batches * observed_cycle_seconds)

    def shorten(self, label, max_len):
        label = label or "translation"
        max_len = max(8, max_len)
        if len(label) <= max_len:
            return label
        return "..." + label[-(max_len - 3) :]

    def compact_status(self, status):
        status = (status or "").strip()
        if not status:
            return ""
        match = re.search(r"(pass-\d+) batch (\d+)/(\d+), lines=(\d+), attempt=(\d+) sending", status)
        if match:
            return f"{match.group(1)} b{match.group(2)}/{match.group(3)} a{match.group(5)} sending"
        match = re.search(r"(pass-\d+) batch (\d+)/(\d+), lines=(\d+), attempt=(\d+)", status)
        if match:
            return f"{match.group(1)} b{match.group(2)}/{match.group(3)} a{match.group(5)}"
        match = re.search(r"done; last API ([^;]+); avg cycle (.+)", status)
        if match:
            return f"ok {match.group(1)} avg {match.group(2)}"
        match = re.search(r"API failed after ([^;]+); retry in (.+)", status)
        if match:
            return f"retry {match.group(2)} after {match.group(1)}"
        match = re.search(r"(.+) after ([^;]+); retry in (.+)", status)
        if match:
            return f"{match.group(1)} retry {match.group(3)}"
        match = re.search(r"rate wait (.+)", status)
        if match:
            return f"wait {match.group(1)}"
        match = re.search(r"(.+); retrying", status)
        if match:
            return f"{match.group(1)} retry"
        if status == "API failed; no retries left":
            return "failed"
        match = re.search(r"(.+); no retries left", status)
        if match:
            return f"{match.group(1)} failed"
        if status == "invalid JSON; retrying":
            return "invalid JSON"
        if status == "validation failed; retrying":
            return "validation retry"
        return status

    def visible_len(self, text):
        return len(re.sub(r"\x1b\[[0-9;]*m", "", text))

    def crop_visible(self, text, max_len):
        max_len = max(0, max_len)
        if self.visible_len(text) <= max_len:
            return text
        plain = re.sub(r"\x1b\[[0-9;]*m", "", text)
        if max_len <= 3:
            return plain[:max_len]
        return plain[: max_len - 3] + "..."

    def finish_line(self):
        if self.line_active:
            print()
            self.line_active = False

    def print_result(self, line):
        width = shutil.get_terminal_size((120, 20)).columns
        plain = re.sub(r"\x1b\[[0-9;]*m", "", line)
        clear = max(0, width - len(plain) - 1)
        sys.stdout.write("\r\x1b[2K" + line + (" " * clear) + "\n")
        sys.stdout.flush()
        self.line_active = False

    def write(self, label, status="", newline=False):
        width = shutil.get_terminal_size((120, 20)).columns
        width = max(60, width)
        bar_width = 10
        current, total = self.file_counts(label)
        percent = self.percent(label)
        filled = int(math.floor(bar_width * percent / 100.0))
        empty = bar_width - filled
        counter = f"{current}/{total} {percent:.2f}%"
        status = self.compact_status(status)
        tail = f"{counter} | T {self.completed}/{self.total} | ETA {self.eta()}"
        if status:
            tail += f" | {status}"
        max_tail = max(28, width - bar_width - 24)
        tail = self.crop_visible(tail, max_tail)
        label_max = max(10, width - bar_width - self.visible_len(tail) - 4)
        label = self.shorten(label, label_max)
        bar = "\x1b[47m" + (" " * filled) + "\x1b[0m" + "\x1b[100m" + (" " * empty) + "\x1b[0m"
        line = f"{label}: {bar} {tail}"
        visible = self.visible_len(line)
        if visible > width - 1:
            overflow = visible - (width - 1)
            label = self.shorten(label, max(8, len(label) - overflow))
            line = f"{label}: {bar} {tail}"
        line = self.crop_visible(line, width - 1)
        clear = max(0, width - self.visible_len(line) - 1)
        sys.stdout.write("\r\x1b[2K" + line + (" " * clear))
        sys.stdout.flush()
        if newline:
            sys.stdout.write("\n")
            sys.stdout.flush()
            self.line_active = False
        else:
            self.line_active = True


def wait_retry(progress, delay_ms, label, status):
    remaining = max(0, int(delay_ms))
    while remaining > 0:
        progress.write(label, f"{status}; retry in {format_duration(math.ceil(remaining / 1000.0))}")
        sleep_ms = min(1000, remaining)
        time.sleep(sleep_ms / 1000.0)
        remaining -= sleep_ms


def trim_request_times(request_times, now):
    rpm_window = RPM_WINDOW_SECONDS + RPM_WINDOW_MARGIN_SECONDS
    while request_times and now - request_times[0] >= rpm_window:
        request_times.popleft()


def forget_rate_limited_request(rate_state, sent_at):
    request_times = rate_state.setdefault("request_times", deque())
    if sent_at is None:
        return
    filtered = deque(t for t in request_times if abs(t - sent_at) > 0.001)
    request_times.clear()
    request_times.extend(filtered)


def local_rate_wait_seconds(args, rate_state):
    rpm_limit = int(math.floor(args.requests_per_minute)) if args.requests_per_minute > 0 else 0
    request_times = rate_state.setdefault("request_times", deque())
    now = time.perf_counter()
    rpm_window = RPM_WINDOW_SECONDS + RPM_WINDOW_MARGIN_SECONDS
    trim_request_times(request_times, now)

    server_block_until = rate_state.get("server_block_until", 0.0) or 0.0
    server_wait = max(0.0, server_block_until - now)

    last_request_at = rate_state.get("last_request_at")
    rps_wait = 0.0
    if last_request_at is not None:
        rps_wait = max(0.0, last_request_at + REQUEST_INTERVAL_SECONDS - now)

    rpm_wait = 0.0
    if rpm_limit > 0 and len(request_times) >= rpm_limit:
        rpm_wait = max(0.0, rpm_window - (now - request_times[0]))

    wait_seconds = max(server_wait, rps_wait, rpm_wait)
    if wait_seconds <= 0:
        return 0.0, ""
    if server_wait >= rps_wait and server_wait >= rpm_wait:
        return wait_seconds, "server"
    if rpm_wait >= rps_wait and rpm_wait > 0:
        return wait_seconds, "RPM"
    return wait_seconds, "RPS"


def wait_for_rate_limit(args, progress, label, rate_state):
    request_times = rate_state.setdefault("request_times", deque())

    while True:
        wait_seconds, reason = local_rate_wait_seconds(args, rate_state)
        if wait_seconds <= 0:
            break

        progress.write(label, f"rate wait {format_duration(wait_seconds)} {reason}")
        sleep_for = min(1.0, wait_seconds)
        time.sleep(sleep_for)

    sent_at = time.perf_counter()
    request_times.append(sent_at)
    rate_state["last_request_at"] = sent_at
    return sent_at


def rate_limit_retry_delay_ms(args, rate_state, exc, sent_at, attempt):
    forget_rate_limited_request(rate_state, sent_at)
    header_delay = exc.retry_after_seconds if isinstance(exc, ApiRequestFailure) else None
    local_delay, local_reason = local_rate_wait_seconds(args, rate_state)

    if header_delay is not None:
        delay_seconds = max(header_delay, local_delay) + RPM_WINDOW_MARGIN_SECONDS
    elif local_delay > 0 and local_reason in ("RPM", "server"):
        delay_seconds = local_delay
    else:
        delay_seconds = max(1.0, retry_delay_ms(args.retry_delay_ms, attempt) / 1000.0)

    rate_state["server_block_until"] = max(rate_state.get("server_block_until", 0.0) or 0.0, time.perf_counter() + delay_seconds)
    return int(math.ceil(delay_seconds * 1000.0))


def invoke_mistral_batch(args, system_prompt, payload, validation_hint):
    shape = '{"translations":[{"id":"same id as input","speaker_translation":"translated visible speaker name or empty string","translation_template":"English translation preserving every {CTRLn} placeholder"}]}'
    user_prompt = (
        f"Translate this batch to {args.target_language}.\n\n"
        "Return JSON only in this exact shape:\n"
        f"{shape}\n\n"
        "Validation hint from previous attempt:\n"
        f"{validation_hint}\n\n"
        "Batch:\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )
    params = {
        "model": args.model,
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if args.reasoning_effort == "high" and args.model in ("mistral-medium-3-5", "mistral-small-latest"):
        params["reasoning_effort"] = "high"

    client = OpenAI(api_key=args.api_key, base_url=resolve_base_url(args.endpoint), timeout=args.timeout_seconds)
    try:
        return client.chat.completions.create(**params)
    except RateLimitError as exc:
        headers = headers_to_dict(getattr(getattr(exc, "response", None), "headers", None))
        retry_after = rate_limit_header_delay(headers)
        raise ApiRequestFailure("rate limit", f"rate limit: {exc}", status_code=429, headers=headers, retry_after_seconds=retry_after) from exc
    except APIConnectionError as exc:
        raise ApiRequestFailure("connection", f"connection error: {exc}") from exc
    except APIStatusError as exc:
        headers = headers_to_dict(getattr(getattr(exc, "response", None), "headers", None))
        retry_after = rate_limit_header_delay(headers) if getattr(exc, "status_code", None) == 429 else None
        reason = "rate limit" if getattr(exc, "status_code", None) == 429 else f"HTTP {exc.status_code}"
        raise ApiRequestFailure(reason, f"HTTP {exc.status_code}: {exc}", status_code=exc.status_code, headers=headers, retry_after_seconds=retry_after) from exc


def parse_response_json(raw):
    parsed = json.loads(raw)
    translations = parsed.get("translations")
    if not isinstance(translations, list):
        raise ValueError("response JSON missing translations array")
    return translations


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read_input_rows(path):
    with Path(path).open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        columns = reader.fieldnames or []
    return rows, columns


def load_protected_identifiers(path):
    protected = {
        "by_file_id": set(),
        "by_file_offset": set(),
        "by_file_text": set(),
    }
    if not path:
        return protected
    path = Path(path)
    if not path.exists():
        return protected
    with path.open("r", encoding="utf-8-sig") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                print(f"warning: skipping malformed protected identifier line {line_no}: {path}")
                continue
            if not should_load_protected_identifier(item):
                continue
            text = str(item.get("source_text", item.get("text", "")))
            file_value = str(item.get("file", ""))
            row_id = str(item.get("id", ""))
            offset_hex = str(item.get("offset_hex", item.get("offset", ""))).strip()
            match_mode = str(item.get("match", "")).strip().lower()
            if not text or not file_value:
                continue
            for file_key in protected_file_keys(file_value):
                if row_id:
                    protected["by_file_id"].add((file_key, row_id))
                if offset_hex:
                    protected["by_file_offset"].add((file_key, offset_hex.lower()))
                if match_mode not in {"id", "offset", "id_or_offset"}:
                    protected["by_file_text"].add((file_key, text))
    return protected


def protected_row_reason(row, input_kind, protected):
    if input_kind != "strings" or not protected:
        return ""
    row_id = str(row.get("id", ""))
    raw_text = str(row.get("text", ""))
    visible_text = convert_export_text(raw_text)
    offset_hex = str(row.get("offset_hex", "")).strip().lower()
    for file_key in protected_file_keys(row.get("file", "")):
        if row_id and (file_key, row_id) in protected.get("by_file_id", set()):
            return "runtime identifier"
        if offset_hex and (file_key, offset_hex) in protected.get("by_file_offset", set()):
            return "runtime identifier"
        if (file_key, raw_text) in protected.get("by_file_text", set()):
            return "runtime identifier"
        if visible_text != raw_text and (file_key, visible_text) in protected.get("by_file_text", set()):
            return "runtime identifier"
    return ""


def filter_protected_rows(rows, input_kind, protected):
    kept = []
    skipped = 0
    for row in rows:
        if protected_row_reason(row, input_kind, protected):
            skipped += 1
        else:
            kept.append(row)
    return kept, skipped


def filter_rows(rows, input_kind, args):
    if input_kind == "dialogue":
        rows = [r for r in rows if str(r.get("dialogue_template", "")).strip()]
    else:
        rows = [
            r
            for r in rows
            if str(r.get("text", "")).strip() and has_japanese(convert_export_text(r.get("text", "")))
        ]
    if args.map_only:
        rows = [r for r in rows if input_kind == "dialogue" and r.get("source") == "map"]
    if args.common_only:
        rows = [r for r in rows if input_kind == "dialogue" and str(r.get("source", "")).startswith("common_event")]
    if args.start_after_id > 0:
        rows = [r for r in rows if int(r.get("id", "0") or "0") > args.start_after_id]
    if args.max_rows > 0:
        rows = rows[: args.max_rows]
    return rows


def run_batch_set(batch_set, pass_label, args, input_kind, system_prompt, history, done, progress, file_stats, reported_files, rate_state, total_usage, term_locks, translation_memory, dynamic_term_memory):
    for batch_number, batch_jobs in enumerate(batch_set, start=1):
        lines = [row_to_line(job["row"], input_kind) for job in batch_jobs]
        jobs_by_id = {str(job["row"].get("id", "")): job for job in batch_jobs}
        current_label = str(lines[0].get("file", args.input_csv)) if lines else str(args.input_csv)
        known_terms = relevant_dynamic_terms(lines, dynamic_term_memory)
        payload = OrderedDict(
            [
                ("batch_id", f"{pass_label}-batch-{batch_number}"),
                ("target_language", args.target_language),
                ("note", "Lines are in extracted file order. Translate source_template; use visible_source and metadata only as aid."),
                ("translation_history", list(history)),
                ("known_translations", known_terms),
                ("lines", lines),
            ]
        )

        validation_hint = "none"
        success = False
        last_raw = ""
        last_errors = []
        file_stats[current_label]["started_at"] = file_stats[current_label].get("started_at") or time.perf_counter()

        for attempt in range(1, args.max_retries + 2):
            cycle_started = time.perf_counter()
            batch_status = f"{pass_label} batch {batch_number}/{len(batch_set)}, lines={len(lines)}, attempt={attempt}"
            progress.write(current_label, batch_status)
            sent_at = wait_for_rate_limit(args, progress, current_label, rate_state)
            progress.write(current_label, f"{batch_status} sending")
            started = time.perf_counter()
            request_seconds = 0.0
            try:
                response = invoke_mistral_batch(args, system_prompt, payload, validation_hint)
                request_seconds = time.perf_counter() - started
                last_raw = response_content(response)
            except Exception as exc:
                request_seconds = time.perf_counter() - started
                last_raw = ""
                last_errors = [f"api request failed: {exc}"]
                validation_hint = "; ".join(last_errors)
                reason = short_error_reason(exc)
                if reason == "rate limit":
                    delay = rate_limit_retry_delay_ms(args, rate_state, exc, sent_at, attempt)
                else:
                    delay = retry_delay_ms(args.retry_delay_ms, attempt)
                if attempt <= args.max_retries and delay > 0:
                    wait_retry(progress, delay, current_label, f"{reason} after {format_duration(request_seconds)}")
                else:
                    progress.write(current_label, f"{reason}; no retries left", newline=True)
                continue

            try:
                translations = parse_response_json(last_raw)
            except Exception as exc:
                last_errors = [f"response was not valid JSON: {exc}"]
                validation_hint = "; ".join(last_errors)
                progress.write(current_label, f"{short_error_reason(exc)}; retrying")
                continue

            by_id = {}
            for translation in translations:
                if isinstance(translation, dict) and translation.get("id") is not None:
                    by_id[str(translation["id"])] = translation

            errors = []
            if len(translations) != len(lines):
                errors.append(f"translation count mismatch: expected={len(lines)} got={len(translations)}")

            expected_ids = {str(line["id"]) for line in lines}
            for translation in translations:
                if isinstance(translation, dict) and translation.get("id") is not None and str(translation["id"]) not in expected_ids:
                    errors.append(f"unexpected id {translation['id']}")

            for line in lines:
                line_id = str(line["id"])
                translation = by_id.get(line_id)
                if translation is None:
                    errors.append(f"missing id {line_id}")
                    continue
                translated_text = normalize_translation_template(translation.get("translation_template", ""))
                translated_text = repair_missing_placeholders(str(line["source_template"]), translated_text, line.get("tokens", {}))
                translation["translation_template"] = translated_text
                if not translated_text.strip() and str(line.get("source_template", "")).strip():
                    errors.append(f"empty translation for id {line_id}")
                    continue
                memory_entry = translation_memory.get(line_memory_key(line, input_kind)) if is_strict_memory_line(line, input_kind) and translation_memory is not None else None
                if memory_entry and translated_text != memory_entry.get("translation_template", ""):
                    errors.append(
                        f"id {line_id}: translation memory mismatch: expected {memory_entry.get('translation_template', '')!r}"
                    )
                    continue
                ok, reason = validate_translation(str(line["source_template"]), translated_text, line.get("tokens", {}), term_locks)
                if not ok:
                    errors.append(f"id {line_id}: {reason}")
                    continue
                if is_strict_memory_line(line, input_kind):
                    ok, reason = validate_dynamic_terms(str(line["source_template"]), translated_text, dynamic_term_memory)
                    if not ok:
                        errors.append(f"id {line_id}: {reason}")

            if errors:
                last_errors = errors
                validation_hint = "; ".join(errors)
                progress.write(current_label, f"{short_error_reason(errors[0])}; retrying")
                continue

            usage = response_usage(response)
            usage_dict = usage_to_dict(usage)
            input_tokens, output_tokens = usage_token_pair(usage)
            request_id = f"{RUN_ID}-{payload['batch_id']}-attempt-{attempt}"
            rows_written = 0
            for line in lines:
                translation = by_id[str(line["id"])]
                remember_translation(translation_memory, line, translation, input_kind)
                remember_dynamic_term(dynamic_term_memory, line, translation, input_kind)
                history.append(
                    OrderedDict(
                        [
                            ("speaker", str(line.get("speaker", ""))),
                            ("source_template", str(line.get("source_template", ""))),
                            ("translation_template", str(translation.get("translation_template", ""))),
                        ]
                    )
                )
                job = jobs_by_id[str(line["id"])]
                for alias_row in job["rows"]:
                    alias_line = row_to_line(alias_row, input_kind)
                    alias_id = str(alias_line["id"])
                    if alias_id in done:
                        continue
                    entry = make_output_entry(alias_line, translation, args, payload["batch_id"], request_id, line["id"], usage_dict)
                    append_json_line(args.output_jsonl, entry)
                    done.add(alias_id)
                    progress.completed += 1
                    progress.file_completed[str(alias_line["file"])] += 1
                    rows_written += 1

            if request_seconds > 0:
                progress.completed_batches += 1
                progress.cycle_seconds_total += time.perf_counter() - cycle_started
            file_stats[current_label]["input_tokens"] += input_tokens
            file_stats[current_label]["output_tokens"] += output_tokens
            total_usage["input_tokens"] += input_tokens
            total_usage["output_tokens"] += output_tokens
            avg = progress.cycle_seconds_total / progress.completed_batches if progress.completed_batches else 0.0
            file_done = (
                current_label not in reported_files
                and progress.file_totals.get(current_label, 0) > 0
                and progress.file_completed.get(current_label, 0) >= progress.file_totals.get(current_label, 0)
            )
            done_status = f"done; last API {format_duration(request_seconds)}; avg cycle {format_duration(avg)}"
            if file_done:
                reported_files.add(current_label)
                elapsed = time.perf_counter() - file_stats[current_label].get("started_at", time.perf_counter())
                file_input = file_stats[current_label]["input_tokens"]
                file_output = file_stats[current_label]["output_tokens"]
                total_cost = calculate_cost(total_usage["input_tokens"], total_usage["output_tokens"], args)
                progress.print_result(result_line(current_label, file_input, file_output, elapsed, args, total_cost=total_cost, ok=True))
            else:
                progress.write(current_label, done_status)
            success = True
            break

        if not success:
            progress.finish_line()
            failed_entry = OrderedDict(
                [
                    ("batch_id", str(payload["batch_id"])),
                    ("pass", pass_label),
                    ("errors", last_errors),
                    ("lines", lines),
                    ("raw_response", last_raw),
                    ("failed_at_utc", utc_now()),
                ]
            )
            append_json_line(args.failed_jsonl, failed_entry)
            print(f"warning: {pass_label} batch {batch_number} failed; wrote {args.failed_jsonl}")
            if args.stop_on_failure:
                raise RuntimeError(f"stopping after failed {pass_label} batch {batch_number}")

        if args.sleep_ms > 0:
            time.sleep(args.sleep_ms / 1000.0)


def parse_args():
    parser = argparse.ArgumentParser(description="Translate WOLF RPG extracted text with Mistral.")
    parser.add_argument("--input-csv", default=str(DEFAULT_INPUT))
    parser.add_argument("--output-jsonl", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--failed-jsonl", default=str(DEFAULT_FAILED))
    parser.add_argument("--prompt-path", default=str(DEFAULT_PROMPT))
    parser.add_argument("--glossary-path", default=str(DEFAULT_GLOSSARY))
    parser.add_argument("--term-locks-path", default=str(DEFAULT_TERM_LOCKS), help="Optional manual JSON file of source terms that must translate to exact target strings.")
    parser.add_argument("--protected-identifiers-path", default=str(DEFAULT_PROTECTED_IDENTIFIERS), help="JSONL rows of runtime identifiers that must be left in the original text and skipped before API calls.")
    parser.add_argument("--api-key", default=os.environ.get("MISTRAL_API_KEY", ""))
    parser.add_argument("--endpoint", default="https://api.mistral.ai/v1", help="OpenAI-compatible base URL. Full /chat/completions URLs are also accepted.")
    parser.add_argument("--model", default="mistral-medium-3-5")
    parser.add_argument("--reasoning-effort", choices=["none", "high"], default="none")
    parser.add_argument("--target-language", default="English")
    parser.add_argument("--batch-size", type=int, default=12)
    parser.add_argument("--max-rows", type=int, default=0)
    parser.add_argument("--start-after-id", type=int, default=0)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--end-retry-rounds", type=int, default=5)
    parser.add_argument("--sleep-ms", type=int, default=1000)
    parser.add_argument("--retry-delay-ms", type=int, default=15000)
    parser.add_argument("--requests-per-minute", type=float, default=0.0, help="Optional RPM ceiling. A hard 1 request/second safety cap is always enforced.")
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--history-size", type=int, default=10)
    parser.add_argument("--temperature", type=float, default=0.15)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--input-cost-per-1m", type=float, default=None)
    parser.add_argument("--output-cost-per-1m", type=float, default=None)
    parser.add_argument("--map-only", action="store_true")
    parser.add_argument("--common-only", action="store_true")
    parser.add_argument("--no-dedupe", action="store_true")
    parser.add_argument("--no-translation-memory", action="store_true")
    parser.add_argument("--no-end-retry", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--stop-on-failure", action="store_true")
    return parser.parse_args()


def main():
    configure_console()
    run_started = time.perf_counter()
    args = parse_args()
    args.input_csv = str(Path(args.input_csv).resolve())
    args.output_jsonl = str(Path(args.output_jsonl).resolve())
    args.failed_jsonl = str(Path(args.failed_jsonl).resolve())
    args.prompt_path = str(Path(args.prompt_path).resolve())
    args.glossary_path = str(Path(args.glossary_path).resolve())
    if args.term_locks_path:
        args.term_locks_path = str(Path(args.term_locks_path).resolve())
    if args.protected_identifiers_path:
        args.protected_identifiers_path = str(Path(args.protected_identifiers_path).resolve())

    if not Path(args.input_csv).exists():
        raise FileNotFoundError(f"Input CSV not found: {args.input_csv}")
    if not Path(args.prompt_path).exists():
        raise FileNotFoundError(f"Prompt file not found: {args.prompt_path}")
    if not Path(args.glossary_path).exists():
        raise FileNotFoundError(f"Glossary file not found: {args.glossary_path}")
    if not args.dry_run and not args.api_key.strip():
        raise RuntimeError("MISTRAL_API_KEY is not set. Set it or pass --api-key.")
    if args.batch_size < 1:
        raise RuntimeError("batch-size must be at least 1")

    prompt = Path(args.prompt_path).read_text(encoding="utf-8").strip()
    glossary = Path(args.glossary_path).read_text(encoding="utf-8").strip()
    system_prompt = prompt + "\n\n" + glossary
    term_locks = load_term_locks(args.term_locks_path) if args.term_locks_path else []
    protected_identifiers = load_protected_identifiers(args.protected_identifiers_path) if args.protected_identifiers_path else {}

    rows, columns = read_input_rows(args.input_csv)
    if "dialogue_template" in columns:
        input_kind = "dialogue"
    elif "text" in columns:
        input_kind = "strings"
    else:
        raise RuntimeError(f"Input CSV is not recognized. Expected dialogue_template or text column: {args.input_csv}")

    rows = filter_rows(rows, input_kind, args)
    rows, protected_skipped = filter_protected_rows(rows, input_kind, protected_identifiers)
    done = set() if args.no_resume or args.dry_run else read_done_ids(args.output_jsonl)
    translation_memory = {}
    memory_conflicts = []
    memory_filled = 0
    if not args.no_translation_memory and not args.no_resume and not args.dry_run:
        translation_memory, memory_conflicts = read_translation_memory(args.output_jsonl, input_kind)
        memory_filled = apply_translation_memory(rows, input_kind, args, done, translation_memory)
    dynamic_term_memory = build_dynamic_term_memory(rows, input_kind, translation_memory) if not args.no_translation_memory else OrderedDict()
    pending = [row for row in rows if str(row.get("id", "")) not in done]
    jobs = new_translation_jobs(pending, input_kind, args.no_dedupe)
    batches = new_batches(jobs, args.batch_size)

    file_totals = Counter(str(row.get("file", "")) for row in rows)
    file_completed = Counter(str(row.get("file", "")) for row in rows if str(row.get("id", "")) in done)
    file_stats = defaultdict(lambda: {"input_tokens": 0, "output_tokens": 0, "started_at": None})
    previous_input, previous_output, previous_request_count = (0, 0, 0)
    if not args.no_resume and not args.dry_run:
        previous_input, previous_output, previous_request_count = read_output_usage_totals(args.output_jsonl)
    total_usage = {"input_tokens": previous_input, "output_tokens": previous_output}
    reported_files = {name for name, total in file_totals.items() if total > 0 and file_completed.get(name, 0) >= total}
    progress = Progress(
        total=len(rows),
        completed=sum(1 for row in rows if str(row.get("id", "")) in done),
        file_totals=file_totals,
        file_completed=file_completed,
        total_batches=len(batches),
    )
    initial_label = row_to_line(pending[0], input_kind)["file"] if pending else args.input_csv

    print(f"input rows: {len(rows)}")
    print(f"input kind: {input_kind}")
    if protected_skipped:
        print(f"protected runtime identifiers skipped: {protected_skipped}")
    print(f"pending rows: {len(pending)}")
    print(f"translation jobs: {len(jobs)}")
    if not args.no_dedupe:
        print(f"deduped rows saved: {len(pending) - len(jobs)}")
    print(f"batches: {len(batches)}")
    print(f"model: {args.model}")
    print(f"reasoning_effort: {args.reasoning_effort}")
    if term_locks:
        print(f"term locks: {len(term_locks)}")
    if not args.no_translation_memory:
        print(f"translation memory: {len(translation_memory)} entries")
        print(f"dynamic term memory: {len(dynamic_term_memory)} terms")
        if memory_filled:
            print(f"translation memory filled: {memory_filled} rows")
        if memory_conflicts:
            print(f"warning: translation memory conflicts: {len(memory_conflicts)} exact source strings already have multiple translations; using the most common existing translation.")
    in_price, out_price = model_prices(args)
    print(f"pricing: input ${in_price:g}/M, output ${out_price:g}/M")
    if args.requests_per_minute > 0:
        print(f"rate limit: {args.requests_per_minute:g} requests/minute sliding window, max 1 request/second")
    else:
        print("rate limit: max 1 request/second")
    if args.dry_run:
        preview_path = str(Path(args.output_jsonl).with_suffix(".dryrun.jsonl"))
        preview = Path(preview_path)
        if preview.exists():
            preview.unlink()
        for batch_index, batch_jobs in enumerate(batches, start=1):
            lines = [row_to_line(job["row"], input_kind) for job in batch_jobs]
            payload = OrderedDict(
                [
                    ("batch_id", f"batch-{batch_index}"),
                    ("target_language", args.target_language),
                    ("note", "Lines are in extracted file order. Translate source_template; use visible_source and metadata only as aid."),
                    ("translation_history", []),
                    ("lines", lines),
                ]
            )
            append_json_line(preview_path, payload)
        print(f"dry-run batches written: {preview_path}")
        return 0

    history = deque(read_translation_history(args.output_jsonl, args.history_size), maxlen=max(0, args.history_size))
    if history:
        print(f"loaded translation history: {len(history)}")
    if previous_input > 0 or previous_output > 0:
        print(
            "loaded previous cost: "
            f"[Input: {previous_input}]"
            f"[Output: {previous_output}]"
            f"[Cost: ${calculate_cost(previous_input, previous_output, args):,.4f}]"
            f"[Requests: {previous_request_count}]"
        )

    progress.write(str(initial_label), "starting")
    rate_state = {"request_times": deque(), "last_request_at": None}

    pass_number = 1
    run_batch_set(batches, f"pass-{pass_number}", args, input_kind, system_prompt, history, done, progress, file_stats, reported_files, rate_state, total_usage, term_locks, translation_memory, dynamic_term_memory)

    while not args.no_end_retry and pass_number <= args.end_retry_rounds:
        remaining_rows = [row for row in rows if str(row.get("id", "")) not in done]
        if not remaining_rows:
            break
        pass_number += 1
        retry_jobs = new_translation_jobs(remaining_rows, input_kind, args.no_dedupe)
        retry_batches = new_batches(retry_jobs, args.batch_size)
        progress.total_batches += len(retry_batches)
        progress.finish_line()
        print(f"warning: retry pass {pass_number} starting for {len(remaining_rows)} untranslated rows in {len(retry_batches)} batches")
        if args.retry_delay_ms > 0:
            time.sleep(args.retry_delay_ms / 1000.0)
        run_batch_set(retry_batches, f"pass-{pass_number}", args, input_kind, system_prompt, history, done, progress, file_stats, reported_files, rate_state, total_usage, term_locks, translation_memory, dynamic_term_memory)

    remaining_rows = [row for row in rows if str(row.get("id", "")) not in done]
    progress.finish_line()
    if remaining_rows:
        print(f"warning: unfinished rows: {len(remaining_rows)}. They remain absent from {args.output_jsonl} and will be retried first on the next run.")
    else:
        print("all requested rows translated")
    session_seconds = time.perf_counter() - run_started
    total_input, total_output, request_count = read_output_usage_totals(args.output_jsonl)
    if total_input <= 0 and total_output <= 0:
        total_input = sum(s["input_tokens"] for s in file_stats.values())
        total_output = sum(s["output_tokens"] for s in file_stats.values())
    total_label = "TOTAL TL" if not remaining_rows else "TOTAL SO FAR"
    print(total_translation_line(total_label, total_input, total_output, session_seconds, args, request_count=request_count))
    print(f"done: {args.output_jsonl}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\ninterrupted; rerun the same command to resume")
        raise SystemExit(130)
