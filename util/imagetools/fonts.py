"""Font discovery and metric-accurate fitting.

The agent never picks a font size. It supplies a string; this module measures
real glyph metrics and returns the largest size that fits the measured region,
wrapping only when the region is tall enough to hold more than one line.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

from util.paths import PROJECT_ROOT

BUNDLED_FONT_DIR = PROJECT_ROOT / "fonts"

# Windows / Linux / macOS families that cover Latin plus CJK punctuation.
_SYSTEM_CANDIDATES = (
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/calibri.ttf",
    "C:/Windows/Fonts/meiryo.ttc",
    "C:/Windows/Fonts/msgothic.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
)

_BOLD_CANDIDATES = (
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/calibrib.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
)


@dataclass
class FittedText:
    """A concrete, renderable layout - no judgement left to the caller.

    ``width`` and ``height`` are the *painted* extent: the ink the glyphs
    actually cover, plus the stroke that will be drawn around it. Not the font's
    nominal line box, which for a single line of capitals overstates the height
    by a third and stops the type a visible margin short of the box it was told
    to fill.

    ``ink_top`` is where that ink starts relative to the drawing origin, so the
    renderer can put the painted extent where it measured it rather than
    guessing the offset a second time.
    """

    lines: list[str]
    font_path: str
    size: int
    line_height: int
    width: int
    height: int
    fits: bool
    reason: str = ""
    stroke: int = 0
    ink_top: int = 0


# Where the operating system keeps its own faces. Every one of these is worth
# offering: the typeface is the single value measurement cannot recover, so the
# choice has to be as wide as the machine allows rather than as wide as a list
# in this file allows.
_SYSTEM_FONT_DIRS = (
    Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Windows/Fonts",
    Path("/usr/share/fonts"),
    Path("/usr/local/share/fonts"),
    Path.home() / ".fonts",
    Path.home() / ".local/share/fonts",
    Path("/System/Library/Fonts"),
    Path("/Library/Fonts"),
    Path.home() / "Library/Fonts",
)

_FONT_SUFFIXES = (".ttf", ".ttc", ".otf")


def available_fonts() -> list[Path]:
    """Every usable face: the bundled ones first, then the system's own."""
    fonts: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        key = str(path).lower()
        if key not in seen and path.is_file():
            seen.add(key)
            fonts.append(path)

    if BUNDLED_FONT_DIR.is_dir():
        for pattern in ("*.ttf", "*.ttc", "*.otf"):
            for path in sorted(BUNDLED_FONT_DIR.glob(pattern)):
                add(path)
    for directory in _SYSTEM_FONT_DIRS:
        try:
            if not directory.is_dir():
                continue
            # One level down as well: Linux keeps its faces in per-family
            # subdirectories and a flat glob finds nothing at all there.
            for path in sorted(directory.iterdir()):
                if path.is_dir():
                    for child in sorted(path.iterdir()):
                        if child.suffix.lower() in _FONT_SUFFIXES:
                            add(child)
                elif path.suffix.lower() in _FONT_SUFFIXES:
                    add(path)
        except OSError:
            continue
    for candidate in _SYSTEM_CANDIDATES + _BOLD_CANDIDATES:
        add(Path(candidate))
    return fonts


@lru_cache(maxsize=2048)
def font_name(path: str) -> str:
    """The face's own name - "Segoe UI Semibold", not "seguisb".

    Read out of the file rather than off the filename. Windows names its font
    files by an eight-character convention nobody has been able to read since
    1995, and a dropdown of them is a dropdown of nothing.
    """
    try:
        family, style = ImageFont.truetype(path, 10).getname()
    except Exception:
        return Path(path).stem
    family = (family or Path(path).stem).strip()
    style = (style or "").strip()
    if not style or style.lower() == "regular":
        return family
    return f"{family} {style}"


def default_font(bold: bool = False) -> str:
    """Pick a sane default, preferring an explicit override then a bundled face."""
    override = os.getenv("IMGTL_FONT", "").strip()
    if override and Path(override).is_file():
        return override

    pool = _BOLD_CANDIDATES if bold else ()
    for candidate in pool:
        if Path(candidate).is_file():
            return candidate

    if BUNDLED_FONT_DIR.is_dir():
        for pattern in ("*.ttf", "*.otf", "*.ttc"):
            found = sorted(BUNDLED_FONT_DIR.glob(pattern))
            if found:
                return str(found[0])

    for candidate in _SYSTEM_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    raise RuntimeError("No usable TrueType font found; set IMGTL_FONT to a .ttf path")


def resolve_font(name: str | None, bold: bool = False) -> str:
    """Accept an absolute path, a bare filename in fonts/, or None."""
    if not name:
        return default_font(bold=bold)
    path = Path(name)
    if path.is_file():
        return str(path)
    bundled = BUNDLED_FONT_DIR / name
    if bundled.is_file():
        return str(bundled)
    raise FileNotFoundError(f"Font not found: {name}")


@lru_cache(maxsize=256)
def _load(font_path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(font_path, size)


def measure(text: str, font_path: str, size: int) -> tuple[int, int]:
    font = _load(font_path, size)
    if not text:
        return 0, size
    left, top, right, bottom = font.getbbox(text)
    return right - left, bottom - top


def text_budget(
    *,
    width: int,
    height: int,
    cap_height: int,
    orientation: str = "horizontal",
    font_path: str | None = None,
) -> int:
    """Roughly how many characters of target text a region can hold.

    An estimate, not a promise - ``fit_text`` is the authority at render time.
    Its job is to give whoever writes the translation a number to aim at before
    the text exists, which is the difference between one render and four.
    """
    path = font_path or default_font()
    size = max(7, cap_height or 12)
    span = height if orientation == "vertical" else width
    sample = "abcdefghijklmnopqrstuvwxyz "
    sample_width, _ = measure(sample, path, size)
    if sample_width <= 0:
        return 20
    per_char = sample_width / len(sample)
    lines = 1
    if orientation == "horizontal":
        lines = max(1, height // max(1, int(size * 1.15)))
    return max(4, int((span / per_char) * lines))


def _wrap(text: str, font_path: str, size: int, max_width: int) -> list[str]:
    """Greedy wrap. Breaks on spaces for Latin, per character for CJK runs."""
    font = _load(font_path, size)

    def width_of(candidate: str) -> int:
        box = font.getbbox(candidate)
        return box[2] - box[0]

    words = text.split(" ")
    if len(words) > 1:
        lines: list[str] = []
        current = ""
        for word in words:
            trial = f"{current} {word}".strip()
            if current and width_of(trial) > max_width:
                lines.append(current)
                current = word
            else:
                current = trial
        if current:
            lines.append(current)
        return lines

    lines = []
    current = ""
    for char in text:
        if current and width_of(current + char) > max_width:
            lines.append(current)
            current = char
        else:
            current += char
    if current:
        lines.append(current)
    return lines


@lru_cache(maxsize=512)
def size_for_cap(font_path: str, cap_height: int) -> int:
    """The point size at which capitals stand *cap_height* pixels tall.

    The panel's "Font size" is in pixels of ink, because that is what was
    measured off the Japanese and what the user is comparing against on screen.
    Point size is not: a 40pt face draws capitals about 28px tall, and the ratio
    is the typeface's business, not a constant. Measuring it is two dozen
    ``getbbox`` calls behind an ``lru_cache``, which is cheaper than being
    wrong by a third.
    """
    if cap_height <= 0:
        return 0
    low, high = 1, max(8, cap_height * 4)
    best = 1
    while low <= high:
        middle = (low + high) // 2
        _, top, _, bottom = _load(font_path, middle).getbbox("H")
        if bottom - top <= cap_height:
            best = middle
            low = middle + 1
        else:
            high = middle - 1
    return best


def stroke_at(size: int, stroke_width: int, reference: int) -> int:
    """How wide the stroke is when the type is set at *size*.

    Shared with the renderer rather than worked out twice. The measured stroke
    belongs to the Japanese, which is usually set larger than the English that
    replaces it; a stroke that does not shrink with the type closes up the
    counters and turns small text into a blob.
    """
    if stroke_width <= 0:
        return 0
    scaled = stroke_width * size / max(1, reference)
    return int(max(1, min(stroke_width, round(scaled))))


def _extent(
    lines: list[str], font_path: str, size: int, line_height: int
) -> tuple[int, int, int]:
    """``(width, height, ink_top)`` of the ink these lines actually cover.

    Measured off the glyph bounding boxes rather than the font's line box. The
    difference is not cosmetic: a single line of capitals occupies about 70% of
    its line box, so budgeting by the line box leaves the type stopping a third
    of the box height short of the edge and refusing to grow any further, which
    is exactly what it looked like from the outside.

    Lines are laid out on a common baseline grid - each line's origin is one
    ``line_height`` below the last, with no per-line nudging - so a line with no
    ascenders sits where its baseline puts it rather than being shoved up to
    meet the top of its slot.
    """
    font = _load(font_path, size)
    top = None
    bottom = None
    widest = 0
    for index, line in enumerate(lines):
        left, line_top, right, line_bottom = font.getbbox(line)
        widest = max(widest, right - left)
        origin = index * line_height
        top = origin + line_top if top is None else min(top, origin + line_top)
        bottom = origin + line_bottom if bottom is None else max(bottom, origin + line_bottom)
    if top is None or bottom is None:
        return 0, 0, 0
    return widest, max(0, bottom - top), top


def fit_text(
    text: str,
    *,
    max_width: int,
    max_height: int,
    font_path: str,
    target_cap_height: int = 0,
    allow_wrap: bool = True,
    min_size: int = 7,
    line_spacing: float = 1.15,
    stroke_width: int = 0,
) -> FittedText:
    """Largest size at which *text* fits the box, wrapping only if permitted.

    Starts from the measured cap height of the source text so the replacement
    keeps the original's visual weight, and only shrinks from there.

    *stroke_width* is the stroke the renderer will draw around the glyphs at the
    reference cap height. It is part of what lands on the image, so it is part
    of what has to fit; leaving it out is how a heavy stroke ends up clipped by
    the edge of its own block.
    """
    text = text.strip()
    if not text:
        return FittedText([], font_path, min_size, min_size, 0, 0, True, "empty")

    reference = target_cap_height if target_cap_height > 0 else max_height
    # The ceiling is the size the caller actually asked for, converted from ink
    # pixels to points by measuring the face rather than by a 1.35 fudge factor.
    # Under it the ladder walks down until the box is satisfied, so "Font size"
    # means what it says right up to the point where the box says no.
    start = size_for_cap(font_path, reference) or max(min_size, reference)
    start = max(min_size, start)

    best_overflow: FittedText | None = None
    for size in range(start, min_size - 1, -1):
        stroke = stroke_at(size, stroke_width, reference)
        room_width = max(1, max_width - 2 * stroke)
        room_height = max(1, max_height - 2 * stroke)

        lines = [text]
        width, _ = measure(text, font_path, size)
        if width > room_width and allow_wrap and room_height >= size * 2:
            lines = _wrap(text, font_path, size, room_width)

        line_height = max(1, int(size * line_spacing))
        widest, ink_height, ink_top = _extent(lines, font_path, size, line_height)

        candidate = FittedText(
            lines=lines,
            font_path=font_path,
            size=size,
            line_height=line_height,
            width=widest + 2 * stroke,
            height=ink_height + 2 * stroke,
            fits=widest <= room_width and ink_height <= room_height,
            stroke=stroke,
            ink_top=ink_top,
        )
        if candidate.fits:
            return candidate
        if best_overflow is None:
            best_overflow = candidate

    result = best_overflow or FittedText(
        [text], font_path, min_size, min_size, 0, 0, False
    )
    result.fits = False
    result.reason = (
        f"does not fit in {max_width}x{max_height}px even at {min_size}pt; "
        "shorten the translation"
    )
    return result
