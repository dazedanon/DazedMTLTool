#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Find images that carry BAKED text.

The game ships `img/` encrypted (`.png_`) and `img.zip` holding the same PNGs
in the clear, so the survey reads the zip and the deploy re-encrypts. Only the
folders a player reads text out of are considered - characters, tilesets,
battlebacks, parallaxes and the 330 enemy sheets are art, and putting 900
sprite sheets through a contact sheet buries the six images that matter.
"""
import os, sys, io, re, zipfile, argparse
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ZIP = os.path.join(ROOT, "img.zip")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "img")

# Folders whose contents are read, not just looked at.
UI_DIRS = ("img/system", "img/titles1", "img/titles2", "img/pictures")
# Inside pictures/, the character art is the bulk and carries no text.
ART_RE = re.compile(
    r"busts/|立ち絵|衣裳|衣装|破れ|全裸|下着|魔法陣|背景|水着|浴衣|"
    r"バスタオル|巫女服|ハロウィン|バニー|花嫁|冬服|ウェイトレス", re.I)

ap = argparse.ArgumentParser()
ap.add_argument("--sheet", default=os.path.join(OUT, "contact.png"))
ap.add_argument("--cols", type=int, default=6)
ap.add_argument("--cell", type=int, default=300)
ap.add_argument("--extract", action="store_true")
args = ap.parse_args()

os.makedirs(OUT, exist_ok=True)
z = zipfile.ZipFile(ZIP)
names = [n for n in z.namelist() if n.lower().endswith((".png", ".jpg"))]
cands = [n for n in names
         if any(n.startswith(d + "/") for d in UI_DIRS) and not ART_RE.search(n)]
cands.sort()
print("candidate UI images: %d of %d" % (len(cands), len(names)))
for n in cands:
    print("   ", n)

if args.extract:
    for n in cands:
        dst = os.path.join(OUT, n.replace("/", "__"))
        with open(dst, "wb") as f:
            f.write(z.read(n))
    print("extracted -> %s" % OUT)

# contact sheet
cell, cols = args.cell, args.cols
rows = (len(cands) + cols - 1) // cols
sheet = Image.new("RGB", (cols * cell, rows * (cell + 18)), (24, 24, 30))
from PIL import ImageDraw, ImageFont
d = ImageDraw.Draw(sheet)
try:
    fnt = ImageFont.truetype("arial.ttf", 11)
except Exception:
    fnt = ImageFont.load_default()
for i, n in enumerate(cands):
    try:
        im = Image.open(io.BytesIO(z.read(n))).convert("RGBA")
    except Exception:
        continue
    bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
    bg.alpha_composite(im)
    im = bg.convert("RGB")
    im.thumbnail((cell - 8, cell - 8))
    x = (i % cols) * cell + 4
    y = (i // cols) * (cell + 18) + 4
    sheet.paste(im, (x, y))
    d.text((x, y + cell - 6), os.path.basename(n)[:40], font=fnt,
           fill=(200, 200, 210))
sheet.save(args.sheet)
print("contact sheet -> %s  (%dx%d)" % (args.sheet, sheet.width, sheet.height))
