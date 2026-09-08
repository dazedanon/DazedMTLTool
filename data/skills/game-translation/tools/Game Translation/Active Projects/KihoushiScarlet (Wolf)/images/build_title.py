"""Title screen: reconstruct the artwork under the Japanese, then set the English.

The Japanese title covers 76% of its own band before any dilation, 90% of the
band over the character art, and forms ONE connected hole of ~115k px, so there
is nothing local left to copy from. Single-scale fills all fail there: diffusion
averages the dark background across the skin, row interpolation stripes it,
Voronoi cuts wedges, FSR returns a flat block.

Two regions, two methods, chosen by evidence rather than by a hand-drawn split:
  * where a fitted background surface demonstrably predicts the surviving
    pixels, the background IS that surface - repaint from the model and the
    result is exact.
  * everywhere else (the character art) only the low-frequency field is
    recoverable - a coarse-to-fine pyramid supplies it, blended into Telea near
    the rim where local structure is still known.

The mask is model-driven too: colour thresholds miss the subtitle's dark
outline, which then survives every fill as a glyph-shaped ghost.
"""
import sys, os
sys.path.insert(0, '.')
import numpy as np
import cv2
from PIL import Image, ImageFilter
from scipy import ndimage
from imgtl import coverage, styled_tile, marker_line

F = 'C:/Windows/Fonts/'
DISPLAY = F + 'ariblk.ttf'
BOLD = F + 'arialbd.ttf'
TIT = '\u30bf\u30a4\u30c8\u30eb.png'
BAND = (120, 385, 0, 752)         # y0, y1, x0, x1 - the ink ends at x=741
DEG = 6


def disk(r):
    y, x = np.mgrid[-r:r + 1, -r:r + 1]
    return (x * x + y * y) <= r * r + 0.5


def design(xs, ys):
    u, v = (np.asarray(xs) - 640) / 640.0, (np.asarray(ys) - 250) / 250.0
    return np.stack([(u ** i) * (v ** j) for i in range(DEG + 1)
                     for j in range(DEG + 1 - i)], -1)


def nconv(img, known, sigma):
    """Background estimate that ignores masked pixels: blur(img*known)/blur(known).

    A fitted polynomial was tried first and is the wrong tool - degree 6 over a
    240px band interpolates beautifully but DIVERGES across a 100px hole (it
    predicted R=255 in the middle of a dark backdrop), so both the mask it
    produced and any residual measured against it were nonsense. Normalised
    convolution cannot diverge: with no data it just returns the neighbourhood
    average."""
    k = known.astype(np.float32)
    num = np.stack([cv2.GaussianBlur(img[:, :, c].astype(np.float32) * k, (0, 0), sigma)
                    for c in range(3)], -1)
    return num / (cv2.GaussianBlur(k, (0, 0), sigma) + 1e-6)[..., None]


def seal_islands(hole, zone, area=140):
    known = ~hole & zone
    lb, k = ndimage.label(known)
    if not k:
        return hole
    sz = ndimage.sum(known, lb, range(1, k + 1))
    return hole | np.isin(lb, np.where(sz < area)[0] + 1)


def analyse(a, sigma=85, thr=8, grow=4):
    """The whole ink footprint, not just the coloured part.

    A colour threshold finds the red fill and the white fill and misses the dark
    OUTLINE and the shadow. Those stay "known", so every fill propagates their
    colour inward and leaves a soft glyph-shaped stain over an area that is
    provably flat backdrop - which is what a reader notices. Comparing the
    original against a local backdrop estimate catches fill, outline, shadow and
    antialiased rim in one test."""
    R, G, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    band = np.zeros(R.shape, bool)
    band[BAND[0]:BAND[1], BAND[2]:BAND[3]] = True
    # Seed ONLY on pixels that cannot be anything but glyph. A loose
    # red-dominance test matches this character's skin better than it matches
    # the title's own light band - 82% of her face passed it - and the fill then
    # smeared her eyes. Saturated red, or neutral white, and nothing else.
    spread = a.max(axis=2) - a.min(axis=2)
    core = (((R > 200) & (G < 90) & (B < 80))
            | ((R > 185) & (G > 185) & (B > 185) & (spread < 30))) & band
    # everything else about the glyph - the light band across it, the outline,
    # the shadow - is found by deviation, but only NEAR a seed, never on its own
    bg = nconv(a, ~ndimage.binary_dilation(core, disk(10)), sigma)
    resid = np.abs(a.astype(np.float32) - bg).max(axis=2)
    # BOUND the deviation test to the glyphs' own neighbourhood. Artwork
    # legitimately departs from a local backdrop estimate, so unbounded this
    # marks a character's face as ink and smears it. An outline and a drop
    # shadow never sit more than ~20px from their glyph.
    near = ndimage.binary_dilation(core, disk(40)) & band
    ink = (((resid > thr) & near) | core) & band
    ink = ndimage.binary_dilation(ndimage.binary_closing(ink, disk(3)), disk(grow)) & band
    ink = seal_islands(ink, band)
    bg2 = nconv(a, ~ink, sigma)
    ok = (np.abs(a.astype(np.float32) - bg2).max(axis=2) < 10) & ~ink & band
    flat = ndimage.binary_fill_holes(ndimage.binary_closing(ok, disk(30))) & band
    lab, n = ndimage.label(flat)
    touch = set(lab[BAND[0]:BAND[1], 2:8].ravel()) - {0}
    if touch:
        flat = np.isin(lab, list(touch))
    return ink, ndimage.binary_erosion(flat, disk(8)), bg2, band


