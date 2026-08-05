"""RapidOCR (ONNX) - the offline fallback.

Lens is better and needs no install, but it talks to an unofficial endpoint
that can rate-limit or disappear. RapidOCR runs locally on onnxruntime, is
about 15 MB, and needs no torch. It is weaker on decorative game type, which is
acceptable for a fallback: the user confirms every reading anyway.

It returns lines only, so paragraphs are grouped here using the same
leading/overlap/type-size rules the old detector used.
"""

from __future__ import annotations

import numpy as np

from util.imagetools.geometry import Box
from util.imagetools.ocr import (
    Block,
    Line,
    OcrUnavailable,
    Reading,
    probe_import,
    register,
    worth_keeping,
)

NAME = "rapidocr"


def _load():
    """Return a callable engine, tolerating both package generations."""
    try:
        from rapidocr_onnxruntime import RapidOCR
    except Exception:
        try:
            from rapidocr import RapidOCR
        except Exception as exc:
            raise OcrUnavailable(
                "RapidOCR is not installed - pip install rapidocr-onnxruntime"
            ) from exc
    return RapidOCR()


INSTALL_HINT = "pip install rapidocr-onnxruntime"


class RapidEngine:
    name = NAME

    def _probe(self) -> tuple[bool, str]:
        ok, detail = probe_import("rapidocr_onnxruntime", INSTALL_HINT)
        if ok:
            return True, detail
        newer, newer_detail = probe_import("rapidocr", INSTALL_HINT)
        return (True, newer_detail) if newer else (False, detail)

    def available(self) -> bool:
        return self._probe()[0]

    def status(self) -> str:
        ok, detail = self._probe()
        if ok:
            return f"{NAME}: ready (offline, onnxruntime)"
        return f"{NAME}: {detail}"

    def read(self, array: np.ndarray) -> Reading:
        engine = _load()
        rgb = array[:, :, :3] if array.ndim == 3 else array
        try:
            raw = engine(np.ascontiguousarray(rgb))
        except Exception as exc:
            raise OcrUnavailable(f"RapidOCR failed: {exc}") from exc
        # Older builds return (result, elapsed); newer ones an object with .txts.
        result = raw[0] if isinstance(raw, tuple) else getattr(raw, "boxes", raw)
        lines = []
        for entry in result or []:
            try:
                points, text = entry[0], str(entry[1])
            except Exception:
                continue
            xs = [float(p[0]) for p in points]
            ys = [float(p[1]) for p in points]
            box = Box(int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)))
            if worth_keeping(text, box):
                lines.append(Line(text, box, 0.0))
        reading = Reading(engine=NAME)
        reading.blocks = group_lines(lines)
        return reading


def group_lines(lines: list[Line]) -> list[Block]:
    """Merge stacked lines into paragraphs.

    Three conditions, all of which a real paragraph satisfies and a heading
    followed by body text does not: the gap is no wider than a line, the lines
    share a margin or overlap substantially, and they are the same type size.
    """
    ordered = sorted(lines, key=lambda line: (line.box.y, line.box.x))
    blocks: list[list[Line]] = []
    for line in ordered:
        if blocks and _joins(blocks[-1], line):
            blocks[-1].append(line)
        else:
            blocks.append([line])
    return [_block(group) for group in blocks]


def _joins(group: list[Line], line: Line) -> bool:
    last = group[-1].box
    box = line.box
    if box.y < last.y:
        return False
    gap = box.y - last.y2
    if gap > max(6, min(last.h, box.h)):
        return False

    overlap = min(last.x2, box.x2) - max(last.x, box.x)
    shared_margin = abs(last.x - box.x) <= max(3, last.h // 2)
    if overlap < 0.5 * min(last.w, box.w) and not shared_margin:
        return False

    median = sorted(item.box.h for item in group)[len(group) // 2]
    if median and max(box.h, median) / max(1, min(box.h, median)) > 1.45:
        return False
    return True


def _block(group: list[Line]) -> Block:
    box = group[0].box
    for line in group[1:]:
        box = box.union(line.box)
    return Block("\n".join(line.text for line in group), box, 0.0, list(group))


register(NAME, RapidEngine)
