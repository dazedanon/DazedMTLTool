#!/usr/bin/env python3
"""Inject translated template lines back into unpacked Godot asset text files."""

from __future__ import annotations

import argparse
import json
import shutil
import re
from pathlib import Path
from typing import Any

from patch_punctuation_only_dialogue import patch_line as patch_punctuation_quote_line


SOURCE_DEFAULT = Path("unpacked_pck") / "assets"
TEMPLATES_DEFAULT = Path("translation_templates")
OUTPUT_DEFAULT = Path("translated_assets")
MANIFEST_NAME = "translation_manifest.json"
DIALOGUE_LABEL_RE = re.compile(r"^\[[^\]]+\]:\s*(.*)$")


def split_newline(line: str) -> tuple[str, str]:
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith("\n"):
        return line[:-1], "\n"
    if line.endswith("\r"):
        return line[:-1], "\r"
    return line, ""


def read_template_lines(templates_dir: Path, prefix: str) -> list[str]:
    lines: list[str] = []
    for path in sorted(templates_dir.glob(f"{prefix}_*.txt")):
        with path.open("r", encoding="utf-8") as handle:
            lines.extend(line.rstrip("\n").rstrip("\r") for line in handle)
    return lines


def strip_dialogue_label(line: str) -> str:
    match = DIALOGUE_LABEL_RE.match(line)
    if match:
        return match.group(1)
    return line


def escape_po_value(text: str) -> str:
    sentinels = {
        r"\n": "\u0000PO_NL\u0000",
        r"\t": "\u0000PO_TAB\u0000",
    }
    for value, sentinel in sentinels.items():
        text = text.replace(value, sentinel)
    text = text.replace("\\", "\\\\").replace('"', '\\"')
    for value, sentinel in sentinels.items():
        text = text.replace(sentinel, value)
    return text


def load_manifest(templates_dir: Path) -> dict[str, Any]:
    manifest_path = templates_dir / MANIFEST_NAME
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing manifest: {manifest_path}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def build_translations(manifest: dict[str, Any], templates_dir: Path) -> dict[int, str]:
    dialogue_lines = [strip_dialogue_label(line) for line in read_template_lines(templates_dir, "dialogue_template")]
    plain_lines = read_template_lines(templates_dir, "plaintext_template")
    dialogue_index = 0
    plain_index = 0
    translations: dict[int, str] = {}

    for index, entry in enumerate(manifest["entries"]):
        if entry["category"] == "dialogue":
            if dialogue_index >= len(dialogue_lines):
                raise ValueError("Not enough dialogue template lines for manifest entries.")
            translations[index] = dialogue_lines[dialogue_index]
            dialogue_index += 1
        elif entry["category"] == "plain":
            if plain_index >= len(plain_lines):
                raise ValueError("Not enough plaintext template lines for manifest entries.")
            translations[index] = plain_lines[plain_index]
            plain_index += 1

    if dialogue_index != len(dialogue_lines):
        raise ValueError(f"Unused dialogue template lines: {len(dialogue_lines) - dialogue_index}")
    if plain_index != len(plain_lines):
        raise ValueError(f"Unused plaintext template lines: {len(plain_lines) - plain_index}")

    return translations


def copy_assets(source_assets: Path, output_assets: Path) -> None:
    source_resolved = source_assets.resolve()
    output_resolved = output_assets.resolve()
    if source_resolved == output_resolved:
        raise ValueError("Output assets folder must be different from the source assets folder.")
    if source_resolved in output_resolved.parents:
        raise ValueError("Output assets folder cannot be inside the source assets folder.")
    if output_assets.exists():
        shutil.rmtree(output_assets)
    shutil.copytree(source_assets, output_assets)


def rewrite_line(entry: dict[str, Any], translation: str, original_line: str) -> str:
    _body, newline = split_newline(original_line)
    translation, _punctuation_changes = patch_punctuation_quote_line(translation)
    mode = entry["mode"]

    if mode in {"speaker_payload", "narration_line", "plain_line"}:
        return (
            entry["line_prefix"]
            + entry["outer_prefix"]
            + translation
            + entry["outer_suffix"]
            + newline
        )

    if mode == "po_msgstr":
        return entry["po_prefix"] + escape_po_value(translation) + entry["po_suffix"] + newline

    raise ValueError(f"Unknown injection mode: {mode}")


def inject_texts(source_assets: Path, templates_dir: Path, output_assets: Path) -> None:
    manifest = load_manifest(templates_dir)
    translations = build_translations(manifest, templates_dir)
    copy_assets(source_assets, output_assets)

    entries_by_file: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for index, entry in enumerate(manifest["entries"]):
        entries_by_file.setdefault(entry["file"], []).append((index, entry))

    files_changed = 0
    lines_changed = 0
    for rel_file, indexed_entries in entries_by_file.items():
        target_path = output_assets / Path(rel_file)
        encoding = indexed_entries[0][1]["encoding"]
        text = target_path.read_text(encoding=encoding)
        lines = text.splitlines(keepends=True)

        for index, entry in indexed_entries:
            line_index = entry["line_index"]
            if line_index >= len(lines):
                raise IndexError(f"Line index outside file: {rel_file}:{line_index + 1}")
            lines[line_index] = rewrite_line(entry, translations[index], lines[line_index])
            lines_changed += 1

        target_path.write_text("".join(lines), encoding=encoding, newline="")
        files_changed += 1

    print("Injected files:", files_changed)
    print("Injected lines:", lines_changed)
    print("Output assets:", output_assets)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inject translated templates into copied unpacked assets.")
    parser.add_argument(
        "source_assets",
        nargs="?",
        type=Path,
        default=SOURCE_DEFAULT,
        help="Original unpacked assets folder.",
    )
    parser.add_argument(
        "-t",
        "--templates",
        type=Path,
        default=TEMPLATES_DEFAULT,
        help="Folder containing translation templates and translation_manifest.json.",
    )
    parser.add_argument(
        "-o",
        "--output-assets",
        type=Path,
        default=OUTPUT_DEFAULT,
        help="Output assets folder to create.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    inject_texts(args.source_assets, args.templates, args.output_assets)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
