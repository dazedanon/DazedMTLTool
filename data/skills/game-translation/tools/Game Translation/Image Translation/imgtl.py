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


# --------------------------------------------------------------------------
# hand-lettered overlay kit - component census, hand-drawn stamps, marker
# text at any angle, gradient-plate rebuild. Proven on the Kihoushi Scarlet
# graffiti overlay (minukirakugaki.png: 11 phrases at five angles, vertical
# columns, a badge with a radial gradient and a yellow rim). Worked example:
# Active Projects\KihoushiScarlet (Wolf)\images\build.py. Needs scipy.
# --------------------------------------------------------------------------
def _disk(r):
    y, x = np.mgrid[-r:r + 1, -r:r + 1]
    return (x * x + y * y) <= r * r + 0.5


def components(img, thr=24):
    """Label the alpha plane. On a transparent-canvas overlay every doodle and
    glyph cluster is its own component, which makes erase/keep decisions exact:
    classify every id once (text vs decoration), erase the text ids, and the
    scribbles/hearts/stars you keep stay byte-identical - provable later with
    a pixel diff. Returns (lab, [{id, px, box}] largest first)."""
    from scipy import ndimage as ndi
    a = np.asarray(img)
    lab, n = ndi.label(a[:, :, 3] > thr, np.ones((3, 3)))
    recs = []
    for i, sl in enumerate(ndi.find_objects(lab), 1):
        recs.append({"id": i, "px": int((lab[sl] == i).sum()),
                     "box": (sl[1].start, sl[0].start, sl[1].stop, sl[0].stop)})
    recs.sort(key=lambda r: -r["px"])
    return lab, recs


def comp_sheet(img, lab, ids, path, bg=(128, 128, 128, 255)):
    """Render ONLY these components on a flat ground - the cheap proof that a
    keep-list is exactly the decorations, or an erase-list exactly the text.
    One look at this image settles what no table of boxes can."""
    a = np.array(img)
    a[~np.isin(lab, list(ids))] = (0, 0, 0, 0)
    out = Image.new("RGBA", img.size, bg)
    out.alpha_composite(Image.fromarray(a))
    out.convert("RGB").save(path)


def comp_stamp(img, lab, comp, ymin=None, ymax=None):
    """Cut a hand-drawn mark (heart, star, arrow) out by its own component so
    no neighbouring stroke rides along - rectangle crops shipped glyph-tail
    slivers twice before this existed. A y-cut splits marks the author joined
    to a glyph (kana + heart in one blob); the largest surviving piece wins."""
    from scipy import ndimage as ndi
    m = lab == comp
    if ymin is not None:
        m[:ymin] = False
    if ymax is not None:
        m[ymax:] = False
    sub, k = ndi.label(m, np.ones((3, 3)))
    if k > 1:
        sizes = ndi.sum(m, sub, range(1, k + 1))
        m = sub == (int(np.argmax(sizes)) + 1)
    ys, xs = np.where(m)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    px = np.array(img)[y0:y1, x0:x1]
    px[~m[y0:y1, x0:x1]] = (0, 0, 0, 0)
    return Image.fromarray(px)


def clear_components(img, lab, ids, grow=2):
    """Erase whole components to alpha 0 (grown a little for the antialiased
    rim) and return the new image. Asserts ink was consumed: an empty
    selection is a wrong id list, never a clean pass."""
    from scipy import ndimage as ndi
    m = ndi.binary_dilation(np.isin(lab, list(ids)), _disk(grow))
    assert m.any(), "clear_components: selection matched no ink"
    a = np.array(img)
    a[m] = (0, 0, 0, 0)
    return Image.fromarray(a)


