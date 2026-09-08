#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
reflow_help.py — preview / patch the CE100 help-tutorial re-flow on a data dir.

The re-flow normally runs INSIDE inject (config.help_reflow); this is a thin CLI
over rpgmvtl.helpwrap for previewing the result or patching data/CommonEvents.json
directly (e.g. after a manual edit). See helpwrap.py for the how/why.

  python tooling/reflow_help.py            # preview every page
  python tooling/reflow_help.py --apply    # rewrite data/CommonEvents.json
"""
import json, os, sys, glob, argparse, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")
from rpgmvtl import helpwrap as H

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")


def preview(data):
    for tpl in H.TEMPLATES:
        lo, hi, slots = tpl["lo"], tpl["hi"], tpl["hi"] - tpl["lo"] + 1
        n = wrapped = 0
        print(f"\n===== template CE{tpl['ce']} (vars {lo}-{hi}, merge={tpl['merge']}) =====")
        for L in H._iter_command_lists(data):
            for varmap, _fi in H._iter_pages(L, tpl["ce"], tpl["font_var"]):
                cmds = {v: varmap[v] for v in range(lo, hi + 1) if v in varmap}
                if not cmds:
                    continue
                body = [H._unq(L[cmds[v]]["parameters"][4]) if v in cmds else ""
                        for v in range(lo, hi + 1)]
                if not any(any(c.isascii() and c.isalpha() for c in line) for line in body):
                    continue
                n += 1
                chosen, flowed = tpl["fonts"][-1], None
                for font in tpl["fonts"]:
                    flowed = H.reflow(body, H._width_cells(font, tpl["avail"]), tpl["merge"]); chosen = font
                    if len(flowed) <= slots:
                        break
                grew = sum(1 for x in flowed if x.strip()) > sum(1 for x in body if x.strip())
                if grew or chosen != tpl["fonts"][0]:
                    wrapped += 1
                    print(f"--- font {chosen} | {len([x for x in flowed if x.strip()])} lines ---")
                    for x in flowed:
                        if x.strip():
                            print("   ", x)
        print(f"  CE{tpl['ce']}: {n} pages/banners, {wrapped} changed (wrapped or font-reduced)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    # tutorials live in CommonEvents; banners (CE36) live across the map files too
    files = [os.path.join(DATA, "CommonEvents.json")] + sorted(glob.glob(os.path.join(DATA, "Map*.json")))
    total = 0
    for f in files:
        if not os.path.exists(f) or os.path.basename(f) == "MapInfos.json":
            continue
        data = json.load(open(f, encoding="utf-8-sig"))
        if a.apply:
            bak = f + ".pre_reflow.bak"
            n = H.apply_reflow(data)
            if n:
                if not os.path.exists(bak):
                    shutil.copy2(f, bak)
                json.dump(data, open(f, "w", encoding="utf-8"), ensure_ascii=False)
                total += n
        elif os.path.basename(f) == "CommonEvents.json":
            preview(data)
    if a.apply:
        print(f"re-flowed {total} pages/banners across data/")


if __name__ == "__main__":
    main()
