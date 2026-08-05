"""Google Lens, via ``chrome-lens-py``.

Measured against ``mistral-ocr-latest`` on nine hand-transcribed regions from
the two images that had failed every previous attempt:

    mistral-ocr 1x crop   59.0%   2/9 exact
    mistral-ocr 2x crop   92.6%   5/9 exact
    Lens        1x        98.3%   6/9 exact
    Lens        2x        99.3%   7/9 exact

and, run on a whole image rather than a crop, it found 12/12 lines on the
hardest one with pixel-tight boxes, no misses and no false positives. It is
also the only engine here that reports rotation, which is what makes the
vertical UI strips work.

It is an *unofficial* endpoint using the API key Chromium embeds, so it needs
no account - and can rate-limit or break without notice. That is precisely why
``ocr`` is a registry rather than a single import.
"""

from __future__ import annotations

import asyncio
import os

import numpy as np
from PIL import Image

from util.imagetools.geometry import Box
from util.imagetools.ocr import (
    Block,
    Line,
    OcrUnavailable,
    Reading,
    Word,
    probe_import,
    register,
    rotated_box,
    worth_keeping,
)

NAME = "lens"

# chrome-lens-py thumbnails anything larger before it goes out, so there is no
# point sending more than this - but there IS a point filling it: a 324x80
# strip has room to go up 4x, and small type reads better with the pixels.
MAX_DIMENSION = 1500


def _language() -> str | None:
    value = os.getenv("IMGTL_OCR_LANG", "ja").strip()
    return value or None


def _flatten(array: np.ndarray) -> Image.Image:
    """RGBA/BGRA ndarray -> an opaque RGB image on white.

    Transparent game assets are the norm, and what sits behind alpha=0 is
    undefined garbage. Compositing onto white first is what stopped the
    transparent test images reading as blank.
    """
    if array.ndim == 2:
        return Image.fromarray(array).convert("RGB")
    if array.shape[2] == 3:
        return Image.fromarray(array[:, :, :3]).convert("RGB")
    rgb = array[:, :, :3].astype(np.float32)
    alpha = (array[:, :, 3].astype(np.float32) / 255.0)[:, :, None]
    flat = rgb * alpha + 255.0 * (1.0 - alpha)
    return Image.fromarray(flat.astype(np.uint8), mode="RGB")