def text_angle(lab, ids, step=1.0):
    """Baseline axis of a handwritten block: the angle whose perpendicular
    projection histogram has minimum entropy. PCA lies on two-line blocks (the
    axis follows the stack, not the baselines) and band-splitting fails
    outright because handwritten lines touch. Returns degrees in [-90, 90) -
    resolve the 180-degree reading-direction ambiguity by eye."""
    ys, xs = np.where(np.isin(lab, list(ids)))
    P = np.stack([xs, ys], 1).astype(float)
    best = (1e18, 0.0)
    for a in np.arange(-90.0, 90.0, step):
        th = np.radians(a)
        v = P @ np.array([np.sin(th), np.cos(th)])
        h, _ = np.histogram(v, bins=np.arange(v.min(), v.max() + 2, 1.0))
        p = h[h > 0] / h.sum()
        e = float(-(p * np.log(p)).sum())
        if e < best[0]:
            best = (e, a)
    return best[1]


CENSOR = "○"   # the JP self-censor circle, as in the censored body words


def coverage(s, fontfile, base=220, tracking=0.0):
    """L-mode coverage of a string at a large base size, later scaled to the
    target box. U+25CB is drawn as a cap-height ring because the handwriting
    faces (comicbd, Inkfree) have no glyph for it - render a censor as
    geometry, never trust font coverage. Tracking (em units) opens letter gaps
    so a vertically stretched display line does not fuse when the outline
    dilates."""
    fnt = ImageFont.truetype(fontfile, base)
    cap = fnt.getbbox("H")
    ring_d = int((cap[3] - cap[1]) * 0.98)
    ring_w = max(5, int(ring_d * 0.15))   # thinner than a letter O, so it reads as a censor
    tmp = Image.new("L", (int(base * (len(s) + 2) * 1.4), base * 3), 0)
    d = ImageDraw.Draw(tmp)
    x, y = base, base
    for ch in s:
        if ch == CENSOR:
            d.ellipse([x, y + cap[1], x + ring_d, y + cap[1] + ring_d],
                      outline=255, width=ring_w)
            x += ring_d + int(base * 0.05)
        else:
            d.text((x, y), ch, font=fnt, fill=255)
            x += d.textlength(ch, font=fnt)
        x += tracking * base
    return tmp.crop(tmp.getbbox())


def styled_tile(cov, w, h, fill, outline=None, out_w=0, fat=0,
                ring=None, ring_w=0, out_off=None):
    """Scale a coverage mask to exactly (w, h) and colour it: optional outline
    (offsettable, for a rim lit to one side), optional second ring between
    outline and core, core fattened by `fat`. Colour goes on LAST over the
    greyscale masks, so stretching never smears the RGB stored under alpha 0.
    `fill` may be a callable (w, h) -> float RGBA array for gradient fills."""
    from scipy import ndimage as ndi
    iw = max(4, int(round(w - 2 * (out_w + fat))))
    ih = max(4, int(round(h - 2 * (out_w + fat))))
    c = np.asarray(cov.resize((iw, ih), Image.LANCZOS)).astype(np.float32) / 255
    c = np.pad(c, out_w + fat + ring_w + 6)
    layers = []
    if outline is not None and out_w:
        o = ndi.grey_dilation(c, footprint=_disk(out_w + fat))
        if out_off:
            o = np.roll(np.roll(o, out_off[1], 0), out_off[0], 1)
        layers.append((o, outline))
    if ring is not None and ring_w:
        layers.append((ndi.grey_dilation(c, footprint=_disk(ring_w + fat)), ring))
    layers.append((ndi.grey_dilation(c, footprint=_disk(fat)) if fat else c, fill))
    hh, ww = c.shape
    rgba = np.zeros((hh, ww, 4), np.float32)
    for al, col in layers:
        aa = al[..., None]
        cc = col(ww, hh) if callable(col) else np.array(col, np.float32)[None, None, :]
        rgba[..., :3] = cc[..., :3] * aa + rgba[..., :3] * (1 - aa)
        rgba[..., 3:] = np.maximum(rgba[..., 3:], aa * 255)
    return Image.fromarray(np.clip(rgba, 0, 255).astype(np.uint8))


