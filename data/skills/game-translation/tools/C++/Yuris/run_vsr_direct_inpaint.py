from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np


VSR_ROOT = Path(__file__).resolve().parent / "video-subtitle-remover"
sys.path.insert(0, str(VSR_ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run VSR inpaint models with a fixed subtitle rectangle mask."
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=("lama", "propainter", "opencv-telea", "opencv-ns"),
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--coords",
        nargs=4,
        type=int,
        metavar=("YMIN", "YMAX", "XMIN", "XMAX"),
        default=None,
        help="Subtitle rectangle in frame coordinates.",
    )
    parser.add_argument(
        "--mask-image",
        type=Path,
        default=None,
        help="Optional full-frame mask image. White pixels are inpainted.",
    )
    parser.add_argument(
        "--crop-pad-y",
        type=int,
        default=96,
        help="Vertical context around the mask sent to the model.",
    )
    parser.add_argument(
        "--crop-pad-x",
        type=int,
        default=160,
        help="Horizontal context around the mask sent to the model.",
    )
    parser.add_argument(
        "--mask-dilate",
        type=int,
        default=8,
        help="Pixels to expand the subtitle mask before inpainting.",
    )
    parser.add_argument(
        "--feather",
        type=int,
        default=0,
        help="Optional edge feather in pixels when compositing the inpainted crop.",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=0,
        help="Limit frames for quick model tests. 0 means the full input.",
    )
    parser.add_argument(
        "--sub-video-length",
        type=int,
        default=24,
        help="ProPainter chunk length. Smaller is slower but uses less VRAM.",
    )
    parser.add_argument(
        "--fp32",
        action="store_true",
        help="Disable fp16 for ProPainter.",
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if args.coords is None and args.mask_image is None:
        raise SystemExit("Provide either --coords or --mask-image.")


def clamp_rect(coords: tuple[int, int, int, int], width: int, height: int) -> tuple[int, int, int, int]:
    ymin, ymax, xmin, xmax = coords
    ymin = max(0, min(height - 1, ymin))
    ymax = max(ymin + 1, min(height, ymax))
    xmin = max(0, min(width - 1, xmin))
    xmax = max(xmin + 1, min(width, xmax))
    return ymin, ymax, xmin, xmax


def build_mask(
    shape: tuple[int, int],
    coords: tuple[int, int, int, int],
    dilate: int,
) -> np.ndarray:
    height, width = shape
    ymin, ymax, xmin, xmax = clamp_rect(coords, width, height)
    mask = np.zeros((height, width), dtype=np.uint8)
    cv2.rectangle(mask, (xmin, ymin), (xmax, ymax), 255, thickness=-1)
    if dilate > 0:
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (dilate * 2 + 1, dilate * 2 + 1))
        mask = cv2.dilate(mask, kernel, iterations=1)
    return mask


def load_mask_image(mask_path: Path, shape: tuple[int, int], dilate: int) -> np.ndarray:
    height, width = shape
    mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
    if mask is None:
        raise RuntimeError(f"Could not read mask image: {mask_path}")
    if mask.shape[:2] != (height, width):
        mask = cv2.resize(mask, (width, height), interpolation=cv2.INTER_NEAREST)
    _, mask = cv2.threshold(mask, 1, 255, cv2.THRESH_BINARY)
    if dilate > 0:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilate * 2 + 1, dilate * 2 + 1))
        mask = cv2.dilate(mask, kernel, iterations=1)
    return mask


