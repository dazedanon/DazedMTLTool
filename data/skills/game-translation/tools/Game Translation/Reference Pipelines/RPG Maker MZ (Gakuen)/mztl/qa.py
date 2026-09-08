#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qa.py - the passes no validator can do.

`ui` dumps every button, choice, notice and label as JP -> EN side by side.
A few hundred lines, minutes to skim, and it is the ONLY pass that catches a
short verb rendered as the wrong part of speech: `訂正する` ("correct it", i.e.
go back and re-enter) came back as "Correct", which reads as agreement and
sends the player the opposite way. It is English, it is short, it carries no
placeholders and no residual Japanese - every automated check passes it.

`scan-output` greps the INJECTED files, not the store, for two things a
per-unit pass is structurally blind to:

  * A control code that survived injection - the most visible failure a patch
    can ship, and sentinel-multiset validation compares source to translation
    and cannot see it.
  * Lines the extractor never saw. Extraction keys on "contains a
    source-language character", so a line holding no Japanese was never a unit
    and no per-unit pass could ever reach it. A row of `______` or `！！！` is
    still on screen. Anything byte-identical between the source and the
    injected output was never a unit.
"""

import os
import re
import glob
import json
import collections

from . import codes, store, fileio, measure, wrap

UI_KINDS = ("choice", "term", "type", "title", "currency", "name", "mapname",
            "ptext", "message", "plugin")

LEAKED_CODE_RE = re.compile(
    r"\\(?:C|I|FS|PX|PY|OW|OC|V|N|P|F|FF|AA|M|FH)\s*\[[^\]\r\n]*\]"
    r"|\\[GgSs](?![A-Za-z])"
    r"|\\[.|!^<>{}$]"
    r"|\u27e6\d+\u27e7",
    re.I)

# Typographic conventions that must be converted whether or not they arrived
# attached to Japanese. Matched in BOTH widths, because authors write the same
# marker either way and a rule matching only the fullwidth form misses half.
CONVENTION_RE = re.compile(r"[＿_]{3,}|[！!]{3,}|[？?]{3,}|[。]{2,}|[、]{2,}|～{2,}")


# --------------------------------------------------------------------------
# Same-source consistency
# --------------------------------------------------------------------------
# Dialogue is deliberately NOT deduped before translation - the model needs a
# coherent run of lines with speakers, and one 「わかった」 rendered "I'll tell
# her" is right in the scene it was translated in and wrong everywhere else the
# engine reuses it. The cost is that a line the game repeats verbatim comes back
# in two or three slightly different English renderings, which is invisible to
# every per-line validator and is exactly what makes a patch feel machine-made.
#
# This game repeats a lot: the Recollection Room (Map011) replays the CG scenes
# from CommonEvents, so the SAME line exists in two or three places and must
# read identically in all of them.
#
# So the clusters are unified - except in the two cases where the reuse really
# is scene-dependent, which is the reason the dedup was skipped in the first
# place:
#
#   * a variant carrying a THIRD-PERSON pronoun. Japanese drops subjects and
#     MT invents them, so "he"/"she"/"they" may resolve to different people in
#     different scenes.
#   * a cluster spoken by MORE THAN ONE speaker. Register and first person
#     differ per speaker even when the source string does not.
#
# Those are reported for a human, never auto-unified.

_THIRD_PERSON_RE = re.compile(
    r"\b(?:he|him|his|himself|she|her|hers|herself|they|them|their|theirs|"
    r"themselves)\b", re.I)


def _pick(variants_by_text):
    """The winning rendering: most sites, then the canonical (non-replay)
    location, then the lowest id. Deterministic, so a re-run is a no-op."""
    def key(item):
        text, units = item
        replay = all(u["id"].startswith("Map011") for u in units)
        return (-len(units), replay, min(u["id"] for u in units))
    return sorted(variants_by_text.items(), key=key)[0][0]


def unify_repeats(store_dir, apply=False, verbose=True, show=8):
    docs = store.load_docs(store_dir)
    groups = collections.OrderedDict()
    for _p, doc in docs:
        for u in doc["units"]:
            if u["kind"] != "text" or not (u.get("tl") or "").strip():
                continue
            groups.setdefault(u["src"], []).append(u)

    unified = skipped = touched = 0
    review = []
    samples = []
    for src, units in groups.items():
        by_text = collections.OrderedDict()
        for u in units:
            by_text.setdefault(u["tl"], []).append(u)
        if len(by_text) < 2:
            continue
        speakers = {u.get("speaker", "") for u in units}
        third = any(_THIRD_PERSON_RE.search(t) for t in by_text)
        if third or len(speakers) > 1:
            why = ("third-person pronoun - may resolve to a different "
                   "character per scene" if third
                   else "spoken by %d different speakers" % len(speakers))
            review.append((src, list(by_text), [u["id"] for u in units], why))
            skipped += 1
            continue
        win = _pick(by_text)
        if len(samples) < show:
            samples.append((src, list(by_text), win))
        for u in units:
            if u["tl"] != win:
                if apply:
                    u["tl"] = win
                touched += 1
        unified += 1

    if apply:
        store.save_docs(docs)

    if verbose:
        print("SAME-SOURCE CONSISTENCY")
        print("  repeated lines with more than one rendering : %d"
              % (unified + skipped))
        print("  unified                                     : %d "
              "(%d unit(s) rewritten)" % (unified, touched))
        print("  left for review                             : %d" % skipped)
        for src, variants, win in samples:
            print("\n  JP  %s" % src.replace("\n", " / ")[:74])
            for v in variants:
                mark = "->" if v == win else "  "
                print("   %s %s" % (mark, v.replace("\n", " / ")[:74]))
        if review:
            print("\n  -- NOT unified, decide these by hand --")
            for src, variants, ids, why in review[:show]:
                print("\n  JP  %s" % src.replace("\n", " / ")[:74])
                print("      (%s)" % why)
                for v, i in zip(variants, ids):
                    print("      %-52s %s" % (v.replace("\n", " / ")[:52], i))
            if len(review) > show:
                print("\n  ... (%d more)" % (len(review) - show))
        if not apply:
            print("\ndry run - pass --apply to rewrite the store")
    return unified, skipped, touched


def dump_ui(cfg, store_dir, out_path=None, verbose=True):
    docs = store.load_docs(store_dir)
    rows = []
    for _p, doc in docs:
        for u in doc["units"]:
            if u["kind"] not in UI_KINDS:
                continue
            rows.append((u["kind"], u["id"], u.get("raw", ""),
                         (u.get("tl") or "").strip()))
    rows.sort(key=lambda r: (r[0], r[2]))
    seen = set()
    lines = ["# UI label review - read this, do not skim it.",
             "# A short verb rendered as the wrong part of speech passes every",
             "# automated check and sends the player the opposite way.", ""]
    for kind, uid, jp, en in rows:
        key = (kind, jp)
        if key in seen:
            continue
        seen.add(key)
        lines.append("[%-8s] %-38s -> %s" % (kind, jp, en or "<UNTRANSLATED>"))
        lines.append("            %s" % uid)
    text = "\n".join(lines)
    if out_path:
        with open(out_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
        if verbose:
            print("wrote %d unique UI labels -> %s" % (len(seen), out_path))
    elif verbose:
        print(text)
    return len(seen)


# --------------------------------------------------------------------------
def scan_output(cfg, out_data_dir, verbose=True):
    """Scan the INJECTED data for leaked codes and never-extracted lines."""
    leaked = []
    never_unit = collections.Counter()
    where = {}
    jp_left = []

    src_files = {os.path.basename(p): p
                 for p in glob.glob(os.path.join(cfg.data_dir, "*.json"))}

    for out in sorted(glob.glob(os.path.join(out_data_dir, "*.json"))):
        base = os.path.basename(out)
        odata, _ = fileio.load(out)
        sdata, _ = fileio.load(src_files[base]) if base in src_files else (None, None)

        for path, value in _walk_strings(odata):
            if not isinstance(value, str) or not value:
                continue
            if _is_asset_or_key(path, value):
                continue
            if codes.PH_RE.search(value):
                leaked.append((base, path, value[:80]))
            if not _is_display_path(path, base):
                continue
            residue = codes.has_untranslated_jp(value)
            convention = CONVENTION_RE.search(value)
            if not residue and not convention:
                continue
            same = _get(sdata, path) if sdata is not None else None
            if same == value:
                key = value if len(value) < 44 else value[:44]
                never_unit[key] += 1
                where.setdefault(key, "%s%s%s"
                                 % (base, path, _code_tag(odata, path)))
            elif residue:
                jp_left.append((base, path, value[:80]))

    if verbose:
        print("SCAN of %s" % out_data_dir)
        print("  leaked sentinels     : %d" % len(leaked))
        for b, p, v in leaked[:15]:
            print("     ! %s %s  %r" % (b, p, v))
        print("  translated but still holding Japanese : %d" % len(jp_left))
        for b, p, v in jp_left[:15]:
            print("     ! %s %s  %r" % (b, p, v))
        print("  byte-identical to the source (either untranslated, or never "
              "a unit at all): %d distinct" % len(never_unit))
        for v, n in never_unit.most_common(20):
            print("     ~ %4dx %-46r %s" % (n, v, where.get(v, "")))
    return leaked, jp_left, never_unit


_DISPLAY_KEYS = {"parameters", "description", "nickname", "profile",
                 "displayName", "message1", "message2", "message3", "message4",
                 "terms", "basic", "commands", "params", "messages",
                 "armorTypes", "weaponTypes", "equipTypes", "skillTypes",
                 "elements", "gameTitle", "currencyUnit"}

_ASSET_RE = re.compile(r"\.(png|ogg|m4a|wav|json|js|ttf|woff2?)$", re.I)

# An EVENT's `name` is the editor's label for it (`毒沼`, `宝箱かミミック`), never
# drawn. A DATABASE entry's `name` is an item in the player's inventory. Both
# are `/name`, so the two have to be told apart by what encloses them, or 281
# copies of one map event's editor label drown the report that is supposed to
# be actionable.
_EVENT_NAME_RE = re.compile(r"/events/\d+/name$|^/\d+/name$")
_DB_NAME_RE = re.compile(r"^/\d+/name$")
_DB_FILES = {"Items.json", "Armors.json", "Weapons.json", "Actors.json",
             "Classes.json", "Skills.json", "States.json", "Enemies.json"}


def _is_asset_or_key(path, value):
    if _ASSET_RE.search(value):
        return True
    for seg in ("/note", "/switches/", "/variables/", "/tilesets", "/data",
                "/autoplayBgm", "/bgm", "/bgs", "/battleback", "/encounterList",
                "/parallaxName", "/battlerName", "/characterName", "/faceName"):
        if seg in path:
            return True
    return False


def _is_display_path(path, base=""):
    if _EVENT_NAME_RE.search(path):
        return base in _DB_FILES and _DB_NAME_RE.search(path) is not None
    return any(("/" + k) in path or path.startswith(k) for k in _DISPLAY_KEYS)


# Codes this pipeline deliberately never translates, so a reviewer reading the
# scan can tell "still to do" from "correctly left alone" at a glance.
_SKIPPED_CODES = {
    108: "comment (dev note)", 408: "comment cont.",
    118: "LABEL - a jump target matched by string equality",
    119: "JUMP TO LABEL - must match its 118 byte for byte",
    355: "script", 655: "script cont.",
    122: "control variable", 111: "conditional branch",
    402: "choice branch label (mirrored from its 102 by index)",
}


def _code_tag(data, path):
    """`[code 118 - LABEL ...]` for a string inside an event command list."""
    m = re.match(r"(?P<lst>.*/list)/(?P<i>\d+)/parameters", path)
    if not m:
        return ""
    lst = _get(data, m.group("lst"))
    try:
        code = lst[int(m.group("i"))].get("code")
    except (TypeError, IndexError, AttributeError, ValueError):
        return ""
    if code in _SKIPPED_CODES:
        return "   [code %d - %s: correctly left alone]" % (code, _SKIPPED_CODES[code])
    return "   [code %s]" % code


def _walk_strings(node, path=""):
    if isinstance(node, dict):
        for k, v in node.items():
            for r in _walk_strings(v, path + "/" + str(k)):
                yield r
    elif isinstance(node, list):
        for i, v in enumerate(node):
            for r in _walk_strings(v, path + "/" + str(i)):
                yield r
    elif isinstance(node, str):
        yield path, node


def _get(node, path):
    cur = node
    for seg in path.strip("/").split("/"):
        try:
            if isinstance(cur, list):
                cur = cur[int(seg)]
            else:
                cur = cur[seg]
        except (KeyError, IndexError, ValueError, TypeError):
            return None
    return cur


# --------------------------------------------------------------------------
def mock_screen(cfg, store_dir, out_png, limit=12, verbose=True):
    """Composite the message box with the real font at the real size.

    This is the only check that sees the widget in relation to the screen. An
    overflow here is an overflow on screen, and rendering the Japanese through
    the same code gives the before/after pair."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("Pillow not installed - `pip install pillow` to render the mock.")
        return 1

    m = measure.reset(cfg.font_path)
    docs = store.load_docs(store_dir)
    picks = []
    for _p, doc in docs:
        for u in doc["units"]:
            if u["kind"] != "text" or not (u.get("tl") or "").strip():
                continue
            restored = codes.unmask_codes(codes.clean_translation(u["tl"]),
                                          u.get("codes") or {})
            f = wrap.fit(restored, cfg.width, cfg.max_rows, m)
            picks.append((f.widest, u, f))
    picks.sort(key=lambda x: -x[0])
    picks = picks[:limit]
    if not picks:
        print("nothing translated yet")
        return 1

    W = measure.BOX_WIDTH
    box_h = measure.LINE_HEIGHT * measure.MESSAGE_ROWS + measure.PADDING * 2
    H = (box_h + 16) * len(picks) + 16
    img = Image.new("RGB", (W, H), (16, 16, 24))
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(cfg.font_path, measure.FONT_SIZE)

    y = 16
    for widest, u, f in picks:
        d.rectangle([measure.MSG_WINDOW_X, y,
                     measure.MSG_WINDOW_X + measure.MSG_WINDOW_WIDTH - 1,
                     y + box_h - 1], fill=(28, 32, 56), outline=(110, 120, 170))
        # The exact right edge of the drawable area.
        rx = measure.MSG_TEXT_X + measure.CONTENTS_WIDTH
        d.line([rx, y, rx, y + box_h], fill=(220, 80, 80))
        ty = y + measure.PADDING
        for line in f.text.split("\n")[:measure.MESSAGE_ROWS]:
            plain = re.sub(r"\\+[A-Za-z]+\[[^\]]*\]", "", line)
            plain = re.sub(r"\\+[A-Za-z.|!^<>{}$]", "", plain)
            d.text((measure.MSG_TEXT_X, ty), plain, font=font,
                   fill=(240, 240, 240))
            ty += measure.LINE_HEIGHT
        d.text((8, y + box_h - 18), "%s  %d cells" % (u["id"], widest),
               font=ImageFont.load_default(), fill=(150, 150, 170))
        y += box_h + 16

    img.save(out_png)
    if verbose:
        print("wrote %s  (%d widest boxes, red line = the %dpx content edge)"
              % (out_png, len(picks), measure.CONTENTS_WIDTH))
    return 0
