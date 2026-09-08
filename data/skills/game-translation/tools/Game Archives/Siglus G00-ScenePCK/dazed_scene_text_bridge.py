r"""Bridge Siglus scene dialogue to/from DazedMTLTool's low-cost Text module.

Why Text module:
  The Dazed JSON module needs wrapper keys / objects and may translate speaker
  fields separately. The Text module only sends one line of text per record, so
  this bridge exports the smallest safe payload and stores all reinjection
  metadata in a local sidecar.

Typical workflow from the game root:

  # 1) Export one compact .txt into DazedMTLTool-main/files/
  python _workspace\tools\dazed_scene_text_bridge.py export

  # 2) In DazedMTLTool, pick the Text module and translate sodom_scene_text.txt.
  #    Dialogue rows use Dazed's native "[Speaker]: line" format. A compact
  #    speaker glossary is exported first because Dazed strips speaker tags
  #    from translated dialogue output.

  # 3) Import/inject the Dazed translated text into a rebuilt Scene.pck copy
  python _workspace\tools\dazed_scene_text_bridge.py inject

The inject command writes _workspace/out/dazed/Scene.pck by default. Use
--replace only after testing; it makes a timestamped backup of the live Scene.pck.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import shutil
import struct
import sys
import textwrap
from dataclasses import asdict, dataclass
from pathlib import Path



# Import the already verified Scene.pck codec from the first-line injection test.
TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))
from patch_first_line import decode_chunk, encode_chunk, parse_pairs, put_u32, u32  # noqa: E402


ROOT = Path(__file__).resolve().parents[2]
DAZED_ROOT = Path(r"C:\Users\sw\Downloads\DazedMTLTool-main")
DEFAULT_DIALOGUE_JSONL = ROOT / "_workspace" / "out" / "dialogue" / "dialogue_lines.jsonl"
DEFAULT_SCENE_STRINGS_JSONL = ROOT / "_workspace" / "out" / "dialogue" / "scene_strings.jsonl"
DEFAULT_OUT_DIR = ROOT / "_workspace" / "out" / "dazed"
DEFAULT_STEM = "sodom_scene_text"
DEFAULT_EXPORT_TXT = DAZED_ROOT / "files" / f"{DEFAULT_STEM}.txt"
DEFAULT_TRANSLATED_TXT = DAZED_ROOT / "translated" / f"{DEFAULT_STEM}.txt"
DEFAULT_MANIFEST = DEFAULT_OUT_DIR / f"{DEFAULT_STEM}.manifest.jsonl"
DEFAULT_TRANSLATIONS = DEFAULT_OUT_DIR / f"{DEFAULT_STEM}.translated.jsonl"
DEFAULT_PATCHED_PCK = DEFAULT_OUT_DIR / "Scene.pck"
DEFAULT_PCK = ROOT / "Scene.pck"
DEFAULT_WRAP_WIDTH = 72

XOR_MULTIPLIER = 0x7087
FULLWIDTH_SPACE = "\u3000"
JP_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uff61-\uff9f]")
JP_PUNCT_RE = re.compile(r"[\u300c\u300d\u300e\u300f\uff08\uff09\uff01\uff1f\u3002\u3001\u2026]")
NARRATION_CONTEXT = "Narration"
CHOICE_CONTEXT = "Choice"
SPEAKER_SPLIT_PATTERNS = (
    re.compile(r"^\s*\[(?P<speaker>[^\]\r\n]{1,80})\]\s*[:：]\s*(?P<text>.+?)\s*$"),
    re.compile(r"^\s*(?P<speaker>[^:\r\n]{1,80}?)\s*::\s*(?P<text>.+?)\s*$"),
)
WRAPPABLE_KINDS = {"dialogue", "narration", "text"}
STRIP_FULLWIDTH_INDENT_KINDS = {"narration", "text"}
SPEAKER_TRANSLATION_OVERRIDES = {
    "\u5973\u683c\u95d8\u5bb6\uff0f\u30cd\u30eb\u30b6": "Nelza",
    "\u30a2\u30ca\u30b9\u30bf\u30b7\u30a2\uff0f\u8b0e\u306e\u5c11\u5973": "Anastasia",
    "\u30d1\u30e1\u30e9\uff0f\uff1f\uff1f\uff1f": "Pamela",
    "\u30d6\u30b8\u30a7\u30ed\uff0f\uff1f\uff1f\uff1f": "Bujero",
    "\u30ea\u30ea\u30fc\u30ca\uff0f\uff1f\uff1f\uff1f": "Lilina",
}
SPEAKER_DESCRIPTOR_RE = re.compile(
    r"\b(?:female|male|mysterious|unknown|martial artist|girl|boy|man|woman)\b|\?{2,}",
    re.IGNORECASE,
)


@dataclass
class BridgeRecord:
    order: int
    scene_index: int
    scene_name: str
    line_index: int
    string_index: int
    kind: str
    speaker: str | None
    source: str
    raw_text: str
    text: str
    quote_open_count: int
    quote_close_count: int
    speaker_string_index: int | None = None
    speaker_source: str | None = None
    export_line: str = ""
    record_type: str = "text"


def utf16_units(text: str) -> list[int]:
    raw = text.encode("utf-16-le", errors="surrogatepass")
    if len(raw) % 2:
        raise ValueError("UTF-16LE encoding produced an odd byte count")
    return list(struct.unpack("<" + "H" * (len(raw) // 2), raw))


def units_to_text(units: list[int]) -> str:
    raw = struct.pack("<" + "H" * len(units), *units) if units else b""
    return raw.decode("utf-16-le", errors="surrogatepass")


def read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def has_japanese(text: str) -> bool:
    return bool(JP_RE.search(text or ""))


def is_translator_visible_source(source: str, kind: str = "") -> bool:
    if has_japanese(source):
        return True
    # Punctuation-only lines such as 「……………………」 still appear in the
    # dialogue window and can carry speaker nameplates, so they must round trip.
    return kind in WRAPPABLE_KINDS and bool(JP_PUNCT_RE.search(source or ""))


def one_line(text: str) -> str:
    return (text or "").replace("\r", " ").replace("\n", " ").strip()


def dazed_context_line(speaker: str | None, source: str, kind: str = "") -> str:
    if speaker:
        context = one_line(speaker)
    elif kind == "choice":
        context = CHOICE_CONTEXT
    else:
        context = NARRATION_CONTEXT
    return f"[{context}]: {one_line(source)}"


def speaker_strings_by_scene(scene_strings_jsonl: Path) -> dict[int, list[tuple[int, str]]]:
    by_scene: dict[int, list[tuple[int, str]]] = {}
    for row in read_jsonl(scene_strings_jsonl):
        if row.get("kind") != "speaker":
            continue
        by_scene.setdefault(int(row["scene_index"]), []).append((int(row["string_index"]), row.get("text") or ""))
    for entries in by_scene.values():
        entries.sort()
    return by_scene


def find_speaker_string_index(
    speakers: dict[int, list[tuple[int, str]]], scene_index: int, string_index: int, speaker: str | None
) -> int | None:
    if not speaker:
        return None
    found: int | None = None
    for candidate_index, candidate_text in speakers.get(scene_index, []):
        if candidate_index >= string_index:
            break
        if candidate_text == speaker:
            found = candidate_index
    return found


def export_records(dialogue_jsonl: Path, scene_strings_jsonl: Path) -> list[BridgeRecord]:
    speakers = speaker_strings_by_scene(scene_strings_jsonl)
    content_records: list[BridgeRecord] = []
    speaker_sources: dict[str, None] = {}
    for row in read_jsonl(dialogue_jsonl):
        source = (row.get("text_for_translation") or "").strip()
        if not source or not is_translator_visible_source(source, row.get("kind", "")):
            continue
        scene_index = int(row["scene_index"])
        string_index = int(row["string_index"])
        speaker = row.get("speaker")
        speaker_string_index = find_speaker_string_index(speakers, scene_index, string_index, speaker)
        if speaker:
            speaker_sources.setdefault(one_line(speaker), None)
        content_records.append(
            BridgeRecord(
                order=0,
                scene_index=scene_index,
                scene_name=row["scene_name"],
                line_index=int(row["line_index"]),
                string_index=string_index,
                kind=row.get("kind", ""),
                speaker=speaker,
                source=source,
                raw_text=row.get("raw_text", ""),
                text=row.get("text", ""),
                quote_open_count=int(row.get("quote_open_count") or 0),
                quote_close_count=int(row.get("quote_close_count") or 0),
                speaker_string_index=speaker_string_index,
                speaker_source=speaker,
                export_line=dazed_context_line(speaker, source, row.get("kind", "")),
                record_type="text",
            )
        )

    speaker_records = [
        BridgeRecord(
            order=0,
            scene_index=-1,
            scene_name="",
            line_index=-1,
            string_index=-1,
            kind="speaker_name",
            speaker=None,
            source=speaker,
            raw_text=speaker,
            text=speaker,
            quote_open_count=0,
            quote_close_count=0,
            speaker_string_index=None,
            speaker_source=speaker,
            export_line=speaker,
            record_type="speaker_name",
        )
        for speaker in speaker_sources
        if speaker
    ]

    records = speaker_records + content_records
    for order, record in enumerate(records):
        record.order = order
    return records


def backup_if_exists(path: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_name(f"{path.name}.bak_{stamp}")
    shutil.copy2(path, backup)
    return backup


def cmd_export(args: argparse.Namespace) -> int:
    records = export_records(args.dialogue_jsonl, args.scene_strings_jsonl)
    if not records:
        raise SystemExit(f"no translatable records found in {args.dialogue_jsonl}")

    args.dazed_txt.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)

    backup = None
    if args.dazed_txt.exists() and not args.force:
        backup = backup_if_exists(args.dazed_txt)

    with args.dazed_txt.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            # Dazed Text translates every non-empty line. Dialogue/text records
            # use its native [Speaker]: line format; speaker glossary records
            # are plain names so their translations survive in output.
            handle.write(record.export_line + "\n")

    write_jsonl(args.manifest, [asdict(record) for record in records])

    speaker_glossary = sum(1 for record in records if record.record_type == "speaker_name")
    content_count = sum(1 for record in records if record.record_type == "text")
    speaker_context = sum(1 for record in records if record.record_type == "text" and record.speaker)
    speaker_patchable = sum(1 for record in records if record.speaker_string_index is not None)
    print(f"Exported {len(records):,} lines for Dazed Text module")
    print(f"Content lines: {content_count:,}")
    print(f"Speaker glossary lines: {speaker_glossary:,}")
    print(f"Dazed-native speaker-context dialogue lines: {speaker_context:,} ({speaker_patchable:,} patchable entries)")
    print(f"Dazed input: {args.dazed_txt}")
    print(f"Manifest:    {args.manifest}")
    if backup:
        print(f"Previous Dazed input backed up: {backup}")
    print("Select the DazedMTLTool Text module for this file.")
    return 0


def load_manifest(path: Path) -> list[BridgeRecord]:
    records = []
    for row in read_jsonl(path):
        row.setdefault("speaker_string_index", None)
        row.setdefault("speaker_source", row.get("speaker"))
        row.setdefault("export_line", row.get("source", ""))
        row.setdefault("record_type", "text")
        records.append(BridgeRecord(**row))
    records.sort(key=lambda item: item.order)
    return records


def read_translated_lines(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8-sig")
    # Keep trailing empty translations if present, but do not add a fake final line.
    lines = text.splitlines()
    return [line.rstrip("\r\n") for line in lines]


def split_translated_speaker_line(record: BridgeRecord, line: str) -> tuple[str | None, str, bool]:
    text = line.strip()
    if record.record_type == "speaker_name":
        return None, normalize_speaker_translation(record.source, text), False

    for pattern in SPEAKER_SPLIT_PATTERNS:
        match = pattern.match(text)
        if not match:
            continue
        speaker = match.group("speaker").strip()
        body = match.group("text").strip()
        if speaker and body:
            if record.speaker:
                return normalize_speaker_translation(record.speaker_source or record.speaker, speaker), body, False
            return None, body, False

    # Dazed's Text module normally strips [Speaker]: from translated dialogue,
    # so a body-only line is expected and not a parse failure.
    return None, text, False


def normalize_speaker_translation(source: str | None, translation: str) -> str:
    text = (translation or "").strip()
    source_key = (source or "").strip()
    if source_key in SPEAKER_TRANSLATION_OVERRIDES:
        return SPEAKER_TRANSLATION_OVERRIDES[source_key]

    if "/" not in text:
        return text

    parts = [part.strip() for part in text.split("/") if part.strip()]
    candidates = [part for part in parts if not SPEAKER_DESCRIPTOR_RE.search(part)]
    if candidates:
        return min(candidates, key=len)
    return parts[0] if parts else text


def build_translations(manifest: Path, translated_txt: Path) -> list[dict]:
    records = load_manifest(manifest)
    lines = read_translated_lines(translated_txt)
    if len(lines) != len(records):
        raise ValueError(
            f"translated line count mismatch: got {len(lines):,}, expected {len(records):,}. "
            "Do not edit line count in the Dazed text file."
        )

    out = []
    for record, translation in zip(records, lines):
        speaker_translation, body_translation, speaker_parse_failed = split_translated_speaker_line(record, translation)
        out.append(
            {
                **asdict(record),
                "speaker_translation": speaker_translation,
                "translation": body_translation.strip(),
                "speaker_parse_failed": speaker_parse_failed,
            }
        )
    return out


def restore_storage_adornments(record: dict, translation: str) -> str:
    """Restore script storage details that we removed to save translation cost."""
    text = translation.strip()
    raw_text = record.get("raw_text") or ""

    # Dazed's Text module strips line whitespace before translation. Restore the
    # original script-side leading/trailing whitespace so round trips preserve
    # layout bytes even when the model only sees the meaningful text.
    edge_ws = " \t" + FULLWIDTH_SPACE
    leading_len = len(raw_text) - len(raw_text.lstrip(edge_ws))
    trailing_len = len(raw_text) - len(raw_text.rstrip(edge_ws))
    leading = raw_text[:leading_len]
    trailing = raw_text[len(raw_text) - trailing_len :] if trailing_len else ""
    if leading and not text.startswith(leading):
        text = leading + text.lstrip(edge_ws)
    if trailing and not text.endswith(trailing):
        text = text.rstrip(edge_ws) + trailing

    # If the translated text still uses Japanese corner quotes and the original
    # stored repeated edge quotes, expand back to the original storage form. The
    # renderer collapses these visually. If the translation uses normal English
    # quotes, leave it alone.
    open_count = int(record.get("quote_open_count") or 0)
    close_count = int(record.get("quote_close_count") or 0)
    if open_count > 1 and text.startswith("「"):
        text = "「" * open_count + text.lstrip("「")
    if close_count > 1 and text.endswith("」"):
        text = text.rstrip("」") + "」" * close_count
    return text


def wrap_visible_translation(record: dict, text: str, wrap_width: int) -> str:
    if wrap_width <= 0:
        return text
    if record.get("record_type") == "speaker_name" or record.get("kind") not in WRAPPABLE_KINDS:
        return text

    edge_ws = " \t" + FULLWIDTH_SPACE
    leading_len = len(text) - len(text.lstrip(edge_ws))
    trailing_len = len(text) - len(text.rstrip(edge_ws))
    leading = text[:leading_len]
    trailing = text[len(text) - trailing_len :] if trailing_len else ""
    body = text[leading_len : len(text) - trailing_len if trailing_len else len(text)].strip(edge_ws)
    if len(body) <= wrap_width:
        return text

    wrapper = textwrap.TextWrapper(
        width=wrap_width,
        break_long_words=False,
        break_on_hyphens=False,
        replace_whitespace=False,
        drop_whitespace=True,
    )
    wrapped_lines: list[str] = []
    for paragraph in re.split(r"\r\n|\r|\n", body):
        if not paragraph:
            wrapped_lines.append(paragraph)
            continue
        wrapped_lines.extend(wrapper.wrap(paragraph) or [paragraph])

    if len(wrapped_lines) <= 1:
        return text
    return leading + "\n".join(wrapped_lines) + trailing


def strip_english_fullwidth_indent(record: dict, text: str) -> str:
    if record.get("record_type") == "speaker_name" or record.get("kind") not in STRIP_FULLWIDTH_INDENT_KINDS:
        return text
    return text.lstrip(FULLWIDTH_SPACE)


def scene_header_pairs(blob: bytes) -> list[tuple[int, int]]:
    if len(blob) < 0x84 or u32(blob, 0) != 0x84:
        raise ValueError("unexpected decoded scene blob header")
    return [(u32(blob, 4 + i * 8), u32(blob, 8 + i * 8)) for i in range(16)]


def decode_string_units_from_table(blob: bytes, pairs: list[tuple[int, int]], entry_index: int) -> list[int]:
    idx_off, idx_count = pairs[1]
    if not 0 <= entry_index < idx_count:
        raise IndexError(f"string index {entry_index} outside table count {idx_count}")
    buf_off, _ = pairs[2]
    char_off = u32(blob, idx_off + entry_index * 8)
    char_len = u32(blob, idx_off + entry_index * 8 + 4)
    start = buf_off + char_off * 2
    raw = blob[start : start + char_len * 2]
    if len(raw) != char_len * 2:
        raise ValueError("string table entry points outside scene blob")
    key = (entry_index * XOR_MULTIPLIER) & 0xFFFF
    stored = struct.unpack("<" + "H" * char_len, raw) if char_len else []
    return [value ^ key for value in stored]


def encode_string_units_for_table(units: list[int], entry_index: int) -> bytes:
    key = (entry_index * XOR_MULTIPLIER) & 0xFFFF
    stored = [(value ^ key) & 0xFFFF for value in units]
    return struct.pack("<" + "H" * len(stored), *stored) if stored else b""


def next_segment_offset_after(pairs: list[tuple[int, int]], offset: int, blob_size: int) -> int:
    candidates = [off for off, _ in pairs if off > offset]
    return min(candidates) if candidates else blob_size


def patch_scene_blob(scene_blob: bytes, replacements: dict[int, str]) -> bytes:
    if not replacements:
        return scene_blob

    pairs = scene_header_pairs(scene_blob)
    idx_off, idx_count = pairs[1]
    buf_off, _ = pairs[2]
    old_buf_end = next_segment_offset_after(pairs, buf_off, len(scene_blob))

    new_index = bytearray(scene_blob[idx_off : idx_off + idx_count * 8])
    new_buffer = bytearray()

    for entry_index in range(idx_count):
        if entry_index in replacements:
            units = utf16_units(replacements[entry_index])
        else:
            units = decode_string_units_from_table(scene_blob, pairs, entry_index)

        char_off = len(new_buffer) // 2
        char_len = len(units)
        struct.pack_into("<II", new_index, entry_index * 8, char_off, char_len)
        new_buffer.extend(encode_string_units_for_table(units, entry_index))

    delta = len(new_buffer) - (old_buf_end - buf_off)
    patched_prefix = bytearray(scene_blob[:buf_off])
    patched_prefix[idx_off : idx_off + len(new_index)] = new_index

    # Shift every segment that originally lived after the string buffer.
    for pair_index, (off, count) in enumerate(pairs):
        if off > buf_off:
            put_u32(patched_prefix, 4 + pair_index * 8, off + delta)
            put_u32(patched_prefix, 8 + pair_index * 8, count)

    return bytes(patched_prefix) + bytes(new_buffer) + scene_blob[old_buf_end:]


def build_replacement_map(translations: list[dict], wrap_width: int = DEFAULT_WRAP_WIDTH) -> dict[int, dict[int, str]]:
    by_scene: dict[int, dict[int, str]] = {}
    seen: dict[tuple[int, int], str] = {}
    speaker_glossary: dict[str, str] = {}

    def add_replacement(scene_index: int, string_index: int, final_text: str, label: str) -> None:
        key = (scene_index, string_index)
        if key in seen and seen[key] != final_text:
            print(
                f"Warning: duplicate {label} replacement for scene {scene_index} string {string_index}; "
                "keeping the first translation",
                file=sys.stderr,
            )
            return
        seen[key] = final_text
        by_scene.setdefault(scene_index, {})[string_index] = final_text

    for row in translations:
        if row.get("record_type") != "speaker_name":
            continue
        source = (row.get("speaker_source") or row.get("source") or "").strip()
        translation = normalize_speaker_translation(source, row.get("translation") or "")
        if source and translation and source not in speaker_glossary:
            speaker_glossary[source] = translation

    for row in translations:
        if row.get("record_type") == "speaker_name":
            continue
        translation = (row.get("translation") or "").strip()
        scene_index = int(row["scene_index"])
        if translation:
            string_index = int(row["string_index"])
            final_text = restore_storage_adornments(row, translation)
            final_text = strip_english_fullwidth_indent(row, final_text)
            final_text = wrap_visible_translation(row, final_text, wrap_width)
            add_replacement(scene_index, string_index, final_text, "text")

        speaker_source = (row.get("speaker_source") or row.get("speaker") or "").strip()
        speaker_translation = normalize_speaker_translation(
            speaker_source, row.get("speaker_translation") or speaker_glossary.get(speaker_source) or ""
        )
        speaker_string_index = row.get("speaker_string_index")
        if speaker_translation and speaker_string_index is not None:
            add_replacement(scene_index, int(speaker_string_index), speaker_translation, "speaker")
    return by_scene


def build_patched_pck(data: bytes, translations: list[dict], wrap_width: int = DEFAULT_WRAP_WIDTH) -> bytes:
    pairs = parse_pairs(data)
    data_idx_off, scene_count = pairs[8]
    data_buf_off, _ = pairs[9]
    replacements_by_scene = build_replacement_map(translations, wrap_width=wrap_width)

    entries = []
    for scene_index in range(scene_count):
        entry_off = data_idx_off + scene_index * 8
        byte_off = u32(data, entry_off)
        byte_len = u32(data, entry_off + 4)
        entries.append((byte_off, byte_len))

    old_data_size = max(byte_off + byte_len for byte_off, byte_len in entries)
    old_data_end = data_buf_off + old_data_size
    tail = data[old_data_end:]

    prefix = bytearray(data[:data_buf_off])
    new_data_buf = bytearray()
    patched_scene_count = 0
    patched_string_count = 0

    for scene_index, (byte_off, byte_len) in enumerate(entries):
        chunk = data[data_buf_off + byte_off : data_buf_off + byte_off + byte_len]
        replacements = replacements_by_scene.get(scene_index, {})
        if replacements:
            decoded = decode_chunk(chunk)
            patched = patch_scene_blob(decoded, replacements)
            chunk = encode_chunk(patched)
            # Verify the encoded chunk before writing it into the PCK.
            if decode_chunk(chunk) != patched:
                raise ValueError(f"scene {scene_index} failed encode/decode verification")
            patched_scene_count += 1
            patched_string_count += len(replacements)

        new_off = len(new_data_buf)
        new_len = len(chunk)
        put_u32(prefix, data_idx_off + scene_index * 8, new_off)
        put_u32(prefix, data_idx_off + scene_index * 8 + 4, new_len)
        new_data_buf.extend(chunk)

    print(f"Patched scenes:  {patched_scene_count:,}")
    print(f"Patched strings: {patched_string_count:,}")
    print(f"Scene data:      {old_data_size:,} -> {len(new_data_buf):,} bytes")
    print(f"Preserved tail:  {len(tail):,} bytes")
    return bytes(prefix) + bytes(new_data_buf) + tail


def cmd_import(args: argparse.Namespace) -> int:
    rows = build_translations(args.manifest, args.translated_txt)
    write_jsonl(args.output, rows)
    content_rows = [row for row in rows if row.get("record_type") != "speaker_name"]
    speaker_rows = [row for row in rows if row.get("record_type") == "speaker_name"]
    untranslated = sum(1 for row in content_rows if has_japanese(row.get("translation", "")))
    untranslated_speakers = sum(
        1
        for row in rows
        if has_japanese(
            (row.get("translation") or "")
            if row.get("record_type") == "speaker_name"
            else (row.get("speaker_translation") or "")
        )
    )
    speaker_parse_failed = sum(1 for row in rows if row.get("speaker_parse_failed"))
    empty = sum(1 for row in content_rows if not row.get("translation"))
    print(f"Imported {len(rows):,} translated lines")
    print(f"Content lines: {len(content_rows):,}")
    print(f"Speaker glossary lines: {len(speaker_rows):,}")
    print(f"Output: {args.output}")
    if untranslated:
        print(f"Warning: {untranslated:,} translated lines still contain Japanese-range text")
    if untranslated_speakers:
        print(f"Warning: {untranslated_speakers:,} translated speaker names still contain Japanese-range text")
    if speaker_parse_failed:
        print(f"Warning: {speaker_parse_failed:,} speaker-context lines did not keep a parseable prefix")
    if empty:
        print(f"Warning: {empty:,} translated lines are empty and will be skipped by inject")
    return 0


def cmd_inject(args: argparse.Namespace) -> int:
    translations = build_translations(args.manifest, args.translated_txt)
    write_jsonl(args.translations_out, translations)
    speaker_parse_failed = sum(1 for row in translations if row.get("speaker_parse_failed"))
    if speaker_parse_failed:
        print(
            f"Warning: {speaker_parse_failed:,} speaker-context lines did not keep a parseable prefix; "
            "those speakers will not be injected separately",
            file=sys.stderr,
        )
    patched = build_patched_pck(args.pck.read_bytes(), translations, wrap_width=args.wrap_width)

    if args.replace:
        stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = args.pck.with_name(f"{args.pck.name}.bak_before_dazed_{stamp}")
        shutil.copy2(args.pck, backup)
        args.pck.write_bytes(patched)
        print(f"Backup written: {backup}")
        print(f"Replaced live PCK: {args.pck}")
    else:
        args.output_pck.parent.mkdir(parents=True, exist_ok=True)
        args.output_pck.write_bytes(patched)
        print(f"Wrote patched PCK copy: {args.output_pck}")
        print("Live Scene.pck was not replaced. Use --replace after testing this copy.")
    print(f"Wrap width: {args.wrap_width if args.wrap_width > 0 else 'disabled'}")
    print(f"Translation sidecar: {args.translations_out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    export = sub.add_parser("export", help="export compact Dazed Text input")
    export.add_argument("--dialogue-jsonl", type=Path, default=DEFAULT_DIALOGUE_JSONL)
    export.add_argument("--scene-strings-jsonl", type=Path, default=DEFAULT_SCENE_STRINGS_JSONL)
    export.add_argument("--dazed-txt", type=Path, default=DEFAULT_EXPORT_TXT)
    export.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    export.add_argument("--force", action="store_true", help="overwrite existing Dazed file without backup")
    export.set_defaults(func=cmd_export)

    imp = sub.add_parser("import", help="read Dazed translated text into a mapped JSONL sidecar")
    imp.add_argument("--translated-txt", type=Path, default=DEFAULT_TRANSLATED_TXT)
    imp.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    imp.add_argument("--output", type=Path, default=DEFAULT_TRANSLATIONS)
    imp.set_defaults(func=cmd_import)

    inj = sub.add_parser("inject", help="inject Dazed translated text into a rebuilt Scene.pck")
    inj.add_argument("--translated-txt", type=Path, default=DEFAULT_TRANSLATED_TXT)
    inj.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    inj.add_argument("--translations-out", type=Path, default=DEFAULT_TRANSLATIONS)
    inj.add_argument("--pck", type=Path, default=DEFAULT_PCK)
    inj.add_argument("--output-pck", type=Path, default=DEFAULT_PATCHED_PCK)
    inj.add_argument("--wrap-width", type=int, default=DEFAULT_WRAP_WIDTH, help="insert English line breaks at this width; use 0 to disable")
    inj.add_argument("--replace", action="store_true", help="replace live Scene.pck after making a backup")
    inj.set_defaults(func=cmd_inject)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())


