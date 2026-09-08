# -*- coding: utf-8 -*-
"""Build Qwen-Image-Edit ComfyUI API workflows for tutorial text translation.

Two builders:
  build_inpaint_2pass(...) - InpaintCrop + (A) Object-Remover erase + (B) write EN.
  build_inpaint_1pass(...)  - InpaintCrop + single guided edit pass (cfg-controlled),
                              the most reliable for JP->EN swap on flat panels.

Both take a tight per-region mask image (white text-box on black) so only that
region is touched; InpaintStitch returns the rest pixel-identical to the source.

Resolution: we set output_target_{w,h} to a bucketed version of the *crop's*
aspect ratio (not a forced square) so wide-thin title strips are not distorted.
"""
from __future__ import annotations

QWEN_CLIP = "qwen_2.5_vl_7b_fp8_scaled.safetensors"
QWEN_VAE = "qwen_image_vae.safetensors"
QWEN_DIT = "nunchaku_qwen_image_edit_2511_best_quality_int4.safetensors"
LORA_LIGHT = "Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors"
LORA_REMOVE = "Qwen-Image-Edit-2511-Object-Remover.safetensors"


def _loaders():
    return {
        "38": {"class_type": "CLIPLoader",
               "inputs": {"clip_name": QWEN_CLIP, "type": "qwen_image", "device": "default"}},
        "39": {"class_type": "VAELoader", "inputs": {"vae_name": QWEN_VAE}},
        "115": {"class_type": "NunchakuQwenImageDiTLoader",
                "inputs": {"model_name": QWEN_DIT, "cpu_offload": "auto",
                           "num_blocks_on_gpu": 60, "use_pin_memory": "disable"}},
    }


def _crop(image_node, mask_node, ctx, tw, th, resize=False):
    return {"class_type": "InpaintCropImproved", "inputs": {
        "image": [image_node, 0], "mask": [mask_node, 0],
        "downscale_algorithm": "bilinear", "upscale_algorithm": "bicubic",
        "preresize": False, "preresize_mode": "ensure minimum resolution",
        "preresize_min_width": 1024, "preresize_min_height": 1024,
        "preresize_max_width": 16384, "preresize_max_height": 16384,
        "mask_fill_holes": True, "mask_expand_pixels": 12, "mask_invert": False,
        "mask_blend_pixels": 16, "mask_hipass_filter": 0.1,
        "extend_for_outpainting": False,
        "extend_up_factor": 1, "extend_down_factor": 1,
        "extend_left_factor": 1, "extend_right_factor": 1,
        "context_from_mask_extend_factor": ctx,
        "output_resize_to_target_size": resize,
        "output_target_width": tw, "output_target_height": th,
        "output_padding": "32", "device_mode": "gpu (much faster)"}}


def _lora_stack(remove: bool):
    if remove:
        return {"class_type": "NunchakuQwenImageLoraStackV3", "inputs": {
            "model": ["115", 0], "lora_count": 2, "cpu_offload": "disable", "toggle_all": True,
            "enabled_1": True, "lora_name_1": LORA_LIGHT, "lora_strength_1": 1.0,
            "enabled_2": True, "lora_name_2": LORA_REMOVE, "lora_strength_2": 1.0}}
    return {"class_type": "NunchakuQwenImageLoraStackV3", "inputs": {
        "model": ["115", 0], "lora_count": 1, "cpu_offload": "disable", "toggle_all": True,
        "enabled_1": True, "lora_name_1": LORA_LIGHT, "lora_strength_1": 1.0}}


def bucket(w, h, area=1024 * 1024, mult=64, long_edge=1536):
    """Aspect-preserving target ~area px, dims rounded to `mult`, with the
    longer edge capped at `long_edge` so very wide-thin strips stay sane."""
    ar = w / h
    th = (area / ar) ** 0.5
    tw = th * ar
    # cap the longer edge
    if tw >= th and tw > long_edge:
        tw, th = long_edge, long_edge / ar
    elif th > tw and th > long_edge:
        th, tw = long_edge, long_edge * ar
    tw = max(mult, int(round(tw / mult)) * mult)
    th = max(mult, int(round(th / mult)) * mult)
    return tw, th


def build_1pass(image_file, mask_file, write_prompt, neg_prompt,
                crop_w, crop_h, ctx=1.15, steps=8, cfg=2.5, seed=42,
                use_light=True, prefix="fb_1pass"):
    """Single guided edit pass through InpaintCrop/Stitch.
    use_light=True keeps 4-step Lightning LoRA (fast, cfg must be ~1);
    use_light=False uses base model so cfg>1 actually guides (slower)."""
    tw, th = bucket(crop_w, crop_h)
    wf = _loaders()
    wf["78"] = {"class_type": "LoadImage", "inputs": {"image": image_file}}
    wf["79"] = {"class_type": "LoadImageMask", "inputs": {"image": mask_file, "channel": "red"}}
    wf["210"] = _crop("78", "79", ctx, tw, th, resize=False)
    wf["117"] = _lora_stack(remove=False) if use_light else None
    model_src = "117"
    if not use_light:
        # base model: feed DiT straight into ModelSampling
        wf.pop("117", None)
        model_src = "115"
    wf["66"] = {"class_type": "ModelSamplingAuraFlow",
                "inputs": {"shift": 3, "model": [model_src, 0]}}
    wf["75"] = {"class_type": "CFGNorm", "inputs": {"strength": 1, "model": ["66", 0]}}
    wf["110"] = {"class_type": "TextEncodeQwenImageEditPlus",
                 "inputs": {"prompt": write_prompt, "clip": ["38", 0], "vae": ["39", 0],
                            "image1": ["210", 1]}}
    wf["111"] = {"class_type": "TextEncodeQwenImageEditPlus",
                 "inputs": {"prompt": neg_prompt, "clip": ["38", 0], "vae": ["39", 0],
                            "image1": ["210", 1]}}
    wf["220"] = {"class_type": "InpaintModelConditioning",
                 "inputs": {"positive": ["110", 0], "negative": ["111", 0], "vae": ["39", 0],
                            "pixels": ["210", 1], "mask": ["210", 2], "noise_mask": True}}
    wf["3"] = {"class_type": "KSampler",
               "inputs": {"seed": seed, "steps": steps, "cfg": cfg,
                          "sampler_name": "euler", "scheduler": "simple", "denoise": 1,
                          "model": ["75", 0], "positive": ["220", 0],
                          "negative": ["220", 1], "latent_image": ["220", 2]}}
    wf["8"] = {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["39", 0]}}
    wf["230"] = {"class_type": "InpaintStitchImproved",
                 "inputs": {"stitcher": ["210", 0], "inpainted_image": ["8", 0]}}
    wf["119"] = {"class_type": "SaveImage",
                 "inputs": {"filename_prefix": prefix, "images": ["230", 0]}}
    return {k: v for k, v in wf.items() if v is not None}