def marker_line(img, s, p0, p1, h, fontfile, fill, outline=None, *,
                ow=0.105, fatr=0.032, ring=None, ringr=0.0, out_off=None,
                stretch=2.8, squash=0.5, tracking=0.0):
    """One phrase along the segment p0 -> p1 (its midline), box height h. The
    segment IS the layout spec: read both endpoints off a grid() zoom of the
    source line, and angle, length and position all follow - faster and less
    error-prone than centre+angle+width. Stroke widths are RATIOS of the drawn
    height (JP marker graffiti measures outline ~0.10 of glyph height, core
    fattening ~0.03); absolute pixel strokes are the bug that made every small
    line illegible, a 6px outline eating a 22px cap. English stretches
    vertically up to `stretch` toward h (condensed marker caps read fine to
    ~2.8x; display faces want ~2.0 plus tracking). Vertical JP columns: p0 at
    the top, p1 at the bottom (90 CW, head tilts right), which also stacks two
    English lines right-to-left exactly like the JP columns."""
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    dv = p1 - p0
    length = float(np.hypot(*dv))
    ang = np.degrees(np.arctan2(-dv[1], dv[0]))
    cov = coverage(s, fontfile, tracking=tracking)
    nh = cov.size[1] * length / cov.size[0]
    draw_h = max(min(h, nh * stretch), nh * squash)
    out_w = max(2, int(round(draw_h * ow))) if outline is not None else 0
    tile = styled_tile(cov, length, draw_h, fill, outline, out_w,
                       int(round(draw_h * fatr)), ring,
                       int(round(draw_h * ringr)), out_off)
    rot = tile.rotate(ang, resample=Image.BICUBIC, expand=True)
    mid = (p0 + p1) / 2
    img.alpha_composite(rot, (int(round(mid[0] - rot.width / 2)),
                              int(round(mid[1] - rot.height / 2))))


def put_stamp(img, st, center, scale=1.0, angle=0.0):
    """Paste a comp_stamp() cutout centred on a point. Hearts beside vertical
    JP columns are drawn UPRIGHT in the source - do not rotate them with the
    text."""
    if scale != 1.0:
        st = st.resize((max(1, int(st.width * scale)),
                        max(1, int(st.height * scale))), Image.LANCZOS)
    if angle:
        st = st.rotate(angle, resample=Image.BICUBIC, expand=True)
    img.alpha_composite(st, (int(center[0] - st.width / 2),
                             int(center[1] - st.height / 2)))


def line_gap(a0, a1, ha, b0, hb):
    """Perpendicular clearance between two roughly parallel marker_line boxes,
    negative meaning overlap. Outlines add ~0.1*h per side on top of this -
    budget for them. Doing this arithmetic up front beats a render-and-look
    round per collision, of which one session needed five."""
    a0, a1, b0 = (np.asarray(p, float) for p in (a0, a1, b0))
    d = a1 - a0
    d = d / np.hypot(*d)
    n = np.array([-d[1], d[0]])
    return abs(float((b0 - a0) @ n)) - (ha + hb) / 2


def ellipse_from_rows(rows, guess):
    """Least-squares (cx, cy, A, B) from per-row (y, x_left, x_right) extents.
    Feed it only CLEAN rows - rows whose outermost opaque pixel is still the
    plate's own rim colour - because type crossing the rim bulges the
    silhouette and a fit over all rows chases the bulges (rms 42 vs 1.6 on the
    reference badge)."""
    from scipy.optimize import least_squares
    P = np.asarray(rows, float)

    def res(p):
        cx, cy, A, B = p
        t = np.clip(1 - ((P[:, 0] - cy) / B) ** 2, 0, None)
        s = A * np.sqrt(t)
        return np.concatenate([cx - s - P[:, 1], cx + s - P[:, 2]])

    return least_squares(res, guess).x


