r"""Do PARALLEL entries read as a matched set?

    parallel_audit.py [--show 20] [--kinds desc,name,mapname,...]

A player reported that one intel panel ended its lines with full stops and the
panel beside it did not. Both were correct English, both fitted, both carried no
residual Japanese, and every existing check passed them. Their Japanese differed
by exactly ONE character - 男A against 男B - which is why nothing saw them as a
pair: a same-source duplicate check compares sources for EQUALITY, and these are
not equal.

So mask the characters that make a parallel entry differ - latin letters,
digits, fullwidth letters, kanji numerals - and group on what is left. Anything
in one group is the same sentence about a different thing, and the player sees
the members side by side or one screen apart. They have to match.

Two failure grades, because they read differently on screen:

  punctuation   the members disagree about terminal stops. Quiet but jarring,
                and the one that got reported.
  wording       the members disagree about a WORD. Much worse, because it is
                usually a glossary break: "Odoro Cavern - 1" next to "Odoro
                Cave - 2", or "Raises Attack by 5." against "Raises ATK by 3".

RESOLVE BY CORPUS MAJORITY, NOT BY TASTE. When this first ran it found 17
groups, and every contested form had a decisive majority elsewhere in the
corpus: 洞窟 Cave 19-0, 攻撃力 Attack 50-9, 経験値 EXP 17-1, and the map-name
separator " - " 83-12. The majority is evidence about a house style already
applied dozens of times. Your preference is evidence about nothing.

AND THEN RE-RUN THE OVERFLOW CHECK, because harmonising is a FIT decision as
much as a correctness one. Resolving 原罪のサジタリウス toward the more literal
"Sagittarius of Original Sin" was the better translation and broke the widget:
260px into a 242px box where the Japanese sat at 198px. The variant that reads
slightly loose can be the only one that fits, and a group is not resolved until
every member both matches its siblings and clears its box.

What this deliberately does NOT do is enforce a punctuation POLICY. Description
lines in this corpus run 233 with a terminal period against 155 without, and the
Japanese runs 263 bare against 122 ending in 。, so there is no policy to
enforce and inventing one would rewrite hundreds of perfectly good lines. The
defect is DIVERGENCE INSIDE A GROUP, never the absence of a period.
"""

import collections
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from artl import config, store                                     # noqa: E402

# What makes two parallel entries differ is the index, not the sentence.
MASK = re.compile("[A-Za-z0-9"
                  "Ａ-Ｚａ-ｚ０-９"
                  "一二三四五六七八九十]")
KINDS = ("desc", "name", "ui", "term", "choice", "mapname", "message")
NL = chr(10)


def shape(text):
    """Terminal-stop fingerprint, blind to the varying index."""
    return tuple(line.rstrip().endswith((".", "!", "?"))
                 for line in MASK.sub("_", text).split(NL) if line.strip())


def main(*argv):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    show = int(argv[argv.index("--show") + 1]) if "--show" in argv else 20
    kinds = (tuple(argv[argv.index("--kinds") + 1].split(","))
             if "--kinds" in argv else KINDS)
    cfg = config.load()

    groups = collections.defaultdict(list)
    for _p, u in store.all_units(store.load_docs(cfg["store_dir"])):
        if u["kind"] not in kinds:
            continue
        if not (u.get("tl") or "").strip() or not (u.get("src") or "").strip():
            continue
        groups[(u["kind"], MASK.sub("_", u["src"]))].append(u)

    multi = [(k, v) for k, v in groups.items() if len(v) > 1]
    punct, words = [], []
    for k, v in multi:
        if len(set(shape(u["tl"]) for u in v)) > 1:
            punct.append((k, v))
        elif len(set(MASK.sub("_", u["tl"]) for u in v)) > 1:
            words.append((k, v))

    print("PARALLEL GROUPS over kinds %s" % ",".join(kinds))
    print("  groups with more than one member : %d" % len(multi))
    print("  diverging in WORDING              : %d" % len(words))
    print("  diverging in PUNCTUATION          : %d" % len(punct))
    for label, rows in (("WORDING", words), ("PUNCTUATION", punct)):
        for k, v in rows[:show]:
            print()
            print("  [%s] %s  %s"
                  % (v[0]["kind"], label, k[1].replace(NL, " / ")[:54]))
            for u in v:
                print("      %-30s %r"
                      % (u["id"][-28:], u["tl"].replace(NL, " / ")[:62]))
    return 1 if (punct or words) else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
