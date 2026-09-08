#!/usr/bin/env python3
import argparse
import csv
import re
from collections import Counter
from pathlib import Path


DIALOGUE_TYPES = {"dialogue", "narration"}
UI_TYPES = {"ui", "choice", "system", "note", "unknown"}
SKIP_TYPES = {"garbage", "metadata"}

SPEAKER_ALIASES = {
    "": "Unknown",
    "unknown": "Unknown",
    "Unknown": "Unknown",
    "UI": "Unknown",
    "Narrator": "Narration",
    "narration": "Narration",
    "male": "Mob",
    "Main": "Mob",
    "Female": "Unknown",
}

PREFIX_SPEAKERS = {
    "イヴ": "Ive",
    "イブ": "Ive",
    "メアリー": "Mary",
    "ゲームマスター": "GameMaster",
    "GM": "GameMaster",
}

NOTE_REASON_RE = re.compile(
    r"\b(written instructions?|instructional note|not spoken|corrupted|placeholder|non-text)\b",
    re.I,
)
MALE_REASON_RE = re.compile(r"\b(male|partner|customer|protagonist)\b", re.I)
NARRATION_REASON_RE = re.compile(r"\b(narrative|narration)\b", re.I)

MALE_TEXT_RE = re.compile(r"(俺|ちんこ|チンポ|射精|精液|声出てるな|喘ぎ方|雑魚ま)")


def read_context(path):
    with Path(path).open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader((line for line in f if not line.startswith("#")), delimiter="\t"))


def read_labels(path):
    labels = {}
    duplicates = []
    if not Path(path).exists():
        return labels, duplicates
    with Path(path).open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            row_id = row.get("id", "")
            if not row_id:
                continue
            if row_id in labels:
                duplicates.append(row_id)
            labels[row_id] = row
    return labels, duplicates


def clean_text(value):
    return re.sub(r"\s+", " ", (value or "").strip())


def strip_explicit_speaker_prefix(text):
    stripped = clean_text(text)
    match = re.match(r"^(イヴ|イブ|メアリー|ゲームマスター|GM)\s*[:：]?\s*([「『].*)$", stripped)
    if match:
        return match.group(2)
    match = re.match(r"^(Ive|Mary|GameMaster)\s*[:：]\s*(.+)$", stripped)
    if match:
        return match.group(2)
    return stripped


def speaker_from_explicit_prefix(text):
    stripped = clean_text(text)
    match = re.match(r"^(イヴ|イブ|メアリー|ゲームマスター|GM)\s*[:：]?\s*[「『]", stripped)
    if match:
        return PREFIX_SPEAKERS.get(match.group(1), "")
    match = re.match(r"^(Ive|Mary|GameMaster)\s*[:：]", stripped)
    if match:
        return match.group(1)
    return ""


def normalize_speaker(label, text_type, text):
    if text_type == "narration":
        return "Narration"
    explicit = speaker_from_explicit_prefix(text)
    if explicit:
        return explicit
    speaker = clean_text(label)
    return SPEAKER_ALIASES.get(speaker, speaker or "Unknown")


def looks_like_narration(text):
    stripped = clean_text(text)
    return stripped.startswith("ーーー") or stripped.startswith("---")


def coerce_text_type(label, context_row, text_type):
    reason = clean_text(label.get("reason", ""))
    text = clean_text(context_row.get("text", ""))
    if text_type == "dialogue" and NOTE_REASON_RE.search(reason):
        return "note"
    if text_type == "dialogue" and (looks_like_narration(text) or NARRATION_REASON_RE.search(reason)):
        return "narration"
    return text_type


def coerce_speaker(label, context_row, text_type, speaker):
    if text_type == "narration":
        return "Narration"
    if speaker != "Unknown":
        return speaker
    reason = clean_text(label.get("reason", ""))
    text = clean_text(context_row.get("text", ""))
    if MALE_REASON_RE.search(reason) or MALE_TEXT_RE.search(text):
        return "Mob"
    return speaker


