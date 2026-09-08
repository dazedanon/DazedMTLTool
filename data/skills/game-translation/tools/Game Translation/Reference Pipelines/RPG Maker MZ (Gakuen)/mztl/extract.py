#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
extract.py - game data -> translation store.

Four phases, run over different file sets with different code profiles, because
one extraction with every code enabled ships a translated plugin keyword or
script identifier and the failure has no crash and no diff:

  Phase 0  the database files + System.json, ALL event codes forced off.
           Does the proper nouns first so the glossary is locked before any
           dialogue mentions them.
  Phase 1  CommonEvents + Map* + Troops: codes 101/401/102 only. Phase 0 +
           Phase 1 alone must make the game playable end to end.
  Phase 1b nothing. This game's 111s hold no string comparisons: the condition
           types are {0,1,2,4,7,8,10,12} and not one of the 19 script
           conditions mentions `$gameVariables`, so the 122/111 reconciliation
           that makes most RPG Maker patches unwinnable does not apply.
           Verified in `audit/CENSUS.txt`, not assumed.
  Phase 2  122 (whitelisted to five display variables), 355/655 (CBR_EroStatus
           `テキスト-` rows only), 357 (two plugins), 108/408 (`選択肢ヘルプ`).

Speaker attribution is STATELESS and refuses to guess. There is no usable
code-101 `parameters[4]` here (41 of 8,368) and almost no face graphic (37), so
the signal is the game's own convention: the speaker is written as the FIRST
PHYSICAL LINE of the 401 run, with the dialogue opening on the next line inside
「」. 4,872 blocks match; the other 3,496 are narration and get an EMPTY
speaker rather than one inherited from an earlier 101, which is the classic way
lines get attributed to the wrong character after a conditional branch.
"""

import os
import re
import glob
import json
import collections

from . import codes, store, fileio
from .config import DB_FILES, KEY_STRINGS

RUN_CODES = (401, 405, -1)
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
                                   if k in ("start", "count", "slot", "field",
                                            "prefix")})],
        "src": src,
        "raw": raw,
        "tl": "",
    }
    for k in ("speaker", "ctx", "nametag", "codes", "note", "faced"):
        if kw.get(k):
            u[k] = kw[k]
    return u


# A line opening with one of these escapes starts a NEW message box.
# c n i k v are absent on purpose: colour, actor name, icon, key and variable
# are inline CONTENT and must stay merged with the sentence around them.
_BLOCK_BREAK = re.compile(
    r"^\s*[\\]+[aAbBdDeEgGhHjJlLoOpPqQrRtTuUwWxXyYzZ]+\[[\w\d\[\]\\]+\]")


# --------------------------------------------------------------------------
# Phase 1 - event command lists
# --------------------------------------------------------------------------
def _extract_list(lst, ptr, uid_prefix, ctx, cfg, units, glossary):
    """Walk one event command list. Never mutates it."""
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
                if j > start and _BLOCK_BREAK.match(line):
                    break
                parts.append(line)
                j += 1
            if parts:
                _emit_text(lst, start, j, parts, ptr, uid_prefix, ctx, cfg,
                           units, glossary)
            i = max(j, i + 1)
            continue

        # ---- 102 choices --------------------------------------------------
        if cfg.code_choices and code == 102 and params and isinstance(params[0], list):
            branch = _choice_branches(lst, i)
            for k, label in enumerate(params[0]):
                if not isinstance(label, str):
                    continue
                masked, cmap, has_cond = _mask_choice(label)
                if not codes.has_jp(codes.PH_RE.sub("", masked)):
                    continue
                uid = "%s:c%d:ch%d" % (uid_prefix, i, k)
                u = _mk_unit(uid, "choice", ptr, masked, label,
                             start=i, slot=k, ctx=ctx, codes=cmap)
                notes = []
                if has_cond:
                    notes.append("one ⟦n⟧ sentinel here is a PLUGIN VISIBILITY "
                                 "CONDITION, not markup - keep it exactly where "
                                 "it sits or the choice stops being conditional")
                if branch:
                    notes.append("branches: " + branch)
                if notes:
                    u["note"] = "; ".join(notes)
                units.append(u)
            i += 1
            continue

        # ---- 122 Control Variables ---------------------------------------
        # `parameters[3] == 4` is direct string assignment; anything else is
        # arithmetic and holds no text. Whitelisted BY VARIABLE ID, never by
        # string, and only for ids proved to be display-only.
        if cfg.code_122 and code == 122 and len(params) > 4 and params[3] == 4:
            v = params[4]
            if isinstance(v, str) and _var_range_allowed(params, cfg):
                inner, q = _peel_quotes(v)
                if (codes.has_jp(inner) and inner.strip() not in KEY_STRINGS
                        and not _looks_like_identifier(inner)):
                    cleaned = codes.clean_source(inner)
                    masked, cmap = codes.mask_codes(cleaned)
                    uid = "%s:c%d:var" % (uid_prefix, i)
                    u = _mk_unit(uid, "ptext", ptr, masked, v,
                                 start=i, slot=4, ctx=ctx, codes=cmap,
                                 note="a value stored into game variable %s and "
                                      "drawn later through a \\V[n] code - keep "
                                      "it to a short noun phrase" % params[0])
                    u["quote"] = q
                    units.append(u)
            i += 1
            continue

        # ---- 355 / 655 script block --------------------------------------
        if cfg.code_355 and code == 355:
            j = i
            rows = []
            while j < n and isinstance(lst[j], dict) and lst[j].get("code") in (355, 655):
                rows.append((j, ((lst[j].get("parameters") or [""]) + [""])[0]))
                j += 1
            for row_idx, value in rows:
                if not isinstance(value, str):
                    continue
                if not value.startswith(cfg.cbr_text_prefix):
                    continue
                body = value[len(cfg.cbr_text_prefix):]
                if not codes.has_jp(body):
                    continue
                cleaned = codes.clean_source(body)
                masked, cmap = codes.mask_codes(cleaned)
                uid = "%s:c%d:cbr" % (uid_prefix, row_idx)
                units.append(_mk_unit(
                    uid, "ptext", ptr, masked, value,
                    start=row_idx, slot=0, prefix=cfg.cbr_text_prefix,
                    ctx=ctx + " / ero-status screen row", codes=cmap,
                    note="one row of the Ero Status screen, drawn at a fixed x "
                         "coordinate next to a number - keep it SHORT and keep "
                         "any trailing colon"))
            i = max(j, i + 1)
            continue

        # ---- 357 MZ plugin command ---------------------------------------
        if cfg.code_357 and code == 357 and len(params) > 3:
            for key, value in _plugin357_slots(params, cfg):
                # No KEY_STRINGS check: `cfg.plugin357_text` admits only
                # arguments the plugin DRAWS (DTextPicture.text,
                # TorigoyaMZ_NotifyMessage.message), so reaching here already
                # proves this is display text. Filtering it again is what left
                # the difficulty VALUE reading `普通` on the opening screen.
                if not codes.has_jp(value):
                    continue
                cleaned = codes.clean_source(value)
                masked, cmap = codes.mask_codes(cleaned)
                uid = "%s:c%d:%s" % (uid_prefix, i, store.sanitize_id(key))
                units.append(_mk_unit(
                    uid, "ptext", ptr, masked, value,
                    start=i, slot=3, field=key, ctx=ctx, codes=cmap,
                    note="argument %r of plugin command %s - it lives inside a "
                         "JSON string, so emit no double quote and no literal "
                         "newline" % (key, params[0])))
            i += 1
            continue

        # ---- 108 / 408 comment block -------------------------------------
        if cfg.code_408 and code == 108:
            j = i
            rows = []
            while j < n and isinstance(lst[j], dict) and lst[j].get("code") in (108, 408):
                rows.append((j, lst[j].get("code"),
                             ((lst[j].get("parameters") or [""]) + [""])[0]))
                j += 1
            head = rows[0][2].strip() if rows else ""
            if head in cfg.comment_markers:
                for row_idx, rcode, value in rows[1:]:
                    if not isinstance(value, str) or not codes.has_jp(value):
                        continue
                    cleaned = codes.clean_source(value)
                    masked, cmap = codes.mask_codes(cleaned)
                    uid = "%s:c%d:help" % (uid_prefix, row_idx)
                    units.append(_mk_unit(
                        uid, "help", ptr, masked, value,
                        start=row_idx, slot=0, ctx=ctx, codes=cmap,
                        note="one line of the choice-help window MPP_ChoiceEX "
                             "draws above the choice list"))
            i = max(j, i + 1)
            continue

        i += 1


def _emit_text(lst, start, end, parts, ptr, uid_prefix, ctx, cfg, units,
               glossary):
    """One 401 run -> at most one unit, plus a glossary speaker."""
    faced = _face_for(lst, start)
    joined = "\n".join(parts)
    speaker_raw = ""
    body = joined
    if cfg.first_line_speaker:
        speaker_raw, body = codes.split_speaker(
            joined, cfg.speaker_max_len, cfg.speaker_openers)
    speaker = codes.clean_source(speaker_raw).strip() if speaker_raw else ""
    if speaker:
        # A speaker is a GLOSSARY entry, not a unit: one English spelling then
        # serves every block that character speaks in.
        glossary.setdefault("names", {})
        if speaker not in glossary["names"]:
            glossary["names"][speaker] = {
                "en": "", "gender": "", "role": "", "register": "",
                "aliases": [], "note": "speaker nameplate (first line of a "
                                       "401 run)",
            }

    cleaned = codes.clean_source(body)
    masked, cmap = codes.mask_codes(cleaned)
    body_has_jp = codes.has_jp(codes.PH_RE.sub("", masked))
    # The SILENT-BEAT rule. A box whose body is `「………」` holds no Japanese, so
    # a has_jp gate skips it - and then inject never sees the unit, and its
    # Japanese NAMEPLATE ships over the rest of the English. Extract when the
    # body has Japanese OR there is a speaker, and pre-fill a Japanese-free
    # body with itself so no request is ever spent on it.
    if not body_has_jp and not speaker:
        return
    uid = "%s:c%d" % (uid_prefix, start)
    u = _mk_unit(uid, "text", ptr, masked, joined,
                 start=start, count=end - start,
                 speaker=speaker, ctx=ctx, codes=cmap)
    if not body_has_jp:
        u["tl"] = masked
        u["locked"] = True
        u["note"] = ("body carries no source text - only the nameplate needed "
                     "translating")
    if speaker_raw:
        # Byte-exact, so inject can re-emit the original line when the glossary
        # has no English for it yet.
        u["speaker_raw"] = speaker_raw
    if faced:
        u["faced"] = True
    units.append(u)


def _face_for(lst, start):
    """True when the 101 owning this run carries a face graphic.

    A face steals 164 px, which is a different wrap width for those lines.
    Only 37 of 8,368 headers have one, so this path is nearly dead - but it is
    counted rather than assumed."""
    k = start - 1
    while k >= 0 and isinstance(lst[k], dict) and lst[k].get("code") in (401, -1):
        k -= 1
    if k >= 0 and isinstance(lst[k], dict) and lst[k].get("code") == 101:
        p = lst[k].get("parameters") or []
        return bool(p and p[0])
    return False


def _var_range_allowed(params, cfg):
    """`121`/`122` write a RANGE. Every id in it must be whitelisted."""
    try:
        a, b = int(params[0]), int(params[1])
    except (TypeError, ValueError):
        return False
    if isinstance(params[0], bool) or isinstance(params[1], bool):
        return False
    if b < a:
        a, b = b, a
    return all(v in cfg.var122_allow for v in range(a, b + 1))


_QUOTE_CHARS = "\"'`"


def _peel_quotes(v):
    s = v.strip()
    if len(s) >= 2 and s[0] in _QUOTE_CHARS and s[-1] == s[0]:
        return s[1:-1], s[0]
    return v, ""


_IDENT_RE = re.compile(r"gameV|_|\"\[|＠|\$game|\.\w+\(")


def _looks_like_identifier(s):
    """Hard-skip markers from the skill's 122 table."""
    return bool(_IDENT_RE.search(s))