def _upscale(image: Image.Image) -> Image.Image:
    """Fill the endpoint's size budget with an integer factor.

    Integer only: fractional Lanczos resamples measurably hurt OCR - 2.5x and
    1.8x scored *worse than 1x* on the Mistral runs, one of them collapsing
    into a repetition loop.
    """
    longest = max(image.width, image.height)
    if longest <= 0:
        return image
    factor = int(MAX_DIMENSION // longest)
    if factor < 2:
        return image
    return image.resize((image.width * factor, image.height * factor), Image.LANCZOS)


INSTALL_HINT = "pip install chrome-lens-py"


class LensEngine:
    name = NAME

    def available(self) -> bool:
        return probe_import("chrome_lens_py", INSTALL_HINT)[0]

    def status(self) -> str:
        ok, detail = probe_import("chrome_lens_py", INSTALL_HINT)
        if ok:
            return f"{NAME}: ready (Google Lens, no API key required)"
        return f"{NAME}: {detail}"

    def read(self, array: np.ndarray) -> Reading:
        if not self.available():
            raise OcrUnavailable(self.status())
        height, width = array.shape[:2]
        image = _upscale(_flatten(array))
        payload = _run(image)
        return _convert(payload, width, height)


def _run(image: Image.Image) -> dict:
    from chrome_lens_py import LensAPI

    async def go() -> dict:
        api = LensAPI(max_concurrent=1)
        # A PIL image is accepted directly - no temp file, which also sidesteps
        # the non-ASCII path handling that bites on Windows.
        return await api.process_image(
            image, ocr_language=_language(), output_format="blocks"
        )

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        raise OcrUnavailable(
            "Lens OCR cannot run inside a running event loop; call it from a worker thread."
        )
    try:
        return asyncio.run(go())
    except Exception as exc:
        raise OcrUnavailable(f"Google Lens request failed: {exc}") from exc


def _geometry(geometry: dict, width: int, height: int) -> tuple[Box, float]:
    """Normalized centre-rotated box -> pixel bounds.

    Each axis is normalized by its own image dimension (verified by drawing
    both candidate readings over the vertical asset and looking at them). The
    coordinates are relative to whatever was sent, so an upscale needs no
    correction here - normalized is resolution independent.
    """
    angle = float(geometry.get("angle_deg") or 0.0)
    box = rotated_box(
        float(geometry.get("center_x") or 0.0) * width,
        float(geometry.get("center_y") or 0.0) * height,
        float(geometry.get("width") or 0.0) * width,
        float(geometry.get("height") or 0.0) * height,
        angle,
    )
    return box.clamp(Box.from_size(width, height)), angle


def _convert(payload: dict, width: int, height: int) -> Reading:
    reading = Reading(engine=NAME)
    bounds = Box.from_size(width, height)

    for item in payload.get("word_data") or []:
        geometry = item.get("geometry") or {}
        box, angle = _geometry(geometry, width, height)
        word = str(item.get("word") or "")
        if word.strip() and box.area > 0:
            reading.words.append(Word(word, box.clamp(bounds), angle))

    for item in payload.get("text_blocks") or []:
        text = str(item.get("text") or "")
        box, angle = _geometry(item.get("geometry") or {}, width, height)
        if not worth_keeping(text, box):
            continue
        # The 'blocks' format gives each line's *text* but no geometry for it.
        # The words have geometry, so recover the lines by clustering the words
        # that fall inside this block - real measured boxes rather than an even
        # division of the block, which matters because a split has to land on
        # the actual glyphs.
        parts = [part for part in text.splitlines() if part.strip()]
        lines = _lines_from_words(parts, box, angle, reading.words)
        if not lines:
            lines = _estimate_lines(parts, box, angle) if len(parts) > 1 else [
                Line(text, box, angle)
            ]
        reading.blocks.append(Block(text, box, angle, lines))

    return reading


def _lines_from_words(
    parts: list[str], box: Box, angle: float, words: list[Word]
) -> list[Line]:
    """Rebuild line boxes by grouping this block's words into rows.

    Returns ``[]`` unless the number of clusters matches the number of text
    lines the engine reported - a mismatch means the clustering disagreed with
    the engine, and a wrong pairing would put text on the wrong box.
    """
    if not parts:
        return []
    inside = [
        word for word in words
        if box.x <= (word.box.x + word.box.x2) // 2 <= box.x2
        and box.y <= (word.box.y + word.box.y2) // 2 <= box.y2
    ]
    if not inside:
        return []
    if len(parts) == 1:
        return [Line(parts[0], box, angle)]

    vertical = abs(abs(angle) - 90.0) < 30.0
    # Lines stack across the text direction: down the page for horizontal text,
    # right to left for a quarter-turned strip.
    def key(word: Word) -> float:
        return (word.box.x + word.box.x2) / 2.0 if vertical else (word.box.y + word.box.y2) / 2.0

    ordered = sorted(inside, key=key)
    thickness = sorted(word.box.w if vertical else word.box.h for word in ordered)
    typical = max(1.0, float(thickness[len(thickness) // 2]))

    clusters: list[list[Word]] = [[ordered[0]]]
    for word in ordered[1:]:
        if key(word) - key(clusters[-1][-1]) > typical * 0.6:
            clusters.append([word])
        else:
            clusters[-1].append(word)
    if len(clusters) != len(parts):
        return []
    if vertical:
        clusters.reverse()          # right-to-left reading order

    lines = []
    for part, cluster in zip(parts, clusters):
        line_box = cluster[0].box
        for word in cluster[1:]:
            line_box = line_box.union(word.box)
        lines.append(Line(part, line_box, angle))
    return lines


def _estimate_lines(parts: list[str], box: Box, angle: float) -> list[Line]:
    """Even split of a block's box across its text lines.

    A fallback only, for when the engine gave block text but no per-line
    geometry. Good enough to drive a split, and the split is re-measured from
    pixels afterwards.
    """
    count = len(parts)
    vertical = abs(abs(angle) - 90.0) < 30.0
    lines = []
    for index, part in enumerate(parts):
        if vertical:
            step = box.w / count
            # Rotated a quarter turn, successive lines advance right to left.
            left = box.x2 - step * (index + 1)
            lines.append(Line(part, Box(int(left), box.y, int(left + step), box.y2), angle))
        else:
            step = box.h / count
            top = box.y + step * index
            lines.append(Line(part, Box(box.x, int(top), box.x2, int(top + step)), angle))
    return lines


register(NAME, LensEngine)
