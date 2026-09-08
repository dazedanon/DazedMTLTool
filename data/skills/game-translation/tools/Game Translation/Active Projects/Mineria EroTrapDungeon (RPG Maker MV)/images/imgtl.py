"""imgtl.py - PIL toolkit for translating text baked into game images.

Proven on the Asuka Virgin Idol Debut image set (36 images: transparent overlays,
paper-texture pages, dark gradient panels, speech bubbles, logos, glow cut-ins,
hand-drawn sketches, autographs) and on Estel the Acrobatic Angel (RPG Maker MZ,
1,301 of 3,391 pictures: plate labels, multi-field cards, quest prose, battle
cut-in dialogue, text over portraits). Companion doc: the game-translation
skill's references/image-translation.md - read it for the workflow and the edge
cases each helper exists for.

Needs numpy; the glyph-mask and inpaint helpers also need scipy.

Usage: copy next to your per-game scripts, set SRC/OUT, then
    import sys; sys.path.insert(0, '.')
    from imgtl import *
"""
import os
from statistics import median
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# Set these per game before using load()/save().
SRC = r""   # folder with the ORIGINAL images (never written to)
OUT = r""   # folder the translated copies are written to

F = r"C:/Windows/Fonts"
FONTS = {
    # sans (gothic JP -> these)
    "arial": f"{F}/arial.ttf", "arialbd": f"{F}/arialbd.ttf",
    "arialbi": f"{F}/arialbi.ttf", "ariblk": f"{F}/ariblk.ttf",
    "impact": f"{F}/impact.ttf",
    "verdanab": f"{F}/verdanab.ttf", "verdanaz": f"{F}/verdanaz.ttf",
    "tahomabd": f"{F}/tahomabd.ttf", "trebucbd": f"{F}/trebucbd.ttf",
    "seguibl": f"{F}/seguibl.ttf", "seguibli": f"{F}/seguibli.ttf",
    # monospace italic (matches the JP-gothic-italic calendar look)
    "consolab": f"{F}/consolab.ttf", "consolaz": f"{F}/consolaz.ttf",
    # serif (Mincho JP -> these)
    "timesbd": f"{F}/timesbd.ttf", "georgiab": f"{F}/georgiab.ttf",
    # handwriting / signatures
    "segoepr": f"{F}/segoepr.ttf", "segoeprb": f"{F}/segoeprb.ttf",
    "segoesc": f"{F}/segoesc.ttf", "segoescb": f"{F}/segoescb.ttf",
    "inkfree": f"{F}/Inkfree.ttf", "comicbd": f"{F}/comicbd.ttf",
}


def font(name, size):
    return ImageFont.truetype(FONTS[name], size)


def jp_font(size, bold=False):
    """MS Gothic via ttc index - PIL has NO font fallback, so use this for any
    symbol Latin fonts lack (■ ★ ☆ ♪ ♡ ○ ● 　...)."""
    return ImageFont.truetype(f"{F}/msgothic.ttc", size, index=0)


def load(name):
    """Original image (read-only source). Always re-edit from SOURCE after a
    botched attempt - never stack fixes onto a damaged output."""
    return Image.open(os.path.join(SRC, name)).convert("RGBA")


def load_out(name):
    """Current output - ONLY for purely additive follow-up patches."""
    return Image.open(os.path.join(OUT, name)).convert("RGBA")


def save(img, name):
    img.save(os.path.join(OUT, name))
    print("wrote", os.path.join(OUT, name))


# --------------------------------------------------------------------------
# probing (never eyeball coordinates - measure)
# --------------------------------------------------------------------------
def alpha_range(img):
    """(min,max) alpha. min<255 means 'white' background is actually
    TRANSPARENT: erase with clear_rect, never fill_rect white."""
    return img.getchannel("A").getextrema()