def _plugin357_slots(params, cfg):
    """[(arg_key, value)] for a whitelisted MZ plugin command.

    Matched on the TRAILING plugin name, because MZ ships the same plugin as
    both `DTextPicture` and `triacontane/DTextPicture` depending on install
    path and a full-string match silently skips half of them. Substring
    matching overlaps (`TextPicture` sits inside `DTextPicture`), so a
    per-command set of already-yielded keys keeps a value from being emitted
    twice."""
    name = params[0] if isinstance(params[0], str) else ""
    args = params[3]
    if not isinstance(args, dict):
        return []
    out = []
    done = set()
    for plugin, keys in cfg.plugin357_text.items():
        if not (name == plugin or name.endswith("/" + plugin)
                or name.endswith("\\" + plugin)):
            continue
        for k in keys:
            if k in done or k not in args:
                continue
            v = args.get(k)
            if isinstance(v, str) and v.strip():
                done.add(k)
                out.append((k, v))
    return out


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
            p = (c.get("parameters") or [None, ""]) + [""]
            out.append("%s=%s" % (p[0], p[1]))
    return " ".join(out)


# NO `\b` in front of this. A word boundary requires a transition between a
# word and a non-word character, and Python's `\w` includes CJK - so in
# `はいen(v[3]<=50)` there is no boundary between `い` and `e` and an anchored
# pattern finds nothing at all. Four choices in this game carry their condition
# glued straight onto the Japanese like that, and every one of them silently
# lost it: `はいen(v[3]<=50)(貞操観念が50以下)` translated to
# "Yes (Chastity 50 or Below)", which turns a choice gated on the Chastity stat
# into one that is ALWAYS visible. No crash, no diff, and nothing a text check
# can see.
_COND_START_RE = re.compile(r"(?:if|en)\(")


