"""Translate the five hand-lettered graffiti overlays.

Re-runnable: reads SRC, writes OUT, never stacks onto a previous output.
Erase is by connected component, so every kept doodle stays byte-identical.
"""
import sys, os
sys.path.insert(0, '.')
import numpy as np
from PIL import Image
from scipy import ndimage
import imgtl
from imgtl import components, comp_sheet, comp_stamp, marker_line, put_stamp

HAND = 'C:/Windows/Fonts/comicbd.ttf'
O = '\u25cb'                       # the source's own censor ring
WHITE = (255, 255, 255, 255)
BLACK = (0, 0, 0, 255)
PINK_T = (255, 107, 194, 255)      # tousatu series
PINK_Y = (255, 75, 181, 255)       # yuuwaku series

os.makedirs('OUT', exist_ok=True)


def build(name, keep, lines, pink, part=None, stamps=None, tag=''):
    src = Image.open(os.path.join('SRC', name)).convert('RGBA')
    H, W = src.height, src.width
    lab, recs = components(src)
    allids = [r['id'] for r in recs]

    erase = np.isin(lab, [i for i in allids if i not in keep])
    if part:                       # a component that is text AND decoration
        for cid, axis, op, val in part:
            m = lab == cid
            Y, X = np.mgrid[0:H, 0:W]
            co = X if axis == 'x' else Y
            m &= (co < val) if op == '<' else (co >= val)
            erase |= m
    erase = ndimage.binary_dilation(erase, np.ones((5, 5)))
    assert erase.sum() > 5000, 'erase consumed no ink'
    a = np.array(src)
    a[erase] = (0, 0, 0, 0)
    img = Image.fromarray(a)

    cut = {k: comp_stamp(src, lab, c, ymin=y0, ymax=y1)
           for k, (c, y0, y1) in (stamps or {}).items()}

    S = {'PW': dict(fill=pink, outline=WHITE),      # pink fill, white outline
         'WP': dict(fill=WHITE, outline=pink),      # white fill, pink outline
         'BP': dict(fill=BLACK, outline=pink),      # black fill, pink outline
         'PB': dict(fill=pink, outline=BLACK),
         'BW': dict(fill=BLACK, outline=WHITE),
         'K': dict(fill=BLACK, outline=None)}
    for ln in lines:
        if ln[0] == 'stamp':
            _, key, cx, cy = ln[:4]
            sc = ln[4] if len(ln) > 4 else 1.0
            put_stamp(img, cut[key], (cx, cy), scale=sc)
            continue
        txt, p0, p1, h, style = ln[:5]
        kw = dict(S[style])
        kw.update(ln[5] if len(ln) > 5 else {})
        marker_line(img, txt, p0, p1, h, HAND, **kw)

    img.save(os.path.join('OUT', name))
    print('written', name.encode('ascii', 'replace').decode(),
          '| erased %d px' % erase.sum())
    return img


# ---------------------------------------------------------------- T1
build('tousaturakugaki010101.png',
      keep=[1, 2, 3, 13, 17, 23],
      part=[(2, 'x', '<', 235)],
      stamps={'h': (23, None, None)},
      pink=PINK_T,
      lines=[
          ('LOOK',  (80, 212), (232, 172), 66, 'PW'),
          ('HERE!', (88, 282), (230, 243), 76, 'PW'),
          ('JERK OFF', (985, 200), (1180, 192), 78, 'PW'),
          ('WELCOME', (1010, 312), (1205, 300), 96, 'PW'),
          ('THICC', (275, 330), (415, 385), 56, 'PW'),
          ('stamp', 'h', 458, 420, 0.70),
          ('LEWD BODY', (300, 405), (470, 448), 58, 'PW'),
          ('BIG-TIT LADY KNIGHT', (505, 490), (1155, 520), 112, 'BP'),
          ('BATHING', (685, 640), (915, 628), 105, 'PW'),
      ])

