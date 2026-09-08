#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
title.py - redraw `img/titles1/_Title.png` in English.

The only image in this game with baked text. Every number below was MEASURED off
the source (`probe_title.py`, `probe_circle.py`, `probe_ink.py`), never
eyeballed:

    logo line 1  魔王ミネリアと (purple 114,1,146   fill x  23..486)
                 名もなき村の   (blue   0,96,223    fill x 494..885)
                 fill rows y 267..338, plate x 0..910, y 242..359
    logo line 2  エロトラップダンジョン (pink 235,0,114  fill x 214..990)
                 fill rows y 380..452, plate x 182..1020, y 364..470

The two plates are separated by only a 5px strip of collage, and the JP ink
overlaps plate edges, strip and collage alike.

Every glyph is drawn fill -> white ring -> heavy BLACK outer ring. Scanline
runs across the source measure the white at 9-11px and the black at 8-13px on
72px fill cores, and there is NO offset drop shadow anywhere - the first
English render drew one, and it read as a different logo pasted on.

## The erase covers the INK, not the fill

The full ink footprint extends ~25px past the fill core (white + black + AA).
The first render erased fill-core boxes +16px, and the box edges cut straight
through the black rings: ink pixels sitting ON the box boundary anchored the
diffusion (glyph-shaped smears across both plates), and everything past the
box survived untouched (black fragments in the strip between the plates and
under line 2). So the erase region is ONE box over the whole logo block, sized
from the fill cores + 30px, and the mask inside it is built so the boundary
rows are guaranteed clean.

White/black detection cannot run bare inside that box: the collage's own dark
tiles (the dungeon screenshot at x 180-330 touches the rings) and the
translucent plates themselves would join the mask - one draft erased half the
plate and the diffusion rebuilt it as raw collage. Three guards:
  * white means the RING's near-pure white (lum > 247), not the plate's
    lightened collage, and black stays nearly neutral (sat < 40),
  * the union is kept only where its connected component contains fill, and
  * nothing farther than 28px from a fill pixel is ever erased - the ink
    (11px white + 13px black + AA) physically cannot reach farther,
so the mask is exactly the logo - fill, rings, AA - and nothing else.

The fill runs in THREE stages because the plates must refill from themselves.
Where the JP ink was densest (魔王ミネリア covers its plate top to bottom)
almost no plate survives around the mask, and a single whole-box diffusion
pulls fire and sparkle from above and below the band straight through the
erased glyphs - a hole in the plate, not a repair. So: masked pixels inside
plate 1 diffuse in a box clipped to plate 1 (anchors are plate, so the fill is
plate), the same for plate 2, and only the leftover ink - ring tips on the
collage and the 5px strip - diffuses with full-context anchors.

## Why the English is THREE lines where the Japanese is two

The Japanese sets both lines at the same size and lets the character count
decide the width. English cannot: the subtitle is 44 characters against the
main line's 16, so one line drops it to 33px against 79 - a strip of type
floating in a 110px plate. Split at its own colour break it is two rows,
keeping the purple/blue split the Japanese has at と. Their black rings merge
slightly (gap = -outer), the way the source glyphs' rings merge into each
other, so the block reads as one unit.

## The English is STRETCHED to the Japanese ink footprint

Every pixel of English ink is a pixel of reconstruction nobody ever sees. The
plates were repaired under the erased glyphs, and repairs on display - however
smooth - is what "blurry" means; the JP never showed this problem because its
near-square kana fill the measure edge to edge. So each row is rendered at its
height-fitted size and then scaled horizontally onto the Japanese fill budget
(sx ~1.4 for the subtitle rows), and the main title is scaled vertically onto
the measured JP ink band (358..474). Extended heavy type also happens to read
much closer to dense square kana than natural-width Arial Black does. The
scale happens about the text anchor with LANCZOS, so placement math is
untouched and edges stay antialiased.

The subtitle block is centred on the Japanese line 1's centre (x 454) and the
main title on line 2's (x 602), so the composition keeps the source's
down-and-right cascade.

## The circle badge stays JAPANESE