def split_choice_condition(label):
    """(bare_label, [condition_clause, ...]) with the clauses byte-exact.

    Balanced-paren scanner, never a regex: a regex ending at the first `)`
    truncates inside `$gameSwitches.value(1)`, producing a condition that no
    longer parses and a choice window that hides an option or crashes. On any
    unbalanced input the label is returned untouched, so a parse failure can
    never delete visible choice text.

    A clause may sit anywhere - leading, trailing, or wedged between the label
    and a human-readable annotation - so each one is replaced IN PLACE by a
    `\\x00k\\x00` marker that `_mask_choice` turns into an ordinary `⟦n⟧`
    sentinel. That puts the condition under the placeholder validator: losing
    one becomes a hard failure instead of a silent change to what the player
    can pick."""
    out = []
    conds = []
    i = 0
    n = len(label)
    while i < n:
        m = _COND_START_RE.search(label, i)
        if not m:
            out.append(label[i:])
            break
        depth = 0
        end = None
        for k in range(m.end() - 1, n):
            if label[k] == "(":
                depth += 1
            elif label[k] == ")":
                depth -= 1
                if depth == 0:
                    end = k + 1
                    break
        if end is None:
            return label, []                  # unbalanced - touch nothing
        out.append(label[i:m.start()])
        out.append("\x00%d\x00" % len(conds))
        conds.append(label[m.start():end])
        i = end
    return "".join(out), conds


