"""Rebuild minukirakugaki.png with English graffiti.

Re-runnable: always reads SRC and writes OUT, never stacks onto a previous output.
"""
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

SRC = 'SRC/minukirakugaki.png'
OUT = 'OUT/minukirakugaki.png'
F = 'C:/Windows/Fonts/'
HAND = F + 'comicbd.ttf'
DISPLAY = F + 'ariblk.ttf'

PINK = (255, 75, 181, 255)
WHITE = (255, 255, 255, 255)
BLACK = (0, 0, 0, 255)
RIM = (229, 214, 0, 255)
TYEL = (255, 228, 95, 255)

CX, CY, EA, EB = 1078.48113208, 174.6011386, 131.73459601, 192.98745115
OVBOX = (920, 0, 1220, 378)

src = Image.open(SRC).convert('RGBA')
W, H = src.size
arr = np.array(src)

lab, ncomp = ndimage.label(arr[:, :, 3] > 24, np.ones((3, 3)))

TEXT_COMPS = (
    [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 20, 21]   # A
    + [23, 24, 26, 36]                                                   # B
    + [30, 31, 33, 34, 35, 39, 40, 41, 48]                               # C
    + [32, 37, 38, 42, 44]                                               # D
    + [46, 47, 50, 52, 56, 58, 59]                                       # E
    + [63, 64, 65, 66, 67, 70, 71, 79]                                   # F
    + [45, 49, 55, 62, 68, 72, 73, 75, 77]                               # G
)


def disk(r):
    y, x = np.mgrid[-r:r + 1, -r:r + 1]
    return (x * x + y * y) <= r * r + 0.5


# ---------------------------------------------------------------- heart stamps
def stamp(comp, ymin=0, ymax=H):
    """Cut a hand-drawn heart out by its own component, so no neighbouring
    stroke rides along; a y-cut splits hearts the author joined to a glyph."""
    m = (lab == comp)
    m[:ymin] = False
    m[ymax:] = False
    sub, k = ndimage.label(m, np.ones((3, 3)))
    if k > 1:
        sizes = ndimage.sum(m, sub, range(1, k + 1))
        m = sub == (int(np.argmax(sizes)) + 1)
    ys, xs = np.where(m)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    px = arr[y0:y1, x0:x1].copy()
    px[~m[y0:y1, x0:x1]] = (0, 0, 0, 0)
    return Image.fromarray(px)


HW = stamp(11)                  # small white heart, pink outline
HW2 = stamp(10, ymin=62)        # big white heart (author joined it to a kana)
H2 = stamp(36)                  # double white hearts
HP = stamp(73, ymin=670)        # pink heart, black outline

# ---------------------------------------------------------------- erase pass
out = arr.copy()

erase = ndimage.binary_dilation(np.isin(lab, TEXT_COMPS), disk(2))
out[erase] = (0, 0, 0, 0)

# --- the badge: repaint the title + kao-manko from a fitted model of the oval
oval = np.load('oval.npy')
interior = ndimage.binary_erosion(oval, disk(9))
Rc, Gc, Bc, Ac = (arr[:, :, i].astype(float) for i in range(4))
blue = (Rc < 62) & (Bc > Rc + 8) & (Bc > 6) & interior
glyph = ndimage.binary_closing(interior & ~blue, disk(2))
glyph = ndimage.binary_dilation(glyph, disk(3)) & interior

# text that crosses the rim or spills onto the transparent canvas beside it
box = np.zeros((H, W), bool)
box[OVBOX[1]:OVBOX[3], OVBOX[0]:OVBOX[2]] = True


def near(c, tol):
    return ((np.abs(Rc - c[0]) < tol) & (np.abs(Gc - c[1]) < tol)
            & (np.abs(Bc - c[2]) < tol) & (Ac > 150))


crossing = (near(PINK, 70) | near(WHITE, 45) | near(TYEL, 55)) & box & ~interior
repaint = ndimage.binary_dilation(glyph | crossing, disk(4)) & box

# silhouette: the fitted ellipse, corrected per row by the offset measured on
# rows whose outermost pixel is still the untouched rim colour
rimcol = ((np.abs(Rc - 229) < 25) & (np.abs(Gc - 214) < 25) & (Bc < 40))
cl_y, cl_lo, cl_hi = [], [], []
for y in range(H):
    op = np.where(Ac[y, 900:1240] > 128)[0]
    if len(op) < 20:
        continue
    lo, hi = 900 + op.min(), 900 + op.max()
    if rimcol[y, lo] and rimcol[y, hi]:
        cl_y.append(y)
        cl_lo.append(lo)
        cl_hi.append(hi)
