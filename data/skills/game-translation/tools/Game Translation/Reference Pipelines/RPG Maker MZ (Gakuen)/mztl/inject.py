#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
inject.py - store -> game data.

Injection always rebuilds from the PRISTINE source file, so it is idempotent:
re-running never double-wraps, double-substitutes or feeds English back into
itself. Nothing here reads the previous output.

Three invariants this module exists to hold:

* **The command count never changes.** A save file stores an INDEX into the
  event command list (`Game_Interpreter._index`), so tombstoning the absorbed
  401s of a run - the usual RPG Maker write-back - moves every later index and
  resumes existing saves at the wrong line. The wrapped English is
  redistributed across exactly the commands the run already had, packing extra
  lines into a command with an embedded `\n` where it needs to. MZ renders
  `Game_Message.allText()` as the commands joined by `\n`, so k wrapped lines
  across c commands render `max(k, c)` rows, and both are capped at the
  window's 4.

* **The speaker line is rebuilt from the glossary, never translated per unit.**
  This game draws the speaker as the first physical row of the message, so it
  costs a row and it must read identically everywhere that character speaks.
  A speaker with no English yet is written back BYTE-EXACT rather than guessed.

* **A store with no translations must inject as a no-op.** `selftest --noop`
  wipes every `tl`, injects to a scratch tree and deep-compares parsed JSON
  against the source. The only values allowed to differ are the ones injected
  from the GLOSSARY rather than from a unit - speaker lines and actor names.
  Anything else means the injector is editing source text on its own
  initiative, which is exactly how a whole-file quote normaliser once shipped
  Japanese wearing English punctuation with every unit-level check green.
"""

import os
import re
import glob
import json
import shutil
import datetime
import collections

from . import codes, store, fileio, wrap, measure, plugins_js
from .config import PICTURE_LAYOUT, CBR_LAYOUT


class Report(object):
    def __init__(self):
        self.written = collections.Counter()
        self.problems = []
        self.skipped = 0
        self.applied = 0
        self.jp_speakers = []

    def problem(self, uid, msg):
        self.problems.append("%s: %s" % (uid, msg))


# --------------------------------------------------------------------------
def _speaker_line(u, glossary, report):
    r"""The rebuilt first row, byte-exact when there is no English for it.

    An untranslated speaker ships a Japanese name plate over English dialogue -
    visible on screen, invisible to every per-unit check, because the plate is
    not part of any unit's text. Reported separately."""
    raw = u.get("speaker_raw")
    if not raw:
        return None
    jp = u.get("speaker") or ""
    # A per-site override, for the case the glossary cannot express: the AUTHOR
    # put the wrong name plate on a line. Map040 ev6 is labelled 女子 ("girl")
    # for both halves of a couple, but the second speaks いいだろ？な？ - masculine -
    # and its event graphic is the boyfriend. Translating 女子 faithfully
    # reproduces the slip, and fixing it in the glossary would rename every
    # mob girl in the game. So it is recorded on the one unit that is wrong.
    en = u.get("speaker_en") or store.name_en(glossary.get("names", {}).get(jp))
    if not en:
        report.jp_speakers.append("%s: %s" % (u["id"], jp))
        return raw
    # Replace the display name inside the raw line exactly once, so any
    # leading/trailing control code the author put on that row survives.
    if jp and jp in raw:
        return raw.replace(jp, en, 1)
    return en