def _mask_choice(label):
    """(masked_src, code_map) for one choice label, conditions included."""
    body, conds = split_choice_condition(label)
    cleaned = codes.clean_source(body)
    masked, cmap = codes.mask_codes(cleaned)
    base = len(cmap)
    for k, clause in enumerate(conds):
        ph = "%s%d%s" % (codes.PH_OPEN, base + k, codes.PH_CLOSE)
        cmap[ph] = clause
        masked = masked.replace("\x00%d\x00" % k, ph)
    return masked, cmap, bool(conds)


# --------------------------------------------------------------------------
def extract_event_file(path, cfg, glossary):
    data, _r = fileio.load(path)
    base = os.path.basename(path)
    stem = os.path.splitext(base)[0]
    units = []

    if base == "CommonEvents.json":
        for idx, ev in enumerate(data):
            if not ev or not isinstance(ev, dict):
                continue
            lst = ev.get("list") or []
            name = ev.get("name", "")
            ctx = "CommonEvents / CE%d %r" % (ev.get("id", idx), name)
            _extract_list(lst, [idx, "list"],
                          "%s:ce%d" % (stem, ev.get("id", idx)),
                          ctx, cfg, units, glossary)
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
                              ctx, cfg, units, glossary)
        return units

    # Map###.json - `events` is a SPARSE list indexed by event id, so the
    # write-back pointer must be the list index taken from enumerate. Looking
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
                          ctx, cfg, units, glossary)

    if cfg.map_display_names and display and codes.has_jp(display):
        masked, cmap = codes.mask_codes(codes.clean_source(display))
        units.append(_mk_unit("%s:displayName" % stem, "mapname",
                              ["displayName"], masked, display,
                              ctx="map name banner (%s)" % stem, codes=cmap))

    # `<LB:text>` note tags - EventLabel draws these as a floating caption over
    # the event. The tag NAME is a key and stays; only the value is translated,
    # and it is spliced back into the note by exact span so every other tag on
    # that note field survives byte-for-byte.
    for tag in (cfg.note_label_tags or ()):
        rx = re.compile(r"<" + re.escape(tag) + r":([^>]*)>")
        for ev_index, ev in enumerate(data.get("events") or []):
            if not ev or not isinstance(ev, dict):
                continue
            note = ev.get("note") or ""
            for m in rx.finditer(note):
                value = m.group(1)
                if not codes.has_jp(value):
                    continue
                masked, cmap = codes.mask_codes(codes.clean_source(value))
                uid = "%s:ev%d:note:%s:%d" % (stem, ev.get("id", ev_index),
                                              tag, m.start(1))
                units.append(_mk_unit(
                    uid, "label", ["events", ev_index, "note"], masked, value,
                    start=m.start(1), count=m.end(1) - m.start(1),
                    ctx="%s / event %d - floating map label drawn by EventLabel"
                        % (stem, ev.get("id", ev_index)),
                    codes=cmap,
                    note="a caption floating over a map object - 1-3 words, "
                         "title case, no final punctuation, and it must not "
                         "contain '>' or the note tag closes early"))
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
            if v.strip() in KEY_STRINGS:
                continue
            masked, cmap = codes.mask_codes(codes.clean_source(v))
            kind = _KIND_BY_FIELD.get(f, "name")
            u = _mk_unit("%s:%d:%s" % (stem, idx, f), kind, [idx, f],
                         masked, v, ctx="%s #%d %s" % (stem, e.get("id", idx),
                                                       e.get("name", "")),
                         codes=cmap)
            # message1..4 are action-log FRAGMENTS the engine concatenates
            # after an actor name. A bare `は倒れた！` gives the model no
            # grammatical subject.
            if kind == "message" and v[:1] in "はをのにが":
                u["dummy_subject"] = True
            units.append(u)
    return units


