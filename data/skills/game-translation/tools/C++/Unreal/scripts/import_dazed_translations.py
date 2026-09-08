#!/usr/bin/env python3
import argparse
import csv
import re
from pathlib import Path

from build_labeled_text_exports import (
    DIALOGUE_TYPES,
    SKIP_TYPES,
    UI_TYPES,
    clean_text,
    coerce_speaker,
    coerce_text_type,
    infer_fallback_speaker,
    infer_fallback_type,
    normalize_speaker,
    read_context,
    read_labels,
)


SPEAKER_TAG_RE = re.compile(r"^\[[^\]]+\]:\s*")
JP_DOTS_RE = re.compile(r"^[・･\s]+[。.]?$")


def classify_export_rows(context_rows, labels):
    dialogue_ids = []
    ui_ids = []
    skipped_ids = []
    missing_ids = []
    last_by_offset = {}

    for context_row in context_rows:
        row_id = context_row["id"]
        group_key = (context_row.get("json_file", ""), context_row.get("raw_offset", ""))
        label = labels.get(row_id)
        if label:
            text_type = clean_text(label.get("text_type")).lower() or infer_fallback_type(context_row)
            text_type = coerce_text_type(label, context_row, text_type)
            speaker = normalize_speaker(label.get("speaker", ""), text_type, context_row.get("text", ""))
            speaker = coerce_speaker(label, context_row, text_type, speaker)
        else:
            text_type = infer_fallback_type(context_row)
            speaker = infer_fallback_speaker(context_row, text_type)
            missing_ids.append(row_id)

        previous = last_by_offset.get(group_key)
        if previous:
            previous_type, previous_speaker = previous
            if text_type == "dialogue" and previous_type == "narration":
                text_type = previous_type
                speaker = previous_speaker
            elif speaker == "Unknown" and previous_speaker != "Unknown":
                speaker = previous_speaker

        if text_type in DIALOGUE_TYPES:
            dialogue_ids.append(row_id)
        elif text_type in UI_TYPES:
            ui_ids.append(row_id)
        elif text_type in SKIP_TYPES:
            skipped_ids.append(row_id)
        else:
            if context_row.get("bucket") == "dialogue":
                dialogue_ids.append(row_id)
            else:
                ui_ids.append(row_id)

        if text_type in DIALOGUE_TYPES or text_type in UI_TYPES:
            if text_type != "dialogue" or speaker != "Unknown":
                last_by_offset[group_key] = (text_type, speaker)

    return dialogue_ids, ui_ids, skipped_ids, missing_ids


def read_lines(path):
    with Path(path).open("r", encoding="utf-8-sig", newline=None) as f:
        return [line.rstrip("\r\n") for line in f]


def clean_translation(line, is_dialogue):
    value = line.strip()
    if is_dialogue:
        value = SPEAKER_TAG_RE.sub("", value).strip()
    if JP_DOTS_RE.fullmatch(value):
        return "..."
    return value


def import_translations(args):
    context_rows = read_context(args.context)
    labels, duplicates = read_labels(args.labels)
    dialogue_ids, ui_ids, skipped_ids, missing_ids = classify_export_rows(context_rows, labels)

    dialogue_lines = read_lines(args.dialogue)
    ui_lines = read_lines(args.ui)
    if len(dialogue_lines) != len(dialogue_ids):
        raise SystemExit(f"dialogue line count mismatch: {len(dialogue_lines)} translated lines for {len(dialogue_ids)} ids")
    if len(ui_lines) != len(ui_ids):
        raise SystemExit(f"ui line count mismatch: {len(ui_lines)} translated lines for {len(ui_ids)} ids")

    translated_by_id = {}
    for row_id, line in zip(dialogue_ids, dialogue_lines):
        translated_by_id[row_id] = clean_translation(line, is_dialogue=True)
    for row_id, line in zip(ui_ids, ui_lines):
        translated_by_id[row_id] = clean_translation(line, is_dialogue=False)

    csv_path = Path(args.csv)
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames

    if not fieldnames:
        raise SystemExit("could not read CSV header")

    updated = 0
    missing_csv_ids = []
    for row in rows:
        translation = translated_by_id.get(row["id"])
        if translation is None:
            continue
        row["translation"] = translation
        updated += 1

    csv_ids = {row["id"] for row in rows}
    for row_id in translated_by_id:
        if row_id not in csv_ids:
            missing_csv_ids.append(row_id)

    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    print(f"context rows: {len(context_rows)}")
    print(f"label rows: {len(labels)}")
    print(f"duplicate label ids: {len(duplicates)}")
    print(f"dialogue ids: {len(dialogue_ids)}")
    print(f"ui ids: {len(ui_ids)}")
    print(f"skipped ids: {len(skipped_ids)}")
    print(f"missing label ids: {len(missing_ids)}")
    print(f"updated CSV rows: {updated}")
    print(f"translated ids missing from CSV: {len(missing_csv_ids)}")


def main():
    parser = argparse.ArgumentParser(description="Import DazedMTLTool translated dialogue/ui text into translations.csv.")
    parser.add_argument("--context", default=".translation_tooling/work/all_text_context.tsv")
    parser.add_argument("--labels", default=".translation_tooling/work/mistral_text_labels.tsv")
    parser.add_argument("--csv", default=".translation_tooling/work/translations.csv")
    parser.add_argument("--dialogue", default=r"C:\Users\sw\Downloads\DazedMTLTool-main\translated\dialogue.txt")
    parser.add_argument("--ui", default=r"C:\Users\sw\Downloads\DazedMTLTool-main\translated\ui.txt")
    args = parser.parse_args()
    import_translations(args)


if __name__ == "__main__":
    main()
