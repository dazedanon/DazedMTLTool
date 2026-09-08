r"""Composite the main menu the way the engine draws it, and look at it.

    menu_mock.py [out.png] [--scale 0.85]

The engine gives every coordinate: the sub-item plate is 192x35 (MenuItem
subItemsBaseWidth/Height on the parent container), its art is the 9-sliced
window_02 texture, and a label is drawn at `24px * MenuItem.scale.X` from
`pos.X` with `origin = MiddleLeft`.

Drawing it here is the only way to judge a SIZE question without launching the
game, and it renders the Japanese through the identical code so the before/after
pair is honest rather than remembered.
"""

import csv
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageDraw                                     # noqa: E402
from artl import config, measure, store                              # noqa: E402

NODE = "9847d4a0-c4c6-4a43-96d5-8739260152d1"
IDXS = ("17", "18", "19", "20", "21", "22", "23", "24")
PLATE_W, PLATE_H = 192, 35
# From the texture's own alpha: the lozenge tapers over 0..48 and 88..136, with
# a flat full-height middle between. Slicing anywhere else deforms the caps.
CAP_L, CAP_R = 48, 48


def plate(src, w, h):
    """3-slice the plate texture to `w`, then scale to `h`."""
    tw, th = src.size
    mid_w = tw - CAP_L - CAP_R
    out = Image.new("RGBA", (w, th), (0, 0, 0, 0))
    out.paste(src.crop((0, 0, CAP_L, th)), (0, 0))
    stretch = src.crop((CAP_L, 0, CAP_L + mid_w, th)).resize(
        (max(1, w - CAP_L - CAP_R), th), Image.BILINEAR)
    out.paste(stretch, (CAP_L, 0))
    out.paste(src.crop((tw - CAP_R, 0, tw, th)), (w - CAP_R, 0))
    return out.resize((w, h), Image.LANCZOS)


def main(*argv):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    out_path = argv[0] if argv and not argv[0].startswith("--") else "menu_mock.png"
    trial = float(argv[argv.index("--scale") + 1]) if "--scale" in argv else 0.85

    cfg = config.load()
    m = measure.resolve(cfg, cfg["layout_font_size"])
    tex = Image.open(os.path.join(cfg["game_dir"], "imgout", "res", "texture",
                                  "window_02.png")).convert("RGBA")
    with io.open(cfg["layout_tsv"], encoding="utf-8") as fh:
        rows = {(r["nodeGuid"], r["idx"]): r
                for r in csv.DictReader(fh, delimiter="\t")}
    docs = store.load_docs(cfg["store_dir"])
    tl = {}
    for _p, u in store.all_units(docs):
        if u["kind"] != "ui":
            continue
        p = u["key"].split(":")
        if len(p) == 4 and p[0] == "M":
            tl[(p[1], p[2])] = (u["raw"], (u.get("tl") or "").strip())

    cols = [("JP, author scale", "jp", None),
            ("EN, shipped scale", "en", None),
            ("EN at x%.2f" % trial, "en", trial)]
    pad, gap, head = 16, 12, 26
    W = pad * 2 + len(cols) * (PLATE_W + gap)
    H = head + pad + len(IDXS) * (PLATE_H + gap)
    img = Image.new("RGBA", (W, H), (16, 16, 22, 255))
    d = ImageDraw.Draw(img)
    label_font = measure.resolve(cfg, 13)._font
    for c, (title, _k, _s) in enumerate(cols):
        d.text((pad + c * (PLATE_W + gap), 6), title, font=label_font,
               fill=(150, 150, 165, 255))

    for r_i, idx in enumerate(IDXS):
        row = rows[(NODE, idx)]
        jp, en = tl[(NODE, idx)]
        base = float(row["scaleX"] or 1.0)
        y = head + pad + r_i * (PLATE_H + gap)
        for c, (_t, which, override) in enumerate(cols):
            x = pad + c * (PLATE_W + gap)
            img.alpha_composite(plate(tex, PLATE_W, PLATE_H), (x, y))
            text = jp if which == "jp" else en
            sc = base if override is None else override
            f = measure.resolve(cfg, max(1, int(round(cfg["layout_font_size"] * sc))))._font
            tw = f.getlength(text)
            bb = f.getbbox(text)
            tx = x + (PLATE_W - tw) / 2.0
            ty = y + (PLATE_H - (bb[3] - bb[1])) / 2.0 - bb[1]
            d.text((tx, ty), text, font=f, fill=(255, 255, 255, 255))
    img.save(out_path)
    print("wrote %s  (%dx%d)" % (out_path, W, H))
    print("plate %dx%d, font %s, layout size %dpx" %
          (PLATE_W, PLATE_H, m.family, cfg["layout_font_size"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
