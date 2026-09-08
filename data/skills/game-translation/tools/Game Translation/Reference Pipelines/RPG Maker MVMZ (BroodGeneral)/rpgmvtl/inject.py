#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
inject.py — write translations from the store back into the game data.

Always rebuilds from the ORIGINAL data (read fresh), so injection is
deterministic and idempotent: re-running reproduces byte-identical output and
never double-applies wrapping or name substitution.

By default it copies the whole data dir to an output dir and patches the copy
(a clean drop-in replacement for www/data). `--in-place` patches the real data
after taking a timestamped backup.
"""

import os
import re
import glob
import json
import shutil

from . import codes, store, patterns, helpwrap
from .config import Config

C_TEXT, C_SCROLL = 401, 405

# width per unit kind (visible chars); None = no wrap
_WRAP = {"text": "width", "desc": "list_width", "profile": "list_width",
         "message": "width"}

_NAME_WIN_RE = re.compile(r"(\\+[knKN][wW])\[([^\]]*)\]")


def _romanize_name_windows(text: str, glossary) -> str:
    """Replace \\kw[jp]/\\nw[jp] name-window contents with the glossary name."""
    if not isinstance(text, str) or "[" not in text:
        return text

    def repl(m):
        return f"{m.group(1)}[{store.name_lookup(glossary, m.group(2))}]"

    return _NAME_WIN_RE.sub(repl, text)


def _wrap_for(kind, text, cfg: Config):
    if not cfg.fix_wrap:
        return text
    attr = _WRAP.get(kind)
    if not attr:
        return text
    return codes.wrap_text(text, getattr(cfg, attr))


def _finalize_scalar(unit, glossary, cfg):
    """Compute the final string for a scalar (non-command-list) unit."""
    text = codes.unmask_codes(unit["tl"], unit.get("codes", {}))
    text = _strip_jp_ruby(text)
    text = codes.strip_residual_kana(text)
    text = codes.normalize_quotes(text)
    text = _space_codes(text)
    text = _wrap_for(unit["kind"], text, cfg)
    return text


# --------------------------------------------------------------------------
# command-list rebuild (text blocks + choices + name-window romanization)
# --------------------------------------------------------------------------
def _net_enlarge(text):
    """net \\{ (makeFontBigger) minus \\} — >0 means the box ENDS still enlarged
    (used to restore the font state across continuation boxes)."""
    return text.count("\\{") - text.count("\\}")


# RPG Maker MZ: \{ adds +12px to the 26px base font (cap 96); \} subtracts.
_FONT_BASE, _FONT_STEP, _FONT_MAX = 26, 12, 96


def _peak_enlarge(text):
    """Max simultaneous \\{ nesting depth, INCLUDING balanced \\{..\\} — i.e. the
    largest font size the line actually reaches. (net-enlarge misses these.)"""
    depth = mx = 0
    i = 0
    while i < len(text):
        two = text[i:i + 2]
        if two == "\\{":
            depth += 1
            mx = max(mx, depth)
            i += 2
        elif two == "\\}":
            depth = max(0, depth - 1)
            i += 2
        else:
            i += 1
    return mx


# capture the escape LETTER too, so the restore re-emits in the source's own case
# (MZ data tends to use \C, MV \c; both render identically but we mirror the input
# so the tool stays engine-agnostic).
_COLOR_RE = re.compile(r"\\([cC])\[(\d+)\]")
_OUTLINE_RE = re.compile(r"\\(o[wW]|O[wW])\[(\d+)\]")


def _active_format(text):
    """Codes that RESTORE the font state still open at the end of `text` — RPG
    Maker resets size/colour/outline at the start of every message box, so when we
    split a long translation into continuation boxes any \\{ (bigger), \\c[n]
    (colour) or \\ow[n] (outline) left open must be re-stated on the next box, and
    kept open until the point it was originally closed. Each code is re-emitted in
    the SAME case it appeared in the source (engine-agnostic)."""
    out = ""
    # size: each \{ is +1 level, \} is -1; the net still-open count carries over.
    out += "\\{" * max(0, text.count("\\{") - text.count("\\}"))
    # colour / outline are ABSOLUTE (last value wins); a trailing [0] means reset.
    cols = _COLOR_RE.findall(text)              # [(letter, num), ...]
    if cols and cols[-1][1] != "0":
        out += "\\" + cols[-1][0] + "[" + cols[-1][1] + "]"
    ows = _OUTLINE_RE.findall(text)
    if ows and ows[-1][1] != "0":
        out += "\\" + ows[-1][0] + "[" + ows[-1][1] + "]"
    return out


# inline codes that EXPAND TO A WORD at runtime: \N[n] actor name, \P[n] party
# member, \V[n] variable. In JP they sit flush against the next char; in English
# that glues the (player-chosen) name to the next word ("Ore-kunWhen"). Insert a
# space when such a code directly abuts an ASCII letter (never before punctuation,
# so possessives like \N[4]'s are left alone).
_NAME_CODE = r"\\[NPVnpv]\[\d+\]"
_SPACE_AFTER = re.compile(r"(" + _NAME_CODE + r")(?=[A-Za-z])")
_SPACE_BEFORE = re.compile(r"(?<=[A-Za-z])(" + _NAME_CODE + r")")


def _space_codes(text: str) -> str:
    if "[" not in text:
        return text
    text = _SPACE_AFTER.sub(r"\1 ", text)
    text = _SPACE_BEFORE.sub(r" \1", text)
    return text


# ruby \r[base,reading] (furigana) whose BASE is Japanese renders the kanji
# untranslated (e.g. \r[射精,で] = 射精 with で over it). The surrounding text was
# already translated around the masked code, so the JP ruby is redundant — drop it.
_RUBY_RE = re.compile(r"\\r\[[^\]]*[぀-ヿ一-鿿][^\]]*\]")


def _strip_jp_ruby(text: str) -> str:
    return _RUBY_RE.sub("", text) if "\\r[" in text else text


# DTextPicture text is either CENTERED full-screen narration (origin=1 on its
# Show-Picture) — which overflows once translated and must be re-wrapped — or a
# position-anchored UI label (origin=0) that must keep its exact layout. We read
# the paired Show-Picture (231) from the live data to tell them apart.
_LEGEND_RE = re.compile(r"\[[→←↑↓]\]|決定[:：]|キャンセル[:：]|ルート|スワイプ")


def _max_line_cells(s):
    return max((codes._visible_len(ln) for ln in (s or "").split("\n")), default=0)


def _ptext_wrap_width(data, ptr, raw, cfg):
    """Width to re-wrap a DTextPicture text unit, or None to leave it as-is.
    Wraps only CENTERED narration; never the anchored UI labels."""
    try:
        list_ptr = list(ptr[:-4]); idx = ptr[-4]
        lst = store.ptr_get(data, list_ptr)
    except Exception:
        return None
    origin = None
    for j in range(idx + 1, min(idx + 60, len(lst))):
        c = lst[j]
        if not isinstance(c, dict):
            continue
        code = c.get("code")
        if code == 357 and (c.get("parameters") or [""])[0] == "triacontane/DTextPicture":
            break
        if code == 231:                       # Show Picture: parameters[2] = origin
            p = c.get("parameters") or []
            origin = p[2] if len(p) > 2 else None
            break
    if origin == 0:
        return None                           # top-left anchored label — keep layout
    if origin != 1:
        # no paired Show-Picture nearby: reflow only clear long prose narration
        if _LEGEND_RE.search(raw or "") or "\\V[" in (raw or "") or _max_line_cells(raw) < 36:
            return None
    return getattr(cfg, "ptext_width", 72)


def _preceding_face(lst, idx):
    """True if the Show-Text (101) header just before the 401 block at `idx`
    carries a face portrait (parameters[0]) — those narrow the text area, so the
    block wraps to the narrower face_width."""
    for k in range(idx - 1, max(-1, idx - 6), -1):
        c = lst[k]
        if not isinstance(c, dict):
            continue
        if c.get("code") == 101:
            p = c.get("parameters") or []
            return bool(len(p) >= 1 and isinstance(p[0], str) and p[0].strip())
        if c.get("code") not in (401, 405):
            break
    return False


def _block_text(unit, glossary, cfg, has_face=False):
    body = codes.unmask_codes(unit["tl"], unit.get("codes", {}))
    body = _strip_jp_ruby(body)
    body = codes.strip_residual_kana(body)
    body = codes.normalize_quotes(body)
    body = _space_codes(body)
    max_rows = getattr(cfg, "max_rows", 3) or 3
    # Readout lines with several \V[] variables (e.g. the post-breeding Service-EXP
    # summary) render at a width the wrapper can't predict — the variable VALUES aren't
    # in the source text, so auto-wrap mis-measures and the line runs off-screen. Leave
    # such lines hand-formatted in the translation (its \n breaks are sized for the
    # widest values) instead of re-wrapping them.
    if cfg.fix_wrap and body.count("\\V[") < 3:
        peak = _peak_enlarge(body)
        if peak > 0:
            # \{-enlarged text renders WIDER and TALLER; scale the wrap width and
            # the row budget down by the peak font size so it can't overflow the
            # box (handles balanced \{..\} that net-enlarge would miss).
            fs = min(_FONT_MAX, _FONT_BASE + peak * _FONT_STEP)
            width = max(16, round(cfg.width * _FONT_BASE / fs))
            max_rows = max(1, round(max_rows * _FONT_BASE / fs))
        elif has_face:
            width = getattr(cfg, "face_width", cfg.width)
        else:
            width = cfg.width
        body = codes.wrap_text(body, width)
    prefix = unit.get("prefix", "")
    if prefix:
        name_en = store.name_lookup(glossary, unit.get("speaker", ""))
        prefix = prefix.replace("{name}", name_en)
    return prefix, body, max_rows


def _rebuild_list(lst, blocks, choices, glossary, cfg, stats):
    """Return a new command list with text blocks collapsed/translated,
    choices replaced, and name windows romanized.

    blocks:  {start_index: unit}
    choices: {cmd_index: {choice_index: unit}}
    """
    out = []
    i = 0
    n = len(lst)
    while i < n:
        cmd = lst[i]
        code = cmd.get("code") if isinstance(cmd, dict) else None

        # MZ native name box (Show Text header, code 101): translate the speaker
        # name stored in parameters[4] via the glossary, so the name box matches
        # the in-prose mentions. No-op when the name isn't in the glossary.
        if code == 101 and isinstance(cmd, dict):
            p = cmd.get("parameters") or []
            if len(p) >= 5 and isinstance(p[4], str) and p[4].strip():
                c = dict(cmd)
                c["parameters"] = list(p)
                c["parameters"][4] = store.name_lookup(glossary, p[4].strip())
                out.append(c)
                i += 1
                continue

        if i in blocks:
            unit = blocks[i]
            count = unit["block"]["count"]
            run_code = unit["block"].get("code", code)
            # safety: verify the original run still matches what we extracted
            cur = "\n".join((lst[j].get("parameters") or [""])[0]
                            for j in range(i, min(i + count, n)))
            if cur != unit.get("raw"):
                stats["mismatch"] += 1
                # leave the original run untouched (just romanize names)
                for j in range(i, min(i + count, n)):
                    c = dict(lst[j])
                    if c.get("parameters"):
                        c["parameters"] = list(c["parameters"])
                        c["parameters"][0] = _romanize_name_windows(c["parameters"][0], glossary)
                    out.append(c)
                i += count
                continue

            if not unit.get("tl", "").strip():
                # untranslated: keep original lines (romanize names only)
                for j in range(i, min(i + count, n)):
                    c = dict(lst[j])
                    if c.get("parameters"):
                        c["parameters"] = list(c["parameters"])
                        c["parameters"][0] = _romanize_name_windows(c["parameters"][0], glossary)
                    out.append(c)
                i += count
                continue

            prefix, body, max_rows = _block_text(unit, glossary, cfg, _preceding_face(lst, i))
            template = dict(lst[i])
            template["code"] = run_code
            if run_code == C_SCROLL:
                # scrolling text: one command per visible line
                lines = [ln for ln in body.split("\n")] or [""]
                if prefix:
                    lines[0] = prefix + lines[0]
                for k, ln in enumerate(lines):
                    c = dict(template)
                    c["parameters"] = [ln]
                    out.append(c)
            else:
                # normal message: split into <=max_rows-row boxes so long
                # translations continue into a new message box rather than
                # overflowing the window vertically.
                lines = body.split("\n")
                header = None
                if len(lines) > max_rows:
                    for c in reversed(out):       # the Show Text (101) header
                        if isinstance(c, dict) and c.get("code") == 101:
                            header = c
                            break
                if len(lines) <= max_rows or header is None:
                    template = dict(template)
                    template["parameters"] = [prefix + body]
                    out.append(template)
                else:
                    for s in range(0, len(lines), max_rows):
                        if s > 0:                 # clone header for each continuation box
                            out.append(dict(header))
                        chunk = "\n".join(lines[s:s + max_rows])
                        # re-apply the font state (\{ size, \c colour, \ow outline)
                        # carried over from the earlier boxes, then the name window
                        restore = _active_format("\n".join(lines[:s])) if s else ""
                        txt = prefix + restore + chunk
                        c = dict(template)
                        c["parameters"] = [txt]
                        out.append(c)
                    stats["split"] = stats.get("split", 0) + 1
            stats["text"] += 1
            i += count
            continue

        # choice command: replace translated choice strings in-place
        if i in choices:
            c = dict(cmd)
            params = [list(p) if isinstance(p, list) else p for p in (c.get("parameters") or [])]
            if params and isinstance(params[0], list):
                for ci, unit in choices[i].items():
                    if not unit.get("tl", "").strip():
                        continue
                    cur = params[0][ci] if ci < len(params[0]) else None
                    if cur != unit.get("raw"):
                        stats["mismatch"] += 1
                        continue
                    txt = codes.unmask_codes(unit["tl"], unit.get("codes", {}))
                    params[0][ci] = txt
                    stats["choice"] += 1
            c["parameters"] = params
            out.append(c)
            i += 1
            continue

        # any other text line: romanize name windows (handles untranslated runs)
        if code in (C_TEXT, C_SCROLL) and isinstance(cmd, dict) and cmd.get("parameters"):
            c = dict(cmd)
            c["parameters"] = list(c["parameters"])
            c["parameters"][0] = _romanize_name_windows(c["parameters"][0], glossary)
            out.append(c)
            i += 1
            continue

        out.append(cmd)
        i += 1
    return out


# --------------------------------------------------------------------------
def _apply_doc(data, doc, glossary, cfg, stats):
    """Apply one store doc's units to a parsed data document (in place)."""
    # Partition units: command-list units (text/choice) vs scalar units.
    blocks_by_list = {}   # tuple(ptr) -> {start: unit}
    choices_by_list = {}  # tuple(ptr_to_list) -> {cmd_index: {choice_index: unit}}
    scalars = []

    for u in doc.get("units", []):
        kind = u["kind"]
        if kind == "text":
            key = tuple(u["ptr"])
            blocks_by_list.setdefault(key, {})[u["block"]["start"]] = u
        elif kind == "choice":
            # ptr = list_ptr + [cmd_index, "parameters", 0, choice_index]
            list_ptr = tuple(u["ptr"][:-4])
            cmd_index = u["ptr"][-4]
            choice_index = u["ptr"][-1]
            choices_by_list.setdefault(list_ptr, {}).setdefault(cmd_index, {})[choice_index] = u
        elif kind in ("label", "scripttext", "vartext"):
            continue                     # substring units — handled by _apply_specials
        else:
            scalars.append(u)

    # 1) scalar fields (safe: pointers into stable data structures)
    for u in scalars:
        if not u.get("tl", "").strip():
            continue
        try:
            cur = store.ptr_get(data, u["ptr"])
        except Exception:
            stats["mismatch"] += 1
            continue
        if cur != u.get("raw"):
            stats["mismatch"] += 1
            continue
        final = _finalize_scalar(u, glossary, cfg)
        if u["kind"] == "ptext" and cfg.fix_wrap:
            w = _ptext_wrap_width(data, u["ptr"], u.get("raw", ""), cfg)
            if w:
                final = codes.wrap_text(final, w)
        store.ptr_set(data, u["ptr"], final)
        stats[u["kind"]] = stats.get(u["kind"], 0) + 1

    # 2) command lists (rebuild once per list)
    all_list_keys = set(blocks_by_list) | set(choices_by_list)
    for key in all_list_keys:
        ptr = list(key)
        try:
            lst = store.ptr_get(data, ptr)
        except Exception:
            stats["mismatch"] += 1
            continue
        new_lst = _rebuild_list(lst, blocks_by_list.get(key, {}),
                                choices_by_list.get(key, {}), glossary, cfg, stats)
        store.ptr_set(data, ptr, new_lst)

    # 3) auto-extracted specials: event-note labels (<LB:..>) + script text (addText)
    _apply_specials(data, doc, stats, cfg)


# Final safety net: convert corner-bracket quotes (「」『』) → straight quotes in
# player-facing database fields that had NO Japanese to translate (e.g. a skill-
# use message template '%1「[%2]…！」'), so none slip through untranslated.
_DB_QUOTE_FIELDS = ("name", "description", "nickname", "profile",
                    "message1", "message2", "message3", "message4")


def _normalize_db_quotes(data):
    if not isinstance(data, list):
        return
    for e in data:
        if isinstance(e, dict):
            for f in _DB_QUOTE_FIELDS:
                v = e.get(f)
                if isinstance(v, str) and ("「" in v or "」" in v or "『" in v or "』" in v):
                    e[f] = codes.normalize_quotes(v)


def _romanize_actor_names(data, glossary, stats):
    """Rewrite each Actors.json `name` from the glossary, so battle UI / status
    windows / action-log messages (%1 = actor name) and \\N[id] all show English.
    (Character names live in the glossary, not as translatable units.)"""
    if not isinstance(data, list):
        return
    for e in data:
        if isinstance(e, dict) and isinstance(e.get("name"), str) and e["name"].strip():
            en = store.name_lookup(glossary, e["name"])
            if en and en != e["name"]:
                e["name"] = en
                stats["actorname"] = stats.get("actorname", 0) + 1


# Event-note display labels (<LB:..>) and code-355 script display text
# (addText('…')) are now AUTO-EXTRACTED as 'label' / 'scripttext' store units, so
# their translations come from the store like any other text. _apply_specials()
# below builds the JP->EN map from those units and rewrites them via patterns.py.
def _apply_specials(data, doc, stats, cfg=None):
    labels, names, scripts, varmap = {}, {}, {}, {}
    for u in doc.get("units", []):
        if not u.get("tl", "").strip():
            continue
        kind = u["kind"]
        if kind not in ("label", "scripttext", "vartext"):
            continue
        jp = codes.unmask_codes(u["src"], u.get("codes", {}))
        en = codes.unmask_codes(u["tl"], u.get("codes", {}))
        if kind == "scripttext":
            scripts[jp] = en
        elif kind == "vartext":
            varmap[jp] = en
        elif u.get("lb_kind") == "name":   # bare <LB> -> event-name label
            names[jp] = en
        else:
            labels[jp] = en
    if labels:
        stats["label"] = stats.get("label", 0) + patterns.apply_note_labels(data, labels)
    if names:
        stats["label"] = stats.get("label", 0) + patterns.apply_name_labels(data, names)
    if scripts:
        stats["scripttext"] = stats.get("scripttext", 0) + patterns.apply_script_text(data, scripts)
    if varmap:
        stats["vartext"] = stats.get("vartext", 0) + patterns.apply_var_text(
            data, varmap, getattr(cfg, "vartext_skip_vars", ()))


def _read(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def _write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def inject_store(data_dir, store_dir, out_dir, cfg: Config, in_place=False):
    """Apply the store to the game data. Returns (per-file stats, totals)."""
    glossary = store.load_glossary(store_dir)
    docs = store.load_docs(store_dir)
    by_source = {}
    for _p, doc in docs:
        src = doc.get("meta", {}).get("source_file")
        if src:
            by_source[src] = doc

    if in_place:
        target_dir = data_dir
        _backup(data_dir)
    else:
        target_dir = out_dir
        _mirror(data_dir, out_dir)

    totals = {}
    per_file = []
    for src, doc in sorted(by_source.items()):
        path = os.path.join(target_dir, src)
        if not os.path.exists(path):
            per_file.append((src, {"error": "source missing"}))
            continue
        data = _read(path)
        stats = {"text": 0, "choice": 0, "mismatch": 0}
        _apply_doc(data, doc, glossary, cfg, stats)   # incl. labels + script text
        if src == "Actors.json":
            _romanize_actor_names(data, glossary, stats)
        if getattr(cfg, "help_reflow", False):         # CE100 tutorials + CE36 banners
            n = helpwrap.apply_reflow(data)            # (callers live in CommonEvents AND maps)
            if n:
                stats["helpreflow"] = stats.get("helpreflow", 0) + n
        _normalize_db_quotes(data)
        _write(path, data)
        per_file.append((src, stats))
        for k, v in stats.items():
            totals[k] = totals.get(k, 0) + v
    return per_file, totals, target_dir


def _backup(data_dir):
    import time
    ts = time.strftime("%Y%m%d_%H%M%S")
    dst = data_dir.rstrip("/\\") + "_backup_" + ts
    shutil.copytree(data_dir, dst)
    return dst


def _mirror(data_dir, out_dir):
    """Copy the entire data dir to out_dir (fresh), so out is a complete set."""
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    shutil.copytree(data_dir, out_dir)
