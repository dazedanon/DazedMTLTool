#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
inject.py - store -> .rvdata2.

Injection always rebuilds from the PRISTINE file, so it is idempotent:
re-running never double-wraps, double-substitutes or feeds English back into
itself. Nothing here reads the previous output.

Three invariants this module exists to hold.

* **The command count never changes.** A VX Ace save marshals the whole
  `$game_map.interpreter`, including `@index` - an INDEX into the command list
  it was running - and `Game_Interpreter#setup` re-binds `@list` from the map
  data on load. Insert or delete a command and every later index moves, so a
  save taken mid-event resumes on the wrong line. The wrapped English is
  redistributed across exactly the commands the run already had: Ace joins a
  box's 401s with "\n" (`Game_Message#all_text`), so k wrapped lines across c
  commands still render k rows, and both are capped at the window's four.

* **A store with no translations injects byte-identically.** Not
  "structurally", not "semantically" - the same bytes. `rvmarshal` round-trips
  all 231 files exactly, so `noop_test()` compares file bytes and any
  difference at all is the injector editing something it was not told to edit.

* **The name plate keeps working.** `\NAME[...]` is peeled off before the model
  sees the line and re-attached here with the English name from the glossary,
  so a speaker tag can be neither paraphrased into the dialogue nor dropped.
"""

import os
import glob
import shutil
import datetime
import collections

from . import codes, store, rvdata, wrap, measure
from . import rvmarshal as M


class Report(object):
    def __init__(self):
        self.written = collections.Counter()
        self.problems = []
        self.skipped = 0
        self.applied = 0

    def problem(self, uid, msg):
        self.problems.append("%s: %s" % (uid, msg))


# --------------------------------------------------------------------------
def budget(u, cfg):
    """(width, hard_width, rows) for one unit.

    A message with a face graphic is drawn from `new_line_x` = 112 px, so its
    box is ten cells narrower. That is a per-unit envelope, not a per-kind one,
    and using the wide budget on a faced line is how text runs under the
    portrait."""
    kind = u["kind"]
    if kind == "text":
        if u.get("faced"):
            return cfg.face_width, cfg.face_hard_width, cfg.max_rows
        return cfg.width, cfg.hard_width, cfg.max_rows
    if kind == "desc":
        return cfg.desc_width, cfg.desc_width, cfg.desc_max_rows
    if kind == "choice":
        return cfg.choice_width, cfg.choice_width, 1
    if kind == "name":
        return cfg.name_width, cfg.name_width, 1
    if kind == "mapname":
        return cfg.mapname_width, cfg.mapname_width, 1
    if kind == "cename":
        return cfg.cename_width, cfg.cename_width, 1
    if kind in ("term", "type", "currency"):
        return cfg.term_width, cfg.term_width, 1
    if kind == "profile":
        return cfg.desc_width, cfg.desc_width, cfg.desc_max_rows
    return cfg.desc_width, cfg.desc_width, None


def _final_text(u, cfg, m, report):
    """The string to write, or None to leave the source alone."""
    raw_tl = u.get("tl") or ""
    if not raw_tl.strip():
        return None
    # A name-prefixed battle-log fragment carries a LEADING SPACE on purpose -
    # the engine writes `subject.name + message` with no separator - so this is
    # the one kind of unit whose leading whitespace must survive. Stripping it
    # here shipped `Erisattacks!`.
    tl = raw_tl.rstrip() if u.get("dummy_subject") else raw_tl.strip()
    tl = codes.clean_translation(tl)
    if codes.has_untranslated_jp(tl):
        report.problem(u["id"], "translation still holds Japanese - left as source")
        return None

    restored = codes.unmask_codes(tl, u.get("codes") or {}, pad_inserts=True)
    width, hard, rows = budget(u, cfg)

    if cfg.fix_wrap and u["kind"] in ("text", "desc", "profile"):
        text, problems = wrap.fit_or_veto(restored, width, rows, m,
                                          hard_width=hard)
        for p in problems:
            # A row overflow is not a defect on this engine - Window_Message
            # paginates - so it is counted, not reported as a problem.
            if p.startswith("rows "):
                report.written["paginated"] += 1
            else:
                report.problem(u["id"], p)
        return text

    w = m.cells(restored)
    if w > width:
        report.problem(u["id"], "%s is %d cells, budget %d"
                       % (u["kind"], w, width))
    return restored


def _write_text_run(lst, site, text, nametag, uid, report, cfg):
    """Redistribute the wrapped block across the run's EXISTING commands."""
    start, count = site["start"], site["count"]
    lines = text.split("\n") or [""]
    if nametag:
        lines[0] = nametag + lines[0]
    groups = wrap.redistribute(lines, count)

    for gi in range(count):
        cmd = lst.items[start + gi]
        if not isinstance(cmd, M.RObject) or cmd.get("@code") not in (401, 405):
            report.problem(uid, "command %d is not a 401/405 any more"
                           % (start + gi))
            return False
        params = cmd.get("@parameters")
        old = params.items[0] if params.items else None
        params.items[0:1] = [rvdata.new_string("\n".join(groups[gi]), old,
                                               cfg.encoding)]
    return True


