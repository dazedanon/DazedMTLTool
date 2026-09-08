#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
helpwrap.py — re-flow the fixed-line-picture text screens so translated English
fits, since these layouts have NO word wrap (each variable is drawn as its own
fixed-position DTextPicture, so the longer English runs off the edge).

Two templates in this game (both shared CommonEvents):
  * CE100 ヘルプ表示テンプレート — the help / tutorial pages (How to Play, How to
    Increase Units, every monster-lore entry, …). Title var 501 + 15 body LINES
    502..516 ('　' = blank spare), body font in var 520, drawn LEFT-aligned at
    x=640 (right half of a 1280-wide screen). Prose is re-paragraphed and wrapped;
    if it can't fit 15 slots the font is stepped down (width grows as font shrinks).
  * CE36 画面中央文字 — the centred screen banners (\\V[4611..4614], 4 lines, default
    font, centred = full screen width). Long lines are wrapped IN PLACE into the
    spare slots, preserving the dev's dramatic line breaks.

Runs INSIDE inject after the code-122 display text is applied (config.help_reflow),
so re-injecting always reproduces it. reflow_help.py is a CLI for previewing.
"""
import re
from . import codes

SCREEN_W = 1280
RECOLLECTION_FONT = 14   # CE995 回想 unlock-grid font (was 16; English rows clipped the top)

# per-template config: ce id, body var range, font var (None=fixed), font ladder,
# available px (left-half 640 vs centred full 1280), and whether to re-paragraph.
TEMPLATES = [
    {"ce": 100, "lo": 502, "hi": 516, "font_var": 520,
     "fonts": [20, 18, 16, 15, 14], "avail": SCREEN_W - 640, "merge": True},
    {"ce": 36, "lo": 4611, "hi": 4614, "font_var": None,
     "fonts": [26], "avail": SCREEN_W, "merge": False},
]
_STRUCT_RE = re.compile(r"^\s*(?:[・•※]|[-—]\s|[0-9０-９]+\s*[.．)、])")


def _width_cells(font, avail):
    # M+ 1m monospace: ~font/2 px per half-width cell across the available area
    return int(avail / (font / 2)) - 3


def _unq(s):
    """Strip the JS string quotes AND un-escape (\\\\ \\' \\\" -> \\ ' \"), so the
    reflow operates on plain text and _requote re-escapes exactly once (no
    double-escaping of apostrophes across the round-trip)."""
    s = s.strip()
    if not (len(s) >= 2 and s[0] in "'\"" and s[-1] == s[0]):
        return s
    inner, out, i = s[1:-1], [], 0
    while i < len(inner):
        if inner[i] == "\\" and i + 1 < len(inner) and inner[i + 1] in "\\'\"":
            out.append(inner[i + 1]); i += 2
        else:
            out.append(inner[i]); i += 1
    return "".join(out)


def _requote(s):
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _is_struct(t):
    return t.strip() == "↓" or bool(_STRUCT_RE.match(t))


def reflow(body, width, merge):
    """body: list of body-line strings ('' / '　' = separator) -> new line list.
    merge=True re-paragraphs runs of prose (tutorials); merge=False wraps each line
    in place (banners), both keeping bullets/arrows/numbers/blanks on their own line."""
    out, para = [], []

    def flush():
        if para:
            out.extend(codes.wrap_text(" ".join(x.strip() for x in para), width).split("\n"))
            para.clear()

    for t in body:
        if not t.strip():
            flush(); out.append("")
        elif merge and not _is_struct(t):
            para.append(t)
        else:
            flush()
            out.extend(codes.wrap_text(t.rstrip(), width).split("\n"))
    flush()
    while out and not out[-1].strip():
        out.pop()
    return out


def _iter_command_lists(data):
    """Every event command list in a file — CommonEvents/Troops (a list of events,
    each with a 'list' and/or 'pages') OR a Map (a dict with 'events' -> 'pages')."""
    if isinstance(data, list):
        for ev in data:
            if ev and isinstance(ev, dict):
                if isinstance(ev.get("list"), list):
                    yield ev["list"]
                for pg in (ev.get("pages") or []):
                    if pg and isinstance(pg.get("list"), list):
                        yield pg["list"]
    elif isinstance(data, dict):
        for ev in (data.get("events") or []):
            if ev and isinstance(ev, dict):
                for pg in (ev.get("pages") or []):
                    if pg and isinstance(pg.get("list"), list):
                        yield pg["list"]


def _iter_pages(L, ce_id, font_var):
    """Yield ({var: last_cmd_index}, font_cmd_index) per page in command list L —
    a run of Control-Variable string assignments ended by a Call-CommonEvent ce_id."""
    cur, font_idx = {}, None
    for i, c in enumerate(L):
        if not isinstance(c, dict):
            continue
        code, ps = c.get("code"), c.get("parameters") or []
        if code == 122 and len(ps) >= 5 and ps[2] == 0 and ps[3] == 4 and isinstance(ps[4], str):
            for v in range(ps[0], ps[1] + 1):
                cur[v] = i
        elif code == 122 and font_var and len(ps) >= 5 and ps[0] == font_var and ps[3] == 0:
            font_idx = i
        elif code == 117 and ps and ps[0] == ce_id:
            yield dict(cur), font_idx
            cur = {}                # keep font_idx: one font-var set controls every
                                    # following page until a new set replaces it


def _process_template(data, tpl):
    lo, hi, slots = tpl["lo"], tpl["hi"], tpl["hi"] - tpl["lo"] + 1
    changed = 0
    for L in _iter_command_lists(data):
        pages = []
        for varmap, font_idx in _iter_pages(L, tpl["ce"], tpl["font_var"]):
            cmds = {v: varmap[v] for v in range(lo, hi + 1) if v in varmap}
            if not cmds:
                continue
            body = [_unq(L[cmds[v]]["parameters"][4]) if v in cmds else ""
                    for v in range(lo, hi + 1)]
            if not any(any(ch.isascii() and ch.isalpha() for ch in line) for line in body):
                continue
            # A fit means NOTHING is dropped: the untruncated output is <= the slot
            # count AND every non-blank line lands in a WRITABLE slot (one that has a
            # Control-Variable command). Try the preferred flow, then the other,
            # stepping the font down — so a dense page shrinks its font, and a long
            # banner line that would need an unused slot is paragraph-merged instead.
            def fits(raw):
                return (len(raw) <= slots and
                        all((not raw[k].strip()) or ((lo + k) in cmds) for k in range(len(raw))))

            chosen, flowed = tpl["fonts"][-1], None
            done = False
            for merge in (tpl["merge"], not tpl["merge"]):
                for font in tpl["fonts"]:
                    raw = reflow(body, _width_cells(font, tpl["avail"]), merge)
                    chosen = font
                    flowed = (raw[:slots] + ["　"] * slots)[:slots]
                    if fits(raw):
                        done = True
                        break
                if done:
                    break
            # blank lines -> fullwidth space (the dev's separator). An EMPTY string in
            # \V[n] renders as "0", so never write '' to a slot.
            flowed = [x if x.strip() else "　" for x in flowed]
            pages.append((cmds, flowed, chosen, font_idx))
        if not pages:
            continue
        # Pages that share ONE font variable (a CE that sets var520 once, then calls the
        # template for several pages) must all display at the SMALLEST font any of them
        # needs — else a page wrapped for font 18 but shown at the shared 20 overflows.
        gmin = {}
        for _cmds, _flowed, chosen, font_idx in pages:
            if font_idx is not None:
                gmin[font_idx] = min(gmin.get(font_idx, chosen), chosen)
        for cmds, flowed, chosen, font_idx in pages:
            did = False
            for k, v in enumerate(range(lo, hi + 1)):
                if v in cmds:
                    nv = _requote(flowed[k])
                    if L[cmds[v]]["parameters"][4] != nv:
                        L[cmds[v]]["parameters"][4] = nv
                        did = True
            if tpl["font_var"] and font_idx is not None and gmin[font_idx] != tpl["fonts"][0]:
                if L[font_idx]["parameters"][4] != gmin[font_idx]:
                    L[font_idx]["parameters"][4] = gmin[font_idx]
                    did = True
            if did:
                changed += 1
    return changed


# CE50 各種族ステータス表示 — the species/unit detail screen. Body = THREE fixed groups
# with no spare slots between them: flavor (4502-4504), race trait (4505), stats blurb
# (4506-4507), drawn in the right-half (x=640 -> 640px) area. English overflows. Rather
# than one tiny global font we make the flavor/trait/stats font a PER-SPECIES variable
# \V[4520] and pick the LARGEST font (16 down to 11) at which every group still fits its
# slots — short species stay big, only wordy ones (or long shared race traits) shrink.
# The base-stats block + "Weakness: \V Critical: \V" line stay a uniform 38 (were 48;
# the English labels ran "Critical" off the right edge).
CE50_ID = 50
CE50_FONT_VAR = 4520
CE50_FONTS = [16, 15, 14, 13, 12, 11]
CE50_STAT_FONT = 38
CE50_AREA = 72           # display width in CELLS at font 18 (= longest JP line that fit)
CE50_GROUPS = [((4502, 4503, 4504), True), ((4505,), False), ((4506, 4507), True)]


def _ce50_width(font):
    return round(CE50_AREA * 18 / font) - 4


CE50_WEAK_FONT_VAR = 4521   # dynamic font for the "Weakness: .. Critical: .." line


def _weak_font_script(label_len):
    # font = largest (cap 38) at which "Weakness: <4518> Critical: <4517>" fits the
    # ~640px area: cells(F) = round(AREA*18/F)-4, so F = floor(AREA*18/(cells+4)).
    # cells = label_len + the two element strings (compound ones like "Fire/Wind" are
    # the overflow culprit). Floor 11 so it always fits.
    return ("$gameVariables.setValue(%d,Math.max(11,Math.min(%d,Math.floor(%d/("
            "%d+String($gameVariables.value(4518)).length"
            "+String($gameVariables.value(4517)).length+4)))));"
            % (CE50_WEAK_FONT_VAR, CE50_STAT_FONT, CE50_AREA * 18, label_len))


def _set_ce50_font(events):
    """In the CE50 template: point the flavor/trait/stats dTexts at the per-species
    font var \\V[4520], shrink the base-stats block 48 -> 38, and make the
    Weakness/Critical line a DYNAMIC font (\\V[4521]) so compound elements
    (e.g. "Fire/Wind") that ran "Critical" off the screen shrink to fit."""
    for ev in events if isinstance(events, list) else []:
        if not (ev and isinstance(ev, dict) and ev.get("id") == CE50_ID
                and isinstance(ev.get("list"), list)):
            continue
        L = ev["list"]
        label_len = None
        for c in L:
            ps = c.get("parameters") or []
            if not (c.get("code") == 357 and len(ps) > 3 and ps[1] == "dText"
                    and isinstance(ps[3], dict)):
                continue
            txt = ps[3].get("text", "")
            if "\\V[4517" in txt and "\\V[4518" in txt:        # the Weakness/Critical line
                ps[3]["fontSize"] = "\\V[%d]" % CE50_WEAK_FONT_VAR
                lab = re.sub(r"\\C\[\d+\]", "", txt)
                label_len = len(re.sub(r"\\V\[\d+(?:,\d+)?\]", "", lab))
            elif any("[%d" % v in txt for v in range(4502, 4508)):
                ps[3]["fontSize"] = "\\V[%d]" % CE50_FONT_VAR
            elif ps[3].get("fontSize") == "48":
                ps[3]["fontSize"] = str(CE50_STAT_FONT)
        # insert the weakness-font compute script once, at the top of CE50 (vars 4517/
        # 4518 are already set by the per-species caller before it calls CE50)
        if label_len is not None and not any(
                isinstance(c, dict) and c.get("code") in (355, 655)
                and (c.get("parameters") or [""])[0]
                and "setValue(%d," % CE50_WEAK_FONT_VAR in c["parameters"][0] for c in L):
            L.insert(0, {"code": 355, "indent": 0,
                         "parameters": [_weak_font_script(label_len)]})


def _reflow_ce50_species(data):
    changed = 0
    for L in _iter_command_lists(data):
        # collect each species (var run ended by a CE50 call) in this command list
        species, cur = [], {}
        for i, c in enumerate(L):
            if not isinstance(c, dict):
                continue
            code, ps = c.get("code"), c.get("parameters") or []
            if code == 122 and len(ps) >= 5 and ps[2] == 0 and ps[3] == 4 and 4502 <= ps[0] <= 4507:
                cur[ps[0]] = i
            elif code == 117 and ps and ps[0] == CE50_ID:
                if cur:
                    species.append((dict(cur), i, c.get("indent", 0)))
                cur = {}
        # bottom-up so the per-species font-var insert doesn't shift earlier indices
        for varmap, call_idx, indent in reversed(species):
            groups = []
            for vs, merge in CE50_GROUPS:
                cm = {v: varmap[v] for v in vs if v in varmap}
                body = [_unq(L[cm[v]]["parameters"][4]) if v in cm else "" for v in vs]
                groups.append((vs, merge, cm, body))
            if not any(any(ch.isascii() and ch.isalpha() for ch in line)
                       for _vs, _m, _cm, body in groups for line in body):
                continue
            # largest font where every group reflows within its slots (font 11 always fits)
            pick_font, pick = None, None
            for font in CE50_FONTS:
                w = _ce50_width(font)
                trial, ok = [], True
                for vs, merge, cm, body in groups:
                    raw = reflow(body, w, merge)
                    if len(raw) > len(vs):
                        ok = False
                        break
                    trial.append((cm, vs, (raw[:len(vs)] + ["　"] * len(vs))[:len(vs)]))
                if ok:
                    pick_font, pick = font, trial
                    break
            if pick is None:
                continue                              # never drop text
            for cm, vs, flowed in pick:
                for k, v in enumerate(vs):
                    if v in cm:
                        L[cm[v]]["parameters"][4] = _requote(flowed[k])
            L.insert(call_idx, {"code": 122, "indent": indent,
                                "parameters": [CE50_FONT_VAR, CE50_FONT_VAR, 0, 0, pick_font]})
            changed += 1
    return changed


# Unit-status screens CE1489-1493 (アクター00-04ユニットステ表示, shown for a bred unit):
# the 5 equip/ability NAME dTexts (bold + outline + \C[15], font 24) hold Armor/Weapon
# names that are far longer in English ("[Nullify] Physical-Element Weaken", 33c) and
# ran past their fixed boxes / into the right-side arrow art. A runtime-determined unit
# can't be sized at inject time, so each box is DYNAMIC: its dText font points at a
# per-slot var, and an inserted script picks (per displayed name) the largest font that
# still clears the arrow (area ~17.5 cells at font 24 -> floor(420/width), capped 24,
# floored 11). Each CE uses DIFFERENT equip vars (2545+, 2565+, … +20 per actor), so we
# read them from the dTexts and give each CE its own free font-var block (2646-2900 are
# free; 5 per CE). Short names stay big; only long ones shrink.
UNIT_STATUS_CES = {1489, 1490, 1491, 1492, 1493}
UNIT_FONT_BASE = 2646
_UNIT_VAR_RE = re.compile(r"\\V\[(\d+)\]")


def _unit_font_script(equip_vars, font_base):
    # JS cell width: ASCII / halfwidth-kana = 1, everything else (☆ 【】 kanji) = 2.
    return ("[%s].forEach(function(v,k){var s=String($gameVariables.value(v)),w=0,i,c;"
            "for(i=0;i<s.length;i++){c=s.charCodeAt(i);w+=(c<=127||(c>=65377&&c<=65439))?1:2;}"
            "$gameVariables.setValue(%d+k,Math.max(11,Math.min(24,"
            "Math.floor(420/Math.max(1,w)))));});"
            % (",".join(map(str, equip_vars)), font_base))


def _set_unit_equip_font(events):
    if not isinstance(events, list):
        return
    for ev in events:
        if not (ev and isinstance(ev, dict) and ev.get("id") in UNIT_STATUS_CES
                and isinstance(ev.get("list"), list)):
            continue
        L = ev["list"]
        font_base = UNIT_FONT_BASE + (ev["id"] - 1489) * 5
        if any(isinstance(c, dict) and c.get("code") in (355, 655) and (c.get("parameters") or [""])[0]
               and "setValue(%d+k" % font_base in c["parameters"][0] for c in L):
            continue                                   # already wired (idempotent)
        # the equip-name dTexts, in document order, with the var each displays
        equip_dt = []
        for i, c in enumerate(L):
            ps = c.get("parameters") or []
            if (c.get("code") == 357 and len(ps) > 3 and ps[1] == "dText"
                    and isinstance(ps[3], dict) and ps[3].get("fontSize") == "24"
                    and "\\C[15]\\V[" in ps[3].get("text", "")):
                m = _UNIT_VAR_RE.search(ps[3]["text"])
                if m:
                    equip_dt.append((i, int(m.group(1))))
        if len(equip_dt) != 5:
            continue
        equip_vars = [v for _i, v in equip_dt]
        # insert the font-compute script right after the LAST equip-name setValue
        insert_idx, indent = None, 0
        for i, c in enumerate(L):
            ps = c.get("parameters") or []
            if (c.get("code") in (355, 655) and ps and isinstance(ps[0], str)
                    and ("setValue(%d," % max(equip_vars)) in ps[0]):
                insert_idx, indent = i + 1, c.get("indent", 0)
        if insert_idx is None:
            continue
        for k, (idx, _v) in enumerate(equip_dt):           # point each dText at its font var
            L[idx]["parameters"][3]["fontSize"] = "\\V[%d]" % (font_base + k)
        L.insert(insert_idx, {"code": 355, "indent": indent,
                              "parameters": [_unit_font_script(equip_vars, font_base)]})


def _set_recollection_font(events):
    """The 回想 (recollection) unlock grid (CE995) draws 19 rows in ONE DTextPicture at
    font 16, centred at y=280. DTextPicture renders larger than the nominal size, so the
    taller English race-tag rows push the grid past the screen and the top row clips.
    Drop the grid font 16 -> 14 so the whole thing fits (tune RECOLLECTION_FONT if it
    needs to be smaller/larger)."""
    for ev in events if isinstance(events, list) else []:
        if not (ev and isinstance(ev, dict) and isinstance(ev.get("list"), list)):
            continue
        for c in ev["list"]:
            ps = c.get("parameters") or []
            if (c.get("code") == 357 and len(ps) > 3 and ps[1] == "dText"
                    and isinstance(ps[3], dict) and "\\V[701]" in ps[3].get("text", "")
                    and ps[3].get("fontSize") == "16"):
                ps[3]["fontSize"] = str(RECOLLECTION_FONT)


def apply_reflow(data):
    """Re-flow every help page (CE100), banner (CE36), species screen (CE50), shrink the
    unit-status equip names (CE1489-1493) and the recollection grid (CE995) reachable
    from a file's event command lists (CommonEvents list OR Map dict). Returns count."""
    _set_ce50_font(data)
    _set_unit_equip_font(data)
    _set_recollection_font(data)
    return (sum(_process_template(data, tpl) for tpl in TEMPLATES)
            + _reflow_ce50_species(data))