def _final_text(u, cfg, m, report, glossary):
    """The string that goes into the file, or None to leave the source alone."""
    tl = (u.get("tl") or "").strip()
    if not tl:
        return None
    tl = codes.clean_translation(tl)
    if codes.has_untranslated_jp(tl):
        report.problem(u["id"], "translation still holds Japanese - left as source")
        return None

    kind = u["kind"]
    restored = codes.unmask_codes(tl, u.get("codes") or {}, pad_inserts=True)
    restored = codes.space_bare_escapes(restored)

    if kind == "text":
        width = cfg.face_width if u.get("faced") else cfg.width
        rows = cfg.max_rows
        spk = _speaker_line(u, glossary, report)
        if spk is not None:
            rows -= 1          # the nameplate is a rendered row
        body, problems = wrap.fit_or_veto(
            restored, width, rows, m,
            hard_width=cfg.hard_cap("text", faced=bool(u.get("faced"))))
        if problems:
            report.problem(u["id"], "; ".join(problems))
        return (spk + "\n" + body) if spk is not None else body

    if kind == "desc":
        text, problems = wrap.fit_or_veto(restored, cfg.list_width,
                                          cfg.list_max_rows, m,
                                          hard_width=cfg.hard_cap("desc"))
        if problems:
            report.problem(u["id"], "; ".join(problems))
        return text

    if kind == "help":
        text, problems = wrap.fit_or_veto(restored, cfg.list_width, 1, m,
                                          hard_width=cfg.hard_cap("help"))
        if problems:
            report.problem(u["id"], "; ".join(problems))
        return text

    budget = cfg.hard_cap(kind)
    w = m.cells(restored)
    if w > budget:
        report.problem(u["id"], "%s is %d cells, budget %d" % (kind, w, budget))
    return restored


def _write_text_run(lst, site, text, uid, report):
    """Redistribute the wrapped block across the run's EXISTING commands."""
    start, count = site["start"], site["count"]
    lines = text.split("\n") or [""]

    if len(lines) <= count:
        # One line per command, blanks at the END so the text reads top-down.
        # MZ joins the commands with \n, so this renders `count` rows with the
        # content in the first len(lines) - and the window is a fixed 4 rows
        # tall either way, so the trailing blanks are invisible.
        groups = [[l] for l in lines] + [[] for _ in range(count - len(lines))]
    else:
        # More wrapped lines than commands: spread the surplus evenly rather
        # than hoarding it in command 0. Rendered rows stay len(lines).
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
            report.problem(uid, "command %d is not a 401/405 any more"
                           % (start + gi))
            return False
        cmd["parameters"] = ["\n".join(groups[gi])]
    return True


_JSON_UNSAFE = re.compile(r'["\r\n]')