# ---------------------------------------------------------------- T2
build('tousaturakugaki010201.png',
      keep=[6, 13, 16, 19, 20, 25, 29, 38, 47, 48, 49, 50, 51, 55, 59, 61],
      pink=PINK_T,
      lines=[
          ('SEX-RELIEF', (175, 70), (385, 62), 55, 'BP'),
          ('LADY KNIGHT', (240, 114), (400, 108), 52, 'BP'),
          ('SC' + O + 'RLET', (172, 176), (405, 169), 55, 'BP'),
          ('WAITING', (425, 52), (545, 46), 52, 'BP'),
          ('FOR OFFERS~', (420, 100), (655, 92), 62, 'BP'),
          ('MOUTH', (772, 204), (858, 202), 24, 'K'),
          ('P' + O + 'SSY', (772, 229), (858, 227), 24, 'K'),
          ('SHLK', (492, 278), (536, 238), 46, 'BP'),
          ('SHLK', (658, 368), (700, 308), 46, 'BP'),
          ('FUCK-HOLES', (940, 275), (1125, 250), 75, 'BP'),
          ('ALL READY', (1000, 345), (1160, 330), 70, 'BP'),
          ("I'M AN EASY TRASH-P" + O + 'SSY', (340, 622), (790, 612), 88, 'BP'),
          ('-LOVING GIRL', (895, 550), (1195, 560), 100, 'WP'),
      ])

# ---------------------------------------------------------------- T3
build('tousaturakugaki010301.png',
      keep=[4, 12, 15, 22, 24, 25, 30, 48, 49, 56, 62, 63, 64, 88, 91, 93, 95,
            97, 99, 114],
      stamps={'h': (4, None, None)},
      pink=PINK_T,
      lines=[
          ('PUBLIC-TOILET LADY KNIGHT', (95, 82), (525, 72), 74, 'BP'),
          ('SCARLET', (180, 162), (410, 155), 58, 'BP'),
          ('stamp', 'h', 455, 158, 1.15),
          ('PERKY', (508, 118), (618, 112), 34, 'WP'),
          ('NIPS', (528, 148), (618, 143), 34, 'WP'),
          ('SOFT', (425, 210), (540, 205), 38, 'BP'),
          ('TIT-P' + O + 'SSY', (458, 245), (578, 240), 38, 'BP'),
          ('stamp', 'h', 596, 246, 0.62),
          ('MOUTH', (775, 202), (858, 200), 22, 'K'),
          ('ONAHOLE', (775, 226), (858, 224), 22, 'K'),
          ('SPOT HER?', (990, 196), (1155, 190), 58, 'K'),
          ('USE HER' + O.replace(O, ''), (990, 250), (1195, 246), 62, 'K'),
          ('stamp', 'h', 1218, 258, 0.85),
          ('CUM-DUMP', (672, 322), (795, 372), 42, 'BP'),
          ('TITS', (690, 385), (778, 420), 42, 'BP'),
          ('stamp', 'h', 800, 400, 0.85),
          ('FILTHY! FREE P' + O + 'SSY', (872, 372), (1240, 368), 58, 'BP'),
          ('ONAHOLE', (1048, 440), (1245, 436), 62, 'BP'),
          ('stamp', 'h', 1030, 432, 0.90),
          ('PERFECT', (412, 420), (505, 448), 44, 'BP'),
          ('ASS-HOLE', (425, 478), (525, 512), 44, 'BP'),
          ('SOAKED', (212, 580), (312, 575), 48, 'WP'),
          ('stamp', 'h', 328, 572, 0.75),
          ('WAY IN', (318, 645), (412, 640), 60, 'WP'),
          ('stamp', 'h', 430, 638, 0.85),
          ('USE ANYTIME', (468, 588), (708, 582), 50, 'BP'),
          ('ALL SET', (472, 636), (690, 630), 50, 'WP'),
          ('stamp', 'h', 706, 630, 0.80),
          ('FEELS', (850, 585), (1150, 578), 88, 'BP'),
          ('AMAZING!', (955, 665), (1158, 658), 84, 'BP'),
      ])