cl_y = np.array(cl_y, float)
yy = np.arange(H, dtype=float)
tt = np.sqrt(np.clip(1 - ((yy - CY) / EB) ** 2, 0, None))
ml, mr = CX - EA * tt, CX + EA * tt
offl = ndimage.gaussian_filter1d(
    np.interp(yy, cl_y, np.array(cl_lo) - np.interp(cl_y, yy, ml)), 6)
offr = ndimage.gaussian_filter1d(
    np.interp(yy, cl_y, np.array(cl_hi) - np.interp(cl_y, yy, mr)), 6)
bl, br = ml + offl, mr + offr
oval_s = np.zeros((H, W), bool)
for y in range(H):
    if tt[y] <= 0:
        continue
    oval_s[y, int(round(bl[y])):int(round(br[y])) + 1] = True

coef = np.load('grad_coef.npy')          # rows: G, B ; degree-7 poly in (u,v)


def grad_rgb(x, y):
    u = (x - CX) / EA
    v = (y - CY) / EB
    des = np.stack([(u ** i) * (v ** j) for i in range(8) for j in range(8 - i)], -1)
    return np.clip(des @ coef[0], 0, 255), np.clip(des @ coef[1], 0, 255)


dist = ndimage.distance_transform_edt(oval_s)
py, px = np.where(repaint)
ins = oval_s[py, px]
out[py[~ins], px[~ins]] = (0, 0, 0, 0)
py, px = py[ins], px[ins]
d = dist[py, px]
sel = d <= 6.0
out[py[sel], px[sel]] = RIM
sel = (d > 6.0) & (d <= 11.0)
out[py[sel], px[sel]] = BLACK
sel = d > 11.0
g_, b_ = grad_rgb(px[sel].astype(float), py[sel].astype(float))
out[py[sel], px[sel], 0] = 0
out[py[sel], px[sel], 1] = g_.astype(np.uint8)
out[py[sel], px[sel], 2] = b_.astype(np.uint8)
out[py[sel], px[sel], 3] = 255

assert erase.sum() > 20000, 'component erase consumed no ink'
assert repaint.sum() > 20000, 'badge repaint consumed no ink'
img = Image.fromarray(out)

# ---------------------------------------------------------------- text engine
BASE = 220
RING = '\u25cb'


def coverage(text, fontfile, tracking=0.0):
    """L-mode coverage of the string at BASE size; U+25CB is drawn as a ring."""
    font = ImageFont.truetype(fontfile, BASE)
    asc, _ = font.getmetrics()
    cap = font.getbbox('H')
    ring_d = int((cap[3] - cap[1]) * 0.98)
    ring_w = max(6, int(ring_d * 0.20))
    pad = BASE
    tmp = Image.new('L', (int(BASE * len(text) * 1.4) + 2 * pad, BASE * 3), 0)
    d = ImageDraw.Draw(tmp)
    x, y = pad, pad
    for ch in text:
        if ch == RING:
            top = y + cap[1]
            d.ellipse([x, top, x + ring_d, top + ring_d], outline=255, width=ring_w)
            x += ring_d + int(BASE * 0.05)
        else:
            d.text((x, y), ch, font=font, fill=255)
            x += d.textlength(ch, font=font)
        x += tracking * BASE
    return tmp.crop(tmp.getbbox())


def styled(cov, w, h, fill, outline=None, out_w=0, fat=0, ring=None, ring_w=0,
           out_off=None):
    iw = max(4, int(round(w - 2 * (out_w + fat))))
    ih = max(4, int(round(h - 2 * (out_w + fat))))
    c = np.asarray(cov.resize((iw, ih), Image.LANCZOS)).astype(np.float32) / 255.0
    pad = out_w + fat + ring_w + 6
    c = np.pad(c, pad)
    layers = []
    if outline is not None and out_w:
        o = ndimage.grey_dilation(c, footprint=disk(out_w + fat))
        if out_off:
            o = np.roll(np.roll(o, out_off[1], 0), out_off[0], 1)
        layers.append((o, outline))
    if ring is not None and ring_w:
        layers.append((ndimage.grey_dilation(c, footprint=disk(ring_w + fat)), ring))
    layers.append((ndimage.grey_dilation(c, footprint=disk(fat)) if fat else c, fill))
    hh, ww = c.shape
    rgba = np.zeros((hh, ww, 4), np.float32)
    for al, col in layers:
        a = al[..., None]
        cc = col(ww, hh) if callable(col) else np.array(col, np.float32)[None, None, :]
        rgba[..., :3] = cc[..., :3] * a + rgba[..., :3] * (1 - a)
        rgba[..., 3:] = np.maximum(rgba[..., 3:], a * 255)
    return Image.fromarray(np.clip(rgba, 0, 255).astype(np.uint8))


