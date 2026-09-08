#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
qa.py - the passes no per-unit validator can do.

`dump_ui` prints every button, choice, label and name as JP -> EN side by side.
A few hundred lines, minutes to skim, and it is the ONLY pass that catches a
short verb rendered as the wrong part of speech: `訂正する` ("go back and
re-enter") came back as "Correct" on another game, which reads as agreement and
sends the player the opposite way. It is English, it is short, it carries no
placeholders and no residual Japanese - every automated check passes it.

`scan_output` reads the INJECTED .rvdata2 files, not the store, for the two
things a per-unit pass is structurally blind to:

  * a control code or a `⟦n⟧` sentinel that survived injection - the most
    visible failure a patch can ship, and sentinel-multiset validation compares
    source to translation and cannot see it;
  * lines the extractor never saw. Extraction keys on "contains a
    source-language character", so a string holding no Japanese was never a
    unit and no per-unit pass could reach it. A row of `＿＿＿＿` or `！！！`
    is still on screen. Anything byte-identical between source and output was
    never a unit, and it is reported WITH its event code so a reviewer can tell
    "still to do" from "correctly left alone" at a glance.

`unify_repeats` gives one repeated line one English rendering. Dialogue is
deliberately not deduped before translation, so the same source line can come
back two or three slightly different ways - invisible to every per-line
validator, and exactly what makes a patch feel machine-made. This game repeats
a great deal: the recollection room replays scenes that also exist in
CommonEvents.
"""

import os
import re
import collections

from . import codes, store, rvdata, measure, wrap, inject
from . import rvmarshal as M
from .config import DB_FIELDS

UI_KINDS = ("choice", "term", "type", "title", "currency", "name", "mapname",
            "message", "desc", "profile", "script")

LEAKED_CODE_RE = re.compile(r"\u27e6\d+\u27e7")

# Typographic conventions that must be converted whether or not they arrived
# attached to Japanese. Matched in BOTH widths, because authors write the same
# marker either way and a rule matching only the fullwidth form misses half.
CONVENTION_RE = re.compile(r"[＿_]{3,}|[！!]{3,}|[？?]{3,}|[。]{2,}|[、]{2,}|～{2,}")

# Codes this pipeline deliberately never translates, so a reviewer can tell
# "still to do" from "correctly left alone".
SKIPPED_CODES = {
    108: "comment (dev note)", 408: "comment cont.",
    118: "LABEL - a jump target matched by string equality",
    119: "JUMP TO LABEL - must match its 118 byte for byte",
    355: "script", 655: "script cont.",
    122: "control variable", 111: "conditional branch",
    231: "show picture - a graphics filename",
    241: "play BGM", 245: "play BGS", 249: "play ME", 250: "play SE",
    101: "message header - the parameter is a FACE GRAPHIC filename",
    402: "choice branch label (mirrored from its 102 by index)",
    284: "change parallax", 283: "change battleback",
    322: "change actor graphic", 129: "change party member",
}


# --------------------------------------------------------------------------
def dump_ui(cfg, store_dir, out_path=None, verbose=True):
    docs = store.load_docs(store_dir)
    glossary = store.load_glossary(store_dir)
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
        lines.append("[%-8s] %-40s -> %s" % (kind, jp.replace("\n", " / "),
                                             en.replace("\n", " / ")
                                             or "<UNTRANSLATED>"))
        lines.append("            %s" % uid)

    # The name plate is not a unit - it is a glossary entry - so it would never
    # appear in a units-only review, and it is drawn on 11,484 message boxes.
    lines.append("")
    lines.append("# \\NAME[] speaker plates, most used first")
    names = sorted(glossary.get("names", {}).items(),
                   key=lambda kv: -(kv[1].get("count", 0)
                                    if isinstance(kv[1], dict) else 0))
    for jp, v in names:
        n = v.get("count", 0) if isinstance(v, dict) else 0
        lines.append("[speaker ] %-40s -> %s   (%d lines)"
                     % (jp, store.name_en(v) or "<UNTRANSLATED>", n))

    text = "\n".join(lines)
    if out_path:
        with open(out_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
        if verbose:
            print("wrote %d unique UI labels + %d speakers -> %s"
                  % (len(seen), len(names), out_path))
    elif verbose:
        print(text)
    return len(seen)


# --------------------------------------------------------------------------
def _iter_display_strings(data, base):
    """(where, code, string node) for every player-facing string in a file.

    Deliberately the SAME notion of player-facing that extraction uses. Two
    implementations of "is this on screen" drift, and the QA one is the one
    nobody tests."""
    if base in DB_FIELDS or base == "Actors.rvdata2":
        fields = DB_FIELDS.get(base, ["@name", "@nickname", "@description"])
        for i, e in enumerate(data.items):
            if not isinstance(e, M.RObject):
                continue
            for f in fields:
                v = e.get(f)
                if isinstance(v, M.RString):
                    yield ("%s#%d%s" % (base, i, f), None, v)
        return
    if base == "System.rvdata2":
        for iv in ("@game_title", "@currency_unit"):
            v = data.get(iv)
            if isinstance(v, M.RString):
                yield ("System%s" % iv, None, v)
        for iv in ("@elements", "@skill_types", "@weapon_types", "@armor_types"):
            arr = data.get(iv)
            for i, v in enumerate(arr.items if isinstance(arr, M.RArray) else []):
                if isinstance(v, M.RString):
                    yield ("System%s[%d]" % (iv, i), None, v)
        terms = data.get("@terms")
        if isinstance(terms, M.RObject):
            for iv in ("@basic", "@params", "@etypes", "@commands"):
                arr = terms.get(iv)
                for i, v in enumerate(arr.items if isinstance(arr, M.RArray) else []):
                    if isinstance(v, M.RString):
                        yield ("System.terms%s[%d]" % (iv, i), None, v)
        return
    if rvdata.is_map_file(base):
        dn = data.get("@display_name")
        if isinstance(dn, M.RString):
            yield ("%s@display_name" % base, None, dn)
    for el in rvdata.event_lists(data, base):
        for ci, c in enumerate(el.node.items):
            if not isinstance(c, M.RObject):
                continue
            code, params = rvdata.command(c)
            # ONLY the parameters that can reach the screen, which is the same
            # rule extraction uses. Walking every string parameter instead
            # buries the report: this game's 8,716 picture names and 4,214 face
            # names are all Japanese, all correctly untranslated, and a report
            # 11,000 lines long is one nobody reads - which is exactly how the
            # single real residual goes unnoticed.
            if code in (401, 405):
                if params and isinstance(params[0], M.RString):
                    yield ("%s/c%d" % (el.uid, ci), code, params[0])
            elif code == 102 and params and isinstance(params[0], M.RArray):
                for qi, q in enumerate(params[0].items):
                    if isinstance(q, M.RString):
                        yield ("%s/c%d[%d]" % (el.uid, ci, qi), code, q)
            elif code == 402 and len(params) > 1 and isinstance(params[1], M.RString):
                yield ("%s/c%d" % (el.uid, ci), code, params[1])


def scan_output(cfg, out_dir, verbose=True):
    leaked, jp_left = [], []
    never_unit = collections.Counter()
    where = {}
    plate_only = 0

    for src in rvdata.data_files(cfg.data_dir):
        base = os.path.basename(src)
        out = os.path.join(out_dir, base)
        if not os.path.exists(out):
            continue
        odata = rvdata.load(out)
        sdata = rvdata.load(src)
        srcmap = {w: n.text() for w, _c, n in _iter_display_strings(sdata, base)}
        for w, code, node in _iter_display_strings(odata, base):
            value = node.text()
            if not value:
                continue
            if LEAKED_CODE_RE.search(value):
                leaked.append((base, w, value[:80]))
            residue = codes.has_untranslated_jp(value)
            convention = CONVENTION_RE.search(value)
            if not residue and not convention:
                continue
            src_value = srcmap.get(w)
            if src_value == value:
                key = value if len(value) < 44 else value[:44]
                never_unit[key] += 1
                tag = ("   [code %d - %s: correctly left alone]"
                       % (code, SKIPPED_CODES[code])) if code in SKIPPED_CODES \
                    else ("   [code %s]" % code if code else "")
                where.setdefault(key, "%s %s%s" % (base, w, tag))
            elif residue:
                # A line whose ONLY change is its `\NAME[]` plate is not a
                # failed translation, it is an untranslated line wearing an
                # English name. Counting it as residual Japanese buries the
                # real residuals in thousands of rows during a partial run,
                # which is exactly how the real one goes unnoticed.
                if (src_value is not None
                        and codes.split_nametag(src_value)[1]
                        == codes.split_nametag(value)[1]):
                    plate_only += 1
                else:
                    jp_left.append((base, w, value[:80]))

    if verbose:
        print("SCAN of %s" % out_dir)
        print("  leaked sentinels     : %d" % len(leaked))
        for b, p, v in leaked[:15]:
            print("     ! %s %s  %r" % (b, p, v))
        print("  translated but still holding Japanese : %d" % len(jp_left))
        for b, p, v in jp_left[:15]:
            print("     ! %s %s  %r" % (b, p, v))
        print("  name plate translated, body not yet   : %d" % plate_only)
        print("  byte-identical to the source (either never a unit, or a code "
              "this pipeline never translates): %d distinct" % len(never_unit))
        for v, n in never_unit.most_common(25):
            print("     ~ %4dx %-46r %s" % (n, v, where.get(v, "")))
    return leaked, jp_left, never_unit


# --------------------------------------------------------------------------
_THIRD_PERSON_RE = re.compile(
    r"\b(?:he|him|his|himself|she|her|hers|herself|they|them|their|theirs|"
    r"themselves)\b", re.I)


def _pick(variants_by_text):
    """The winning rendering: most sites, then the lowest id. Deterministic,
    so a re-run is a no-op."""
    return sorted(variants_by_text.items(),
                  key=lambda it: (-len(it[1]), min(u["id"] for u in it[1])))[0][0]


def unify_repeats(store_dir, apply=False, verbose=True, show=8):
    docs = store.load_docs(store_dir)
    groups = collections.OrderedDict()
    for _p, doc in docs:
        for u in doc["units"]:
            if u["kind"] != "text" or not (u.get("tl") or "").strip():
                continue
            groups.setdefault(u["src"], []).append(u)

    unified = skipped = touched = 0
    review, samples = [], []
    for src, units in groups.items():
        by_text = collections.OrderedDict()
        for u in units:
            by_text.setdefault(u["tl"], []).append(u)
        if len(by_text) < 2:
            continue
        speakers = {u.get("speaker", "") for u in units}
        third = any(_THIRD_PERSON_RE.search(t) for t in by_text)
        if third or len(speakers) > 1:
            review.append((src, list(by_text), [u["id"] for u in units],
                           "third-person pronoun - may resolve to a different "
                           "character per scene" if third
                           else "spoken by %d different speakers" % len(speakers)))
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
        print("  unified                                     : %d (%d unit(s) "
              "rewritten)" % (unified, touched))
        print("  left for review                             : %d" % skipped)
        for src, variants, win in samples:
            print("\n  JP  %s" % src.replace("\n", " / ")[:74])
            for v in variants:
                print("   %s %s" % ("->" if v == win else "  ",
                                    v.replace("\n", " / ")[:74]))
        if review:
            print("\n  -- NOT unified, decide these by hand --")
            for src, variants, ids, why in review[:show]:
                print("\n  JP  %s\n      (%s)" % (src.replace("\n", " / ")[:74], why))
                for v, i in zip(variants, ids):
                    print("      %-52s %s" % (v.replace("\n", " / ")[:52], i))
            if len(review) > show:
                print("\n  ... (%d more)" % (len(review) - show))
        if not apply:
            print("\ndry run - pass --apply to rewrite the store")
    return unified, skipped, touched


# --------------------------------------------------------------------------
def mock_screen(cfg, store_dir, out_png, limit=12, font_px=None, verbose=True):
    """Composite the message box at the real screen size.

    The only check that sees the widget in relation to the screen. `font_px`
    defaults to the MEASURED `measure.FONT_PX` (20), so a line crossing the red
    content edge here crosses it in game - which is how the first faced
    overflow was confirmed."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("Pillow not installed - `pip install pillow` to render the mock.")
        return 1

    font_px = font_px or measure.FONT_PX
    m = measure.reset(cfg.font_path())
    docs = store.load_docs(store_dir)
    picks = []
    for _p, doc in docs:
        for u in doc["units"]:
            if u["kind"] != "text" or not (u.get("tl") or "").strip():
                continue
            restored = codes.unmask_codes(codes.clean_translation(u["tl"]),
                                          u.get("codes") or {})
            width, hard, rows = inject.budget(u, cfg)
            f = wrap.fit(restored, width, rows, m)
            picks.append((f.widest, u, f))
    picks.sort(key=lambda x: -x[0])
    picks = picks[:limit]
    if not picks:
        print("nothing translated yet")
        return 1

    W = measure.SCREEN_WIDTH
    box_h = measure.LINE_HEIGHT * measure.MESSAGE_ROWS + measure.PADDING * 2
    H = (box_h + 18) * len(picks) + 16
    img = Image.new("RGB", (W, H), (16, 16, 24))
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(cfg.font_path() or "arial.ttf", font_px)
    except Exception:
        font = ImageFont.load_default()

    y = 16
    for widest, u, f in picks:
        faced = bool(u.get("faced"))
        d.rectangle([0, y, W - 1, y + box_h - 1], fill=(28, 32, 56),
                    outline=(110, 120, 170))
        x0 = measure.PADDING + (measure.FACE_INDENT if faced else 0)
        if faced:
            d.rectangle([measure.PADDING, y + measure.PADDING,
                         measure.PADDING + 96, y + measure.PADDING + 96],
                        outline=(90, 90, 120))
        rx = measure.PADDING + measure.CONTENTS_WIDTH
        d.line([rx, y, rx, y + box_h], fill=(220, 80, 80))
        ty = y + measure.PADDING
        for line in f.text.split("\n")[:measure.MESSAGE_ROWS]:
            plain = re.sub(r"\\+[A-Za-z]+\[[^\]]*\]", "", line)
            plain = re.sub(r"\\+[A-Za-z.|!^<>{}$]", "", plain)
            d.text((x0, ty), plain, font=font, fill=(240, 240, 240))
            ty += measure.LINE_HEIGHT
        d.text((8, y + box_h - 14), "%s  %d cells%s"
               % (u["id"], widest, "  [faced]" if faced else ""),
               font=ImageFont.load_default(), fill=(150, 150, 170))
        y += box_h + 18

    img.save(out_png)
    if verbose:
        print("wrote %s  (%d widest boxes, red line = the %d px content edge, "
              "font drawn at %dpx)"
              % (out_png, len(picks), measure.CONTENTS_WIDTH, font_px))
    return 0
