#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
extract.py - game data -> translation store.

Two phases over different file sets with different code profiles, because one
extraction with every code enabled ships a translated jump label or a script
identifier, and that failure has no crash and no diff.

  Phase 0  the database files, Actors and System, with EVERY event code off.
           Proper nouns first, so the glossary is locked before any dialogue
           mentions them.
  Phase 1  Map*, CommonEvents and Troops: codes 401 and 102 only. Phase 0 plus
           phase 1 alone must make the game playable end to end.

There is no phase for 355 / 122 / 111: this game's 69 scripts are all
`SceneManager.call(Scene_ShortMove)`, not one of its 946 control-variable
commands takes a script operand, and not one of its 9,452 conditional branches
holds Japanese. Verified by census, not assumed - see `config.py`.

SPEAKER ATTRIBUTION IS STATED, NOT GUESSED
    11,484 of 12,880 message boxes open with `\NAME[...]`, the name-plate code
    this game's own script defines, so the speaker is in the data. The tag is
    split off, the model never sees it, and the 221 distinct names become
    glossary entries translated once each. A box with no tag gets NO speaker
    rather than inheriting the last one - which is how lines end up attributed
    to the wrong character after a conditional branch. The face graphic is
    recorded as a scene note only, because every face sheet in this game is the
    heroine in one of her dresses and it identifies her costume, not a speaker.
