#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Composite the character-creation screen at its real coordinates.

`Bitmap.drawText` SQUEEZES rather than clips, and a DTextPicture caption has no
box at all - it is drawn at an absolute x/y and simply runs into whatever is
next to it. So neither a width check nor a screenshot skim catches this: the
only thing that does is drawing the widgets IN RELATION TO EACH OTHER, with the
game's own font at the game's own size, and looking.

Renders the JP source and the EN output side by side from the same code, so the
before/after pair is directly comparable.
"""
import os, sys, json, argparse
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from mztl import config  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("-o", "--out", default=os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "creation_screen.png"))
args = ap.parse_args()

cfg = config.Config()
W, H = 816, 624
FONT = cfg.font_path


def read(data_dir):
    """[(text, fontSize, x, y)] for the caption pictures on this screen."""
    with open(os.path.join(data_dir, "Map002.json"), encoding="utf-8-sig") as f:
        d = json.load(f)
    L = d["events"][1]["pages"][0]["list"]
    out, pending = [], None
    for c in L:
        p = c.get("parameters") or []
        if c.get("code") == 357 and len(p) > 3 and p[0] == "DTextPicture":
            a = p[3] if isinstance(p[3], dict) else {}
            pending = (a.get("text", "").replace("\n", ""),
                       int(a.get("fontSize", 32)))
        elif c.get("code") == 231 and pending is not None:
            if len(p) > 5 and not p[1]:
                out.append((pending[0], pending[1], int(p[4]), int(p[5])))
            pending = None
    return out


def render(rows, title):
    img = Image.new("RGB", (W, H), (12, 12, 16))
    d = ImageDraw.Draw(img)
    # Only the first three label pictures plus the three value columns are on
    # screen at once; the rest are the per-branch preparations.
    seen_y = {}
    for text, size, x, y in rows:
        seen_y.setdefault((x, y), text)
    for (x, y), text in seen_y.items():
        f = ImageFont.truetype(FONT, 32)
        d.text((x, y), text, font=f, fill=(238, 238, 238))
    d.line([(0, 0), (0, H)], fill=(60, 60, 80))
    small = ImageFont.load_default()
    d.text((8, 8), title, font=small, fill=(255, 210, 120))
    return img


src = os.path.join(os.path.dirname(HERE), "data_backup_20260824_160344")
out = os.path.join(HERE, "out", "data")
a = render(read(src)[:3] + [r for r in read(src) if r[2] in (300, 430)][:3],
           "JP  (source)")
b = render(read(out)[:3] + [r for r in read(out) if r[2] in (300, 430)][:3],
           "EN  (patched, value column 300 -> 430)")
sheet = Image.new("RGB", (W, H * 2 + 8), (0, 0, 0))
sheet.paste(a, (0, 0))
sheet.paste(b, (0, H + 8))
sheet.save(args.out)
print("wrote", args.out)
