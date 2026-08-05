"""Pluggable OCR backends.

An engine takes an image and returns the text it can find, already grouped:
paragraph *blocks*, the *lines* inside them, and the individual *words*. All
three levels come from one reading because each is needed somewhere:

  * blocks   - the unit that gets translated, so a paragraph reads as a
               paragraph instead of line by line
  * lines    - what a block splits back into when the grouping is wrong
  * words    - a glyph-tight erase mask, instead of blanking the whole box and
               taking the artwork with it

Engines are registered by name and resolved lazily, because the good one
(Google Lens) talks to an unofficial endpoint that can rate-limit or break, and
the fallback (RapidOCR) is an optional dependency that may not be installed.
Neither may be assumed present: ``available()`` answers without raising and
``engine_status()`` explains why not.

No PyQt in here. This runs on a worker thread and in tests.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Iterable, Iterator, Protocol

import numpy as np

from util.imagetools.geometry import Box

# Text smaller than this is below the size anything can render legibly, and is
# almost always a detector artefact - a stray mark, a panel edge, an icon's
# highlight. Lens returns a 14x2 block containing "-" on one of the test images.
MIN_SPAN = 8
MIN_THICKNESS = 5


class OcrUnavailable(RuntimeError):
    """The engine cannot run - not installed, no network, endpoint refused."""


def probe_import(module: str, install_hint: str) -> tuple[bool, str]:
    """``(importable, explanation)`` for an optional dependency.

    Reports the *actual* failure rather than assuming the package is missing.
    Guessing "not installed" sends someone to reinstall a package that is
    already there when the real cause is a version clash or a missing DLL,
    which is a dead end.

    ``invalidate_caches`` matters more than it looks: pip-installing while
    DazedTL is open leaves the interpreter's cached listing of site-packages
    stale, so a freshly installed engine reads as missing until a restart.
    """
    import importlib

    importlib.invalidate_caches()
    try:
        importlib.import_module(module)
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.split(".")[0] != module.split(".")[0]:
            return False, f"needs {exc.name}, which is missing ({install_hint})"
        return False, f"not installed - {install_hint}"
    except Exception as exc:
        return False, f"installed but unusable: {type(exc).__name__}: {exc}"
    return True, "ready"


@dataclass
class Word:
    text: str
    box: Box
    angle: float = 0.0

    def to_dict(self) -> dict:
        return {"text": self.text, "box": self.box.as_xywh(), "angle": round(self.angle, 2)}

    @staticmethod
    def from_dict(data: dict) -> "Word":
        return Word(str(data.get("text") or ""), Box.from_any(data["box"]),
                    float(data.get("angle") or 0.0))


@dataclass
class Line:
    text: str
    box: Box
    angle: float = 0.0

    def to_dict(self) -> dict:
        return {"text": self.text, "box": self.box.as_xywh(), "angle": round(self.angle, 2)}

    @staticmethod
    def from_dict(data: dict) -> "Line":
        return Line(str(data.get("text") or ""), Box.from_any(data["box"]),
                    float(data.get("angle") or 0.0))


@dataclass
class Block:
    """A paragraph as the engine grouped it. ``text`` keeps the line breaks."""

    text: str
    box: Box
    angle: float = 0.0
    lines: list[Line] = field(default_factory=list)

    @property
    def vertical(self) -> bool:
        """Rotated roughly a quarter turn - a vertical UI strip, not body text."""
        return abs(abs(self.angle) - 90.0) < 30.0

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "box": self.box.as_xywh(),
            "angle": round(self.angle, 2),
            "lines": [line.to_dict() for line in self.lines],
        }

    @staticmethod
    def from_dict(data: dict) -> "Block":
        return Block(
            str(data.get("text") or ""),
            Box.from_any(data["box"]),
            float(data.get("angle") or 0.0),
            [Line.from_dict(item) for item in data.get("lines") or []],
        )


@dataclass
class Reading:
    blocks: list[Block] = field(default_factory=list)
    words: list[Word] = field(default_factory=list)
    engine: str = ""

    def to_dict(self) -> dict:
        return {
            "engine": self.engine,
            "blocks": [block.to_dict() for block in self.blocks],
            "words": [word.to_dict() for word in self.words],
        }

    @staticmethod
    def from_dict(data: dict) -> "Reading":
        return Reading(
            [Block.from_dict(item) for item in data.get("blocks") or []],
            [Word.from_dict(item) for item in data.get("words") or []],
            str(data.get("engine") or ""),
        )


class OcrEngine(Protocol):
    name: str

    def available(self) -> bool: ...
    def status(self) -> str: ...
    def read(self, array: np.ndarray) -> Reading: ...


def rotated_box(cx: float, cy: float, w: float, h: float, angle: float) -> Box:
    """Axis-aligned bounds of a rotated rectangle.

    Lens reports a *centre-rotated* box: the extent is measured along the text
    baseline, not along the image axes. On a vertical strip that means a
    154x21 box describes something 21 wide and 154 tall on screen. Rotating the
    corners and taking their bounds is the only way to get the region a numpy
    slice can actually address. Verified against the vertical AC8 asset, where
    the naive reading puts every box in the wrong place.
    """
    radians = math.radians(angle)
    cos, sin = math.cos(radians), math.sin(radians)
    dx, dy = w / 2.0, h / 2.0
    xs, ys = [], []
    for sx, sy in ((-dx, -dy), (dx, -dy), (dx, dy), (-dx, dy)):
        xs.append(cx + sx * cos - sy * sin)
        ys.append(cy + sx * sin + sy * cos)
    return Box(int(math.floor(min(xs))), int(math.floor(min(ys))),
               int(math.ceil(max(xs))), int(math.ceil(max(ys))))


def worth_keeping(text: str, box: Box) -> bool:
    """Drop detector artefacts before they reach the user's review list."""
    if not text.strip():
        return False
    span, thickness = max(box.w, box.h), min(box.w, box.h)
    return span >= MIN_SPAN and thickness >= MIN_THICKNESS


