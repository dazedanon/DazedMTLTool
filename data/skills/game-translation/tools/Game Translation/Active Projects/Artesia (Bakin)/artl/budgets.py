#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
budgets.py - which pixel box each translated string actually has to fit in.

This is where Bakin differs most from the RPG Maker pipelines, and it is worth
stating plainly because it inverts the usual work:

  * `BakinTL layout` measured **3,910 widgets, every one `sizeType = MANUAL`**,
    so every widget declares a real pixel box.
  * Of the 2,569 that carry text, only **118 (4.6%) word-wrap**. The other
    **95%** are one line: 1,783 are CLIPPED at `size.X` (the text is LOST) and
    668 are drawn past it (they collide with a neighbour).
  * So there is almost nothing to re-flow TO. On Bakin the fitting work is
    SHORTENING, not wrapping - the inverse of RPG Maker.

And the budget is usually not on the unit that was translated. Most layout
slots hold a content-getter code (`\skillname`, `\currentitemdes`,
`\battlemessage`) and draw whatever the getter returns at run time, so the
budget for `NSkill.name` is the MINIMUM `size.X` over every slot that draws
`\skillname` - and it is hard if any of those slots clips.

Two guardrails that stop this accusing the author:

  * The min-across-slots rule is a RANKING HEURISTIC, not an enforceable
    budget. On the reference game the narrowest clipping `partyname` slot was
    84px while the shipped Japanese name measured 96px. Where the author's own
    text already exceeds the box, the box is not the real bound.
  * The check is therefore DIFFERENTIAL: a slot is flagged only when the
    English is wider than the Japanese it replaced, and the already-over count
    is reported separately.
"""

import collections
import csv
import os
import re

# `\skillname` -> the rom field whose value it draws. Only the getters this
# game's layout actually uses are listed; `tools/codes_raw.txt` has all 541.
GETTER_FIELD = {
    "skillname": ("NSkill", "name"),
    "skilldes": ("NSkill", "description"),
    "currentskillname": ("NSkill", "name"),
    "currentskilldes": ("NSkill", "description"),
    "selectskillname": ("NSkill", "name"),
    "selectskilldes": ("NSkill", "description"),
    "learnskillname": ("NSkill", "name"),
    "currentlearnskillname": ("NSkill", "name"),
    "currentlearnskilldes": ("NSkill", "description"),
    "forgetskillname": ("NSkill", "name"),
    "itemname": ("NItem", "name"),
    "itemdes": ("NItem", "description"),
    "currentitemname": ("NItem", "name"),
    "currentitemdes": ("NItem", "description"),
    "selectitemname": ("NItem", "name"),
    "selectitemdes": ("NItem", "description"),
    "shopitemname": ("NItem", "name"),
    "shopitemdes": ("NItem", "description"),
    "partyname": ("Cast", "name"),
    "currentpartyname": ("Cast", "name"),
    "partydes": ("Cast", "description"),
    "currentpartydes": ("Cast", "description"),
    "reservename": ("Cast", "name"),
    "enemyname": ("Cast", "name"),
    "castname": ("Cast", "name"),
    "partyclass": ("Job", "name"),
    "currentpartyclass": ("Job", "name"),
    "partysubclass": ("Job", "name"),
    "partycondition": ("Condition", "name"),
    "currentpartycondition": ("Condition", "name"),
    "map": ("Map", "name"),
    "title": ("GameSettings", "title"),
    "subtitle": ("GameSettings", "subTitle"),
    "battlemessage": (None, None),      # runtime-assembled, no single field
    "message": (None, None),
}

_GETTER_RE = re.compile(r"\\([A-Za-z_]+)")


def _unesc(s):
    return (s or "").replace("\\t", "\t").replace("\\r", "\r") \
                    .replace("\\n", "\n").replace("\\\\", "\\")


def load_layout(path):
    """Rows from `BakinTL layout`, with the TSV escaping undone."""
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            r["text"] = _unesc(r.get("text"))
            r["node"] = _unesc(r.get("node"))
            r["name"] = _unesc(r.get("name"))
            for k in ("sizeX", "sizeY", "scaleX", "textScale"):
                try:
                    r[k] = float(r.get(k) or 0)
                except ValueError:
                    r[k] = 0.0
            for k in ("wordWrap", "clipping", "autoResize"):
                r[k] = (r.get(k) == "1")
            rows.append(r)
    return rows


class Budget(object):
    __slots__ = ("px", "clips", "wraps", "rows", "slots", "why")

    def __init__(self, px, clips, wraps, rows, slots, why):
        self.px = px
        self.clips = clips
        self.wraps = wraps
        self.rows = rows
        self.slots = slots
        self.why = why

    def __repr__(self):
        return "Budget(%.0fpx clips=%s wraps=%s rows=%d %s)" % (
            self.px, self.clips, self.wraps, self.rows, self.why)


def build(layout_rows, shipped_max=None):
    """Returns (by_key, by_field).

    `by_key["M:<node>:<i>:text"]`   the widget's OWN box, for a literal label.
    `by_field[("NSkill","name")]`   the bound on every value of that rom field.

    **The min over slots drawing a getter is a RANKING HEURISTIC, not a budget.**
    Measured on this game: the narrowest slot drawing `\\partyname` is 45px while
    the shipped Japanese cast names measure 159-162px, and the narrowest
    `\\skilldes` slot is 26px. Those slots are decorative sub-elements, not the
    visual bound. Enforcing them would flag every cast name in the game and the
    check would be switched off within a day - which is how a real overflow
    ships.

    So the bound is `max(narrowest slot, the widest value the AUTHOR already
    ships through this field)`. The author's own text is ground truth: whatever
    renders acceptably in Japanese renders acceptably in English at the same
    width. `shipped_max` is `{(Type, field): px}` and comes from measuring the
    store; without it this degrades to the heuristic and says so in `why`.
    """
    by_key = {}
    by_field = collections.defaultdict(list)
    for r in layout_rows:
        # THE SCALE DIVIDES, IT DOES NOT MULTIPLY - and having it the wrong way
        # round made this check 1/scale^2 too strict on every shrunken widget.
        #
        # `MenuItem.scale.X` scales the GLYPHS, not the box: the engine draws
        # with `MeasureString(mLargeFont, s).X * scale.X * PROD(ancestor
        # scale.X)` and clips against a rectangle that is NOT scaled with it
        # (`TextRenderer.DrawCallback`, `GetRenderScaleWithoutMyself`; and
        # `GraphicsCore.refreshFont` creates that font at 72px drawn at 1/3, so
        # the nominal is 24px at scale 1.0).
        #
        # Callers measure text UNSCALED, so to compare in one space the BOX is
        # normalised into unscaled units instead: a 64px box at scale 0.8 holds
        # 80px of unscaled text, not 51px. The old form asserted the opposite
        # and then hid the damage - the too-small budget made the shipped
        # JAPANESE look over-wide, which tripped the "author already overflows"
        # exclusion below and silently removed the widget from the check
        # altogether.
        # textScale is NOT part of this. It is read in exactly two places in the
        # engine - SpinRenderer.ResetProperty and SliderRenderer - while
        # TextRenderer/SpecialTextRenderer compute their scale from
        # `MenuItem.scale.X * 0.33333334f` and ignore it. For a TEXT_PANEL the
        # column is inert. It is 1.0 on all 3,910 rows of this game, so
        # including it changed no number here, but it would silently corrupt
        # the budget on a game that uses sliders or spinners.
        eff = r["sizeX"] / (r["scaleX"] or 1.0)
        key = "M:%s:%s:text" % (r["nodeGuid"], r["idx"])
        rows = int(r.get("maxLineNum") or 1) if r["wordWrap"] else 1
        by_key[key] = Budget(eff, r["clipping"], r["wordWrap"], rows, 1,
                             "own box on %s" % r["node"])
        # A WRAPPING slot holds `rows` lines, so its capacity in total-text-width
        # is that many times its width. Treating a 360px 3-line description box
        # as a 360px budget flagged six skill descriptions that wrap perfectly
        # well inside it.
        cap = eff * rows
        for g in _GETTER_RE.findall(r["text"] or ""):
            fld = GETTER_FIELD.get(g.lower())
            if fld and fld[0]:
                by_field[fld].append((cap, r["clipping"], r["node"], r["wordWrap"], rows))

    out = {}
    for fld, slots in by_field.items():
        narrowest = min(slots, key=lambda s: s[0])
        author = (shipped_max or {}).get(fld)

        # THE NARROWEST SLOT THAT CAN HOLD THE AUTHOR'S OWN WIDEST VALUE.
        #
        # Plain `min` over slots is the ranking heuristic this docstring warns
        # about, and the old code only patched it by raising the result to the
        # author's widest shipped value. That still understates the real bound
        # whenever a decorative sub-element drags the minimum down: the skill
        # `description` field is drawn in four 360x3 wrapping boxes (1,080px of
        # capacity) and in a 32px stub, so the minimum was 40px, the author rule
        # lifted it to 868px - the widest Japanese description - and six English
        # descriptions that wrap comfortably inside 1,080px were reported as
        # CLIPPED.
        #
        # A slot too narrow to hold what the author already ships through this
        # field is PROVEN not to be the visual bound, by the author's own
        # content. Drop those, then take the narrowest of what remains.
        usable = [s for s in slots if author is None or s[0] >= author]
        if usable:
            pick = min(usable, key=lambda s: s[0])
            px = pick[0]
            why = ("narrowest of %d slots that can hold the author's own widest "
                   "value (%s)" % (len(usable), pick[2]))
        else:
            # Every slot is narrower than the author's own text, so `size.X` is
            # not the visual bound anywhere and the author is the only evidence.
            pick = narrowest
            px = author if author else narrowest[0]
            why = ("no slot holds the author's widest %.0fpx value (narrowest "
                   "is %.0fpx on %s), so the author's own width is the bound"
                   % (author or 0.0, narrowest[0], narrowest[2]))
        clips = any(s[1] for s in slots if s[0] == px)
        wraps = bool(pick[3]) if len(pick) > 3 else False
        rows = int(pick[4]) if len(pick) > 4 else 1
        out[fld] = Budget(px, clips, wraps, rows, len(slots), why)
    return by_key, out


def shipped_widths(docs, metrics, rom_types):
    """{(Type, field): widest SHIPPED Japanese in px} over the store.

    Measured on the `raw` source, not on `src`: `src` has its control codes
    masked to sentinels, which are a different width from what they restore to.
    Line endings are normalised first - `metrics.width` splits on LF, and a rom
    field's CRLF would leave a stray CR measured as part of the line.
    """
    from . import codes as _c
    out = {}
    for _p, doc in docs:
        for u in doc["units"]:
            t = rom_types.get(u["key"])
            if not t:
                continue
            f = {"desc": "description"}.get(u["kind"], "name")
            w = metrics.width(_c.to_lf(u.get("raw") or ""))
            k = (t, f)
            if w > out.get(k, 0.0):
                out[k] = w
    return out


# Field-less kinds: what actually bounds them.
#
# `text` and `telop` go through `MessageReader.ReadMessage`, and on THIS engine
# build width and height are both SOFT. Verified by decompilation
# (`ENGINE-CODES.md` section 5):
#
#   * `MessageEntry.wordWrap` measures with `textDrawer.MeasureString`, a
#     native glyph-metrics call into SharpKmyGfx - not a character count.
#   * `splitByLines(maxLineNum)` does `line %= lineCount` and starts a new
#     inherited MessageEntry every time the index wraps, enqueuing each one.
#     Overflow becomes another key press. NOTHING is discarded.
#   * r64268's `ReadMessage` has no `isWordWrap` parameter at all - the newer
#     r73294 gained one wired to `MenuItem.useMultiLineText`. So the `wrap=0`
#     this build reports on the Message widget does NOT mean dialogue runs off
#     the box, and the data agrees: 11.8% of the SHIPPED JAPANESE physical
#     lines already measure wider than the 690px panel, which no author would
#     ship if it clipped.
#
# The cost of a long translation here is pacing, not loss: extra pages the
# player has to click through, which can desynchronise anything the script does
# after the message. That is a soft note with a threshold, never a failure.
#
# Measured panels: Message 690x140 and 670x136 at maxLineNum 3, Telop 1280x720
# at 3, nameplate slots 234-330px (clipped), so a speaker name is bounded even
# though the line it heads is not.
SOFT_KINDS = {"text", "telop"}

# The nameplate budget, in pixels. The nameplate is on screen for 71,519 lines,
# so it is the single most visible label in the game - and it is also the
# clearest example of why the narrowest-slot figure must not be enforced.
#
# The narrowest of the 36 slots drawing the nameplate getter is 234px. But the
# AUTHOR ships 11 nameplates wider than that, up to 360px
# (`なにを言えばいいかわからない男`), so 234 is not the visual bound - it is a
# decorative sub-element, exactly as with the field budgets. Enforcing 234
# flagged 67 English names covering 1,470 lines, almost all of them perfectly
# ordinary two-word job titles.
#
# So the budget is `max(narrowest slot, widest shipped Japanese nameplate)`,
# derived at run time by `nameplate_px`. The constant below is only the
# fallback for a caller with no store to measure.
NAMEPLATE_SLOT_PX = 234.0
NAMEPLATE_PX = 360.0


def nameplate_px(docs, metrics):
    """The honest nameplate budget: the author's own widest, or the slot."""
    widest = NAMEPLATE_SLOT_PX
    for _p, doc in docs:
        for u in doc["units"]:
            sp = u.get("speaker")
            if sp:
                w = metrics.width(sp)
                if w > widest:
                    widest = w
    return widest

# The message panel's own width and line cap, for the extra-pages note.
MESSAGE_PX, MESSAGE_LINES = 670.0, 3

def for_unit(u, by_key, by_field, rom_types=None):
    """The Budget a unit's translation has to fit, or None when unbounded.

    `None` is an honest answer, not a gap to paper over. `term` (the engine's
    own system glossary) and `message` are drawn by engine code rather than by
    a `\\getter` in a layout slot, so nothing in the layout data bounds them;
    inventing a budget for those would flag correct English against a number
    that came from nowhere. `BattleCommand.name` and `Attribute.name` are the
    same - no slot draws a getter for them in this game's layouts.

    `choice` is unbounded for a different reason: Bakin builds the dialogue
    choice container programmatically (`MenuSettings.createMenuContainer` /
    `convertChoicesMenuContainerSize`), so there is no static box in the layout
    data at all - the only nodes whose names mention selection are the ITEM
    picker. The prompt constrains choices to 1-4 words instead, and the UI
    review pass is what actually reads them."""
    kind = u["kind"]
    if kind in SOFT_KINDS:
        return None
    if kind == "ui":
        return by_key.get(u["key"])
    if kind in ("name", "desc", "affix"):
        t = (rom_types or {}).get(u["key"])
        if t:
            f = "description" if kind == "desc" else "name"
            return by_field.get((t, f))
        return None
    if kind == "mapname":
        return by_field.get(("Map", "name"))
    return None
