from __future__ import annotations

import argparse
import subprocess
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


FFMPEG = Path("tools/ffmpeg/bin/ffmpeg.exe")
X0, X1 = 120, 1160
Y0, Y1 = 585, 690


@dataclass(frozen=True)
class ScenePlate:
    start: float
    end: float
    base_time: float


@dataclass(frozen=True)
class MovieConfig:
    video: Path
    ass: Path
    output: Path
    check_dir: Path
    plates: tuple[ScenePlate, ...]
    check_times: tuple[float, ...]


CONFIGS = {
    "prolag": MovieConfig(
        video=Path("converted/prolag.mp4"),
        ass=Path("work/prolag_english.ass"),
        output=Path("converted/prolag_english_cleanplate.mp4"),
        check_dir=Path("work/prolag_cleanplate_check"),
        plates=(
            ScenePlate(1.500, 13.625, 1.400),
            ScenePlate(13.708, 23.667, 13.500),
            ScenePlate(24.458, 35.917, 24.400),
            ScenePlate(39.542, 53.042, 38.000),
            ScenePlate(54.000, 68.500, 53.500),
            ScenePlate(68.917, 75.458, 68.850),
        ),
        check_times=(5.0, 16.5, 19.0, 31.5, 40.8, 46.0, 61.5, 69.0, 77.8),
    ),
    "epilag": MovieConfig(
        video=Path("converted/epilag.mp4"),
        ass=Path("work/epilag_english.ass"),
        output=Path("converted/epilag_english_cleanplate.mp4"),
        check_dir=Path("work/epilag_cleanplate_check"),
        plates=(
            ScenePlate(1.583, 18.417, 1.500),
            ScenePlate(19.542, 37.833, 19.000),
            ScenePlate(37.833, 49.167, 19.000),
        ),
        check_times=(4.4, 17.9, 20.0, 30.6, 31.1, 38.0, 40.0, 47.0),
    ),
}


