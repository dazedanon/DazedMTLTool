#!/usr/bin/env python3
"""Build a structured translation master JSON for NoEcstasyNoLife (FortuneBride).

Dialogue lives in DT_DialogueNodes as FText records with stable loc keys
"<RowName>_SpeakerName" / "<RowName>_DialogueText". This script parses the
RawExport.Data blob, recovers per-line speakers, groups lines into scenes by
row-name prefix, and links every string back to translations.csv ids so the
existing apply/rebuild pipeline can inject the results.

Output: work/translation_master.json
"""
import base64
import collections
import csv
import json
import re
import struct
import sys
from pathlib import Path

TOOLING = Path(__file__).resolve().parent.parent
WORK = TOOLING / "work"
DT_JSON = (
    WORK
    / "json/NoEcstasyNoLife/Content/_Common/Gameplay/Services/DialogueManager/DT_DialogueNodes.json"
)
CSV_PATH = WORK / "translations.csv"
OUT_PATH = WORK / "translation_master.json"

NS_MARKER = b"\x11\x00\x00\x00DT_DialogueNodes\x00"


def parse_dialogue_blob():
    doc = json.loads(DT_JSON.read_text(encoding="utf-8"))
    raw = doc["Exports"][0]["Data"]
    data = base64.b64decode(raw) if isinstance(raw, str) else bytes(bytearray(d & 0xFF for d in raw))
    recs = []
    i = 0
    while True:
        j = data.find(NS_MARKER, i)
        if j < 0:
            break
        p = j + len(NS_MARKER)
        (klen,) = struct.unpack_from("<i", data, p)
        p += 4
        key = data[p : p + klen - 1].decode("ascii")
        p += klen
        (slen,) = struct.unpack_from("<i", data, p)
        lenoff = p
        payload = p + 4
        if slen < 0:
            end = payload + (-slen) * 2
            src = data[payload:end].decode("utf-16-le").rstrip("\x00")
        else:
            end = payload + slen
            src = data[payload:end].decode("utf-8", errors="replace").rstrip("\x00")
        recs.append({"key": key, "src": src, "raw_offset": lenoff})
        i = end
    return recs


def scene_of(row_name):
    # OP_Classroom_1 -> OP_Classroom ; Konoha_Ending_00012 -> Konoha_Ending
    return re.sub(r"_?\d+$", "", row_name) or row_name


def main():
    recs = parse_dialogue_blob()

    rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8-sig")))
    dn_csv = collections.defaultdict(list)  # raw_offset -> [csv rows] (segments in order)
    other_csv = []
    for r in rows:
        if "DT_DialogueNodes" in r["json_file"] and r["kind"] == "raw":
            dn_csv[int(r["raw_offset"])].append(r)
        elif "DT_DialogueNodes" in r["json_file"]:
            other_csv.append(r)  # stray json-kind rows from the table
        else:
            other_csv.append(r)
    for segs in dn_csv.values():
        segs.sort(key=lambda r: int(r.get("segment_index") or 0))

    # assemble dialogue rows
    nodes = {}
    order = []
    for rec in recs:
        for suffix, field in (("_SpeakerName", "speaker"), ("_DialogueText", "text")):
            if rec["key"].endswith(suffix):
                rn = rec["key"][: -len(suffix)]
                node = nodes.setdefault(rn, {})
                if rn not in order:
                    order.append(rn)
                node[field] = rec["src"]
                node[field + "_offset"] = rec["raw_offset"]
                break

    speakers = {}
    scenes = collections.OrderedDict()
    missing_csv = []
    for rn in order:
        node = nodes[rn]
        speaker = node.get("speaker", "")
        text = node.get("text", "")
        # speaker csv ids (speaker strings are duplicated per row in the csv)
        sp_ids = [r["id"] for r in dn_csv.get(node.get("speaker_offset", -1), [])]
        if speaker:
            entry = speakers.setdefault(speaker, {"translation": "", "csv_ids": [], "lines": 0})
            entry["csv_ids"].extend(sp_ids)
            entry["lines"] += 1
        text_rows = dn_csv.get(node.get("text_offset", -1), [])
        if text and not text_rows:
            missing_csv.append((rn, text[:30]))
        line = {
            "row": rn,
            "speaker": speaker,
            "source": text,
            "translation": "",
        }
        if len(text_rows) == 1:
            line["csv_id"] = text_rows[0]["id"]
        elif text_rows:
            # multi-segment string: translate each visible segment separately
            line["segments"] = [
                {"csv_id": r["id"], "source": r["source"], "translation": ""} for r in text_rows
            ]
        scenes.setdefault(scene_of(rn), []).append(line)

    # categorize the non-dialogue strings
    def category(r):
        f = r["json_file"]
        if "CharmData" in f:
            return "charms"
        if "TypeWriter" in f.split("/")[-1]:
            return "typewriter_options"
        if "/UI/" in f or "/Widget" in f or f.split("/")[-1].startswith("WBP_"):
            return "ui"
        return "other"

    buckets = {"charms": collections.OrderedDict(), "typewriter_options": [], "ui": collections.OrderedDict(), "other": []}
    for r in other_csv:
        cat = category(r)
        entry = {
            "csv_id": r["id"],
            "source": r["source"],
            "translation": "",
        }
        asset = r["json_file"].split("/")[-1].replace(".json", "")
        if cat in ("charms", "ui"):
            buckets[cat].setdefault(asset, []).append(entry)
        else:
            entry["asset"] = asset
            buckets[cat].append(entry)

    out = {
        "meta": {
            "game": "NoEcstasyNoLife (FortuneBride)",
            "source_language": "ja",
            "target_language": "en",
            "instructions": (
                "Fill every 'translation' field with natural English. REQUIRED reading before "
                "translating: tooling/tl/game_prompt.md (translation bible: premise, cast voices, "
                "tone, markup rules) and tooling/tl/glossary.json (locked character spellings and "
                "terminology + do-not-translate list). Dialogue is grouped by scene in play order; "
                "translate whole scenes together for context. Text in （） is inner monologue. "
                "Be concise: injection is fixed-byte-span (ASCII must fit ~2x the JP char count). "
                "Do not translate csv_id, row, or source fields. For entries with 'segments', "
                "translate each segment separately."
            ),
            "dialogue_lines": sum(len(v) for v in scenes.values()),
            "scenes": len(scenes),
        },
        "speakers": speakers,
        "dialogue_scenes": [{"scene": k, "lines": v} for k, v in scenes.items()],
        "charms": buckets["charms"],
        "typewriter_options": buckets["typewriter_options"],
        "ui": buckets["ui"],
        "other": buckets["other"],
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT_PATH}")
    print(f"scenes: {len(scenes)}, dialogue lines: {out['meta']['dialogue_lines']}, speakers: {len(speakers)}")
    for cat in ("charms", "ui"):
        print(f"{cat}: {sum(len(v) for v in buckets[cat].values())} strings in {len(buckets[cat])} assets")
    print(f"typewriter_options: {len(buckets['typewriter_options'])}, other: {len(buckets['other'])}")
    if missing_csv:
        print(f"WARNING: {len(missing_csv)} dialogue texts have no csv row: {missing_csv[:5]}")


if __name__ == "__main__":
    main()
