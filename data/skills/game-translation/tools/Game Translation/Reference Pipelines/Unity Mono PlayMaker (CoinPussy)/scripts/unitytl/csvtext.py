#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
csvtext.py — the game's scripted dialogue: TextAsset CSVs inside resources.assets.

AssetRipper exports no TextAssets for this game, but the entire script lives in
five CSV TextAssets (dump them with `tools/scripts/dump_textassets.py`):

    EventData_Hscene_casino.csv   H-scene subtitles + the AV narrator's commentary
    EventData_Event_casino.csv    story dialogue, with a speaker name per line
    EventData_Stage_casino.csv    in-battle barks
    EventData_W.csv               minigame / UI reaction lines
    EventData_Comment_W.csv       live-stream viewer comments (two pools)

The game reads them via PlayMaker `ReadTextAsset` -> `ReadCsv` ->
`CsvReader.LoadFromString(string, bool, char)`, so a translated build swaps the
whole CSV string at that one call. That means translations are per ROW: no global
dictionary constraint, and identical Japanese in two different files may render
differently. Within one file a string is still translated once, so a line that
repeats across loops/playthroughs stays consistent.

Round-trip fidelity is a hard requirement and is asserted on extract: reading a
CSV and rewriting it unchanged must reproduce the original bytes exactly (verified
for all five files: QUOTE_MINIMAL, CRLF terminators, UTF-8 BOM).
"""

import csv
import io
import os

from . import codes

# Per-file column policy. Columns not named here are engine data (animation,
# facial, voice, timing, state keys) and are never translated.
#   columns          column name (or bare index) -> unit kind for the prompt
#   speaker_column   a column whose value IS the line's speaker, read per row
#   column_speakers  fixed speaker per column, when the file has no speaker column
POLICY = {
    "EventData_Hscene_casino.csv": {
        "bucket": "CSV_Hscene",
        "columns": {"MessageJP": "hdialogue", "Announce": "narration", "Announce2": "narration"},
        "speaker_column": None,
        # MessageJP is always the heroine; Announce is the broadcast hype-man, a
        # completely different register — tagging both as the heroine would have the
        # model translate the narrator in her voice.
        "column_speakers": {"MessageJP": "受付ちゃん", "Announce": "実況アナウンサー",
                            "Announce2": "実況アナウンサー"},
    },
    "EventData_Event_casino.csv": {
        "bucket": "CSV_Event",
        "columns": {"MessageJP": "dialogue", "Announce": "speaker"},
        "speaker_column": "Announce",
        "column_speakers": {},
    },
    "EventData_Stage_casino.csv": {
        "bucket": "CSV_Stage",
        "columns": {"MessageJP": "bark"},
        "speaker_column": None,
        "column_speakers": {"MessageJP": "受付ちゃん"},
    },
    "EventData_W.csv": {
        "bucket": "CSV_W",
        "columns": {"MessageJP": "bark"},
        "speaker_column": None,
        "column_speakers": {"MessageJP": "受付ちゃん"},
    },
    "EventData_Comment_W.csv": {
        "bucket": "CSV_Comment",
        # The 3rd column has an empty header — address it by index.
        "columns": {"MessageJP": "comment", 2: "comment"},
        "speaker_column": None,
        "column_speakers": {},
    },
}

BOM = "﻿"


def read_csv(path):
    """(rows, had_bom). Rows include the header row."""
    raw = open(path, "rb").read()
    had_bom = raw.startswith(b"\xef\xbb\xbf")
    txt = raw.decode("utf-8-sig")
    return list(csv.reader(io.StringIO(txt, newline=""))), had_bom


def write_csv(path, rows, had_bom=True):
    buf = io.StringIO(newline="")
    csv.writer(buf, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL).writerows(rows)
    data = ((BOM if had_bom else "") + buf.getvalue()).encode("utf-8")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
    return len(data)


def assert_roundtrip(path):
    """Reading then rewriting a CSV must reproduce it byte for byte."""
    raw = open(path, "rb").read()
    rows, had_bom = read_csv(path)
    buf = io.StringIO(newline="")
    csv.writer(buf, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL).writerows(rows)
    out = ((BOM if had_bom else "") + buf.getvalue()).encode("utf-8")
    if out != raw:
        raise AssertionError(f"CSV round-trip is not byte-identical: {path}")



def scene_key(event_id: str) -> str:
    """Group an EventID into the scene beat it belongs to.

    Only the final numeric segment is dropped, which is exactly the line counter:
        H_Casino_Stage01_Rush_4     -> H_Casino_Stage01_Rush
        H_Comment_Stage08_End_44    -> H_Comment_Stage08_End
        H_Comment_2                 -> H_Comment
        UI_Touch_01_0               -> UI_Touch_01
    Stripping more would merge unrelated beats; stripping less would emit a scene
    header per line, which fragments the prompt and wastes tokens.
    """
    parts = (event_id or "").split("_")
    if len(parts) > 1 and parts[-1].isdigit():
        parts = parts[:-1]
    return "_".join(parts)


def _col_indices(header, columns):
    """{column index: kind} for a policy's `columns` (names or bare indices)."""
    out = {}
    for key, kind in columns.items():
        if isinstance(key, int):
            if key < len(header):
                out[key] = kind
        else:
            for i, h in enumerate(header):
                if h.strip() == key:
                    out[i] = kind
    return out


