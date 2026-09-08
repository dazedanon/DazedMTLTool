# -*- coding: utf-8 -*-
"""Drive the Qwen_TextTranslate_2pass ComfyUI workflow per text-region.

Instead of hand-painting a MaskEditor mask, we generate a grayscale mask PNG
from explicit rectangles (the JP-text boxes we can see in each image), feed the
full source image + that mask into the workflow's InpaintCrop (via LoadImageMask),
and run the two passes:
  A) Object-Remover LoRA erases the masked text -> clean plate
  B) Lightning writes the English text guided by a per-region style prompt
The crop/stitch keeps everything outside the mask pixel-identical to the source.

This module only PREPARES artifacts and emits the API-format workflow dict; the
MCP layer uploads files and enqueues. Run standalone to (re)generate masks.

A "region" can carry several rectangles (e.g. a multi-line paragraph) that are
all erased together and rewritten as one English block.
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

TOOLING = Path(__file__).resolve().parent.parent
SRC = TOOLING / "extracted_images" / "_IkaseruGame" / "UI" / "Tutorial" / "TutorialPagePics"
MASK_DIR = TOOLING / "work" / "qwen_masks"
WF_DIR = TOOLING / "work" / "qwen_workflows"


def make_mask(src_name: str, region_id: str, rects, size, feather: int = 6) -> Path:
    """White rectangles (text to replace) on black, same size as the source."""
    MASK_DIR.mkdir(parents=True, exist_ok=True)
    m = Image.new("L", size, 0)
    d = ImageDraw.Draw(m)
    for (x0, y0, x1, y1) in rects:
        d.rectangle([x0, y0, x1, y1], fill=255)
    if feather:
        m = m.filter(ImageFilter.GaussianBlur(feather))
        # re-threshold core to keep solid coverage, blurred edge stays soft
        m = m.point(lambda v: 255 if v > 40 else v)
    out = MASK_DIR / f"{src_name}__{region_id}.png"
    m.save(out)
    return out


def build_workflow(base_api: dict, image_filename: str, mask_filename: str,
                   write_prompt: str, remove_prompt: str | None = None,
                   neg_write: str | None = None) -> dict:
    """Return a copy of the 2pass API workflow wired to load a separate mask
    image (LoadImageMask) instead of the embedded MaskEditor alpha, with the
    per-region English/style prompt substituted into pass B."""
    wf = json.loads(json.dumps(base_api))  # deep copy

    # node 78 LoadImage -> point at our region's full source image
    wf["78"]["inputs"]["image"] = image_filename

    # add a LoadImageMask node and rewire InpaintCrop.mask (210) to it
    wf["79"] = {
        "class_type": "LoadImageMask",
        "_meta": {"title": "region mask (auto-generated)"},
        "inputs": {"image": mask_filename, "channel": "red"},
    }
    wf["210"]["inputs"]["mask"] = ["79", 0]

    # pass B positive prompt (write English in matching style)
    wf["1101"]["inputs"]["prompt"] = write_prompt
    if remove_prompt:
        wf["1100"]["inputs"]["prompt"] = remove_prompt
    if neg_write:
        wf["1111"]["inputs"]["prompt"] = neg_write

    # unique save prefix so results don't collide
    return wf


if __name__ == "__main__":
    # standalone: regenerate all masks from regions.json if present
    reg_path = TOOLING / "scripts" / "qwen_regions.json"
    if reg_path.exists():
        data = json.loads(reg_path.read_text(encoding="utf-8"))
        for img_name, spec in data.items():
            src = SRC / f"{img_name}.png"
            size = Image.open(src).size
            for reg in spec["regions"]:
                p = make_mask(img_name, reg["id"], reg["rects"], size)
                print("mask:", p.name)
