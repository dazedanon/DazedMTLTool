#!/usr/bin/env python3
"""
clean_text.py — finish a painted mask into a transparent text-free PNG.

Pipeline per image NAME (expects tooling/maskwork/NAME_{flat,mask,orig}.png,
produced by mask_painter.py):

  1. Composite the Qwen Object-Remover output back ONLY inside the painted mask
     (everything outside the mask stays pixel-identical to the original).
  2. White-fill any residual colored overlay (thin arrows/hearts) that sit over
     the background gap and were under-painted.
  3. Restore transparency by BORDER-FLOOD-FILL through light pixels — this
     reclaims all background (incl. reconstructed areas under removed text)
     but stops at the character, so character art is never cut.

The Qwen step itself runs in ComfyUI and is driven by the agent (this script
takes the already-fetched Qwen output as `--gen`). Steps 1–3 are pure Pillow.

Usage:
  python tooling/clean_text.py NAME --gen /path/to/qwen_output.png
       [--gap X0 X1]      # central background gap x-range for arrow fill (default 430 610)
       [--out tooling/NAME_EN.png]
"""
import os, sys, argparse
import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "tooling", "maskwork")


def composite_in_mask(flat, gen, mask, feather=3):
    if gen.size != flat.size:
        gen = gen.resize(flat.size, Image.LANCZOS)
    o = np.array(flat.convert("RGB")).astype(np.float32)
    g = np.array(gen.convert("RGB")).astype(np.float32)
    m = mask.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(feather))
    mm = (np.array(m).astype(np.float32) / 255.0)[:, :, None]
    return (o * (1 - mm) + g * mm).clip(0, 255).astype(np.uint8)


def fill_gap_arrows(rgb, gap_x0, gap_x1):
    a = rgb.astype(np.int32)
    R, G, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    mx = a.max(2); mn = a.min(2); sat = mx - mn
    H, W = R.shape
    pink = (R > 195) & (B > 140) & (G < R - 15) & (sat > 25)
    band = np.zeros((H, W), bool)
    band[:, gap_x0:gap_x1] = True
    m = (pink & band).astype("uint8") * 255
    mi = Image.fromarray(m).filter(ImageFilter.MaxFilter(7)).filter(ImageFilter.GaussianBlur(2))
    mm = np.array(mi).astype(np.float32) / 255
    out = a.astype(np.float32)
    for c in range(3):
        out[:, :, c] = out[:, :, c] * (1 - mm) + 255 * mm
    return out.clip(0, 255).astype(np.uint8)


def restore_alpha(clean_rgb, orig_rgba, painted_mask):
    """STRICT rule: alpha == original EVERYWHERE outside the painted mask
    (no flood, no hole-fill -> can never cut hair/outline NOR invent an opaque
    white patch where the original was transparent). ONLY inside the painted
    region do we recompute: transparent where the stitched RGB reconstructed to
    background (light + low-saturation), else keep the original alpha (skin/hair
    that was under the removed text)."""
    new = clean_rgb.astype(np.int32)
    oa = np.array(orig_rgba)[:, :, 3]
    painted = np.array(painted_mask.filter(ImageFilter.MaxFilter(5))) > 40
    mx = new.max(2); sat = new.max(2) - new.min(2)
    recon_bg = (mx > 236) & (sat < 24)
    alpha = oa.copy()
    alpha[painted & recon_bg] = 0
    return np.dstack([clean_rgb, alpha]).astype("uint8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--gen", required=True, help="Qwen Object-Remover output PNG")
    ap.add_argument("--gap", nargs=2, type=int, default=[430, 610])
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    flat = Image.open(os.path.join(WORK, f"{a.name}_flat.png"))
    mask = Image.open(os.path.join(WORK, f"{a.name}_mask.png")).convert("L")
    orig = Image.open(os.path.join(WORK, f"{a.name}_orig.png")).convert("RGBA")
    gen = Image.open(a.gen)

    comp = composite_in_mask(flat, gen, mask)
    comp = fill_gap_arrows(comp, a.gap[0], a.gap[1])
    res = restore_alpha(comp, orig, mask)

    out = a.out or os.path.join(ROOT, "tooling", f"{a.name}_EN.png")
    Image.fromarray(res, "RGBA").save(out)

    # quick previews next to output
    r = Image.fromarray(res, "RGBA")
    blk = Image.new("RGBA", r.size, (20, 20, 20, 255)); blk.alpha_composite(r)
    blk.convert("RGB").save(out.replace(".png", "_onblack.png"))
    print("saved", out, "| opaque px", int((res[:, :, 3] > 10).sum()))


if __name__ == "__main__":
    main()
