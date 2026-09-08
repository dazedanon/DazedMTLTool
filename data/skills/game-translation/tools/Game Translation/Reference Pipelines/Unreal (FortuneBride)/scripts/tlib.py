# -*- coding: utf-8 -*-
"""Typesetting helper: render English text onto a Qwen-cleaned plate, placed
inside the rectangles the user drew in the mask tool.

A `block` is one text element. You give it a box (usually a saved rect), the
English lines, a base color, optional highlight phrases (rendered in an accent
colour, e.g. quoted game terms), alignment, and styling. Font size auto-fits the
box width unless pinned. Text is vertically centred in the box.
"""
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

SERIF = "C:/Windows/Fonts/georgia.ttf"
SERIF_B = "C:/Windows/Fonts/georgiab.ttf"
SERIF_I = "C:/Windows/Fonts/georgiai.ttf"

# palette sampled from the originals
WHITE = (244, 240, 250)
BODY = (210, 196, 232)        # lavender body text
PINK = (228, 130, 214)        # quoted-term accent
HOTPINK = (255, 110, 195)
RED = (255, 90, 90)
GOLD = (255, 180, 60)
CYAN = (140, 210, 255)
GREEN = (150, 230, 130)


def font(sz, style="r"):
    return ImageFont.truetype({"r": SERIF, "b": SERIF_B, "i": SERIF_I}[style], int(sz))


class Plate:
    def __init__(self, name, plate_dir="work/tut_plates", reg_dir="work/tut_regions"):
        self.name = name
        self.img = Image.open(Path(plate_dir) / f"{name}.png").convert("RGBA")
        self.d = ImageDraw.Draw(self.img)
        j = Path(reg_dir) / f"{name}.json"
        self.rects = json.loads(j.read_text())["rects"] if j.exists() else []

    def rect(self, i):
        return self.rects[i]

    def erase_fill(self, box, grow=8, feather=6, strip=12):
        """PIL-fill a box from the plate's own background (vertical gradient
        sampled just above/below), for captions not covered by the Qwen erase."""
        import numpy as np
        arr = np.asarray(self.img.convert("RGB")).astype(int)
        x0, y0, x1, y1 = box
        x0 = max(0, x0 - grow); y0 = max(0, y0 - grow)
        x1 = min(self.img.width, x1 + grow); y1 = min(self.img.height, y1 + grow)
        top = arr[max(0, y0 - strip):max(1, y0 - 2), x0:x1]
        bot = arr[min(arr.shape[0] - 1, y1 + 2):min(arr.shape[0], y1 + strip), x0:x1]
        m = lambda a: tuple(int(np.median(a[..., c])) for c in range(3)) if a.size else (10, 6, 16)
        ct, cb = m(top), m(bot)
        w, h = x1 - x0, y1 - y0
        grad = Image.new("RGB", (w, h))
        gd = ImageDraw.Draw(grad)
        for i in range(h):
            t = i / max(1, h - 1)
            gd.line([(0, i), (w, i)], fill=tuple(int(ct[c] + (cb[c] - ct[c]) * t) for c in range(3)))
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).rectangle([feather, feather, w - feather, h - feather], fill=255)
        mask = mask.filter(ImageFilter.GaussianBlur(feather))
        self.img.paste(grad, (x0, y0), mask)
        self.d = ImageDraw.Draw(self.img)

    # ---- run splitting for highlights ----
    @staticmethod
    def _runs(text, highlights):
        segs = [(text, None)]
        if highlights:
            for phrase, col in sorted(highlights.items(), key=lambda kv: -len(kv[0])):
                out = []
                for t, c in segs:
                    if c is not None or phrase not in t:
                        out.append((t, c)); continue
                    k = t.find(phrase)
                    if k > 0: out.append((t[:k], None))
                    out.append((phrase, col))
                    if k + len(phrase) < len(t): out.append((t[k + len(phrase):], None))
                segs = out
        return segs

    def _linew(self, segs, f):
        return sum(self.d.textlength(t, font=f) for t, _ in segs)

    def _glow(self, pos, t, f, col, anchor, a=120, blur=5):
        g = Image.new("RGBA", self.img.size, (0, 0, 0, 0))
        ImageDraw.Draw(g).text(pos, t, font=f, fill=col + (a,), anchor=anchor)
        self.img.alpha_composite(g.filter(ImageFilter.GaussianBlur(blur)))

    def block(self, box, lines, color=BODY, highlights=None, align="center",
              size=None, max_size=64, min_size=14, style="r", glow=False,
              tracking=0, lh_factor=1.5, pad=0.92, valign="center", center_x=None,
              left_x=None):
        """Render `lines` (list of str) inside `box`=[x0,y0,x1,y1]."""
        x0, y0, x1, y1 = box
        bw, bh = (x1 - x0) * pad, (y1 - y0)
        seglines = [self._runs(s, highlights) for s in lines]

        # choose font size: largest that fits width AND total height
        def fits(sz):
            f = font(sz, style)
            wide = max((self._linew(sl, f) + tracking * sum(len(t) for t, _ in sl)) for sl in seglines)
            tall = len(seglines) * sz * lh_factor
            return wide <= bw and tall <= bh
        if size:
            fs = size
        else:
            fs = max_size
            while fs > min_size and not fits(fs):
                fs -= 1
        f = font(fs, style)
        lh = fs * lh_factor
        total_h = len(seglines) * lh
        if valign == "center":
            cy = y0 + (bh - total_h) / 2 + lh / 2
        elif valign == "top":
            cy = y0 + lh / 2
        else:
            cy = y1 - total_h + lh / 2

        for sl in seglines:
            lw = self._linew(sl, f) + tracking * sum(len(t) for t, _ in sl)
            if align == "center":
                cxx = center_x if center_x is not None else (x0 + x1) / 2
                x = cxx - lw / 2
            elif align == "right":
                x = x1 * pad - lw
            else:
                x = left_x if left_x is not None else x0 + (x1 - x0) * (1 - pad) / 2
            for t, c in sl:
                col = c or color
                if tracking:
                    for ch in t:
                        if glow: self._glow((x, cy), ch, f, col, "lm")
                        self.d.text((x, cy), ch, font=f, fill=col + (255,), anchor="lm")
                        x += self.d.textlength(ch, font=f) + tracking
                else:
                    if glow: self._glow((x, cy), t, f, col, "lm")
                    self.d.text((x, cy), t, font=f, fill=col + (255,), anchor="lm")
                    x += self.d.textlength(t, font=f)
            cy += lh
        return fs

    def save(self, out_dir="images_translated"):
        p = Path(out_dir); p.mkdir(parents=True, exist_ok=True)
        self.img.convert("RGB").save(p / f"{self.name}.png")
        return p / f"{self.name}.png"