# --------------------------------------------------------------------------
# registry

_FACTORIES: dict[str, Callable[[], OcrEngine]] = {}
_ORDER: list[str] = []


def register(name: str, factory: Callable[[], OcrEngine]) -> None:
    if name not in _FACTORIES:
        _ORDER.append(name)
    _FACTORIES[name] = factory


def engine_names() -> list[str]:
    return list(_ORDER)


def get_engine(name: str = "") -> OcrEngine:
    """Resolve an engine by name, or the first available one when unnamed."""
    _load_builtin()
    if name:
        try:
            factory = _FACTORIES[name]
        except KeyError:
            raise OcrUnavailable(
                f"Unknown OCR engine {name!r}. Available: {', '.join(_ORDER) or 'none'}"
            ) from None
        return factory()
    for candidate in _ORDER:
        engine = _FACTORIES[candidate]()
        if engine.available():
            return engine
    raise OcrUnavailable(
        "No OCR engine is available.\n" + "\n".join(engine_status().values())
    )


def engine_status() -> dict[str, str]:
    _load_builtin()
    report = {}
    for name in _ORDER:
        try:
            report[name] = _FACTORIES[name]().status()
        except Exception as exc:            # a broken optional dep must not hide the rest
            report[name] = f"{name}: unusable ({exc})"
    return report


_loaded = False


def _load_builtin() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    # Import for the side effect of registering. Order is preference order.
    for module in ("util.imagetools.ocr.lens", "util.imagetools.ocr.rapid"):
        try:
            __import__(module)
        except Exception:
            # An engine whose module will not even import is simply not offered;
            # engine_status() is where the user finds out why.
            pass


def read_many(
    images: Iterable[tuple[str, np.ndarray]],
    engine: OcrEngine | None = None,
    *,
    should_stop: Callable[[], bool] | None = None,
) -> Iterator[tuple[str, Reading | None, str]]:
    """Read a batch, yielding ``(key, reading, error)`` as each finishes.

    Yields per image rather than returning a list so a long run can show
    progress and be cancelled part-way without losing what it already read.
    """
    engine = engine or get_engine()
    for key, array in images:
        if should_stop is not None and should_stop():
            return
        try:
            yield key, engine.read(array), ""
        except Exception as exc:
            yield key, None, str(exc)
