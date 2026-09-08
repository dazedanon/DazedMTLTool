#!/usr/bin/env python3
"""Extract and inject Goborin Tyrano/KAG text for translation.

The exporter deliberately separates:

* dialogue/story text: Dazed Text-style speaker context, with a speaker glossary
  first and then "[Speaker]: line" / "[Narration]: line" records. KAG tags stay
  in the exported line so translators can preserve or reposition them.
* menu/other text: plain one-line strings from UI tags, config strings, item
  names, choices, and non-chapter scenario text.

Injection is manifest-driven and writes patched copies by default. Use
``--replace`` only when you want to modify the unpacked ASAR data in place; it
creates a timestamped backup of every touched source file first.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


WORKSPACE = Path(__file__).resolve().parents[1]
DEFAULT_DATA_ROOT = WORKSPACE / "unpacked_asar" / "data"
DEFAULT_OUT_DIR = WORKSPACE / "text_translation"
DEFAULT_DIALOGUE_TXT = DEFAULT_OUT_DIR / "dialogue.txt"
DEFAULT_MENU_TXT = DEFAULT_OUT_DIR / "menu.txt"
DEFAULT_DIALOGUE_MANIFEST = DEFAULT_OUT_DIR / "dialogue_manifest.jsonl"
DEFAULT_MENU_MANIFEST = DEFAULT_OUT_DIR / "menu_manifest.jsonl"
DEFAULT_INVENTORY_CSV = DEFAULT_OUT_DIR / "text_inventory.csv"
DEFAULT_PATCHED_DATA = WORKSPACE / "patched_data"
BACKUP_ROOT = WORKSPACE / "backups"

JP_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uff61-\uff9f]")
TAG_RE = re.compile(r"\[[^\]\r\n]*\]")
BRACKET_LINE_RE = re.compile(r"^\s*\[(?P<speaker>[^\]\r\n]{1,120})\]\s*[:：]\s*(?P<text>.*)$")
WRAP_MARKER_RE = re.compile(r"\\[nN]|<br\s*/?>", re.IGNORECASE)
ATTR_RE = re.compile(
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*"
    r"(?:\"(?P<dval>[^\"]*)\"|'(?P<sval>[^']*)'|(?P<uval>[^\s\]]+))"
)

PREFIX_TAGS = {"fv", "font"}
SUFFIX_TAGS = {"p", "pv", "r", "l", "font"}
NARRATION_CONTEXT = "Narration"

KS_TAG_ATTRS: dict[str, set[str]] = {
    "button": {"hint"},
    "chapter": {"title"},
    "chara_new": {"jname"},
    "dialog": {"text", "label_ok", "label_cancel"},
    "dialog_config_ng": {"text"},
    "dialog_config_ok": {"text"},
    "glink": {"text"},
    "item_get": {"name"},
    "ptext": {"text"},
    "title": {"name"},
}


@dataclass
class TextRecord:
    order: int
    bucket: str
    record_type: str
    file: str
    line_index: int
    kind: str
    source: str
    export_text: str
    speaker: str | None = None
    speaker_line_index: int | None = None
    mode: str = "line"
    start: int | None = None
    end: int | None = None
    prefix: str = ""
    suffix: str = ""
    leading_ws: str = ""
    trailing_ws: str = ""
    tag: str | None = None
    attr: str | None = None


def has_japanese(text: str) -> bool:
    return bool(JP_RE.search(text or ""))


def is_translatable_speaker(text: str | None) -> bool:
    return bool(text) and not (text or "").isascii()


def one_line(text: str) -> str:
    return (text or "").replace("\r", " ").replace("\n", " ").strip()


def export_line(text: str) -> str:
    return (text or "").replace("\r", " ").replace("\n", r"\n")


def line_body_newline(line: str) -> tuple[str, str]:
    body = line.rstrip("\r\n")
    return body, line[len(body) :]


def split_edge_ws(text: str) -> tuple[str, str, str]:
    leading_len = len(text) - len(text.lstrip(" \t\u3000"))
    trailing_len = len(text) - len(text.rstrip(" \t\u3000"))
    leading = text[:leading_len]
    trailing = text[len(text) - trailing_len :] if trailing_len else ""
    core_end = len(text) - trailing_len if trailing_len else len(text)
    return leading, text[leading_len:core_end], trailing


def tag_name(tag: str) -> str:
    inner = tag[1:-1].strip()
    if not inner:
        return ""
    return inner.split(None, 1)[0].lower()


def split_outer_tags(text: str) -> tuple[str, str, str]:
    prefix = ""
    body = text
    while body.startswith("["):
        end = body.find("]")
        if end < 0:
            break
        tag = body[: end + 1]
        if tag_name(tag) not in PREFIX_TAGS:
            break
        prefix += tag
        body = body[end + 1 :]

    suffix_parts: list[str] = []
    while body.endswith("]"):
        start = body.rfind("[")
        if start < 0:
            break
        tag = body[start:]
        if tag_name(tag) not in SUFFIX_TAGS:
            break
        suffix_parts.append(tag)
        body = body[:start]

    suffix = "".join(reversed(suffix_parts))
    return prefix, body, suffix


def restore_wrappers(record: dict, translated: str) -> str:
    text = translated.strip()
    leading = record.get("leading_ws") or ""
    trailing = record.get("trailing_ws") or ""
    if leading and not text.startswith(leading):
        text = leading + text.lstrip(" \t\u3000")
    if trailing and not text.endswith(trailing):
        text = text.rstrip(" \t\u3000") + trailing
    return f"{record.get('prefix') or ''}{text}{record.get('suffix') or ''}"


def normalize_wrap_markers(text: str) -> str:
    return WRAP_MARKER_RE.sub("[r]", text)


def translated_body_for_line(record: dict, text: str, allow_wrap_markers: bool = False) -> str:
    body = text.strip()
    if allow_wrap_markers:
        body = normalize_wrap_markers(body)

    # Current manifests export the complete line body, tags included. Older
    # manifests stored outer tags/spacing separately, so keep that path alive.
    if record.get("prefix") or record.get("suffix") or record.get("leading_ws") or record.get("trailing_ws"):
        return restore_wrappers(record, body)
    return body


def relpath(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def is_chapter_file(rel: str) -> bool:
    path = Path(rel)
    return len(path.parts) >= 2 and path.parts[0] == "scenario" and path.name.startswith("chapter") and path.suffix == ".ks"


def iter_source_files(data_root: Path) -> list[Path]:
    patterns = ["scenario/**/*.ks", "system/**/*.tjs", "system/**/*.js", "others/**/*.ks", "others/**/*.js", "others/**/*.tjs"]
    files: list[Path] = []
    for pattern in patterns:
        files.extend(data_root.glob(pattern))
    return sorted({p for p in files if p.is_file() and not p.name.lower().startswith("_sample")})


def read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8-sig", errors="replace").splitlines(keepends=True)


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def tag_spans(line: str) -> list[tuple[int, int, str, str]]:
    spans: list[tuple[int, int, str, str]] = []
    pos = 0
    while True:
        start = line.find("[", pos)
        if start < 0:
            break
        end = line.find("]", start + 1)
        if end < 0:
            break
        inner = line[start + 1 : end]
        name = inner.strip().split(None, 1)[0].lower() if inner.strip() else ""
        spans.append((start, end + 1, name, inner))
        pos = end + 1
    return spans


def add_menu_span_records(
    records: list[TextRecord], rel: str, line_index: int, line: str, order_base: int
) -> int:
    added = 0
    for tag_start, _tag_end, name, inner in tag_spans(line):
        wanted = KS_TAG_ATTRS.get(name)
        if not wanted:
            continue
        for match in ATTR_RE.finditer(inner):
            attr = match.group("name")
            if attr not in wanted:
                continue
            group = "dval" if match.group("dval") is not None else "sval" if match.group("sval") is not None else "uval"
            value = match.group(group) or ""
            if not value or value.startswith(("&", "%")) or not has_japanese(value):
                continue
            leading, core, trailing = split_edge_ws(value)
            start = tag_start + 1 + match.start(group)
            end = tag_start + 1 + match.end(group)
            records.append(
                TextRecord(
                    order=order_base + added,
                    bucket="menu",
                    record_type="menu",
                    file=rel,
                    line_index=line_index,
                    kind="ks_attr",
                    source=core,
                    export_text=export_line(core),
                    mode="span",
                    start=start,
                    end=end,
                    leading_ws=leading,
                    trailing_ws=trailing,
                    tag=name,
                    attr=attr,
                )
            )
            added += 1
    return added


def js_string_spans(line: str) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == "/" and i + 1 < len(line) and line[i + 1] == "/":
            break
        if ch not in ("'", '"', "`"):
            i += 1
            continue
        quote = ch
        start = i + 1
        i += 1
        escaped = False
        value_chars: list[str] = []
        while i < len(line):
            ch = line[i]
            if escaped:
                value_chars.append(ch)
                escaped = False
                i += 1
                continue
            if ch == "\\":
                escaped = True
                value_chars.append(ch)
                i += 1
                continue
            if ch == quote:
                value = "".join(value_chars)
                spans.append((start, i, value))
                i += 1
                break
            value_chars.append(ch)
            i += 1
    return spans


def add_js_string_records(records: list[TextRecord], rel: str, line_index: int, line: str, order_base: int) -> int:
    added = 0
    for start, end, value in js_string_spans(line):
        if not has_japanese(value):
            continue
        leading, core, trailing = split_edge_ws(value)
        records.append(
            TextRecord(
                order=order_base + added,
                bucket="menu",
                record_type="menu",
                file=rel,
                line_index=line_index,
                kind="js_string",
                source=core,
                export_text=export_line(core),
                mode="span",
                start=start,
                end=end,
                leading_ws=leading,
                trailing_ws=trailing,
            )
        )
        added += 1
    return added


def add_config_records(records: list[TextRecord], rel: str, line_index: int, line: str, order_base: int) -> int:
    match = re.match(r"^;?(?P<key>[A-Za-z0-9_.]+)=(?P<value>.*)$", line)
    if not match or match.group("key") != "System.title":
        return 0
    value = match.group("value")
    if not has_japanese(value):
        return 0
    leading, core, trailing = split_edge_ws(value)
    records.append(
        TextRecord(
            order=order_base,
            bucket="menu",
            record_type="menu",
            file=rel,
            line_index=line_index,
            kind="config_value",
            source=core,
            export_text=export_line(core),
            mode="span",
            start=match.start("value"),
            end=match.end("value"),
            leading_ws=leading,
            trailing_ws=trailing,
        )
    )
    return 1


def make_raw_text_record(
    order: int,
    bucket: str,
    rel: str,
    line_index: int,
    body: str,
    speaker: str | None,
    speaker_line_index: int | None,
) -> TextRecord:
    kind = "dialogue" if speaker else "narration"
    return TextRecord(
        order=order,
        bucket=bucket,
        record_type="text",
        file=rel,
        line_index=line_index,
        kind=kind if bucket == "dialogue" else "menu_text",
        source=body,
        export_text=export_line(body),
        speaker=speaker,
        speaker_line_index=speaker_line_index,
        mode="line",
    )


def scan_files(data_root: Path) -> tuple[list[TextRecord], list[TextRecord]]:
    dialogue: list[TextRecord] = []
    menu: list[TextRecord] = []
    speaker_order: dict[str, None] = {}

    for path in iter_source_files(data_root):
        rel = relpath(path, data_root)
        lines = read_lines(path)
        chapter = is_chapter_file(rel)
        current_speaker: str | None = None
        current_speaker_line: int | None = None
        in_iscript = False
        in_block_comment = False

        for line_index, line in enumerate(lines):
            body, _newline = line_body_newline(line)
            stripped = body.lstrip()
            lower = stripped.lower()

            if lower.startswith("[iscript]"):
                in_iscript = True
                continue
            if lower.startswith("[endscript]"):
                in_iscript = False
                continue

            if path.suffix.lower() in {".js", ".tjs"}:
                added = add_config_records(menu, rel, line_index, body, len(menu))
                if not added:
                    add_js_string_records(menu, rel, line_index, body, len(menu))
                continue

            if in_iscript:
                add_js_string_records(menu, rel, line_index, body, len(menu))
                continue

            if in_block_comment:
                if "*/" in stripped:
                    in_block_comment = False
                continue
            if stripped.startswith("/*"):
                if "*/" not in stripped:
                    in_block_comment = True
                continue

            if stripped.startswith("#"):
                name = stripped[1:].strip()
                current_speaker = name or None
                current_speaker_line = line_index if name else None
                if chapter and is_translatable_speaker(current_speaker):
                    speaker_order.setdefault(current_speaker, None)
                continue

            if not stripped or stripped.startswith(";") or stripped.startswith("*") or stripped.startswith("@"):
                continue

            add_menu_span_records(menu, rel, line_index, body, len(menu))

            visible = TAG_RE.sub("", body).strip()
            if not has_japanese(visible):
                continue

            bucket = "dialogue" if chapter else "menu"
            record = make_raw_text_record(
                order=len(dialogue) if bucket == "dialogue" else len(menu),
                bucket=bucket,
                rel=rel,
                line_index=line_index,
                body=body,
                speaker=current_speaker if bucket == "dialogue" else None,
                speaker_line_index=current_speaker_line if bucket == "dialogue" else None,
            )
            if bucket == "dialogue":
                dialogue.append(record)
            else:
                menu.append(record)

    speaker_records = [
        TextRecord(
            order=0,
            bucket="dialogue",
            record_type="speaker_name",
            file="",
            line_index=-1,
            kind="speaker_name",
            source=speaker,
            export_text=speaker,
            speaker=speaker,
            mode="speaker",
        )
        for speaker in speaker_order
    ]

    all_dialogue = speaker_records + dialogue
    for order, record in enumerate(all_dialogue):
        record.order = order
    for order, record in enumerate(menu):
        record.order = order
    return all_dialogue, menu


def write_text_file(path: Path, records: list[TextRecord], dialogue: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            if dialogue and record.record_type == "speaker_name":
                handle.write(record.export_text + "\n")
            elif dialogue:
                context = record.speaker or NARRATION_CONTEXT
                handle.write(f"[{context}]: {record.export_text}\n")
            else:
                handle.write(record.export_text + "\n")


def write_inventory(path: Path, dialogue: list[TextRecord], menu: list[TextRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["bucket", "record_type", "kind", "file", "line", "speaker", "source"],
        )
        writer.writeheader()
        for record in dialogue + menu:
            writer.writerow(
                {
                    "bucket": record.bucket,
                    "record_type": record.record_type,
                    "kind": record.kind,
                    "file": record.file,
                    "line": record.line_index + 1 if record.line_index >= 0 else "",
                    "speaker": record.speaker or "",
                    "source": record.source,
                }
            )


def cmd_extract(args: argparse.Namespace) -> int:
    dialogue, menu = scan_files(args.data_root)
    write_text_file(args.dialogue_txt, dialogue, dialogue=True)
    write_text_file(args.menu_txt, menu, dialogue=False)
    write_jsonl(args.dialogue_manifest, [asdict(record) for record in dialogue])
    write_jsonl(args.menu_manifest, [asdict(record) for record in menu])
    write_inventory(args.inventory_csv, dialogue, menu)

    print(f"Dialogue lines: {len(dialogue):,} ({sum(1 for r in dialogue if r.record_type == 'speaker_name'):,} speaker glossary)")
    print(f"Menu/other lines: {len(menu):,}")
    print(f"Dialogue text: {args.dialogue_txt}")
    print(f"Menu text:     {args.menu_txt}")
    print(f"Inventory:     {args.inventory_csv}")
    return 0


def read_translation_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8-sig", errors="replace").splitlines()


def read_menu_translation_lines(path: Path, expected_count: int) -> list[str]:
    lines = read_translation_lines(path)
    if len(lines) != expected_count:
        raise ValueError(
            f"menu line count mismatch: got {len(lines)}, expected {expected_count}. "
            r"Use [r], literal \n, or <br> inside one physical line instead of adding real new lines."
        )
    return lines


def read_dialogue_translation_lines(path: Path, records: list[dict]) -> list[str]:
    lines = read_translation_lines(path)
    if len(lines) == len(records):
        return lines

    speaker_count = sum(1 for record in records if record.get("record_type") == "speaker_name")
    if len(lines) < speaker_count:
        raise ValueError(f"dialogue line count mismatch: got {len(lines)}, expected {len(records)}")

    speaker_lines = lines[:speaker_count]
    content_lines = lines[speaker_count:]
    expected_content_count = len(records) - speaker_count

    rebuilt_content: list[str] = []
    current: str | None = None
    saw_prefixed_record = False
    for line in content_lines:
        if BRACKET_LINE_RE.match(line):
            saw_prefixed_record = True
            if current is not None:
                rebuilt_content.append(current)
            current = line
        elif current is not None:
            current += "[r]" + line.strip()
        else:
            rebuilt_content.append(line)

    if current is not None:
        rebuilt_content.append(current)

    if saw_prefixed_record and len(rebuilt_content) == expected_content_count:
        return speaker_lines + rebuilt_content

    raise ValueError(
        f"dialogue line count mismatch: got {len(lines)}, expected {len(records)}. "
        r"Keep one physical line per record, or use [r], literal \n, or <br> for manual wraps. "
        "Physical continuation lines are only auto-joined when Dazed speaker prefixes are still present."
    )


def split_dazed_line(line: str) -> tuple[str | None, str]:
    match = BRACKET_LINE_RE.match(line)
    if not match:
        return None, line.strip()
    return match.group("speaker").strip(), match.group("text").strip()


def add_full_replacement(replacements: dict[str, dict[int, dict]], file: str, line_index: int, text: str) -> None:
    line_map = replacements.setdefault(file, {})
    state = line_map.setdefault(line_index, {"full": None, "spans": []})
    existing = state.get("full")
    if existing is not None and existing != text:
        raise ValueError(f"conflicting full-line replacement for {file}:{line_index + 1}")
    state["full"] = text


def add_span_replacement(
    replacements: dict[str, dict[int, dict]], file: str, line_index: int, start: int, end: int, text: str
) -> None:
    line_map = replacements.setdefault(file, {})
    state = line_map.setdefault(line_index, {"full": None, "spans": []})
    if state.get("full") is not None:
        raise ValueError(f"span replacement conflicts with full-line replacement for {file}:{line_index + 1}")
    state["spans"].append((start, end, text))


def build_replacements(
    dialogue_manifest: Path,
    dialogue_txt: Path,
    menu_manifest: Path,
    menu_txt: Path,
) -> dict[str, dict[int, dict]]:
    replacements: dict[str, dict[int, dict]] = {}

    dialogue_records = read_jsonl(dialogue_manifest)
    dialogue_lines = read_dialogue_translation_lines(dialogue_txt, dialogue_records)
    if len(dialogue_records) != len(dialogue_lines):
        raise ValueError(f"dialogue line count mismatch: got {len(dialogue_lines)}, expected {len(dialogue_records)}")

    speaker_map: dict[str, str] = {}
    for record, line in zip(dialogue_records, dialogue_lines):
        if record.get("record_type") == "speaker_name":
            source = (record.get("source") or "").strip()
            if source:
                speaker_map[source] = line.strip()

    for record, line in zip(dialogue_records, dialogue_lines):
        if record.get("record_type") == "speaker_name":
            continue
        parsed_speaker, body = split_dazed_line(line)
        body_text = translated_body_for_line(record, body, allow_wrap_markers=True)
        add_full_replacement(replacements, record["file"], int(record["line_index"]), body_text)

        source_speaker = (record.get("speaker") or "").strip()
        speaker_line_index = record.get("speaker_line_index")
        if is_translatable_speaker(source_speaker) and speaker_line_index is not None:
            translated_speaker = parsed_speaker if parsed_speaker and parsed_speaker != NARRATION_CONTEXT else ""
            translated_speaker = translated_speaker or speaker_map.get(source_speaker, "")
            if translated_speaker:
                add_full_replacement(
                    replacements,
                    record["file"],
                    int(speaker_line_index),
                    f"#{translated_speaker.strip()}",
                )

    menu_records = read_jsonl(menu_manifest)
    menu_lines = read_menu_translation_lines(menu_txt, len(menu_records))
    if len(menu_records) != len(menu_lines):
        raise ValueError(f"menu line count mismatch: got {len(menu_lines)}, expected {len(menu_records)}")

    for record, line in zip(menu_records, menu_lines):
        text = line.strip()
        if record.get("mode") == "line":
            add_full_replacement(
                replacements,
                record["file"],
                int(record["line_index"]),
                translated_body_for_line(record, text, allow_wrap_markers=True),
            )
        elif record.get("mode") == "span":
            add_span_replacement(
                replacements,
                record["file"],
                int(record["line_index"]),
                int(record["start"]),
                int(record["end"]),
                restore_wrappers(record, text),
            )
        else:
            raise ValueError(f"unknown menu replacement mode: {record.get('mode')}")

    return replacements


def backup_file(data_root: Path, backup_root: Path, rel: str) -> None:
    src = data_root / rel
    dst = backup_root / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def apply_replacements(
    data_root: Path,
    replacements: dict[str, dict[int, dict]],
    output_data: Path,
    replace: bool = False,
) -> list[Path]:
    written: list[Path] = []
    backup_dir: Path | None = None
    if replace:
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = BACKUP_ROOT / f"text_original_{stamp}"

    for rel, line_map in sorted(replacements.items()):
        src = data_root / rel
        lines = read_lines(src)
        for line_index, state in line_map.items():
            body, newline = line_body_newline(lines[line_index])
            if state.get("full") is not None:
                body = state["full"]
            else:
                for start, end, text in sorted(state["spans"], key=lambda item: item[0], reverse=True):
                    body = body[:start] + text + body[end:]
            lines[line_index] = body + newline

        if replace:
            assert backup_dir is not None
            backup_file(data_root, backup_dir, rel)
            out_path = src
        else:
            out_path = output_data / rel
            out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("".join(lines), encoding="utf-8", newline="")
        written.append(out_path)

    if backup_dir is not None:
        print(f"Backup directory: {backup_dir}")
    return written


def cmd_inject(args: argparse.Namespace) -> int:
    replacements = build_replacements(args.dialogue_manifest, args.dialogue_txt, args.menu_manifest, args.menu_txt)
    written = apply_replacements(args.data_root, replacements, args.output_data, args.replace)
    print(f"Files patched: {len(written):,}")
    if args.replace:
        print(f"Replaced files under: {args.data_root}")
    else:
        print(f"Patched copies under: {args.output_data}")
    return 0


def cmd_roundtrip(args: argparse.Namespace) -> int:
    cmd_extract(args)
    replacements = build_replacements(args.dialogue_manifest, args.dialogue_txt, args.menu_manifest, args.menu_txt)
    written = apply_replacements(args.data_root, replacements, args.output_data, replace=False)

    diffs: list[str] = []
    for out_path in written:
        rel = relpath(out_path, args.output_data)
        original = (args.data_root / rel).read_text(encoding="utf-8-sig", errors="replace")
        patched = out_path.read_text(encoding="utf-8-sig", errors="replace")
        if original != patched:
            diffs.append(rel)
            if len(diffs) >= 10:
                break
    print(f"Roundtrip files checked: {len(written):,}")
    print(f"Roundtrip diffs: {len(diffs):,}")
    for rel in diffs:
        print(f"DIFF: {rel}")
    return 1 if diffs else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
        p.add_argument("--dialogue-txt", type=Path, default=DEFAULT_DIALOGUE_TXT)
        p.add_argument("--menu-txt", type=Path, default=DEFAULT_MENU_TXT)
        p.add_argument("--dialogue-manifest", type=Path, default=DEFAULT_DIALOGUE_MANIFEST)
        p.add_argument("--menu-manifest", type=Path, default=DEFAULT_MENU_MANIFEST)

    extract = sub.add_parser("extract", help="extract dialogue and menu text")
    add_common(extract)
    extract.add_argument("--inventory-csv", type=Path, default=DEFAULT_INVENTORY_CSV)
    extract.set_defaults(func=cmd_extract)

    inject = sub.add_parser("inject", help="inject translated dialogue/menu text")
    add_common(inject)
    inject.add_argument("--output-data", type=Path, default=DEFAULT_PATCHED_DATA)
    inject.add_argument("--replace", action="store_true", help="replace source files after backing them up")
    inject.set_defaults(func=cmd_inject)

    roundtrip = sub.add_parser("roundtrip", help="extract, inject the source text, and compare")
    add_common(roundtrip)
    roundtrip.add_argument("--inventory-csv", type=Path, default=DEFAULT_INVENTORY_CSV)
    roundtrip.add_argument("--output-data", type=Path, default=WORKSPACE / "roundtrip_data")
    roundtrip.set_defaults(func=cmd_roundtrip)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
