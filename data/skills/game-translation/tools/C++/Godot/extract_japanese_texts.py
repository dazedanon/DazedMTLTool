#!/usr/bin/env python3
"""Extract Japanese text from unpacked Godot assets into round-trip templates."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


SOURCE_DEFAULT = Path("unpacked_pck") / "assets"
OUTPUT_DEFAULT = Path("translation_templates")
MANIFEST_NAME = "translation_manifest.json"
MAX_LINES_PER_FILE = 500

ALLOWED_EXTENSIONS = {
    ".txt",
    ".po",
}

PO_DIALOGUE_SPEAKERS = {
    "merchant.po": "usa00",
}

ENCODINGS = ("utf-8-sig", "utf-8", "shift_jis", "cp932")
JAPANESE_RE = re.compile(
    r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uff66-\uff9f\u3000\u3010-\u3011]"
)
JP_QUOTED_PUNCT_RE = re.compile(
    r"^[\u300c\u300e][\s\u2026\u30fb\u3001\u3002\uff01\uff1f!??.\uff0e,\uff0c\u301c~\u30fc\u2014\u2015-]+[\u300d\u300f]$"
)
SPEAKER_LINE_RE = re.compile(r"^(\s*)([^:\uff1a]+)(\s*[:\uff1a]\s*)(.*)$")
MSGSTR_RE = re.compile(r"^(\s*msgstr\s+\")(.*)(\"\s*)$")
PATH_LIKE_RE = re.compile(
    r"^\s*[-*]?\s*['\"]?\s*(?:\.{1,2}/|\.{1,2}\\|/|[A-Za-z]:\\|[A-Za-z]:/)[^'\"\r\n]*\.[A-Za-z0-9]{2,6}\s*['\"]?\s*$",
    re.IGNORECASE,
)
SKIP_METADATA_RE = re.compile(r"^\s*(?:#|//|;|--|/\*|\\\*|<!--|-->|EOF|return|func)\b", re.IGNORECASE)
ONLY_SYMBOLS_RE = re.compile(r"^\W*$", re.UNICODE)
TAG_RE = re.compile(r"\[([A-Za-z_][A-Za-z0-9_]*)(?:=[^\]]*)?\]")
ANY_TAG_RE = re.compile(r"\[[^\]\[]+\]")
SCENARIO_DIRECTIVE_KEYS = {
    "area_\u53e3",
    "bg",
    "bgm",
    "body",
    "camera_focus",
    "cg",
    "flash",
    "posure",
    "se",
    "\u4e0a\u7740",
    "\u4e0a\u8155",
    "\u53e3",
    "\u53f3\u624b",
    "\u53f3\u811a",
    "\u5de6\u624b",
    "\u5de6\u811a",
    "\u624b\u888b",
    "\u767a\u60c5",
    "\u76ee",
    "\u30ad\u30e3\u30df",
}


@dataclass
class ManifestEntry:
    category: str
    mode: str
    file: str
    line_index: int
    encoding: str
    speaker: str | None
    source: str
    line_prefix: str
    outer_prefix: str
    outer_suffix: str
    po_prefix: str | None = None
    po_suffix: str | None = None


class SplitWriter:
    def __init__(self, base_dir: Path, prefix: str, max_lines: int) -> None:
        self.base_dir = base_dir
        self.prefix = prefix
        self.max_lines = max_lines
        self.file_count = 0
        self.line_count = 0
        self._lines_in_file = 0
        self._handle = None
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._open_next_file()

    def _open_next_file(self) -> None:
        if self._handle is not None:
            self._handle.close()
        self.file_count += 1
        self._lines_in_file = 0
        path = self.base_dir / f"{self.prefix}_{self.file_count:03d}.txt"
        self._handle = path.open("w", encoding="utf-8", newline="\n")

    def write(self, line: str) -> None:
        if self._lines_in_file >= self.max_lines:
            self._open_next_file()
        self._handle.write(line.rstrip("\n") + "\n")
        self._lines_in_file += 1
        self.line_count += 1

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None


def has_japanese(text: str) -> bool:
    return bool(JAPANESE_RE.search(text))


def has_japanese_quoted_punctuation(text: str) -> bool:
    stripped = ANY_TAG_RE.sub("", text).strip()
    return bool(JP_QUOTED_PUNCT_RE.fullmatch(stripped))


def is_translatable_text(text: str) -> bool:
    return has_japanese(text) or has_japanese_quoted_punctuation(text)


def decode_text(file_path: Path) -> tuple[str, str] | None:
    raw = file_path.read_bytes()
    if b"\x00" in raw[:4096]:
        return None
    for encoding in ENCODINGS:
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return None


def iter_source_files(assets_root: Path) -> Iterable[Path]:
    for file_path in sorted(p for p in assets_root.rglob("*") if p.is_file()):
        if file_path.suffix.lower() in ALLOWED_EXTENSIONS:
            yield file_path


def should_skip_line(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if PATH_LIKE_RE.match(stripped):
        return True
    if SKIP_METADATA_RE.match(stripped):
        return True
    if ONLY_SYMBOLS_RE.match(stripped) and not has_japanese_quoted_punctuation(stripped):
        return True
    return False


def is_scenario_directive_line(line_body: str) -> bool:
    match = SPEAKER_LINE_RE.match(line_body)
    if not match:
        return False
    indent, key, _colon, payload = match.groups()
    stripped_key = key.strip()
    if indent:
        return True
    if not payload.strip():
        return True
    return stripped_key in SCENARIO_DIRECTIVE_KEYS or stripped_key.startswith("area_")


def split_newline(line: str) -> tuple[str, str]:
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith("\n"):
        return line[:-1], "\n"
    if line.endswith("\r"):
        return line[:-1], "\r"
    return line, ""


def closing_tag_name(tag: str) -> str | None:
    match = re.fullmatch(r"\[/([A-Za-z_][A-Za-z0-9_]*)\]", tag)
    if not match:
        return None
    return match.group(1)


def opening_tag_name(tag: str) -> str | None:
    match = re.fullmatch(r"\[([A-Za-z_][A-Za-z0-9_]*)(?:=[^\]]*)?\]", tag)
    if not match:
        return None
    return match.group(1)


def split_outer_tags(text: str) -> tuple[str, str, str]:
    """Remove balanced tags that wrap the whole payload.

    Internal tags are intentionally left in the extracted text so a translator can
    keep or move them. Example: [wave]text[/wave] extracts as text, while
    text [wave]word[/wave] keeps the inner [wave] tags visible.
    """
    prefix_parts: list[str] = []
    suffix_parts: list[str] = []
    working = text.strip()

    while True:
        open_match = TAG_RE.match(working)
        if not open_match:
            break
        name = open_match.group(1)
        close_match = re.search(rf"\[/{re.escape(name)}\]\s*$", working)
        if not close_match:
            break
        prefix_parts.append(working[: open_match.end()])
        suffix_parts.insert(0, working[close_match.start() : close_match.end()].strip())
        working = working[open_match.end() : close_match.start()].strip()

    return "".join(prefix_parts), working, "".join(suffix_parts)


def unescape_po_value(text: str) -> str:
    return text.replace(r"\"", '"').replace(r"\n", r"\n").replace(r"\\", "\\")


def relpath(file_path: Path, root: Path) -> str:
    return file_path.relative_to(root).as_posix()


def parse_line(
    line_body: str,
    file_path: Path,
    assets_dir: Path,
    line_index: int,
    encoding: str,
) -> tuple[ManifestEntry, str] | None:
    stripped = line_body.strip()
    if should_skip_line(stripped):
        return None

    suffix = file_path.suffix.lower()
    file_rel = relpath(file_path, assets_dir)
    in_scenarios = "scenarios" in file_path.parts

    if suffix == ".txt" and in_scenarios and is_scenario_directive_line(line_body):
        return None

    if suffix == ".po":
        msg_match = MSGSTR_RE.match(line_body)
        if not msg_match:
            return None
        value = unescape_po_value(msg_match.group(2))
        if not value or not is_translatable_text(value):
            return None
        speaker = PO_DIALOGUE_SPEAKERS.get(file_path.name.lower())
        category = "dialogue" if speaker else "plain"
        entry = ManifestEntry(
            category=category,
            mode="po_msgstr",
            file=file_rel,
            line_index=line_index,
            encoding=encoding,
            speaker=speaker,
            source=value,
            line_prefix="",
            outer_prefix="",
            outer_suffix="",
            po_prefix=msg_match.group(1),
            po_suffix=msg_match.group(3),
        )
        if speaker:
            return entry, f"[{speaker}]: {value}"
        return entry, value

    speaker_match = SPEAKER_LINE_RE.match(line_body)
    if speaker_match:
        speaker = speaker_match.group(2).strip()
        payload = speaker_match.group(4).strip()
        outer_prefix, source, outer_suffix = split_outer_tags(payload)
        if not is_translatable_text(source):
            return None
        entry = ManifestEntry(
            category="dialogue",
            mode="speaker_payload",
            file=file_rel,
            line_index=line_index,
            encoding=encoding,
            speaker=speaker,
            source=source,
            line_prefix=f"{speaker_match.group(1)}{speaker_match.group(2)}{speaker_match.group(3)}",
            outer_prefix=outer_prefix,
            outer_suffix=outer_suffix,
        )
        return entry, f"[{speaker}]: {source}"

    if is_translatable_text(line_body) and in_scenarios:
        outer_prefix, source, outer_suffix = split_outer_tags(line_body.strip())
        if not is_translatable_text(source):
            return None
        indent = line_body[: len(line_body) - len(line_body.lstrip())]
        entry = ManifestEntry(
            category="dialogue",
            mode="narration_line",
            file=file_rel,
            line_index=line_index,
            encoding=encoding,
            speaker="Narration",
            source=source,
            line_prefix=indent,
            outer_prefix=outer_prefix,
            outer_suffix=outer_suffix,
        )
        return entry, f"[Narration]: {source}"

    if is_translatable_text(line_body):
        outer_prefix, source, outer_suffix = split_outer_tags(line_body.strip())
        if not is_translatable_text(source):
            return None
        indent = line_body[: len(line_body) - len(line_body.lstrip())]
        entry = ManifestEntry(
            category="plain",
            mode="plain_line",
            file=file_rel,
            line_index=line_index,
            encoding=encoding,
            speaker=None,
            source=source,
            line_prefix=indent,
            outer_prefix=outer_prefix,
            outer_suffix=outer_suffix,
        )
        return entry, source

    return None


def clear_previous_outputs(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for pattern in ("dialogue_template_*.txt", "plaintext_template_*.txt", MANIFEST_NAME):
        for path in out_dir.glob(pattern):
            if path.is_file():
                path.unlink()


def extract_texts(assets_dir: Path, out_dir: Path, chunk_size: int) -> None:
    if not assets_dir.exists():
        raise FileNotFoundError(f"Assets folder missing: {assets_dir}")

    clear_previous_outputs(out_dir)
    dialogue_writer = SplitWriter(out_dir, "dialogue_template", chunk_size)
    plain_writer = SplitWriter(out_dir, "plaintext_template", chunk_size)
    entries: list[ManifestEntry] = []
    skipped = 0

    for file_path in iter_source_files(assets_dir):
        decoded = decode_text(file_path)
        if decoded is None:
            continue
        text, encoding = decoded
        lines = text.splitlines(keepends=True)

        for line_index, raw_line in enumerate(lines):
            line_body, _newline = split_newline(raw_line)
            parsed = parse_line(line_body, file_path, assets_dir, line_index, encoding)
            if parsed is None:
                skipped += 1
                continue

            entry, output_line = parsed
            entries.append(entry)
            if entry.category == "dialogue":
                dialogue_writer.write(output_line)
            else:
                plain_writer.write(output_line)

    if dialogue_writer.line_count == 0:
        dialogue_writer.write("[Narration]: (no Japanese dialogue collected)")
    if plain_writer.line_count == 0:
        plain_writer.write("(no other Japanese text collected)")

    dialogue_writer.close()
    plain_writer.close()

    manifest = {
        "version": 1,
        "assets_dir": str(assets_dir),
        "dialogue_lines": sum(1 for entry in entries if entry.category == "dialogue"),
        "plain_lines": sum(1 for entry in entries if entry.category == "plain"),
        "entries": [asdict(entry) for entry in entries],
    }
    (out_dir / MANIFEST_NAME).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print("Dialogue chunks:", dialogue_writer.file_count)
    print("Plaintext chunks:", plain_writer.file_count)
    print("Dialogue lines:", manifest["dialogue_lines"])
    print("Plaintext lines:", manifest["plain_lines"])
    print("Skipped lines:", skipped)
    print("Manifest:", out_dir / MANIFEST_NAME)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract Japanese dialogue/plaintext from unpacked assets.")
    parser.add_argument(
        "assets",
        nargs="?",
        type=Path,
        default=SOURCE_DEFAULT,
        help="Root folder containing unpacked assets.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=OUTPUT_DEFAULT,
        help="Output folder for split template files.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=MAX_LINES_PER_FILE,
        help="Number of lines per output chunk file.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    extract_texts(args.assets, args.output, args.chunk_size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
