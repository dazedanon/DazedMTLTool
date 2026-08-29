#!/usr/bin/env python3
"""Expose DazedTL's local inpainting backends to image-translation helpers."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _print(payload: dict, *, stream=None) -> None:
    print(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        file=stream or sys.stdout,
    )


def _runtime():
    try:
        import numpy as np
        from PIL import Image

        from util.imagetools import inpaint
    except (ImportError, ModuleNotFoundError) as exc:
        raise RuntimeError(
            "The image editor resources are unavailable in this Python "
            f"({sys.executable}): {exc}. Open Edit text in DazedTL and accept "
            "the resource download before using the local inpainting bridge."
        ) from exc
    return np, Image, inpaint


def _status() -> dict:
    _np, _image, inpaint = _runtime()
    methods = []
    for method in inpaint.METHODS:
        methods.append(
            {
                "available": inpaint.available(method),
                "label": inpaint.METHOD_LABELS[method],
                "name": method,
                "status": inpaint.status(method),
            }
        )
    return {
        "ok": True,
        "python": sys.executable,
        "methods": methods,
    }


def _load_inputs(image_path: Path, mask_path: Path):
    np, Image, inpaint = _runtime()
    if not image_path.is_file():
        raise ValueError(f"Input image does not exist: {image_path}")
    if not mask_path.is_file():
        raise ValueError(f"Mask image does not exist: {mask_path}")

    with Image.open(image_path) as source:
        if source.format != "PNG":
            raise ValueError(f"Input must be a PNG, not {source.format or 'unknown'}")
        if source.mode not in ("RGB", "RGBA"):
            raise ValueError(
                f"Input must be an 8-bit RGB or RGBA PNG, not mode {source.mode}"
            )
        source_mode = source.mode
        rgba = np.asarray(source.convert("RGBA"), dtype=np.uint8).copy()

    with Image.open(mask_path) as source_mask:
        if source_mask.size != (rgba.shape[1], rgba.shape[0]):
            raise ValueError(
                "Mask dimensions must exactly match the input image: "
                f"{source_mask.size} != {(rgba.shape[1], rgba.shape[0])}"
            )
        mask = np.asarray(source_mask.convert("L"), dtype=np.uint8) > 0
    if not mask.any():
        raise ValueError("Mask contains no nonzero pixels")
    return np, Image, inpaint, rgba, mask, source_mode


def _context_window(rgba, mask, method: str, inpaint, np) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(mask)
    x = int(xs.min())
    y = int(ys.min())
    x2 = int(xs.max()) + 1
    y2 = int(ys.max()) + 1
    tight_mask = mask[y:y2, x:x2]
    tight_alpha = rgba[y:y2, x:x2, 3]
    crowded = float((tight_mask | (tight_alpha == 0)).mean()) > inpaint.CROWDED
    if inpaint.needs_context(method):
        share = inpaint.CONTEXT
    elif crowded:
        share = inpaint.CROWDED_CONTEXT
    else:
        share = 0.0
    pad = int(max(x2 - x, y2 - y) * share)
    return (
        max(0, x - pad),
        max(0, y - pad),
        min(rgba.shape[1], x2 + pad),
        min(rgba.shape[0], y2 + pad),
    )


def _save_png(Image, pixels, mode: str, output: Path, *, replace: bool) -> None:
    if output.exists() and not replace:
        raise ValueError(f"Output already exists (pass --replace to overwrite it): {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.stem}.", suffix=".png", dir=output.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        rendered = Image.fromarray(pixels, mode="RGBA")
        if mode == "RGB":
            rendered = rendered.convert("RGB")
        rendered.save(temporary, format="PNG")
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def _fill(args) -> dict:
    np, Image, inpaint, rgba, mask, source_mode = _load_inputs(args.image, args.mask)
    if args.method not in inpaint.METHODS:
        raise ValueError(
            f"Unknown method {args.method!r}; choose from {', '.join(inpaint.METHODS)}"
        )
    if args.output.resolve() in (args.image.resolve(), args.mask.resolve()):
        raise ValueError("Output must not overwrite the input image or mask")

    x, y, x2, y2 = _context_window(rgba, mask, args.method, inpaint, np)
    candidate = rgba.copy()
    view = candidate[y:y2, x:x2].copy()
    hole = mask[y:y2, x:x2]
    repaired, complaint, changed = inpaint.reconstruct_rgba(
        view, hole, args.method, allow_fallback=False
    )
    if complaint:
        raise inpaint.InpaintError(complaint)
    if not changed:
        raise RuntimeError(
            "The requested backend changed no masked pixels; no candidate was written"
        )
    candidate[y:y2, x:x2] = repaired
    if not np.array_equal(candidate[~mask], rgba[~mask]):
        raise RuntimeError("Reconstruction changed pixels outside the supplied mask")

    _save_png(Image, candidate, source_mode, args.output, replace=args.replace)
    return {
        "changed_mask_pixels": changed,
        "context_xywh": [x, y, x2 - x, y2 - y],
        "mask_pixels": int(mask.sum()),
        "method": args.method,
        "mode": source_mode,
        "ok": True,
        "output": str(args.output.resolve()),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="Report installed and loadable backends as JSON")

    fill = commands.add_parser(
        "fill", help="Reconstruct exactly the nonzero pixels in a full-size mask"
    )
    fill.add_argument("--image", required=True, type=Path, help="Source RGB/RGBA PNG")
    fill.add_argument("--mask", required=True, type=Path, help="Same-size mask PNG")
    fill.add_argument("--output", required=True, type=Path, help="Candidate PNG path")
    fill.add_argument("--method", required=True, help="Backend name reported by status")
    fill.add_argument(
        "--replace", action="store_true", help="Replace an existing candidate output"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        payload = _status() if args.command == "status" else _fill(args)
    except Exception as exc:
        _print(
            {"error": f"{type(exc).__name__}: {exc}", "ok": False},
            stream=sys.stderr,
        )
        return 2
    _print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
