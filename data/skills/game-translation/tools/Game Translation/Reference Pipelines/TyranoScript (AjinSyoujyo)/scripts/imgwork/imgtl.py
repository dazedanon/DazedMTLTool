"""imgtl.py - PIL toolkit for translating text baked into game images.

Proven on the Asuka Virgin Idol Debut image set (36 images: transparent overlays,
paper-texture pages, dark gradient panels, speech bubbles, logos, glow cut-ins,
hand-drawn sketches, autographs). Companion doc: the game-translation skill's
references/image-translation.md - read it for the workflow and the edge cases
each helper exists for.

Usage: copy next to your per-game scripts, set SRC/OUT, then
    import sys; sys.path.insert(0, '.')
    from imgtl import *
"""
import os
from statistics import median
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