def place(text, p0, p1, h, fontfile=HAND, stretch=2.8, squash=0.5,
          ow=0.105, fatr=0.032, ringr=0.0, tracking=0.0, **style):
    p0, p1 = np.array(p0, float), np.array(p1, float)
    dv = p1 - p0
    length = float(np.hypot(*dv))
    ang = np.degrees(np.arctan2(-dv[1], dv[0]))
    cov = coverage(text, fontfile, tracking)
    nh = cov.size[1] * length / cov.size[0]
    draw_h = min(h, nh * stretch)
    draw_h = max(draw_h, nh * squash)
    out_w = max(2, int(round(draw_h * ow)))
    fat = int(round(draw_h * fatr))
    rw = int(round(draw_h * ringr)) if ringr else 0
    tile = styled(cov, length, draw_h, out_w=out_w, fat=fat, ring_w=rw, **style)
    rot = tile.rotate(ang, resample=Image.BICUBIC, expand=True)
    m = (p0 + p1) / 2
    img.alpha_composite(rot, (int(round(m[0] - rot.width / 2)),
                              int(round(m[1] - rot.height / 2))))


def put(st, center, scale=1.0, angle=0.0):
    s = st
    if scale != 1.0:
        s = s.resize((max(1, int(s.width * scale)), max(1, int(s.height * scale))),
                     Image.LANCZOS)
    if angle:
        s = s.rotate(angle, resample=Image.BICUBIC, expand=True)
    img.alpha_composite(s, (int(center[0] - s.width / 2), int(center[1] - s.height / 2)))


WP = dict(fill=WHITE, outline=PINK)     # white fill, pink outline
BP = dict(fill=BLACK, outline=PINK)     # black fill, pink outline
PB = dict(fill=PINK, outline=BLACK)     # pink fill, black outline


def pink_grad(x_off, y_off):
    def f(w, h):
        y, x = np.mgrid[0:h, 0:w]
        gx, gy = x + x_off, y + y_off
        return np.stack([np.clip(427.6 - .1484 * gx - .140 * gy, 0, 255),
                         np.clip(171.2 - .0850 * gx - .0397 * gy, 0, 255),
                         np.clip(322.2 - .1224 * gx - .0988 * gy, 0, 255),
                         np.full(gx.shape, 255.0)], -1)
    return f


# ---------------------------------------------------------------- layout
# A - top left
place('SAVE UP A BIG LOAD', (95, 40), (392, 43), 46, **WP)
put(HW, (416, 45))
place('AND SPURT IT OUT', (85, 83), (362, 87), 52, **WP)
put(HW2, (398, 88))

# B - column beside the badge
place('MAKE IT STICKY', (922, 110), (858, 302), 46, **WP)
put(H2, (856, 335))

# C - lick lick / long-tongue air-bj girl
place('LICK LICK', (160, 335), (250, 296), 44, **WP)
put(HW, (275, 277))
place('LONG-TONGUE', (150, 385), (335, 305), 46, **BP)
place('AIR-BJ GIRL', (168, 430), (350, 352), 46, **BP)

# D - cum on my tits
place('CUM ON', (540, 256), (612, 328), 42, **WP)
place('MY TITS', (506, 302), (578, 374), 42, **WP)
put(HW, (618, 374))

# E - two columns
place('C\u25cbCK STANDBY', (725, 360), (719, 528), 46, **WP)
put(HW, (721, 553))
place('LEWD TITS', (675, 365), (670, 538), 44, **WP)
put(HW, (671, 563))

# F - repeat rate / sky-high
place('REPEAT RATE', (62, 543), (300, 536), 64, ow=0.09, **PB)
place('SKY-HIGH!!', (88, 648), (486, 640), 118, ow=0.058, stretch=1.95,
      tracking=0.055, **PB)

# G - filthy cock-pleaser / lady knight
place('FILTHY C\u25cbCK-PLEASER', (992, 362), (955, 672), 56, ow=0.09, **PB)
place('LADY KNIGHT', (918, 480), (902, 655), 60, ow=0.09, **PB)
put(HP, (901, 691))

# H - the badge
for txt, cx, cy, w, hgt in (('No.1', 1079, 72, 142, 80),
                            ('MOST', 1079, 168, 180, 90),
                            ('POPULAR', 1079, 262, 165, 72)):
    place(txt, (cx - w / 2, cy), (cx + w / 2, cy), hgt, fontfile=DISPLAY,
          fill=pink_grad(cx - w / 2, cy - hgt / 2), outline=TYEL, ring=BLACK,
          ow=0.105, fatr=0.0, ringr=0.038, out_off=(2, 2))

# I - face-pussy, across the badge rim
place('FACE-P\u25cbSSY', (1000, 92), (947, 258), 52, **WP)

img.save(OUT)
print('written', OUT)
