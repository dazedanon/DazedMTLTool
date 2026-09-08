# -*- coding: utf-8 -*-
"""Shared helpers for typesetting translated text onto the tutorial images.

Workflow per image: load source PNG, erase JP regions (border-safe), render EN
centered/left with optional pink/colored highlight runs and a soft glow.
"""
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

TOOLING = Path(__file__).resolve().parent.parent
SRC = TOOLING / "extracted_images" / "_IkaseruGame" / "UI" / "Tutorial" / "TutorialPagePics"
OUT = TOOLING / "extracted_images_translated"

SERIF = "C:/Windows/Fonts/georgia.ttf"
SERIF_B = "C:/Windows/Fonts/georgiab.ttf"

PINK = (217, 143, 208)
WHITE = (245, 240, 250)
BODY = (207, 192, 232)
HOTPINK = (255, 63, 176)
CYAN = (127, 208, 255)
RED = (255, 80, 80)
GOLD = (255, 176, 48)
BG = (0, 0, 16, 255)


def load(name):
    return Image.open(SRC / f"{name}.png").convert("RGBA")


def save(img, name):
    OUT.mkdir(parents=True, exist_ok=True)
    img.save(OUT / f"{name}.png")


def font(sz, bold=False):
    path = SERIF_B if bold and Path(SERIF_B).exists() else SERIF
    return ImageFont.truetype(path, sz)


class Typesetter:
    def __init__(self, img):
        self.img = img
        self.d = ImageDraw.Draw(img)
        self.a = np.asarray(img.convert("RGB")).astype(int)

    # ---- measurement ----
    def jp_vspan(self, x0, x1, y0, y1):
        """Vertical extent of text within a band (for tight label erasing)."""
        reg = self.a[y0:y1, x0:x1]
        m = (reg.sum(2) > 230) | ((reg.max(2) - reg.min(2)) > 55)
        ys = np.where(m.any(1))[0]
        return (y0 + int(ys.min()), y0 + int(ys.max())) if len(ys) else None

    def jp_xspan(self, y0, y1, x0, x1):
        reg = self.a[y0:y1, x0:x1]
        m = (reg.sum(2) > 230) | ((reg.max(2) - reg.min(2)) > 55)
        xs = np.where(m.any(0))[0]
        return (x0 + int(xs.min()), x0 + int(xs.max())) if len(xs) else None

    # ---- erase ----
    def erase(self, x0, y0, x1, y1, bg=BG, feather=False):
        if not feather:
            self.img.paste(Image.new("RGBA", (x1 - x0, y1 - y0), bg), (x0, y0))
        else:
            w, h = x1 - x0, y1 - y0
            patch = Image.new("RGBA", (w + 24, h + 24), bg)
            mask = Image.new("L", patch.size, 0)
            ImageDraw.Draw(mask).rectangle([12, 12, w + 12, h + 12], fill=255)
            mask = mask.filter(ImageFilter.GaussianBlur(8))
            self.img.paste(patch, (x0 - 12, y0 - 12), mask)
        # keep the numpy view in sync for later measurements
        self.a = np.asarray(self.img.convert("RGB")).astype(int)

    def erase_sample(self, x0, y0, x1, y1, sample_xy):
        """Erase with a colour sampled from the live image (for non-black panels)."""
        bg = tuple(self.img.convert("RGB").getpixel(sample_xy)) + (255,)
        self.erase(x0, y0, x1, y1, bg=bg)

    # ---- render ----
    def _glow(self, pos, txt, f, col, anchor):
        g = Image.new("RGBA", self.img.size, (0, 0, 0, 0))
        ImageDraw.Draw(g).text(pos, txt, font=f, fill=col + (170,), anchor=anchor)
        g = g.filter(ImageFilter.GaussianBlur(5))
        self.img.alpha_composite(g)

    def center(self, txt, f, col, cx, cy, glow=False, tracking=0):
        if tracking:
            total = sum(self.d.textlength(c, font=f) + tracking for c in txt) - tracking
            x = cx - total / 2
            for c in txt:
                if glow:
                    self._glow((x, cy), c, f, col, "lm")
                self.d.text((x, cy), c, font=f, fill=col + (255,), anchor="lm")
                x += self.d.textlength(c, font=f) + tracking
            return
        if glow:
            self._glow((cx, cy), txt, f, col, "mm")
        self.d.text((cx, cy), txt, font=f, fill=col + (255,), anchor="mm")

    def left(self, txt, f, col, x, cy, glow=False):
        if glow:
            self._glow((x, cy), txt, f, col, "lm")
        self.d.text((x, cy), txt, font=f, fill=col + (255,), anchor="lm")

    def runs(self, segs, f, x, cy, default, anchor="lm"):
        """segs = [(text, color_or_None), ...] drawn inline starting at x."""
        for t, c in segs:
            self.d.text((x, cy), t, font=f, fill=(c or default) + (255,), anchor=anchor)
            x += self.d.textlength(t, font=f)
        return x

    def para(self, lines, f, cx, cy, default, lh, center=True, glow=False):
        """lines = list of segs; each segs = [(text,color),...]. Centered or left at cx."""
        for i, segs in enumerate(lines):
            y = cy + i * lh
            total = sum(self.d.textlength(t, font=f) for t, _ in segs)
            x = cx - total / 2 if center else cx
            if glow:
                # glow the whole line subtly
                gx = x
                for t, c in segs:
                    self._glow((gx, y), t, f, (c or default), "lm")
                    gx += self.d.textlength(t, font=f)
            for t, c in segs:
                self.d.text((x, y), t, font=f, fill=(c or default) + (255,), anchor="lm")
                x += self.d.textlength(t, font=f)