def extract_file(path, carried=None):
    """Build units for one CSV. Returns (bucket, units, stats).

    Units are deduped WITHIN the file (same Japanese -> one translation), keyed by
    (kind, raw); `cells` records every (row, col) the string occupies so injection
    can write them all back.
    """
    name = os.path.basename(path)
    pol = POLICY.get(name)
    if not pol:
        return None, [], {}
    assert_roundtrip(path)
    rows, _bom = read_csv(path)
    header = rows[0] if rows else []
    colmap = _col_indices(header, pol["columns"])
    spk_col = pol.get("speaker_column")
    spk_i = header.index(spk_col) if spk_col in header else None
    col_speakers = pol.get("column_speakers") or {}

    units, order = {}, []
    skipped = 0
    for ri in range(1, len(rows)):
        row = rows[ri]
        event_id = row[0].strip() if row else ""
        speaker = ""
        if spk_i is not None and spk_i < len(row):
            speaker = row[spk_i].strip()
        for ci, kind in sorted(colmap.items()):
            if ci >= len(row):
                continue
            val = row[ci]
            if not val.strip():
                continue
            if not codes.has_jp(val):
                skipped += 1
                continue
            # The speaker column is itself displayed (name box) — translate it as a
            # name, and never give it a speaker tag of its own.
            k = kind
            col_name = header[ci].strip() if ci < len(header) else ""
            spk = "" if kind == "speaker" else (speaker or col_speakers.get(col_name)
                                               or col_speakers.get(ci, ""))
            key = (k, val)
            u = units.get(key)
            if u is None:
                src, cmap = codes.mask(val)
                u = {
                    "kind": k,
                    "raw": val,
                    "src": src,
                    "codes": cmap,
                    "speaker": spk,
                    "scene": scene_key(event_id),
                    "event": event_id,
                    "col": header[ci].strip() or f"col{ci}",
                    "cells": [],
                    "tl": (carried or {}).get(val, ""),
                }
                units[key] = u
                order.append(key)
            u["cells"].append([ri, ci])
    ordered = [units[k] for k in order]
    stats = {"rows": len(rows) - 1, "units": len(ordered),
             "cells": sum(len(u["cells"]) for u in ordered), "skipped_nonjp": skipped}
    return pol["bucket"], ordered, stats


def inject_file(src_path, out_path, units):
    """Write a translated copy of one CSV. Untranslated cells keep the Japanese."""
    rows, had_bom = read_csv(src_path)
    written = missing = 0
    for u in units:
        tl = (u.get("tl") or "").strip()
        if not tl:
            missing += len(u.get("cells", []))
            continue
        text = codes.unmask(tl, u.get("codes") or {})
        for ri, ci in u.get("cells", []):
            if 0 < ri < len(rows) and ci < len(rows[ri]):
                rows[ri][ci] = text
                written += 1
    size = write_csv(out_path, rows, had_bom)
    return {"written": written, "missing": missing, "bytes": size}
