# -*- coding: utf-8 -*-
"""Typeset English onto the Qwen-cleaned plate for tutorial_02_currency.

Plate: work/qwen_out/fb_t02_plate_final_00001_.png (JP erased, borders/numbers/
pink EN subtitles preserved). We render the white JP-replacement lines (title +
two labels) and the two body paragraphs (white with pink highlight runs),
positioned where the JP was, sized/colored to match the original style.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

TOOLING = Path(__file__).resolve().parent.parent
PLATE = TOOLING / "work" / "qwen_out" / "fb_t02_plate_final_00001_.png"
OUT = TOOLING / "extracted_images_translated" / "tutorial_02_currency.png"

SERIF = "C:/Windows/Fonts/georgia.ttf"
SERIF_B = "C:/Windows/Fonts/georgiab.ttf"
WHITE = (245, 242, 250)
PINK = (224, 120, 210)

def font(sz, bold=False):
    return ImageFont.truetype(SERIF_B if bold else SERIF, sz)

def glow(img, pos, txt, f, col, anchor, a=150, blur=6):
    g = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(g).text(pos, txt, font=f, fill=col + (a,), anchor=anchor)
    img.alpha_composite(g.filter(ImageFilter.GaussianBlur(blur)))

def center(d, img, txt, f, col, cx, cy, tracking=0, gl=True):
    if tracking:
        total = sum(d.textlength(c, font=f) + tracking for c in txt) - tracking
        x = cx - total / 2
        for c in txt:
            if gl: glow(img, (x, cy), c, f, col, "lm")
            d.text((x, cy), c, font=f, fill=col + (255,), anchor="lm")
            x += d.textlength(c, font=f) + tracking
    else:
        if gl: glow(img, (cx, cy), txt, f, col, "mm")
        d.text((cx, cy), txt, font=f, fill=col + (255,), anchor="mm")

def runs_centered(d, img, segs, f, cx, cy, gl=True):
    total = sum(d.textlength(t, font=f) for t, _ in segs)
    x = cx - total / 2
    for t, c in segs:
        col = c or WHITE
        if gl: glow(img, (x, cy), t, f, col, "lm", a=110, blur=5)
        d.text((x, cy), t, font=f, fill=col + (255,), anchor="lm")
        x += d.textlength(t, font=f)

SRC = TOOLING / "extracted_images" / "_IkaseruGame" / "UI" / "Tutorial" / "TutorialPagePics" / "tutorial_02_currency.png"

def main():
    img = Image.open(PLATE).convert("RGBA")
    src = Image.open(SRC).convert("RGBA")

    # restore the counter interiors (icon + 13 / 3) from the original — erase clipped them.
    # paste the inner area of each counter box (clear of the purple border ornaments).
    img.paste(src.crop((255, 410, 870, 515)), (255, 410))   # left counter: heart icon + "13" (digits y464-490)
    img.paste(src.crop((1330, 440, 1560, 545)), (1330, 440))  # right counter: "3"

    # restore the pink EN subtitle glosses (a "keep" element the erase dimmed)
    img.paste(src.crop((730, 245, 2240, 290)), (730, 245))   # CURRENCY & TICKET (title gloss)
    img.paste(src.crop((470, 928, 650, 968)), (470, 928))    # CURRENCY (left)
    img.paste(src.crop((1370, 963, 1500, 1000)), (1370, 963))  # TICKET (right)

    d = ImageDraw.Draw(img)

    # --- Title (white, wide tracking): measured JP center y153, above pink gloss y250 ---
    center(d, img, "Currency & Tickets", font(96), WHITE, 1486, 153, tracking=10)

    # --- Labels (bold white): measured 快楽ポイント center y849, チケット center y896 ---
    center(d, img, "Pleasure Points", font(58, bold=True), WHITE, 642, 849, tracking=2)
    center(d, img, "Tickets", font(58, bold=True), WHITE, 2125, 896, tracking=2)

    # --- Left paragraph (3 lines), measured rows y1034-1265 (cx ~ 642) ---
    fb = font(40)
    lh = 80
    lx, ly = 642, 1065
    lines_L = [
        [("This room's unique currency. The", None)],
        [("goal is to earn it by ", None), ("spinning the slots", PINK)],
        [("to escape", PINK), (" the room.", None)],
    ]
    for i, segs in enumerate(lines_L):
        runs_centered(d, img, segs, fb, lx, ly + i * lh)

    # --- Right paragraph (2 lines), measured rows y1073-1215 (cx ~ 2125) ---
    rx, ry = 2125, 1110
    lines_R = [
        [("Used in the store to buy ", None), ("“Charms”", PINK)],
        [("that help you progress.", None)],
    ]
    for i, segs in enumerate(lines_R):
        runs_centered(d, img, segs, fb, rx, ry + i * lh)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(OUT)
    print("saved", OUT)

if __name__ == "__main__":
    main()
