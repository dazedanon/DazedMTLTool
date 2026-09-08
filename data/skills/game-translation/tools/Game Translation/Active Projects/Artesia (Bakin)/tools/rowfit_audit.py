r"""Does the English still fit the ROW budget of a wrapping widget?

    rowfit_audit.py [--rows 3] [--show 20] [--slots]

`validate` measures WIDTH. It reported 0 overflow while the skill panel drew
"MP Cost: 40" twice on screen, because nothing was counting ROWS.

THE DEFECT. Every description slot declares `maxLineNum = 3`, and the author
writes the MP cost INTO the description behind a hard newline. The body gets
two rows and the MP line is the third; English needing three rows on its own
pushes the MP line to a fourth, and the player sees the MP cost twice - once
spilling past the panel border, once in its proper place below. Width alone can
never see this: every one of those lines FITS. Only the count is wrong.

WHY THIS FILE DERIVES ITS SLOTS INSTEAD OF NAMING A \\. The first version
hardcoded ONE code. But the same `description` record is drawn by several:

    \\currentitemdes      item panels
    \\currentskilldes     skill panels          <-- the reported defect
    \\selectshopitemdes   shop panels
    \\currentdictionarydes dictionary panels

The fix and the check were written from the same wrong assumption, so the check
CONFIRMED the error - it reported zero while the skill panels were still
broken, and the player had to report the identical screenshot twice. A gate
that shares a premise with the fix it guards is not a gate. So the slot set is
read out of the layout every run, and `--slots` prints it: if a new panel
appears, it is measured rather than missed.

Two populations, reported separately because they fail differently:
  doubled   the description carries the author's own MP line, so a surplus row
            is DUPLICATED on screen. Loud, and the reason this check exists.
  clipped   a plain description. `clipping` is set on nearly every slot, so the
            surplus is cut off instead - quieter, still text the player never
            sees, and largely pre-existing.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import ImageFont                                          # noqa: E402

from artl import budgets, config, measure, store, wrap             # noqa: E402

BS = chr(92)


def slots(cfg):
    """[(eff_width, label)] for every wrapping widget that draws a description.

    Matched on the CODE's shape rather than a fixed list, so a panel using a
    code nobody has seen yet is still measured."""
    ov = cfg.get("layout_scale_overrides") or {}
    out = []
    for r in budgets.load_layout(cfg["layout_tsv"]):
        text = r.get("text") or ""
        if str(r.get("wordWrap")).lower() != "true":
            continue
        code = None
        for tok in text.split(BS):
            t = tok.strip().lower()
            if t.endswith("des") or t.startswith("currentitemdictionary")                     or t.startswith("currentskilldictionar"):
                code = BS + tok
                break
        if code is None:
            continue
        key = "%s:%s" % (r["nodeGuid"], r["idx"])
        sc = ov.get(key, float(r.get("scaleX") or 1.0)) or 1.0
        out.append((r["sizeX"] / sc, "%-22s idx %-4s %-24s x%.2f"
                    % (str(r.get("node"))[:22], r["idx"], code, sc)))
    return sorted(out)


def main(*argv):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rows_max = int(argv[argv.index("--rows") + 1]) if "--rows" in argv else 3
    show = int(argv[argv.index("--show") + 1]) if "--show" in argv else 20
    cfg = config.load()

    sl = slots(cfg)
    if not sl:
        print("no wrapping description slot in the layout - nothing to check")
        return 2
    width, where = sl[0]
    met = measure.resolve(cfg, cfg["layout_font_size"])
    font = ImageFont.truetype(met.path, cfg["layout_font_size"])

    def nrows(text):
        n = 0
        for para in text.split(chr(10)):
            n += len(wrap.wrap_text(para, width, font.getlength)) or 1
        return n

    units = [u for _p, u in store.all_units(store.load_docs(cfg["store_dir"]))
             if u["id"].endswith(":description") and (u.get("tl") or "").strip()]

    doubled, clipped = [], []
    for u in units:
        n = nrows(u["tl"])
        if n <= rows_max:
            continue
        (doubled if "MP Cost" in u["tl"] else clipped).append((n, u))

    print("ROW FIT over %d descriptions, %d drawing slots" % (len(units), len(sl)))
    print("  %s" % met.describe())
    print("  budget %d rows, charged against the NARROWEST slot:" % rows_max)
    print("    %.0fpx  %s" % (width, where))
    if "--slots" in argv:
        for w, lab in sl:
            print("    %.0fpx  %s" % (w, lab))
    print()
    print("  DOUBLED - the MP line is pushed to row %d+ and drawn twice : %d"
          % (rows_max + 1, len(doubled)))
    print("  clipped - surplus rows cut off by the slot's clipping      : %d"
          % len(clipped))
    for n, u in sorted(doubled, key=lambda x: -x[0])[:show]:
        print("   %d rows  %s" % (n, u["id"][:52]))
        print("           %r" % u["tl"].replace(chr(10), " / ")[:80])
    return 1 if doubled else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