def _apply_unit(data, u, cfg, m, report, glossary):
    text = _final_text(u, cfg, m, report, glossary)
    if text is None:
        report.skipped += 1
        return
    kind = u["kind"]
    for site in u["sites"]:
        ptr = site["ptr"]
        try:
            if kind == "text" and "start" in site:
                lst = store.ptr_get(data, ptr)
                if _write_text_run(lst, site, text, u["id"], report):
                    report.applied += 1

            elif kind == "choice":
                lst = store.ptr_get(data, ptr)
                cmd = lst[site["start"]]
                label = u.get("cond_prefix", "") + text + u.get("cond_suffix", "")
                cmd["parameters"][0][site["slot"]] = label
                _mirror_402(lst, site["start"], site["slot"], label)
                report.applied += 1

            elif kind == "help":
                lst = store.ptr_get(data, ptr)
                lst[site["start"]]["parameters"][0] = text
                report.applied += 1

            elif kind == "label":
                # A note field holds PLUGIN CONFIG, of which one tag value is
                # drawn. Writing the whole field replaces `<LB:アズサの部屋>`
                # with `Azusa's Room`, which does not merely lose the other
                # tags - it destroys the tag itself, so `event().meta['LB']`
                # is undefined and EventLabel draws NOTHING. Splice the value's
                # exact span and leave every other byte of the note alone.
                note = store.ptr_get(data, ptr)
                s, c = site["start"], site["count"]
                if not isinstance(note, str) or note[s:s + c] != u["raw"]:
                    report.problem(u["id"],
                                   "note span moved (%r != %r) - not written"
                                   % (note[s:s + c] if isinstance(note, str)
                                      else note, u["raw"]))
                    continue
                if ">" in text:
                    report.problem(u["id"],
                                   "translation contains '>' which closes the "
                                   "note tag early - not written")
                    continue
                store.ptr_set(data, ptr, note[:s] + text + note[s + c:])
                report.applied += 1

            elif kind == "ptext" and "start" in site:
                lst = store.ptr_get(data, ptr)
                cmd = lst[site["start"]]
                code = cmd.get("code")
                if code in (355, 655):
                    # `CBR-エロステータス` row: `A.split(/\-(.*)/, 2)` keeps the
                    # keyword and hands everything after the FIRST hyphen to the
                    # renderer, so a hyphen inside the English is safe.
                    cmd["parameters"][0] = site.get("prefix", "") + text
                elif code == 122:
                    # The value lives inside a JSON string the engine eval()s.
                    # Re-emit in the source's own quote style, with the quote
                    # character stripped out of the translation.
                    q = u.get("quote") or '"'
                    body = text.replace(q, "").replace('"', "'").replace("\n", " ")
                    cmd["parameters"][4] = q + body + q
                elif code == 357:
                    args = cmd["parameters"][3]
                    key = site.get("field")
                    if isinstance(args, dict) and key in args:
                        args[key] = _JSON_UNSAFE.sub("", text)
                else:
                    report.problem(u["id"], "unexpected host code %s" % code)
                    continue
                report.applied += 1

            else:
                store.ptr_set(data, ptr, text)
                report.applied += 1
        except (KeyError, IndexError, TypeError) as e:
            report.problem(u["id"], "site %r unreachable: %s" % (ptr, e))
    report.written[kind] += 1


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
def _inject_mz_speakers(data, glossary, report):
    r"""Rewrite code-101 `parameters[4]`, the MZ native speaker plate.

    This game barely uses the field - 41 headers of 8,368 - which is why the
    extractor reads the speaker off the first 401 line instead. But "barely"
    is not "never", and `Window_NameBox` draws whatever is in `parameters[4]`
    whenever it is non-empty. Left alone, those 41 messages ship a JAPANESE
    name plate sitting on top of English dialogue: on screen, and invisible to
    every per-unit check, because the plate is not part of any unit's text.
    The output scan is what found them.

    Glossary-driven like the actor names, and guarded the same way - a value
    with no English stays byte-exact, so an empty glossary changes nothing and
    the no-op test still holds."""
    def walk(lst):
        for cmd in lst:
            if not isinstance(cmd, dict) or cmd.get("code") != 101:
                continue
            p = cmd.get("parameters") or []
            if len(p) <= 4 or not isinstance(p[4], str) or not p[4]:
                continue
            if not codes.has_jp(p[4]):
                continue
            en = store.name_en(glossary.get("names", {}).get(p[4]))
            if en:
                p[4] = en
                report.written["mz-speaker"] += 1
            else:
                report.jp_speakers.append("code-101 parameters[4]: %s" % p[4])

    if isinstance(data, list):
        for e in data:
            if not isinstance(e, dict):
                continue
            if isinstance(e.get("list"), list):
                walk(e["list"])
            for page in (e.get("pages") or []):
                if isinstance(page, dict) and isinstance(page.get("list"), list):
                    walk(page["list"])
    elif isinstance(data, dict):
        for e in (data.get("events") or []):
            if not isinstance(e, dict):
                continue
            for page in (e.get("pages") or []):
                if isinstance(page, dict) and isinstance(page.get("list"), list):
                    walk(page["list"])


