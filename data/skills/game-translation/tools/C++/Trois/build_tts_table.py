#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_tts_table.py — build the EN->JP side table the TTS-swap DLL uses.

The auto-voice (Open JTalk) reads the on-screen dialogue text. After translation
that text is English, which makes the synth path hang. We want it to speak the
ORIGINAL Japanese instead, while English stays on screen. The DLL hooks the synth
entry (sub_5E6B10), normalizes the incoming text, looks it up here, and if found
swaps in the Japanese before mecab runs.

Key idea: the deployed English scripts (natuiso/scripts/*.txt) and the original
Japanese scripts (natuiso_extracted/scripts/*.txt) are line-for-line structurally
identical -- same commands, same @speaker blocks, in the same order. So we walk
both in parallel, pair up the Nth dialogue block, and map EN-text -> JP-text.

Lookup is whitespace-insensitive: we strip ALL whitespace (spaces, full-width
spaces, tabs, newlines) from the key, so however the engine joins wrapped lines
doesn't matter. The DLL must apply the SAME normalization to the incoming string.

  python tooling/build_tts_table.py            # -> tooling/tts_jp_table.json (+ .bin)

Output formats:
  tts_jp_table.json : {normalized_en: jp, ...}  (human-inspectable)
  tts_jp_table.bin  : flat binary the DLL memory-maps:
        magic 'TTSJ' u32count, then count records:
          u32 keylen, key bytes (normalized EN, utf-8),
          u32 vallen, val bytes (JP, utf-8)
        records sorted by key for bsearch.
"""
import os, sys, glob, json, struct

ROOT = os.path.dirname(os.path.abspath(__file__)) + "/.."
EN_DIR = os.path.join(ROOT, "natuiso", "scripts")
JP_DIR = os.path.join(ROOT, "natuiso_extracted", "scripts")
OUT_JSON = os.path.join(ROOT, "tooling", "tts_jp_table.json")
OUT_BIN  = os.path.join(ROOT, "tooling", "tts_jp_table.bin")

AT = "＠"          # ＠ full-width
AT2 = "@"
WS = " \t\r\n　 "


def normalize(s):
    """Strip every whitespace char; used for both keys and DLL-side lookups."""
    return "".join(ch for ch in s if ch not in WS)


def is_text_line(l):
    s = l.lstrip()
    if not s:
        return False
    if s.startswith("//"):
        return False
    if s.startswith(AT) or s.startswith(AT2):
        return False
    c = s[0]
    if ord(c) > 127:          # non-ASCII leading -> JP dialogue/narration
        return True
    if c in "\"「（(":  # " 「 （ ( -> EN dialogue / paren
        return True
    return False               # otherwise a command line


def parse_blocks(path):
    """Ordered list of (speaker, joined_text) for every @speaker dialogue block."""
    lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
    blocks = []
    for l in lines:
        s = l.lstrip()
        if s.startswith(AT) or s.startswith(AT2):
            sp = s[1:].split(",")[0].split("\t")[0].strip()
            blocks.append([sp, []])
        elif blocks and is_text_line(l):
            blocks[-1][1].append(l.strip())
        # command / blank lines: ignored (do not break a block; matches engine
        # which keeps collecting the message body until the next directive)
    return [(sp, "\n".join(tl)) for sp, tl in blocks if tl]


def main():
    en_files = sorted(glob.glob(os.path.join(EN_DIR, "*.txt")))
    if not en_files:
        sys.exit("No EN scripts at %s -- deploy the loose scripts first." % EN_DIR)

    table = {}
    collisions = 0
    skipped_files = []
    total_pairs = 0
    for ef in en_files:
        name = os.path.basename(ef)
        jf = os.path.join(JP_DIR, name)
        if not os.path.exists(jf):
            skipped_files.append((name, "no JP counterpart"))
            continue
        en = parse_blocks(ef)
        jp = parse_blocks(jf)
        if len(en) != len(jp):
            skipped_files.append((name, "block mismatch EN=%d JP=%d" % (len(en), len(jp))))
            continue
        for (esp, etext), (jsp, jtext) in zip(en, jp):
            k = normalize(etext)
            if not k:
                continue
            if k in table and table[k] != jtext:
                collisions += 1
                continue          # keep first; duplicates are usually identical short lines
            table[k] = jtext
            total_pairs += 1

    # JSON (inspectable)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(table, f, ensure_ascii=False, indent=0)

    # BIN (DLL-friendly, sorted by key for bsearch)
    recs = sorted(table.items(), key=lambda kv: kv[0].encode("utf-8"))
    with open(OUT_BIN, "wb") as f:
        f.write(b"TTSJ")
        f.write(struct.pack("<I", len(recs)))
        for k, v in recs:
            kb = k.encode("utf-8"); vb = v.encode("utf-8")
            f.write(struct.pack("<I", len(kb))); f.write(kb)
            f.write(struct.pack("<I", len(vb))); f.write(vb)

    print("EN scripts:        %d" % len(en_files))
    print("entries in table:  %d" % len(table))
    print("collisions skipped:%d" % collisions)
    if skipped_files:
        print("files skipped:")
        for n, why in skipped_files:
            print("   %-22s %s" % (n, why))
    print("wrote %s" % OUT_JSON)
    print("wrote %s (%d bytes)" % (OUT_BIN, os.path.getsize(OUT_BIN)))


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        try: s.reconfigure(encoding="utf-8", errors="replace")
        except Exception: pass
    main()