def infer_fallback_type(context_row):
    bucket = context_row.get("bucket", "")
    text = context_row.get("text", "")
    if bucket == "dialogue" and looks_like_narration(text):
        return "narration"
    if bucket == "dialogue":
        return "dialogue"
    if bucket == "ui":
        return "ui"
    return "unknown"


def infer_fallback_speaker(context_row, text_type):
    if text_type == "narration":
        return "Narration"
    if text_type == "dialogue":
        text = context_row.get("text", "")
        json_file = context_row.get("json_file", "")
        if MALE_TEXT_RE.search(text):
            return "Mob"
        if "/VoiceLine/Zirai/" in json_file:
            return "Zirai"
        return "Unknown"
    return "UI"


def build_exports(context_rows, labels):
    dialogue_lines = []
    ui_lines = []
    missing = []
    skipped = []
    counts = Counter()
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
            missing.append(context_row)

        previous = last_by_offset.get(group_key)
        if previous:
            previous_type, previous_speaker = previous
            if text_type == "dialogue" and previous_type == "narration":
                text_type = previous_type
                speaker = previous_speaker
            elif speaker == "Unknown" and previous_speaker != "Unknown":
                speaker = previous_speaker

        text = context_row.get("text", "")
        counts[text_type] += 1
        if text_type in DIALOGUE_TYPES:
            dialogue_lines.append(f"[{speaker}]: {strip_explicit_speaker_prefix(text)}")
        elif text_type in UI_TYPES:
            ui_lines.append(clean_text(text))
        elif text_type in SKIP_TYPES:
            skipped.append((text_type, context_row))
        else:
            if context_row.get("bucket") == "dialogue":
                dialogue_lines.append(f"[{speaker or 'Unknown'}]: {strip_explicit_speaker_prefix(text)}")
            else:
                ui_lines.append(clean_text(text))

        if text_type in DIALOGUE_TYPES or text_type in UI_TYPES:
            if text_type != "dialogue" or speaker != "Unknown":
                last_by_offset[group_key] = (text_type, speaker)

    return dialogue_lines, ui_lines, missing, skipped, counts


def write_lines(path, lines):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="\n") as f:
        for line in lines:
            if line:
                f.write(line + "\n")


def write_missing(path, missing):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["id", "bucket", "json_file", "raw_offset", "segment_index", "segment_count", "text"],
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(missing)


def write_skipped(path, skipped):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter="\t", lineterminator="\n")
        writer.writerow(["text_type", "id", "bucket", "json_file", "raw_offset", "text"])
        for text_type, row in skipped:
            writer.writerow([text_type, row["id"], row.get("bucket", ""), row.get("json_file", ""), row.get("raw_offset", ""), row.get("text", "")])


def main():
    parser = argparse.ArgumentParser(description="Build final UI/dialogue text exports from Mistral labels.")
    parser.add_argument("--context", default=".translation_tooling/work/all_text_context.tsv")
    parser.add_argument("--labels", default=".translation_tooling/work/mistral_text_labels.tsv")
    parser.add_argument("--dialogue-out", default=".translation_tooling/work/dialogue.txt")
    parser.add_argument("--ui-out", default=".translation_tooling/work/ui.txt")
    parser.add_argument("--missing-out", default=".translation_tooling/work/mistral_missing_ids.tsv")
    parser.add_argument("--skipped-out", default=".translation_tooling/work/labeled_skipped.tsv")
    args = parser.parse_args()

    context_rows = read_context(args.context)
    labels, duplicates = read_labels(args.labels)
    dialogue_lines, ui_lines, missing, skipped, counts = build_exports(context_rows, labels)

    write_lines(args.dialogue_out, dialogue_lines)
    write_lines(args.ui_out, ui_lines)
    write_missing(args.missing_out, missing)
    write_skipped(args.skipped_out, skipped)

    print(f"context rows: {len(context_rows)}")
    print(f"label rows: {len(labels)}")
    print(f"duplicate label ids: {len(duplicates)}")
    print(f"missing labels: {len(missing)}")
    print(f"dialogue lines: {len(dialogue_lines)}")
    print(f"ui lines: {len(ui_lines)}")
    print(f"skipped rows: {len(skipped)}")
    print("text type counts:")
    for key, value in counts.most_common():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
