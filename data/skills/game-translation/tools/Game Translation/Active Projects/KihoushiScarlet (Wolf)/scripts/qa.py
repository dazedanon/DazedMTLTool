#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qa.py - the passes no automated validator can replace, run over batch.json after
`claude_translate.py validate` comes back clean.

    python scripts/qa.py ui-pairs        > logs/ui-pairs.txt
    python scripts/qa.py parallel-drift
    python scripts/qa.py glued
    python scripts/qa.py nameplates
    python scripts/qa.py speaker-voice   > logs/speaker-voice.txt

`validate` proves a line is English, keeps its sentinels, and has no residual
Japanese. Every check here exists because a line can pass all of that and still be
wrong on screen.
"""

import os
import re
import sys
import json
import argparse
import collections

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(WS, "scripts"))

import claude_translate as ct  # noqa: E402


_BATCH = os.path.join(WS, "batch.json")
FIX = False


def lines():
    with open(_BATCH, encoding="utf-8") as f:
        return json.load(f)["lines"]


def _flat(s):
    return (s or "").replace("\n", " / ")


# --------------------------------------------------------------------------
def cmd_ui_pairs():
    """Dump every UI-ish label as JP -> EN, side by side, deduped.

    This is the only pass that catches a short verb rendered as the wrong part of
    speech. 訂正する means "go back and re-enter"; rendered as the bare adjective
    "Correct" it reads as agreement and sends the player the opposite way. It is
    English, it is short, it has no placeholders and no residual Japanese, so every
    automated check passes it. A few hundred lines, minutes to skim.
    """
    seen = set()
    rows = collections.defaultdict(list)
    for l in lines():
        k = ct.line_kind(l)
        if k not in ("ui", "choice", "name", "db", "system"):
            continue
        key = (k, l["source"])
        if key in seen:
            continue
        seen.add(key)
        rows[k].append((l["source"], l.get("text") or "", l.get("note") or ""))
    total = sum(len(v) for v in rows.values())
    print(f"# {total} distinct UI / choice / name / db / system labels")
    print("# READ THIS BY EYE. Look for a verb rendered as an adjective or noun.\n")
    for k in ("ui", "choice", "name", "db", "system"):
        if not rows[k]:
            continue
        print(f"\n{'=' * 70}\n== {k.upper()}  ({len(rows[k])})\n{'=' * 70}")
        for src, tl, note in sorted(rows[k]):
            n = f"   [{note[:40]}]" if note else ""
            print(f"{_flat(src)[:80]:<82} | {_flat(tl)[:80]}{n}")
    return 0


# --------------------------------------------------------------------------
# Entries that are PARALLEL by construction and drifted apart.
# Skimming will not catch these: 男A and 男B are two unequal strings, so a
# same-source check sees nothing. Mask the varying index and group on the rest.
_INDEX_RE = re.compile(r"[0-9０-９]+|(?<=[^A-Za-z])[A-Za-zＡ-Ｚａ-ｚ](?![A-Za-z])")


def _mask_index(s):
    return _INDEX_RE.sub("#", s)


def cmd_parallel_drift():
    seen = {}
    for l in lines():
        tl = l.get("text") or ""
        if not tl.strip():
            continue
        src = l["source"]
        if not ct.JP_RE.search(src):
            continue
        key = (ct.line_kind(l), _mask_index(src))
        seen.setdefault(key, {}).setdefault(_mask_index(tl), []).append((src, tl))
    groups = {k: v for k, v in seen.items() if len(v) > 1}
    if FIX and groups:
        _fix_parallel(seen, groups)
        return 0
    print(f"parallel groups: {len(seen)}   diverged: {len(groups)}")
    print("(resolve by CORPUS MAJORITY, not taste, then re-run the overflow check - "
          "the more literal variant is often the one that no longer fits)\n")
    for k, variants in sorted(groups.items(), key=lambda x: -len(x[1]))[:60]:
        print(f"-- {k[0]}: {_flat(k[1])[:70]!r}")
        for _mtl, pairs in sorted(variants.items(), key=lambda x: -len(x[1])):
            src, tl = pairs[0]
            print(f"     x{len(pairs):<4} {_flat(src)[:52]:<54} -> {_flat(tl)[:60]}")
    return 0 if not groups else 1


_NUM_RE = re.compile(r"[0-9０-９]+")


def _fix_parallel(seen, groups):
    """Re-render every diverged sibling from the group's MAJORITY template.

    Resolved by corpus majority rather than taste: which phrasing reads best is an
    opinion, but which one the player has already seen 52 times is a fact. The
    template is only usable when the majority translation contains its own source's
    number verbatim - otherwise the number cannot be located and the group is left
    for a human rather than guessed at.
    """
    import claude_translate as ct
    batch = json.load(open(_BATCH, encoding="utf-8"))
    by_id = {l["id"]: l for l in batch["lines"]}
    changed = skipped = 0
    for key, variants in groups.items():
        ranked = sorted(variants.items(), key=lambda x: -len(x[1]))
        _mtl, top = ranked[0]
        src0, tl0 = top[0]
        nums0 = _NUM_RE.findall(src0)
        if len(set(nums0)) != 1 or nums0[0] not in tl0:
            skipped += 1
            print(f"  ? cannot locate the number in the majority form; left alone: "
                  f"{_flat(tl0)[:70]!r}")
            continue
        n0 = nums0[0]
        for _m, pairs in ranked[1:]:
            for src, _old in pairs:
                nums = _NUM_RE.findall(src)
                if len(set(nums)) != 1:
                    skipped += 1
                    continue
                new_tl = tl0.replace(n0, nums[0])
                for l in batch["lines"]:
                    if l["source"] == src and (l.get("text") or "") != new_tl:
                        l["text"] = new_tl
                        changed += 1
    print(f"parallel-drift --fix: {changed} line(s) normalised to the majority form, "
          f"{skipped} group(s) left for a human")
    if changed:
        tmp = _BATCH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(batch, f, ensure_ascii=False, indent=1)
        os.replace(tmp, _BATCH)
        print("  batch.json written - re-run `claude_translate.py validate` and rebuild")


# --------------------------------------------------------------------------
def cmd_glued():
    """Render each VALUE-inserting {Wn} with a stand-in and look for it pressed
    against a letter.

    Two things keep this readable. It substitutes and reads the string a player
    would actually see, because reasoning about it structurally ("a literal ending
    in a letter before an expression") is mostly noise - a formatting prefix has the
    same shape. And it only fires on the 64 sentinels the legend shows are
    \\cself / \\cdb / \\udb / \\v inserts; run against all 86 it reported 59,249 hits,
    almost all of them colour spans and icons that must stay flush. A list nobody
    reads is not a check.
    """
    with open(_BATCH, encoding="utf-8") as f:
        batch = json.load(f)
    inserts = ct.insert_sentinels(batch)
    if not inserts:
        print("no value-inserting sentinels in this batch - nothing to check")
        return 0
    tok = re.compile("|".join(re.escape(t) for t in inserts))
    bad = re.compile(r"[A-Za-z0-9](?:\x00)|(?:\x00)[A-Za-z0-9]")
    hits = []
    for l in lines():
        tl = l.get("text") or ""
        if not tok.search(tl):
            continue
        rendered = tok.sub("\x00", tl)
        m = bad.search(rendered)
        if m:
            shown = rendered.replace("\x00", "<VALUE>")
            hits.append(("insert", l["file"], l["id"], _flat(tl)[:70],
                         _flat(shown)[max(0, m.start() - 25):m.end() + 40]))
    print(f"glued inserts: {len(hits)}   "
          f"(checked {len(inserts)} value-inserting sentinels of "
          f"{len(batch.get('_sentinel_legend') or {})})")
    print("(an insert that substitutes a NOUN needs a space in English; one that is "
          "a colour or line-break code must NOT be padded - check which each is in "
          "batch.json's _sentinel_legend before fixing)\n")
    for label, f, i, tl, ctx in hits[:80]:
        print(f"  [{label}] {f} {i}\n      tl : {tl}\n      as : ...{ctx}...")
    return 0 if not hits else 1


# --------------------------------------------------------------------------
def cmd_lexer():
    r"""Codes the engine's greedy escape lexer will swallow the next word into.

    Wolf lexes a backslash plus a LETTER RUN, so `
` followed by `s` becomes the
    unknown code `
so` and those words are never drawn - a bug English creates and
    Japanese cannot, because kana terminates the run. The same happens when a code
    that takes NO argument is followed by `[`: `\E[Base System Error]` reads as one
    bracketed code.

    Getting the rule right matters more than having it. Two wrong versions were
    written first. Flagging every `\X[` reports `\i[126]` and `\cself[8]`, which are
    codes that legitimately take a bracket - the whole corpus. And matching
    `\([A-Za-z]+)(?=[A-Za-z])` splits INSIDE a valid name, reporting `\csel` before
    the `f` of `\cself` 298 times. So: match the WHOLE run, then split it after the
    longest real code name, exactly as the fix for the bug has to.

    The name list is read off the batch's own legend plus Wolf's argument-less codes,
    never guessed.
    """
    with open(_BATCH, encoding="utf-8") as f:
        batch = json.load(f)
    legend = batch.get("_sentinel_legend") or {}

    bracket_names, bare_names = set(), set()
    for c in legend.values():
        m = re.match(r"\\([A-Za-z]+)\[", c)
        if m:
            bracket_names.add(m.group(1))
            continue
        m = re.match(r"\\([A-Za-z]+)$", c)
        if m:
            bare_names.add(m.group(1))
    bare_names |= {"n", "E"}           # line break / clear, both argument-less
    known = bracket_names | bare_names

    def unmask(x):
        for t in sorted(legend, key=lambda t: -int(t[2:-1])):
            x = x.replace(t, legend[t])
        return x

    run_re = re.compile(r"\\([A-Za-z]+)")
    sym_bracket_re = re.compile(r"\\([>.!^<|])(?=\[)")
    hits = collections.defaultdict(list)
    for l in lines():
        tl = l.get("text") or ""
        if not tl.strip():
            continue
        u = unmask(tl)
        for m in run_re.finditer(u):
            run = m.group(1)
            if run in known:
                continue
            pref = max((k for k in known if run.startswith(k)), key=len, default=None)
            if pref:
                hits["code+letter"].append(
                    (l, "\\" + run + "  (= \\" + pref + " + " + repr(run[len(pref):]) + ")"))
            # a run matching no known code at all is the author's own text, not ours
        for m in sym_bracket_re.finditer(u):
            hits["code+bracket"].append((l, m.group(0)))
        for m in re.finditer(r"\\([A-Za-z]+)(?=\[)", u):
            if m.group(1) in bare_names and m.group(1) not in bracket_names:
                hits["code+bracket"].append((l, m.group(0)))

    print(f"greedy-lexer collisions")
    print(f"  known bracketed codes : {sorted(bracket_names)}")
    print(f"  known bare codes      : {sorted(bare_names)}")
    total = 0
    for k, v in hits.items():
        total += len(v)
        print(f"  {k}: {len(v)} unit(s), {len({l['source'] for l, _ in v})} distinct")
        for l, tok in v[:6]:
            print(f"    ! {tok} in {l['id']}")
            print(f"      {_flat(unmask(l['text']))[:110]}")
    if not total:
        print("  none")
    return 0 if not total else 1


# --------------------------------------------------------------------------
def cmd_nameplates():
    """The speaker is peeled out of the body by the 【 】 convention, so a nameplate
    left Japanese passes every per-unit check. Report it ONCE per distinct speaker,
    not once per line - one bad speaker would otherwise print thousands of identical
    failures with the actual cause nowhere in sight."""
    bad = collections.Counter()
    good = collections.Counter()
    shape = 0
    for l in lines():
        m = ct.NAMEPLATE_RE.match(l["source"])
        if not m:
            continue
        tl = l.get("text") or ""
        if not tl.strip():
            continue
        mt = ct.NAMEPLATE_RE.match(tl)
        if not mt:
            shape += 1
            continue
        name = mt.group(1)
        (bad if ct.UNTRANSLATED_JP_RE.search(name) else good)[m.group(1) + " -> " + name] += 1
    print(f"distinct translated nameplates : {len(good)}")
    print(f"nameplates still Japanese      : {len(bad)} distinct")
    for k, n in bad.most_common():
        print(f"   ! {k}   ({n} lines)")
    print(f"lines whose 【 】\\n shape was lost: {shape}   "
          "(the engine parses that shape; losing it loses the speaker box)")
    print("\n-- every locked speaker rendering --")
    for k, n in good.most_common():
        print(f"   {n:6d}  {k}")
    return 0 if not bad and not shape else 1


# --------------------------------------------------------------------------
def cmd_speaker_voice():
    """Sample each speaker's lines so a human can check the register held.

    A gendered NOUN aimed at the addressee ("nice one, guy") is a misgender no
    pronoun check sees: it is a noun, about the listener, in a fluent line with no
    placeholders and no residual Japanese.
    """
    by = collections.defaultdict(list)
    for l in lines():
        m = ct.NAMEPLATE_RE.match(l["source"])
        if not m:
            continue
        tl = l.get("text") or ""
        if tl.strip():
            by[m.group(1)].append((l["source"], tl))
    print(f"# {len(by)} speakers; up to 6 sampled lines each\n")
    for spk, rows in sorted(by.items(), key=lambda x: -len(x[1])):
        print(f"\n== {spk}  ({len(rows)} lines)")
        seen = set()
        shown = 0
        for src, tl in rows:
            if tl in seen:
                continue
            seen.add(tl)
            print(f"   JP {_flat(src)[:100]}")
            print(f"   EN {_flat(tl)[:100]}")
            shown += 1
            if shown >= 6:
                break
    return 0


def main():
    global _BATCH, FIX
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("check", choices=["ui-pairs", "parallel-drift", "glued",
                                      "nameplates", "speaker-voice", "lexer"])
    # Point a check at tl/_selftest_batch.json to prove it can FIRE. A scan that
    # reports nothing has to show it could have reported something - a broken
    # reader and a clean corpus look identical, and the broken one is silent.
    ap.add_argument("--fix", action="store_true",
                    help="parallel-drift: rewrite diverged siblings from the "
                         "majority form")
    ap.add_argument("--batch", default=None,
                    help="read a different filled batch (e.g. tl/_selftest_batch.json)")
    args = ap.parse_args()
    FIX = args.fix
    if args.batch:
        _BATCH = os.path.join(WS, args.batch) if not os.path.isabs(args.batch) else args.batch
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    return {
        "ui-pairs": cmd_ui_pairs, "parallel-drift": cmd_parallel_drift,
        "glued": cmd_glued, "nameplates": cmd_nameplates,
        "speaker-voice": cmd_speaker_voice, "lexer": cmd_lexer,
    }[args.check]()


if __name__ == "__main__":
    sys.exit(main() or 0)