def surface_fit(xs, ys, vals, cx, cy, sa, sb, deg=7):
    """Polynomial colour surface in normalised plate coordinates - the way to
    erase big type off a smooth gradient plate. Inpainting a plate that is
    mostly type returns blur; a deg-7 fit on the surviving background pixels
    reproduced a radial gradient at rms < 1 per channel. Fit each channel
    separately; evaluate with surface_eval."""
    u, v = (np.asarray(xs) - cx) / sa, (np.asarray(ys) - cy) / sb
    X = np.stack([(u ** i) * (v ** j)
                  for i in range(deg + 1) for j in range(deg + 1 - i)], 1)
    co, *_ = np.linalg.lstsq(X, np.asarray(vals, float), rcond=None)
    return co


def surface_eval(coeffs, xs, ys, cx, cy, sa, sb, deg=7):
    u, v = (np.asarray(xs) - cx) / sa, (np.asarray(ys) - cy) / sb
    X = np.stack([(u ** i) * (v ** j)
                  for i in range(deg + 1) for j in range(deg + 1 - i)], -1)
    return X @ coeffs


# --------------------------------------------------------------------------
# flattened siblings, unreconstructable regions, and reading aids.
# Added after the Kihoushi Scarlet set (8 images: 5 graffiti overlays, one
# flattened copy of one of them, a title screen, a translucent banner).
# --------------------------------------------------------------------------
def composite_mask(flat, overlay, thr=2, grow=3):
    """Prove `flat` is `clean_art` with `overlay` composited on it, and hand
    back the exact ink mask. A game that ships an overlay OFTEN also ships the
    baked version for a still/photo/CG-gallery frame; that second file is the
    same text and looks half-translated if you skip it.

    The win is the mask: it is the overlay's own ALPHA, so it is exact and
    free, where a flattened image on its own would need a glyph-mask guess.
    Workflow: clean = inpaint under this mask, then composite the TRANSLATED
    overlay onto the result.

    Returns (mask, agreement) - agreement is the share of the overlay's fully
    opaque pixels that `flat` reproduces. Below ~0.99 the two are not a
    composite pair and the whole approach is off."""
    from scipy import ndimage as ndi
    f = np.asarray(flat.convert("RGBA")).astype(int)
    o = np.asarray(overlay.convert("RGBA")).astype(int)
    solid = o[:, :, 3] == 255
    if not solid.any():
        return None, 0.0
    d = np.abs(o[:, :, :3] - f[:, :, :3])[solid].max(axis=1)
    agree = float((d <= thr).mean())
    mask = ndi.binary_dilation(o[:, :, 3] > 16, _disk(grow))
    return mask, agree


def soft_plate(img, mask, sample_x=(46, 56), sigma=20, lo=0.10, hi=0.42):
    """LAST RESORT. Lay a plate over a region, shaped by the text rather than by
    a rectangle.

    Try `inpaint_large` + `poly_background` first and expect them to win: this
    was reached for on a game title, and filling the hole properly turned out
    both possible and better. A plate hides art the Japanese never covered, and
    on the reference title it read as a box slapped onto the picture - the user
    rejected it on sight. Keep it for a region that is genuinely beyond repair
    AND where the composition already has a panel to extend, and say in the
    hand-off that it dims more artwork than the source did.

    Blurring the glyph mask is what stops it reading as a box: the alpha then
    hugs the text in an organic blob. `sample_x` is a column strip of the
    artwork's own edge, read per row, so the plate is the picture's colour
    rather than an invented one."""
    from scipy import ndimage as ndi
    a = np.asarray(img.convert("RGBA")).astype(float)
    plate = a[:, sample_x[0]:sample_x[1], :3].mean(axis=1)
    soft = ndi.gaussian_filter(mask.astype(float), sigma)
    al = np.clip((soft - lo) / max(1e-6, hi - lo), 0, 1)[..., None]
    a[:, :, :3] = plate[:, None, :] * al + a[:, :, :3] * (1 - al)
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def glyph_strip(tiles, path, scale=5, bg=(60, 60, 60, 255), pad=20):
    """Lay labelled crops side by side to settle an ambiguous reading.

    Hand-lettered kana at 40px are often undecidable in isolation, and the
    author is the control: crop the SAME glyph where it appears unambiguously
    elsewhere in the set and compare. On the reference set this decided two
    readings that zooming alone could not, and it is faster than a fourth
    magnification. `tiles` is [(label, PIL crop), ...]."""
    W = sum(t.width for _, t in tiles) + pad * (len(tiles) + 1)
    Hh = max(t.height for _, t in tiles) + 34
    sheet = Image.new("RGBA", (W, Hh), bg)
    d = ImageDraw.Draw(sheet)
    x = pad
    for name, t in tiles:
        sheet.alpha_composite(t.convert("RGBA"), (x, 8))
        d.text((x, Hh - 22), str(name), fill=(255, 255, 0, 255))
        x += t.width + pad
    sheet.resize((sheet.width * scale, sheet.height * scale),
                 Image.LANCZOS).convert("RGB").save(path)
    return sheet


