r"""Japanese left in the OUTPUT rom, found by walking it rather than re-extracting.

    census_gate.py [work/census_out.tsv] [--show 30]

    BakinTL census out work\census_out.tsv     # produce the input first

WHY THIS EXISTS, AND WHY `scan-output` IS NOT ENOUGH.

`tl.py scan-output` re-extracts the injected tree and looks for residual
Japanese. It therefore shares the EXTRACTOR's blind spot exactly: a string the
extractor cannot reach is not a unit, so it is not in the re-extraction, so the
scan reports it clean. It printed `never extracted as a unit: 0` while 50
Japanese battle messages sat in the shipped rom.

Those messages live at

    Condition.EffectParamSettings.EffectParamList[].Message

- a settable string property on an element of a list behind a property. A
Condition stores its battle text TWICE, the flat `messageForAlly` family and
this nested copy, and the ENGINE reads the nested one. Every unit in the store
was translated and every check was green.

`BakinTL census` walks every field and property generically, so it sees what the
whitelist cannot. The catch is that it sees EVERYTHING - 73,698 Japanese strings
in this game's output, almost all editor metadata. Raw census output is not a
gate; it is a haystack.

So this classifies each PATH and fails only on what it cannot account for:

    editor-name   object, event, folder and sheet names the editor shows
    asset-path    import paths, source file names, related paths
    formula       damage formulas - they reference variable NAMES, which are
                  keys and must stay Japanese
    key           switch and variable references, visibility conditions
    tag           editor tags
    script-attr   Script command arguments, where TEXT_SLOTS already decides
                  which slots are drawn
    REVIEW        anything else - a path nobody has classified yet

**REVIEW is the whole point.** A new engine build, a re-extraction or a game
update can introduce a path that holds player text, and the only safe default is
to fail on a path nobody has looked at. Classify it here once it has been
judged, with the reason in the table.
"""

import collections
import csv
import io
import os
import re
import sys

# path pattern -> why it is not player-facing. Ordered; first match wins.
CLASSES = [
    (r"(ImportPath|importPath|resourcePath|relatedPath|SourcePath|SourceFileName)$",
     "asset-path"),
    (r"\.path$", "asset-path"),
    (r"([Ff]ormula)$", "formula"),
    (r"^Script\.commands\[\]\.attrList\[\]\.value$", "script-attr"),
    (r"\.tags$", "tag"),
    (r"(visibilityCondition|conditionName|switchName|variableName)", "key"),
    (r"MenuSettings\.items\[\](\.subItems\[\])*\.name$", "editor-name"),
    (r"\.(name|_name|Name|category|GraphicName|stackName|graphicMotion)$",
     "editor-name"),
    (r"templateInfo$", "editor-help"),
    # `usName` is the layout editor's own label for a widget - the name shown in
    # the tree, never on screen. Distinct from `.text`, which IS drawn.
    (r"\.usName$", "editor-name"),
    (r"(visibilitySwitch|Motion)$", "key"),
    (r"(exportDestination|iconPath|[Nn]ormalMap)$", "asset-path"),
]

# Japanese that survives ONLY inside a code argument is a KEY - a variable or
# switch name the engine looks up - and must stay Japanese. This is judged on
# the VALUE, never on the path: `MenuItem.text` is a genuine display field, so
# excusing the whole path would hide a real untranslated label. Excusing one
# value because its Japanese is all inside `\$[...]` is safe.
CODE_ARG = re.compile(r"\\?[A-Za-z_#$]+\[[^\]]*\]")
JP = re.compile(r"[぀-ヿ㐀-䶿一-鿿]")


def is_code_key(value):
    return bool(value) and not JP.search(CODE_ARG.sub("", value))


def classify(path):
    for pat, verdict in CLASSES:
        if re.search(pat, path):
            return verdict
    return "REVIEW"


def main(*argv):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = [a for a in argv if not a.startswith("--")]
    path = args[0] if args else os.path.join("work", "census_out.tsv")
    show = int(argv[argv.index("--show") + 1]) if "--show" in argv else 30
    if not os.path.exists(path):
        print("no census at %s\n  run:  BakinTL census out %s" % (path, path))
        return 2

    with io.open(path, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    per_path = collections.Counter(r["path"] for r in rows)
    sample = {}
    for r in rows:
        sample.setdefault(r["path"], r["value"])

    # A path is only REVIEW if something under it is Japanese for a reason the
    # code-key rule cannot explain.
    real_jp = collections.Counter()
    for r in rows:
        if not is_code_key(r["value"]):
            real_jp[r["path"]] += 1

    buckets = collections.Counter()
    review = []
    for p, n in per_path.items():
        v = classify(p)
        if v == "REVIEW" and not real_jp.get(p):
            v = "code-key"
        buckets[v] += n
        if v == "REVIEW":
            review.append((real_jp.get(p, n), p, sample[p]))

    print("CENSUS GATE over %s" % path)
    print("  %d distinct paths, %d Japanese strings\n" % (len(per_path), len(rows)))
    for v, n in buckets.most_common():
        print("   %-14s %8d strings" % (v, n))
    print()
    if not review:
        print("  UNCLASSIFIED PATHS: 0 - every path carrying Japanese is accounted for")
        return 0
    print("  UNCLASSIFIED PATHS: %d  <-- judge each, then add it to CLASSES"
          % len(review))
    for n, p, v in sorted(review, reverse=True)[:show]:
        print("   %-66s x%-6d %r" % (p[:66], n, v[:32]))
    return 1


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
