#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_digests.py - rebuild digest/ from the CURRENT batch.json, and stamp it.

    python scripts/make_digests.py build
    python scripts/make_digests.py check     # exit 1 if digest/ is stale

digest/ is what the glossary is written from, so it inherits batch.json's sentinel
numbering. That numbering is a property of the FILE LIST passed to `wolf mt-export`,
not of the game: adding `out/names.json` to the export re-ordered it and only 36 of
86 tokens kept their meaning. A glossary written against a stale digest does not
fail loudly - its keys stop matching, and any key that still matches now says the
wrong thing about that token. So the digest carries a stamp and `check` refuses a
mismatch. To repair an artifact already written against the old numbering, use
`remap_sentinels.py` rather than regenerating and re-paying for the reading.
"""

import os
import re
import sys
import json
import hashlib
import argparse
import collections

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BATCH = os.path.join(WS, "batch.json")
D = os.path.join(WS, "digest")
STAMP = os.path.join(D, "_stamp.json")
NP = re.compile(r"^【([^】\n]{1,24})】")


def _identity(batch):
    h = hashlib.sha256()
    for tok in sorted(batch["_sentinel_legend"], key=lambda s: int(s[2:-1])):
        h.update(f"{tok}={batch['_sentinel_legend'][tok]}\n".encode("utf-8"))
    return {"lines": len(batch["lines"]),
            "legend_sha": h.hexdigest()[:16],
            "legend_size": len(batch["_sentinel_legend"])}


def _flat(s, n):
    return s.replace("\r\n", " / ").replace("\n", " / ")[:n]


def cmd_build():
    with open(BATCH, encoding="utf-8") as f:
        batch = json.load(f)
    L = batch["lines"]
    os.makedirs(D, exist_ok=True)

    speakers = collections.defaultdict(list)
    for l in L:
        m = NP.match(l["source"])
        if m:
            speakers[m.group(1)].append(l["source"])
    rows = sorted(speakers.items(), key=lambda x: -len(x[1]))
    with open(os.path.join(D, "speakers.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write(f"# {len(rows)} nameplate speakers (convention: 【NAME】 newline 「line」)\n\n")
        for k, v in rows:
            seen = []
            for s in v:
                if s not in seen:
                    seen.append(s)
                if len(seen) >= 4:
                    break
            f.write(f"## {k}  ({len(v)} lines, {len(set(v))} distinct)\n")
            for s in seen:
                f.write("   " + _flat(s, 200) + "\n")
            f.write("\n")

    ui = [l for l in L if (l.get("speaker") in ("UI", "Choice"))
          or l["file"].endswith(("DataBase.json", "CDataBase.json",
                                 "SysDatabase.json", "GameDat.json"))]
    seen, out = set(), []
    for l in ui:
        if l["source"] in seen:
            continue
        seen.add(l["source"])
        out.append((l.get("speaker") or "", l["file"].split("/")[-1], l["source"]))
    with open(os.path.join(D, "ui_and_db.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write(f"# {len(out)} distinct UI / Choice / database strings\n")
        f.write("# NOTE: an in-string newline is written as a literal \\n so one record "
                "is one line and nothing has to be reassembled.\n\n")
        for sp, fn, s in out:
            f.write(f"[{sp or fn}] " + s.replace("\r\n", "\\n").replace("\n", "\\n") + "\n")

    nar, seen = [], set()
    for l in L:
        s = l["source"]
        if s in seen:
            continue
        seen.add(s)
        if l.get("speaker") == "Narration" and len(s) > 25:
            nar.append(s)
    nar.sort(key=len, reverse=True)
    with open(os.path.join(D, "story_sample.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write(f"# {len(nar)} distinct narration/dialogue units; longest 400 then every 20th\n\n")
        for s in nar[:400]:
            f.write(s.replace("\r\n", "\\n").replace("\n", "\\n")[:600] + "\n")
        f.write("\n# --- sampled tail ---\n")
        for s in nar[400::20]:
            f.write(s.replace("\r\n", "\\n").replace("\n", "\\n")[:400] + "\n")

    nm = json.load(open(os.path.join(WS, "out", "names.json"), encoding="utf-8"))
    by = collections.defaultdict(list)
    for n in nm["names"]:
        by[n.get("note") or "?"].append(n)
    with open(os.path.join(D, "db_names.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write(f"# {nm['count']} DB names, dynamic_lookups={nm['dynamic_lookups']}, "
                f"registry_skipped={nm['registry_skipped']}\n")
        f.write("# these are RAW (not sentinel-masked) - they come from out/names.json\n\n")
        for cat, items in sorted(by.items(), key=lambda x: -len(x[1])):
            f.write(f"## {cat}  ({len(items)})\n")
            for n in items:
                f.write(f"   [{n['safety']}] {n['source']}\n")
            f.write("\n")

    with open(STAMP, "w", encoding="utf-8") as f:
        json.dump(_identity(batch), f, ensure_ascii=False, indent=1)
    print(f"digest/ rebuilt from batch.json: {len(rows)} speakers, {len(out)} UI strings, "
          f"{len(nar)} narration units, {nm['count']} DB names")
    print(f"stamped {STAMP}: {json.load(open(STAMP, encoding='utf-8'))}")
    return 0


def cmd_check():
    with open(BATCH, encoding="utf-8") as f:
        cur = _identity(json.load(f))
    if not os.path.exists(STAMP):
        print("digest/ has no stamp - rebuild it.")
        return 1
    with open(STAMP, encoding="utf-8") as f:
        was = json.load(f)
    if was == cur:
        print("digest/ matches batch.json:", cur)
        return 0
    print("digest/ is STALE.")
    print("  built from:", was)
    print("  batch.json:", cur)
    if was.get("legend_sha") != cur.get("legend_sha"):
        print("  ! the SENTINEL LEGEND changed. Anything written from this digest "
              "carries the old {Wn} numbering and must be run through "
              "remap_sentinels.py, not just regenerated.")
    return 1


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["build", "check"])
    args = ap.parse_args()
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    return cmd_build() if args.action == "build" else cmd_check()


if __name__ == "__main__":
    sys.exit(main() or 0)
