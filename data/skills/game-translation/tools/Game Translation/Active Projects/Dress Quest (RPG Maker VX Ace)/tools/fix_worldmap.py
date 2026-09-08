#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
fix_worldmap.py - the world map's two budgets, which are not the same budget.

The same place name is drawn in TWO windows:

    Window_k_ShortMove_Command   window_width 140 -> 116 px = 11 cells
                                 (`add_command(master[i][0][0], ...)`)
    Window_k_ShortMove_Info      Graphics.width - 140 -> 476 px = 47 cells
                                 (the title row)

The narrow one wins, and "Baron, Royal Capital" was clipped to
"Baron, Royal Capit" in the list. A per-script width budget cannot express
that, so the names get a per-entry budget of 11.

The descriptions have the opposite problem - too little text, not too much.
`Window_k_ShortMove_Info#refresh` draws `explan[0]` and `explan[1]` on two
separate rows, and the script's own comment says so:

    #EXPLAN[0～] = [説明1行目,説明2行目]

The author filled only the first element, and their single lines run to 62
cells in a 47-cell window, so the Japanese clips too. Splitting the English
across both elements gives 94 cells instead of 47, which is room for the whole
sentence rather than a compressed one.

    python tools/fix_worldmap.py            # show what would change
    python tools/fix_worldmap.py --apply
"""

import os
import re
import sys
import json
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from acetl import store, config, parse, measure, client as C   # noqa: E402
from acetl import requests as R                                # noqa: E402

SECTION = "わーるどまっぷ"
NAME_CELLS = 11          # the command window, and the reason for this script
LINE_CELLS = 45          # each of the two info rows, 47 with a margin

SYSTEM = """\
You are localizing an RPG Maker VX Ace world map into English.

Each entry is a place on the map. You are given the Japanese name, the Japanese
description, and the English already in the patch.

Return for each:
  "name"  - the place name for a LIST, hard limit %d half-width characters.
            Shorter is better than clever: it is a map pin label, and the full
            name is shown elsewhere. Do not abbreviate with a full stop.
  "line1" - the first row of the description, at most %d half-width characters
  "line2" - the second row, at most %d, or "" when one row says it all

line1 and line2 are drawn as two separate rows and are NOT joined, so line1
must end at a natural break - a clause, a comma - and line2 must read on from
it. Between them there is room for the whole Japanese sentence, so translate it
fully rather than compressing it.

Output ONLY a JSON object mapping each number, as a string, to
{"name": "...", "line1": "...", "line2": "..."}.
""" % (NAME_CELLS, LINE_CELLS, LINE_CELLS)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=os.path.join(os.path.dirname(HERE), "tl"))
    ap.add_argument("--model", default=R.MODEL_DEFAULT)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)

    m = measure.reset(config.Config().font_path())
    path = os.path.join(a.store, "scripts_rb.json")
    led = store.read_json(path)

    names, descs = [], []
    for e in led["entries"]:
        if e["name"] != SECTION or not e.get("en"):
            continue
        (descs if e["context"].startswith("EXPLAN") else
         names if e["context"].startswith("MOVE_LIST") else []).append(e)

    # Pair each place with its description by the index in `MOVE_LIST[n]` /
    # `EXPLAN[n]`, which is what the engine itself uses to line them up.
    def idx(e):
        mm = re.search(r"\[(\d+)\]", e["context"])
        return int(mm.group(1)) if mm else -1

    by_idx = {}
    for e in names:
        by_idx.setdefault(idx(e), {})["name"] = e
    for e in descs:
        by_idx.setdefault(idx(e), {})["desc"] = e
    rows = [(i, v) for i, v in sorted(by_idx.items()) if "name" in v]
    if not rows:
        print("no world-map entries in the ledger")
        return 1

    body = ["Translate each place. Return ONLY the JSON object."]
    for n, (i, v) in enumerate(rows, 1):
        d = v.get("desc")
        body.append("[%d] name JP %s   (current EN %s, %d cells)\n"
                    "     desc JP %s\n     current EN desc: %s"
                    % (n, json.dumps(v["name"]["jp"], ensure_ascii=False),
                       json.dumps(v["name"]["en"], ensure_ascii=False),
                       m.cells(v["name"]["en"]),
                       json.dumps(d["jp"], ensure_ascii=False) if d else "(none)",
                       json.dumps(d["en"], ensure_ascii=False) if d else "(none)"))

    print("%d place(s); name budget %d cells, description rows %d cells each"
          % (len(rows), NAME_CELLS, LINE_CELLS))
    msg = C.get_client().messages.create(
        model=a.model, max_tokens=max(4096, len(rows) * 200),
        **R.sampling_params(a.model), **R.output_config("low"),
        system=[{"type": "text", "text": SYSTEM}],
        messages=[{"role": "user", "content": "\n".join(body)}])
    usage = C.Usage()
    usage.add(getattr(msg, "usage", None))
    obj = parse.parse("".join(b.text for b in msg.content
                              if getattr(b, "type", "") == "text"))

    over = 0
    for k, v in obj.items():
        try:
            _i, pair = rows[int(k) - 1]
        except (ValueError, IndexError):
            continue
        if not isinstance(v, dict):
            continue
        nm = (v.get("name") or "").strip()
        if nm:
            flag = "!" if m.cells(nm) > NAME_CELLS else " "
            over += 1 if flag == "!" else 0
            print("  name%s %-22s %-20s -> %-14s %2d" %
                  (flag, pair["name"]["jp"], pair["name"]["en"], nm, m.cells(nm)))
            if a.apply:
                pair["name"]["en"] = nm
                pair["name"]["budget"] = NAME_CELLS
        d = pair.get("desc")
        if not d:
            continue
        lines = [x for x in ((v.get("line1") or "").strip(),
                             (v.get("line2") or "").strip()) if x]
        if not lines:
            continue
        widths = [m.cells(x) for x in lines]
        flag = "!" if max(widths) > LINE_CELLS + 2 else " "
        over += 1 if flag == "!" else 0
        print("  desc%s %s" % (flag, " | ".join("%s (%d)" % (x, w)
                                                for x, w in zip(lines, widths))))
        if a.apply:
            d["en_lines"] = lines
            d["en"] = lines[0]
            d["budget"] = LINE_CELLS + 2
            d["width"] = [m.cells(d["jp"]), max(widths)]

    print("\n%d over budget" % over)
    print(usage.report(a.model, batch=False, ttl="5m"))
    if a.apply:
        store.write_json(path, led)
        print("ledger written - now: restore a pristine Scripts.rvdata2, then "
              "`tl.py scripts apply`")
    else:
        print("\ndry run - pass --apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