def extract_actors(path, cfg, glossary):
    r"""Actor names go into the GLOSSARY, never into units.

    One English spelling then serves the name box, any \N[id] reference and the
    menu at once. Consequence worth knowing before it alarms you: a store with
    zero translations still legitimately rewrites Actors.json on inject."""
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
        if value.strip() in KEY_STRINGS:
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
            add("System:switches:%d" % i, "term", ["switches", i], v, "switch name")
    if cfg.system_variables:
        # Whitelisted BY ID. A variable name is a key in general - plugins and
        # events resolve them by name - so only the ids something is proved to
        # DRAW are extracted. Here that is variable 1, whose name LL_Variable-
        # Window renders as the label of the on-screen calendar box.
        for i in sorted(cfg.system_variable_allow):
            names = data.get("variables", []) or []
            if 0 <= i < len(names):
                add("System:variables:%d" % i, "term", ["variables", i],
                    names[i],
                    "the LABEL of the on-screen box LL_VariableWindow draws "
                    "for variable %d - a value is printed immediately after "
                    "it, so keep any trailing colon and keep it short" % i)
    return units


def extract_map_infos(path, cfg, glossary):
    r"""MapInfos names - the map-name banner wherever displayName is blank.

    `MapNameExtend` is enabled with `showReal: true`, and its override makes
    `Game_Map.displayName()` fall back to `$dataMapInfos[id].name`. 42 maps
    here have a blank display name, so for those the MapInfos entry IS what the
    banner shows."""
    if not cfg.map_info_names:
        return []
    data, _r = fileio.load(path)
    units = []
    for idx, e in enumerate(data):
        if not e or not isinstance(e, dict):
            continue
        v = e.get("name", "")
        if not isinstance(v, str) or not codes.has_jp(v):
            continue
        masked, cmap = codes.mask_codes(codes.clean_source(v))
        units.append(_mk_unit(
            "MapInfos:%d:name" % idx, "mapname", [idx, "name"], masked, v,
            ctx="MapInfos #%s - the map-name banner (MapNameExtend showReal)"
                % e.get("id", idx),
            codes=cmap))
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

    # Troops.json carries BOTH a database `name` field and event pages, so its
    # two extractions must land in one doc or the second write drops the first.
    for base in DB_FILES:
        p = os.path.join(cfg.data_dir, base)
        if not os.path.exists(p) or base in ("Actors.json", "Troops.json"):
            continue
        _write(store_dir, base, extract_database(p, cfg, glossary),
               totals, verbose)

    sysp = os.path.join(cfg.data_dir, "System.json")
    if cfg.system and os.path.exists(sysp):
        _write(store_dir, "System.json", extract_system(sysp, cfg, glossary),
               totals, verbose)

    mip = os.path.join(cfg.data_dir, "MapInfos.json")
    if cfg.map_info_names and os.path.exists(mip):
        _write(store_dir, "MapInfos.json", extract_map_infos(mip, cfg, glossary),
               totals, verbose)

    # --- Phase 1 + 2 -------------------------------------------------------
    event_files = sorted(glob.glob(os.path.join(cfg.data_dir,
                                                "Map[0-9][0-9][0-9].json")))
    for extra in ("CommonEvents.json", "Troops.json"):
        p = os.path.join(cfg.data_dir, extra)
        if os.path.exists(p):
            event_files.append(p)
    for p in event_files:
        base = os.path.basename(p)
        units = extract_event_file(p, cfg, glossary)
        if base == "Troops.json":
            units = extract_database(p, cfg, glossary) + units
        _write(store_dir, base, units, totals, verbose)

    store.save_glossary(store_dir, glossary)
    if verbose:
        print("\nTOTAL %d units" % sum(totals.values()))
        for k, v in totals.most_common():
            print("  %-10s %d" % (k, v))
        print("  glossary names: %d" % len(glossary.get("names", {})))
    return totals