さざめき通り in the bottom-left corner is the developer's circle name - a
brand mark, not game text - and it stays as shipped, per the user's call. An
earlier draft romanised it to "Sazameki-dori"; the measured badge geometry
lives in probe_circle.py if that is ever wanted again.
"""

import os
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import imgtl  # noqa: E402

SRC = os.path.join(HERE, "src", "_Title.png")
OUT = os.path.join(HERE, "out", "_Title.png")

PURPLE = (114, 1, 146)
BLUE = (0, 96, 223)
PINK = (235, 0, 114)
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)

FONT = r"C:\Windows\Fonts\ariblk.ttf"

# --- measured source geometry ---------------------------------------------
L1 = dict(y=(267, 338), x=(23, 885))          # fill cores, subtitle line
L2 = dict(y=(380, 452), x=(214, 990))         # fill cores, main line
PLATE1 = (0, 242, 910, 359)                   # translucent plates, exclusive
PLATE2 = (182, 364, 1020, 470)
INK_PAD = 30                                   # fill core -> ink + margin

# --- the English -----------------------------------------------------------
SUB_TOP = "Demon Lord Mineria"
SUB_BOTTOM = "and the Nameless Village's"
MAIN = "Ero Trap Dungeon"

# Total-ink band for the two subtitle rows. Top at the plate's top edge;
# bottom allows the black ring to dip ~2px past the plate, as the source's
# ring bottoms do (plate ends 359, ink measured to ~362).
SUB_BAND = (242, 361)

# The JP main line's total ink rows (fill 380..452 + rings). The English is
# scaled vertically onto this band so the repaired strip above the plate and
# the ring-dip zone below it stay covered by ink, as they were in the source.
MAIN_INK_BAND = (358, 474)

# Ring proportions, from the measured 9-11px white / 8-13px black on 72px
# cores. PIL draws one stroke per call, so black is a third pass at
# inner+outer.
RING_INNER = 0.13
RING_OUTER = 0.12


def rings_for(size):
    return max(4, round(size * RING_INNER)), max(4, round(size * RING_OUTER))


def logo_mask(im, box):
    """Boolean mask of BOTH logo lines inside `box`: fill hues, then white and
    black rings admitted only near and connected to fill. See the docstring."""
    import numpy as np
    from scipy import ndimage
    x0, y0 = box[0], box[1]
    a = np.asarray(im.crop(box).convert("RGB")).astype(np.int16)
    lum = a.mean(axis=2)
    sat = a.max(axis=2) - a.min(axis=2)

    fill = np.zeros(a.shape[:2], dtype=bool)
    for hues, core in (([PURPLE, BLUE], L1), ([PINK], L2)):
        hit = np.zeros_like(fill)
        for h in hues:
            hit |= np.abs(a - np.array(h, dtype=np.int16)).max(axis=2) <= 78
        # keep only components that touch this line's fill-core rect, so the
        # magenta dungeon-screenshot highlights cannot hue-match their way in
        lab, n = ndimage.label(hit)
        core_zone = np.zeros_like(hit)
        core_zone[core["y"][0] - y0:core["y"][1] - y0,
                  core["x"][0] - x0:core["x"][1] - x0] = True
        ids = set(np.unique(lab[hit & core_zone])) - {0}
        if ids:
            fill |= np.isin(lab, list(ids))

    dist = ndimage.distance_transform_edt(~fill)
    near = dist <= 28
    white = (lum > 247) & (sat < 16) & near
    black = (lum < 75) & (sat < 40) & near

    cat = ndimage.binary_dilation(fill | white | black, iterations=3)
    lab, n = ndimage.label(cat)
    ids = set(np.unique(lab[fill])) - {0}
    keep = np.isin(lab, list(ids))
    keep = ndimage.binary_dilation(keep, iterations=5) & near
    ink = int(keep.sum())
    if ink < 500:
        raise RuntimeError("logo mask consumed %d px - hard stop" % ink)
    return keep, ink


def _pass_layer(text, size, stroke, color):
    """One stroke pass on a tight layer, 'mm'-anchored. Returns the layer and
    the anchor's position inside it, so a later scale about the anchor keeps
    the placement math exact."""
    f = ImageFont.truetype(FONT, size)
    bb = f.getbbox(text, stroke_width=stroke, anchor="mm")
    m = 4
    ax, ay = m - bb[0], m - bb[1]
    layer = Image.new("RGBA", (bb[2] - bb[0] + 2 * m, bb[3] - bb[1] + 2 * m),
                      (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    if stroke:
        d.text((ax, ay), text, font=f, fill=color + (255,), anchor="mm",
               stroke_width=stroke, stroke_fill=color + (255,))
    else:
        d.text((ax, ay), text, font=f, fill=color + (255,), anchor="mm")
    return layer, ax, ay


def draw_logo_block(im, items):
    """Draw glyph rows in the source's style: for ALL rows, black outer ring
    first, then every white ring, then every fill - so rows whose rings merge
    read as one block, the way the source's characters merge.

    `items` is a list of (text, (cx, cy), fill_rgb, size, sx, sy). Each pass
    is rendered tight, scaled by (sx, sy) about the text anchor with LANCZOS,
    and composited at (cx, cy). Returns the union ink footprint as a boolean
    array, for the coverage report."""
    import numpy as np
    cover = np.zeros((im.height, im.width), dtype=bool)
    passes = [
        (lambda i, o, fill: (i + o, BLACK)),
        (lambda i, o, fill: (i, WHITE)),
        (lambda i, o, fill: (0, fill)),
    ]
    for p in passes:
        for text, (cx, cy), fill, size, sx, sy in items:
            inner, outer = rings_for(size)
            stroke, color = p(inner, outer, fill)
            layer, ax, ay = _pass_layer(text, size, stroke, color)
            if sx != 1.0 or sy != 1.0:
                layer = layer.resize((max(1, round(layer.width * sx)),
                                      max(1, round(layer.height * sy))),
                                     Image.LANCZOS)
                ax, ay = ax * sx, ay * sy
            px, py = round(cx - ax), round(cy - ay)
            im.alpha_composite(layer, (px, py))
            if color is BLACK:
                a = np.asarray(layer)[..., 3] > 0
                y0, x0 = max(0, py), max(0, px)
                y1 = min(im.height, py + a.shape[0])
                x1 = min(im.width, px + a.shape[1])
                cover[y0:y1, x0:x1] |= a[y0 - py:y1 - py, x0 - px:x1 - px]
    return cover


def fit(text, target_w, hi=160):
    """Largest size whose rendered FILL width fits. The rings extend past the
    budget symmetrically, exactly as the source's rings extend past its fill
    cores, so the budget is the fill-core width in both languages."""
    lo, best = 8, 8
    while lo <= hi:
        mid = (lo + hi) // 2
        f = ImageFont.truetype(FONT, mid)
        b = f.getbbox(text)
        if b[2] - b[0] <= target_w:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def ink_extent(text, size, stroke):
    """(top, bottom) of the ACTUAL rendered ink relative to a 'mm' anchor.

    A font's em box is not what lands on the plate. "Demon Lord Mineria" has no
    descender at all, so its ink is far shorter than `size * 1.12` would
    suggest. Render it and look."""
    f = ImageFont.truetype(FONT, size)
    pad = size * 2 + stroke * 4
    probe = Image.new("L", (int(f.getbbox(text)[2] + pad), int(pad)), 0)
    d = ImageDraw.Draw(probe)
    cy = probe.height / 2.0
    d.text((pad / 2.0, cy), text, font=f, fill=255, anchor="lm",
           stroke_width=stroke, stroke_fill=255)
    bb = probe.getbbox()
    if bb is None:
        return 0.0, 0.0
    return bb[1] - cy, bb[3] - cy


def fit_two_rows(top, bottom, width, band):
    """Widest common WIDTH at which the two rows' rendered ink blocks (rings
    included) stack inside `band`. Each row gets its own size - a common size
    leaves the 18-character top row at 61% of the 26-character bottom row, and
    the Japanese look is lines that fill their measure.

    The gap is -outer: the black rings overlap by half their own width, the
    white rings stay separated, and the pair reads as one merged block like
    the source's glyphs. Returns (size_top, size_bottom, cy_top, cy_bottom)."""
    band_h = band[1] - band[0]
    for w in range(width, 200, -4):
        s1, s2 = fit(top, w), fit(bottom, w)
        i1, o1 = rings_for(s1)
        i2, o2 = rings_for(s2)
        gap = -min(o1, o2)
        ta, ba = ink_extent(top, s1, i1 + o1)
        tb, bb = ink_extent(bottom, s2, i2 + o2)
        need = (ba - ta) + (bb - tb) + gap
        if need > band_h:
            continue
        slack = (band_h - need) / 2.0
        cy_a = band[0] + slack - ta
        cy_b = cy_a + ba + gap - tb
        return s1, s2, cy_a, cy_b
    return 8, 8, band[0] + band_h * 0.3, band[0] + band_h * 0.7


