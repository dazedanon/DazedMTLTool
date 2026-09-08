from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import cv2
import numpy as np


VIDEO = Path("converted/epilag.mp4")
ASS = Path("work/epilag_english.ass")
FFMPEG = Path("tools/ffmpeg/bin/ffmpeg.exe")
OUTPUT = Path("converted/epilag_english_inpaint.mp4")
CHECK_DIR = Path("work/epilag_inpaint_check")

X0, X1 = 120, 1160
Y0, Y1 = 585, 690

TIMINGS = [
    (1.583, 9.917),
    (9.917, 18.417),
    (19.542, 30.750),
    (30.750, 37.833),
    (37.833, 49.167),
]


def in_subtitle_time(t: float) -> bool:
    return any(start <= t < end for start, end in TIMINGS)


def subtitle_core_mask(frame: np.ndarray) -> np.ndarray:
    crop = frame[Y0:Y1, X0:X1]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    _, s, v = cv2.split(hsv)
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
    if not in_subtitle_time(t):
        return frame
    mask = subtitle_inpaint_mask(frame)
    if int((mask > 0).sum()) < 80:
        return frame
    return cv2.inpaint(frame, mask, 5, cv2.INPAINT_TELEA)


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
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            t = frame_idx / fps
            cleaned = inpaint_frame(frame, t)
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
        render_check_frames([4.4, 17.9, 20.0, 30.6, 31.1, 38.0, 40.0, 47.0])
    else:
        render_video()


if __name__ == "__main__":
    main()
