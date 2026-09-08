#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_glossary.py - assemble tl/glossary.json + tl/game_prompt.md from the
glossary-workflow artifacts in tl/_sources/, and audit the result against the
corpus.

    python scripts/make_glossary.py build     # write glossary.json + game_prompt.md
    python scripts/make_glossary.py audit     # check the built glossary vs batch.json

`tl/_sources/` holds one JSON per workflow run:

    characters.json  {"names": [{jp, en, gender, role, register, aliases}, ...]}
    terms.json       {"terms": [{jp, en}, ...], "do_not_translate": [...]}
    ui_terms.json    same shape as terms.json
    bible.md         the game bible, verbatim

The merge is deterministic and re-runnable: a fix goes into `_sources/`, not into
the generated files, so a later rebuild does not silently drop it.
"""

import os
import re
import sys
import json
import argparse
import collections

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(WS, "tl", "_sources")
GLOSSARY = os.path.join(WS, "tl", "glossary.json")
PROMPT = os.path.join(WS, "tl", "game_prompt.md")
BATCH = os.path.join(WS, "batch.json")

# `Data\` is a literal path fragment the extractor picked up; it is the only
# string in this corpus that carries a backslash and it must ship untouched.
BASE_DNT = ["Data\\"]


# RAW backslash codes only. A {Wn} sentinel must NOT be stripped: the UI terms are
# already in masked form, and removing their sentinels turns `{W1}の` into the bare
# particle `の` - a key that matches almost every chunk and teaches the model
# nothing, and `速度 X {W7} Y {W8}` into a string the corpus does not contain.
_CODE_RE = re.compile(r"\\[A-Za-z]+\[[^\]]*\]|\\[A-Za-z]")


def _strip_codes(s):
    return _CODE_RE.sub("", s).strip()


_CORPUS = {}


def _corpus_blob():
    if "b" not in _CORPUS:
        with open(BATCH, encoding="utf-8") as f:
            _CORPUS["b"] = "\n".join(l["source"] for l in json.load(f)["lines"])
    return _CORPUS["b"]


def _read(name, default=None):
    p = os.path.join(SRC, name)
    if not os.path.exists(p):
        return default
    with open(p, encoding="utf-8") as f:
        return f.read() if name.endswith(".md") else json.load(f)


def cmd_build():
    chars = (_read("characters.json") or {}).get("names", [])
    terms = []
    dnt = list(BASE_DNT)
    for fn in ("terms.json", "ui_terms.json"):
        d = _read(fn) or {}
        terms += d.get("terms", [])
        dnt += d.get("do_not_translate", [])
    bible = _read("bible.md", "")

    names = collections.OrderedDict()
    for n in chars:
        jp = (n.get("jp") or "").strip()
        en = (n.get("en") or "").strip()
        if not jp or not en:
            continue
        names[jp] = {k: v for k, v in (
            ("en", en),
            ("gender", (n.get("gender") or "").strip() or None),
            ("role", (n.get("role") or "").strip() or None),
            ("register", (n.get("register") or "").strip() or None),
            ("aliases", [a for a in (n.get("aliases") or []) if a and a != jp] or None),
        ) if v}

    tmap = collections.OrderedDict()
    stripped = 0
    for t in terms:
        jp = (t.get("jp") or "").strip()
        en = (t.get("en") or "").strip()
        # The batch the model sees is sentinel-masked, so a glossary key carrying a
        # raw \c[2] prefix or an \i[126] suffix can never match the chunk text and
        # is silently dead weight in the prompt. Key on the bare word and strip the
        # matching decoration off the English so the pair still lines up.
        bare = _strip_codes(jp)
        if bare != jp:
            stripped += 1
            en = _strip_codes(en)
            jp = bare
        # a term that is already a locked character name would send two competing
        # instructions for the same string
        if jp and en and jp not in names:
            tmap.setdefault(jp, en)

    # A {Wn} sentinel does not belong on the denylist: the multiset guard already
    # makes dropping one a hard failure, and listing all 86 just pads every request
    # with a block that teaches the model nothing. The denylist is for source
    # strings that must survive as themselves.
    # The digests flattened CRLF to LF, so a multi-line key written from them never
    # matches the 109 CRLF units in the corpus (all database descriptions). Match on
    # the real corpus text and rewrite the key, rather than leaving a rule that is
    # present, plausible, and silently never applied.
    corpus = _corpus_blob()
    crlf_fixed = 0
    for jp in list(tmap):
        if "\n" in jp and jp not in corpus:
            alt = jp.replace("\r\n", "\n").replace("\n", "\r\n")
            if alt in corpus:
                tmap[alt] = tmap.pop(jp)
                crlf_fixed += 1

    seen = set()
    dnt_final = []
    for s in dnt:
        s = (s or "").strip()
        if s and s not in seen and not re.fullmatch(r"\{W\d+\}", s):
            seen.add(s)
            dnt_final.append(s)
    for jp in list(tmap):
        if jp in seen:
            del tmap[jp]

    with open(GLOSSARY, "w", encoding="utf-8") as f:
        json.dump({"names": names, "terms": tmap, "do_not_translate": dnt_final},
                  f, ensure_ascii=False, indent=1)
    if bible:
        with open(PROMPT, "w", encoding="utf-8") as f:
            f.write(bible.rstrip() + "\n")

    print(f"wrote {GLOSSARY}")
    print(f"  names            : {len(names)}")
    print(f"  terms            : {len(tmap)}")
    print(f"  do_not_translate : {len(dnt_final)}")
    if crlf_fixed:
        print(f"  ({crlf_fixed} multi-line key(s) re-pointed at the corpus's CRLF form)")
    if stripped:
        print(f"  ({stripped} term key(s) had control codes stripped so they can match "
              "the sentinel-masked chunk text)")
    print(f"wrote {PROMPT}  ({len(bible)} chars)" if bible else "  ! no bible.md in _sources")
    return 0


def cmd_audit():
    with open(GLOSSARY, encoding="utf-8") as f:
        g = json.load(f)
    with open(BATCH, encoding="utf-8") as f:
        lines = json.load(f)["lines"]
    sources = [l["source"] for l in lines]
    blob = "\n".join(sources)

    # A collision only breaks the GAME where the colliding string is a real database
    # ROW NAME, because that is the only position the engine resolves by name. Two
    # nameplate labels merging onto one English name is usually correct - the author
    # typed 受付お姉さん and 受付のお姉さん for the same person - so those are reported
    # separately and do not fail the audit. A string is not a key; a position is.
    with open(os.path.join(WS, "out", "names.json"), encoding="utf-8") as f:
        row_names = {n["source"] for n in json.load(f)["names"]}

    print("== English collisions ==")
    rev = collections.defaultdict(list)
    for jp, v in g["names"].items():
        rev[v["en"]].append(jp)
    for jp, en in g["terms"].items():
        rev[en].append(jp)
    dup = {en: jps for en, jps in rev.items() if len(jps) > 1}
    blockers = {en: jps for en, jps in dup.items()
                if sum(1 for jp in jps if jp in row_names) > 1}
    cosmetic = {en: jps for en, jps in dup.items() if en not in blockers}
    print(f"   BLOCKER - two DATABASE ROW NAMES share one English string: {len(blockers)}")
    for en, jps in list(blockers.items())[:25]:
        print(f"    ! {en!r} <- {jps}")
    print(f"   informational - display-only labels merged onto one name: {len(cosmetic)}")
    for en, jps in list(cosmetic.items())[:25]:
        print(f"    . {en!r} <- {jps}")

    print("\n== glossary entries that never occur in the corpus ==")
    dead = [jp for jp in list(g["names"]) + list(g["terms"]) if jp not in blob]
    print(f"   {len(dead)} dead entry(ies)")
    for jp in dead[:25]:
        print(f"    ? {jp!r}")

    print("\n== nameplate speakers with no glossary entry ==")
    NP = re.compile(r"^【([^】\n]{1,24})】")
    spk = collections.Counter()
    for s in sources:
        m = NP.match(s)
        if m:
            spk[m.group(1)] += 1
    missing = [(n, c) for n, c in spk.most_common() if n not in g["names"]]
    print(f"   {len(missing)} of {len(spk)} speakers unlocked "
          f"({sum(c for _n, c in missing)} lines)")
    for n, c in missing[:30]:
        print(f"    ! {n!r}  ({c} lines)")

    print("\n== do_not_translate entries that are PLAYER-VISIBLE somewhere ==")
    # A string is not a key - a POSITION is. Report any dnt entry that also shows up
    # as a dialogue, choice or UI unit, because there it must be translated.
    # `speaker == "UI"` alone is too weak a signal: WolfDawn tags a resource-path
    # SetString and a menu button identically. Flag only positions where the string
    # is genuinely drawn - a menu CHOICE, or inside a line that carries a nameplate.
    risky, embedded = [], []
    for s in g["do_not_translate"]:
        for l in lines:
            src = l["source"]
            if src.strip() == s and (l.get("speaker") == "Choice"
                                     or src.startswith("【")):
                risky.append((s, l["file"], l["id"]))
                break
        else:
            # not drawn as a whole unit, but it is an ordinary word that occurs
            # inside prose. Harmless as long as the denylist is applied to the
            # whole-unit position only - which hard_issues now does - but worth
            # seeing, because a global strip here blinds the residual-JP check.
            n = sum(1 for l in lines if s in l["source"] and l["source"].strip() != s)
            if n:
                embedded.append((s, n))
    print(f"   {len(risky)} entry(ies) drawn as a player-facing unit")
    for s, f, i in risky:
        print(f"    ! {s!r} at {f} {i}")
    print(f"   {len(embedded)} entry(ies) also occur INSIDE prose "
          "(fine - the denylist is scoped to the whole-unit position)")
    for s, n in sorted(embedded, key=lambda x: -x[1])[:15]:
        print(f"    . {s!r} inside {n} other unit(s)")

    print("\n== gender coverage ==")
    ng = [jp for jp, v in g["names"].items() if not v.get("gender")]
    print(f"   {len(ng)} name(s) with no gender - the pronoun resolver cannot use these")
    for jp in ng[:20]:
        print(f"    ? {jp!r}")

    fail = bool(blockers) or bool(risky)
    print("\nAUDIT", "FAIL" if fail else "OK")
    return 1 if fail else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["build", "audit"])
    args = ap.parse_args()
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    os.makedirs(SRC, exist_ok=True)
    return cmd_build() if args.action == "build" else cmd_audit()


if __name__ == "__main__":
    sys.exit(main() or 0)