def _apply_picture_layout(data, base, report):
    r"""Move a DTextPicture value column so an English label has room.

    The only place this patch changes a NON-STRING leaf, and every change is
    declared in `config.PICTURE_LAYOUT` with its measurement.
    `verify_structure` reads the same table and fails on anything undeclared,
    so a coordinate cannot be nudged quietly.

    Guarded on the CURRENT value: the override records what it expects to find
    and refuses to write if the file does not say that, so a re-run over
    already-patched data is a no-op and a game update that moves the picture
    is a loud failure rather than a silent double-move."""
    for (f, ptr_str, idx), params in PICTURE_LAYOUT.items():
        if f != base:
            continue
        ptr = [int(p) if p.isdigit() else p for p in ptr_str.split("/")]
        try:
            lst = store.ptr_get(data, ptr)
            cmd = lst[idx]
        except (KeyError, IndexError, TypeError):
            report.problem("layout:%s#%s[%d]" % (f, ptr_str, idx),
                           "command not reachable")
            continue
        if not isinstance(cmd, dict) or cmd.get("code") != 231:
            report.problem("layout:%s#%s[%d]" % (f, ptr_str, idx),
                           "expected a 231 Show Picture, found code %s"
                           % (cmd.get("code") if isinstance(cmd, dict) else "?"))
            continue
        for slot, (expect, new, why) in params.items():
            cur = (cmd.get("parameters") or [None] * (slot + 1))[slot]
            if cur == new:
                continue                      # already applied
            if cur != expect:
                report.problem(
                    "layout:%s#%s[%d]" % (f, ptr_str, idx),
                    "parameters[%d] is %r, expected %r - NOT moved"
                    % (slot, cur, expect))
                continue
            cmd["parameters"][slot] = new
            report.written["picture-layout"] += 1


TILE = 48                     # Game_Map.tileWidth()
_LB_X_RE = re.compile(r"<LB_X:(-?\d+)>")


def _apply_label_offsets(data, base, cfg, m, report):
    r"""Lay out the `<LB:>` captions on each map row so none is clipped by the
    map edge and none lands on its neighbour.

    `EventLabel` sets `Sprite.anchor.x = 0.5`, so a caption is CENTRED on its
    event and spreads both ways. English is wider than the Japanese the author
    laid out for, which breaks two ways at once:

      * past a map edge - and unlike ordinary camera clipping this one is
        PERMANENT, because `Game_Map.displayX` clamps at the map boundary, so
        no amount of walking brings the overflow into view
      * onto the caption beside it - the recollection room is a grid of scene
        titles 7 tiles apart and the English titles are long

    Both are fixed with the plugin's own per-event x offset `<LB_X:n>`
    (`findLabelX = screenX() + this._labelX`), which moves the caption without
    touching a single word of the translation. Only labels on the SAME ROW can
    collide, since different rows are separated vertically, so each row is laid
    out independently as a small 1-D packing problem: keep every caption inside
    the map, keep `GAP` px between neighbours, and otherwise stay as close to
    the event as those two constraints allow.

    A caption still in the source language is treated as a FIXED obstacle -
    the author's own layout applies to it and this pass has no business moving
    it. That is also what keeps the no-op test honest, since an empty store
    leaves every label untranslated and therefore every label immovable.

    Offsets are COMPUTED from the translated width, so they stay correct if the
    text or the font size changes; `plugins_js.LAYOUT_OVERRIDES` is the single
    place the size comes from."""
    if not isinstance(data, dict) or "events" not in data:
        return
    try:
        size = int(plugins_js.LAYOUT_OVERRIDES["EventLabel"]["fontSize"][0])
    except (KeyError, ValueError, TypeError):
        return
    map_w = (data.get("width") or 0) * TILE
    if not map_w:
        return

    half_px = size / 2.0        # every Latin glyph in this font is 0.5 em
    GAP = 8                     # px of daylight between neighbouring captions
    MARGIN = 4                  # px of daylight against the map edge

    rows = {}
    for ev in (data.get("events") or []):
        if not ev or not isinstance(ev, dict):
            continue
        note = ev.get("note") or ""
        mm = re.search(r"<LB:([^>]*)>", note)
        if not mm or not mm.group(1).strip():
            continue
        text = mm.group(1)
        rows.setdefault(ev.get("y", 0), []).append({
            "ev": ev,
            "note": note,
            "home": ev.get("x", 0) * TILE + TILE // 2,
            "half": m.cells(text) * half_px / 2.0,
            "movable": not codes.has_jp(text),
        })

    placed = {}
    for _y, items in rows.items():
        items.sort(key=lambda it: it["home"])
        pos = [it["home"] for it in items]

        # Relaxation rather than a closed form: the constraints (separate from
        # both neighbours, stay inside both edges) can pull against each other,
        # and on rows this small - a handful of captions - iterating to a fixed
        # point is both shorter and more obviously correct than case analysis.
        for _ in range(64):
            moved = False
            for i in range(len(items) - 1):
                a, b = items[i], items[i + 1]
                overlap = (pos[i] + a["half"] + GAP) - (pos[i + 1] - b["half"])
                if overlap <= 0:
                    continue
                if a["movable"] and b["movable"]:
                    pos[i] -= overlap / 2.0
                    pos[i + 1] += overlap / 2.0
                elif b["movable"]:
                    pos[i + 1] += overlap
                elif a["movable"]:
                    pos[i] -= overlap
                else:
                    continue        # both are the author's - leave them alone
                moved = True
            for i, it in enumerate(items):
                if not it["movable"]:
                    continue
                lo, hi = MARGIN + it["half"], map_w - MARGIN - it["half"]
                if lo > hi:         # caption is wider than the whole map
                    new = map_w / 2.0
                else:
                    new = min(max(pos[i], lo), hi)
                if new != pos[i]:
                    pos[i] = new
                    moved = True
            if not moved:
                break

        for it, x in zip(items, pos):
            if it["movable"]:
                placed[id(it["ev"])] = (it, int(round(x - it["home"])))

    for ev in (data.get("events") or []):
        if not ev or not isinstance(ev, dict):
            continue
        entry = placed.get(id(ev))
        if entry is None:
            continue
        it, off = entry
        note = it["note"]
        if not off:
            # Never leave a stale offset behind if the text got shorter.
            if _LB_X_RE.search(note):
                ev["note"] = _LB_X_RE.sub("", note)
                report.written["label-offset-cleared"] += 1
            continue
        tag = "<LB_X:%d>" % off
        if _LB_X_RE.search(note):
            ev["note"] = _LB_X_RE.sub(tag, note)
        else:
            sep = "" if note.endswith("\n") or not note.strip() else "\n"
            ev["note"] = note + sep + tag
        report.written["label-offset"] += 1


