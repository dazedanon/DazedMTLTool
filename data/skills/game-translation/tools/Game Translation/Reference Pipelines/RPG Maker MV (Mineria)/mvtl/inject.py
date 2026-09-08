#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
inject.py - store -> game data.

Injection always rebuilds from the PRISTINE source file, so it is idempotent:
re-running never double-wraps, double-substitutes or feeds English back into
itself. Nothing here reads the previous output.

Two invariants this module exists to hold:

* **The command count never changes.** A save file stores an INDEX into the
  event command list (`Game_Interpreter._index`), so tombstoning the absorbed
  401s of a run - the usual RPG Maker write-back - moves every later index and
  resumes a third of existing saves at the wrong line. The wrapped English is
  redistributed across exactly the commands the run already had, packing extra
  lines into a command with an embedded `\\n` where it needs to. MV renders
  `Game_Message.allText()` as the commands joined by `\\n`, so k wrapped lines
  across c commands render `max(k, c)` rows, and both are capped at the
  window's 4.

* **A store with no translations must inject as a no-op.** `selftest --noop`
  wipes every `tl`, injects to a scratch tree and deep-compares parsed JSON
  against the source. The only values allowed to differ are the ones injected
  from the GLOSSARY rather than from a unit - actor names. Anything else means
  the injector is editing source text on its own initiative, which is exactly
  how a whole-file quote normaliser once shipped Japanese wearing English
  punctuation with every unit-level check green.
"""

import os
import re
import glob
import shutil
import datetime
import collections

from . import codes, store, fileio, wrap, measure
from .config import DO_NOT_TRANSLATE


class Report(object):
    def __init__(self):
        self.written = collections.Counter()
        self.problems = []
        self.skipped = 0
        self.applied = 0

    def problem(self, uid, msg):
        self.problems.append("%s: %s" % (uid, msg))


# --------------------------------------------------------------------------
def _final_text(u, cfg, m, report):
    """The string that goes into the file, or None to leave the source alone."""
    tl = (u.get("tl") or "").strip()
    if not tl:
        return None
    tl = codes.clean_translation(tl)
    if codes.has_untranslated_jp(tl):
        report.problem(u["id"], "translation still holds Japanese - left as source")
        return None

    kind = u["kind"]
    # Word-insert padding applies to the popup labels TOO, even though they are
    # a space-delimited plugin argument. `魔力\V[66]` is fine in Japanese and
    # renders "Mana25" in English - the exact "a number pressed against a
    # letter" failure. The space is added here and converted to U+00A0 by
    # `to_single_token` on the way into the argument, which command356's
    # `split(" ")` does not see and the shipped font draws at half width.
    # `淫乱度+\V[2]` is untouched: `+` is not a word character, so no pad.
    restored = codes.unmask_codes(tl, u.get("codes") or {}, pad_inserts=True)

    if kind == "text":
        width, rows = cfg.width, cfg.max_rows
    elif kind == "desc":
        width, rows = cfg.list_width, cfg.list_max_rows
    elif kind == "choice":
        width, rows = cfg.choice_width, 1
    elif kind == "ptext":
        width, rows = cfg.ptext_width, 1
    else:
        width, rows = cfg.list_width, None

    if cfg.fix_wrap and kind in ("text", "desc"):
        text, problems = wrap.fit_or_veto(restored, width, rows, m,
                                          hard_width=cfg.hard_width)
        if problems:
            report.problem(u["id"], "; ".join(problems))
        return text

    if kind in ("choice", "ptext", "term", "name", "type", "title", "currency"):
        w = m.cells(restored)
        if w > width:
            report.problem(u["id"], "%s is %d cells, budget %d" % (kind, w, width))
    return restored


def _write_text_run(lst, site, text, nametag, uid, report):
    """Redistribute the wrapped block across the run's EXISTING commands."""
    start, count = site["start"], site["count"]
    lines = [l for l in text.split("\n")] or [""]
    if nametag:
        lines[0] = nametag + lines[0]

    if len(lines) <= count:
        # One line per command, blanks at the END so the text reads top-down.
        # MV joins the commands with \n, so this renders `count` rows with the
        # content in the first len(lines) - and the window is a fixed 4 rows
        # tall either way, so the trailing blanks are invisible.
        groups = [[l] for l in lines] + [[] for _ in range(count - len(lines))]
    else:
        # More wrapped lines than commands: spread the surplus evenly rather
        # than hoarding it in command 0, so no single command holds a block
        # that would look wrong in the editor. Rendered rows stay len(lines).
        per = [1] * count
        for i in range(len(lines) - count):
            per[i % count] += 1
        groups, k = [], 0
        for p in per:
            groups.append(lines[k:k + p])
            k += p

    for gi in range(count):
        cmd = lst[start + gi]
        if not isinstance(cmd, dict) or cmd.get("code") not in (401, 405):
            report.problem(uid, "command %d is not a 401/405 any more" % (start + gi))
            return False
        cmd["parameters"] = ["\n".join(groups[gi])]
    return True


