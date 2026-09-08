#!/usr/bin/env python3
"""Mistral live translator for this Unity/Utage visual novel.

This uses normal /v1/chat/completions requests, not the Mistral Batch API.
Scene-grouped Utage dialogue is still kept together so each request has useful
context for dialogue, narration, and choices.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, deque
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parents[1]
OUT_DIR = SCRIPT_DIR / "out"

DEFAULT_INPUT = ROOT_DIR / "tooling" / "utage_dialogue_scenes.json"
DEFAULT_OUTPUT = OUT_DIR / "utage_translations.jsonl"
DEFAULT_FAILED = OUT_DIR / "utage_translations.failed.jsonl"
DEFAULT_MERGED = OUT_DIR / "utage_dialogue_scenes.mistral.en.json"
DEFAULT_DRYRUN = OUT_DIR / "utage_live_preview.jsonl"
DEFAULT_PROMPT = SCRIPT_DIR / "prompt.md"
DEFAULT_GLOSSARY = SCRIPT_DIR / "glossary.md"

CHAT_ENDPOINT = "/v1/chat/completions"
CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff\uff66-\uff9f]")
RICH_TEXT_TAG_RE = re.compile(r"</?[A-Za-z][^<>]*?>")
FORMAT_TOKEN_RE = re.compile(
    r"("
    r"\\[nrt]"
    r"|\\u[0-9A-Fa-f]{4}"
    r"|%[+\-#0 ]?(?:\d+|\*)?(?:\.\d+)?[bcdeEfFgGosxX]"
    r"|\{[A-Za-z0-9_][A-Za-z0-9_.:\-]*\}"
    r"|\[[A-Za-z][A-Za-z0-9_]*(?:=[^\]]*)?\]"
    r")"
)
RUN_ID = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


class MistralApiError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


def configure_console() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_json_line(path: Path, item: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")


def has_japanese(text: str) -> bool:
    return bool(CJK_RE.search(str(text or "")))


def strip_protected_for_cjk_check(text: str) -> str:
    text = RICH_TEXT_TAG_RE.sub("", str(text or ""))
    text = FORMAT_TOKEN_RE.sub("", text)
    return text


def protected_tokens(text: str) -> list[str]:
    text = str(text or "")
    return RICH_TEXT_TAG_RE.findall(text) + FORMAT_TOKEN_RE.findall(text)


def token_counts(text: str) -> Counter[str]:
    return Counter(protected_tokens(text))


def read_done_ids(path: Path) -> set[str]:
    done: set[str] = set()
    if not path.exists():
        return done
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            entry_id = str(item.get("id", ""))
            if entry_id and str(item.get("translation", "")).strip():
                done.add(entry_id)
    return done


def read_translation_map(path: Path) -> dict[str, dict[str, Any]]:
    translations: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return translations
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            entry_id = str(item.get("id", ""))
            if entry_id:
                translations[entry_id] = item
    return translations


def categories_for_entry(entry: dict[str, Any]) -> list[str]:
    values: list[str] = []
    raw = entry.get("categories", [])
    if isinstance(raw, str):
        values.append(raw)
    elif isinstance(raw, list):
        values.extend(str(item) for item in raw if str(item).strip())
    for key in ("category", "kind", "type"):
        value = str(entry.get(key, "") or "").strip()
        if value and value not in values:
            values.append(value)
    return values


def speaker_value(entry: dict[str, Any]) -> str:
    speaker = entry.get("speaker", "")
    if isinstance(speaker, dict):
        return str(
            speaker.get("speaker")
            or speaker.get("name")
            or speaker.get("source")
            or speaker.get("text")
            or ""
        )
    return str(speaker or entry.get("speaker_source", "") or "")


def source_text_for_entry(entry: dict[str, Any]) -> str:
    for key in ("text", "source_template", "source_text", "llm_text", "value"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def llm_text_for_entry(entry: dict[str, Any]) -> str:
    explicit = str(entry.get("llm_text", "") or "").strip()
    if explicit:
        return explicit
    text = source_text_for_entry(entry)
    speaker = speaker_value(entry)
    kind = str(entry.get("type", entry.get("kind", "")) or "")
    if speaker and kind == "dialogue":
        return f"{speaker}: {text}"
    if kind == "choice":
        return f"[Choice] {text}"
    if kind == "narration":
        return f"[Narration] {text}"
    return text


def normalized_entry(entry: dict[str, Any], fallback_id: str, *, default_kind: str) -> dict[str, Any]:
    text = source_text_for_entry(entry)
    entry_id = str(entry.get("id", "") or entry.get("uid", "") or fallback_id)
    kind = str(entry.get("type", "") or entry.get("kind", "") or entry.get("category", "") or default_kind)
    occurrences = entry.get("occurrences", [])
    first_occurrence = occurrences[0] if isinstance(occurrences, list) and occurrences else {}
    source = str(
        entry.get("source", "")
        or entry.get("source_file", "")
        or first_occurrence.get("source", "")
        or entry.get("sheet", "")
        or ""
    )
    return {
        "id": entry_id,
        "kind": kind,
        "type": kind,
        "speaker": speaker_value(entry),
        "source_text": text,
        "llm_text": llm_text_for_entry(entry),
        "translation": str(entry.get("translation", "") or ""),
        "notes": str(entry.get("notes", "") or ""),
        "context": str(entry.get("context", "") or ""),
        "categories": categories_for_entry(entry),
        "keys": entry.get("keys", []),
        "source": source,
        "row_index": entry.get("row_index", entry.get("row", entry.get("line", None))),
        "voice": entry.get("voice", ""),
        "raw": entry,
    }


def scene_unit(scene: dict[str, Any], scene_index: int) -> dict[str, Any] | None:
    scene_id = str(scene.get("id", "") or f"scene_{scene_index:05d}")
    entries = []
    for entry_index, entry in enumerate(scene.get("entries", []), start=1):
        if not isinstance(entry, dict):
            continue
        normalized = normalized_entry(
            entry,
            f"{scene_id}_{entry_index:04d}",
            default_kind=str(entry.get("type", "dialogue") or "dialogue"),
        )
        if normalized["source_text"].strip():
            entries.append(normalized)
    if not entries:
        return None
    return {
        "unit_id": scene_id,
        "kind": "utage_scene",
        "scene": {
            "id": scene_id,
            "workbook": scene.get("workbook", ""),
            "sheet": scene.get("sheet", ""),
            "label": scene.get("label", ""),
            "speakers": scene.get("speakers", []),
            "type_counts": scene.get("type_counts", {}),
        },
        "entries": entries,
    }


def group_record_units(records: list[dict[str, Any]], *, group_size: int) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            continue
        normalized = normalized_entry(record, f"record_{index:05d}", default_kind="ui_text")
        if not normalized["source_text"].strip():
            continue
        group_key = str(
            record.get("scene_id", "")
            or record.get("scene", "")
            or record.get("category", "")
            or (record.get("categories", ["text"])[0] if isinstance(record.get("categories"), list) and record.get("categories") else "")
            or record.get("source_kind", "")
            or record.get("source", "")
            or "records"
        )
        buckets.setdefault(group_key, []).append(normalized)

    units: list[dict[str, Any]] = []
    unit_no = 1
    for group_key, entries in buckets.items():
        for chunk_start in range(0, len(entries), max(1, group_size)):
            chunk = entries[chunk_start : chunk_start + max(1, group_size)]
            units.append(
                {
                    "unit_id": f"records_{unit_no:05d}_{group_key}",
                    "kind": "record_chunk",
                    "scene": {
                        "id": str(group_key),
                        "workbook": "",
                        "sheet": "",
                        "label": str(group_key),
                        "speakers": sorted({e["speaker"] for e in chunk if e.get("speaker")}),
                        "type_counts": dict(Counter(e["kind"] for e in chunk)),
                    },
                    "entries": chunk,
                }
            )
            unit_no += 1
    return units


def detect_input_type(data: Any, requested: str) -> str:
    if requested != "auto":
        return requested
    if isinstance(data, dict) and isinstance(data.get("scenes"), list):
        return "utage-scenes"
    if isinstance(data, dict) and isinstance(data.get("records"), list):
        return "records"
    if isinstance(data, dict) and isinstance(data.get("entries"), list):
        return "records"
    raise RuntimeError("Could not detect input type. Use --input-type.")


def load_units(input_path: Path, args) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    data = json.loads(input_path.read_text(encoding="utf-8"))
    input_type = detect_input_type(data, args.input_type)
    if input_type == "utage-scenes":
        units = [
            unit
            for index, scene in enumerate(data.get("scenes", []), start=1)
            if isinstance(scene, dict)
            for unit in [scene_unit(scene, index)]
            if unit
        ]
        return data, units, input_type
    if input_type in {"records", "utage-flat", "non-dialogue"}:
        records = data.get("records")
        if not isinstance(records, list):
            records = data.get("entries")
        if not isinstance(records, list):
            raise RuntimeError(f"Input JSON has no records/entries list: {input_path}")
        return data, group_record_units(records, group_size=args.batch_size), input_type
    raise RuntimeError(f"Unsupported input type: {input_type}")


def entry_matches_filters(entry: dict[str, Any], args) -> bool:
    kinds = {part.strip() for value in args.kind for part in str(value).split(",") if part.strip()}
    categories = {part.strip() for value in args.category for part in str(value).split(",") if part.strip()}
    entry_categories = set(categories_for_entry(entry))
    if kinds and str(entry.get("kind", "")) not in kinds and not (entry_categories & kinds):
        return False
    if categories and not (entry_categories & categories):
        return False
    if args.only_empty and str(entry.get("translation", "")).strip():
        return False
    if args.source_contains and args.source_contains not in str(entry.get("source", "")):
        return False
    return True


def split_units(units: list[dict[str, Any]], args) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    max_lines = max(1, int(args.max_lines_per_request))
    max_chars = max(1000, int(args.max_chars_per_request))
    for unit in units:
        entries = list(unit["entries"])
        chunks: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        current_chars = 0
        for entry in entries:
            entry_chars = len(str(entry.get("llm_text", ""))) + len(str(entry.get("source_text", ""))) + 80
            if current and (len(current) >= max_lines or current_chars + entry_chars > max_chars):
                chunks.append(current)
                current = []
                current_chars = 0
            current.append(entry)
            current_chars += entry_chars
        if current:
            chunks.append(current)

        for chunk_index, chunk in enumerate(chunks, start=1):
            item = dict(unit)
            item["entries"] = chunk
            item["chunk"] = {
                "index": chunk_index,
                "count": len(chunks),
                "source_entry_count": len(entries),
            }
            if len(chunks) > 1:
                item["unit_id"] = f"{unit['unit_id']}_part{chunk_index:03d}"
                start_index = entries.index(chunk[0])
                end_index = entries.index(chunk[-1]) + 1
                before = entries[max(0, start_index - args.context_overlap) : start_index]
                after = entries[end_index : end_index + args.context_overlap]
                item["context_before"] = [e["llm_text"] for e in before]
                item["context_after"] = [e["llm_text"] for e in after]
            result.append(item)
    return result


def filter_units(units: list[dict[str, Any]], done_ids: set[str], args) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    after_seen = not bool(args.start_after_id)
    total_rows = 0
    for unit in units:
        kept_entries = []
        for entry in unit["entries"]:
            entry_id = str(entry.get("id", ""))
            if not after_seen:
                if entry_id == args.start_after_id:
                    after_seen = True
                continue
            if not args.no_resume and entry_id in done_ids:
                continue
            if not entry_matches_filters(entry, args):
                continue
            kept_entries.append(entry)
            total_rows += 1
            if args.max_rows and total_rows >= args.max_rows:
                break
        if kept_entries:
            item = dict(unit)
            item["entries"] = kept_entries
            filtered.append(item)
            if args.max_units and len(filtered) >= args.max_units:
                break
        if args.max_rows and total_rows >= args.max_rows:
            break
    return split_units(filtered, args)


def load_system_prompt(prompt_path: Path, glossary_path: Path) -> str:
    prompt = prompt_path.read_text(encoding="utf-8").strip()
    glossary = glossary_path.read_text(encoding="utf-8").strip()
    return f"{prompt}\n\n# Project Glossary\n{glossary}".strip()


def line_payload(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": entry["id"],
        "type": entry["kind"],
        "speaker": entry.get("speaker", ""),
        "text": entry["source_text"],
        "context_line": entry.get("llm_text", entry["source_text"]),
        "source": entry.get("source", ""),
        "context": entry.get("context", ""),
        "row_index": entry.get("row_index"),
        "voice": entry.get("voice", ""),
        "categories": entry.get("categories", []),
        "keys": entry.get("keys", []),
        "notes": entry.get("notes", ""),
    }


def build_payload(args, unit: dict[str, Any], validation_hint: str = "") -> dict[str, Any]:
    payload = {
        "request_id": unit["unit_id"],
        "project": "Unity IL2CPP visual novel using Utage",
        "target_language": args.target_language,
        "input_kind": unit["kind"],
        "scene": unit.get("scene", {}),
        "chunk": unit.get("chunk", {"index": 1, "count": 1, "source_entry_count": len(unit["entries"])}),
        "context_before": unit.get("context_before", []),
        "context_after": unit.get("context_after", []),
        "lines": [line_payload(entry) for entry in unit["entries"]],
    }
    if validation_hint:
        payload["validation_hint"] = validation_hint
    return payload


def build_user_prompt(payload: dict[str, Any]) -> str:
    return (
        "Translate the following Unity/Utage payload into English.\n"
        "Return one JSON object only, with this exact shape:\n"
        '{"translations":[{"id":"line id","translation":"English text",'
        '"translation_speaker":"English speaker name or empty","notes":""}]}\n'
        "Return every input line exactly once, in the same order. Do not add prose.\n\n"
        "SOURCE_PAYLOAD_JSON:\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def build_chat_body(args, system_prompt: str, unit: dict[str, Any], validation_hint: str = "") -> dict[str, Any]:
    payload = build_payload(args, unit, validation_hint)
    body: dict[str, Any] = {
        "model": args.model,
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": build_user_prompt(payload)},
        ],
    }
    if args.reasoning_effort != "none":
        body["reasoning_effort"] = args.reasoning_effort
    return body


def parse_translator_json(raw: str) -> list[dict[str, Any]]:
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    parsed = json.loads(text)
    translations = parsed if isinstance(parsed, list) else parsed.get("translations")
    if not isinstance(translations, list):
        raise ValueError("response JSON missing translations array")
    return [item for item in translations if isinstance(item, dict)]


def punctuation_warnings(source: str, translation: str) -> list[str]:
    warnings: list[str] = []
    source = str(source or "").strip()
    translation = str(translation or "").strip()
    if not source or not translation:
        return warnings
    ending_map = {
        "？": ("?", "?!", "!?"),
        "！": ("!", "?!", "!?"),
        "。": (".", "!", "?", '"', "'"),
        "…": ("...", "…", ".", "!", "?", '"', "'"),
    }
    for jp, allowed in ending_map.items():
        if source.endswith(jp) and not translation.endswith(allowed):
            warnings.append(f"source ended with {jp}; check ending punctuation")
            break
    return warnings


def validate_one(entry: dict[str, Any], translated: dict[str, Any], args) -> tuple[dict[str, Any], list[str], list[str]]:
    source = str(entry.get("source_text", "") or "")
    translation = str(translated.get("translation", "") or "").strip()
    warnings: list[str] = []
    errors: list[str] = []
    if not translation:
        errors.append("empty translation")

    source_counts = token_counts(source)
    target_counts = token_counts(translation)
    if source_counts != target_counts:
        missing = source_counts - target_counts
        extra = target_counts - source_counts
        if missing:
            errors.append(f"missing protected tokens: {dict(missing)}")
        if extra:
            warnings.append(f"extra protected tokens: {dict(extra)}")

    if not args.no_cjk_check and has_japanese(strip_protected_for_cjk_check(translation)):
        warnings.append("translation still contains Japanese/CJK characters")
    warnings.extend(punctuation_warnings(source, translation))

    output = {
        "id": str(entry.get("id", "")),
        "type": entry.get("kind", ""),
        "speaker": entry.get("speaker", ""),
        "translation_speaker": str(translated.get("translation_speaker", "") or "").strip(),
        "source_text": source,
        "source_context_line": entry.get("llm_text", source),
        "translation": translation,
        "notes": str(translated.get("notes", "") or "").strip(),
        "source": entry.get("source", ""),
        "row_index": entry.get("row_index"),
        "model": args.model,
        "run_id": RUN_ID,
        "created_at": now_iso(),
        "warnings": warnings,
    }
    return output, warnings, errors


def validate_translations(unit: dict[str, Any], translations: list[dict[str, Any]], args) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    expected_entries = list(unit.get("entries", []))
    expected_by_id = {str(entry["id"]): entry for entry in expected_entries}
    outputs: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    if len(translations) == len(expected_entries):
        for index, item in enumerate(translations):
            if str(item.get("id", "")) not in expected_by_id:
                item["id"] = expected_entries[index]["id"]

    seen: set[str] = set()
    for item in translations:
        entry_id = str(item.get("id", ""))
        entry = expected_by_id.get(entry_id)
        if not entry:
            failures.append({"id": entry_id, "error": "unexpected or missing id", "raw": item})
            continue
        seen.add(entry_id)
        output, warnings, errors = validate_one(entry, item, args)
        output["unit_id"] = unit["unit_id"]
        output["scene"] = unit.get("scene", {})
        if errors:
            failures.append({"id": entry_id, "error": "; ".join(errors), "warnings": warnings, "output": output})
            if not args.strict_validation:
                outputs.append(output)
        else:
            outputs.append(output)

    for entry in expected_entries:
        if str(entry["id"]) not in seen:
            failures.append({"id": entry["id"], "error": "missing translation in model response"})
    return outputs, failures


def response_content_from_chat(body: dict[str, Any]) -> str:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("chat response missing choices")
    message = choices[0].get("message", {})
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False)


def api_url(args, path: str) -> str:
    base = str(args.api_base or "https://api.mistral.ai").rstrip("/")
    if path.startswith("/v1/"):
        if base.endswith("/v1"):
            return base[:-3] + path
        return base + path
    return base + "/" + path.lstrip("/")


def post_chat(args, body: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {args.api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    request = urllib.request.Request(api_url(args, CHAT_ENDPOINT), data=data, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=args.timeout_seconds) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        raise MistralApiError(f"HTTP {exc.code} from Mistral API: {body_text[:800]}", status=exc.code, body=body_text) from exc
    except urllib.error.URLError as exc:
        raise MistralApiError(f"Mistral API connection error: {exc}") from exc


def retry_delay(args, attempt: int, exc: BaseException) -> float:
    if isinstance(exc, MistralApiError) and exc.status == 429:
        return max(float(args.retry_delay_ms) / 1000.0, float(args.rate_limit_sleep_seconds))
    return min(float(args.retry_delay_ms) / 1000.0 * (2 ** max(0, attempt - 1)), 300.0)


def wait_for_rate_limit(args, request_times: deque[float]) -> None:
    if args.requests_per_minute <= 0:
        return
    now = time.time()
    while request_times and now - request_times[0] >= 60:
        request_times.popleft()
    if len(request_times) < args.requests_per_minute:
        return
    wait = 60 - (now - request_times[0]) + 0.25
    print(f"rate limit wait: {wait:.1f}s")
    time.sleep(max(0.0, wait))


def translate_unit(args, system_prompt: str, unit: dict[str, Any], request_times: deque[float]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    validation_hint = ""
    for attempt in range(1, args.max_retries + 1):
        try:
            body = build_chat_body(args, system_prompt, unit, validation_hint)
            wait_for_rate_limit(args, request_times)
            response_body = post_chat(args, body)
            request_times.append(time.time())
            translations = parse_translator_json(response_content_from_chat(response_body))
            outputs, failures = validate_translations(unit, translations, args)
            if failures and args.strict_validation:
                validation_hint = "; ".join(str(f.get("error", "")) for f in failures[:5])
                raise ValueError(validation_hint)
            return outputs, failures, response_body.get("usage", {})
        except Exception as exc:
            if attempt >= args.max_retries:
                raise
            delay = retry_delay(args, attempt, exc)
            print(f"{unit['unit_id']}: retry {attempt}/{args.max_retries} after {delay:.1f}s: {exc}")
            time.sleep(delay)
    raise RuntimeError("unreachable retry loop exit")


def write_dryrun(path: Path, units: list[dict[str, Any]], args, system_prompt: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for unit in units:
            item = {
                "unit_id": unit["unit_id"],
                "entry_ids": [entry["id"] for entry in unit["entries"]],
                "scene": unit.get("scene", {}),
                "chat_body": build_chat_body(args, system_prompt, unit),
            }
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def run_translation(args, units: list[dict[str, Any]], system_prompt: str) -> tuple[int, int]:
    output_path = Path(args.output_jsonl)
    failed_path = Path(args.failed_jsonl)
    request_times: deque[float] = deque()
    translated_count = 0
    failed_count = 0
    for index, unit in enumerate(units, start=1):
        print(f"request {index}/{len(units)}: {unit['unit_id']} ({len(unit['entries'])} lines)")
        try:
            outputs, failures, usage = translate_unit(args, system_prompt, unit, request_times)
            for output in outputs:
                output["usage"] = usage
                append_json_line(output_path, output)
                translated_count += 1
            for failure in failures:
                failure["unit_id"] = unit["unit_id"]
                append_json_line(failed_path, failure)
                failed_count += 1
        except Exception as exc:
            failed_count += len(unit.get("entries", [])) or 1
            append_json_line(
                failed_path,
                {
                    "unit_id": unit["unit_id"],
                    "ids": [entry["id"] for entry in unit.get("entries", [])],
                    "error": str(exc),
                    "created_at": now_iso(),
                },
            )
            print(f"{unit['unit_id']}: failed: {exc}")
            if args.stop_on_failure:
                raise
        if args.live_sleep_seconds > 0:
            time.sleep(args.live_sleep_seconds)
    return translated_count, failed_count


def merge_translations(input_data: dict[str, Any], output_jsonl: Path, merged_json: Path) -> None:
    translations = read_translation_map(output_jsonl)
    merged = deepcopy(input_data)
    translated_count = 0

    if isinstance(merged.get("scenes"), list):
        for scene in merged["scenes"]:
            for entry in scene.get("entries", []):
                translated = translations.get(str(entry.get("id", "")))
                if not translated:
                    continue
                entry["translation"] = translated.get("translation", "")
                entry["translation_speaker"] = translated.get("translation_speaker", "")
                entry["translator_notes"] = translated.get("notes", "")
                entry["translation_warnings"] = translated.get("warnings", [])
                entry["translation_model"] = translated.get("model", "")
                translated_count += 1
        merged.setdefault("meta", {})
        merged["meta"]["translated_count"] = translated_count
        merged["meta"]["translation_output_jsonl"] = str(output_jsonl)
        write_json(merged_json, merged)
        return

    records_key = "records" if isinstance(merged.get("records"), list) else "entries"
    if isinstance(merged.get(records_key), list):
        for entry in merged[records_key]:
            translated = translations.get(str(entry.get("id", "")))
            if not translated:
                continue
            entry["translation"] = translated.get("translation", "")
            entry["translator_notes"] = translated.get("notes", "")
            entry["translation_warnings"] = translated.get("warnings", [])
            entry["translation_model"] = translated.get("model", "")
            translated_count += 1
    merged.setdefault("meta", {})
    merged["meta"]["translated_count"] = translated_count
    merged["meta"]["translation_output_jsonl"] = str(output_jsonl)
    write_json(merged_json, merged)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-json", default=str(DEFAULT_INPUT))
    parser.add_argument("--input-type", choices=["auto", "utage-scenes", "utage-flat", "records", "non-dialogue"], default="auto")
    parser.add_argument("--output-jsonl", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--failed-jsonl", default=str(DEFAULT_FAILED))
    parser.add_argument("--merged-json", default=str(DEFAULT_MERGED))
    parser.add_argument("--dryrun-jsonl", default=str(DEFAULT_DRYRUN))
    parser.add_argument("--prompt-path", default=str(DEFAULT_PROMPT))
    parser.add_argument("--glossary-path", default=str(DEFAULT_GLOSSARY))
    parser.add_argument("--api-key", default=os.environ.get("MISTRAL_API_KEY", ""))
    parser.add_argument("--api-base", default="https://api.mistral.ai")
    parser.add_argument("--model", default="mistral-medium-3-5")
    parser.add_argument("--target-language", default="English")
    parser.add_argument("--temperature", type=float, default=0.15)
    parser.add_argument("--max-tokens", type=int, default=16384)
    parser.add_argument("--reasoning-effort", choices=["none", "high"], default="none")
    parser.add_argument("--batch-size", type=int, default=40, help="Records per request for non-scene inputs.")
    parser.add_argument("--max-lines-per-request", type=int, default=90)
    parser.add_argument("--max-chars-per-request", type=int, default=36000)
    parser.add_argument("--context-overlap", type=int, default=6)
    parser.add_argument("--max-rows", type=int, default=0)
    parser.add_argument("--max-units", type=int, default=0)
    parser.add_argument("--start-after-id", default="")
    parser.add_argument("--kind", action="append", default=[])
    parser.add_argument("--category", action="append", default=[])
    parser.add_argument("--source-contains", default="")
    parser.add_argument("--only-empty", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--merge-only", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--live-sleep-seconds", type=float, default=1.0)
    parser.add_argument("--requests-per-minute", type=float, default=0.0)
    parser.add_argument("--rate-limit-sleep-seconds", type=float, default=30.0)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--retry-delay-ms", type=int, default=15000)
    parser.add_argument("--no-cjk-check", action="store_true")
    parser.add_argument("--strict-validation", action="store_true")
    parser.add_argument("--stop-on-failure", action="store_true")
    return parser.parse_args()


def resolve_paths(args) -> None:
    for attr in (
        "input_json",
        "output_jsonl",
        "failed_jsonl",
        "merged_json",
        "dryrun_jsonl",
        "prompt_path",
        "glossary_path",
    ):
        setattr(args, attr, str(Path(getattr(args, attr)).resolve()))


def print_plan(input_type: str, all_units: list[dict[str, Any]], pending_units: list[dict[str, Any]], done_ids: set[str], args) -> None:
    all_lines = sum(len(unit["entries"]) for unit in all_units)
    pending_lines = sum(len(unit["entries"]) for unit in pending_units)
    print(f"input type: {input_type}")
    print(f"all units: {len(all_units)}")
    print(f"all lines: {all_lines}")
    print(f"already translated lines: {len(done_ids)}")
    print(f"pending units: {len(pending_units)}")
    print(f"pending lines: {pending_lines}")
    print(f"model: {args.model}")
    if args.requests_per_minute > 0:
        print(f"rate limit: {args.requests_per_minute:g} requests/minute")
    print(f"sleep between requests: {args.live_sleep_seconds:g}s")


def main() -> int:
    configure_console()
    args = parse_args()
    resolve_paths(args)

    input_path = Path(args.input_json)
    output_path = Path(args.output_jsonl)
    failed_path = Path(args.failed_jsonl)
    merged_path = Path(args.merged_json)
    dryrun_path = Path(args.dryrun_jsonl)
    prompt_path = Path(args.prompt_path)
    glossary_path = Path(args.glossary_path)

    if not input_path.exists():
        raise FileNotFoundError(f"Input JSON not found: {input_path}")
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    if not glossary_path.exists():
        raise FileNotFoundError(f"Glossary file not found: {glossary_path}")

    input_data, base_units, input_type = load_units(input_path, args)
    all_units = split_units(base_units, args)
    done_ids = set() if args.no_resume else read_done_ids(output_path)
    pending_units = filter_units(base_units, done_ids, args)
    system_prompt = load_system_prompt(prompt_path, glossary_path)
    print_plan(input_type, all_units, pending_units, done_ids, args)

    if args.merge_only:
        merge_translations(input_data, output_path, merged_path)
        print(f"wrote merged JSON: {merged_path}")
        return 0

    if args.dry_run:
        write_dryrun(dryrun_path, pending_units, args, system_prompt)
        print(f"wrote dry-run preview: {dryrun_path}")
        return 0

    if not pending_units:
        merge_translations(input_data, output_path, merged_path)
        print(f"wrote merged JSON: {merged_path}")
        return 0

    if not args.api_key.strip():
        raise RuntimeError("MISTRAL_API_KEY is not set. Set it or pass --api-key.")

    translated, failed = run_translation(args, pending_units, system_prompt)
    print(f"translated lines this run: {translated}; failures: {failed}")
    merge_translations(input_data, output_path, merged_path)
    print(f"wrote JSONL translations: {output_path}")
    print(f"wrote merged JSON: {merged_path}")
    if failed_path.exists():
        print(f"failure log: {failed_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