# The collage includes a screenshot of the game's own map HUD, and its 魔力
# label is 25x11 px of real Japanese on the title screen. The patch renames that
# gauge to "Mana", so leaving it here would put two names for one gauge on the
# first screen a player sees. Measured bbox, sampled plate colour, no guessing.
HUD_BOX = (24, 398, 52, 411)
HUD_PLATE = (47, 43, 64)
HUD_INK = (196, 218, 255)          # RPG Maker's systemColor, as it reads here
HUD_TEXT = "Mana"


def patch_hud(im):
    d = ImageDraw.Draw(im)
    d.rectangle(HUD_BOX, fill=HUD_PLATE + (255,))
    w = HUD_BOX[2] - HUD_BOX[0]
    h = HUD_BOX[3] - HUD_BOX[1]
    size = 12
    while size > 6:
        f = ImageFont.truetype(r"C:\Windows\Fonts\arialbd.ttf", size)
        b = f.getbbox(HUD_TEXT)
        if b[2] - b[0] <= w - 2 and b[3] - b[1] <= h - 1:
            break
        size -= 1
    d.text((HUD_BOX[0] + 1, HUD_BOX[1] + h / 2.0), HUD_TEXT, font=f,
           fill=HUD_INK + (255,), anchor="lm")


def main():
    im = Image.open(SRC).convert("RGBA")

    # --- erase --------------------------------------------------------------
    # One box over the whole logo block, sized fill-cores + INK_PAD so every
    # boundary row is clean - a boundary that cuts through ink anchors the
    # diffusion and smears ghosts across the plate.
    logo_box = (max(0, L1["x"][0] - INK_PAD), max(0, L1["y"][0] - INK_PAD),
                min(im.width, max(L1["x"][1], L2["x"][1]) + INK_PAD),
                min(im.height, L2["y"][1] + INK_PAD))

    m_logo, n_logo = logo_mask(im, logo_box)
    print("mask consumed: logo block %d px" % n_logo)

    # Three-stage fill: each plate refills from ITSELF, then the leftovers
    # (ring tips on collage, the 5px strip between the plates) refill with
    # full context. See the docstring.
    import numpy as np
    lx0, ly0 = logo_box[0], logo_box[1]
    work = im.copy()
    rest = m_logo.copy()
    for plate in (PLATE1, PLATE2):
        px0, py0, px1, py1 = plate
        sub = m_logo[py0 - ly0:py1 - ly0, px0 - lx0:px1 - lx0]
        if sub.any():
            imgtl.inpaint_diffuse(work, plate, sub, smooth=1.6, iters=1500)
        rest[py0 - ly0:py1 - ly0, px0 - lx0:px1 - lx0] = False
    if rest.any():
        imgtl.inpaint_diffuse(work, logo_box, rest, smooth=1.6, iters=1500)

    # --- subtitle: two rows stretched onto the JP fill budget ---------------
    sub_w = L1["x"][1] - L1["x"][0]
    s_top, s_bot, cy_a, cy_b = fit_two_rows(SUB_TOP, SUB_BOTTOM, sub_w,
                                            SUB_BAND)
    ft = ImageFont.truetype(FONT, s_top)
    fb = ImageFont.truetype(FONT, s_bot)
    w_top = ft.getbbox(SUB_TOP)[2] - ft.getbbox(SUB_TOP)[0]
    w_bot = fb.getbbox(SUB_BOTTOM)[2] - fb.getbbox(SUB_BOTTOM)[0]
    sx_top = min(1.5, sub_w / float(w_top))
    sx_bot = min(1.5, sub_w / float(w_bot))
    cx_sub = (L1["x"][0] + L1["x"][1]) / 2.0
    cover = draw_logo_block(work, [
        (SUB_TOP, (cx_sub, cy_a), PURPLE, s_top, sx_top, 1.0),
        (SUB_BOTTOM, (cx_sub, cy_b), BLUE, s_bot, sx_bot, 1.0)])

    # --- main title, stretched onto the JP ink band -------------------------
    main_w = L2["x"][1] - L2["x"][0]
    main_h = L2["y"][1] - L2["y"][0]
    size_main = min(fit(MAIN, main_w), int(main_h * 1.15))
    fm = ImageFont.truetype(FONT, size_main)
    w_main = fm.getbbox(MAIN)[2] - fm.getbbox(MAIN)[0]
    sx_main = min(1.5, main_w / float(w_main))
    im_, om_ = rings_for(size_main)
    ta_m, bb_m = ink_extent(MAIN, size_main, im_ + om_)
    sy_main = min(1.18, (MAIN_INK_BAND[1] - MAIN_INK_BAND[0])
                  / float(bb_m - ta_m))
    cx_main = (L2["x"][0] + L2["x"][1]) / 2.0
    # centre the STRETCHED ink on the JP ink band, not the em box on the plate
    cy_main = (MAIN_INK_BAND[0] + MAIN_INK_BAND[1]) / 2.0 \
        - sy_main * (ta_m + bb_m) / 2.0
    cover |= draw_logo_block(work, [
        (MAIN, (cx_main, cy_main), PINK, size_main, sx_main, sy_main)])

    # The circle badge さざめき通り (bottom left) is the developer's brand
    # mark and stays Japanese on purpose.

    patch_hud(work)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    work.convert("RGBA").save(OUT)

    # Coverage: how much of the REPAIRED area still shows. Exposed repair on
    # the plates is smooth and invisible; exposed repair on the collage or the
    # strip is the "blurry parts", so that number is the one to watch.
    import numpy as np
    lx0_, ly0_ = logo_box[0], logo_box[1]
    exposed = m_logo & ~cover[ly0_:logo_box[3], lx0_:logo_box[2]]
    on_plate = np.zeros_like(exposed)
    for px0, py0, px1, py1 in (PLATE1, PLATE2):
        on_plate[py0 - ly0_:py1 - ly0_, px0 - lx0_:px1 - lx0_] = True
    print("repair exposed: %d px on the plates (smooth), %d px on collage"
          % (int((exposed & on_plate).sum()),
             int((exposed & ~on_plate).sum())))

    print("subtitle  sizes %2d/%2d  sx %.2f/%.2f  rows at y %.0f / %.0f  "
          "stretched widths %d / %d (budget %d)"
          % (s_top, s_bot, sx_top, sx_bot, cy_a, cy_b,
             round(w_top * sx_top), round(w_bot * sx_bot), sub_w))
    print("main      size %2d  sx %.2f  sy %.2f  ink y %.0f..%.0f "
          "(JP band %d..%d)"
          % (size_main, sx_main, sy_main,
             cy_main + ta_m * sy_main, cy_main + bb_m * sy_main,
             MAIN_INK_BAND[0], MAIN_INK_BAND[1]))
    print("wrote", OUT)

    deploy = os.path.join(os.path.dirname(HERE), "out", "img", "titles1",
                          "_Title.png")
    os.makedirs(os.path.dirname(deploy), exist_ok=True)
    work.convert("RGBA").save(deploy)
    print("deployed", deploy)


if __name__ == "__main__":
    main()
