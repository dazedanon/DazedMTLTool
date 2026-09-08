#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ablate each number-canonicalisation rule and report its NET effect.

A rule that removes twelve false positives and creates fifteen new ones is not
an improvement, and the only way to know which it did is to turn it off and
count. Prints the flag count with every rule on, then with each one disabled.
"""
import os, sys, re, collections
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from artl import store, validate as V

docs = store.load_docs(os.path.join(HERE, "tl"))
PAIRS = [(u, u["src"], (u.get("tl") or "").strip())
         for _d, u in store.all_units(docs) if (u.get("tl") or "").strip()]


def count(**off):
    saved = {}
    if off.get("kana"):
        saved["kana"] = V._KANA_NUM_RE
        V._KANA_NUM_RE = re.compile(r"(?!x)x")
    if off.get("digit_scale"):
        saved["digit_scale"] = V._DIGIT_SCALE_RE
        V._DIGIT_SCALE_RE = re.compile(r"(?!x)x")
    if off.get("bare_scale"):
        saved["bare_scale"] = V._BARE_SCALE_RE
        V._BARE_SCALE_RE = re.compile(r"(?!x)x")
    if off.get("ban"):
        saved["ban"] = V._KANJI_NUM_RE
        V._KANJI_NUM_RE = re.compile(
            r"(?<![0-9何])([〇零一二三四五"
            r"六七八九十百千万兆]{1,8})"
            r"(?=[" + "日人個回年月時秒匹"
            "枚本階度倍円歳割層つ" + r"])")
    if off.get("ordinal"):
        saved["ordinal"] = V._ORDINAL_RE
        V._ORDINAL_RE = re.compile(r"(?!x)x")
    ids = []
    for u, src, tl in PAIRS:
        if V._visible_numbers(src) != V._visible_numbers(tl):
            ids.append(u["id"])
    for k, v in saved.items():
        setattr(V, {"kana": "_KANA_NUM_RE", "digit_scale": "_DIGIT_SCALE_RE",
                    "bare_scale": "_BARE_SCALE_RE", "ban": "_KANJI_NUM_RE",
                    "ordinal": "_ORDINAL_RE"}[k], v)
    return set(ids)


base = count()
print("all rules on          : %d flags" % len(base))
for name in ("kana", "digit_scale", "bare_scale", "ban", "ordinal"):
    off = count(**{name: True})
    added = len(off - base)      # this rule REMOVES these when on
    removed = len(base - off)    # this rule CREATES these when on
    print("  %-12s off -> %4d flags   (rule fixes %3d, rule causes %3d, net %+d)"
          % (name, len(off), added, removed, removed - added))