def _apply_unit(data, u, cfg, m, report, glossary):
    text = _final_text(u, cfg, m, report)
    nametag = u.get("nametag", "")
    if nametag:
        en = store.name_en(glossary.get("names", {}).get(
            codes.nametag_name(nametag)))
        if en:
            nametag = codes.retag(nametag, en)
    if text is None:
        # An untranslated line still gets its ENGLISH name plate: the tag is a
        # separate glossary-owned string, and a Japanese plate over an
        # otherwise English build is a visible inconsistency.
        #
        # The body is rebuilt from `raw`, NOT from `src`. `src` has been
        # cleaned for the model - leading ideographic indents dropped, pacing
        # gaps folded to ASCII spaces, halfwidth kana normalised - and writing
        # that back would silently edit Japanese the player is still reading.
        # Only the tag changes here.
        if nametag and nametag != u.get("nametag"):
            _old_tag, body = codes.split_nametag(u["raw"])
            text = body
            report.written["nameplate-only"] += 1
        else:
            report.skipped += 1
            return

    for site in u["sites"]:
        ptr = site["ptr"]
        try:
            if u["kind"] == "text":
                lst = rvdata.ptr_get(data, ptr)
                if _write_text_run(lst, site, text, nametag, u["id"], report, cfg):
                    report.applied += 1
            elif u["kind"] == "choice":
                lst = rvdata.ptr_get(data, ptr)
                cmd = lst.items[site["start"]]
                arr = cmd.get("@parameters").items[0]
                old = arr.items[site["slot"]]
                arr.items[site["slot"]] = rvdata.new_string(text, old,
                                                            cfg.encoding)
                _mirror_402(lst, site["start"], site["slot"], text, cfg)
                report.applied += 1
            else:
                rvdata.ptr_set_string(data, ptr, text, cfg.encoding)
                report.applied += 1
        except (KeyError, IndexError, TypeError) as e:
            report.problem(u["id"], "site %r unreachable: %s" % (ptr, e))
    report.written[u["kind"]] += 1


def _mirror_402(lst, choice_idx, slot, label, cfg):
    """Copy the translated choice into its 402 branch label, BY INDEX.

    The engine branches on parameters[0] (the index), so parameters[1] is only
    read by the editor and by a human reviewing the branch. Translating it as
    its own unit would double the cost and let the two drift."""
    indent = lst.items[choice_idx].get("@indent") or 0
    for c in lst.items[choice_idx + 1:]:
        if not isinstance(c, M.RObject):
            continue
        ci = c.get("@indent") or 0
        if ci < indent:
            break
        code = c.get("@code")
        if code == 404 and ci == indent:
            break
        if code == 402 and ci == indent:
            ps = c.get("@parameters").items
            if ps and ps[0] == slot and len(ps) > 1:
                ps[1] = rvdata.new_string(label, ps[1], cfg.encoding)
                return


# --------------------------------------------------------------------------
def _inject_glossary_names(data, base, glossary, cfg, report):
    """Actor name and nickname come from the glossary, not from units."""
    if base != "Actors.rvdata2":
        return
    for e in data.items:
        if not isinstance(e, M.RObject):
            continue
        for f in ("@name", "@nickname"):
            v = e.get(f)
            if not isinstance(v, M.RString) or not v.data:
                continue
            en = store.name_en(glossary.get("names", {}).get(v.text()))
            if en:
                e.set(f, rvdata.new_string(en, v, cfg.encoding))
                report.written["actor-name"] += 1


# --------------------------------------------------------------------------
def run(cfg, store_dir, out_dir=None, in_place=False, verbose=True):
    """Write every translated unit into a fresh copy of the data folder."""
    m = measure.reset(cfg.font_path())
    glossary = store.load_glossary(store_dir)
    docs = store.load_docs(store_dir)
    by_file = {}
    for _p, doc in docs:
        by_file[doc["meta"]["source_file"]] = doc["units"]

    if in_place:
        dest = cfg.data_dir
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = os.path.join(cfg.game_root, "Data_backup_" + stamp)
        shutil.copytree(cfg.data_dir, backup)
        if verbose:
            print("backed up Data\\ -> %s" % backup)
    else:
        dest = out_dir or os.path.join(os.path.dirname(store_dir), "out", "Data")
        if os.path.isdir(dest):
            shutil.rmtree(dest)
        os.makedirs(dest, exist_ok=True)

    report = Report()
    for src in rvdata.data_files(cfg.data_dir):
        base = os.path.basename(src)
        units = by_file.get(base, [])
        if not units and base not in ("Actors.rvdata2",) and not in_place:
            # Nothing to change: copy the bytes rather than re-serialising
            # them, so the output is provably untouched for that file.
            shutil.copy2(src, os.path.join(dest, base))
            continue
        data = rvdata.load(src)
        for u in units:
            _apply_unit(data, u, cfg, m, report, glossary)
        _inject_glossary_names(data, base, glossary, cfg, report)
        rvdata.save(os.path.join(dest, base), data)

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
    tree, and compares FILE BYTES against the source. Byte comparison is
    possible here because the Marshal writer round-trips exactly, and it is a
    far stronger statement than comparing parsed trees: it also catches a
    changed link table, a re-ordered ivar or a rewritten float."""
    import tempfile
    import filecmp

    scratch = tempfile.mkdtemp(prefix="acetl_noop_")
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

    out = os.path.join(scratch, "Data")
    run(cfg, store_copy, out_dir=out, verbose=False)

    diffs = []
    for src in rvdata.data_files(cfg.data_dir):
        base = os.path.basename(src)
        q = os.path.join(out, base)
        if not os.path.exists(q):
            diffs.append(base + ": missing from the output")
        elif not filecmp.cmp(src, q, shallow=False):
            a = open(src, "rb").read()
            b = open(q, "rb").read()
            at = next((i for i in range(min(len(a), len(b))) if a[i] != b[i]),
                      min(len(a), len(b)))
            diffs.append("%s: %d -> %d bytes, first difference at %d"
                         % (base, len(a), len(b), at))
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
