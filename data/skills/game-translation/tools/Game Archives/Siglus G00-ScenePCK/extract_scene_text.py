"""Extract decoded Siglus scene strings into translator-friendly JSON.

This game stores the main scene string table as UTF-16LE code units XORed with
the string entry index multiplied by 0x7087. Entry 0 therefore remains plaintext.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import struct
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

XOR_MULTIPLIER = 0x7087
FULLWIDTH_SPACE = "\u3000"
OPEN_QUOTES = {0x300C, 0x300E}
CLOSE_QUOTES = {0x300D, 0x300F}
QUOTE_PAIRS = (("\u300c", "\u300d"), ("\u300e", "\u300f"))
SENTENCE_END = {0x3002, 0xFF01, 0xFF1F, 0x2026}
PAUSE_PUNCT = {0x3001, 0xFF0C, 0x002C, 0x002E}
SPEAKER_DISALLOWED_PUNCT = {0x3001, 0x3002, 0xFF0C, 0x002C, 0x002E, 0x2026} | CLOSE_QUOTES
CHOICE_DISALLOWED_PUNCT = SPEAKER_DISALLOWED_PUNCT | OPEN_QUOTES | CLOSE_QUOTES | {
    0x0021,
    0x003F,
    0xFF01,
    0xFF1F,
}
RESOURCE_EXTENSIONS = (".g00", ".gan", ".wav", ".ogg", ".mp3", ".png", ".bmp")
RESOURCE_PREFIXES = (
    "g00",
    "gan",
    "wav",
    "koe",
    "bgm",
    "bg",
    "ev",
    "sys",
    "mask",
)
SCENE_NAME_RE = re.compile(r"^\d{4}_[A-Za-z0-9_]+$")
ASCII_TOKEN_RE = re.compile(r"^[A-Za-z0-9_./\\ -]+$")


@dataclass
class SceneString:
    scene_index: int
    scene_name: str
    string_index: int
    char_offset: int
    char_len: int
    xor_key: str
    kind: str
    text: str


@dataclass
class DialogueLine:
    scene_index: int
    scene_name: str
    line_index: int
    string_index: int
    kind: str
    speaker: str | None
    raw_text: str
    text: str
    text_for_translation: str
    quote_open_count: int
    quote_close_count: int


def u32(blob: bytes, offset: int) -> int:
    return struct.unpack_from("<I", blob, offset)[0]


def parse_header_pairs(blob: bytes) -> list[tuple[int, int]]:
    if len(blob) < 0x84:
        raise ValueError("scene blob is too small for a Siglus scene header")
    header_size = u32(blob, 0)
    if header_size != 0x84:
        raise ValueError(f"unexpected scene header size 0x{header_size:X}")
    return [(u32(blob, 4 + i * 8), u32(blob, 8 + i * 8)) for i in range(16)]


def find_vm_choice_indices(blob: bytes, strings: list[SceneString]) -> set[int]:
    """Find menu/select strings by scanning VM string pushes feeding opcode 0x30.

    The Siglus VM pushes typed operands with opcode 0x02. Type 20 is a decoded
    string-table index and opcode 0x30 consumes the current operand run for a
    select-like operation. The same opcode is also used for resource selects, so
    resource-looking entries are filtered out here.
    """
    pairs = parse_header_pairs(blob)
    code_off, code_size = pairs[0]
    code = blob[code_off : code_off + code_size]
    by_index = {item.string_index: item for item in strings}
    choice_indices: set[int] = set()
    pos = 0
    push_run: list[tuple[int, int]] = []

    while pos < len(code):
        op = code[pos]
        pos += 1

        if op == 0x02 and pos + 4 <= len(code):
            value_type = u32(code, pos)
            pos += 4
            if value_type in {10, 20} and pos + 4 <= len(code):
                value = u32(code, pos)
                pos += 4
                push_run.append((value_type, value))
            else:
                push_run = []
            continue

        if op == 0x30:
            candidates = []
            for value_type, value in push_run:
                if value_type != 20:
                    continue
                item = by_index.get(value)
                if not item:
                    continue
                text = item.text.strip()
                if item.kind == "resource" or is_resource_or_script_string(text):
                    continue
                if not has_japanese(text):
                    continue
                if is_quoted_line(text) or any(ord(char) in CLOSE_QUOTES for char in text):
                    continue
                candidates.append(value)
            if len(candidates) >= 2:
                choice_indices.update(candidates)

            # opcode 0x30 immediate layout, from the VM interpreter:
            # u32 id, u32 count, count*u32 payload, u32 tail/control.
            if pos + 8 <= len(code):
                pos += 4
                count = u32(code, pos)
                pos += 4
                if 0 <= count < 1000 and pos + count * 4 + 4 <= len(code):
                    pos += count * 4 + 4
            push_run = []
            continue

        immediate_sizes = {
            0x01: 4,
            0x03: 4,
            0x04: 4,
            0x07: 8,
            0x10: 4,
            0x11: 4,
            0x12: 4,
            0x20: 12,
            0x21: 5,
            0x22: 9,
            0x31: 4,
        }
        skip = immediate_sizes.get(op, 0)
        if pos + skip <= len(code):
            pos += skip
        push_run = []

    return choice_indices


def decode_utf16_xor(raw: bytes, entry_index: int) -> str:
    if len(raw) % 2:
        raise ValueError("UTF-16LE raw string has odd byte length")
    if not raw:
        return ""
    count = len(raw) // 2
    key = (entry_index * XOR_MULTIPLIER) & 0xFFFF
    values = struct.unpack("<" + "H" * count, raw)
    return "".join(chr(value ^ key) for value in values)


def first_non_indent(text: str) -> str:
    return text.lstrip(FULLWIDTH_SPACE + " \t")


def jp_score(text: str) -> float:
    if not text:
        return 0.0
    good = 0
    bad = 0
    for char in text:
        code = ord(char)
        if code in (0x0009, 0x000A, 0x000D, 0x0020, 0x3000):
            good += 1
        elif 0x3040 <= code <= 0x30FF:
            good += 1
        elif 0x3400 <= code <= 0x9FFF:
            good += 1
        elif 0xFF00 <= code <= 0xFFEF:
            good += 1
        elif code in OPEN_QUOTES or code in SENTENCE_END or code in PAUSE_PUNCT:
            good += 1
        elif 0x20 <= code <= 0x7E:
            good += 1
        else:
            bad += 1
    return good / max(1, good + bad)


def has_sentence_punctuation(text: str) -> bool:
    return any(ord(char) in SENTENCE_END or ord(char) in PAUSE_PUNCT for char in text)


def is_quoted_line(text: str) -> bool:
    stripped = first_non_indent(text)
    return bool(stripped) and ord(stripped[0]) in OPEN_QUOTES


def is_parenthetical_text(text: str) -> bool:
    stripped = first_non_indent(text)
    return bool(stripped) and ord(stripped[0]) == 0xFF08


def has_japanese(text: str) -> bool:
    return any(
        0x3040 <= ord(char) <= 0x30FF
        or 0x3400 <= ord(char) <= 0x9FFF
        or 0xFF61 <= ord(char) <= 0xFF9F
        for char in text
    )


def is_resource_or_script_string(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    lowered = stripped.lower()
    if has_japanese(stripped) and (stripped.startswith("/ ") or " / " in stripped):
        return False
    if stripped.startswith("$"):
        return True
    if "\\" in stripped or "/" in stripped:
        return True
    if lowered.endswith(RESOURCE_EXTENSIONS):
        return True
    if SCENE_NAME_RE.match(stripped):
        return True
    if ASCII_TOKEN_RE.match(stripped):
        if "_" in stripped or any(char.isdigit() for char in stripped):
            return True
        if any(lowered.startswith(prefix) for prefix in RESOURCE_PREFIXES):
            return True
    return False


def edge_quote_counts(text: str) -> tuple[int, int]:
    stripped = first_non_indent(text)
    if not stripped:
        return 0, 0
    for open_quote, close_quote in QUOTE_PAIRS:
        if stripped.startswith(open_quote):
            open_count = len(stripped) - len(stripped.lstrip(open_quote))
            close_count = len(stripped) - len(stripped.rstrip(close_quote))
            return open_count, close_count
    return 0, 0


def normalize_display_text(text: str) -> str:
    prefix_len = len(text) - len(first_non_indent(text))
    prefix = text[:prefix_len]
    body = text[prefix_len:]
    if not body:
        return text

    for open_quote, close_quote in QUOTE_PAIRS:
        if not body.startswith(open_quote):
            continue
        open_count = len(body) - len(body.lstrip(open_quote))
        close_count = len(body) - len(body.rstrip(close_quote))
        if open_count <= 1 and close_count <= 1:
            return text
        inner_end = len(body) - close_count if close_count else len(body)
        inner = body[open_count:inner_end]
        normalized = open_quote + inner
        if close_count:
            normalized += close_quote
        return prefix + normalized

    return text


def is_likely_speaker(text: str) -> bool:
    stripped = text.strip()
    if not stripped or len(stripped) > 32:
        return False
    if is_quoted_line(stripped):
        return False
    if ord(stripped[0]) in {0x0028, 0xFF08}:
        return False
    if stripped.startswith(FULLWIDTH_SPACE):
        return False
    if any(ord(char) in SPEAKER_DISALLOWED_PUNCT for char in stripped):
        return False
    return jp_score(stripped) >= 0.75


def is_contextual_speaker(text: str) -> bool:
    stripped = text.strip()
    if not stripped or len(stripped) > 40:
        return False
    if stripped.startswith(FULLWIDTH_SPACE) or is_quoted_line(stripped):
        return False
    if ord(stripped[0]) in {0x0028, 0xFF08}:
        return False
    return not any(ord(char) in SPEAKER_DISALLOWED_PUNCT for char in stripped)


def is_choice_option_candidate(text: str) -> bool:
    stripped = text.strip()
    if not stripped or len(stripped) > 48:
        return False
    if is_resource_or_script_string(stripped):
        return False
    if not has_japanese(stripped):
        return False
    if stripped[0] in {"\u30fb", "\u2026"}:
        return False
    if any(ord(char) in CHOICE_DISALLOWED_PUNCT for char in stripped):
        return False
    return True


def classify_string(text: str) -> str:
    stripped = first_non_indent(text)
    if not stripped:
        return "empty"
    if is_resource_or_script_string(text):
        return "resource"
    if is_quoted_line(text):
        return "dialogue"
    if text.startswith(FULLWIDTH_SPACE):
        return "narration"
    if is_likely_speaker(text):
        return "speaker"
    if jp_score(text) >= 0.75:
        return "text"
    return "other"


def scene_id_from_path(path: Path) -> tuple[int, str]:
    match = re.match(r"^(\d+)_(.+)\.k1k2\.bin$", path.name)
    if not match:
        raise ValueError(f"unexpected decoded scene filename: {path.name}")
    return int(match.group(1)), match.group(2)


def extract_scene_strings(path: Path) -> list[SceneString]:
    blob = path.read_bytes()
    pairs = parse_header_pairs(blob)
    scene_index, scene_name = scene_id_from_path(path)

    idx_off, idx_count = pairs[1]
    buf_off, _buf_count = pairs[2]
    strings: list[SceneString] = []

    for entry_index in range(idx_count):
        entry_off = idx_off + entry_index * 8
        char_offset = u32(blob, entry_off)
        char_len = u32(blob, entry_off + 4)
        raw_start = buf_off + char_offset * 2
        raw_end = raw_start + char_len * 2
        if raw_start < 0 or raw_end > len(blob):
            raise ValueError(
                f"{path.name}: string {entry_index} points outside blob "
                f"(0x{raw_start:X}..0x{raw_end:X})"
            )
        text = decode_utf16_xor(blob[raw_start:raw_end], entry_index)
        strings.append(
            SceneString(
                scene_index=scene_index,
                scene_name=scene_name,
                string_index=entry_index,
                char_offset=char_offset,
                char_len=char_len,
                xor_key=f"0x{(entry_index * XOR_MULTIPLIER) & 0xFFFF:04X}",
                kind=classify_string(text),
                text=text,
            )
        )

    return strings


def build_dialogue_lines(strings: list[SceneString], choice_indices: set[int] | None = None) -> list[DialogueLine]:
    lines: list[DialogueLine] = []
    pending_speaker: str | None = None
    choice_indices = choice_indices or set()
    speaker_context_indices: set[int] = set()

    pending_context_index: int | None = None
    for current in strings:
        if current.kind == "speaker":
            pending_context_index = current.string_index
            continue
        if current.kind == "dialogue" or (current.kind == "text" and is_parenthetical_text(current.text)):
            if pending_context_index is not None:
                speaker_context_indices.add(pending_context_index)
            pending_context_index = None
            continue
        if current.kind not in {"empty", "resource"}:
            pending_context_index = None

    inline_fragment_indices: set[int] = set()
    for index, current in enumerate(strings):
        if current.kind != "speaker" or current.string_index in speaker_context_indices:
            continue
        if not has_japanese(current.text):
            continue
        neighbors = [
            strings[index - 1] if index > 0 else None,
            strings[index + 1] if index + 1 < len(strings) else None,
        ]
        has_visible_neighbor = any(
            neighbor is not None
            and neighbor.kind not in {"empty", "resource"}
            and not is_resource_or_script_string(neighbor.text)
            for neighbor in neighbors
        )
        if has_visible_neighbor:
            inline_fragment_indices.add(current.string_index)

    for index, current in enumerate(strings):
        text = current.text
        kind = current.kind
        next_string = strings[index + 1] if index + 1 < len(strings) else None
        next_is_dialogue = bool(next_string and next_string.kind == "dialogue")

        if kind == "empty":
            continue

        if kind == "resource":
            pending_speaker = None
            continue

        if current.string_index in choice_indices:
            display_text = normalize_display_text(text)
            lines.append(
                DialogueLine(
                    scene_index=current.scene_index,
                    scene_name=current.scene_name,
                    line_index=len(lines),
                    string_index=current.string_index,
                    kind="choice",
                    speaker=None,
                    raw_text=text,
                    text=display_text,
                    text_for_translation=display_text.lstrip(FULLWIDTH_SPACE),
                    quote_open_count=0,
                    quote_close_count=0,
                )
            )
            pending_speaker = None
            continue

        if current.string_index in inline_fragment_indices:
            display_text = normalize_display_text(text)
            quote_open_count, quote_close_count = edge_quote_counts(text)
            lines.append(
                DialogueLine(
                    scene_index=current.scene_index,
                    scene_name=current.scene_name,
                    line_index=len(lines),
                    string_index=current.string_index,
                    kind="text",
                    speaker=None,
                    raw_text=text,
                    text=display_text,
                    text_for_translation=display_text.lstrip(FULLWIDTH_SPACE),
                    quote_open_count=quote_open_count,
                    quote_close_count=quote_close_count,
                )
            )
            pending_speaker = None
            continue

        if kind == "speaker" or (next_is_dialogue and is_contextual_speaker(text)):
            pending_speaker = text.strip()
            continue

        speaker = None
        if kind == "dialogue":
            speaker = pending_speaker
            pending_speaker = None
        elif kind == "text" and is_parenthetical_text(text):
            speaker = pending_speaker
            pending_speaker = None
        elif kind in {"narration", "text", "other"}:
            pending_speaker = None

        if kind in {"dialogue", "narration"} or (kind == "text" and (is_parenthetical_text(text) or has_japanese(text))):
            display_text = normalize_display_text(text)
            quote_open_count, quote_close_count = edge_quote_counts(text)
            lines.append(
                DialogueLine(
                    scene_index=current.scene_index,
                    scene_name=current.scene_name,
                    line_index=len(lines),
                    string_index=current.string_index,
                    kind=kind,
                    speaker=speaker,
                    raw_text=text,
                    text=display_text,
                    text_for_translation=display_text.lstrip(FULLWIDTH_SPACE),
                    quote_open_count=quote_open_count,
                    quote_close_count=quote_close_count,
                )
            )

    return lines


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_csv(path: Path, rows: list[DialogueLine]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "scene_index",
                "scene_name",
                "line_index",
                "string_index",
                "kind",
                "speaker",
                "raw_text",
                "text",
                "text_for_translation",
                "quote_open_count",
                "quote_close_count",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--decoded-dir",
        type=Path,
        default=Path("_workspace/out/scenes_decoded"),
        help="directory containing *.k1k2.bin decoded scene blobs",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("_workspace/out/dialogue"),
        help="directory for extracted text output",
    )
    args = parser.parse_args()

    scene_paths = sorted(args.decoded_dir.glob("*.k1k2.bin"))
    if not scene_paths:
        raise SystemExit(f"no decoded scenes found in {args.decoded_dir}")

    args.out_dir.mkdir(parents=True, exist_ok=True)

    all_strings: list[SceneString] = []
    all_lines: list[DialogueLine] = []
    scenes: list[dict] = []

    for scene_path in scene_paths:
        scene_blob = scene_path.read_bytes()
        scene_strings = extract_scene_strings(scene_path)
        choice_indices = find_vm_choice_indices(scene_blob, scene_strings)
        scene_lines = build_dialogue_lines(scene_strings, choice_indices)
        all_strings.extend(scene_strings)
        all_lines.extend(scene_lines)
        scenes.append(
            {
                "scene_index": scene_strings[0].scene_index if scene_strings else None,
                "scene_name": scene_strings[0].scene_name if scene_strings else scene_path.stem,
                "string_count": len(scene_strings),
                "line_count": len(scene_lines),
                "lines": [asdict(line) for line in scene_lines],
            }
        )

    write_jsonl(args.out_dir / "scene_strings.jsonl", [asdict(row) for row in all_strings])
    write_jsonl(args.out_dir / "dialogue_lines.jsonl", [asdict(row) for row in all_lines])
    write_csv(args.out_dir / "dialogue_lines.csv", all_lines)

    summary = {
        "decoder": {
            "main_string_table": "utf16le_code_unit ^ ((string_index * 0x7087) & 0xffff)",
            "xor_multiplier": f"0x{XOR_MULTIPLIER:04X}",
        },
        "scene_count": len(scenes),
        "string_count": len(all_strings),
        "line_count": len(all_lines),
        "outputs": {
            "all_strings_jsonl": "scene_strings.jsonl",
            "dialogue_jsonl": "dialogue_lines.jsonl",
            "dialogue_csv": "dialogue_lines.csv",
            "dialogue_json": "dialogue_lines_by_scene.json",
        },
        "scenes": scenes,
    }
    (args.out_dir / "dialogue_lines_by_scene.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
        newline="\n",
    )

    print(f"Decoded {len(all_strings):,} strings from {len(scenes)} scenes")
    print(f"Wrote {len(all_lines):,} extracted dialogue/narration/text records")
    print(f"Output directory: {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
