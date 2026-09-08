#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
img_translate.py — replace baked-in text in images with a translation, matching
the original style. Spec-driven and reusable: a per-image JSON lists text regions
(box, original, translation, erase method, font/color/align). `detect` seeds the
spec via OCR; `render` produces the translated image + a side-by-side preview.

Only suitable for flat text on simple backgrounds (UI dialogs, solid/gradient
panels, text on transparent layers). Stylized typography over artwork (logos,
eyecatch cards, angled SFX) needs manual design — this tool won't match those.

  python img_translate.py detect  img.png -o spec.json [--gpu]
  python img_translate.py render  spec.json -o out_dir

Erase methods (per region):
  rowbg   fill the box using the background colour sampled per-row from a clean
          column (perfect for vertical gradients / horizontally-uniform panels)
  solid   fill with a colour (given, or auto = dominant colour around the box)
  inpaint OpenCV inpaint (mild textures)
  clear   set the box to fully transparent (RGBA text-only layers)
"""
import os, sys, json, argparse
import numpy as np
from PIL import Image, ImageDraw, ImageFont


def load_img(path):
    im = Image.open(path)
    return im.convert("RGBA")


def auto_text_color(im, box):
    """Pick the dominant non-background (darkest-or-most-saturated) colour in box."""
    a = np.array(im.crop(box).convert("RGB")).reshape(-1, 3)
    lum = a.mean(1)
    # text is the minority extreme vs background; pick pixels far from the median bg
    bg = np.median(a, 0)
    dist = np.abs(a.astype(int) - bg).sum(1)
    sel = a[dist > dist.max() * 0.5]
    if len(sel) == 0:
        sel = a[lum < np.percentile(lum, 10)]
    return tuple(int(x) for x in np.median(sel, 0)) if len(sel) else (0, 0, 0)


def erase(im, region):
    box = region["box"]
    method = region.get("erase", "rowbg")
    if method == "none":
        return im
    arr = np.array(im)
    x0, y0, x1, y1 = box
    if method == "clear":
        arr[y0:y1, x0:x1, 3] = 0
    elif method == "solid":
        c = region.get("bg")
        if c == "auto" or c is None:
            ring = np.array(im.crop((max(0, x0 - 8), y0, min(im.width, x1 + 8), y1)).convert("RGB"))
            c = [int(v) for v in np.median(ring.reshape(-1, 3), 0)]
        arr[y0:y1, x0:x1, :3] = c
        arr[y0:y1, x0:x1, 3] = 255
    elif method == "inpaint":
        import cv2
        rgb = arr[:, :, :3].copy()
        mask = np.zeros(arr.shape[:2], np.uint8)
        mask[y0:y1, x0:x1] = 255
        rgb = cv2.inpaint(rgb, mask, 3, cv2.INPAINT_TELEA)
        arr[:, :, :3] = rgb
    else:  # rowbg
        ref_x = region.get("ref_x", max(0, x0 - 12))
        for y in range(y0, y1):
            arr[y, x0:x1, :] = arr[y, ref_x, :]
    return Image.fromarray(arr)


def _wrap(font, text, max_w):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if font.getbbox(trial)[2] <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    return lines


def _lines_for(font_path, text, box, wrap, spacing):
    """Return (font, [lines]) fitting box. Honors explicit \\n; auto-wraps if wrap."""
    w = box[2] - box[0]
    h = box[3] - box[1]
    explicit = "\n" in text
    size = min(220, h if not (explicit or wrap) else h)
    while size > 6:
        f = ImageFont.truetype(font_path, size)
        if explicit:
            lines = text.split("\n")
        elif wrap:
            lines = _wrap(f, text, w * 0.98)
        else:
            lines = [text]
        widest = max((f.getbbox(ln)[2] - f.getbbox(ln)[0]) for ln in lines)
        lh = (f.getbbox("Ay")[3] - f.getbbox("Ay")[1])
        total_h = lh * len(lines) + int(lh * spacing) * (len(lines) - 1)
        if widest <= w * 0.99 and total_h <= h * 0.99:
            return f, lines
        size -= 1
    return ImageFont.truetype(font_path, 8), (text.split("\n") if explicit else [text])


def _font_for_height(font_path, text, target_h):
    lo, hi = 6, 400
    while lo < hi:
        mid = (lo + hi + 1) // 2
        f = ImageFont.truetype(font_path, mid)
        l, t, r, b = f.getbbox(text)
        if (b - t) <= target_h:
            lo = mid
        else:
            hi = mid - 1
    return ImageFont.truetype(font_path, lo)


def _draw_text(d, x, y, text, font, fill, outline, ow):
    if outline:
        oc = tuple(outline) if isinstance(outline, (list, tuple)) else outline
        for dx in range(-ow, ow + 1):
            for dy in range(-ow, ow + 1):
                if dx or dy:
                    d.text((x + dx, y + dy), text, font=font, fill=oc)
    d.text((x, y), text, font=font, fill=fill)


def _draw_star(d, cx, cy, r, fill, outline, ow):
    import math
    pts = []
    for i in range(10):
        ang = -math.pi / 2 + i * math.pi / 5
        rad = r if i % 2 == 0 else r * 0.42
        pts.append((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
    oc = tuple(outline) if isinstance(outline, (list, tuple)) else outline
    d.polygon(pts, fill=tuple(fill) if isinstance(fill, (list, tuple)) else fill,
              outline=oc, width=max(1, ow))


def render_region(im, region, default_font):
    box = region["box"]
    font_path = region.get("font") or default_font
    color = region.get("color", "auto")
    color = tuple(color) if isinstance(color, (list, tuple)) else color
    outline = region.get("outline")
    ow = int(region.get("outline_width", 2))

    # --- "A ★ B" credit layout with a drawn yellow star separator ---
    if region.get("name_parts"):
        a, b = region["name_parts"]
        sz = region.get("size", {})
        th0 = sz.get("height", 34) if isinstance(sz, dict) else (int(sz) if sz != "auto" else 34)
        avail = (box[2] - box[0]) * 0.98
        th = th0
        while th > 8:  # shrink to fit the box width
            font = _font_for_height(font_path, a + b, th)
            wa = font.getbbox(a)[2] - font.getbbox(a)[0]
            wb = font.getbbox(b)[2] - font.getbbox(b)[0]
            sr = int(th * 0.45)
            gap = int(th * 0.5)
            total = wa + gap + 2 * sr + gap + wb
            if total <= avail:
                break
            th -= 1
        d = ImageDraw.Draw(im)
        al = region.get("align", "center")
        if al == "left":
            x = box[0]
        elif al == "right":
            x = box[2] - total
        else:
            x = box[0] + (box[2] - box[0] - total) // 2
        cy = (box[1] + box[3]) // 2
        for part, w in ((a, wa), (None, 2 * sr), (b, wb)):
            if part is None:
                _draw_star(d, x + sr, cy, sr, region.get("star_fill", [245, 225, 95]),
                           outline or [24, 48, 120], max(2, ow))
            else:
                l, t, r, bb = font.getbbox(part)
                _draw_text(d, x - l, cy - (bb - t) // 2 - t, part, font, color, outline, ow)
            x += w + gap
        return im

    text = region.get("en", "")
    if not text:
        return im
    color = region.get("color", "auto")
    if color == "auto" or color is None:
        color = auto_text_color(Image.open(region["_src"]).convert("RGBA"), box) \
            if "_src" in region else (60, 60, 60)
    color = tuple(color) if isinstance(color, (list, tuple)) else color
    spacing = float(region.get("line_spacing", 0.25))
    wrap = bool(region.get("wrap", False))
    size = region.get("size", "auto")
    if isinstance(size, dict) and "height" in size:  # match a target glyph height
        base = max(text.split("\n"), key=len) if "\n" in text else text
        font = _font_for_height(font_path, base or "Ay", int(size["height"]))
        lines = text.split("\n") if "\n" in text else (_wrap(font, text, (box[2]-box[0]) * 0.98) if wrap else [text])
    elif size == "auto":
        font, lines = _lines_for(font_path, text, box, wrap, spacing)
    else:
        font = ImageFont.truetype(font_path, int(size))
        lines = text.split("\n") if "\n" in text else (_wrap(font, text, (box[2]-box[0]) * 0.98) if wrap else [text])
    d = ImageDraw.Draw(im)
    lh = (font.getbbox("Ay")[3] - font.getbbox("Ay")[1])
    step = lh + int(lh * spacing)
    total_h = lh * len(lines) + int(lh * spacing) * (len(lines) - 1)
    align = region.get("align", "center")
    y = box[1] + (box[3] - box[1] - total_h) // 2
    out = region.get("outline")
    ow = int(region.get("outline_width", 2))
    for ln in lines:
        l, t, r, b = font.getbbox(ln)
        tw = r - l
        if align == "center":
            x = box[0] + (box[2] - box[0] - tw) // 2 - l
        elif align == "right":
            x = box[2] - tw - l
        else:
            x = box[0] - l
        if out:
            oc = tuple(out) if isinstance(out, (list, tuple)) else (0, 0, 0)
            for dx in range(-ow, ow + 1):
                for dy in range(-ow, ow + 1):
                    if dx or dy:
                        d.text((x + dx, y - t + dy), ln, font=font, fill=oc)
        d.text((x, y - t), ln, font=font, fill=color)
        y += step
    return im


def cmd_render(args):
    spec = json.load(open(args.spec, encoding="utf-8"))
    src_path = spec["image"]
    default_font = spec.get("font")
    im = load_img(src_path)
    orig = im.copy()
    for reg in spec["regions"]:
        reg["_src"] = src_path
        im = erase(im, reg)
        im = render_region(im, reg, default_font)
    os.makedirs(args.out, exist_ok=True)
    base = os.path.basename(src_path)
    out_path = os.path.join(args.out, base)
    im.save(out_path)
    # side-by-side preview
    pv = Image.new("RGBA", (orig.width, orig.height * 2 + 8), (255, 255, 255, 255))
    pv.paste(orig, (0, 0)); pv.paste(im, (0, orig.height + 8))
    pv.convert("RGB").save(os.path.join(args.out, "_preview_" + os.path.splitext(base)[0] + ".png"))
    print("wrote", out_path)


def cmd_detect(args):
    import easyocr
    r = easyocr.Reader(["ja", "en"], gpu=args.gpu, verbose=False)
    res = r.readtext(args.image)
    regions = []
    for box, txt, conf in res:
        xs = [p[0] for p in box]; ys = [p[1] for p in box]
        regions.append({
            "box": [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))],
            "jp": txt, "en": "", "erase": "rowbg", "color": "auto",
            "align": "center", "size": "auto", "conf": round(float(conf), 3),
        })
    spec = {"image": args.image, "font": args.font, "regions": regions}
    json.dump(spec, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("wrote %s with %d regions (fill in 'en' and adjust 'erase')" % (args.out, len(regions)))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    pd = sub.add_parser("detect"); pd.add_argument("image"); pd.add_argument("-o", "--out", required=True)
    pd.add_argument("--font", default=None); pd.add_argument("--gpu", action="store_true")
    pd.set_defaults(func=cmd_detect)
    pr = sub.add_parser("render"); pr.add_argument("spec"); pr.add_argument("-o", "--out", default="img_out")
    pr.set_defaults(func=cmd_render)
    args = ap.parse_args()
    for s in (sys.stdout, sys.stderr):
        try: s.reconfigure(encoding="utf-8", errors="replace")
        except Exception: pass
    args.func(args)


if __name__ == "__main__":
    main()
