from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import torch

from render_prolag_inpaint import FFMPEG, VIDEO, subtitle_inpaint_mask


VSR_ROOT = Path("tools/video-subtitle-remover").resolve()
sys.path.insert(0, str(VSR_ROOT))

from backend.inpaint.lama_inpaint import LamaInpaint  # noqa: E402


def crop_bounds(mask: np.ndarray, pad_y: int, pad_x: int) -> tuple[int, int, int, int]:
    ys, xs = np.where(mask > 0)
    if len(xs) == 0 or len(ys) == 0:
        raise ValueError("empty mask")

    height, width = mask.shape
    ymin = max(0, int(ys.min()) - pad_y)
    ymax = min(height, int(ys.max()) + 1 + pad_y)
    xmin = max(0, int(xs.min()) - pad_x)
    xmax = min(width, int(xs.max()) + 1 + pad_x)
    return ymin, ymax, xmin, xmax


def inpaint_with_lama(
    lama: LamaInpaint,
    frame: np.ndarray,
    mask: np.ndarray,
    pad_y: int,
    pad_x: int,
) -> np.ndarray:
    if int((mask > 0).sum()) < 80:
        return frame

    ymin, ymax, xmin, xmax = crop_bounds(mask, pad_y, pad_x)
    crop = frame[ymin:ymax, xmin:xmax]
    mask_crop = mask[ymin:ymax, xmin:xmax]
    patch = lama.inpaint(crop, mask_crop)

    out = frame.copy()
    target = out[ymin:ymax, xmin:xmax]
    target[mask_crop > 0] = patch[mask_crop > 0]
    return out


def grow_mask(mask: np.ndarray, pixels: int) -> np.ndarray:
    if pixels <= 0:
        return mask
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (pixels * 2 + 1, pixels * 2 + 1))
    return cv2.dilate(mask, kernel, iterations=1)


def render(duration: float, output: Path, pad_y: int, pad_x: int, extra_dilate: int) -> None:
    cap = cv2.VideoCapture(str(VIDEO))
    if not cap.isOpened():
        raise SystemExit(f"Could not open {VIDEO}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = min(int(round(duration * fps)), int(cap.get(cv2.CAP_PROP_FRAME_COUNT)))

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model_path = VSR_ROOT / "backend" / "models" / "big-lama" / "big-lama.pt"
    lama = LamaInpaint(device=device, model_path=str(model_path))

    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(FFMPEG),
        "-hide_banner",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "bgr24",
        "-s:v",
        f"{width}x{height}",
        "-r",
        f"{fps:.6f}",
        "-i",
        "-",
        "-i",
        str(VIDEO),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-t",
        f"{duration:.3f}",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        str(output),
    ]

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    assert proc.stdin is not None

    frame_idx = 0
    masked_frames = 0
    try:
        while frame_idx < total_frames:
            ok, frame = cap.read()
            if not ok:
                break
            mask = grow_mask(subtitle_inpaint_mask(frame), extra_dilate)
            if int((mask > 0).sum()) >= 80:
                frame = inpaint_with_lama(lama, frame, mask, pad_y, pad_x)
                masked_frames += 1
            proc.stdin.write(frame.tobytes())
            frame_idx += 1
            if frame_idx % 60 == 0 or frame_idx == total_frames:
                print(f"processed {frame_idx}/{total_frames} frames; masked {masked_frames}")
    finally:
        cap.release()
        proc.stdin.close()
        code = proc.wait()

    if code != 0:
        raise SystemExit(code)
    print(f"wrote {output}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=15.0)
    parser.add_argument("--output", type=Path, default=Path("work/prolag_lama_glyph_first15_clean.mp4"))
    parser.add_argument("--pad-y", type=int, default=64)
    parser.add_argument("--pad-x", type=int, default=96)
    parser.add_argument("--extra-dilate", type=int, default=0)
    args = parser.parse_args()
    render(args.duration, args.output, args.pad_y, args.pad_x, args.extra_dilate)


if __name__ == "__main__":
    main()
