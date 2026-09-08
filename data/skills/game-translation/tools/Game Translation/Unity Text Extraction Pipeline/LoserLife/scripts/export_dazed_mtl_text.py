#!/usr/bin/env python3
"""
Export Loser Life text into DazedMTLTool text-module input files.

The .txt files are intentionally simple line-based inputs. Reinjection metadata
lives in sidecar manifests so the Dazed text module can write clean translated
line files without needing to preserve IDs or comments.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import re
import warnings
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable


JAPANESE_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uff66-\uff9f]")
ASSET_PATH_RE = re.compile(
    r"(?i)(^assets[\\/]|^resources[\\/]|[\\/].*\.(?:anim|asset|bundle|controller|jpeg|jpg|mat|mp3|ogg|png|prefab|shader|tga|wav)$)"
)
SECTION_RE = re.compile(r"^  ([A-Za-z_][\w$<>.\-]*):\s*$")
ACTOR_OR_CONV_RE = re.compile(r"^  - id: (-?\d+)\s*$")
ENTRY_RE = re.compile(r"^    - id: (-?\d+)\s*$")
CONV_FIELD_TITLE_RE = re.compile(r"^    - title: (.*)$")
CONV_FIELD_VALUE_RE = re.compile(r"^      value:(?:\s*(.*))?$")
ENTRY_FIELD_TITLE_RE = re.compile(r"^      - title: (.*)$")
ENTRY_FIELD_VALUE_RE = re.compile(r"^        value:(?:\s*(.*))?$")
ENTRY_PROP_RE = re.compile(r"^      ([A-Za-z_][\w$<>.\-]*):(?:\s*(.*))?$")
BLOCK_MARKERS = {"|", "|-", "|+", ">", ">-", ">+"}

DIALOGUE_DB_REL = "Assets/MonoBehaviour/Dialogue Database.asset"
SHOP_DIALOGUE_FIELDS = {
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
}


@dataclass
class FieldValue:
    value: str
    line: int


@dataclass
class Actor:
    actor_id: int
    fields: dict[str, FieldValue] = field(default_factory=dict)


@dataclass
class DialogueEntry:
    conversation_id: int
    entry_id: int
    fields: dict[str, FieldValue] = field(default_factory=dict)
    props: dict[str, str] = field(default_factory=dict)
    line: int = 0


@dataclass
class Conversation:
    conversation_id: int
    fields: dict[str, FieldValue] = field(default_factory=dict)
    entries: list[DialogueEntry] = field(default_factory=list)
    line: int = 0


@dataclass
class ExportEntry:
    id: str
    kind: str
    split: str
    category: str
    source_file: str
    line: int
    field: str
    context: str
    speaker: str
    original_text: str
    export_text: str
    export_file: str = ""
    export_line: int = 0
    split_file: str = ""
    split_line: int = 0
    stable_key: str = ""
    occurrence_count: int = 1
    source_refs: list[str] = field(default_factory=list)
    conversation_id: str = ""
    conversation_title: str = ""
    entry_id: str = ""


def has_japanese(text: str) -> bool:
    return bool(JAPANESE_RE.search(text or ""))


def clean_text(text: str) -> str:
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").replace("\u200b", "").strip()


def looks_like_asset_path(text: str) -> bool:
    normalized = clean_text(text).replace("\\", "/")
    if ASSET_PATH_RE.search(normalized):
        return True
    if "/" not in normalized:
        return False
    return Path(normalized).suffix.lower() in {
        ".anim",
        ".asset",
        ".bundle",
        ".controller",
        ".jpeg",
        ".jpg",
        ".mat",
        ".mp3",
        ".ogg",
        ".png",
        ".prefab",
        ".shader",
        ".tga",
        ".wav",
    }


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


def parse_scalar(raw_value: str | None) -> str:
    if raw_value is None:
        return ""
    raw = raw_value.strip()
    if not raw:
        return ""
    if raw in BLOCK_MARKERS:
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


def collect_block(lines: list[str], start_index: int, parent_indent: int) -> tuple[str, int]:
    parts: list[str] = []
    index = start_index
    while index < len(lines):
        line = lines[index].rstrip("\r\n")
        indent = len(line) - len(line.lstrip(" "))
        if line.strip() and indent <= parent_indent:
            break
        parts.append(line[parent_indent + 1 :] if len(line) > parent_indent else "")
        index += 1
    return "\n".join(parts), index


def read_value(lines: list[str], index: int, raw_value: str | None, value_indent: int) -> tuple[str, int]:
    parsed = parse_scalar(raw_value)
    if parsed in BLOCK_MARKERS:
        return collect_block(lines, index + 1, value_indent)
    return parsed, index + 1


def parse_dialogue_database(path: Path) -> tuple[dict[int, Actor], list[Conversation]]:
    lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    actors: dict[int, Actor] = {}
    conversations: list[Conversation] = []
    section = ""
    current_actor: Actor | None = None
    current_conversation: Conversation | None = None
    current_entry: DialogueEntry | None = None
    current_field = ""
    in_dialogue_entries = False
    index = 0

    def flush_actor() -> None:
        nonlocal current_actor
        if current_actor is not None:
            actors[current_actor.actor_id] = current_actor
        current_actor = None

    def flush_entry() -> None:
        nonlocal current_entry
        if current_entry is not None and current_conversation is not None:
            current_conversation.entries.append(current_entry)
        current_entry = None

    def flush_conversation() -> None:
        nonlocal current_conversation, in_dialogue_entries
        flush_entry()
        if current_conversation is not None:
            conversations.append(current_conversation)
        current_conversation = None
        in_dialogue_entries = False

    while index < len(lines):
        line = lines[index].rstrip("\r\n")
        line_no = index + 1

        section_match = SECTION_RE.match(line)
        if section_match:
            if section == "actors":
                flush_actor()
            if section == "conversations":
                flush_conversation()
            section = section_match.group(1)
            current_field = ""
            index += 1
            continue

        if section == "actors":
            actor_match = ACTOR_OR_CONV_RE.match(line)
            if actor_match:
                flush_actor()
                current_actor = Actor(actor_id=int(actor_match.group(1)))
                current_field = ""
                index += 1
                continue

            title_match = CONV_FIELD_TITLE_RE.match(line)
            if title_match:
                current_field = parse_scalar(title_match.group(1))
                index += 1
                continue

            value_match = CONV_FIELD_VALUE_RE.match(line)
            if value_match and current_actor is not None and current_field:
                value, index = read_value(lines, index, value_match.group(1), 6)
                current_actor.fields[current_field] = FieldValue(clean_text(value), line_no)
                continue

        elif section == "conversations":
            conv_match = ACTOR_OR_CONV_RE.match(line)
            if conv_match:
                flush_conversation()
                current_conversation = Conversation(conversation_id=int(conv_match.group(1)), line=line_no)
                current_field = ""
                in_dialogue_entries = False
                index += 1
                continue

            if line == "    dialogueEntries:":
                in_dialogue_entries = True
                flush_entry()
                current_field = ""
                index += 1
                continue

            if not in_dialogue_entries:
                title_match = CONV_FIELD_TITLE_RE.match(line)
                if title_match:
                    current_field = parse_scalar(title_match.group(1))
                    index += 1
                    continue

                value_match = CONV_FIELD_VALUE_RE.match(line)
                if value_match and current_conversation is not None and current_field:
                    value, index = read_value(lines, index, value_match.group(1), 6)
                    current_conversation.fields[current_field] = FieldValue(clean_text(value), line_no)
                    continue

            else:
                entry_match = ENTRY_RE.match(line)
                if entry_match:
                    flush_entry()
                    conv_id = current_conversation.conversation_id if current_conversation else -1
                    current_entry = DialogueEntry(
                        conversation_id=conv_id,
                        entry_id=int(entry_match.group(1)),
                        line=line_no,
                    )
                    current_field = ""
                    index += 1
                    continue

                title_match = ENTRY_FIELD_TITLE_RE.match(line)
                if title_match:
                    current_field = parse_scalar(title_match.group(1))
                    index += 1
                    continue

                value_match = ENTRY_FIELD_VALUE_RE.match(line)
                if value_match and current_entry is not None and current_field:
                    value, index = read_value(lines, index, value_match.group(1), 8)
                    current_entry.fields[current_field] = FieldValue(clean_text(value), line_no)
                    continue

                prop_match = ENTRY_PROP_RE.match(line)
                if prop_match and current_entry is not None:
                    current_entry.props[prop_match.group(1)] = parse_scalar(prop_match.group(2))
                    index += 1
                    continue

        index += 1

    if section == "actors":
        flush_actor()
    if section == "conversations":
        flush_conversation()
    return actors, conversations


def actor_field(actor: Actor | None, name: str) -> str:
    if actor is None:
        return ""
    field_value = actor.fields.get(name)
    return field_value.value if field_value else ""


def actor_speaker(actors: dict[int, Actor], actor_id_text: str) -> str:
    try:
        actor_id = int(actor_id_text)
    except (TypeError, ValueError):
        return "Narration"
    actor = actors.get(actor_id)
    display = actor_field(actor, "Display Name")
    name = display if display.strip() else actor_field(actor, "Name")
    name = clean_text(name)
    if not name or name.lower() in {"void", "none", "null"}:
        return "Narration"
    return name


def safe_speaker(speaker: str) -> str:
    speaker = clean_text(speaker or "Narration")
    speaker = speaker.replace("[", "(").replace("]", ")").replace(":", " ")
    speaker = " ".join(speaker.split())
    return speaker or "Narration"


def export_line(speaker: str, text: str) -> str:
    body = clean_text(text).replace("\n", "\\n")
    return f"[{safe_speaker(speaker)}]: {body}"


def stable_hash(*parts: str) -> str:
    payload = "\x1f".join(parts).encode("utf-8", errors="surrogatepass")
    return hashlib.sha1(payload).hexdigest()[:12]


def make_entry_id(prefix: str, index: int, *parts: str) -> tuple[str, str]:
    key = stable_hash(*parts)
    return f"{prefix}{index:05d}_{key[:8]}", key


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def find_exported_project(root: Path) -> Path:
    candidates = sorted(root.glob("AssetRipper_export_*/ExportedProject"))
    if not candidates:
        raise FileNotFoundError("No AssetRipper_export_*/ExportedProject folder found.")
    return candidates[-1]


def read_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def text_from_row(row: dict[str, str]) -> str:
    return clean_text(row.get("text") or "")


def field_from_row(row: dict[str, str]) -> str:
    return row.get("field") or ""


def context_for_row(row: dict[str, str], fallback: str) -> str:
    context = clean_text(row.get("context") or "")
    if context:
        return context
    source = row.get("source_file") or ""
    stem = Path(source).stem if source else ""
    return stem or fallback


def source_ref(row: dict[str, str]) -> str:
    field = row.get("field") or ""
    line = row.get("line") or ""
    source = row.get("source_file") or ""
    context = row.get("context") or ""
    suffix = f" {field}" if field else ""
    if context:
        suffix += f" [{context}]"
    return f"{source}:{line}{suffix}"


def build_dialogue_database_entries(
    actors: dict[int, Actor],
    conversations: Iterable[Conversation],
    start_index: int,
) -> tuple[list[ExportEntry], int]:
    entries: list[ExportEntry] = []
    index = start_index
    for conversation in conversations:
        conv_title = conversation.fields.get("Title")
        title = conv_title.value if conv_title else f"Conversation {conversation.conversation_id}"
        for dialogue_entry in conversation.entries:
            actor_id = dialogue_entry.fields.get("Actor")
            speaker = actor_speaker(actors, actor_id.value if actor_id else "")
            for field_name, speaker_override in (("Dialogue Text", ""), ("Menu Text", "Player Choice")):
                field_value = dialogue_entry.fields.get(field_name)
                if field_value is None or not has_japanese(field_value.value):
                    continue
                index += 1
                final_speaker = speaker_override or speaker
                entry_id, key = make_entry_id(
                    "LLD",
                    index,
                    DIALOGUE_DB_REL,
                    str(field_value.line),
                    field_name,
                    str(conversation.conversation_id),
                    str(dialogue_entry.entry_id),
                    field_value.value,
                )
                entries.append(
                    ExportEntry(
                        id=entry_id,
                        stable_key=key,
                        kind="dialogue",
                        split="dialogue_database",
                        category="dialogue_database",
                        source_file=DIALOGUE_DB_REL,
                        line=field_value.line,
                        field=f"value[{field_name}]",
                        context=title,
                        speaker=final_speaker,
                        original_text=field_value.value,
                        export_text=export_line(final_speaker, field_value.value),
                        source_refs=[
                            f"{DIALOGUE_DB_REL}:{field_value.line} value[{field_name}] "
                            f"[conversation={conversation.conversation_id}; entry={dialogue_entry.entry_id}; title={title}]"
                        ],
                        conversation_id=str(conversation.conversation_id),
                        conversation_title=title,
                        entry_id=str(dialogue_entry.entry_id),
                    )
                )
    return entries, index


def build_speaker_name_entries(actors: dict[int, Actor], start_index: int) -> tuple[list[ExportEntry], int]:
    entries: list[ExportEntry] = []
    index = start_index
    for actor_id in sorted(actors):
        actor = actors[actor_id]
        name = actor.fields.get("Name")
        if name is None or not has_japanese(name.value):
            continue
        index += 1
        entry_id, key = make_entry_id("LLG", index, DIALOGUE_DB_REL, str(name.line), "actor_name", name.value)
        entries.append(
            ExportEntry(
                id=entry_id,
                stable_key=key,
                kind="general",
                split="dialogue_speakers",
                category="dialogue_speaker_name",
                source_file=DIALOGUE_DB_REL,
                line=name.line,
                field="actors.Name",
                context=f"Actor {actor_id}",
                speaker="Name",
                original_text=name.value,
                export_text=export_line("Name", name.value),
                source_refs=[f"{DIALOGUE_DB_REL}:{name.line} actors.Name [actor={actor_id}]"],
            )
        )
    return entries, index


def classify_csv_row(row: dict[str, str]) -> tuple[str, str, str]:
    category = row.get("category") or ""
    field = field_from_row(row)
    field_lower = field.lower()
    field_base = re.sub(r"\[\d+\]", "", field_lower).replace("\\", ".").split(".")[-1]
    if category == "dialogue_database":
        return "skip", "skip", ""
    if category == "npc_ambient_dialogue":
        return "dialogue", "npc_ambient", "NPC Ambient"
    if category == "shop_text" and field_base in SHOP_DIALOGUE_FIELDS:
        return "dialogue", "shop_dialogue", "Shop"
    if category in {"voice_line", "bundle_voice_line"}:
        return "dialogue", "voice_lines", "Voice"
    if field_base.startswith("voice_"):
        return "dialogue", "voice_lines", "Voice"
    if category == "source_literal":
        return "general", "runtime_literals", "System"
    if field_base in {"info", "tip", "itemtip", "iteminfotiptext", "progresstext", "description", "desc"}:
        return "general", "items_menus_descriptions", "Info"
    if category in {"ui_text", "tutorial_ui", "ui_message"}:
        return "general", "ui_tutorial_messages", "UI"
    if category == "shop_text":
        return "general", "shops_and_buying", "Shop UI"
    if field_base == "m_name":
        return "general", "names_low_priority", "Name"
    if category == "game_data_name" or field_base in {"name", "subname", "displayname", "productname", "title"}:
        return "general", "items_menus_names", "Name"
    return "general", "misc_player_text", "Text"


def build_csv_entries(rows: Iterable[dict[str, str]], dialogue_start: int, general_start: int) -> tuple[list[ExportEntry], list[ExportEntry]]:
    dialogue_entries: list[ExportEntry] = []
    general_candidates: list[ExportEntry] = []
    dialogue_index = dialogue_start
    general_index = general_start

    for row in rows:
        text = text_from_row(row)
        if not has_japanese(text):
            continue
        if looks_like_asset_path(text) or looks_like_character_table(text):
            continue
        kind, split, speaker = classify_csv_row(row)
        if kind == "skip":
            continue
        context = context_for_row(row, speaker)
        source_file = row.get("source_file") or ""
        line_text = row.get("line") or "0"
        try:
            line = int(line_text)
        except ValueError:
            line = 0

        if kind == "dialogue":
            dialogue_index += 1
            entry_id, key = make_entry_id(
                "LLD",
                dialogue_index,
                source_file,
                str(line),
                field_from_row(row),
                context,
                text,
            )
            dialogue_entries.append(
                ExportEntry(
                    id=entry_id,
                    stable_key=key,
                    kind="dialogue",
                    split=split,
                    category=row.get("category") or "",
                    source_file=source_file,
                    line=line,
                    field=field_from_row(row),
                    context=context,
                    speaker=speaker,
                    original_text=text,
                    export_text=export_line(speaker, text),
                    source_refs=[source_ref(row)],
                )
            )
            continue

        general_index += 1
        entry_id, key = make_entry_id(
            "LLG",
            general_index,
            split,
            speaker,
            text,
        )
        general_candidates.append(
            ExportEntry(
                id=entry_id,
                stable_key=key,
                kind="general",
                split=split,
                category=row.get("category") or "",
                source_file=source_file,
                line=line,
                field=field_from_row(row),
                context=context,
                speaker=speaker,
                original_text=text,
                export_text=export_line(speaker, text),
                source_refs=[source_ref(row)],
            )
        )

    return dialogue_entries, dedupe_general_entries(general_candidates)


def dedupe_general_entries(entries: Iterable[ExportEntry]) -> list[ExportEntry]:
    grouped: dict[tuple[str, str, str], ExportEntry] = {}
    for entry in entries:
        key = (entry.split, entry.speaker, entry.original_text)
        existing = grouped.get(key)
        if existing is None:
            grouped[key] = entry
            continue
        existing.occurrence_count += 1
        existing.source_refs.extend(entry.source_refs)
    return sorted(grouped.values(), key=lambda entry: (entry.split, entry.speaker, entry.original_text, entry.source_file, entry.line))


def assign_export_locations(entries: list[ExportEntry], base_dir: Path, subdir: str, all_name: str) -> None:
    output_dir = base_dir / subdir
    for line_no, entry in enumerate(entries, start=1):
        entry.export_file = f"{subdir}/{all_name}"
        entry.export_line = line_no


def write_text_file(path: Path, entries: Iterable[ExportEntry]) -> int:
    lines = [entry.export_text for entry in entries]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8", newline="\n")
    return len(lines)


def write_split_files(base_dir: Path, subdir: str, entries: list[ExportEntry], max_lines: int) -> list[str]:
    files: list[str] = []
    groups: dict[str, list[ExportEntry]] = defaultdict(list)
    for entry in entries:
        groups[entry.split].append(entry)

    for split in sorted(groups):
        split_entries = groups[split]
        if not split_entries:
            continue
        for chunk_index, start in enumerate(range(0, len(split_entries), max_lines), start=1):
            chunk = split_entries[start : start + max_lines]
            name = f"{split}.txt" if len(split_entries) <= max_lines else f"{split}_{chunk_index:03d}.txt"
            rel = f"{subdir}/{name}"
            for line_no, entry in enumerate(chunk, start=1):
                entry.split_file = rel
                entry.split_line = line_no
            path = base_dir / subdir / name
            write_text_file(path, chunk)
            files.append(rel)
    return files


def manifest_row(entry: ExportEntry) -> dict[str, object]:
    row = asdict(entry)
    row["source_refs"] = json.dumps(entry.source_refs, ensure_ascii=False)
    return row


def write_manifest_csv(path: Path, entries: list[ExportEntry]) -> None:
    fieldnames = list(manifest_row(entries[0]).keys()) if entries else list(ExportEntry.__dataclass_fields__)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for entry in entries:
            writer.writerow(manifest_row(entry))


def write_manifest_json(path: Path, entries: list[ExportEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig") as handle:
        json.dump([asdict(entry) for entry in entries], handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def write_summary(path: Path, dialogue_entries: list[ExportEntry], general_entries: list[ExportEntry], generated_files: list[str]) -> None:
    dialogue_splits = Counter(entry.split for entry in dialogue_entries)
    general_splits = Counter(entry.split for entry in general_entries)
    lines = [
        "Loser Life DazedMTL text export",
        "",
        f"Dialogue lines: {len(dialogue_entries)}",
        f"General text lines: {len(general_entries)}",
        "",
        "Dialogue splits:",
    ]
    lines.extend(f"- {split}: {count}" for split, count in sorted(dialogue_splits.items()))
    lines.append("")
    lines.append("General splits:")
    lines.extend(f"- {split}: {count}" for split, count in sorted(general_splits.items()))
    lines.append("")
    lines.append("Generated text files:")
    lines.extend(f"- {file}" for file in generated_files)
    lines.append("")
    lines.append("Notes:")
    lines.append("- Text files are DazedMTLTool text-module inputs.")
    lines.append("- Manifests map each text line back to the original AssetRipper source, all-in-one line, and split-file line for reinjection.")
    lines.append("- Actual newlines inside game strings are escaped as \\n so every source record stays one tool line.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def clean_generated_subdir(base_dir: Path, subdir: str) -> None:
    output_dir = base_dir / subdir
    if not output_dir.exists():
        return
    generated_suffixes = {".txt", ".csv", ".json"}
    for path in output_dir.iterdir():
        if path.is_file() and path.suffix.lower() in generated_suffixes:
            path.unlink()


def main() -> int:
    root = repo_root()
    parser = argparse.ArgumentParser(description="Export Loser Life text for DazedMTLTool text module.")
    parser.add_argument("--exported-project", type=Path, default=None)
    parser.add_argument("--input-csv", type=Path, default=root / "tooling" / "outputs" / "japanese_text_all_occurrences.csv")
    parser.add_argument("--output-dir", type=Path, default=root / "tooling" / "mtl_exports")
    parser.add_argument("--max-lines", type=int, default=350, help="Maximum lines per split file.")
    args = parser.parse_args()

    exported_project = args.exported_project or find_exported_project(root)
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    clean_generated_subdir(output_dir, "dialogue")
    clean_generated_subdir(output_dir, "general")

    dialogue_db = exported_project / DIALOGUE_DB_REL
    actors, conversations = parse_dialogue_database(dialogue_db)
    dialogue_entries, dialogue_index = build_dialogue_database_entries(actors, conversations, 0)
    speaker_entries, general_index = build_speaker_name_entries(actors, 0)

    rows = read_rows(args.input_csv)
    csv_dialogue, csv_general = build_csv_entries(rows, dialogue_index, general_index)
    dialogue_entries.extend(csv_dialogue)
    general_entries = dedupe_general_entries([*speaker_entries, *csv_general])

    dialogue_entries.sort(key=lambda entry: (entry.split, entry.source_file, entry.line, entry.field, entry.id))
    general_entries.sort(key=lambda entry: (entry.split, entry.speaker, entry.original_text, entry.source_file, entry.line))

    assign_export_locations(dialogue_entries, output_dir, "dialogue", "dialogue_all.txt")
    assign_export_locations(general_entries, output_dir, "general", "general_text_all.txt")

    generated_files: list[str] = []
    generated_files.append("dialogue/dialogue_all.txt")
    write_text_file(output_dir / "dialogue" / "dialogue_all.txt", dialogue_entries)
    generated_files.extend(write_split_files(output_dir, "dialogue", dialogue_entries, args.max_lines))

    generated_files.append("general/general_text_all.txt")
    write_text_file(output_dir / "general" / "general_text_all.txt", general_entries)
    generated_files.extend(write_split_files(output_dir, "general", general_entries, args.max_lines))

    write_manifest_csv(output_dir / "dialogue" / "dialogue_manifest.csv", dialogue_entries)
    write_manifest_json(output_dir / "dialogue" / "dialogue_manifest.json", dialogue_entries)
    write_manifest_csv(output_dir / "general" / "general_manifest.csv", general_entries)
    write_manifest_json(output_dir / "general" / "general_manifest.json", general_entries)
    write_summary(output_dir / "README.md", dialogue_entries, general_entries, generated_files)

    print(f"Dialogue lines: {len(dialogue_entries)}")
    print(f"General text lines: {len(general_entries)}")
    print(f"Actor names: {len(speaker_entries)}")
    print(f"Conversations: {len(conversations)}")
    print(f"Wrote: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
