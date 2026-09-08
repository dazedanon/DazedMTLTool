r"""Prove the layout repair moved whitespace and nothing else.

    rebalance_verify.py

Reads `work/translated.jsonl` - the exact strings handed to BakinTL, whose
writing is already proven byte-exact by the no-op gate - and re-renders every
unit with the repair pass DISABLED. Four things must hold:

  * identical after stripping whitespace (no word gained, lost or reordered);
  * the rendered LINE COUNT is unchanged, so nothing newly paginates;
  * every line the pass PRODUCED fits its box. Note the word produced: a line
    the pass declined to touch may well exceed the box and be wrapped by the
    engine, which is exactly what happened before the pass existed and is not
    a defect. Checking every line instead of the produced ones reports the
    author's own long lines as our damage;
  * the orphan count never rises.

`selftest` proves the algorithm on one photographed line. This proves the
corpus, from the bytes actually shipped.
"""

import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from artl import balance, codes, config, inject, measure, store, wrap  # noqa: E402


def produced(old_lines, new_lines):
    """The new lines that came from splitting an old one, or None if the two
    line lists are not a refinement of each other."""
    out = []
    j = 0
    for old in old_lines:
        want = "".join(old.split())
        got, run = "", []
        while j < len(new_lines) and got != want:
            run.append(new_lines[j])
            got += "".join(new_lines[j].split())
            j += 1
        if got != want:
            return None
        if len(run) > 1:
            out.extend(run)
    return out if j == len(new_lines) else None


def main(*argv):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cfg = config.load()
    codes.load_keywords(cfg["keywords"])
    m = measure.reset(cfg)
    docs = store.load_docs(cfg["store_dir"])
    glossary = store.load_glossary(cfg["store_dir"])
    name_map = {jp: store.name_en(v)
                for jp, v in (glossary.get("names") or {}).items()
                if store.name_en(v)}

    by_key, args = {}, {}
    for _p, u in store.all_units(docs):
        if u["kind"] == "codearg":
            if (u.get("tl") or "").strip():
                args.setdefault(u["key"], {})[u["sub"]] = u["tl"]
        else:
            by_key[u["key"]] = u

    path = os.path.join(cfg["work_dir"], "translated.jsonl")
    st = collections.Counter()
    bad = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            u = by_key.get(rec["key"])
            if u is None:
                st["no-unit"] += 1
                continue
            st["checked"] += 1
            shipped = rec["en"]
            # The baseline must differ from the shipped string ONLY by the
            # repair pass, so it needs the same code-argument substitution.
            plain = inject.render(u, args.get(rec["key"]), name_map)
            if shipped == plain:
                continue
            st["changed"] += 1

            if "".join(shipped.split()) != "".join(plain.split()):
                bad.append(("WORDS CHANGED", rec["key"], plain, shipped))
                continue
            width = balance.wrap_width(cfg, u["kind"])
            if not width:
                bad.append(("REPAIRED A KIND WITH NO MEASURED WIDTH",
                            rec["key"], plain, shipped))
                continue
            # The nameplate is drawn in its own box, so strip it before
            # measuring the body - exactly as `render` does before repairing.
            b_old = codes.split_speaker(codes.to_lf(plain))[1]
            b_new = codes.split_speaker(codes.to_lf(shipped))[1]
            r_old = wrap.wrap_text(b_old, width, m.width)
            r_new = wrap.wrap_text(b_new, width, m.width)
            if len(r_old) != len(r_new):
                bad.append(("LINE COUNT %d -> %d" % (len(r_old), len(r_new)),
                            rec["key"], plain, shipped))
                continue

            made = produced(b_old.split("\n"), b_new.split("\n"))
            if made is None:
                bad.append(("NOT A REFINEMENT of the original lines",
                            rec["key"], plain, shipped))
                continue
            over = [ln for ln in made if m.width(ln) > width]
            if over:
                bad.append(("A LINE THE PASS PRODUCED IS OVER THE BOX "
                            "(%0.0fpx > %0.0f) so the engine will re-wrap it"
                            % (m.width(over[0]), width),
                            rec["key"], plain, shipped))
                continue

            o_old = sum(len(wrap.orphans(wrap.wrap_line(ln, width, m.width),
                                         width, m.width))
                        for ln in b_old.split("\n"))
            o_new = sum(len(wrap.orphans(wrap.wrap_line(ln, width, m.width),
                                         width, m.width))
                        for ln in b_new.split("\n"))
            if o_new > o_old:
                bad.append(("ORPHANS ROSE %d -> %d" % (o_old, o_new),
                            rec["key"], plain, shipped))
                continue
            st["orphans-removed"] += o_old - o_new
            st["verified"] += 1

    print("REBALANCE VERIFY  %s" % path)
    print("  %s" % m.describe())
    print("  write sites checked : %d" % st["checked"])
    print("  changed by the pass : %d" % st["changed"])
    print("  verified clean      : %d" % st["verified"])
    print("  orphan lines removed: %d" % st["orphans-removed"])
    print("  DEFECTS             : %d" % len(bad))
    for why, key, old, new in bad[:12]:
        print("\n  %s\n  %s" % (why, key))
        print("     was %r" % old[:160])
        print("     now %r" % new[:160])
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
