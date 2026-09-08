"""Per-image probe: component-id overlay + optional grid zooms."""
import sys, os
sys.path.insert(0, '.')
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from imgtl import components

os.makedirs('probe', exist_ok=True)
FB = ImageFont.truetype('C:/Windows/Fonts/arialbd.ttf', 15)


def load(name):
    return Image.open(os.path.join('SRC', name)).convert('RGBA')


def comp_overlay(im, tag, minpx=40, scale=1):
    lab, recs = components(im)
    bg = Image.new('RGBA', im.size, (128, 128, 128, 255))
    bg.alpha_composite(im)
    bg = bg.convert('RGB')
    d = ImageDraw.Draw(bg)
    for r in recs:
        if r['px'] < minpx:
            continue
        x0, y0, x1, y1 = r['box']
        d.rectangle([x0, y0, x1 - 1, y1 - 1], outline=(0, 255, 0))
        d.text((x0 + 1, y0 + 1), str(r['id']), font=FB, fill=(255, 255, 0),
               stroke_width=2, stroke_fill=(0, 0, 0))
    if scale != 1:
        bg = bg.resize((bg.width * scale, bg.height * scale), Image.LANCZOS)
    bg.save('probe/%s_comps.png' % tag)
    return lab, recs


def grid(im, box, path, f=3, step=20, bg=(128, 128, 128, 255)):
    c = im.crop(box)
    g = Image.new('RGBA', c.size, bg)
    g.alpha_composite(c)
    g = g.resize((c.width * f, c.height * f), Image.LANCZOS).convert('RGB')
    d = ImageDraw.Draw(g)
    for x in range((box[0] // step) * step, box[2], step):
        px = (x - box[0]) * f
        if px < 0:
            continue
        d.line([(px, 0), (px, g.height)], fill=(0, 255, 0))
        d.text((px + 2, 2), str(x), fill=(255, 255, 0))
    for y in range((box[1] // step) * step, box[3], step):
        py = (y - box[1]) * f
        if py < 0:
            continue
        d.line([(0, py), (g.width, py)], fill=(0, 255, 0))
        d.text((2, py + 2), str(y), fill=(255, 255, 0))
    g.save(path)


def rot(im, box, path, ang, f=4, bg=(128, 128, 128, 255)):
    c = im.crop(box)
    g = Image.new('RGBA', c.size, bg)
    g.alpha_composite(c)
    g = g.rotate(ang, resample=Image.BICUBIC, expand=True, fillcolor=bg)
    g = g.resize((g.width * f, g.height * f), Image.LANCZOS)
    g.convert('RGB').save(path)