class CleanPlateRenderer:
    def __init__(self, config: MovieConfig) -> None:
        self.config = config
        self.cap = cv2.VideoCapture(str(config.video))
        if not self.cap.isOpened():
            raise SystemExit(f"Could not open {config.video}")
        self.fps = self.cap.get(cv2.CAP_PROP_FPS)
        self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.base_frames: dict[float, np.ndarray] = {}
        self.base_grays: dict[float, np.ndarray] = {}

    def frame_at(self, time_s: float) -> np.ndarray:
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(time_s * self.fps)))
        ok, frame = self.cap.read()
        if not ok:
            raise RuntimeError(f"Could not read frame at {time_s:.3f}s")
        return frame

    def get_plate(self, time_s: float) -> ScenePlate | None:
        for plate in self.config.plates:
            if plate.start <= time_s < plate.end:
                return plate
        return None

    def get_base_frame(self, base_time: float) -> np.ndarray:
        if base_time not in self.base_frames:
            frame = self.frame_at(base_time)
            self.base_frames[base_time] = frame
            self.base_grays[base_time] = self.small_gray(frame)
        return self.base_frames[base_time]

    @staticmethod
    def small_gray(frame: np.ndarray) -> np.ndarray:
        small = cv2.resize(frame, (640, 360), interpolation=cv2.INTER_AREA)
        return cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0

    def subtitle_core_mask(self, frame: np.ndarray) -> np.ndarray:
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

    def subtitle_patch_mask(self, frame: np.ndarray) -> np.ndarray:
        core = self.subtitle_core_mask(frame)
        if int((core > 0).sum()) < 80:
            return np.zeros(frame.shape[:2], dtype=np.uint8)

        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (45, 25))
        grown = cv2.dilate(core, kernel, iterations=1)
        shadow = np.zeros_like(grown)
        shadow[10:, 8:] = grown[:-10, :-8]
        grown = cv2.bitwise_or(grown, shadow)

        full = np.zeros(frame.shape[:2], dtype=np.uint8)
        full[Y0:Y1, X0:X1] = grown
        return full

    def align_base(self, base_time: float, frame: np.ndarray) -> np.ndarray:
        base = self.get_base_frame(base_time)
        base_gray = self.base_grays[base_time]
        target_gray = self.small_gray(frame)

        align_mask = np.zeros(base_gray.shape, dtype=np.uint8)
        align_mask[15:288, 18:622] = 1

        warp = np.eye(2, 3, dtype=np.float32)
        criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 80, 1e-5)
        try:
            _, warp = cv2.findTransformECC(
                base_gray,
                target_gray,
                warp,
                cv2.MOTION_TRANSLATION,
                criteria,
                inputMask=align_mask,
                gaussFiltSize=5,
            )
            warp[0, 2] *= self.width / 640
            warp[1, 2] *= self.height / 360
        except cv2.error:
            warp = np.eye(2, 3, dtype=np.float32)

        return cv2.warpAffine(
            base,
            warp,
            (self.width, self.height),
            flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP,
            borderMode=cv2.BORDER_REPLICATE,
        )

    @staticmethod
    def match_color(source: np.ndarray, target: np.ndarray, mask: np.ndarray) -> np.ndarray:
        context = np.zeros(mask.shape, dtype=np.uint8)
        context[max(0, Y0 - 35) : min(mask.shape[0], Y1 + 20), X0:X1] = 255
        context[mask > 0] = 0
        coords = context > 0
        if int(coords.sum()) < 1000:
            return source

        out = source.astype(np.float32)
        src = source[coords].astype(np.float32)
        dst = target[coords].astype(np.float32)
        for channel in range(3):
            src_mean, src_std = float(src[:, channel].mean()), float(src[:, channel].std())
            dst_mean, dst_std = float(dst[:, channel].mean()), float(dst[:, channel].std())
            if src_std > 1.0:
                out[..., channel] = (out[..., channel] - src_mean) * (dst_std / src_std) + dst_mean
            else:
                out[..., channel] = out[..., channel] + (dst_mean - src_mean)
        return np.clip(out, 0, 255).astype(np.uint8)

    def clean_frame(self, frame: np.ndarray, time_s: float) -> np.ndarray:
        mask = self.subtitle_patch_mask(frame)
        if int((mask > 0).sum()) < 80:
            return frame

        plate = self.get_plate(time_s)
        if plate is None:
            return cv2.inpaint(frame, mask, 5, cv2.INPAINT_TELEA)

        aligned = self.align_base(plate.base_time, frame)
        aligned = self.match_color(aligned, frame, mask)
        alpha = cv2.GaussianBlur(mask.astype(np.float32) / 255.0, (0, 0), 2.0)[..., None]
        return (frame.astype(np.float32) * (1.0 - alpha) + aligned.astype(np.float32) * alpha).astype(np.uint8)

    def render_check_frames(self) -> None:
        self.config.check_dir.mkdir(parents=True, exist_ok=True)
        for time_s in self.config.check_times:
            frame = self.frame_at(time_s)
            clean = self.clean_frame(frame, time_s)
            cv2.imwrite(str(self.config.check_dir / f"cleanplate_{time_s:05.2f}.png"), clean)

    def render_video(self) -> None:
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cmd = [
            str(FFMPEG),
            "-hide_banner",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-s:v",
            f"{self.width}x{self.height}",
            "-r",
            f"{self.fps:.6f}",
            "-i",
            "-",
            "-i",
            str(self.config.video),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-vf",
            f"subtitles='{self.config.ass.as_posix()}'",
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
            str(self.config.output),
        ]

        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        assert proc.stdin is not None
        frame_idx = 0
        try:
            while True:
                ok, frame = self.cap.read()
                if not ok:
                    break
                time_s = frame_idx / self.fps
                cleaned = self.clean_frame(frame, time_s)
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
    parser.add_argument("movie", choices=CONFIGS.keys())
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    renderer = CleanPlateRenderer(CONFIGS[args.movie])
    if args.check:
        renderer.render_check_frames()
    else:
        renderer.render_video()


if __name__ == "__main__":
    main()
