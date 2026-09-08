#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qa.py - the passes no validator can do.

`ui` dumps every button, choice, notice and label as JP -> EN side by side.
A few hundred lines, minutes to skim, and it is the ONLY pass that catches a
short verb rendered as the wrong part of speech: `訂正する` ("correct it", i.e.
go back and re-enter) came back as "Correct", which reads as agreement and
sends the player the opposite way. It is English, it is short, it carries no
placeholders and no residual Japanese - every automated check passes it.

`scan-output` re-exports the INJECTED rom tree and scans that, not the store,
for two things a per-unit pass is structurally blind to:

  * A control code that survived injection - the most visible failure a patch
    can ship, and sentinel-multiset validation compares source to translation
    and cannot see it.
  * Lines the extractor never saw. Extraction keys on "contains a
    source-language character", so a line holding no Japanese was never a unit
    and no per-unit pass could ever reach it. A row of `______` or `！！！` is
    still on screen. Anything byte-identical between the source and the
    injected output was never a unit.
"""

import os
import re
import glob
import json
import collections

from . import codes, store

UI_KINDS = ("choice", "term", "ui", "title", "name", "desc", "affix",
            "mapname", "message", "sptext", "strvar", "codearg")

# A sentinel or a masked code that survived into the shipped text. The
# nameplate code is deliberately NOT here - it belongs in the output, with a
# translated name inside it.
LEAKED_CODE_RE = re.compile(
    r"⟦\s*\d+\s*⟧"
    r"|\\(?:c|w|z|v|s|h|H|Variable)\[[^\]\r\n]*\]"
    r"|\\[nbiu!^<>]\["
    r"|\\(?:blink|blspd|blrate|lipspd|lip)(?!\[)",
    re.I)

# Typographic conventions that must be converted whether or not they arrived
# attached to Japanese. Matched in BOTH widths, because authors write the same
# marker either way and a rule matching only the fullwidth form misses half.
CONVENTION_RE = re.compile(r"[＿_]{3,}|[！!]{3,}|[？?]{3,}|[。]{2,}|[、]{2,}|～{2,}")


# --------------------------------------------------------------------------
# Same-source consistency
# --------------------------------------------------------------------------
# This game deduplicates dialogue on (speaker, source) BEFORE translating -
# 83,999 units are 22,914 distinct pairs, and the measurement behind that
# ruling is documented on `store.dedup_key`. So the usual "same line, three
# different renderings" problem is mostly prevented rather than repaired here.
#
# What dedup cannot prevent is the case the standing rule exists for: a line
# reused by the SAME speaker in a DIFFERENT scene, where one rendering is right
# where it was written and wrong in the other. This pass is the after-the-fact
# half of that ruling, and it also catches drift introduced by a retry round or
# a hand edit.
#
# The 回想部屋 recollection rooms replay whole scenes, so the same line
# legitimately exists in several places and must read identically in all.
#
# Clusters are unified - except in the two cases where the reuse really is
# scene-dependent:
#
#   * a variant carrying a THIRD-PERSON pronoun. Japanese drops subjects and
#     MT invents them, so "he"/"she"/"they" may resolve to different people in
#     different scenes.
#   * a cluster spoken by MORE THAN ONE speaker. Register and first person
#     differ per speaker even when the source string does not.
#
# Those are reported for a human, never auto-unified.

_THIRD_PERSON_RE = re.compile(
    r"\b(?:he|him|his|himself|she|her|hers|herself|they|them|their|theirs|"
    r"themselves)\b", re.I)


def _pick(variants_by_text):
    """The winning rendering: most sites, then the canonical (non-replay)
    location, then the lowest id. Deterministic, so a re-run is a no-op."""
    def key(item):
        text, units = item
        # Prefer the rendering that was NOT written for a replay room: the
        # recollection rooms show a scene out of context, so their copy is the
        # one more likely to have lost a referent.
        replay = all("回想" in (u.get("owner") or "") for u in units)
        return (-len(units), replay, min(u["id"] for u in units))
    return sorted(variants_by_text.items(), key=key)[0][0]


def unify_repeats(store_dir, apply=False, verbose=True, show=8):
    docs = store.load_docs(store_dir)
    groups = collections.OrderedDict()
    for _p, doc in docs:
        for u in doc["units"]:
            if u["kind"] != "text" or not (u.get("tl") or "").strip():
                continue
            groups.setdefault(u["src"], []).append(u)

    unified = skipped = touched = 0
    review = []
    samples = []
    for src, units in groups.items():
        by_text = collections.OrderedDict()
        for u in units:
            by_text.setdefault(u["tl"], []).append(u)
        if len(by_text) < 2:
            continue
        speakers = {u.get("speaker", "") for u in units}
        third = any(_THIRD_PERSON_RE.search(t) for t in by_text)
        if third or len(speakers) > 1:
            why = ("third-person pronoun - may resolve to a different "
                   "character per scene" if third
                   else "spoken by %d different speakers" % len(speakers))
            # One id PER VARIANT, not the flat unit list: zipping distinct
            # texts against every unit id printed the wrong id beside each
            # rendering, which is worse than printing none.
            review.append((src, list(by_text),
                           [us[0]["id"] for us in by_text.values()], why))
            skipped += 1
            continue
        win = _pick(by_text)
        if len(samples) < show:
            samples.append((src, list(by_text), win))
        for u in units:
            if u["tl"] != win:
                if apply:
                    u["tl"] = win
                touched += 1
        unified += 1

    if apply:
        store.save_docs(docs)

    if verbose:
        print("SAME-SOURCE CONSISTENCY")
        print("  repeated lines with more than one rendering : %d"
              % (unified + skipped))
        print("  unified                                     : %d "
              "(%d unit(s) rewritten)" % (unified, touched))
        print("  left for review                             : %d" % skipped)
        for src, variants, win in samples:
            print("\n  JP  %s" % src.replace("\n", " / ")[:74])
            for v in variants:
                mark = "->" if v == win else "  "
                print("   %s %s" % (mark, v.replace("\n", " / ")[:74]))
        if review:
            print("\n  -- NOT unified, decide these by hand --")
            for src, variants, ids, why in review[:show]:
                print("\n  JP  %s" % src.replace("\n", " / ")[:74])
                print("      (%s)" % why)
                for v, i in zip(variants, ids):
                    print("      %-52s %s" % (v.replace("\n", " / ")[:52], i))
            if len(review) > show:
                print("\n  ... (%d more)" % (len(review) - show))
        if not apply:
            print("\ndry run - pass --apply to rewrite the store")
    return unified, skipped, touched


def dump_ui(cfg, store_dir, out_path=None, verbose=True):
    docs = store.load_docs(store_dir)
    rows = []
    for _p, doc in docs:
        for u in doc["units"]:
            if u["kind"] not in UI_KINDS:
                continue
            rows.append((u["kind"], u["id"], u.get("raw", ""),
                         (u.get("tl") or "").strip()))
    rows.sort(key=lambda r: (r[0], r[2]))
    seen = set()
    lines = ["# UI label review - read this, do not skim it.",
             "# A short verb rendered as the wrong part of speech passes every",
             "# automated check and sends the player the opposite way.", ""]
    for kind, uid, jp, en in rows:
        key = (kind, jp)
        if key in seen:
            continue
        seen.add(key)
        lines.append("[%-8s] %-38s -> %s" % (kind, jp, en or "<UNTRANSLATED>"))
        lines.append("            %s" % uid)
    text = "\n".join(lines)
    if out_path:
        with open(out_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
        if verbose:
            print("wrote %d unique UI labels -> %s" % (len(seen), out_path))
    elif verbose:
        print(text)
    return len(seen)


