# -*- coding: utf-8 -*-
"""Split the 5 AI-translation collages (Downloads/1..5.png) into 15 separate
tutorial images, correcting each to its original's aspect ratio/dimensions.

Layout discovered by inspection:
  Collages 1-4 (standard): TOP = full-width image N (vertically squished),
                           BOTTOM-LEFT = N+1, BOTTOM-RIGHT = N+2  (both ~16:9)
  Collage 5  (mirrored):  TOP-LEFT = 13, TOP-RIGHT = 14, BOTTOM = full-width 15
Each crop is resized to the exact original dimensions so it is a drop-in,
aspect-correct replacement (the full-width crops get un-squished vertically).
"""
from pathlib import Path
from PIL import Image

TOOLING = Path(__file__).resolve().parent.parent
DL = Path("C:/Users/sw/Downloads")
ORIG = TOOLING / "extracted_images" / "_IkaseruGame" / "UI" / "Tutorial" / "TutorialPagePics"
OUT = TOOLING / "images_translated"

NAMES = {
    1: "tutorial_01_controls", 2: "tutorial_02_currency", 3: "tutorial_03_saisen",
    4: "tutorial_04_ido", 5: "tutorial_05_store", 6: "tutorial_06_part_charm",
    7: "tutorial_07_mental_state", 8: "tutorial_08_slot_intro", 9: "tutorial_09_symbol_pattern",
    10: "tutorial_10_red_button", 11: "tutorial_11_six66", 12: "tutorial_12_game_loop",
    13: "tutorial_13_modifier", 14: "tutorial_14_start_demo", 15: "tutorial_15_finish_demo",
}


INSET = 16  # px trimmed off INTERNAL seam edges to drop neighbor-border bleed


def regions(W, H, collage):
    """Return list of (tutorial_number, (x0,y0,x1,y1)) for a collage.
    Internal seam edges (the midline cuts) are inset by INSET; outer image
    edges are kept flush."""
    xm, ym = W // 2, H // 2
    s = INSET
    if collage <= 4:
        n = (collage - 1) * 3
        return [
            (n + 1, (0, 0, W, ym - s)),          # top full-width: bottom is seam
            (n + 2, (0, ym + s, xm - s, H)),     # BL: top+right are seams
            (n + 3, (xm + s, ym + s, W, H)),     # BR: top+left are seams
        ]
    # collage 5: two on top, full-width bottom
    return [
        (13, (0, 0, xm - s, ym - s)),    # TL: bottom+right seams
        (14, (xm + s, 0, W, ym - s)),    # TR: bottom+left seams
        (15, (0, ym + s, W, H)),         # bottom full-width: top is seam
    ]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for c in range(1, 6):
        im = Image.open(DL / f"{c}.png").convert("RGB")
        W, H = im.size
        for num, box in regions(W, H, c):
            crop = im.crop(box)
            ow, oh = Image.open(ORIG / f"{NAMES[num]}.png").size
            out = crop.resize((ow, oh), Image.LANCZOS)
            out.save(OUT / f"{NAMES[num]}.png")
            print(f"{NAMES[num]:30s} crop {crop.size} -> {(ow, oh)}")


if __name__ == "__main__":
    main()