def _apply_cbr_layout(data, base, report):
    r"""Move a CBR_EroStatus caption's `x-NNN` row.

    These are plain string leaves inside a 655 script command, so they need no
    structural exception - but they are still declared in `config.CBR_LAYOUT`
    with their measurement and guarded on the value they expect to find, so a
    re-run is a no-op rather than a second move."""
    for (f, ce_id), rows in CBR_LAYOUT.items():
        if f != base or not isinstance(data, list):
            continue
        ce = next((e for e in data
                   if e and isinstance(e, dict) and e.get("id") == ce_id), None)
        if ce is None:
            report.problem("cbr-layout:%s#CE%d" % (f, ce_id), "event not found")
            continue
        lst = ce.get("list") or []
        for idx, (expect, new, why) in rows.items():
            if idx >= len(lst) or not isinstance(lst[idx], dict):
                report.problem("cbr-layout:%s#CE%d[%d]" % (f, ce_id, idx),
                               "command not reachable")
                continue
            cmd = lst[idx]
            cur = ((cmd.get("parameters") or [""]) + [""])[0]
            if cur == new:
                continue                       # already applied
            if cur != expect:
                report.problem(
                    "cbr-layout:%s#CE%d[%d]" % (f, ce_id, idx),
                    "row is %r, expected %r (%s) - NOT moved" % (cur, expect, why))
                continue
            cmd["parameters"][0] = new
            report.written["cbr-layout"] += 1


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
        backup = os.path.join(cfg.game_root, "data_backup_" + stamp)
        if not os.path.isdir(backup):
            shutil.copytree(cfg.data_dir, backup)
        if verbose:
            print("backed up data/ -> %s" % backup)
    else:
        dest = out_dir or os.path.join(os.path.dirname(store_dir), "out", "data")
        if os.path.isdir(dest):
            shutil.rmtree(dest)
        os.makedirs(dest, exist_ok=True)

    report = Report()
    for src in sorted(glob.glob(os.path.join(cfg.data_dir, "*.json"))):
        base = os.path.basename(src)
        data, rend = fileio.load(src)
        # `label` units are a SPAN SPLICE into a shared note field, so two of
        # them on one note shift each other's offsets. Applying the highest
        # offset first keeps every earlier span valid. Every other kind writes
        # a whole value and does not care about order, so they keep theirs.
        units = by_file.get(base, [])
        units = sorted(units, key=lambda u: (
            u["kind"] == "label",
            -(u["sites"][0].get("start") or 0) if u["kind"] == "label" else 0))
        for u in units:
            _apply_unit(data, u, cfg, m, report, glossary)
        _inject_glossary_names(data, base, glossary, report)
        _inject_mz_speakers(data, glossary, report)
        _apply_picture_layout(data, base, report)
        _apply_cbr_layout(data, base, report)
        _apply_label_offsets(data, base, cfg, m, report)
        fileio.save(os.path.join(dest, base), data, rend)

    if verbose:
        print("\nINJECT -> %s" % dest)
        print("  units written : %d" % sum(report.written.values()))
        for k, v in report.written.most_common():
            print("      %-12s %d" % (k, v))
        print("  sites applied : %d" % report.applied)
        print("  left as source: %d" % report.skipped)
        if report.jp_speakers:
            print("  !! %d message(s) kept a JAPANESE nameplate over English "
                  "dialogue" % len(report.jp_speakers))
            for s in report.jp_speakers[:10]:
                print("      ! " + s)
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

    Wipes every translation in a COPY of the store, injects into a scratch tree
    and deep-compares parsed JSON against the source. With an empty glossary
    too, NOTHING may differ - not even a speaker line."""
    import tempfile

    scratch = tempfile.mkdtemp(prefix="mztl_noop_")
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

    # Declared layout repairs are not store-driven, so they fire even with an
    # empty store. They are deliberate and separately proven, so they are
    # accepted BY EXACT PATH and reported - never tolerated as a class.
    allowed = set()
    for (f, ptr_str, idx), params in PICTURE_LAYOUT.items():
        for slot in params:
            allowed.add("%s: /%s/%d/parameters/%d" % (f, ptr_str, idx, slot))
    # CBR_LAYOUT moves an `x-NNN` row inside a 655 script command. Its path is
    # the common event's index in the file, not its id, so it is resolved the
    # same way `_apply_cbr_layout` does.
    for (f, ce_id), rows in CBR_LAYOUT.items():
        for idx in rows:
            allowed.add("%s: /%d/list/%d/parameters/0" % (f, ce_id, idx))

    diffs, declared = [], []
    for src in sorted(glob.glob(os.path.join(cfg.data_dir, "*.json"))):
        base = os.path.basename(src)
        a, _ = fileio.load(src)
        b, _ = fileio.load(os.path.join(out, base))
        if a == b:
            continue
        d = base + ": " + _first_diff(a, b)
        if any(d.startswith(p + " ") for p in allowed):
            declared.append(d)
            continue
        diffs.append(d)
    shutil.rmtree(scratch, ignore_errors=True)
    if verbose:
        if diffs:
            print("NO-OP INJECT: FAIL - %d file(s) changed with an empty store"
                  % len(diffs))
            for d in diffs[:20]:
                print("   " + d)
        else:
            print("NO-OP INJECT: PASS - an empty store injects byte-identically"
                  "%s" % (" apart from %d DECLARED layout repair(s)"
                          % len(declared) if declared else ""))
            for d in declared:
                print("   = " + d)
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
