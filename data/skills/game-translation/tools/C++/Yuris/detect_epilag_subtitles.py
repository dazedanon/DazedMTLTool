from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


VIDEO = Path("converted/epilag.mp4")
OUT_JSON = Path("work/epilag_detected_segments.json")
OUT_SHEET = Path("work/epilag_detected_segments.png")

X0, X1 = 120, 1160
Y0, Y1 = 585, 690


@dataclass
class Segment:
    start_frame: int
    end_frame: int
    key_frame: int
    area: int


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


def feature(mask: np.ndarray) -> np.ndarray:
    small = cv2.resize(mask, (208, 21), interpolation=cv2.INTER_AREA)
    return (small > 25).astype(np.uint8)


def changed(prev: np.ndarray | None, cur: np.ndarray) -> float:
    if prev is None:
        return 1.0
    denom = max(int(prev.sum()), int(cur.sum()), 1)
    return float(np.bitwise_xor(prev, cur).sum()) / float(denom)


def fmt_time(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def main() -> None:
    cap = cv2.VideoCapture(str(VIDEO))
    if not cap.isOpened():
        raise SystemExit(f"Could not open {VIDEO}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    min_gap = int(round(fps * 0.7))

    segments: list[Segment] = []
    active: Segment | None = None
    prev_feat: np.ndarray | None = None
    last_change = -10_000

    for frame_idx in range(frame_count):
        ok, frame = cap.read()
        if not ok:
            break

        mask = subtitle_core_mask(frame)
        area = int((mask > 0).sum())
        has_text = area > 120
        cur_feat = feature(mask) if has_text else None

        if has_text and active is None:
            active = Segment(frame_idx, frame_idx, frame_idx, area)
            prev_feat = cur_feat
            last_change = frame_idx
            continue

        if active is not None and not has_text:
            active.end_frame = frame_idx - 1
            segments.append(active)
            active = None
            prev_feat = None
            continue

        if active is not None and has_text and cur_feat is not None:
            diff = changed(prev_feat, cur_feat)
            if diff > 0.34 and frame_idx - last_change >= min_gap:
                active.end_frame = frame_idx - 1
                segments.append(active)
                active = Segment(frame_idx, frame_idx, frame_idx, area)
                last_change = frame_idx
            else:
                active.end_frame = frame_idx
                if area > active.area:
                    active.key_frame = frame_idx
                    active.area = area
            prev_feat = cur_feat

    if active is not None:
        segments.append(active)

    merged: list[Segment] = []
    for seg in segments:
        duration = (seg.end_frame - seg.start_frame + 1) / fps
        if merged and duration < 0.4:
            merged[-1].end_frame = seg.end_frame
            continue
        merged.append(seg)

    data = []
    for idx, seg in enumerate(merged, 1):
        start = seg.start_frame / fps
        end = (seg.end_frame + 1) / fps
        data.append(
            {
                "index": idx,
                "start_frame": seg.start_frame,
                "end_frame": seg.end_frame,
                "start": start,
                "end": end,
                "start_srt": fmt_time(start),
                "end_srt": fmt_time(end),
                "area": seg.area,
            }
        )

    OUT_JSON.write_text(json.dumps(data, indent=2), encoding="utf-8")

    thumbs = []
    for seg in merged:
        cap.set(cv2.CAP_PROP_POS_FRAMES, seg.key_frame)
        ok, frame = cap.read()
        if not ok:
            continue
        crop = frame[560:710, 0:1280].copy()
        cv2.putText(
            crop,
            f"{seg.key_frame / fps:05.2f}s",
            (18, 34),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            (0, 255, 255),
            2,
            cv2.LINE_AA,
        )
        thumbs.append(crop)

    if thumbs:
        OUT_SHEET.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(OUT_SHEET), np.vstack(thumbs))

    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