def ink_bbox(img, thr=40, step=1):
    """bbox of non-transparent pixels (transparent-canvas images)."""
    px = img.load()
    xs, ys = [], []
    for y in range(0, img.height, step):
        for x in range(0, img.width, step):
            if px[x, y][3] > thr:
                xs.append(x)
                ys.append(y)
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def ybands(img, x0, x1, y0, y1, pred, min_gap=4):
    """Consecutive rows where pred(pixel) holds anywhere in x0..x1 -> text-line
    bands [(ya,yb)]. pred examples:
      dark  = lambda p: p[3]>150 and (p[0]+p[1]+p[2])/3 < 130
      white = lambda p: p[3]>150 and (p[0]+p[1]+p[2])/3 > 195"""
    px = img.load()
    rows = [any(pred(px[x, y]) for x in range(x0, x1)) for y in range(y0, y1)]
    out, i = [], 0
    while i < len(rows):
        if rows[i]:
            s = i; e = i; gap = 0
            while i < len(rows):
                if rows[i]:
                    e = i; gap = 0
                else:
                    gap += 1
                    if gap >= min_gap:
                        break
                i += 1
            out.append((y0 + s, y0 + e))
        i += 1
    return out


def xclusters(img, x0, x1, y0, y1, pred, min_gap=6):
    """Column clusters of ink within a y-band -> [(xa,xb)] per word/symbol.
    Use to find a leading symbol (○■★) so it can be KEPT while the text after
    it is replaced."""
    px = img.load()
    cols = [any(pred(px[x, y]) for y in range(y0, y1)) for x in range(x0, x1)]
    out, i = [], 0
    while i < len(cols):
        if cols[i]:
            s = i; e = i; gap = 0
            while i < len(cols):
                if cols[i]:
                    e = i; gap = 0
                else:
                    gap += 1
                    if gap >= min_gap:
                        break
                i += 1
            out.append((x0 + s, x0 + e))
        i += 1
    return out


def zoom(img, box, scale, path):
    """Write an upscaled crop for visual inspection (compose transparent images
    onto a mid-gray so white halos/outlines are visible)."""
    crop = img.crop(box)
    bg = Image.new("RGBA", crop.size, (128, 128, 128, 255))
    bg.alpha_composite(crop)
    w, h = crop.size
    bg.convert("RGB").resize((w * scale, h * scale), Image.LANCZOS).save(path)


# --------------------------------------------------------------------------
# erasing (pick by background type; boxes are INCLUSIVE of x1,y1 in PIL!)
# --------------------------------------------------------------------------
def clear_rect(img, box):
    """Transparent canvas -> erase to alpha 0."""
    ImageDraw.Draw(img).rectangle(box, fill=(0, 0, 0, 0))


def fill_rect(img, box, color):
    """Flat opaque background (sample the exact color first)."""
    ImageDraw.Draw(img).rectangle(box, fill=color)


def patch_rect(img, box, src_xy):
    """Copy a same-size clean patch over box. For textures with VERTICAL
    stripes keep src x == box x (same columns, different rows)."""
    x0, y0, x1, y1 = box
    img.paste(img.crop((src_xy[0], src_xy[1],
                        src_xy[0] + (x1 - x0), src_xy[1] + (y1 - y0))), (x0, y0))


def tile_paper(img, box, srcbox):
    """Tile a VERIFIED-CLEAN patch over box (low-contrast paper noise hides
    seams). The one hard rule: srcbox must contain nothing but texture - a
    source band that clips a panel edge stamps dark streaks everywhere."""
    tile = img.crop(srcbox)
    tw, th = tile.size
    x0, y0, x1, y1 = box
    for ty in range(y0, y1, th):
        for tx in range(x0, x1, tw):
            img.paste(tile.crop((0, 0, min(tw, x1 - tx), min(th, y1 - ty))), (tx, ty))


def rowfill(img, box, sx0, sx1, skip=lambda p: False):
    """Vertical-gradient panels: fill each row with the median color sampled
    from clean columns sx0..sx1 of the SAME row. skip() excludes overlay pixels
    (e.g. red tutorial circles) from the sample."""
    px = img.load()
    for y in range(box[1], box[3]):
        cols = [px[x, y] for x in range(sx0, sx1) if not skip(px[x, y])]
        if not cols:
            cols = [px[sx0, y]]
        c = (int(median(p[0] for p in cols)), int(median(p[1] for p in cols)),
             int(median(p[2] for p in cols)), 255)
        for x in range(box[0], box[2]):
            px[x, y] = c


# --------------------------------------------------------------------------
# overlay preservation (tutorial circles / arrows drawn OVER text)
# --------------------------------------------------------------------------
def snap_pixels(img, boxes, pred):
    """Snapshot overlay pixels (e.g. red circles: p[0]>170 and p[1]<70 and
    p[2]<70) inside the edit boxes BEFORE erasing."""
    px = img.load()
    out = []
    for (x0, y0, x1, y1) in boxes:
        for y in range(y0, y1):
            for x in range(x0, x1):
                if pred(px[x, y]):
                    out.append((x, y, px[x, y]))
    return out