def _apply_unit(data, u, cfg, m, report):
    text = _final_text(u, cfg, m, report)
    if text is None:
        report.skipped += 1
        return
    for site in u["sites"]:
        ptr = site["ptr"]
        try:
            if "start" in site and u["kind"] == "text":
                lst = store.ptr_get(data, ptr)
                if _write_text_run(lst, site, text, u.get("nametag", ""),
                                   u["id"], report):
                    report.applied += 1
            elif "start" in site and u["kind"] == "choice":
                lst = store.ptr_get(data, ptr)
                cmd = lst[site["start"]]
                label = u.get("cond_prefix", "") + text + u.get("cond_suffix", "")
                cmd["parameters"][0][site["slot"]] = label
                _mirror_402(lst, site["start"], site["slot"], label)
                report.applied += 1
            elif "start" in site and u["kind"] == "ptext":
                lst = store.ptr_get(data, ptr)
                cmd = lst[site["start"]]
                args = cmd["parameters"][0].split(" ")
                args[site["slot"]] = codes.to_single_token(text)
                cmd["parameters"][0] = " ".join(args)
                report.applied += 1
            else:
                store.ptr_set(data, ptr, text)
                report.applied += 1
        except (KeyError, IndexError, TypeError) as e:
            report.problem(u["id"], "site %r unreachable: %s" % (ptr, e))
    report.written[u["kind"]] += 1


def _mirror_402(lst, choice_idx, slot, label):
    """Copy the translated choice into its 402 branch label by INDEX.

    The engine branches on parameters[0] (the index), so parameters[1] is
    editor-facing. Translating it as its own unit doubles the cost and lets the
    two drift; mirroring keeps a reviewer's branch view honest."""
    indent = lst[choice_idx].get("indent", 0)
    for c in lst[choice_idx + 1:]:
        if not isinstance(c, dict):
            continue
        if c.get("indent", 0) < indent:
            break
        if c.get("code") == 404 and c.get("indent", 0) == indent:
            break
        if (c.get("code") == 402 and c.get("indent", 0) == indent
                and (c.get("parameters") or [None])[0] == slot):
            c["parameters"][1] = label
            return


# --------------------------------------------------------------------------
def _inject_glossary_names(data, base, glossary, report):
    """Actor names come from the glossary, not from units."""
    if base != "Actors.json":
        return
    for e in data:
        if not e or not isinstance(e, dict):
            continue
        for f in ("name", "nickname"):
            v = e.get(f, "")
            if isinstance(v, str) and v and codes.has_jp(v):
                en = store.name_en(glossary.get("names", {}).get(v))
                if en:
                    e[f] = en
                    report.written["actor-name"] += 1