class ExtractionCollapsed(RuntimeError):
    pass


def _write(store_dir, base, units, totals, verbose):
    r"""Save one doc, refusing to destroy finished work.

    THE FAILURE THIS GUARD EXISTS FOR. `extract` reads `cfg.data_dir`, and
    after `inject --in-place` that directory holds the ENGLISH build. Running
    extract against it finds no Japanese, so every file yields zero units - and
    the old code cheerfully wrote those empty docs over the store, wiping
    10,505 finished translations in one pass with no error and no prompt.
    (Recovered from the copy under `Tools\Game Translation\Reference
    Pipelines\`, which is the entire reason the skill says to keep tooling
    outside the game folder.)

    A re-extraction that finds materially less than the store already holds is
    always a mistake - a wrong `--game`, a half-restored backup, or exactly the
    case above - so it raises instead of writing."""
    path = store.doc_path(store_dir, base)
    kept = 0
    old_units = []
    if os.path.exists(path):
        old_units = store.read_json(path).get("units", [])
        kept = store.merge_translations(old_units, units)

    old_done = sum(1 for u in old_units if (u.get("tl") or "").strip())
    if old_done and len(units) < len(old_units) * 0.5:
        raise ExtractionCollapsed(
            "%s: the store holds %d unit(s) (%d translated) but this "
            "extraction found only %d.\n"
            "  Refusing to overwrite. This almost always means data/ is "
            "already the ENGLISH build - restore the pristine data/ from a "
            "data_backup_* folder and re-run."
            % (base, len(old_units), old_done, len(units)))

    if not units and not os.path.exists(path):
        return
    store.save_doc(store_dir, base, units)
    for u in units:
        totals[u["kind"]] += 1
    if verbose:
        note = "  (%d translations carried over)" % kept if kept else ""
        print("  %-20s %4d units%s" % (base, len(units), note))
