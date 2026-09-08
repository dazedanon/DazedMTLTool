r"""Which backslash codes appear in the OUTPUT, and are they known?

    escape_audit.py

`validate.invented-backslash` asks whether a backslash run in a translation is
one the engine defines. Its answer is only as good as the table it checks
against, so this prints both sides: what the table holds, and what the corpus
actually contains.
"""

import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from artl import codes, config, store                            # noqa: E402

PROBES = ["npl", "npc", "npr", "np", "n", "b", "i", "u", "c", "w", "z", "r",
          "blink", "blspd", "lip", "money", "map", "time", "skillname",
          "innpriceg", "currentitemnum"]


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cfg = config.load()
    codes.load_keywords(cfg["keywords"])
    print("keyword table entries: %d" % len(codes._KEYWORDS))
    for p in PROBES:
        print("   %-16s known: %s" % ("\\" + p, p in codes._KEYWORDS))

    docs = store.load_docs(cfg["store_dir"])
    seen = collections.Counter()
    unknown = collections.Counter()
    n_units = 0
    for _p, u in store.all_units(docs):
        tl = u.get("tl") or ""
        if not tl:
            continue
        n_units += 1
        restored = codes.unmask_codes(tl, u.get("codes") or {}, pad_inserts=True)
        if u["kind"] == "text" and u.get("plate"):
            restored = codes.join_speaker(
                u.get("speaker_en") or u.get("speaker"), restored, u.get("plate"))
        import re
        for m in re.finditer(r"\\([A-Za-z_#$]+)", restored):
            seen[m.group(1).lower()] += 1
        for e in codes.unknown_escapes(restored):
            unknown[e.lstrip("\\").lower()] += 1

    print("\nbackslash codes present in the OUTPUT over %d translated units:"
          % n_units)
    for e, n in seen.most_common(15):
        print("   %-18s %8d   known: %s" % ("\\" + e, n, e in codes._KEYWORDS))
    print("\nflagged UNKNOWN by the current table:")
    for e, n in unknown.most_common(15):
        print("   %-18s %8d" % ("\\" + e, n))
    if not unknown:
        print("   none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