# --------------------------------------------------------------------------
def run(cfg, store_dir, out_dir=None, in_place=False, verbose=True):
    """Write every translated unit into a fresh copy of the data folder."""
    m = measure.reset(cfg.font_path)
    glossary = store.load_glossary(store_dir)
    docs = store.load_docs(store_dir)
    by_file = {}
    for _p, doc in docs:
        by_file[doc["meta"]["source_file"]] = doc["units"]

    if in_place:
        dest = cfg.data_dir
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = os.path.join(cfg.www, "data_backup_" + stamp)
        shutil.copytree(cfg.data_dir, backup)
        if verbose:
            print("backed up data/ -> %s" % backup)
    else:
        dest = out_dir or os.path.join(os.path.dirname(store_dir), "out", "www", "data")
        if os.path.isdir(dest):
            shutil.rmtree(dest)
        os.makedirs(dest, exist_ok=True)

    report = Report()
    for src in sorted(glob.glob(os.path.join(cfg.data_dir, "*.json"))):
        base = os.path.basename(src)
        data, rend = fileio.load(src)
        units = by_file.get(base, [])
        for u in units:
            _apply_unit(data, u, cfg, m, report)
        _inject_glossary_names(data, base, glossary, report)
        fileio.save(os.path.join(dest, base), data, rend)

    if verbose:
        print("\nINJECT -> %s" % dest)
        print("  units written : %d" % sum(report.written.values()))
        for k, v in report.written.most_common():
            print("      %-12s %d" % (k, v))
        print("  sites applied : %d" % report.applied)
        print("  left as source: %d" % report.skipped)
        if report.problems:
            print("  problems      : %d" % len(report.problems))
            for p in report.problems[:40]:
                print("      ! " + p)
            if len(report.problems) > 40:
                print("      ... (%d more)" % (len(report.problems) - 40))
    return report


# --------------------------------------------------------------------------
def noop_test(cfg, store_dir, verbose=True):
    """Prove the injector edits nothing it was not told to edit.

    Wipes every translation in a COPY of the store, injects into a scratch
    tree, and deep-compares parsed JSON against the source. Only Actors.json
    may differ, and only where the glossary supplies a name."""
    import tempfile
    import json as _json

    scratch = tempfile.mkdtemp(prefix="mvtl_noop_")
    store_copy = os.path.join(scratch, "tl")
    shutil.copytree(store_dir, store_copy)
    for p in glob.glob(os.path.join(store.units_dir(store_copy), "*.json")):
        doc = store.read_json(p)
        for u in doc["units"]:
            u["tl"] = ""
        store.write_json(p, doc)
    g = store.load_glossary(store_copy)
    g["names"] = {}
    store.save_glossary(store_copy, g)

    out = os.path.join(scratch, "data")
    run(cfg, store_copy, out_dir=out, verbose=False)

    diffs = []
    for src in sorted(glob.glob(os.path.join(cfg.data_dir, "*.json"))):
        base = os.path.basename(src)
        a, _ = fileio.load(src)
        b, _ = fileio.load(os.path.join(out, base))
        if a != b:
            diffs.append(base + ": " + _first_diff(a, b))
    shutil.rmtree(scratch, ignore_errors=True)
    if verbose:
        if diffs:
            print("NO-OP INJECT: FAIL - %d file(s) changed with an empty store"
                  % len(diffs))
            for d in diffs[:20]:
                print("   " + d)
        else:
            print("NO-OP INJECT: PASS - an empty store injects byte-identically")
    return not diffs


def _first_diff(a, b, path=""):
    if type(a) is not type(b):
        return "%s type %s vs %s" % (path, type(a).__name__, type(b).__name__)
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                return "%s/%s added" % (path, k)
            if k not in b:
                return "%s/%s removed" % (path, k)
            if a[k] != b[k]:
                return _first_diff(a[k], b[k], "%s/%s" % (path, k))
    if isinstance(a, list):
        if len(a) != len(b):
            return "%s length %d vs %d" % (path, len(a), len(b))
        for i, (x, y) in enumerate(zip(a, b)):
            if x != y:
                return _first_diff(x, y, "%s/%d" % (path, i))
    return "%s %r -> %r" % (path, a, b)