# --------------------------------------------------------------------------
# large-hole reconstruction. Needs cv2 (opencv-contrib-python).
# --------------------------------------------------------------------------
def inpaint_pyramid(rgb, hole, levels=6, iters=120):
    """Coarse-to-fine low-frequency fill for large holes; review its limits.

    Display type destroys most of what it covers - a game title measured 76% of
    its own band and 90% over the character art, in ONE connected 115k-px hole -
    so in that example full resolution left little local information and the
    tested single-scale methods failed: diffusion averages the backdrop across the skin,
    row interpolation stripes it, nearest-colour cuts wedges, FSR returns a flat
    block. Downsampled six times that same hole is a few pixels across, so a
    fill there carries a real colour field, and each level up re-imposes the
    pixels that survived. Low frequency is genuinely all that is recoverable;
    this recovers it and nothing pretends otherwise."""
    import cv2
    imgs, masks = [np.asarray(rgb).astype(np.float32)], [hole.astype(np.float32)]
    for _ in range(levels):
        imgs.append(cv2.pyrDown(imgs[-1]))
        masks.append(cv2.pyrDown(masks[-1]))
    cur = imgs[-1].copy()
    k = np.array([[.05, .2, .05], [.2, 0, .2], [.05, .2, .05]], np.float32)
    for lv in range(levels, -1, -1):
        m = masks[lv] > 0.02
        if lv < levels:
            up = cv2.pyrUp(cur, dstsize=(imgs[lv].shape[1], imgs[lv].shape[0]))
            cur = imgs[lv].copy()
            cur[m] = up[m]
        base = imgs[lv].copy()
        for _ in range(iters):
            sm = cv2.filter2D(cur, -1, k)
            cur[m] = sm[m]
            cur[~m] = base[~m]
    return np.clip(cur, 0, 255).astype(np.uint8)


def inpaint_large(rgb, hole, feather=24, sharpen=0.5, radius=6):
    """Pyramid field blended into Telea by depth into the hole: sharp structure
    where the rim still knows something, smooth field where it cannot."""
    import cv2
    from scipy import ndimage as ndi
    rgb = np.asarray(rgb)[:, :, :3]
    m8 = (hole * 255).astype(np.uint8)
    tel = cv2.inpaint(rgb[:, :, ::-1], m8, radius, cv2.INPAINT_TELEA)[:, :, ::-1]
    pyr = inpaint_pyramid(rgb, hole)
    w = np.clip(ndi.distance_transform_edt(hole) / feather, 0, 1)[..., None]
    out = tel.astype(np.float32) * (1 - w) + pyr.astype(np.float32) * w
    if sharpen:
        out = np.clip(out + sharpen * (out - cv2.GaussianBlur(out, (0, 0), 2.0)),
                      0, 255)
    res = rgb.astype(np.float32).copy()
    res[hole] = out[hole]
    return np.clip(res, 0, 255).astype(np.uint8)


