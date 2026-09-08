r"""Bucket the validation flags and show real examples of each.

    triage.py [check ...]

A count is not actionable. Before paying for a retry round, look at what each
flag actually is: a check that is right about the shape and wrong about the
case cannot be fixed by asking the model again, and a retry on it is money for
a differently-wrong answer.
"""

import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from artl import budgets, codes, config, measure, store, validate   # noqa: E402


def main(*only):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cfg = config.load()
    m = measure.reset(cfg)
    docs = store.load_docs(cfg["store_dir"])
    validate.load_budgets(cfg, docs)
    if cfg.get("keywords"):
        codes.load_keywords(cfg["keywords"])
    glossary = store.load_glossary(cfg["store_dir"])
    from artl import inject
    inject.resolve_speakers(docs, glossary)

    by_check = collections.defaultdict(list)
    kinds = collections.defaultdict(collections.Counter)
    for _p, u in store.all_units(docs):
        for c in validate.hard_issues(u, cfg, m):
            by_check[c].append(u)
            kinds[c][u["kind"]] += 1

    for check in sorted(by_check, key=lambda c: -len(by_check[c])):
        if only and check not in only:
            continue
        units = by_check[check]
        print("\n%s  %d unit(s)   kinds: %s"
              % ("=" * 4 + " " + check, len(units),
                 dict(kinds[check].most_common(6))))
        # Distinct sources, so 400 copies of one line show as one case.
        seen = set()
        shown = 0
        for u in units:
            k = (u["kind"], u["src"])
            if k in seen:
                continue
            seen.add(k)
            print("   %-46s [%s]" % (u["id"][:46], u["kind"]))
            print("      JP  %s" % (u["src"] or "").replace("\n", " / ")[:96])
            print("      EN  %s" % (u.get("tl") or "").replace("\n", " / ")[:96])
            if check == "number-drift":
                print("      nums src=%s  tl=%s"
                      % (validate._visible_numbers(u["src"]),
                         validate._visible_numbers(u["tl"])))
            if check == "overflow":
                print("      %s" % validate._overflow(u, cfg, m))
            shown += 1
            if shown >= 12:
                break
        print("   (%d distinct source(s) behind %d unit(s))"
              % (len(seen), len(units)))
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