"""

import os
import collections

from . import codes, store, rvdata
from . import rvmarshal as M
from .config import DB_FIELDS, DO_NOT_TRANSLATE


def _mk_unit(uid, kind, ptr, src, raw, **kw):
    u = {
        "id": uid,
        "kind": kind,
        "sites": [dict(ptr=ptr, **{k: v for k, v in kw.items()
                                   if k in ("start", "count", "slot", "field")})],
        "src": src,
        "raw": raw,
        "tl": "",
    }
    for k in ("speaker", "ctx", "nametag", "codes", "note", "faced",
              "dummy_subject"):
        if kw.get(k):
            u[k] = kw[k]
    return u


def _prepare(text):
    """Name tag off, source cleaned, inline codes masked."""
    nametag, body = codes.split_nametag(text)
    masked, cmap = codes.mask_codes(codes.clean_source(body))
    return nametag, masked, cmap


# --------------------------------------------------------------------------
# Phase 1 - event command lists
# --------------------------------------------------------------------------
def extract_list(el, cfg, units, glossary, speakers):
    """Walk one command list. Never mutates it."""
    items = el.node.items
    n = len(items)
    face = ""
    i = 0
    while i < n:
        c = items[i]
        if not isinstance(c, M.RObject):
            i += 1
            continue
        code, params = rvdata.command(c)

        if code == 101:
            # [face_name, face_index, background, position]. The face name is
            # an asset key: never translated, but it narrows the text box by
            # `new_line_x` = 112 px, so it changes this unit's width budget.
            face = rvdata.stext(params[0]) if params else ""
            i += 1
            continue

        if cfg.code_text and code in (401, 405):
            run_code = code
            start = i
            parts = []
            j = i
            while j < n:
                cj = items[j]
                if not isinstance(cj, M.RObject) or cj.get("@code") != run_code:
                    break
                pj = (cj.get("@parameters").items
                      if isinstance(cj.get("@parameters"), M.RArray) else [])
                if not pj or not isinstance(pj[0], M.RString):
                    break
                parts.append(pj[0].text())
                j += 1
            if parts:
                joined = "\n".join(parts)
                nametag, src, cmap = _prepare(joined)
                body_jp = codes.has_jp(codes.PH_RE.sub("", src))
                if nametag and not body_jp:
                    # 79 runs in this game draw a body with no Japanese in it -
                    # `「………」`, a row of dots, a beat of silence - while the
                    # ONLY Japanese on screen is the speaker inside
                    # `\NAME[...]`. Extraction keys on "contains Japanese", so
                    # without this branch the unit never exists, inject never
                    # sees it, and those message boxes ship a Japanese name
                    # plate over an English scene. The unit is created with its
                    # body already "translated" to itself and locked, so it
                    # costs no API call and no pass can touch it; the tag is
                    # rebuilt from the glossary on inject like any other.
                    spk = codes.nametag_name(nametag)
                    if spk:
                        speakers[spk] += 1
                    u = _mk_unit("%s:c%d" % (el.uid, start), "text", el.ptr,
                                 src, joined, start=start, count=j - start,
                                 speaker=spk, ctx=el.ctx, nametag=nametag,
                                 codes=cmap, faced=bool(face))
                    u["tl"] = src
                    u["locked"] = True
                    u["waive"] = {"identical": "the body holds no Japanese "
                                  "(a silent beat); this unit exists only so "
                                  "the \\NAME[] plate is rebuilt in English"}
                    units.append(u)
                elif body_jp:
                    spk = codes.nametag_name(nametag)
                    if spk:
                        speakers[spk] += 1
                    # The face graphic is NOT part of `ctx`. It changes from
                    # box to box within one scene, and a ctx that changes
                    # re-emits the `# scene:` header on every single line of
                    # the request - hundreds of wasted tokens per request and a
                    # prompt that reads as if every line were a new scene. It
                    # is kept as its own field: the width budget needs it, the
                    # translator does not.
                    u = _mk_unit(
                        "%s:c%d" % (el.uid, start), "text", el.ptr, src, joined,
                        start=start, count=j - start, speaker=spk, ctx=el.ctx,
                        nametag=nametag, codes=cmap, faced=bool(face))
                    if face:
                        u["face"] = face
                    units.append(u)
            i = max(j, i + 1)
            continue

        if cfg.code_choices and code == 102 and params and isinstance(params[0], M.RArray):
            branch = _choice_branches(items, i)
            for k, label in enumerate(params[0].items):
                if not isinstance(label, M.RString):
                    continue
                text = label.text()
                if not codes.has_jp(text) or text in DO_NOT_TRANSLATE:
                    continue
                masked, cmap = codes.mask_codes(codes.clean_source(text))
                u = _mk_unit("%s:c%d:ch%d" % (el.uid, i, k), "choice", el.ptr,
                             masked, text, start=i, slot=k, ctx=el.ctx,
                             codes=cmap)
                if branch:
                    u["note"] = "branches: " + branch
                units.append(u)
            i += 1
            continue

        i += 1


def _choice_branches(items, idx):
    """`0=はい 1=いいえ` for the 402 labels that follow this 102.

    Without these in front of a reviewer a swapped Yes/No is invisible: the
    engine branches on parameters[0], the INDEX, so inverting two labels
    silently rewires which branch the player gets."""
    indent = items[idx].get("@indent") or 0
    out = []
    for c in items[idx + 1:]:
        if not isinstance(c, M.RObject):
            continue
        ci = c.get("@indent") or 0
        if ci < indent:
            break
        code = c.get("@code")
        if code == 404 and ci == indent:
            break
        if code == 402 and ci == indent:
            p = c.get("@parameters").items
            out.append("%s=%s" % (p[0], rvdata.stext(p[1]) if len(p) > 1 else ""))
    return " ".join(out)


def extract_event_file(path, cfg, glossary, speakers, names):
    data = rvdata.load(path)
    base = os.path.basename(path)
    stem = os.path.splitext(base)[0]
    units = []
    for el in rvdata.event_lists(data, base, names.get(_map_id(base), "")):
        extract_list(el, cfg, units, glossary, speakers)

    if cfg.common_event_names and base == "CommonEvents.rvdata2":
        # A common event's name looks like an editor label, and on most games
        # it is. Not here: this game's recollection gallery draws it in its
        # help window (`回想.rb:181`, `$data_common_events[id].name`), so 47 of
        # the 56 are player-visible text.
        for idx, ce in enumerate(data.items):
            if not isinstance(ce, M.RObject):
                continue
            v = ce.get("@name")
            if not isinstance(v, M.RString) or not codes.has_jp(v.text()):
                continue
            masked, cmap = codes.mask_codes(codes.clean_source(v.text()))
            units.append(_mk_unit("%s:ce%s:name" % (stem, ce.get("@id")),
                                  "cename", [idx, "@name"], masked, v.text(),
                                  ctx="scene title in the Recollection gallery",
                                  codes=cmap))

    if cfg.map_display_names and rvdata.is_map_file(base):
        dn = data.get("@display_name")
        if isinstance(dn, M.RString) and codes.has_jp(dn.text()):
            masked, cmap = codes.mask_codes(codes.clean_source(dn.text()))
            units.append(_mk_unit("%s:displayName" % stem, "mapname",
                                  ["@display_name"], masked, dn.text(),
                                  ctx="map name banner shown on entering %s"
                                      % stem, codes=cmap))
    return units


def _map_id(base):
    try:
        return int(base[3:6])
    except (ValueError, IndexError):
        return -1


# --------------------------------------------------------------------------
# Phase 0 - database
# --------------------------------------------------------------------------
_KIND_BY_FIELD = {
    "@name": "name", "@description": "desc",
    "@message1": "message", "@message2": "message",
    "@message3": "message", "@message4": "message",
}

# Battle-log fragments the engine draws as `subject.name + message`, with no
# separator of its own. Read straight off this game's `Window_BattleLog`:
#   :219  add_text(subject.name + item.message1)       Skill message1
#   :220  add_text(item.message2)                      Skill message2 - ALONE
#   :390  replace_text(target.name + state_msg)        State message1 / message2
#   :403  add_text(target.name + state.message4)       State message4
#   Game_BattlerBase / display_current_state           State message3
# The English in these needs a LEADING SPACE, which Japanese does not.
PREFIXED_MESSAGES = {
    ("Skills.rvdata2", "@message1"),
    ("States.rvdata2", "@message1"), ("States.rvdata2", "@message2"),
    ("States.rvdata2", "@message3"), ("States.rvdata2", "@message4"),
}


def extract_database(path, cfg, glossary):
    base = os.path.basename(path)
    fields = DB_FIELDS.get(base)
    if not fields:
        return []
    data = rvdata.load(path)
    stem = os.path.splitext(base)[0]
    units = []
    for idx, e in enumerate(data.items):
        if not isinstance(e, M.RObject):
            continue
        ename = rvdata.stext(e.get("@name"))
        for f in fields:
            v = e.get(f)
            if not isinstance(v, M.RString):
                continue
            text = v.text()
            if not codes.has_jp(text) or text in DO_NOT_TRANSLATE:
                continue
            masked, cmap = codes.mask_codes(codes.clean_source(text))
            kind = _KIND_BY_FIELD.get(f, "name")
            u = _mk_unit("%s:%d:%s" % (stem, idx, f.lstrip("@")), kind,
                         [idx, f], masked, text,
                         ctx="%s #%s %s" % (stem, e.get("@id"), ename),
                         codes=cmap)
            # Which battle-log fragments are name-PREFIXED is a property of the
            # engine, not of the string, so it is read off `Window_BattleLog`
            # rather than guessed from a leading particle. Skill message2 is
            # the one that stands alone (`add_text(item.message2)`), and giving
            # it a dummy subject would produce a sentence with two subjects.
            if (base, f) in PREFIXED_MESSAGES:
                u["dummy_subject"] = True
            units.append(u)
    return units


def extract_actors(path, cfg, glossary):
    """Actor names go into the GLOSSARY, never into units.

    One English spelling then serves the menu, the name plate and any `\\N[id]`
    reference at once."""
    data = rvdata.load(path)
    units = []
    seeded = 0
    for idx, e in enumerate(data.items):
        if not isinstance(e, M.RObject):
            continue
        for f in ("@name", "@nickname"):
            v = rvdata.stext(e.get(f))
            if v and codes.has_jp(v):
                if store.seed_name(glossary, v,
                                   "Actors.rvdata2 #%s %s" % (e.get("@id"),
                                                              f.lstrip("@"))):
                    seeded += 1
        prof = e.get("@description")
        if isinstance(prof, M.RString) and codes.has_jp(prof.text()):
            masked, cmap = codes.mask_codes(codes.clean_source(prof.text()))
            units.append(_mk_unit("Actors:%d:description" % idx, "profile",
                                  [idx, "@description"], masked, prof.text(),
                                  ctx="actor profile, shown on the status screen",
                                  codes=cmap))
    return units, seeded


def extract_system(path, cfg, glossary):
    data = rvdata.load(path)
    units = []

    def add(uid, kind, ptr, node, ctx):
        text = rvdata.stext(node)
        if not text or not codes.has_jp(text) or text in DO_NOT_TRANSLATE:
            return
        masked, cmap = codes.mask_codes(codes.clean_source(text))
        units.append(_mk_unit(uid, kind, ptr, masked, text, ctx=ctx, codes=cmap))

    add("System:gameTitle", "title", ["@game_title"], data.get("@game_title"),
        "game title - the window caption and the title screen")
    add("System:currencyUnit", "currency", ["@currency_unit"],
        data.get("@currency_unit"),
        "currency unit, drawn immediately after a number")

    for iv, kind in (("@elements", "type"), ("@skill_types", "type"),
                     ("@weapon_types", "type"), ("@armor_types", "type")):
        arr = data.get(iv)
        if not isinstance(arr, M.RArray):
            continue
        for i, v in enumerate(arr.items):
            # Slot 0 is the empty "none" entry; preserving the INDEX is what
            # stops every type shifting by one.
            add("System:%s:%d" % (iv.lstrip("@"), i), kind, [iv, i], v,
                "System %s[%d] - a category label" % (iv.lstrip("@"), i))

    terms = data.get("@terms")
    if isinstance(terms, M.RObject):
        for iv in ("@basic", "@params", "@etypes", "@commands"):
            arr = terms.get(iv)
            if not isinstance(arr, M.RArray):
                continue
            for i, v in enumerate(arr.items):
                add("System:terms:%s:%d" % (iv.lstrip("@"), i), "term",
                    ["@terms", iv, i], v,
                    "System terms.%s[%d] - a UI label, keep it terse"
                    % (iv.lstrip("@"), i))

    if cfg.system_switches:
        arr = data.get("@switches")
        for i, v in enumerate(arr.items if isinstance(arr, M.RArray) else []):
            add("System:switches:%d" % i, "term", ["@switches", i], v,
                "switch name")
    if cfg.system_variables:
        arr = data.get("@variables")
        for i, v in enumerate(arr.items if isinstance(arr, M.RArray) else []):
            add("System:variables:%d" % i, "term", ["@variables", i], v,
                "variable name")
    return units


# --------------------------------------------------------------------------
def run(cfg, store_dir, verbose=True):
    """Full extraction. Re-runnable: existing translations are carried over."""
    glossary = store.load_glossary(store_dir)
    os.makedirs(store.units_dir(store_dir), exist_ok=True)
    totals = collections.Counter()
    speakers = collections.Counter()
    names = rvdata.map_names(cfg.data_dir)

    # --- Phase 0 -----------------------------------------------------------
    actors = os.path.join(cfg.data_dir, "Actors.rvdata2")
    if cfg.actor_names and os.path.exists(actors):
        units, seeded = extract_actors(actors, cfg, glossary)
        _write(store_dir, "Actors.rvdata2", units, totals, verbose)
        if verbose and seeded:
            print("  Actors.rvdata2       %d name(s) seeded into the glossary"
                  % seeded)

    if cfg.db_names:
        for base in sorted(DB_FIELDS):
            p = os.path.join(cfg.data_dir, base)
            if os.path.exists(p):
                _write(store_dir, base, extract_database(p, cfg, glossary),
                       totals, verbose)

    sysp = os.path.join(cfg.data_dir, "System.rvdata2")
    if cfg.system and os.path.exists(sysp):
        _write(store_dir, "System.rvdata2", extract_system(sysp, cfg, glossary),
               totals, verbose)

    # --- Phase 1 -----------------------------------------------------------
    event_files = [p for p in rvdata.data_files(cfg.data_dir)
                   if rvdata.is_map_file(os.path.basename(p))]
    for extra in ("CommonEvents.rvdata2", "Troops.rvdata2"):
        p = os.path.join(cfg.data_dir, extra)
        if os.path.exists(p):
            event_files.append(p)
    for p in event_files:
        units = extract_event_file(p, cfg, glossary, speakers, names)
        _write(store_dir, os.path.basename(p), units, totals, verbose)

    # Speaker names are proper nouns with a register, exactly like actor names,
    # and go into the same glossary so one English spelling serves the name
    # plate and every mention in prose.
    seeded = 0
    for jp, n in speakers.most_common():
        if store.seed_name(glossary, jp, "\\NAME[] speaker", count=n):
            seeded += 1
        else:
            cur = glossary["names"].get(jp)
            if isinstance(cur, dict):
                cur["count"] = n
    store.save_glossary(store_dir, glossary)

    if verbose:
        print("\n  %d distinct \\NAME[] speakers (%d seeded now, %d uses)"
              % (len(speakers), seeded, sum(speakers.values())))
        print("\nTOTAL %d units" % sum(totals.values()))
        for k, v in totals.most_common():
            print("  %-10s %d" % (k, v))
    return totals


def _write(store_dir, base, units, totals, verbose):
    path = store.doc_path(store_dir, base)
    kept = 0
    if os.path.exists(path):
        old = store.read_json(path)
        kept = store.merge_translations(old.get("units", []), units)
    if not units and not os.path.exists(path):
        return
    store.save_doc(store_dir, base, units)
    for u in units:
        totals[u["kind"]] += 1
    if verbose and units:
        note = "  (%d carried over)" % kept if kept else ""
        print("  %-22s %5d units%s" % (base, len(units), note))