def restore_pixels(img, snap):
    """Re-stamp the snapshot AFTER text is drawn - overlay ends up on top,
    exactly like the original draw order."""
    px = img.load()
    for x, y, c in snap:
        px[x, y] = c


# --------------------------------------------------------------------------
# text rendering
# --------------------------------------------------------------------------
def text(img, xy, s, fname, size, fill, stroke=0, stroke_fill=None,
         anchor="la", spacing=4, align="left"):
    """Plain / outlined text. anchor 'lm'=left-middle of a band, 'mm'=center,
    'rm'=right-align, 'ls'=baseline (for clipped sliver headings)."""
    ImageDraw.Draw(img).text(xy, s, font=font(fname, size), fill=fill,
                             stroke_width=stroke, stroke_fill=stroke_fill,
                             anchor=anchor, spacing=spacing, align=align)


def fit_size(s, fname, target_w, max_size=72):
    """Largest font size whose rendered width fits target_w - measure, never
    guess (JP->EN typically expands 1.3-2x)."""
    d = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    w = d.textbbox((0, 0), s, font=font(fname, 100))[2]
    return min(max_size, int(100 * target_w / w))


def text_width(s, fname, size):
    d = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    return d.textbbox((0, 0), s, font=font(fname, size))[2]


def glow_text(img, xy, s, fname, size, core=(255, 255, 255, 255),
              glow=(255, 0, 0, 255), radius=6, passes=3, anchor="la"):
    """Cut-in style: colored halo (blurred stroked copies) + thin colored edge
    + solid core on top."""
    base = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(base)
    d.text(xy, s, font=font(fname, size), fill=glow, anchor=anchor,
           stroke_width=max(2, radius // 3), stroke_fill=glow)
    halo = base.filter(ImageFilter.GaussianBlur(radius))
    for _ in range(passes - 1):
        halo = Image.alpha_composite(halo, base.filter(ImageFilter.GaussianBlur(radius)))
    img.alpha_composite(halo)
    edge = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(edge).text(xy, s, font=font(fname, size), fill=glow,
                              anchor=anchor, stroke_width=2, stroke_fill=glow)
    img.alpha_composite(edge.filter(ImageFilter.GaussianBlur(1)))
    ImageDraw.Draw(img).text(xy, s, font=font(fname, size), fill=core, anchor=anchor)


def shadow_text(img, xy, s, fname, size, fill, shadow=(70, 70, 70, 160),
                offset=(2, 2), blur=1.0, anchor="la"):
    """Soft drop shadow + text (subtitles on light/transparent canvases)."""
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).text(xy, s, font=font(fname, size), fill=shadow, anchor=anchor)
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(blur)), dest=offset)
    ImageDraw.Draw(img).text(xy, s, font=font(fname, size), fill=fill, anchor=anchor)


def vgrad(size_wh, top, bottom):
    w, h = size_wh
    g = Image.new("RGBA", (1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        g.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t)
                                 for i in range(3)) + (255,))
    return g.resize((w, h))


