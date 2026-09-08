from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import cv2
import numpy as np


VIDEO = Path("converted/prolag.mp4")
ASS = Path("work/prolag_english.ass")
FFMPEG = Path("tools/ffmpeg/bin/ffmpeg.exe")
OUTPUT = Path("converted/prolag_english_inpaint.mp4")
CHECK_DIR = Path("work/prolag_inpaint_check")

X0, X1 = 120, 1160
Y0, Y1 = 585, 690

TIMINGS = [
    (1.500, 13.625),
    (13.708, 17.375),
    (17.375, 23.667),
    (24.458, 35.917),
    (39.542, 45.542),
    (45.542, 53.042),
    (54.000, 61.458),
    (61.458, 68.500),
    (68.917, 75.458),
    (75.458, 87.000),
]


def subtitle_interval_index(t: float) -> int | None:
    for index, (start, end) in enumerate(TIMINGS):
        if start <= t < end:
            return index
    return None


def in_subtitle_time(t: float) -> bool:
    return subtitle_interval_index(t) is not None


def subtitle_core_mask(frame: np.ndarray) -> np.ndarray:
    crop = frame[Y0:Y1, X0:X1]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    b, g, r = cv2.split(crop)

    white = (v > 165) & (s < 105) & (np.maximum.reduce([b, g, r]) - np.minimum.reduce([b, g, r]) < 95)
    white = white.astype(np.uint8) * 255

    num, labels, stats, _ = cv2.connectedComponentsWithStats(white, 8)
    filtered = np.zeros_like(white)
    for i in range(1, num):
        x, y, w, hgt, area = stats[i]
        if area < 5 or area > 900:
            continue
        if hgt < 4 or hgt > 34:
            continue
        if w < 2 or w > 70:
            continue
        if y < 18 or y + hgt > 98:
            continue
        filtered[labels == i] = 255

    return filtered


def subtitle_inpaint_mask(frame: np.ndarray) -> np.ndarray:
    core = subtitle_core_mask(frame)
    if int((core > 0).sum()) < 80:
        return np.zeros(frame.shape[:2], dtype=np.uint8)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (17, 11))
    grown = cv2.dilate(core, kernel, iterations=1)

    # The source subtitles have a soft shadow offset down/right; include that
    # shadow in the inpaint region without making the whole lower third blurry.
    shadow = np.zeros_like(grown)
    shadow[3:, 3:] = grown[:-3, :-3]
    shadow2 = np.zeros_like(grown)
    shadow2[5:, 0:] = grown[:-5, 0:]
    grown = cv2.bitwise_or(grown, shadow)
    grown = cv2.bitwise_or(grown, shadow2)

    full = np.zeros(frame.shape[:2], dtype=np.uint8)
    full[Y0:Y1, X0:X1] = grown
    return full


def inpaint_frame(frame: np.ndarray, t: float) -> np.ndarray:
    cleaned, _ = inpaint_frame_with_fallback(frame, t)
    return cleaned


def inpaint_frame_with_fallback(
    frame: np.ndarray,
    t: float,
    fallback_mask: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray | None]:
    if not in_subtitle_time(t):
        return frame, None
    mask = subtitle_inpaint_mask(frame)
    if subtitle_interval_index(t) == len(TIMINGS) - 1 and t >= 86.000:
        fade_mask = np.zeros(frame.shape[:2], dtype=np.uint8)
        fade_mask[Y0:Y1, X0:X1] = 255
        mask = cv2.bitwise_or(mask, fade_mask)
    if int((mask > 0).sum()) < 80:
        if fallback_mask is None:
            return frame, None
        mask = fallback_mask
    return cv2.inpaint(frame, mask, 5, cv2.INPAINT_TELEA), mask


def render_check_frames(times: list[float]) -> None:
    cap = cv2.VideoCapture(str(VIDEO))
    fps = cap.get(cv2.CAP_PROP_FPS)
    CHECK_DIR.mkdir(parents=True, exist_ok=True)
    for t in times:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t * fps)))
        ok, frame = cap.read()
        if not ok:
            continue
        cleaned = inpaint_frame(frame, t)
        mask = subtitle_inpaint_mask(frame)
        cv2.imwrite(str(CHECK_DIR / f"clean_{t:05.2f}.png"), cleaned)
        cv2.imwrite(str(CHECK_DIR / f"mask_{t:05.2f}.png"), mask)


def render_video() -> None:
    cap = cv2.VideoCapture(str(VIDEO))
    if not cap.isOpened():
        raise SystemExit(f"Could not open {VIDEO}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

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
        "-vf",
        f"subtitles='{ASS.as_posix()}'",
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
        str(OUTPUT),
    ]

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    assert proc.stdin is not None
    frame_idx = 0
    last_interval: int | None = None
    fallback_mask: np.ndarray | None = None
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            t = frame_idx / fps
            interval = subtitle_interval_index(t)
            if interval != last_interval:
                fallback_mask = None
                last_interval = interval
            cleaned, fallback_mask = inpaint_frame_with_fallback(frame, t, fallback_mask)
            proc.stdin.write(cleaned.tobytes())
            frame_idx += 1
            if frame_idx % 240 == 0:
                print(f"processed {frame_idx}/{frames} frames")
    finally:
        proc.stdin.close()
        code = proc.wait()
    if code != 0:
        raise SystemExit(code)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        render_check_frames([5.0, 16.5, 19.0, 31.5, 40.8, 46.0, 61.5, 64.4, 69.0, 77.8, 85.5])
    else:
        render_video()


if __name__ == "__main__":
    main()