def seal_islands(hole, zone, area=140):
    """Fold stranded specks of "known" pixels inside the hole into it.

    They are leftover glyph rim, not artwork, and any fill that samples them
    paints their colour outward - that was a dark blob and a green speck in the
    middle of an otherwise clean reconstruction."""
    from scipy import ndimage as ndi
    known = ~hole & zone
    lb, k = ndi.label(known)
    if not k:
        return hole
    sz = ndi.sum(known, lb, range(1, k + 1))
    return hole | np.isin(lb, np.where(sz < area)[0] + 1)


def poly_background(rgb, clean, deg=6, centre=None, scale=None):
    """Fit a smooth backdrop surface on pixels known to be background.

    Returns model(xs, ys) -> Nx3. Where a game's title sits on a gradient rather
    than on artwork this reproduces it exactly (rms ~1 per channel), which no
    inpaint does, and it is also the only thing that finds the hole properly:
    a colour threshold sees the red fill and the white fill and misses the dark
    OUTLINE, which then survives every fill as a glyph-shaped ghost."""
    a = np.asarray(rgb).astype(float)[:, :, :3]
    h, w = a.shape[:2]
    cx, cy = centre or (w / 2.0, h / 2.0)
    sx, sy = scale or (w / 2.0, h / 2.0)

    def design(xs, ys):
        u, v = (np.asarray(xs) - cx) / sx, (np.asarray(ys) - cy) / sy
        return np.stack([(u ** i) * (v ** j) for i in range(deg + 1)
                         for j in range(deg + 1 - i)], -1)

    ys, xs = np.where(clean)
    co = [np.linalg.lstsq(design(xs, ys), a[ys, xs, c], rcond=None)[0]
          for c in range(3)]

    def model(hx, hy):
        X = design(hx, hy)
        return np.stack([np.clip(X @ co[c], 0, 255) for c in range(3)], 1)
    return model


def nconv_background(img, known, sigma=85):
    """Local backdrop estimate that ignores masked pixels:
    blur(img*known) / blur(known).

    Use this, not a fitted polynomial. A degree-6 surface interpolates a smooth
    gradient beautifully (rms ~1) and then DIVERGES the moment it has to cross a
    100px hole - on the reference title it predicted R=255 in the middle of a
    near-black backdrop, which silently poisoned both the mask built from it and
    every residual measured against it. Normalised convolution cannot diverge:
    with no data under the kernel it returns the neighbourhood average.

    Its first job is finding ink, not filling: a colour threshold catches the
    fill and misses the dark OUTLINE and the drop shadow, those stay "known", and
    every inpaint then propagates their colour inward and leaves a soft
    glyph-shaped stain over provably flat background. `|image - nconv| > ~8`
    catches fill, outline, shadow and antialiased rim in one test."""
    import cv2
    a = np.asarray(img).astype(np.float32)[:, :, :3]
    k = known.astype(np.float32)
    num = np.stack([cv2.GaussianBlur(a[:, :, c] * k, (0, 0), sigma)
                    for c in range(3)], -1)
    return num / (cv2.GaussianBlur(k, (0, 0), sigma) + 1e-6)[..., None]


def smoothness(img, region, sigma=25):
    """Mean and max deviation from a heavy blur - a ghost detector for flat
    areas, and the only honest way to say a fill is clean.

    A Laplacian check reported 0.00% rough on a plate that visibly carried a
    soft stain, because the leftover is LOW frequency, not an edge. Score the
    repaired area and score an equivalent never-texted patch of the same
    artwork: parity with that control is the pass mark. The reference title
    finished at mean 0.92 / max 10.3 against a control of 1.18 / 33.2."""
    import cv2
    g = cv2.cvtColor(np.asarray(img).astype(np.uint8), cv2.COLOR_RGB2GRAY).astype(np.float32)
    d = np.abs(g - cv2.GaussianBlur(g, (0, 0), sigma))
    return float(d[region].mean()), float(d[region].max())