def logo_text(img, center_xy, s, fname, size, grad_top, grad_bottom,
              outline_color, outline_w, shadow_color, shadow_off,
              shear=0.22, rotate=0.0):
    """Slot/event logo: gradient fill through a text mask, thick light outline,
    hard offset shadow, italic shear, slight rotation. Sample grad/outline/
    shadow colors from the ORIGINAL glyph pixels (top rows vs bottom rows)."""
    f = font(fname, size)
    d = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    bbox = d.textbbox((0, 0), s, font=f)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad = outline_w + abs(shadow_off[0]) + abs(shadow_off[1]) + int(th * abs(shear)) + 24
    W, H = tw + pad * 2, th + pad * 2

    def mask(stroke):
        m = Image.new("L", (W, H), 0)
        ImageDraw.Draw(m).text((pad - bbox[0], pad - bbox[1]), s, font=f, fill=255,
                               stroke_width=stroke, stroke_fill=255)
        return m

    fill_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    fill_layer.paste(vgrad((W, H), grad_top, grad_bottom), (0, 0), mask(0))
    outline_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    outline_layer.paste(Image.new("RGBA", (W, H), outline_color), (0, 0), mask(outline_w))
    shadow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shadow_layer.paste(Image.new("RGBA", (W, H), shadow_color), (0, 0), mask(outline_w + 2))

    combo = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    combo.alpha_composite(shadow_layer, dest=shadow_off)
    combo.alpha_composite(outline_layer)
    combo.alpha_composite(fill_layer)
    if shear:
        combo = combo.transform((W + int(H * abs(shear)), H), Image.AFFINE,
                                (1, shear, -shear * H if shear > 0 else 0, 0, 1, 0),
                                resample=Image.BICUBIC)
    if rotate:
        combo = combo.rotate(rotate, resample=Image.BICUBIC, expand=True)
    combo = combo.crop(combo.getbbox())
    img.alpha_composite(combo, dest=(center_xy[0] - combo.width // 2,
                                     center_xy[1] - combo.height // 2))


# --------------------------------------------------------------------------
# coordinate reading
# --------------------------------------------------------------------------
def grid(img, box, scale, path, step=20, bg=(120, 120, 128, 255)):
    """zoom() plus labelled x/y gridlines. Reach for this BEFORE writing a probe:
    for a one-off layout it is faster to read two numbers off the picture than to
    write a detector, and it is how you hardcode a table when a detector keeps
    trading one family's correctness for another's."""
    crop = img.crop(box)
    b = Image.new("RGBA", crop.size, bg)
    b.alpha_composite(crop)
    w, h = crop.size
    im = b.convert("RGB").resize((w * scale, h * scale), Image.LANCZOS)
    d = ImageDraw.Draw(im)
    f = ImageFont.truetype(FONTS["arialbd"], 12)
    for x in range(box[0] - box[0] % step, box[2], step):
        X = (x - box[0]) * scale
        d.line([(X, 0), (X, im.height)], fill=(255, 0, 0), width=1)
        d.text((X + 2, 2), str(x), font=f, fill=(255, 80, 80))
    for y in range(box[1] - box[1] % step, box[3], step):
        Y = (y - box[1]) * scale
        d.line([(0, Y), (im.width, Y)], fill=(0, 160, 255), width=1)
        d.text((2, Y + 2), str(y), font=f, fill=(80, 200, 255))
    im.save(path)


# --------------------------------------------------------------------------
# classifying a large set
# --------------------------------------------------------------------------
def family_key(img, bbox, cells=24):
    """(bbox, alpha-silhouette hash) - identical across lit/dimmed/selected
    states of one widget and different across artworks, so it groups state
    variants that no filename convention catches. Group a folder by this and you
    get one representative per geometry to classify, and one erase recipe to
    write.

    Hash the SILHOUETTE, not the opacity. Any finer quantisation puts a cell on
    a bucket boundary and splits the family: measured over five known lit/dimmed
    pairs, a three-level empty/partial/solid key grouped 2 of 5 (one plate sits
    at alpha 250 lit and 251 dimmed), a plain silhouette grouped 5 of 5 with no
    wrong merges.

    A fully opaque image has no silhouette, so every full-screen card would hash
    alike - 354 unrelated cards landed in one family before this fallback. There,
    key off a dhash of the luminance instead: it compares neighbouring cells
    rather than absolute values, so it survives the brightness shift between a
    lit and a dimmed state while still separating different artwork.

    Bias toward splitting either way. A split family costs one extra
    representative to look at; a wrong merge silently applies one widget's erase
    recipe to another."""
    import hashlib
    crop = img.crop(bbox)
    a = np.asarray(crop.getchannel("A").resize((cells, cells), Image.BILINEAR))
    sil = a > 24
    if sil.mean() < 0.98:
        return (tuple(bbox), "a" + hashlib.md5(sil.tobytes()).hexdigest()[:11])
    g = np.asarray(crop.convert("L").resize((cells + 1, cells), Image.BILINEAR), dtype=np.int16)
    d = g[:, 1:] > g[:, :-1]
    return (tuple(bbox), "l" + hashlib.md5(d.tobytes()).hexdigest()[:11])


def _runs(flags, gap=0, minlen=1):
    out, i, n = [], 0, len(flags)
    while i < n:
        if flags[i]:
            s = e = i
            g = 0
            while i < n:
                if flags[i]:
                    e = i
                    g = 0
                else:
                    g += 1
                    if g > gap:
                        break
                i += 1
            if e - s + 1 >= minlen:
                out.append((s, e))
        i += 1
    return out


def cjk_lines(img, box=None, masks=None, light_thr=214, dark_thr=66,
              min_h=11, max_h=130, athr=120):
    """Rows of ink whose column profile splits into SQUARE, equal-size groups -
    the shape CJK type makes and proportional Latin type does not. Returns
    [(x0, y0, x1, y1, n_square)].

    Use it to RANK candidates and, run over the outputs, as a residual-Japanese
    gate. Never use it to exclude: it misses text over artwork (the ink mask is
    polluted), two-glyph labels, and anything proportional.

    light_thr/dark_thr must match the game's real ink. Cream type at
    (219,203,168) has a min channel of 168 and is invisible to the 214 default,
    so sample a few families first or pass your own masks."""
    box = box or (0, 0, img.width, img.height)
    a = np.asarray(img.crop(box)).astype(np.int16)
    op = a[..., 3] > athr
    if masks is None:
        masks = [op & (a[..., :3].min(2) >= light_thr),
                 op & (a[..., :3].max(2) <= dark_thr)]
    out = []
    for m in masks:
        if not m.any():
            continue
        rows = m.sum(1) > max(1, int(m.shape[1] * 0.0008))
        for y0, y1 in _runs(rows, gap=2):
            h = y1 - y0 + 1
            if not (min_h <= h <= max_h):
                continue
            sub = m[y0:y1 + 1]
            # split on a SMALL gap, then re-merge neighbours only while the
            # result still fits one square glyph. A generous gap merges adjacent
            # kanji into one wide blob (mincho labels are set nearly touching)
            # and the square test then rejects the whole line; a small gap alone
            # would shatter multi-stroke glyphs like 川.
            parts = [g for g in _runs(sub.any(0), gap=2) if g[1] - g[0] + 1 >= 2]
            groups = []
            for p in parts:
                if groups and (p[1] - groups[-1][0] + 1) <= 1.35 * h:
                    groups[-1] = (groups[-1][0], p[1])
                else:
                    groups.append(p)
            groups = [g for g in groups if g[1] - g[0] + 1 >= 3]
            if len(groups) < 2:
                continue
            sq = 0
            for ga, gb in groups:
                w = gb - ga + 1
                if not (0.62 * h <= w <= 1.32 * h):
                    continue
                if 0.10 <= sub[:, ga:gb + 1].mean() <= 0.80:
                    sq += 1
            if sq >= 2:
                out.append((box[0] + groups[0][0], box[1] + y0,
                            box[0] + groups[-1][1], box[1] + y1, sq))
    return out


# --------------------------------------------------------------------------
# erasing text that sits on art you must keep
# --------------------------------------------------------------------------
def _ring(a, op, core, dark_delta, halo, grow):
    from scipy import ndimage as ndi
    lum = a[..., :3].mean(2)
    rest = op & ~core
    base = float(np.median(lum[rest])) if rest.any() else 0.0
    if dark_delta is None:
        m = core
    else:
        k = np.ones((halo * 2 + 1, halo * 2 + 1), bool)
        m = core | (ndi.binary_dilation(core, k) & op & (np.abs(lum - base) > dark_delta))
    if grow:
        m = ndi.binary_dilation(m, np.ones((grow * 2 + 1, grow * 2 + 1), bool))
    return m


def glyph_mask(img, box, *, delta=40, dark_delta=20, halo=4, grow=2, athr=60,
               polarity="auto", max_frac=0.62):
    """Adaptive glyph mask: ink is whatever stands off the plate's own median
    luminance. The workhorse for flat and gently textured plates.

    POLARITY IS THE TRAP. A bright-only mask over dark-on-cream returns EMPTY,
    the erase becomes a no-op, and the English is drawn on top of the Japanese
    with every check still passing. auto computes both cores and keeps the one
    with a plausible ink fraction. Assert mask.sum() before you draw."""
    a = np.asarray(img.crop(box)).astype(np.int16)
    op = a[..., 3] > athr
    if not op.any():
        return np.zeros(a.shape[:2], bool)
    lum = a[..., :3].mean(2)
    base = float(np.median(lum[op]))
    bright = op & (lum - base > delta)
    dark = op & (base - lum > delta)
    if polarity == "bright":
        core = bright
    elif polarity == "dark":
        core = dark
    else:
        ok = [c for c in (bright, dark) if 0.004 <= c.mean() <= max_frac]
        core = ok[0] if len(ok) == 1 else (bright if bright.sum() >= dark.sum() else dark)
    if not core.any():
        return core
    return _ring(a, op, core, dark_delta, halo, grow)


def glyph_mask_pure(img, box, *, thr=228, dark=False, dark_delta=22, halo=4,
                    grow=1, athr=60):
    """Mask keyed on a PURE tone (near-white by default) instead of a delta.
    Use over portraits and busy art, where a delta mask eats eye whites and skin
    highlights and the inpaint then drags them across the picture.

    For a soft drop shadow use dark_delta about 10 with halo about 10: a
    core-only mask leaves the shadow as dark blobs around the new text, which
    reads as smearing and sends you hunting the wrong bug."""
    a = np.asarray(img.crop(box)).astype(np.int16)
    op = a[..., 3] > athr
    core = op & ((a[..., :3].max(2) <= thr) if dark else (a[..., :3].min(2) >= thr))
    if not core.any():
        return core
    return _ring(a, op, core, dark_delta, halo, grow)


def inpaint_rows(img, box, mask, passes=2):
    """Fill masked pixels by interpolating along each row between the nearest
    unmasked neighbours. Exact over flat fills and horizontal banding, and the
    wrong choice over anything with slope - it turns a diagonal streak into
    horizontal stripes, which is the usual cause of 'why does this look smeared'."""
    a = np.asarray(img).astype(np.float64).copy()
    x0, y0 = box[0], box[1]
    H, W = mask.shape
    for _ in range(passes):
        for r in range(H):
            row = mask[r]
            if not row.any():
                continue
            y = y0 + r
            idx = np.where(row)[0]
            for run in np.split(idx, np.where(np.diff(idx) > 1)[0] + 1):
                s, e = run[0], run[-1]
                lx = s - 1
                while lx >= 0 and row[lx]:
                    lx -= 1
                rx = e + 1
                while rx < W and row[rx]:
                    rx += 1
                lv = a[y, x0 + lx] if lx >= 0 else None
                rv = a[y, x0 + rx] if rx < W else None
                if lv is None and rv is None:
                    continue
                lv = rv if lv is None else lv
                rv = lv if rv is None else rv
                n = e - s + 2
                for k, xx in enumerate(range(s, e + 1), start=1):
                    t = k / float(n)
                    a[y, x0 + xx] = lv * (1 - t) + rv * t
    img.paste(Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGBA"), (0, 0))
    return img


def inpaint_diffuse(img, box, mask, *, smooth=1.2, iters=800):
    """Fill masked pixels by propagating colour inward from every side, then
    smoothing inside the mask only. Follows diagonal streaks, gradients and
    portrait edges that inpaint_rows() would smear into stripes."""
    from scipy.ndimage import convolve, gaussian_filter
    a = np.asarray(img.crop(box)).astype(np.float64)
    cur = a.copy()
    cur[mask] = 0.0
    valid = (~mask).astype(np.float64)
    k = np.array([[1., 1., 1.], [1., 0., 1.], [1., 1., 1.]])
    for _ in range(iters):
        todo = valid < 0.5
        if not todo.any():
            break
        den = convolve(valid, k, mode="nearest")
        fill = todo & (den > 0)
        if not fill.any():
            break
        for c in range(4):
            num = convolve(cur[..., c] * valid, k, mode="nearest")
            cur[..., c][fill] = num[fill] / den[fill]
        valid[fill] = 1.0
    if smooth:
        sm = np.stack([gaussian_filter(cur[..., c], smooth) for c in range(4)], -1)
        cur[mask] = sm[mask]
    out = np.asarray(img).astype(np.float64).copy()
    out[box[1]:box[3], box[0]:box[2]] = cur
    img.paste(Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGBA"), (0, 0))
    return img


def sibling_clean(crops, masks, spread_thr=14):
    """Rebuild shared background from a family of variants that differ only by
    their text. Returns (clean_rgba, unreliable) for the box the crops share.

    Each variant's own glyphs are held out, so the median sees only clean pixels.
    `unreliable` marks pixels where the siblings DISAGREE - that is per-variant
    art (a portrait), not shared background, and pasting the median there drops
    one character's face into another's card. Inpaint those instead."""
    stack = np.stack([np.asarray(c).astype(np.float64) for c in crops])
    for i, m in enumerate(masks):
        stack[i][m] = np.nan
    with np.errstate(all="ignore"):
        med = np.nanmedian(stack, axis=0)
        spread = np.nanstd(stack, axis=0)[..., :3].mean(2)
    unreliable = np.isnan(med[..., 0]) | (np.nan_to_num(spread) > spread_thr)
    clean = Image.fromarray(np.clip(np.nan_to_num(med), 0, 255).astype(np.uint8), "RGBA")
    return clean, unreliable


def apply_clean(img, box, clean, mask, unreliable):
    """Paste sibling-derived background over this variant's own glyphs only, then
    inpaint the pixels the siblings could not agree on."""
    a = np.asarray(img.crop(box)).copy()
    use = mask & ~unreliable
    a[use] = np.asarray(clean)[use]
    img.paste(Image.fromarray(a, "RGBA"), (box[0], box[1]))
    rest = mask & unreliable
    if rest.any():
        inpaint_diffuse(img, box, rest, smooth=1.0)
    return img


def rowclip_fill(img, box, is_plate, fill=None):
    """Repaint only between the first and last plate-tone pixel of each row, so
    rounded corners, torn edges and slanted trapezoid sides survive. This is what
    makes plate detection stop mattering - see the label-plate section."""
    from collections import Counter
    px = img.load()
    x0, y0, x1, y1 = box
    for y in range(y0, y1):
        run = [x for x in range(x0, x1) if is_plate(px[x, y])]
        if not run:
            continue
        a, b = min(run), max(run)
        if fill is None:
            c = Counter(px[x, y] for x in range(a, b + 1) if is_plate(px[x, y]))
            col = c.most_common(1)[0][0]
        else:
            col = fill
        for x in range(a, b + 1):
            px[x, y] = col


# --------------------------------------------------------------------------
# multi-colour body text
# --------------------------------------------------------------------------
def rich_text(img, s, box, fname, *, hi=22, lo=12, colour=(60, 38, 32, 255),
              accent=(214, 52, 52, 255), lead=1.30, max_lines=8, mark="<r>"):
    """Wrap and draw body text carrying inline emphasis runs, shrinking to fit.
    Write the source as 'plain <r>emphasised</r> plain'. Japanese UI prose marks
    the actionable clause in a second colour, and dropping that loses the only
    cue telling the player where to go."""
    import re as _re
    close = mark.replace("<", "</")
    on = False
    words = []
    for part in _re.split("(%s|%s)" % (_re.escape(mark), _re.escape(close)), s):
        if part == mark:
            on = True
        elif part == close:
            on = False
        elif part:
            words += [(w, on) for w in part.split(" ") if w]
    # A run boundary mid-sentence splits "<r>daytime</r>." into two tokens, and
    # naively re-joining them prints "daytime .". Carry a per-token flag saying
    # whether a space belongs in front of it.
    NO_SPACE_BEFORE = ".,!?;:)]}»’”%"
    NO_SPACE_AFTER = "([{«‘“"
    toks = []
    for i, (w, r) in enumerate(words):
        lead = i > 0 and w[0] not in NO_SPACE_BEFORE and words[i - 1][0][-1] not in NO_SPACE_AFTER
        toks.append((w, r, lead))

    x0, y0, x1, y1 = box
    W, H = x1 - x0, y1 - y0
    size, lines = lo, None
    for sz in range(hi, lo - 1, -1):
        sp = text_width(" ", fname, sz)
        ls, cur, cw = [], [], 0
        for w, r, lead in toks:
            ww = text_width(w, fname, sz)
            adv = (sp if (cur and lead) else 0) + ww
            if cur and cw + adv > W:
                ls.append(cur)
                cur, cw = [], 0
                adv = ww
            cur.append((w, r, cur and lead))
            cw += adv
        if cur:
            ls.append(cur)
        if len(ls) <= max_lines and len(ls) * sz * lead <= H:
            size, lines = sz, ls
            break
    if lines is None:
        return None
    d = ImageDraw.Draw(img)
    f = font(fname, size)
    sp = text_width(" ", fname, size)
    for i, line in enumerate(lines):
        x = x0
        y = y0 + i * size * lead
        for w, r, gap in line:
            if gap:
                x += sp
            d.text((x, y), w, font=f, fill=(accent if r else colour))
            x += text_width(w, fname, size)
    return size, len(lines)
