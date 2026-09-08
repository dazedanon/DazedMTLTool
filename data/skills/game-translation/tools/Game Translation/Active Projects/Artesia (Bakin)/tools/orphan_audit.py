r"""How often does the shipped English leave a word alone on its own line?

    orphan_audit.py [--width 690] [--show 12]

Runs the ENGINE's own wrap (`artl/wrap.py`, transcribed from the decompiled
`MessageEntry.wordWrap`) over every dialogue unit and counts the tails.

Four things are reported separately because they need different answers:

  orphan    a wrap tail narrower than a third of the box - the "you're a /
            nuisance?" case. Cosmetic, but it is the thing that makes a patch
            look machine-made.
  pages     the unit now needs more than `maxLineNum` rendered lines, so the
            engine paginates and the player gets an extra key press. Costs
            pacing, never text.
  vs JP     the same counts for the SHIPPED JAPANESE, because a defect the
            author already ships is not one the patch introduced.
  FIXED     what `artl/balance.py` would repair without touching a word, and
            what it declines to. The residue is the honest number: a line whose
            every legal split still leaves a short tail cannot be repaired by
            moving whitespace, and this pass will not rewrite prose to chase it.

The width DEFAULTS TO THE CALIBRATED `message_px`, not a literal. Every orphan
figure taken before the font calibration was measured at 24px/670px and is
wrong - re-derive rather than compare against them.
"""

import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from artl import balance, codes, config, measure, store, wrap        # noqa: E402


def main(*argv):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cfg = config.load()
    width = float(cfg["message_px"])
    max_lines = int(cfg["message_lines"])
    show = 12
    if "--width" in argv:
        width = float(argv[argv.index("--width") + 1])
    if "--show" in argv:
        show = int(argv[argv.index("--show") + 1])

    m = measure.reset(cfg)
    meas = m.width
    docs = store.load_docs(cfg["store_dir"])

    stats = collections.Counter()
    examples = []
    seen = set()
    for _p, u in store.all_units(docs):
        if u["kind"] not in ("text", "telop"):
            continue
        tl = codes.clean_translation(u.get("tl") or "")
        if not tl.strip():
            continue
        body_en = codes.unmask_codes(tl, u.get("codes") or {}, pad_inserts=True)
        body_jp = codes.split_speaker(u["raw"])[1]

        en_lines = 0
        for tag, body in (("EN", body_en), ("JP", body_jp)):
            total = 0
            orph = 0
            for line in codes.to_lf(body).split("\n"):
                r = wrap.wrap_line(line, width, meas)
                total += len(r)
                orph += len(wrap.orphans(r, width, meas))
            stats[tag + ":units"] += 1
            if orph:
                stats[tag + ":orphan-units"] += 1
                stats[tag + ":orphans"] += orph
            if total > max_lines:
                stats[tag + ":paginates"] += 1
            if tag == "EN":
                en_lines = total
            if tag != "EN" or not orph:
                continue

            fixed, _n, coded = balance.rebalance_text(body_en, width, meas)
            stats["CODED:units"] += bool(coded)
            after = wrap.wrap_text(fixed, width, meas)
            left = sum(len(wrap.orphans(wrap.wrap_line(ln, width, meas),
                                        width, meas))
                       for ln in codes.to_lf(fixed).split("\n"))
            if left < orph:
                stats["FIX:units"] += 1
                stats["FIX:orphans"] += orph - left
            if left:
                stats["RESIDUE:units"] += 1
                stats["RESIDUE:orphans"] += left
            # NOT "paginates after" - 701 units already did before we touched
            # them. The invariant is that the count does not CHANGE.
            if len(after) != en_lines:
                stats["FIX:linecount"] += 1

            k = (u["kind"], u["src"])
            if k not in seen:
                seen.add(k)
                examples.append((u, body_en, fixed))

    print("wrap width %.0fpx, maxLineNum %d" % (width, max_lines))
    print(m.describe())
    print()
    for tag in ("EN", "JP"):
        n = stats[tag + ":units"]
        print("  %s  units %6d   with an orphan %5d (%4.1f%%)   orphan lines "
              "%5d   paginating %5d"
              % (tag, n, stats[tag + ":orphan-units"],
                 100.0 * stats[tag + ":orphan-units"] / max(1, n),
                 stats[tag + ":orphans"], stats[tag + ":paginates"]))
    en = max(1, stats["EN:orphan-units"])
    print()
    print("  rebalance repairs %5d of %d affected units (%4.1f%%), %d orphan "
          "lines" % (stats["FIX:units"], en, 100.0 * stats["FIX:units"] / en,
                     stats["FIX:orphans"]))
    print("  residue           %5d units still carry %d orphan line(s) - no "
          "legal split removes them" % (stats["RESIDUE:units"],
                                        stats["RESIDUE:orphans"]))
    print("  code-bearing      %5d units skipped outright: a control code's "
          "drawn width is not knowable from the string" % stats["CODED:units"])
    print("  line count moved  %5d  (must be 0: rebalance may never add or "
          "drop a rendered line, so pagination cannot change)"
          % stats["FIX:linecount"])
    print()
    print("  distinct English sources with an orphan: %d" % len(examples))
    print()
    for u, body, fixed in examples[:show]:
        print("   %s" % u["id"][:52])
        for tag, txt in (("was", body), ("now", fixed)):
            if tag == "now" and txt == body:
                print("      (unchanged)")
                break
            for line in codes.to_lf(txt).split("\n"):
                for k, r in enumerate(wrap.wrap_line(line, width, meas)):
                    mark = "  <- ORPHAN" if (k and meas(r) <= width * 0.34) else ""
                    print("   %s|%-72s|%s" % (tag if not k else "   ",
                                              r[:72], mark))
                    tag = "   "
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
