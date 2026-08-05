"""Integer pixel rectangles."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Box:
    """Pixel rectangle. ``x2``/``y2`` are exclusive."""

    x: int
    y: int
    x2: int
    y2: int

    def __post_init__(self) -> None:
        # Coordinates routinely arrive from OpenCV stats and numpy indexing as
        # np.int32, which json.dump refuses. Coercing once here keeps every
        # construction site from having to remember, and the job file is the
        # only durable record of a run.
        for name in ("x", "y", "x2", "y2"):
            value = getattr(self, name)
            if type(value) is not int:
                object.__setattr__(self, name, int(value))

    @property
    def w(self) -> int:
        return self.x2 - self.x

    @property
    def h(self) -> int:
        return self.y2 - self.y

    @property
    def area(self) -> int:
        return max(0, self.w) * max(0, self.h)

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.x2, self.y2)

    def as_xywh(self) -> list[int]:
        return [self.x, self.y, self.w, self.h]

    def slices(self) -> tuple[slice, slice]:
        """``(rows, cols)`` for numpy indexing."""
        return slice(self.y, self.y2), slice(self.x, self.x2)

    def expand(self, pad: int, bounds: "Box | None" = None) -> "Box":
        box = Box(self.x - pad, self.y - pad, self.x2 + pad, self.y2 + pad)
        return box.clamp(bounds) if bounds is not None else box

    def clamp(self, bounds: "Box") -> "Box":
        return Box(
            max(bounds.x, min(self.x, bounds.x2)),
            max(bounds.y, min(self.y, bounds.y2)),
            max(bounds.x, min(self.x2, bounds.x2)),
            max(bounds.y, min(self.y2, bounds.y2)),
        )

    def union(self, other: "Box") -> "Box":
        return Box(
            min(self.x, other.x),
            min(self.y, other.y),
            max(self.x2, other.x2),
            max(self.y2, other.y2),
        )

    def intersects(self, other: "Box") -> bool:
        return not (
            self.x2 <= other.x
            or other.x2 <= self.x
            or self.y2 <= other.y
            or other.y2 <= self.y
        )

    def contains(self, other: "Box") -> bool:
        return (
            self.x <= other.x
            and self.y <= other.y
            and self.x2 >= other.x2
            and self.y2 >= other.y2
        )

    @staticmethod
    def from_size(width: int, height: int) -> "Box":
        return Box(0, 0, width, height)

    @staticmethod
    def from_xywh(x: int, y: int, w: int, h: int) -> "Box":
        return Box(int(x), int(y), int(x) + int(w), int(y) + int(h))

    @staticmethod
    def from_any(value) -> "Box":
        """Accept a Box, ``[x, y, w, h]``, or a dict with x/y/w/h or x/y/x2/y2."""
        if isinstance(value, Box):
            return value
        if isinstance(value, dict):
            if "x2" in value:
                return Box(int(value["x"]), int(value["y"]), int(value["x2"]), int(value["y2"]))
            return Box.from_xywh(value["x"], value["y"], value["w"], value["h"])
        x, y, w, h = (int(v) for v in value)
        return Box.from_xywh(x, y, w, h)
