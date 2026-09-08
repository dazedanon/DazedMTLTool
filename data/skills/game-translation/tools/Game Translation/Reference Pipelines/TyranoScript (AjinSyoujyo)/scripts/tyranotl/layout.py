"""Does the English still fit the box it is drawn in?

Measured, not guessed. The game ships its own font at
``data/others/MyFont1.otf`` and every widget carries its pixel geometry in the
tag that draws it, so widths are computed with the real face when Pillow is
available and with a per-script advance estimate otherwise.

Three widget classes matter:

``ptext``   free-positioned, **never wraps**. Hard constraint: the English must
            not be wider than the room the Japanese had, or it runs off screen.
``choice``  glink/button labels inside a fixed ``width=`` box (600 px here).
``dialogue`` the message box, which is 1920 px wide with 50/70 px margins and
            auto-returns. Width is not a constraint; total length is a soft one.
"""
from __future__ import annotations

import functools
from pathlib import Path

from . import codes

#: from data/system/Config.tjs and system/macro.ks show_mesL
SCREEN_W = 1920
MESSAGE_BOX_W = SCREEN_W - 50 - 70
MESSAGE_FONT = 42          # [deffont size=42] in first.ks
MESSAGE_LINES = 3          # 300 px tall box at 42 px + 8 px leading

GLINK_DEFAULT_W = 600
GLINK_DEFAULT_SIZE = 27

FONT_REL = "data/others/MyFont1.otf"


@functools.lru_cache(maxsize=8)
def _font(app_root: str, size: int):
    try:
        from PIL import ImageFont
    except ImportError:
        return None
    path = Path(app_root) / FONT_REL
    if not path.exists():
        return None
    try:
        return ImageFont.truetype(str(path), size)
    except OSError:
        return None


def measure(text: str, size: int, app_root: Path | None = None) -> float:
    """Advance width in pixels at ``size`` px."""
    font = _font(str(app_root), size) if app_root else None
    if font is not None:
        return font.getlength(text)
    # Fallback: CJK is square, Latin averages ~0.52 em in this face.
    cells = codes.display_width(text)
    return cells * size * 0.52


def budget_for(unit_kind: str, site) -> tuple[int, int] | None:
    """``(font_size, max_width_px)`` for a unit's widget, or ``None`` if unbounded."""
    attrs = {}
    if unit_kind == "ptext":
        size = int(_attr(site, "size", 37))
        # A free-positioned label has the screen from its x to the right edge.
        x = _attr(site, "x", None)
        try:
            left = int(str(x))
        except (TypeError, ValueError):
            left = 0
        return size, max(200, SCREEN_W - left - 20)
    if unit_kind == "choice":
        size = int(_attr(site, "size", GLINK_DEFAULT_SIZE))
        declared = _attr(site, "width", None)
        if declared is None:
            # An undeclared glink sizes itself to its text and can run into
            # whatever sits beside it - the day button overlapped the clock, the
            # bug-report button overlapped the time icons. With no declared box,
            # the Japanese's own width is the only evidence of the room there is.
            return size, None
        return size, max(80, int(declared) - 24)
    if unit_kind == "hint":
        # A hover tooltip floats free; the `width` on the tag it hangs off is the
        # button graphic's width, not the tooltip's, so it is not a bound at all.
        return None
    if unit_kind == "dialogue":
        return MESSAGE_FONT, MESSAGE_BOX_W * MESSAGE_LINES
    return None


def _attr(site, name: str, default):
    """Pull a sibling attribute off the tag this site came from.

    Sites store only their own span, so the tag text is re-read lazily by the
    caller through ``site.context``; when it is absent the default applies.
    """
    context = getattr(site, "context", "") or ""
    if not context:
        return default
    import re
    m = re.search(rf'\b{name}\s*=\s*"([^"]*)"|\b{name}\s*=\s*\'([^\']*)\'', context)
    if not m:
        return default
    return m.group(1) or m.group(2) or default


def neighbour_bound(site, app_root: Path) -> int | None:
    """How much room a free-standing widget actually has to its right.

    A glink with no ``width=`` sizes itself to its text, so what limits it is not
    the screen edge but whatever sits beside it on the same row: the day button
    ran into the clock, the bug-report button ran into the time icons. Scans the
    same file for another positioned widget at a similar ``y`` and takes the
    nearest one to the right.
    """
    from . import kslex

    try:
        own_x = int(_attr(site, "x", None))
        own_y = int(_attr(site, "y", None))
    except (TypeError, ValueError):
        return None

    script = app_root / site.file
    if not script.exists():
        return None
    nearest = SCREEN_W
    for line in kslex.read(script, site.file).lines:
        for tag in line.tags:
            if tag.name not in ("glink", "button", "ptext", "image", "mtext"):
                continue
            attrs = {a.name: a.value for a in tag.attrs}
            try:
                x = int(attrs.get("x") or attrs.get("left"))
                y = int(attrs.get("y") or attrs.get("top"))
            except (TypeError, ValueError):
                continue
            if abs(y - own_y) <= 25 and own_x < x < nearest:
                nearest = x
    return max(60, nearest - own_x - 16) if nearest < SCREEN_W else None


def check(unit, app_root: Path) -> list[str]:
    """Soft layout warnings for one translated unit."""
    if not unit.en or not unit.sites:
        return []
    warnings: list[str] = []
    plain_src = codes.SENTINEL_RE.sub("", unit.src)
    plain_en = codes.SENTINEL_RE.sub("", unit.en)
    if not plain_en.strip():
        return []

    budget = budget_for(unit.kind, unit.sites[0])
    if budget:
        size, limit = budget
        if limit is None or unit.kind == "ptext":
            limit = limit or 0
            # The screen edge is not the real bound. Several of this game's
            # free-positioned labels are already wider than the room between
            # their x and the screen edge, so the Japanese itself is the
            # evidence of how much space there is: anything no wider than the
            # source fits wherever the source fitted.
            limit = max(limit, int(measure(plain_src, size, app_root) * 1.05))
        elif unit.kind == "choice" and budget[1] is None:
            limit = int(measure(plain_src, size, app_root) * 1.15)
        width = measure(plain_en, size, app_root)
        if width > limit:
            warnings.append(f"{unit.kind} overflows: {width:.0f}px > {limit}px at {size}px")

    src_cells = codes.display_width(plain_src)
    if src_cells and len(plain_en) > src_cells * 4 and unit.kind != "dialogue":
        warnings.append(f"expands {len(plain_en) / src_cells:.1f}x - likely too long for its widget")

    if unit.src.count("\n") != unit.en.count("\n"):
        warnings.append("line-break count changed")
    return warnings


def wrap(text: str, size: int, max_width: float, app_root: Path | None = None) -> list[str]:
    """Greedy word wrap to a pixel width. Used for the shortening report only -
    the message box auto-returns, so nothing is rewrapped on injection."""
    words = text.split(" ")
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and measure(candidate, size, app_root) > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines
