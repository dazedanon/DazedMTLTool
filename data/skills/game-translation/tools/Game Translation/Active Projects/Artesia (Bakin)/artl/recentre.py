#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
recentre.py - put a hand-positioned label back where the author centred it.

THE DEFECT. Bakin has no "centre this text in its box" flag on a MenuItem. A
layout label is drawn from `pos.X` with `origin = MiddleLeft`, so to make a
label LOOK centred on its decorative plate the author nudged `pos.X` by hand,
once per label, against the width of the JAPANESE string:

    idx  text          pos.X   drawn(JP)   centre
     17  アイテム           47        96      95.0
     18  スキル            60        72      96.0
     19  装備             72        48      96.0
     20  ファストトラベル       18       154      94.8     (scale.X 0.8)
     21  Hステータス         27       137      95.5
     22  セーブ            60        72      96.0
     23  コンフィグ          35       120      95.0

Seven strings from 48px to 154px wide, all landing on the same centre within
**1.2px**. That is not a coincidence and it is not a layout engine doing it -
it is seven deliberate hand offsets.

Replace the text and `pos.X` does not move, so every label is now off centre by
half the width difference. English is mostly shorter than Japanese here, so
they all drift LEFT - up to 31px - into the plate's left end-cap, with a gap on
the right. Nothing overflows. Nothing is clipped. Every width check passes and
the menu looks broken, which is exactly what a player reports as "the text is
out of its box".

THE FIX is arithmetic, not editorial:

    new_pos.X = pos.X + (drawn(JP) - drawn(EN)) / 2

which preserves each label's OWN centre rather than snapping the group to a
common one. If the author left one label deliberately off the group centre,
that intent survives.

WHY A GROUP IS REQUIRED. A label sitting at `origin = MiddleLeft` might be
hand-centred, or it might be plainly left-aligned at a margin - and shifting a
left-aligned label is a regression, not a repair. The two are indistinguishable
from one widget. They are easy to tell apart from a GROUP: several sibling
labels whose `pos.X` values DIFFER while their Japanese centres AGREE can only
be hand-centring, because left alignment would have given them all the same
`pos.X`. So this module never acts on a widget it cannot see as part of such a
group, and reports the ones it declined.

THE FONT SIZE IS NOT THE MESSAGE ONE. Layout widgets render at 24px on this
build and the message box at 22px (see `config.layout_font_size`). The group
test is what proved it: at 22px those seven centres scatter over 5.6px, at 24px
over 1.2px. Seven independent strings agreeing to a pixel is a far stronger
calibration than any single screenshot measurement, and it is self-checking -
`detect` reports the spread it achieved, so a wrong font size shows up as a
group that fails to cohere rather than as silently wrong offsets.
"""

import collections

# A group is only believable when its members really do share a centre...
CENTRE_TOL_PX = 3.0
# ...and were really nudged apart. Identical pos.X across the group means plain
# left alignment, whose centres agree only by accident of equal widths.
MIN_POSX_SPREAD_PX = 8.0
MIN_GROUP = 3
# Below this the shift is invisible and churning the layout rom is not worth it.
MIN_SHIFT_PX = 2.0


def drawn(text, metrics, row, scale=None):
    """On-screen width of a layout label: measured, then scaled by the widget.

    `scale.X` scales the GLYPHS - a 0.8 label renders smaller, which is visible
    in any screenshot that has both a 1.0 and a 0.8 label in it. `size.X` is
    NOT scaled with it, so the two do not cancel and both have to be applied
    where they belong. `textScale` is deliberately absent: TextRenderer computes
    its scale from `scale.X` alone and only Spin/Slider renderers read it.

    `scale` overrides the row's own, which is what lets a label be RESIZED and
    RECENTRED in one step - the new centre has to be computed from the width the
    label will have after the resize, not the width it has now."""
    if not text:
        return 0.0
    if scale is None:
        scale = _f(row.get("scaleX"), 1.0)
    return metrics.width(text) * scale


def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def detect(rows, texts, metrics):
    """Find hand-centred groups.

    `rows`   layout.tsv rows (dicts) - needs nodeGuid, idx, posX, origin, scaleX
    `texts`  {(nodeGuid, idx): japanese_source}
    Returns [group], each a dict with the members and the evidence."""
    buckets = collections.defaultdict(list)
    for r in rows:
        key = (r["nodeGuid"], r["idx"])
        jp = texts.get(key)
        if not jp or not jp.strip():
            continue
        # Group by node AND anchor: a MiddleLeft row and a MiddleRight row are
        # positioned by different rules and must never be pooled.
        buckets[(r["nodeGuid"], r.get("origin"), r.get("sizeY"))].append((r, jp))

    out = []
    for (node, origin, _sy), members in sorted(buckets.items()):
        if len(members) < MIN_GROUP:
            continue
        cents = [(_f(r["posX"]) + drawn(jp, metrics, r) / 2.0) for r, jp in members]
        xs = [_f(r["posX"]) for r, _jp in members]
        spread = max(cents) - min(cents)
        if spread > CENTRE_TOL_PX or (max(xs) - min(xs)) < MIN_POSX_SPREAD_PX:
            continue
        out.append({
            "node": node, "origin": origin,
            "members": members,
            "centre": sum(cents) / len(cents),
            "spread": spread,
            "posx_spread": max(xs) - min(xs),
        })
    return out


def adopt(groups, rows, texts, metrics, tol=CENTRE_TOL_PX):
    """Pull in siblings that share a detected group's centre but not its shape.

    `detect` buckets by (node, origin, sizeY) so it cannot pool widgets
    positioned by different rules. That is right for FINDING a group and wrong
    for finishing one: this game's "Quit Game" button sits on the same plate as
    the other seven, hand-centred on the same x, but is authored with a
    different origin and box, so it was left behind and shipped off centre while
    its neighbours were fixed.

    Once a group's centre is known it is evidence in its own right, and a
    sibling in the same node whose SOURCE text centres on that same x is
    hand-centred on the same plate whatever its anchor says."""
    for grp in groups:
        have = {(r["nodeGuid"], r["idx"]) for r, _jp in grp["members"]}
        for r in rows:
            key = (r["nodeGuid"], r["idx"])
            if r["nodeGuid"] != grp["node"] or key in have:
                continue
            jp = texts.get(key)
            if not jp or not jp.strip():
                continue
            c = _f(r["posX"]) + drawn(jp, metrics, r) / 2.0
            if abs(c - grp["centre"]) <= tol:
                grp["members"].append((r, jp))
                grp["adopted"] = grp.get("adopted", 0) + 1
    return groups


# A label is only nudged vertically when it is out by at least this much.
MIN_VSHIFT_PX = 1.0


# How far the author's own box centre may sit from a panel band's centre and
# still count as "they meant this centred".
INTENT_TOL_PX = 3.0
# A sibling container this thin is a RULE, not content: it subdivides the panel.
DIVIDER_MAX_H = 4.0


def _scale_of(r, scale_overrides):
    sc = (scale_overrides or {}).get((r["nodeGuid"], r["idx"]))
    return _f(r.get("scaleX"), 1.0) if sc is None else sc


def _band(rows, container, y):
    """The vertical band of `container` that `y` falls in, split by its rules.

    A panel with a divider across it is two cells, and a heading centred in the
    top cell is not centred in the panel. Ignoring the rule would drag it to the
    panel's middle - straight through the rule."""
    edges = [0.0, _f(container.get("sizeY"))]
    for q in rows:
        if q["nodeGuid"] != container["nodeGuid"]:
            continue
        if q.get("parent") != container["idx"]:
            continue
        h = _f(q.get("sizeY"))
        if (q.get("layoutType") or "") == "RENDER_CONTAINER" and 0 < h <= DIVIDER_MAX_H:
            edges.append(_f(q.get("posY")))
            edges.append(_f(q.get("posY")) + h)
    edges = sorted(set(edges))
    lo, hi = edges[0], edges[-1]
    for a, b in zip(edges, edges[1:]):
        if a <= y <= b:
            lo, hi = a, b
            break
    return lo, hi


def vcentre(rows, ink_ratio=0.0, base_px=24.0, only_nodes=None,
            scale_overrides=None, only_panels=None):
    """[(write_key, new_pos_y, detail)] for labels sitting off-centre on a plate.

    `origin` on a TEXT_PANEL sets BOTH alignments, which is not obvious and is
    the whole of this defect (`TextRenderer.ResetProperty`, decompiled):

        MiddleLeft -> vertical Center, horizontal Left
        TopLeft    -> vertical Top,    horizontal Left

    and `DrawString` then aligns the text inside the item's OWN box:

        Center: y = pos.Y + size.Y/2 - textHeight/2
        Top:    y = pos.Y

    So a `Middle*` label is centred on its own box, NOT on the plate it sits on,
    and the two only coincide when `pos.Y == (plateH - size.Y) / 2`. On this
    game's menu the boxes are 45px tall on a 35px plate at `pos.Y = 2`, so every
    one of them is centred at 24.5 against a plate centre of 17.5 - seven pixels
    low, with the descenders hanging past the frame. The one button the author
    gave `TopLeft` lands centred by luck, which is exactly what makes the other
    seven look wrong next to it.

    The correction is text-independent, which is why it is worth doing as
    geometry rather than by eye:

        pos.Y = plateH/2 - size.Y/2

    NOTE this is the AUTHOR's offset, not damage the translation did - the
    Japanese sat equally low. It is a deliberate improvement, so it is gated on
    `config.layout_vcentre` and can be turned off.

    Only `Middle*` is handled. Centring a `Top*` or `Bottom*` label depends on
    the rendered height of its own text, so it would move with every retranslation
    and is reported instead.

    AND ONLY WHERE THE LABEL IS ALONE ON ITS PLATE. `pos.Y` is also how an author
    STACKS several labels on one plate, and centring those would pile them on top
    of each other: this game's save slots put five fields on one 80px plate at
    `pos.Y` 4 and 38, and a blanket centring pass moved all of them to 24. Where a
    sub container holds more than one text panel, every `pos.Y` in it is
    deliberate layout and none of it is ours to touch. This is the same discipline
    as requiring a group before moving a label horizontally: act only where the
    evidence is unambiguous, and count what was declined."""
    by_idx = {}
    for r in rows:
        by_idx[(r["nodeGuid"], r["idx"])] = r

    def parent(r):
        p = r.get("parent")
        if p in (None, "", "-1"):
            return None
        return by_idx.get((r["nodeGuid"], p))

    # How many text panels share each sub container. More than one means the
    # author is stacking them and pos.Y is load-bearing.
    def sub_of(r):
        p = parent(r)
        while p is not None and (p.get("layoutType") or "") != "MENU_SUB_CONTAINER":
            p = parent(p)
        return p

    siblings = collections.Counter()
    for r in rows:
        if (r.get("layoutType") or "") != "TEXT_PANEL":
            continue
        if not (r.get("text") or "").strip():
            continue
        sub = sub_of(r)
        if sub is not None:
            siblings[(sub["nodeGuid"], sub["idx"])] += 1

    out, skipped = [], collections.Counter()
    for r in rows:
        if (r.get("layoutType") or "") != "TEXT_PANEL":
            continue
        if not (r.get("text") or "").strip():
            continue
        # TWO KINDS OF REGION, and they need different evidence.
        #
        # A MENU_SUB_CONTAINER is a BUTTON. Its label belongs centred on it by
        # definition, so no further evidence is needed - which matters, because
        # this game's menu boxes are 45px tall on a 35px plate and their centres
        # do NOT coincide.
        #
        # A RENDER_CONTAINER is a PANEL that may hold several things at
        # deliberate positions - a heading above a rule, a value below it - so
        # centring everything in it would be vandalism. There the author has to
        # SHOW the intent, by having already placed the box centred in its band.
        # Then all that is wrong is the ink offset.
        sub = parent(r)
        while sub is not None and (sub.get("layoutType") or "") not in (
                "MENU_SUB_CONTAINER", "RENDER_CONTAINER"):
            sub = parent(sub)
        if sub is None:
            continue
        kind = sub.get("layoutType") or ""
        box_c = _f(r.get("posY")) + _f(r.get("sizeY")) / 2.0

        if kind == "RENDER_CONTAINER":
            # Middle* ONLY, exactly as for a button. This branch returns early,
            # so without its own check it would happily "centre" a Top* or
            # Bottom* label whose vertical alignment is not centring at all -
            # it moved the Inn's right-aligned \money value on the first run.
            if not (r.get("origin") or "").startswith("Middle"):
                skipped["panel label origin %s: not centred by the engine"
                        % (r.get("origin") or "?")] += 1
                continue
            # Approved by the CONTAINER'S OWN SHAPE, not by its node. Scoping
            # by node let every Middle* label in any screen that merely happened
            # to contain a money panel through - BattleResult, MainMenu - which
            # is the same over-reach as before wearing a different hat. A shape
            # is one widget, verified once and identical everywhere it appears.
            shape = (_f(sub.get("sizeX")), _f(sub.get("sizeY")))
            if only_panels is not None and shape not in only_panels:
                skipped["panel %gx%g is not an approved shape"
                        % (shape[0], shape[1])] += 1
                continue
            lo, hi = _band(rows, sub, box_c)
            if hi <= lo:
                skipped["panel band is empty"] += 1
                continue
            target = (lo + hi) / 2.0
            if abs(box_c - target) > INTENT_TOL_PX:
                skipped["panel label is not centred in its band - "
                        "position is deliberate"] += 1
                continue
            k = ink_ratio * base_px * _scale_of(r, scale_overrides)
            want = target - _f(r.get("sizeY")) / 2.0 - k
            cur = _f(r.get("posY"))
            if abs(want - cur) < MIN_VSHIFT_PX:
                continue
            out.append(("M:%s:%s:posY" % (r["nodeGuid"], r["idx"]),
                        "%.2f" % want,
                        {"node": r.get("node"), "idx": r["idx"],
                         "text": r.get("text"), "old": cur, "new": want,
                         "plate_h": hi - lo, "sizeY": _f(r.get("sizeY"))}))
            continue

        if only_nodes is not None and r["nodeGuid"] not in only_nodes:
            skipped["button node not calibrated - no screenshot measured"] += 1
            continue
        n = siblings.get((sub["nodeGuid"], sub["idx"]), 0)
        if n > 1:
            skipped["%d labels share the plate: pos.Y is deliberate stacking" % n] += 1
            continue
        owner = parent(sub)
        plate_h = _f(owner.get("subH")) if owner is not None else 0.0
        if plate_h <= 0:
            skipped["no plate height"] += 1
            continue
        origin = r.get("origin") or ""
        if not origin.startswith("Middle"):
            skipped["origin %s: centring depends on the text's own height" % origin] += 1
            continue
        # The line box is centred at `pos.Y + size.Y/2`; the visible ink sits
        # `K` above that, so the ink is centred when pos.Y is lowered by K.
        # K is measured, not derived - see `config.layout_ink_offset_ratio`.
        # The DRAWN size, so the override has to be honoured here exactly as it
        # is in `fixes`. Reading the row's own scaleX computes the offset for a
        # size the label will not ship at, and the resulting shift silently
        # falls under MIN_VSHIFT_PX - which is how this went unnoticed once
        # already.
        sc = (scale_overrides or {}).get((r["nodeGuid"], r["idx"]))
        if sc is None:
            sc = _f(r.get("scaleX"), 1.0)
        k = ink_ratio * base_px * sc
        want = plate_h / 2.0 - _f(r.get("sizeY")) / 2.0 - k
        cur = _f(r.get("posY"))
        if abs(want - cur) < MIN_VSHIFT_PX:
            continue
        out.append(("M:%s:%s:posY" % (r["nodeGuid"], r["idx"]),
                    "%.2f" % want,
                    {"node": r.get("node"), "idx": r["idx"], "text": r.get("text"),
                     "old": cur, "new": want, "plate_h": plate_h,
                     "sizeY": _f(r.get("sizeY"))}))
    return out, skipped


def fixes(rows, texts, translations, metrics, scale_overrides=None):
    """[(write_key, new_pos_x_string, detail)] for every hand-centred label.

    `translations` {(nodeGuid, idx): english}. A member with no translation is
    left alone - its Japanese is still on screen and still correctly placed.

    `scale_overrides` {(nodeGuid, idx): scale} resizes a label; the new centre
    is then computed from its resized width, so resize and recentre compose."""
    out = []
    skipped = collections.Counter()
    scale_overrides = scale_overrides or {}
    for grp in adopt(detect(rows, texts, metrics), rows, texts, metrics):
        for r, jp in grp["members"]:
            key = (r["nodeGuid"], r["idx"])
            en = translations.get(key)
            if not en or not en.strip():
                skipped["untranslated"] += 1
                continue
            # The Japanese is measured at the AUTHOR's scale - that is what
            # defines the centre we are restoring - and the English at whatever
            # scale it will actually ship with.
            jw = drawn(jp, metrics, r)
            ew = drawn(en, metrics, r, scale_overrides.get(key))
            px = _f(r["posX"])
            new = px + (jw - ew) / 2.0
            if abs(new - px) < MIN_SHIFT_PX:
                skipped["shift below %.0fpx" % MIN_SHIFT_PX] += 1
                continue
            # Never push a label off the left edge of its own container. If the
            # arithmetic wants to, the group model is wrong for this widget.
            if new < 0:
                skipped["would go negative"] += 1
                continue
            out.append(("M:%s:%s:posX" % (r["nodeGuid"], r["idx"]),
                        "%.2f" % new,
                        {"node": r.get("node"), "idx": r["idx"], "jp": jp, "en": en,
                         "old": px, "new": new, "jp_px": jw, "en_px": ew,
                         "centre": grp["centre"]}))
    return out, skipped
