#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract.py - game data -> translation store.

Four phases, run over different file sets with different code profiles, because
one extraction with every code enabled ships a translated plugin keyword or
script identifier and the failure has no crash and no diff:

  Phase 0  the database files + System.json, ALL event codes forced off.
           Does the proper nouns first so the glossary is locked before any
           dialogue mentions them.
  Phase 1  CommonEvents + Map*: codes 101/401/102 only. Phase 0 + Phase 1
           alone must make the game playable end to end.
  Phase 1b nothing. This game's 111s hold no string comparisons at all
           (condition types are 0/1/3/8/12 - no `$gameVariables` equality),
           so the 122/111 reconciliation that makes most RPG Maker patches
           unwinnable does not apply. Verified, not assumed.
  Phase 2  code 356, whitelisted to `LL_InfoPopupWIndowMV showWindow` (the
           only one of 912 plugin commands that carries text).

Speaker attribution is STATELESS and refuses to guess. There is no code-101
`parameters[4]` in MV and every face graphic in this game is empty, so the only
signal is the LL_StandingPictureMV portrait run - and every portrait is the
protagonist. A block that opens with one is hers; anything else gets an empty
speaker and leans on the scene context instead of inheriting from an earlier
101, which is the classic way lines get attributed to the wrong character after
a conditional branch.
"""

import os
import re
import glob
import json
import collections

from . import codes, store, fileio
from .config import DB_FILES, DO_NOT_TRANSLATE

RUN_CODES = (401, 405, -1)

# Codes that open a text run. 405 is absent from this game but costs nothing.
TEXT_HEADER = 101


# --------------------------------------------------------------------------
def _ctx_label(map_name, display_name, ev_id, ev_name, page):
    bits = [map_name]
    if display_name:
        bits.append(display_name)
    if ev_id is not None:
        bits.append("event %d%s" % (ev_id, (" %r" % ev_name) if ev_name else ""))
    if page is not None:
        bits.append("page %d" % page)
    return " / ".join(bits)


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
    for k in ("speaker", "ctx", "nametag", "codes", "note"):
        if kw.get(k):
            u[k] = kw[k]
    return u


def _prepare(text, cfg):
    """Portrait run off, source cleaned, inline codes masked.

    Returns (nametag, src, code_map, raw)."""
    nametag, body = codes.split_portrait(text)
    cleaned = codes.clean_source(body)
    masked, cmap = codes.mask_codes(cleaned)
    return nametag, masked, cmap, text


# --------------------------------------------------------------------------
# Phase 1 - event command lists
# --------------------------------------------------------------------------
def _extract_list(lst, ptr, uid_prefix, ctx, cfg, units, portrait_speaker,
                  solo=False):
    """Walk one event command list. Never mutates it.

    `solo` marks a scene proved over the corpus to have exactly one speaker,
    so a line without a portrait code is still hers. See Config."""
    i = 0
    n = len(lst)
    while i < n:
        c = lst[i]
        if not isinstance(c, dict):
            i += 1
            continue
        code = c.get("code")
        params = c.get("parameters") or []

        # ---- 401 / 405 run ------------------------------------------------
        if cfg.code_text and code in (401, 405):
            run_code = code
            start = i
            parts = []
            j = i
            while j < n:
                cj = lst[j]
                if not isinstance(cj, dict) or cj.get("code") != run_code:
                    break
                pj = cj.get("parameters") or []
                if not pj:
                    break
                line = pj[0]
                # Cut the run at a block-level escape: a line opening \f[..] or
                # \p[..] is a NEW message box, and merging across it fuses two
                # boxes the engine draws separately. c/n/i/k/v are deliberately
                # absent from this class - they are inline content.
                # This game's only leading run is \F[..] (LL_StandingPictureMV),
                # which is a portrait, so it is admitted on the FIRST line only.
                if j > start and _BLOCK_BREAK.match(line):
                    break
                parts.append(line)
                j += 1
            if parts:
                joined = "\n".join(parts)
                nametag, src, cmap, raw = _prepare(joined, cfg)
                if codes.has_jp(codes.PH_RE.sub("", src)):
                    speaker = portrait_speaker if (nametag or solo) else ""
                    uid = "%s:c%d" % (uid_prefix, start)
                    units.append(_mk_unit(
                        uid, "text", ptr, src, raw,
                        start=start, count=j - start,
                        speaker=speaker, ctx=ctx, nametag=nametag,
                        codes=cmap,
                    ))
            i = max(j, i + 1)
            continue

        # ---- 102 choices --------------------------------------------------
        if cfg.code_choices and code == 102 and params and isinstance(params[0], list):
            branch = _choice_branches(lst, i)
            for k, label in enumerate(params[0]):
                if not isinstance(label, str):
                    continue
                bare, pre, suf = split_choice_condition(label)
                if not codes.has_jp(bare) or bare in DO_NOT_TRANSLATE:
                    continue
                cleaned = codes.clean_source(bare)
                masked, cmap = codes.mask_codes(cleaned)
                uid = "%s:c%d:ch%d" % (uid_prefix, i, k)
                u = _mk_unit(uid, "choice", ptr, masked, label,
                             start=i, slot=k, ctx=ctx, codes=cmap)
                u["cond_prefix"] = pre
                u["cond_suffix"] = suf
                if branch:
                    u["note"] = "branches: " + branch
                units.append(u)
            i += 1
            continue

        # ---- 356 MV plugin command ---------------------------------------
        if cfg.code_356 and code == 356 and params and isinstance(params[0], str):
            hit = _plugin356_slots(params[0], cfg)
            for slot, value in hit:
                if not codes.has_jp(value) or value in DO_NOT_TRANSLATE:
                    continue
                cleaned = codes.clean_source(value)
                masked, cmap = codes.mask_codes(cleaned)
                uid = "%s:c%d:a%d" % (uid_prefix, i, slot)
                units.append(_mk_unit(
                    uid, "ptext", ptr, masked, value,
                    start=i, slot=slot, ctx=ctx, codes=cmap,
                    note="single space-delimited plugin argument - the "
                         "translation must contain no ASCII space",
                ))
            i += 1
            continue

        i += 1


# A line opening with one of these escapes starts a NEW message box.
# c n i k v are absent on purpose: colour, actor name, icon, key and variable
# are inline CONTENT and must stay merged with the sentence around them.
_BLOCK_BREAK = re.compile(
    r"^\s*[\\]+[aAbBdDeEgGhHjJlLmMoOpPqQrRsStTuUwWxXyYzZ]+\[[\w\d\[\]\\]+\]")


def _choice_branches(lst, idx):
    """`0=はい 1=いいえ` for the 402 branch labels that follow this 102.

    Without these in front of a reviewer, a swapped Yes/No is invisible: the
    engine branches on parameters[0] (the INDEX), so inverting two labels
    silently rewires which branch the player gets."""
    indent = lst[idx].get("indent", 0)
    out = []
    for c in lst[idx + 1:]:
        if not isinstance(c, dict):
            continue
        if c.get("indent", 0) < indent:
            break
        if c.get("code") == 404 and c.get("indent", 0) == indent:
            break
        if c.get("code") == 402 and c.get("indent", 0) == indent:
            p = c.get("parameters") or [None, ""]
            out.append("%s=%s" % (p[0], p[1]))
    return " ".join(out)


def split_choice_condition(label):
    """Peel plugin visibility clauses off a choice label.

    Balanced-paren scanner, never a regex: a regex ending at the first `)`
    truncates inside `$gameSwitches.value(1)`, producing a condition that no
    longer parses and a choice window that hides an option or crashes. On any
    unbalanced input the label is returned untouched."""
    pre = ""
    s = label
    for kw in ("if(", "en("):
        if s.startswith(kw):
            depth = 0
            for i, ch in enumerate(s):
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        pre, s = s[:i + 1], s[i + 1:]
                        break
            else:
                return label, "", ""
            break
    suf = ""
    m = re.search(r"(?:\b(?:if|en)\((?:[^()]|\([^()]*\))*\)\s*)+$", s)
    if m:
        suf = s[m.start():]
        s = s[:m.start()]
    return s, pre, suf


def _plugin356_slots(command, cfg):
    """[(arg_index, value)] for a whitelisted MV plugin command."""
    args = command.split(" ")
    if len(args) < 2:
        return []
    name, sub = args[0], args[1]
    table = cfg.plugin356_text.get(name)
    if not table:
        return []
    slots = table.get(sub)
    if not slots:
        return []
    out = []
    for s in slots:
        idx = s + 1                      # args[0] is the plugin name
        if idx < len(args):
            out.append((idx, args[idx]))
    return out


# --------------------------------------------------------------------------
def extract_event_file(path, cfg, glossary):
    data, _r = fileio.load(path)
    base = os.path.basename(path)
    stem = os.path.splitext(base)[0]
    units = []
    speaker = cfg.portrait_speaker

    if base == "CommonEvents.json":
        for idx, ev in enumerate(data):
            if not ev or not isinstance(ev, dict):
                continue
            lst = ev.get("list") or []
            name = ev.get("name", "")
            ctx = "CommonEvents / CE%d %r" % (ev.get("id", idx), name)
            solo = bool(cfg.solo_speaker_scene_re
                        and re.search(cfg.solo_speaker_scene_re, name))
            if solo:
                ctx += " [trap-encounter CG scene - the protagonist is the "
                ctx += "only speaker]"
            _extract_list(lst, [idx, "list"],
                          "%s:ce%d" % (stem, ev.get("id", idx)),
                          ctx, cfg, units, speaker, solo=solo)
        return units

    if base == "Troops.json":
        for idx, tr in enumerate(data):
            if not tr or not isinstance(tr, dict):
                continue
            for pi, page in enumerate(tr.get("pages") or []):
                lst = page.get("list") or []
                ctx = "Troops / troop %d %r page %d" % (tr.get("id", idx),
                                                        tr.get("name", ""), pi)
                _extract_list(lst, [idx, "pages", pi, "list"],
                              "%s:t%d:p%d" % (stem, tr.get("id", idx), pi),
                              ctx, cfg, units, speaker)
        return units

    # Map###.json - `events` is a SPARSE list indexed by event id, so the
    # write-back pointer must be the list index, taken from enumerate. Looking
    # it up with .index(ev) would collide between two structurally identical
    # events and send a translation to the wrong one.
    display = data.get("displayName", "") or ""
    for ev_index, ev in enumerate(data.get("events") or []):
        if not ev or not isinstance(ev, dict):
            continue
        ev_id = ev.get("id", ev_index)
        for pi, page in enumerate(ev.get("pages") or []):
            lst = page.get("list") or []
            ctx = _ctx_label(stem, display, ev_id, ev.get("name", ""), pi)
            _extract_list(lst, ["events", ev_index, "pages", pi, "list"],
                          "%s:ev%d:p%d" % (stem, ev_id, pi),
                          ctx, cfg, units, speaker)

    if cfg.map_display_names and display and codes.has_jp(display):
        masked, cmap = codes.mask_codes(codes.clean_source(display))
        units.append(_mk_unit("%s:displayName" % stem, "mapname",
                              ["displayName"], masked, display,
                              ctx="map name banner (%s)" % stem, codes=cmap))
    return units


# --------------------------------------------------------------------------
# Phase 0 - database
# --------------------------------------------------------------------------
_DB_FIELDS = {
    "Items.json": ["name", "description"],
    "Armors.json": ["name", "description"],
    "Weapons.json": ["name", "description"],
    "Skills.json": ["name", "description", "message1", "message2"],
    "States.json": ["name", "message1", "message2", "message3", "message4"],
    "Enemies.json": ["name"],
    "Classes.json": ["name"],
    "Troops.json": ["name"],
}
_KIND_BY_FIELD = {
    "name": "name", "description": "desc", "note": "note",
    "message1": "message", "message2": "message",
    "message3": "message", "message4": "message",
}


def extract_database(path, cfg, glossary):
    base = os.path.basename(path)
    fields = _DB_FIELDS.get(base)
    if not fields:
        return []
    data, _r = fileio.load(path)
    stem = os.path.splitext(base)[0]
    units = []
    for idx, e in enumerate(data):
        if not e or not isinstance(e, dict):
            continue
        for f in fields:
            v = e.get(f, "")
            if not isinstance(v, str) or not codes.has_jp(v):
                continue
            if v in DO_NOT_TRANSLATE:
                continue
            masked, cmap = codes.mask_codes(codes.clean_source(v))
            kind = _KIND_BY_FIELD.get(f, "name")
            u = _mk_unit("%s:%d:%s" % (stem, idx, f), kind, [idx, f],
                         masked, v, ctx="%s #%d %s" % (stem, e.get("id", idx),
                                                       e.get("name", "")),
                         codes=cmap)
            # message1..4 are action-log FRAGMENTS the engine concatenates
            # after an actor name. A bare `は触手を伸ばした！` gives the model
            # no grammatical subject.
            if kind == "message" and v[:1] in "はをのにが":
                u["dummy_subject"] = True
            units.append(u)
    return units


def extract_actors(path, cfg, glossary):
    """Actor names go into the GLOSSARY, never into units.

    One English spelling then serves the name box, any \\N[id] reference and
    the menu at once. Consequence worth knowing before it alarms you: a store
    with zero translations still legitimately rewrites Actors.json on inject."""
    data, _r = fileio.load(path)
    seeded = 0
    for e in data:
        if not e or not isinstance(e, dict):
            continue
        for f in ("name", "nickname"):
            v = e.get(f, "")
            if isinstance(v, str) and codes.has_jp(v):
                if v not in glossary["names"]:
                    glossary["names"][v] = {
                        "en": "", "gender": "", "role": "",
                        "register": "", "aliases": [],
                        "note": "seeded from Actors.json #%d %s" % (e.get("id", 0), f),
                    }
                    seeded += 1
    return seeded


def extract_system(path, cfg, glossary):
    data, _r = fileio.load(path)
    units = []

    def add(uid, kind, ptr, value, ctx, **kw):
        if not isinstance(value, str) or not codes.has_jp(value):
            return
        if value in DO_NOT_TRANSLATE:
            return
        masked, cmap = codes.mask_codes(codes.clean_source(value))
        u = _mk_unit(uid, kind, ptr, masked, value, ctx=ctx, codes=cmap)
        u.update(kw)
        units.append(u)

    add("System:gameTitle", "title", ["gameTitle"], data.get("gameTitle", ""),
        "game title (window caption + title screen)")
    add("System:currencyUnit", "currency", ["currencyUnit"],
        data.get("currencyUnit", ""), "currency unit, drawn beside a number")

    for cat in ("basic", "commands", "params"):
        for i, v in enumerate(data.get("terms", {}).get(cat, []) or []):
            add("System:terms:%s:%d" % (cat, i), "term",
                ["terms", cat, i], v,
                "System terms.%s[%d] - a UI label, keep it terse" % (cat, i))

    for k, v in sorted((data.get("terms", {}).get("messages") or {}).items()):
        add("System:terms:messages:%s" % k, "message",
            ["terms", "messages", k], v,
            "battle/menu message %r - %%1 %%2 are runtime substitutions" % k)

    for lst in ("armorTypes", "weaponTypes", "equipTypes", "skillTypes", "elements"):
        for i, v in enumerate(data.get(lst, []) or []):
            # Slot 0 is usually null/empty; preserving the index is what stops
            # every type being renamed by one.
            add("System:%s:%d" % (lst, i), "type", [lst, i], v,
                "System %s[%d] - a type label" % (lst, i))

    if cfg.system_switches:
        for i, v in enumerate(data.get("switches", []) or []):
            add("System:switches:%d" % i, "term", ["switches", i], v,
                "switch name")
    if cfg.system_variables:
        for i, v in enumerate(data.get("variables", []) or []):
            add("System:variables:%d" % i, "term", ["variables", i], v,
                "variable name")
    return units


# --------------------------------------------------------------------------
def run(cfg, store_dir, verbose=True):
    """Full extraction. Re-runnable: existing translations are carried over."""
    glossary = store.load_glossary(store_dir)
    os.makedirs(store.units_dir(store_dir), exist_ok=True)
    totals = collections.Counter()

    # --- Phase 0 -----------------------------------------------------------
    actors = os.path.join(cfg.data_dir, "Actors.json")
    if cfg.actor_names and os.path.exists(actors):
        n = extract_actors(actors, cfg, glossary)
        if verbose and n:
            print("  Actors.json  -> %d name(s) seeded into the glossary" % n)

    for base in DB_FILES:
        p = os.path.join(cfg.data_dir, base)
        if not os.path.exists(p) or base == "Actors.json":
            continue
        units = extract_database(p, cfg, glossary)
        _write(store_dir, base, units, totals, verbose)

    sysp = os.path.join(cfg.data_dir, "System.json")
    if cfg.system and os.path.exists(sysp):
        _write(store_dir, "System.json", extract_system(sysp, cfg, glossary),
               totals, verbose)

    # --- Phase 1 + 2 -------------------------------------------------------
    event_files = sorted(glob.glob(os.path.join(cfg.data_dir, "Map[0-9][0-9][0-9].json")))
    for extra in ("CommonEvents.json", "Troops.json"):
        p = os.path.join(cfg.data_dir, extra)
        if os.path.exists(p):
            event_files.append(p)
    for p in event_files:
        units = extract_event_file(p, cfg, glossary)
        _write(store_dir, os.path.basename(p), units, totals, verbose)

    store.save_glossary(store_dir, glossary)
    if verbose:
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
    if verbose:
        note = "  (%d translations carried over)" % kept if kept else ""
        print("  %-20s %4d units%s" % (base, len(units), note))
