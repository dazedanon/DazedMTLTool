#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
qa_scan.py - the passes that read the INJECTED build rather than the store.

Kept separate from `qa.py` because it shells out to BakinTL and needs the game
folder, while everything in `qa.py` is pure Python over the store.
"""

import collections
import json
import os
import subprocess

from . import store
from .qa import CONVENTION_RE, LEAKED_CODE_RE


def _load(path):
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                u = json.loads(line)
                out[u["key"]] = u["src"]
    return out


def scan_output(cfg, out_dir=None, verbose=True):
    r"""Re-export the injected rom tree and scan what the engine will read.

    Two classes no per-unit pass can reach:

      * A sentinel or control code that survived injection - the most visible
        failure a patch can ship. Sentinel-multiset validation compares source
        to translation and is structurally blind to it.
      * Lines the extractor never saw. Extraction keys on "contains Japanese",
        so a string holding none was never a unit and nothing per-unit could
        ever reach it. A row of `______` or `！！！` is still on screen.
        Anything byte-identical between the pristine export and the injected
        one was never a unit.
    """
    out_dir = out_dir or cfg["out_dir"]
    scan_dir = os.path.join(cfg["work_dir"], "_injected")
    os.makedirs(scan_dir, exist_ok=True)
    env = dict(os.environ, BAKIN_DATA=os.path.join(cfg["game_dir"], "data"))
    rc = subprocess.call([cfg["bakintl"], "export", out_dir, scan_dir], env=env)
    if rc != 0:
        print("BakinTL export of the injected tree failed (rc=%d)" % rc)
        return 1

    pristine = _load(os.path.join(cfg["work_dir"], "units.jsonl"))
    after = _load(os.path.join(scan_dir, "units.jsonl"))

    survived = {k: v for k, v in after.items() if pristine.get(k) == v}
    leaked = []
    conventions = collections.Counter()
    for k, v in after.items():
        if LEAKED_CODE_RE.search(v):
            leaked.append((k, v[:70]))
        for m in CONVENTION_RE.finditer(v):
            conventions[m.group(0)] += 1

    docs = store.load_docs(cfg["store_dir"])
    known = {u["key"] for _p, doc in docs for u in doc["units"]}
    never = {k: v for k, v in survived.items() if k not in known}

    if verbose:
        print("OUTPUT SCAN over %s" % out_dir)
        print("  strings still containing Japanese : %d" % len(after))
        print("     byte-identical to the source   : %d" % len(survived))
        print("     never extracted as a unit      : %d" % len(never))
        print("  leaked sentinels / control codes  : %d" % len(leaked))
        for k, v in leaked[:15]:
            print("     ! %-44s %s" % (k[:44], v))
        for k, v in list(never.items())[:15]:
            print("     ? %-44s %s" % (k[:44], v[:60]))
        if conventions:
            print("  typographic runs still in the OUTPUT that a convention "
                  "pass should have converted - these are invisible to every "
                  "per-unit check when they carry no Japanese:")
            for tok, n in conventions.most_common(10):
                print("     %-12r %d" % (tok, n))
    return 0 if not leaked else 1


def speaker_report(cfg, store_dir, out_path=None, verbose=True):
    r"""Every nameplate speaker with its line count and approved English name.

    The nameplate is markup on this engine (`\NPL[..]`), so this list is exact
    rather than a guess - and it is the roster the model is handed. A blank
    English column is a character who will ship under whatever spelling the
    model invented for the prose, with nothing holding the name box to it.
    """
    docs = store.load_docs(store_dir)
    g = store.load_glossary(store_dir)
    counts = collections.Counter()
    scenes = collections.defaultdict(set)
    for _p, doc in docs:
        for u in doc["units"]:
            if u.get("speaker"):
                counts[u["speaker"]] += 1
                scenes[u["speaker"]].add(u["owner"])
    # The nameplate has a real, narrow, CLIPPING box - 234px at its narrowest
    # of 36 slots - and it is on screen for 71,519 lines. A name that overruns
    # it is cut, and that is the most visible label the patch can break.
    from . import budgets, measure
    m = measure.reset(cfg)
    plate_px = budgets.nameplate_px(docs, m)
    lines = ["# Nameplate speakers, most frequent first.",
             "# Budget %.0fpx - the widest the AUTHOR ships. The narrowest of "
             "the 36 slots is %.0fpx, but 11 shipped Japanese nameplates "
             "exceed it, so that slot is not the visual bound."
             % (plate_px, budgets.NAMEPLATE_SLOT_PX),
             "# %s" % m.describe(),
             "# lines  scenes  px  JP -> EN  (gender; role)", ""]
    missing = over = 0
    for jp, n in counts.most_common():
        v = g.get("names", {}).get(jp)
        en = store.name_en(v)
        if not en:
            missing += 1
        px = m.width(en) if en else 0.0
        flag = ""
        if en and px > plate_px:
            over += 1
            flag = "  !! CLIPPED, needs <= %.0fpx" % plate_px
        meta = ""
        if isinstance(v, dict):
            bits = [b for b in (v.get("gender") or "", v.get("role") or "") if b]
            meta = ("  (%s)" % "; ".join(bits)) if bits else ""
        lines.append("%6d  %6d %4.0f  %-22s -> %s%s%s"
                     % (n, len(scenes[jp]), px, jp, en or "<UNTRANSLATED>",
                        meta, flag))
    text = "\n".join(lines)
    if out_path:
        with open(out_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
    if verbose:
        print("%d distinct speakers, %d without an approved English name, "
              "%d too wide for the %.0fpx nameplate"
              % (len(counts), missing, over, plate_px))
        print(("-> %s" % out_path) if out_path else text)
    return missing
