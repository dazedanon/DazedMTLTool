# -*- coding: utf-8 -*-
"""Batch Qwen Object-Remover erase for the tutorial images.

For each image: upload FModel source + the hand-drawn mask to ComfyUI, run the
InpaintCrop -> (Lightning + Object-Remover) erase -> InpaintStitch graph, and
download the clean plate (masked text removed, everything else pixel-identical).

Usage:
  python scripts/qwen_erase_batch.py                 # all 15
  python scripts/qwen_erase_batch.py tutorial_02_currency tutorial_04_ido
"""
import json
import sys
import time
import urllib.request
import urllib.parse
from pathlib import Path

from PIL import Image, ImageFilter

DILATE = 16  # px grown on every mask so the solid core covers all glyphs and
             # the feathered erase edge falls on empty background (kills the
             # faint edge-residue that tight masks leave on small labels)

COMFY = "http://127.0.0.1:8188"
TOOLING = Path(__file__).resolve().parent.parent
SRC_DIR = Path(r"C:/Users/sw/Desktop/Tools/C++/FModel/Output/Exports/NoEcstasyNoLife/Content/_IkaseruGame/UI/Tutorial/TutorialPagePics")
MASK_DIR = TOOLING / "work" / "tut_masks"
OUT_DIR = TOOLING / "work" / "tut_plates"


def upload(path, name):
    import io
    boundary = "----fbbound"
    data = path.read_bytes()
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="image"; filename="{name}"\r\n'
        f"Content-Type: image/png\r\n\r\n"
    ).encode() + data + (
        f"\r\n--{boundary}\r\n"
        f'Content-Disposition: form-data; name="overwrite"\r\n\r\ntrue\r\n'
        f"--{boundary}--\r\n"
    ).encode()
    req = urllib.request.Request(f"{COMFY}/upload/image", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    urllib.request.urlopen(req).read()


def build(img_name, mask_name, prefix):
    return {
        "38": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_2.5_vl_7b_fp8_scaled.safetensors", "type": "qwen_image", "device": "default"}},
        "39": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
        "115": {"class_type": "NunchakuQwenImageDiTLoader", "inputs": {"model_name": "nunchaku_qwen_image_edit_2511_best_quality_int4.safetensors", "cpu_offload": "auto", "num_blocks_on_gpu": 60, "use_pin_memory": "disable"}},
        "78": {"class_type": "LoadImage", "inputs": {"image": img_name}},
        "79": {"class_type": "LoadImageMask", "inputs": {"image": mask_name, "channel": "red"}},
        "210": {"class_type": "InpaintCropImproved", "inputs": {"image": ["78", 0], "mask": ["79", 0], "downscale_algorithm": "bilinear", "upscale_algorithm": "bicubic", "preresize": False, "preresize_mode": "ensure minimum resolution", "preresize_min_width": 1024, "preresize_min_height": 1024, "preresize_max_width": 16384, "preresize_max_height": 16384, "mask_fill_holes": True, "mask_expand_pixels": 12, "mask_invert": False, "mask_blend_pixels": 20, "mask_hipass_filter": 0.1, "extend_for_outpainting": False, "extend_up_factor": 1, "extend_down_factor": 1, "extend_left_factor": 1, "extend_right_factor": 1, "context_from_mask_extend_factor": 1.2, "output_resize_to_target_size": False, "output_target_width": 1024, "output_target_height": 1024, "output_padding": "32", "device_mode": "gpu (much faster)"}},
        "117": {"class_type": "NunchakuQwenImageLoraStackV3", "inputs": {"model": ["115", 0], "lora_count": 2, "cpu_offload": "disable", "toggle_all": True, "enabled_1": True, "lora_name_1": "Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors", "lora_strength_1": 1, "enabled_2": True, "lora_name_2": "Qwen-Image-Edit-2511-Object-Remover.safetensors", "lora_strength_2": 1}},
        "66": {"class_type": "ModelSamplingAuraFlow", "inputs": {"shift": 3, "model": ["117", 0]}},
        "75": {"class_type": "CFGNorm", "inputs": {"strength": 1, "model": ["66", 0]}},
        "110": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {"prompt": "Remove the text from the image while preserving the background, panels, gradients, ornate borders, photos and all other elements. Fill the area with the matching background.", "clip": ["38", 0], "vae": ["39", 0], "image1": ["210", 1]}},
        "111": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {"prompt": "text, letters, characters, japanese, kanji, katakana, watermark, blurry, distortion, artifacts", "clip": ["38", 0], "vae": ["39", 0], "image1": ["210", 1]}},
        "220": {"class_type": "InpaintModelConditioning", "inputs": {"positive": ["110", 0], "negative": ["111", 0], "vae": ["39", 0], "pixels": ["210", 1], "mask": ["210", 2], "noise_mask": True}},
        "3": {"class_type": "KSampler", "inputs": {"seed": 42, "steps": 4, "cfg": 1, "sampler_name": "euler", "scheduler": "simple", "denoise": 1, "model": ["75", 0], "positive": ["220", 0], "negative": ["220", 1], "latent_image": ["220", 2]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["39", 0]}},
        "230": {"class_type": "InpaintStitchImproved", "inputs": {"stitcher": ["210", 0], "inpainted_image": ["8", 0]}},
        "119": {"class_type": "SaveImage", "inputs": {"filename_prefix": prefix, "images": ["230", 0]}},
    }


def enqueue(wf):
    body = json.dumps({"prompt": wf}).encode()
    req = urllib.request.Request(f"{COMFY}/prompt", data=body, headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req))["prompt_id"]


def wait(pid, timeout=180):
    t0 = time.time()
    while time.time() - t0 < timeout:
        h = json.load(urllib.request.urlopen(f"{COMFY}/history/{pid}"))
        if h:
            return h[pid]
        time.sleep(2)
    raise TimeoutError(pid)


def fetch(hist, dest):
    for node in hist["outputs"].values():
        for im in node.get("images", []):
            q = urllib.parse.urlencode({"filename": im["filename"], "subfolder": im.get("subfolder", ""), "type": im["type"]})
            data = urllib.request.urlopen(f"{COMFY}/view?{q}").read()
            dest.write_bytes(data)
            return im["filename"]


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    names = sys.argv[1:] or [p.stem for p in sorted(SRC_DIR.glob("tutorial_*.png"))]
    for i, name in enumerate(names, 1):
        src = SRC_DIR / f"{name}.png"
        mask = MASK_DIR / f"{name}.png"
        if not mask.exists():
            print(f"[{i}/{len(names)}] {name}: NO MASK, skip")
            continue
        upload(src, f"fb_{name}.png")
        # dilate the mask before upload so the erase fully covers glyph edges
        dil_dir = MASK_DIR.parent / "tut_masks_dil"
        dil_dir.mkdir(exist_ok=True)
        m = Image.open(mask).convert("L").filter(
            ImageFilter.GaussianBlur(DILATE)).point(lambda v: 255 if v > 36 else 0)
        dil = dil_dir / f"{name}.png"
        m.save(dil)
        upload(dil, f"fbm_{name}.png")
        pid = enqueue(build(f"fb_{name}.png", f"fbm_{name}.png", f"plate_{name}"))
        hist = wait(pid)
        fn = fetch(hist, OUT_DIR / f"{name}.png")
        print(f"[{i}/{len(names)}] {name}: erased -> {fn}", flush=True)


if __name__ == "__main__":
    main()
