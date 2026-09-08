#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
translate_images.py — project driver: render English versions of natuiso's flat
UI text images using img_translate.py as the engine. Translations + layout for
THIS game live here; the reusable engine stays in img_translate.py.

  python translate_images.py            # -> images_en/ (+ images_en/_previews/)
"""
import os, sys, json
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import img_translate as IT

SRC = "jp_text_images"
OUT = "images_en"
PREV = os.path.join(OUT, "_previews")
EN_FONT = "natuiso_extracted/system/fonts/fonts.en_us.otf"

DIALOG_TEXT = [70, 70, 72]


def dialog_box(path, ymin=95, ymax=150):
    """Auto-find the single centered dark text line on the gradient panel."""
    im = np.array(Image.open(path).convert("RGB")); W = im.shape[1]
    lum = im.mean(2)
    ys, xs = np.where(lum < 140)
    pts = [(int(y), int(x)) for y, x in zip(ys, xs) if ymin < y < ymax and 60 < x < W - 60]
    by = [p[0] for p in pts]; bx = [p[1] for p in pts]
    return [min(bx) - 10, min(by) - 5, max(bx) + 10, max(by) + 5]


def render(path, regions):
    im = IT.load_img(path)
    orig = im.copy()
    for r in regions:
        r["_src"] = path
        im = IT.erase(im, r)
        im = IT.render_region(im, r, EN_FONT)
    rel = os.path.relpath(path, SRC)
    dest = os.path.join(OUT, rel)
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    im.save(dest)
    # preview (orig over result on a checkerboard so transparency is visible)
    pv = Image.new("RGBA", (orig.width, orig.height * 2 + 8), (200, 200, 200, 255))
    pv.paste(orig, (0, 0), orig); pv.paste(im, (0, orig.height + 8), im)
    os.makedirs(PREV, exist_ok=True)
    pv.convert("RGB").save(os.path.join(PREV, rel.replace(os.sep, "__") + ".png"))
    print("  ", rel)


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)) + "/..")  # project root
    print("Rendering English UI images -> %s" % OUT)

    # ---- 1) confirmation dialogs (shared gradient panel template) ----
    dialogs = {
        "system/dialog/dialog_load.png":       "Load this game?",
        "system/dialog/dialog_save.png":       "Save this game?",
        "system/dialog/dialog_quit.png":       "Quit the game?",
        "system/dialog/dialog_title.png":      "Return to the title screen?",
        "system/dialog/dialog_savedelete.png": "Delete this save data?",
        "system/dialog/dialog_saveupdate.png": "Overwrite this save data?",
    }
    # All dialog text sits at y120-135; use ONE fixed height so every dialog matches.
    DLG_H = 19
    for rel, en in dialogs.items():
        p = os.path.join(SRC, rel)
        render(p, [
            {"box": dialog_box(p), "en": "", "erase": "rowbg", "ref_x": 30},  # clean JP
            {"box": [40, 113, 562, 142], "en": en, "erase": "none", "color": DIALOG_TEXT,
             "align": "center", "size": {"height": DLG_H}},                   # fixed-size text
        ])

    # NOTE: system/dialog/sample.png is a developer LAYOUT MOCK (the game composes the
    # real confirmation from dialog_title.png + separate ○/× button + checkbox assets),
    # so it is intentionally skipped — it is not a shipping asset.

    # ---- 2) autosave info bar (white text on a TRANSLUCENT black bar) ----
    # bar = [0,0,0,128] center with lighter edges; copy a clean bar column per row
    # so the translucency + edge profile are preserved exactly.
    # text is x53-225; icon (gray) ends ~x28. Start text at x48 for icon spacing.
    p = os.path.join(SRC, "system/autosave/info.png")
    render(p, [{"box": [48, 2, 242, 34], "en": "Autosaved", "erase": "rowbg", "ref_x": 245,
                "color": [255, 255, 255], "align": "left", "size": "auto"}])

    # ---- 2b) "don't ask again" checkbox label, 3 states (same text; keep each checkbox) ----
    # 215x35; checkbox x0-29, text x40-214 dark-grey (48,48,48). Text is on transparency.
    for f in ("kakunin", "kakunin_check", "kakunin_over"):
        p = os.path.join(SRC, "system/dialog/%s.png" % f)
        render(p, [
            {"box": [34, 0, 215, 35], "en": "", "erase": "clear"},           # wipe JP, keep checkbox
            {"box": [40, 13, 212, 33], "en": "Don't ask again", "erase": "none",
             "color": [48, 48, 48], "align": "left", "size": {"height": 17}},
        ])

    # ---- 3) age/disclaimer warning (white on black; wipe black, re-render) ----
    p = os.path.join(SRC, "system/menu/title/waring.png")
    render(p, [
        {"box": [0, 0, 1280, 720], "en": "", "erase": "solid", "bg": [0, 0, 0]},
        {"box": [200, 86, 1080, 184], "erase": "none", "color": [255, 255, 255],
         "align": "center", "line_spacing": 0.35, "size": "auto",
         "en": "This product is intended for those aged 18 and over.\n"
               "Persons under 18 may not play this product."},
        {"box": [310, 246, 970, 315], "erase": "none", "color": [255, 255, 255],
         "align": "center", "line_spacing": 0.35, "size": "auto",
         "en": "This work is a work of fiction. Any persons or\n"
               "organizations appearing in it bear no relation to reality."},
        {"box": [330, 372, 950, 476], "erase": "none", "color": [255, 255, 255],
         "align": "center", "line_spacing": 0.3, "size": "auto",
         "en": "This work depicts acts that may constitute crimes.\n"
               "Should you commit similar acts in reality, you may face\n"
               "severe legal punishment, so please exercise caution."},
        {"box": [180, 520, 1100, 588], "erase": "none", "color": [210, 210, 210],
         "align": "center", "wrap": True, "line_spacing": 0.3, "size": "auto",
         "en": "All images contained in this product (including those on the packaging and "
               "enclosed printed materials) are legally protected as copyrighted works. Illegal "
               "acts such as reproduction, lending, adaptation, alteration or public transmission "
               "may incur civil liability and criminal penalties, even if you were merely involved "
               "in another person's act."},
        {"box": [300, 606, 980, 632], "erase": "none", "color": [210, 210, 210],
         "align": "center", "size": "auto",
         "en": "This product is sold in Japan only (Japan sales only). "
               "We do not provide support for environments outside Japan."},
    ])

    # ---- 4) stylized SAMPLE placeholders ----
    # nameplate: original is pink-red fill (240,168,168) + BLACK outline, ~39px tall
    p = os.path.join(SRC, "system/nameplate/nameplate_キャラ１.png")
    render(p, [
        {"box": [0, 0, 480, 60], "en": "", "erase": "clear"},  # wipe all old text
        {"box": [8, 4, 440, 56], "en": "Character 1", "erase": "none",
         "color": [240, 168, 168], "outline": [0, 0, 0], "outline_width": 3,
         "align": "left", "size": {"height": 34}},
    ])

    # staff-roll: text is WHITE (240,240,240) fill + dark-BLUE (24,48,120) outline, ~37px;
    # the separator is a yellow star (drawn). Keep the chibi art / outer stars.
    STAFF = dict(color=[240, 240, 240], outline=[24, 48, 120], outline_width=3)
    # 00 "キャスト" -> CAST (single word, between the kept star pairs at x72 / x240)
    render(os.path.join(SRC, "system/menu/staffroll/00_sanple.PNG"),
           [{"box": [74, 2, 244, 49], "en": "CAST", "erase": "clear",
             "align": "center", "size": {"height": 30}, **STAFF}])
    # 01 chibi ends x133 -> clear right of it (generous), then place the credit
    # left-aligned at ~x142 (where the original text began), not centered.
    render(os.path.join(SRC, "system/menu/staffroll/01_sanple.PNG"),
           [{"box": [135, 4, 884, 121], "en": "", "erase": "clear"},
            {"box": [142, 4, 884, 121], "erase": "none", "align": "left",
             "name_parts": ["Burunyan-Man", "Kaneda Mahiru"], "size": {"height": 34}, **STAFF}])
    render(os.path.join(SRC, "system/menu/staffroll/02_sanple.PNG"),
           [{"box": [90, 8, 552, 110], "en": "", "erase": "clear"},
            {"box": [94, 8, 552, 110], "erase": "none", "align": "left",
             "name_parts": ["Kuroneko", "Momose Poko"], "size": {"height": 34}, **STAFF}])

    print("Done. Results in %s/ (previews in %s/)." % (OUT, PREV))
    print("Note: nameplate + staffroll are stylized dev SAMPLES; font match is approximate.")


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        try: s.reconfigure(encoding="utf-8", errors="replace")
        except Exception: pass
    main()