def read_frames(input_path: Path, max_frames: int) -> tuple[list[np.ndarray], float, tuple[int, int]]:
    cap = cv2.VideoCapture(str(input_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open input video: {input_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    frames: list[np.ndarray] = []

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frames.append(frame)
        if max_frames and len(frames) >= max_frames:
            break

    cap.release()
    if not frames:
        raise RuntimeError(f"No frames were read from: {input_path}")
    return frames, fps, (width, height)


def write_frames(output_path: Path, frames: list[np.ndarray], fps: float, size: tuple[int, int]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(output_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        size,
    )
    if not writer.isOpened():
        raise RuntimeError(f"Could not open video writer: {output_path}")
    for frame in frames:
        writer.write(frame)
    writer.release()


def expand_to_multiple(length: int, multiple: int) -> int:
    remainder = length % multiple
    if remainder == 0:
        return length
    return length + multiple - remainder


def crop_bounds(
    mask: np.ndarray,
    pad_y: int,
    pad_x: int,
    multiple: int,
) -> tuple[int, int, int, int]:
    ys, xs = np.where(mask > 0)
    if len(xs) == 0 or len(ys) == 0:
        raise RuntimeError("Mask is empty.")

    height, width = mask.shape
    ymin = max(0, int(ys.min()) - pad_y)
    ymax = min(height, int(ys.max()) + 1 + pad_y)
    xmin = max(0, int(xs.min()) - pad_x)
    xmax = min(width, int(xs.max()) + 1 + pad_x)

    target_h = min(height, expand_to_multiple(ymax - ymin, multiple))
    target_w = min(width, expand_to_multiple(xmax - xmin, multiple))
    center_y = (ymin + ymax) // 2
    center_x = (xmin + xmax) // 2

    ymin = max(0, min(height - target_h, center_y - target_h // 2))
    ymax = ymin + target_h
    xmin = max(0, min(width - target_w, center_x - target_w // 2))
    xmax = xmin + target_w
    return ymin, ymax, xmin, xmax


def paste_masked(
    frame: np.ndarray,
    patch: np.ndarray,
    mask: np.ndarray,
    bounds: tuple[int, int, int, int],
    feather: int,
) -> np.ndarray:
    ymin, ymax, xmin, xmax = bounds
    out = frame.copy()
    target = out[ymin:ymax, xmin:xmax]

    if feather <= 0:
        target[mask > 0] = patch[mask > 0]
        return out

    kernel = max(3, feather * 2 + 1)
    if kernel % 2 == 0:
        kernel += 1
    alpha = cv2.GaussianBlur(mask.astype(np.float32) / 255.0, (kernel, kernel), 0)
    alpha = np.clip(alpha, 0.0, 1.0)[:, :, None]
    blended = patch.astype(np.float32) * alpha + target.astype(np.float32) * (1.0 - alpha)
    target[:] = np.clip(blended, 0, 255).astype(np.uint8)
    return out


def run_opencv(
    frames: list[np.ndarray],
    mask: np.ndarray,
    bounds: tuple[int, int, int, int],
    mode: str,
    feather: int,
) -> list[np.ndarray]:
    flag = cv2.INPAINT_TELEA if mode == "opencv-telea" else cv2.INPAINT_NS
    ymin, ymax, xmin, xmax = bounds
    mask_crop = mask[ymin:ymax, xmin:xmax]
    out = []
    for index, frame in enumerate(frames, start=1):
        crop = frame[ymin:ymax, xmin:xmax]
        patch = cv2.inpaint(crop, mask_crop, 3, flag)
        out.append(paste_masked(frame, patch, mask_crop, bounds, feather))
        if index % 25 == 0 or index == len(frames):
            print(f"{mode}: {index}/{len(frames)} frames")
    return out


def run_lama(
    frames: list[np.ndarray],
    mask: np.ndarray,
    bounds: tuple[int, int, int, int],
    feather: int,
) -> list[np.ndarray]:
    import torch
    from backend.inpaint.lama_inpaint import LamaInpaint

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model_path = VSR_ROOT / "backend" / "models" / "big-lama" / "big-lama.pt"
    lama = LamaInpaint(device=device, model_path=str(model_path))

    ymin, ymax, xmin, xmax = bounds
    mask_crop = mask[ymin:ymax, xmin:xmax]
    out = []
    for index, frame in enumerate(frames, start=1):
        crop = frame[ymin:ymax, xmin:xmax]
        patch = lama.inpaint(crop, mask_crop)
        out.append(paste_masked(frame, patch, mask_crop, bounds, feather))
        if index % 10 == 0 or index == len(frames):
            print(f"lama: {index}/{len(frames)} frames")
    return out


def run_propainter(
    frames: list[np.ndarray],
    mask: np.ndarray,
    bounds: tuple[int, int, int, int],
    feather: int,
    sub_video_length: int,
    fp32: bool,
) -> list[np.ndarray]:
    import torch
    from backend.inpaint.propainter_inpaint import PropainterInpaint

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model_dir = VSR_ROOT / "backend" / "models" / "propainter"
    propainter = PropainterInpaint(
        device=device,
        model_dir=str(model_dir),
        sub_video_length=sub_video_length,
        use_fp16=not fp32,
    )

    ymin, ymax, xmin, xmax = bounds
    crop_frames = [frame[ymin:ymax, xmin:xmax].copy() for frame in frames]
    mask_crop = mask[ymin:ymax, xmin:xmax]
    patches = propainter.inpaint(crop_frames, mask_crop)
    return [
        paste_masked(frame, patch, mask_crop, bounds, feather)
        for frame, patch in zip(frames, patches)
    ]


def main() -> None:
    args = parse_args()
    validate_args(args)
    frames, fps, (width, height) = read_frames(args.input, args.max_frames)
    if args.mask_image is not None:
        mask = load_mask_image(args.mask_image, (height, width), args.mask_dilate)
    else:
        mask = build_mask((height, width), tuple(args.coords), args.mask_dilate)
    multiple = 8 if args.mode == "propainter" else 1
    bounds = crop_bounds(mask, args.crop_pad_y, args.crop_pad_x, multiple)

    print(f"input: {args.input}")
    print(f"frames: {len(frames)} at {fps:.3f} fps, size: {width}x{height}")
    if args.mask_image is not None:
        print(f"mask image: {args.mask_image}")
    print(f"mode: {args.mode}, crop bounds: {bounds}, mask dilate: {args.mask_dilate}")
    start = time.perf_counter()

    if args.mode.startswith("opencv"):
        out_frames = run_opencv(frames, mask, bounds, args.mode, args.feather)
    elif args.mode == "lama":
        out_frames = run_lama(frames, mask, bounds, args.feather)
    else:
        out_frames = run_propainter(
            frames,
            mask,
            bounds,
            args.feather,
            args.sub_video_length,
            args.fp32,
        )

    write_frames(args.output, out_frames, fps, (width, height))
    elapsed = time.perf_counter() - start
    print(f"wrote: {args.output}")
    print(f"elapsed: {elapsed:.1f}s")


if __name__ == "__main__":
    main()