# ---------------------------------------------------------------- Y2
build('yuuwakurakugaki010201.png',
      keep=[15, 23, 65, 71, 72, 74, 79, 80, 84, 85, 91],
      pink=PINK_Y,
      lines=[
          ('SUPER-LEWD LADY KNIGHT', (512, 62), (872, 56), 66, 'BP'),
          ('NOW SEDUCING...', (672, 148), (975, 142), 72, 'BP'),
          ('BEING WATCHED...', (1170, 30), (1170, 400), 72, 'BP'),
          ('IS TURNING ME ON...', (1068, 60), (1068, 665), 56, 'BP'),
          ('SENSITIVE NIPPLES', (280, 215), (262, 495), 52, 'BP'),
          ("SCRATCH 'EM", (196, 248), (188, 470), 44, 'BP'),
          ('TITFUCK', (642, 292), (778, 300), 46, 'PW'),
          ('ENTRANCE', (672, 342), (812, 348), 46, 'PW'),
          ('HUGE BOOBS', (922, 250), (912, 475), 58, 'BP'),
          ('WAITING TO BE GROPED', (866, 405), (860, 645), 48, 'BP'),
          ('MY P' + O + "SSY'S", (92, 598), (295, 592), 52, 'BP'),
          ('ALL SET TOO', (138, 655), (462, 648), 62, 'BP'),
          ('WAY IN!', (742, 642), (802, 640), 38, 'PW'),
          ('SQUELCH', (746, 692), (830, 690), 34, 'PW'),
      ])

# ---------------------------------------------------------------- Y3
build('yuuwakurakugaki010301.png',
      keep=[82, 83, 86, 91, 96, 97, 100, 101, 107, 108, 112, 114, 124, 143,
            148, 151, 158, 162, 163, 164, 165, 167, 172, 179, 180,
            5, 13, 25],
      part=[(145, 'x', '<', 928)],
      pink=PINK_Y,
      lines=[
          ('LOVES CUM', (692, 54), (1160, 46), 78, 'BP'),
          ('SCARLET', (768, 128), (1100, 122), 76, 'BP'),
          ("SORRY I'M SUCH A", (26, 106), (258, 102), 32, 'BP'),
          ('MASO-SLUT KNIGHT...', (26, 140), (232, 136), 30, 'K'),
          ('LET ME APOLOGIZE BY', (22, 174), (250, 170), 32, 'BP'),
          ('SERVING YOUR C' + O + 'CK', (22, 208), (240, 204), 32, 'BP'),
          ('RAW HOLE', (340, 152), (488, 148), 52, 'PB'),
          ('TOTAL C' + O + 'CK', (72, 328), (288, 322), 62, 'K'),
          ('OBEDIENCE!', (156, 412), (466, 406), 82, 'K'),
          ('DISPOSABLE', (598, 280), (742, 276), 40, 'K'),
          ('TIT-PUSSY', (522, 398), (632, 512), 46, 'BP'),
          ('ASS-P' + O + 'SSY TOO', (842, 285), (1000, 280), 48, 'BP'),
          ('SQUELCHING', (886, 325), (1022, 320), 46, 'BP'),
          ('SUPER-LOOSE', (934, 405), (926, 528), 40, 'BP'),
          ('PLEASE USE IT', (896, 432), (888, 572), 40, 'BP'),
          ('ANYTIME, ANYWHERE', (30, 528), (330, 500), 52, 'K'),
          ('SLOPPY-FUCK  CUM-DUMP TOILET', (28, 588), (628, 542), 62, 'WP'),
          ('EASY-P' + O + 'SSY ONAHOLE', (1108, 250), (1100, 600), 56, 'BP'),
          ('FOLLOWS ANYONE!', (1182, 250), (1176, 630), 58, 'K'),
      ])
