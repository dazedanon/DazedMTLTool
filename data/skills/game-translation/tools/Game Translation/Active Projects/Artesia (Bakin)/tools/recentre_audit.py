r"""Which hand-positioned labels did the translation knock off centre?

    recentre_audit.py [--show 20] [--groups]

Bakin has no centring flag on a MenuItem. Where the author wanted a label
centred on a plate they nudged `pos.X` by hand against the width of the
Japanese, so replacing the text leaves every one of those labels off centre by
half the width difference - a defect no width check can see, because nothing
overflows and nothing is clipped.

`--groups` prints the detected hand-centred groups and the spread they cohere
to, which doubles as a check on `layout_font_size`: a wrong size makes the
groups fail to cohere rather than silently producing wrong offsets.
"""

import collections
import csv
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from artl import config, measure, recentre, store                    # noqa: E402


def load_rows(path):
    with io.open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def main(*argv):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    show = int(argv[argv.index("--show") + 1]) if "--show" in argv else 20
    cfg = config.load()
    m = measure.resolve(cfg, cfg["layout_font_size"])
    rows = load_rows(cfg["layout_tsv"])
    docs = store.load_docs(cfg["store_dir"])

    texts, trans = {}, {}
    for _p, u in store.all_units(docs):
        if u["kind"] != "ui":
            continue
        p = u["key"].split(":")
        if len(p) != 4 or p[0] != "M" or p[3] != "text":
            continue
        texts[(p[1], p[2])] = u["raw"]
        tl = (u.get("tl") or "").strip()
        if tl:
            trans[(p[1], p[2])] = tl

    groups = recentre.detect(rows, texts, m)
    fixes, skipped = recentre.fixes(rows, texts, trans, m)

    print("RECENTRE AUDIT")
    print("  %s" % m.describe())
    print("  layout rows %d, ui text units %d, translated %d"
          % (len(rows), len(texts), len(trans)))
    print()
    print("  hand-centred groups found : %d  (%d labels)"
          % (len(groups), sum(len(g["members"]) for g in groups)))
    print("  labels needing a shift    : %d" % len(fixes))
    for k, v in sorted(skipped.items()):
        print("    not shifted, %-24s %d" % (k, v))
    if fixes:
        sh = sorted(abs(d["new"] - d["old"]) for _k, _v, d in fixes)
        print("  shift px: median %.0f, worst %.0f" % (sh[len(sh) // 2], sh[-1]))

    if "--groups" in argv:
        print("\n  groups (spread is how tightly the JAPANESE centres agree -")
        print("  a wrong layout_font_size shows up here as a large spread):")
        for g in sorted(groups, key=lambda x: -len(x["members"]))[:show]:
            print("    %-24s %-12s n=%-3d centre %6.1f  spread %4.1fpx  "
                  "posX spread %5.1fpx"
                  % ((g["members"][0][0].get("node") or "")[:24], g["origin"],
                     len(g["members"]), g["centre"], g["spread"], g["posx_spread"]))

    print("\n  worst offenders:")
    print("    %-22s %-16s %-14s %7s %7s %8s"
          % ("node", "JP", "EN", "old x", "new x", "shift"))
    for _k, _v, d in sorted(fixes, key=lambda t: -abs(t[2]["new"] - t[2]["old"]))[:show]:
        print("    %-22s %-16s %-14s %7.1f %7.1f %+8.1f"
              % ((d["node"] or "")[:22], d["jp"][:16], d["en"][:14],
                 d["old"], d["new"], d["new"] - d["old"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
