#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
inject.py — write the translated store back into the SRPG patch + js_strings.json.

Targets:
  * patch/*.json   — whole-field substitution by (kind, original-JP). Dialogue and
    info text get control codes restored and are wrapped to the message-box width;
    names use the glossary first (character names), then the deduped name units.
    customParameters JS literals get only their quoted JP substrings replaced.
  * js_strings.json — the plugin/engine strings: each entry's "translation" is
    filled from the matching plugin unit (then run js_text_tool.py apply).

Idempotent: always rebuilds substitutions from the original JP, so re-running
never double-translates.
"""

import os
import re
import json
import glob

from . import codes, store
from .extract import KEY_KIND, SKIP_KEYS, _SQ_RE, JP, plugin_translatable, plugin_blacklist

DEFAULT_WIDTH = 54   # message-box wrap width (monospace cells); tune per game.
# The character/word dictionary ("Manual") draws a right-side illustration over
# the ~560px text column (CharacterScreen draws it at contentX+offset+250 ≈ x720
# at 1280). Full-width 54-cell lines run under that art and get clipped
# ("...the player, swor[n]"), so dictionary page text wraps narrower to clear it.
PAGES_WIDTH = 44

# The shop/menu-NPC greeting cluster (info_misc:1056-1157) draws in a NARROW,
# 2-LINE face box (445px wide, 104px tall ≈ 2 lines) beside the keeper portrait,
# NOT the wide ~1280px map dialogue box. The message is shown with \at[1]
# (auto/non-blocking), so it must fit the box in ≤2 lines — the JP author wrote
# every greeting as exactly 2 short lines. The global 54-cell width never wraps
# these (overflow into the Buy/Sell panel); a too-tight width over-wraps to 3+
# lines which clip/auto-advance before the player can read them. Wrap at ~32
# cells (the box holds ~32 ASCII chars/line) and skip page-align. Greetings whose
# EN is too long for 2 lines at this width are shortened by hand in tl/.
SHOP_BOX_WIDTH = 32
SHOP_NARROW_IDS = set(range(1056, 1158))   # inclusive 1056..1157


def _restore(tl, code_map, wrap=0, page_align=False, page_pack=False):
    """Restore masked codes + cosmetic cleanup; optionally wrap dialogue."""
    t = codes.normalize_quotes(tl)
    t = codes.strip_residual_kana(t)
    t = codes.unmask_codes(t, code_map)
    if wrap and wrap > 0:
        t = _reflow(t, wrap)
        if page_align:
            t = _page_align(t, MESSAGE_PAGE_LINES)
        elif page_pack:
            t = _page_pack(t, INFO_PAGE_ROWS)
    return t


# The event message box clears every MESSAGE_PAGE_LINES lines, and each \vo voice
# fires when its page opens. The JP author sized every speaker turn to a multiple
# of this so a 【Name】 always tops its page with its dialogue, and used blank lines
# as deliberate pauses that landed at a page bottom. English line-merging is shorter,
# which desyncs both (the next 【Name】 creeps up, and a pause floats into mid-screen).
# _page_align rebuilds the page structure: each "segment" — a run of content that
# should begin on a fresh page — starts at a speaker header (【…】) OR after a blank
# line (a pause). Every segment but the last is padded to a whole number of pages,
# so the next 【Name】/pause lands at the top of a new page instead of mid-screen.
MESSAGE_PAGE_LINES = 3

# A speaker header tops its own page. The JP uses 【Name】; the EN translation
# renders these as a standalone "Name:" line instead (often after a \vo[...] voice
# code that must stay attached so the voice fires when the page opens). Both must
# be treated as page-segment boundaries, or consecutive speakers pile into one box
# ("Name: ... Name: ... Name: ..." all visible at once). The colon form is matched
# conservatively — a short line whose only content (after stripping control codes)
# is a name ending in ":" with no sentence punctuation — which has zero false
# positives across the script.
_CTRLCODE = re.compile(r"\\[A-Za-z]+\[[^\]]*\]")


def _is_speaker_header(line):
    if "【" in line or "】" in line:
        return True
    s = _CTRLCODE.sub("", line).strip()       # drop \vo[...]/\C[..] etc.
    if not (s.endswith(":") and len(s) <= 30 and s[:1] not in "\"'「『“‘"):
        return False
    name = s[:-1].strip()
    if not name or re.search(r"[.!?。！？]", name):
        return False
    # Real speaker headers are Title-Case names ("Balam Grang", "Knight Commander",
    # "Prototype Enhanced Slave"). Reject sentence fragments that merely end in ":"
    # ("...spoke up:", "...think to themselves:") — any lowercase-initial word means
    # it's prose, not a name.
    for w in re.split(r"[ \-]+", name):
        if w and w[0].isalpha() and not w[0].isupper():
            return False
    return True


# The InfoWindow (subquest briefings, etc.) paginates at INFO_PAGE_ROWS lines and
# the player advances with the down arrow. Its page break falls wherever row N+1
# lands, which after English reflow can split a sentence across pages (the box
# visually "ends" mid-line, e.g. "...If such people"). _page_pack greedily packs
# whole blank-line-delimited paragraphs into pages of <=n rows, padding a page to
# its bottom when the next paragraph wouldn't fit, so page breaks land at
# paragraph gaps instead of mid-sentence. A lone paragraph longer than n is left
# for the engine to break (rare for these briefings).
INFO_PAGE_ROWS = 15


def _page_pack(text, n):
    paras, cur = [], []
    for ln in text.split("\n"):
        if ln.strip() == "":
            if cur:
                paras.append(cur)
                cur = []
        else:
            cur.append(ln)
    if cur:
        paras.append(cur)
    if len(paras) < 2:
        return text
    out, row = [], 0
    for p in paras:
        if row > 0 and row + 1 + len(p) > n:   # +1 for the paragraph gap
            out.extend([""] * (n - row))       # pad to page bottom
            row = 0
        if row > 0:
            out.append("")
            row += 1
        out.extend(p)
        row += len(p)
    return "\n".join(out)


def _page_align(text, n):
    segments, cur = [], []
    for line in text.split("\n"):
        if _is_speaker_header(line):          # speaker header -> new page-segment
            if cur:
                segments.append(cur)
            cur = [line]
        elif not line.strip():               # pause -> end segment, drop the blank
            if cur:
                segments.append(cur)
                cur = []
        else:
            cur.append(line)
    if cur:
        segments.append(cur)
    if len(segments) < 2:
        return text                          # single block: nothing to page-align
    out = []
    for j, seg in enumerate(segments):
        out.extend(seg)
        if j < len(segments) - 1:            # pad every segment but the last to a page
            out.extend([""] * ((-len(seg)) % n))
    return "\n".join(out)


# Keep these glued to the following capitalized name word, and numbers to their
# unit, so a line wrap never separates them (non-breaking space, kinsoku-style).
_TITLE = (r"(?:Lady|Lord|Sir|Dame|Princess|Prince|King|Queen|Empress|Emperor|"
          r"Madam|Master|Mistress|Captain|Commander|General|Colonel|Major|"
          r"Lieutenant|Sergeant|Sister|Brother|Father|Mother|Saint|Duke|Duchess|"
          r"St\.|Mr\.|Mrs\.|Ms\.|Dr\.|Prof\.)")
_UNIT = r"(?:turns?|HP|MP|SP|TP|EXP|Lv|Lvl|levels?|gold|pts?|points?|times?|days?|%)"
# Short function words that read badly when stranded at a line end — glue each to
# the word that follows so the article/preposition/conjunction travels with its
# phrase (and breaks fall at natural phrase starts instead).
_LEAD = (r"a|an|the|to|of|in|on|at|by|for|as|into|onto|from|with|and|or|but|nor|"
         r"my|your|his|her|its|our|their|I")
_BIND_TITLE = re.compile(r"(\b" + _TITLE + r") +(?=[A-Z])")
_BIND_UNIT = re.compile(r"(\d+) +(?=" + _UNIT + r"\b)", re.IGNORECASE)
_BIND_LEAD = re.compile(r"(?<![\w'])(" + _LEAD + r") +(?=[\w'\"⟦])", re.IGNORECASE)


def _bind_units(s):
    s = _BIND_TITLE.sub(lambda m: m.group(1) + "\x00", s)
    s = _BIND_UNIT.sub(lambda m: m.group(1) + "\x00", s)
    s = _BIND_LEAD.sub(lambda m: m.group(1) + "\x00", s)
    return s


def _fix_widow(wrapped, width):
    """Widow control: if a paragraph's last line is a lone short word, pull the
    previous word down so it doesn't end on a stub ("...sink into the\\nlight?" ->
    "...sink into\\nthe light?"). Only acts when the merged last line still fits,
    and splits on real spaces so a bound unit (General\\x00Balam) is never broken."""
    lines = wrapped.split("\n")
    last = lines[-1].strip() if lines else ""
    if len(lines) >= 2 and last and " " not in last \
            and codes._visible_len(last) <= max(12, width // 4):
        prev = lines[-2].split(" ")
        if len(prev) >= 2:
            cand = prev[-1] + " " + lines[-1]
            if codes._visible_len(cand) <= width:
                lines[-2] = " ".join(prev[:-1])
                lines[-1] = cand
    return "\n".join(lines)


def _reflow(text, width):
    """Greedy-reflow each prose block so every line fills to `width` before it
    breaks — the translation's own soft line-breaks are merged away, which kills
    orphan tail-words mid-message ("...H-scene\\nvoices,\\nplease set..." ->
    "...H-scene voices, please set...").  Hard breaks are kept ONLY where they
    carry structure: a blank line (paragraph break) and a speaker header line
    (contains 【…】), so named H-scene dialogue keeps each 【Name】 on its own line."""
    out, buf = [], []

    def flush():
        if buf:
            # Bind logical units so a wrap can't strand a title from its name
            # ("General\nBalam") or a number from its unit ("3\nturns") — the
            # "keep linguistic units together" rule from subtitle/typography
            # style guides. _bind_units swaps the protected space for a sentinel
            # that wrap_text treats as part of the token; we restore it after.
            wrapped = codes.wrap_text(_bind_units(" ".join(buf)), width)
            wrapped = _fix_widow(wrapped, width)   # before unbinding, so a bound
            out.append(wrapped.replace("\x00", " "))  # "General Balam" can't be split
            buf.clear()

    for line in text.split("\n"):
        if not line.strip():
            flush()
            out.append("")
        elif _is_speaker_header(line):       # speaker header (【…】 or "Name:") -> own line
            flush()
            out.append(line)
        else:
            buf.append(line.strip())
    flush()
    return "\n".join(out)


def _build_maps(store_dir, width):
    """Return (by_kind, name_map, plugin_map).
       by_kind[(kind, raw)] = restored EN ;  name_map[jp] = EN (glossary chars)."""
    docs = store.load_docs(store_dir)
    glossary = store.load_glossary(store_dir)
    by_kind = {}
    plugin_map = {}
    for _p, doc in docs:
        for u in doc["units"]:
            tl = u.get("tl", "")
            if not tl.strip():
                continue
            kind = u["kind"]
            page_align = (kind == "text")
            # 'info' = InfoWindow briefings (subquest text etc.); pack paragraphs
            # into 15-row pages so page breaks land at paragraph gaps, not
            # mid-sentence (the box paginates with the down arrow).
            page_pack = (kind == "info")
            if kind == "pages":
                wrap = PAGES_WIDTH
            elif kind in ("text", "info"):
                wrap = width
                # Narrow shop-keeper box: wrap tight and don't page-align/pack.
                uid = u.get("id", "")
                if uid.startswith("info_misc:"):
                    try:
                        n = int(uid.split(":", 1)[1])
                    except ValueError:
                        n = -1
                    if n in SHOP_NARROW_IDS:
                        wrap = SHOP_BOX_WIDTH
                        page_align = False
                        page_pack = False
            else:
                wrap = 0
            en = _restore(tl, u.get("codes", {}), wrap,
                          page_align=page_align, page_pack=page_pack)
            if kind == "plugin":
                plugin_map[u["raw"]] = en
            else:
                by_kind[(kind, u["raw"])] = en
    name_map = {jp: store.name_en(v) for jp, v in glossary.get("names", {}).items()
                if store.name_en(v)}
    return by_kind, name_map, plugin_map


def inject_patch(patch_dir, store_dir, width=DEFAULT_WIDTH, in_place=True, out_dir=None):
    by_kind, name_map, _plugin = _build_maps(store_dir, width)
    target = patch_dir if in_place else (out_dir or patch_dir + "_translated")
    stats = {"files": 0, "fields": 0, "names_glossary": 0, "customparam_subs": 0, "skipped_no_tl": 0}

    for path in sorted(glob.glob(os.path.join(patch_dir, "**", "*.json"), recursive=True)):
        rel = os.path.relpath(path, patch_dir).replace("\\", "/")
        try:
            data = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        changed = [False]

        def repl(node, key=None):
            if isinstance(node, dict):
                return {k: repl(v, k) for k, v in node.items()}
            if isinstance(node, list):
                return [repl(v, key) for v in node]
            if not (isinstance(node, str) and node and JP.search(node)):
                return node
            if key in SKIP_KEYS:
                return node
            # customParameters: substitute only quoted JP substrings (handled
            # before the KEY_KIND gate, since it's not a whole-field text key)
            if key == "customParameters":
                def sub(m):
                    val = m.group(1)
                    en = by_kind.get(("customparam", val))
                    if en is not None:
                        stats["customparam_subs"] += 1
                        changed[0] = True
                        # These values are single-quoted JS string literals evaluated
                        # by the game; escape backslashes then single-quotes so an
                        # apostrophe ("Knight's") or quote ("'Slave Ship'") can't break
                        # the literal ("カスタムパラメータの設定 ... Expected '}'").
                        en_esc = en.replace("\\", "\\\\").replace("'", "\\'")
                        return "'" + en_esc + "'"
                    return m.group(0)
                return _SQ_RE.sub(sub, node)
            if key not in KEY_KIND:
                return node
            kind = KEY_KIND[key]
            # names: glossary characters win, else deduped name unit
            if kind == "name" and node in name_map:
                changed[0] = True
                stats["names_glossary"] += 1
                return name_map[node]
            en = by_kind.get((kind, node))
            if en is None:
                stats["skipped_no_tl"] += 1
                return node
            changed[0] = True
            stats["fields"] += 1
            return en

        new = repl(data)
        if changed[0]:
            dst = os.path.join(target, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "w", encoding="utf-8", newline="\n") as f:
                json.dump(new, f, ensure_ascii=False, indent=4)
            stats["files"] += 1
        elif not in_place:
            dst = os.path.join(target, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "w", encoding="utf-8", newline="\n") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
    return stats, target


def inject_js(js_strings_path, store_dir, width=DEFAULT_WIDTH):
    """Fill js_strings.json 'translation' fields from the plugin units."""
    _bk, _nm, plugin_map = _build_maps(store_dir, width)
    if not os.path.exists(js_strings_path):
        return {"files": 0, "filled": 0}
    js = json.load(open(js_strings_path, encoding="utf-8"))
    bl = plugin_blacklist(js)
    filled = skipped = 0
    for jsfile, entries in js.items():
        for e in entries:
            # only fill genuinely player-facing entries — never an asset filename,
            # debug-log arg, or an `=== 'id'`/voice-key literal, even if the SAME
            # text is translated elsewhere as a display label (would break triggers).
            if not plugin_translatable(e.get("original", ""), e.get("context", ""), bl):
                skipped += 1
                continue
            en = plugin_map.get(e.get("original", ""))
            if en:
                e["translation"] = en
                filled += 1
    with open(js_strings_path, "w", encoding="utf-8") as f:
        json.dump(js, f, ensure_ascii=False, indent=2)
    return {"files": len(js), "filled": filled, "skipped_nonfacing": skipped}
