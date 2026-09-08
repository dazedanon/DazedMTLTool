"""Banner, title screen, and the flattened voyeur photo."""
import sys, os
sys.path.insert(0, '.')
import numpy as np
from PIL import Image
from scipy import ndimage
import imgtl
from imgtl import marker_line, styled_tile, coverage, inpaint_diffuse

F = 'C:/Windows/Fonts/'
BLACK_FONT = F + 'ariblk.ttf'
BOLD = F + 'arialbd.ttf'
os.makedirs('OUT', exist_ok=True)


def disk(r):
    y, x = np.mgrid[-r:r + 1, -r:r + 1]
    return (x * x + y * y) <= r * r + 0.5


# ================================================================ banner
BAN = '\u30aa\u30ca\u30cb\u30fc\u30d0\u30b9\u30bf\u30fc\u30ba.png'
src = Image.open(os.path.join('SRC', BAN)).convert('RGBA')
a = np.array(src)
BAND = (0, 0, 0, 142)
before = int((a[296:452] != np.array(BAND, np.uint8)).any(-1).sum())
a[296:392, :] = BAND                       # line 1 rows
a[396:452, 308:956] = BAND                 # line 2, keeping both original marks
assert before > 10000, 'banner erase consumed no ink'
img = Image.fromarray(a)

YEL = (255, 213, 0, 255)
SHADOW = (0, 0, 0, 190)
for txt, p0, p1, h, fnt in [
        ('THE MASTURBATION BUSTERS APPEAR!', (150, 344), (1136, 344), 74, BLACK_FONT),
        ('MIND WHERE YOU MASTURBATE', (316, 420), (950, 420), 42, BOLD)]:
    cov = coverage(txt, fnt)
    length = p1[0] - p0[0]
    nh = cov.size[1] * length / cov.size[0]
    dh = min(h, nh * 2.0)
    sh = styled_tile(cov, length, dh, SHADOW)
    img.alpha_composite(sh, (int(p0[0] + 5), int(p0[1] - dh / 2 + 5)))
    tile = styled_tile(cov, length, dh, YEL)
    img.alpha_composite(tile, (int(p0[0]), int(p0[1] - dh / 2)))
img.save(os.path.join('OUT', BAN))
print('written banner')

# (title moved to build_title.py - it needs its own two-pass reconstruction)

# ================================================================ photo
PH = 'tousatusyasin010101.png'
T1 = 'tousaturakugaki010101.png'
photo = Image.open(os.path.join('SRC', PH)).convert('RGBA')
jp = np.array(Image.open(os.path.join('SRC', T1)).convert('RGBA'))
ink = ndimage.binary_dilation(jp[:, :, 3] > 16, disk(3))
print('photo ink mask px', int(ink.sum()))
assert ink.sum() > 50000, 'photo mask consumed no ink'
clean = photo
ys, xs = np.where(ink)
lab_i, n = ndimage.label(ink, np.ones((3, 3)))
for sl in ndimage.find_objects(lab_i):
    y0, y1 = max(0, sl[0].start - 24), min(720, sl[0].stop + 24)
    x0, x1 = max(0, sl[1].start - 24), min(1280, sl[1].stop + 24)
    clean = inpaint_diffuse(clean, (x0, y0, x1, y1),
                            ink[y0:y1, x0:x1], smooth=1.1, iters=400)
clean.save('probe/PHOTO_clean.png')
en = Image.open(os.path.join('OUT', T1)).convert('RGBA')
out = clean.copy()
out.alpha_composite(en)
out.save(os.path.join('OUT', PH))
print('written photo')

