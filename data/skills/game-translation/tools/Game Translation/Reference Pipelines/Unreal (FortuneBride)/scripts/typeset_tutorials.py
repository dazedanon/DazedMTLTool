#!/usr/bin/env python3
"""Auto-typeset translated text onto the extracted tutorial images.

For each JP text element in tutorial_image_map.json:
  1. erase the JP by filling its box with the local background colour (these
     captions sit on near-flat dark panels, so an edge-sampled fill blends in),
  2. render the English translation centred/left in the box, in a serif font at
     the mapped colour, with optional per-phrase highlight colours.

Not pixel-perfect on busy photo backgrounds, but clean on the panel text.
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

TOOLING = Path(__file__).resolve().parent.parent
SRC = TOOLING / "extracted_images" / "_IkaseruGame" / "UI" / "Tutorial" / "TutorialPagePics"
OUT = TOOLING / "extracted_images_translated"
MAP = json.loads((TOOLING / "scripts" / "tutorial_image_map.json").read_text(encoding="utf-8"))

# a serif that approximates the original's letterspaced caption face
FONT_CANDIDATES = [
    "C:/Windows/Fonts/georgia.ttf",
    "C:/Windows/Fonts/timesbd.ttf",
    "C:/Windows/Fonts/times.ttf",
    "C:/Windows/Fonts/seguisb.ttf",
]


def load_font(size):
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def sample_bg(img, box):
    """Median colour of a ring just outside the text box = panel background."""
    x, y, w, h = box
    px = img.load()
    samples = []
    margin = 8
    for sx in range(max(0, x - margin), min(img.width, x + w + margin), 6):
        for sy in (max(0, y - margin), min(img.height - 1, y + h + margin)):
            samples.append(px[sx, sy][:3])
    for sy in range(max(0, y - margin), min(img.height, y + h + margin), 6):
        for sx in (max(0, x - margin), min(img.width - 1, x + w + margin)):
            samples.append(px[sx, sy][:3])
    if not samples:
        return (20, 12, 30)
    samples.sort(key=lambda c: c[0] + c[1] + c[2])
    return samples[len(samples) // 2]


def detect_text_box(img, hint, bg_thresh=70):
    """Within a coarse hint box [x,y,w,h], find the true bounding box of the
    text (pixels brighter than the dark panel background). Returns a tight box,
    or the hint if nothing detected."""
    x, y, w, h = hint
    x = max(0, x)
    y = max(0, y)
    w = min(w, img.width - x)
    h = min(h, img.height - y)
    region = np.asarray(img.convert("RGB"))[y : y + h, x : x + w]
    if region.size == 0:
        return hint
    bright = region.sum(axis=2) > bg_thresh * 3
    # also catch coloured (pink/red) text that isn't bright: high single channel
    coloured = (region.max(axis=2).astype(int) - region.min(axis=2).astype(int)) > 60
    mask = bright | coloured
    ys, xs = np.where(mask)
    if len(xs) < 20:
        return hint
    pad = 6
    bx = x + max(0, int(xs.min()) - pad)
    by = y + max(0, int(ys.min()) - pad)
    bw = int(xs.max() - xs.min()) + 2 * pad
    bh = int(ys.max() - ys.min()) + 2 * pad
    return [bx, by, bw, bh]


def erase_box(img, box):
    """Cover the JP text with the sampled background, feathered at the edges."""
    x, y, w, h = box
    bg = sample_bg(img, box)
    patch = Image.new("RGBA", (w + 24, h + 24), bg + (255,))
    # feather: blur a mask so the patch melts into the panel
    mask = Image.new("L", patch.size, 0)
    ImageDraw.Draw(mask).rectangle([12, 12, w + 12, h + 12], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(8))
    img.paste(patch, (x - 12, y - 12), mask)


def split_highlights(text, highlights):
    """Yield (substring, is_highlight, colour) runs for per-phrase colouring."""
    if not highlights:
        yield text, None
        return
    # longest phrases first so they aren't split by shorter ones
    phrases = sorted(highlights.items(), key=lambda kv: -len(kv[0]))
    segments = [(text, None)]
    for phrase, colour in phrases:
        new_segments = []
        for seg_text, seg_colour in segments:
            if seg_colour is not None or phrase not in seg_text:
                new_segments.append((seg_text, seg_colour))
                continue
            i = seg_text.find(phrase)
            if i > 0:
                new_segments.append((seg_text[:i], None))
            new_segments.append((phrase, colour))
            if i + len(phrase) < len(seg_text):
                new_segments.append((seg_text[i + len(phrase) :], None))
        segments = new_segments
    yield from segments


def wrap_text(text, font, max_width, draw):
    words = text.split(" ")
    lines, cur = [], ""
    for word in words:
        trial = (cur + " " + word).strip()
        if draw.textlength(trial, font=font) <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def draw_glow(img, pos, text, font, colour, anchor):
    """Soft glow behind bright pink/white text, matching the originals."""
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.text(pos, text, font=font, fill=colour + (180,), anchor=anchor)
    glow = glow.filter(ImageFilter.GaussianBlur(6))
    img.alpha_composite(glow)


def render_element(img, el):
    box = el["box"]
    x, y, w, h = box
    font = load_font(el.get("size", 36))
    draw = ImageDraw.Draw(img)
    base_colour = hex_to_rgb(el["color"])
    tracking = el.get("tracking", 0)
    highlights = {k: hex_to_rgb(v) for k, v in el.get("highlight", {}).items()}
    anchor_x = "left" in el.get("anchor", "center")

    text = el["en"]
    wrap = el.get("wrap")
    max_w = w
    lines = wrap_text(text, font, max_w, draw) if wrap else [text]

    line_h = int(el.get("size", 36) * 1.45)
    total_h = line_h * len(lines)
    start_y = y + (h - total_h) // 2 if h > total_h else y

    bright = sum(base_colour) > 600 or max(base_colour) > 220
    for li, line in enumerate(lines):
        ly = start_y + li * line_h
        runs = list(split_highlights(line, highlights))
        line_w = sum(draw.textlength(t, font=font) + tracking * len(t) for t, _ in runs)
        if anchor_x:
            cx = x
        else:
            cx = x + (w - line_w) // 2
        for run_text, run_colour in runs:
            colour = run_colour if run_colour else base_colour
            if tracking:
                for ch in run_text:
                    if bright:
                        draw_glow(img, (cx, ly), ch, font, colour, "la")
                    draw.text((cx, ly), ch, font=font, fill=colour + (255,), anchor="la")
                    cx += draw.textlength(ch, font=font) + tracking
            else:
                if bright:
                    draw_glow(img, (cx, ly), run_text, font, colour, "la")
                draw.text((cx, ly), run_text, font=font, fill=colour + (255,), anchor="la")
                cx += draw.textlength(run_text, font=font)


def process(name, spec):
    src = SRC / f"{name}.png"
    if not src.exists():
        print(f"missing source: {name}")
        return False
    img = Image.open(src).convert("RGBA")
    # detect tight JP boxes first (before any erasing changes the pixels), then
    # erase generously so no JP strokes peek out around the English
    for el in spec["elements"]:
        det = detect_text_box(img, el["box"])
        # union of the hint and the detected extent, so we never under-erase
        hx, hy, hw, hh = el["box"]
        dx, dy, dw, dh = det
        ux = min(hx, dx)
        uy = min(hy, dy)
        ux2 = max(hx + hw, dx + dw)
        uy2 = max(hy + hh, dy + dh)
        el["_erase"] = [ux, uy, ux2 - ux, uy2 - uy]
    for el in spec["elements"]:
        erase_box(img, el["_erase"])
    for el in spec["elements"]:
        render_element(img, el)
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"{name}.png"
    img.save(out)
    print(f"OK  {name}  ({len(spec['elements'])} elements)")
    return True


def main():
    names = sys.argv[1:] or list(MAP["images"].keys())
    for name in names:
        if name in MAP["images"]:
            process(name, MAP["images"][name])
        else:
            print(f"no map entry: {name}")


if __name__ == "__main__":
    main()