def pyramid(rgb, hole, levels=6, iters=120):
    imgs, masks = [rgb.astype(np.float32)], [hole.astype(np.float32)]
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


def fill(rgb, hole, feather=24, sharpen=0.5):
    m8 = (hole * 255).astype(np.uint8)
    tel = cv2.inpaint(rgb[:, :, ::-1], m8, 6, cv2.INPAINT_TELEA)[:, :, ::-1]
    pyr = pyramid(rgb, hole)
    w = np.clip(ndimage.distance_transform_edt(hole) / feather, 0, 1)[..., None]
    out = tel.astype(np.float32) * (1 - w) + pyr.astype(np.float32) * w
    return np.clip(out + sharpen * (out - cv2.GaussianBlur(out, (0, 0), 2.0)), 0, 255)


def reconstruct():
    src = Image.open(os.path.join('SRC', TIT)).convert('RGBA')
    rgb = np.array(src)[:, :, :3]
    a = rgb.astype(int)
    ink, flat, bg2, band = analyse(a)
    assert ink.sum() > 80000, 'title mask consumed no ink'
    out = fill(rgb, ink)
    res = rgb.astype(np.float32).copy()
    res[ink] = out[ink]
    w = np.clip(ndimage.gaussian_filter(flat.astype(np.float32), 5) * 1.3, 0, 1)[..., None]
    sel = ink & ndimage.binary_dilation(flat, disk(10))
    res[sel] = bg2[sel] * w[sel] + res[sel] * (1 - w[sel])
    o = np.array(src)
    o[:, :, :3] = np.clip(res, 0, 255).astype(np.uint8)
    return Image.fromarray(o), ink, flat


def fit_tracking(txt, font, box_w, box_h):
    best, bt = None, 0.0
    for tr in np.arange(0, 0.9, 0.02):
        cov = coverage(txt, font, tracking=float(tr))
        err = abs(cov.size[0] / cov.size[1] - box_w / box_h)
        if best is None or err < best:
            best, bt = err, float(tr)
    return bt


def title_fill(w, h):
    y, x = np.mgrid[0:h, 0:w]
    t = y / max(1, h - 1)
    hi = np.exp(-((t - 0.52) ** 2) / (2 * 0.11 ** 2))
    return np.stack([255 * np.ones_like(t, float), 20 + 150 * hi, 145 * hi,
                     np.full(t.shape, 255.0)], -1)


DKRED = (118, 0, 4, 255)
img, ink, flat = reconstruct()
img.save('probe/TITLE_clean.png')

for txt, x0, x1, cy, h in [('CRIMSON KNIGHT', 70, 740, 196, 92),
                           ('SCARLET', 70, 740, 278, 82)]:
    tr = fit_tracking(txt, DISPLAY, x1 - x0, h)
    cov = coverage(txt, DISPLAY, tracking=tr)
    L = x1 - x0
    dh = min(h, cov.size[1] * L / cov.size[0] * 1.6)
    sh = styled_tile(cov, L, dh, (12, 0, 8, 165), DKRED, 11, 0)
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(4)),
                        (int(x0 + 4), int(cy - dh / 2 + 6)))
    img.alpha_composite(styled_tile(cov, L, dh, title_fill, DKRED, 7, 0),
                        (int(x0), int(cy - dh / 2)))

# The subtitle is not flat white: it is a chrome bevel - a flat grey body with
# a white highlight along the TOP edge of every stroke, lit from above. Median
# fill measures 205, the top edge reaches 254 on the columns that catch it.
def bevel_line(img, s, x0, x1, cy, h, fontfile, body=(205, 205, 205),
               hi=(255, 255, 255), outline=(20, 3, 12), ow=0.075, lift=0.13):
    from scipy import ndimage as ndi
    cov = coverage(s, fontfile)
    L = x1 - x0
    dh = min(h, cov.size[1] * L / cov.size[0] * 2.0)
    out_w = max(2, int(round(dh * ow)))
    pad = out_w + 6
    iw, ih = max(4, int(L - 2 * out_w)), max(4, int(dh - 2 * out_w))
    c = np.asarray(cov.resize((iw, ih), Image.LANCZOS)).astype(np.float32) / 255
    c = np.pad(c, pad)
    k = max(2, int(round(dh * lift)))
    edge = np.clip(c - np.roll(c, k, axis=0), 0, 1)      # top edge of each stroke
    edge = ndi.gaussian_filter(edge, 0.8) * c
    o = ndi.grey_dilation(c, footprint=disk(out_w))
    hh, ww = c.shape
    rgba = np.zeros((hh, ww, 4), np.float32)
    for al, col in ((o, outline), (c, body), (edge, hi)):
        a3 = al[..., None]
        rgba[..., :3] = np.array(col, np.float32)[None, None, :] * a3 + rgba[..., :3] * (1 - a3)
        rgba[..., 3:] = np.maximum(rgba[..., 3:], a3 * 255)
    tile = Image.fromarray(np.clip(rgba, 0, 255).astype(np.uint8))
    img.alpha_composite(tile, (int(x0 - pad), int(cy - hh / 2)))


bevel_line(img, '~In Search of the Legendary Herb~', 66, 744, 334, 46, BOLD)
img.save(os.path.join('OUT', TIT))
print('written title | ink %d px | flat region %d px' % (ink.sum(), flat.sum()))
