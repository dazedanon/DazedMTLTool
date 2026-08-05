"""Erase the source text, draw the translation.

The step everyone expected to need a model, and it needs none. `style.py`
measured what was there; this puts it back and writes the English over it.

Two things make that safe rather than reckless:

**Rendering always starts from the pristine original.** The first render stashes
a copy under ``.dazedtl/original`` and every render after that reads from it, so
a second pass cannot erase text that is already English and redraw it on top of
itself. Re-rendering is idempotent, which is what makes the preview loop usable
- the user can turn a knob twenty times and the twentieth result is as clean as
the first.

**Only the glyph pixels are erased, never the whole rectangle.** A confirmed
block routinely contains something that is not text - an icon beside a label, a
frame, a gradient - and blanking the box takes it with it.

Where the translation does not fit, there is a ladder rather than a failure:
wrap, shrink to 70% of the measured cap height, grow the box into space that is
provably empty, then shrink as far as legibility allows. Each rung is recorded
in the note, because "it fits" and "it fits because it is now 7pt" deserve
different reactions from the person looking at the preview.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

from util.imagetools.fonts import (
    FittedText,
    _load,
    fit_text,
    resolve_font,
    size_for_cap,
)
from util.imagetools import inpaint as inpaintmod
from util.imagetools.geometry import Box
from util.imagetools.paint import composite
from util.imagetools.style import (
    ALPHA_OPAQUE,
    BG_HGRADIENT,
    BG_INPAINT,
    BG_KEEP,
    BG_PATCH,
    BG_SOLID,
    BG_TRANSPARENT,
    BG_VGRADIENT,
    Style,
    ink_mask,
    measure,
)

# Antialiased glyph edges spill a little past the measured ink box.
ERASE_BLEED = 2

MIN_SIZE = 7
# How far below the measured cap height the type may shrink before the result
# stops looking like the same UI. Past this the block is grown instead.
COMFORTABLE = 0.70
# How far a block may grow into verified-empty space, as a share of its width.
GROWTH_LIMIT = 1.8


@dataclass
class Note:
    """What happened to one block, in words the preview panel can show."""

    block_id: str
    ok: bool
    message: str
    tight: bool = False          # rendered, but it had to give something up


@dataclass
class Result:
    array: np.ndarray
    notes: list[Note] = field(default_factory=list)
    # The render taken apart, for the editor's live brush. ``base`` is the image
    # after the erase and the paint layer but before a word of English; the text
    # sits on ``overlay`` on its own. Recombining them is two array composites,
    # so a stroke can appear under the type as it is drawn without re-rendering
    # anything - which is the difference between a brush and a wait.
    base: np.ndarray | None = None
    overlay: np.ndarray | None = None

    @property
    def failures(self) -> list[Note]:
        return [note for note in self.notes if not note.ok]

    @property
    def tight(self) -> list[Note]:
        return [note for note in self.notes if note.ok and note.tight]


# ------------------------------------------------------------------- files


def load_rgba(path: str | Path) -> np.ndarray | None:
    """Read any image as RGBA.

    Through ``imdecode`` rather than ``imread``: the workspace is full of
    Japanese filenames and OpenCV's own path handling mangles them on Windows,
    returning None for a file that is plainly there.
    """
    try:
        raw = np.fromfile(str(path), dtype=np.uint8)
        array = cv2.imdecode(raw, cv2.IMREAD_UNCHANGED)
    except Exception:
        return None
    if array is None:
        return None
    if array.ndim == 2:
        array = cv2.cvtColor(array, cv2.COLOR_GRAY2BGRA)
    elif array.shape[2] == 3:
        array = cv2.cvtColor(array, cv2.COLOR_BGR2BGRA)
    return cv2.cvtColor(array, cv2.COLOR_BGRA2RGBA)


def save_rgba(array: np.ndarray, path: str | Path) -> None:
    """Write RGBA PNG. Same non-ASCII path problem, same fix in reverse."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    bgra = cv2.cvtColor(array, cv2.COLOR_RGBA2BGRA)
    ok, buffer = cv2.imencode(".png", bgra)
    if not ok:
        raise OSError(f"Could not encode {target}")
    buffer.tofile(str(target))


# ------------------------------------------------------------------- erase


def _bleed_box(array: np.ndarray, box: Box) -> Box:
    return box.expand(ERASE_BLEED, Box.from_size(array.shape[1], array.shape[0]))


def word_limit(target: Box, words: list[Box], pad: int = 3) -> np.ndarray | None:
    """Where the OCR actually saw words, as a mask over the padded crop.

    A block's rectangle is the bounding box of its lines, so anything else
    inside that rectangle is caught by it - and on an illustrated page that is
    routinely a piece of the illustration. Lens reports geometry per *word*, and
    confining the erase to those keeps the picture out of it: a caption whose
    corner overlapped a circle used to take a bite out of the circle.

    Returns ``None`` when the words do not account for enough of the block, in
    which case the box is the better authority - a box the user drew by hand,
    or one enlarged to catch text the OCR missed, has no words to speak for it.
    """
    inside = [word for word in words if target.intersects(word)]
    if not inside:
        return None
    mask = np.zeros((target.h, target.w), dtype=bool)
    for word in inside:
        local = Box(
            max(0, word.x - pad - target.x),
            max(0, word.y - pad - target.y),
            min(target.w, word.x2 + pad - target.x),
            min(target.h, word.y2 + pad - target.y),
        )
        if local.w > 0 and local.h > 0:
            rows, cols = local.slices()
            mask[rows, cols] = True
    if mask.mean() < 0.5:
        return None
    return mask


def erase(
    array: np.ndarray, box: Box, style: Style, limit: np.ndarray | None = None
) -> Note:
    """Reconstruct the background under one block's glyphs, in place."""
    if style.background == BG_KEEP:
        return Note("", True, "background left as it is", tight=True)

    target = _bleed_box(array, box)
    rows, cols = target.slices()
    crop = array[rows, cols]
    # The mask is computed on the padded crop rather than pasted in from the
    # tight one, so the antialiased rim that sits just outside the confirmed box
    # is caught too. Left behind it reads as a coloured ghost of the old text.
    mask = ink_mask(crop, style)
    if limit is not None and limit.shape == mask.shape:
        mask &= limit
    if not mask.any():
        # Marked tight so it reaches the panel. A block with a translation in it
        # and nothing found to erase is almost always a wrong setting rather
        # than an empty box, and reporting it as a plain success is how a
        # silently-ignored "erase by" choice looked like the tool doing nothing.
        return Note(
            "",
            True,
            "no source text found under this box — nothing was erased, so the "
            "translation is drawn over whatever is there",
            tight=True,
        )
    # Grow it before painting. A glyph does not end where the ink mask does: it
    # fades out over two or three antialiased pixels that sit within ~3% of the
    # background and so fall below any sane ink threshold. Leave them and the
    # old text is still legible as a faint outline of itself - which measured as
    # a maximum error of 24/765 and was plainly visible on screen. Only inpaint
    # used to do this, which is why it was the only strategy that came out clean
    # on a flat field.
    mask = cv2.dilate(
        mask.astype(np.uint8),
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)),
    ) > 0

    if style.background == BG_TRANSPARENT:
        crop[mask] = (0, 0, 0, 0)
        return Note("", True, "glyphs cleared to transparent")

    if style.background == BG_SOLID and style.fill:
        crop[mask] = np.array(style.fill, dtype=np.uint8)
        return Note("", True, f"glyphs filled with rgba{tuple(style.fill)}")

    if style.background == BG_VGRADIENT and style.row_colors:
        for local_y in range(target.h):
            row = mask[local_y]
            if not row.any():
                continue
            index = min(max(0, target.y + local_y - box.y), len(style.row_colors) - 1)
            crop[local_y][row] = np.array(style.row_colors[index], dtype=np.uint8)
        return Note("", True, "glyphs filled row by row")

    if style.background == BG_HGRADIENT and style.column_colors:
        for local_x in range(target.w):
            column = mask[:, local_x]
            if not column.any():
                continue
            index = min(
                max(0, target.x + local_x - box.x), len(style.column_colors) - 1
            )
            crop[:, local_x][column] = np.array(
                style.column_colors[index], dtype=np.uint8
            )
        return Note("", True, "glyphs filled column by column")

    if style.background == BG_PATCH and style.donor is not None:
        # The donor was found for the tight box; pad it the same way so it lines
        # up with the padded crop.
        donor = style.donor.expand(ERASE_BLEED)
        drows, dcols = donor.slices()
        source = array[drows, dcols]
        if source.shape[:2] != crop.shape[:2]:
            return Note("", False, "the clone strip no longer matches this box")
        crop[mask] = source[mask]
        return Note("", True, f"glyphs cloned from {style.donor.as_xywh()}")

    if style.background == BG_INPAINT:
        # Only the glyph pixels go into the mask. The one inpaint that looked
        # awful in testing had a box-wide mask over 24% artwork, and it smeared
        # the artwork rather than the text.
        return _reconstruct(array, target, mask, style)

    # Everything above needs its own measurement to work with, and falling
    # through means the method is set but that measurement is not there. Say
    # which one is missing and what to do about it - the old catch-all named the
    # strategy and nothing else, which read as a bug in the tool rather than as
    # a choice the image cannot support.
    return Note("", False, _unerasable(style))


def _reconstruct(
    array: np.ndarray, target: Box, mask: np.ndarray, style: Style
) -> Note:
    """Rebuild the artwork under *mask*, colour **and** opacity.

    Alpha used to be left alone here, and every other erase method writes it, so
    reconstruction was the one strategy that could leave a perfect silhouette of
    the Japanese behind. On battle3_2.png the name plate is opaque white type
    cut into a 70% black bar: the colour came back as bar, the opacity stayed at
    255, and the result over the game background was a hard black shadow of the
    text in exactly the shape of the words that were supposed to be gone.

    The classical methods get the tight crop and nothing more - they average
    inwards from the mask edge, and a wider crop only offers somewhere further
    away to average from. A model is the opposite: a hole with no picture around
    it is a hole it has nothing to say about, so it is handed a frame of context
    and only the masked pixels are taken from what comes back.
    """
    method = style.inpaint_method or inpaintmod.DEFAULT
    bounds = Box.from_size(array.shape[1], array.shape[0])

    # Fully transparent pixels have no colour to lend - what is stored under
    # alpha 0 is whatever the exporter left there, usually black - so they are
    # marked unknown rather than believed. Their own alpha keeps whatever comes
    # back for them invisible.
    trows, tcols = target.slices()
    crowded = float(
        (mask | (array[trows, tcols][:, :, 3] == 0)).mean()
    ) > inpaintmod.CROWDED

    if inpaintmod.needs_context(method):
        share = inpaintmod.CONTEXT
    elif crowded:
        # A diffusion fill reads only from the pixels it is handed, and a box
        # drawn tightly around a word is mostly word. Left on the tight crop it
        # returns the picture unchanged and raises nothing, so the block came
        # back marked reconstructed with the source text still on it.
        share = inpaintmod.CROWDED_CONTEXT
    else:
        share = 0.0
    pad = int(max(target.w, target.h) * share)
    window = target.expand(pad, bounds) if pad else target

    rows, cols = window.slices()
    view = array[rows, cols]
    hole = np.zeros(view.shape[:2], dtype=bool)
    hole[
        target.y - window.y : target.y2 - window.y,
        target.x - window.x : target.x2 - window.x,
    ] = mask

    unknown = hole | (view[:, :, 3] == 0)

    rgb = cv2.cvtColor(np.ascontiguousarray(view), cv2.COLOR_RGBA2RGB)
    repaired, complaint = inpaintmod.fill(rgb, unknown, method)
    moved = int((repaired != rgb).any(axis=2)[hole].sum())
    view[:, :, :3] = np.where(hole[:, :, None], repaired, view[:, :, :3])
    view[:, :, 3] = np.where(
        hole, inpaintmod.fill_alpha(np.ascontiguousarray(view[:, :, 3]), hole), view[:, :, 3]
    )

    if not moved and hole.any():
        # Nothing was reconstructed, whatever the reason. Saying "reconstructed"
        # here is the failure the user has to spot for themselves, and they
        # should not have to.
        return Note("", True, (
            "there was too little clean artwork around this box to rebuild "
            "what the glyphs were sitting on — nothing was erased. Try a "
            "different “Erase by”, or widen the box"
        ), tight=True)

    message = "artwork reconstructed under the glyphs"
    if complaint:
        message = f"{message} - {complaint}"
    return Note("", True, message, tight=True)


_MISSING = {
    BG_SOLID: (
        "no fill colour was found for this block — pick one under “Erase by”, "
        "or use “Reconstruct the artwork”"
    ),
    BG_VGRADIENT: (
        "there is no clean margin either side of this box to read a vertical "
        "gradient from — try “Reconstruct the artwork”"
    ),
    BG_HGRADIENT: (
        "the background between the glyphs is not a left-to-right gradient — "
        "try “Reconstruct the artwork”"
    ),
    BG_PATCH: (
        "no clean strip above or below this block to clone from — try "
        "“Reconstruct the artwork”"
    ),
}


def _unerasable(style: Style) -> str:
    known = _MISSING.get(style.background)
    if known:
        return known
    return (
        f"“{style.background}” is not an erase method this build knows; "
        "choose another under “Erase by”"
    )


# ------------------------------------------------------------------ growth


def growth_room(
    source: np.ndarray,
    box: Box,
    style: Style,
    others: list[Box],
    *,
    vertical: bool = False,
) -> Box:
    """Widen a label into space that is provably empty.

    Two kanji become seven letters, and forcing that into the Japanese ink box
    drops the type well below every other label in the game - which is more
    visible than the extra width would be. Most UI art leaves room beside its
    text; this measures how much is genuinely free.

    Free means: matches this block's own background, and belongs to no other
    block. So it can never grow over artwork or over a neighbouring label. The
    erase mask is untouched - growth decides where glyphs may be *drawn*, never
    what gets rubbed out.
    """
    height, width = source.shape[:2]
    bounds = Box.from_size(width, height)
    # A rotated strip is drawn rotated, so growing it sideways would push the
    # text off its own baseline. Only flat labels grow.
    if vertical or style.background in (BG_INPAINT, BG_KEEP, BG_PATCH, BG_HGRADIENT):
        return box

    if style.background == BG_TRANSPARENT:
        free_pixel = source[:, :, 3] <= ALPHA_OPAQUE
    elif style.fill:
        fill = np.array(style.fill[:3], dtype=np.int16)
        close = np.abs(source[:, :, :3].astype(np.int16) - fill).sum(axis=2) <= 40
        free_pixel = close | (source[:, :, 3] <= ALPHA_OPAQUE)
    else:
        return box

    blocked = np.zeros(width, dtype=bool)
    for other in others:
        if other.as_tuple() == box.as_tuple():
            continue
        if other.y < box.y2 and other.y2 > box.y:
            blocked[max(0, other.x) : min(width, other.x2)] = True

    strip = free_pixel[box.y : box.y2, :]
    if strip.size == 0:
        return box
    free = strip.all(axis=0) & ~blocked

    left = box.x
    while left > 0 and free[left - 1]:
        left -= 1
    right = box.x2
    while right < width and free[right]:
        right += 1
    if right - left <= box.w:
        return box

    # Keep the label roughly where the artist put it rather than letting it
    # drift to whichever side happened to be emptier.
    cap = int(box.w * GROWTH_LIMIT)
    grown = Box(left, box.y, right, box.y2)
    if grown.w > cap:
        centre = (box.x + box.x2) // 2
        half = cap // 2
        grown = Box(max(left, centre - half), box.y, min(right, centre + half), box.y2)
    return grown.clamp(bounds)


# --------------------------------------------------------------------- fit


@dataclass
class Layout:
    fitted: FittedText
    box: Box
    align: str
    fits: bool
    note: str = ""
    tight: bool = False


def plan(
    text: str,
    box: Box,
    style: Style,
    *,
    vertical: bool,
    font_path: str,
    room: Box | None = None,
) -> Layout:
    """The fit ladder. Stops at the first rung that works and says which one."""
    cap = max(MIN_SIZE, int(style.cap_height))
    # The rungs are floors on the *point size*, but the style speaks in pixels of
    # ink. Convert once, here, so "70% of the original" is 70% of what the reader
    # sees rather than 70% of a number the font is free to reinterpret.
    ceiling = max(MIN_SIZE, size_for_cap(font_path, cap) or cap)
    comfortable = max(MIN_SIZE, size_for_cap(font_path, int(round(cap * COMFORTABLE))))

    stroke_width = style.outline_width if style.outline_color else 0

    def attempt(target: Box, floor: int) -> FittedText:
        width, height = (target.h, target.w) if vertical else (target.w, target.h)
        return fit_text(
            text,
            max_width=width,
            max_height=height,
            font_path=font_path,
            target_cap_height=cap,
            allow_wrap=not vertical,
            min_size=floor,
            stroke_width=stroke_width,
        )

    # 1. its own box, at a size close to the original's
    first = attempt(box, comfortable)
    if first.fits:
        return Layout(first, box, style.align, True)

    # 2. the same, in space beside it that measurement proved empty
    if room is not None and room.area > box.area:
        grown = attempt(room, comfortable)
        if grown.fits:
            return Layout(
                grown, room, style.align, True,
                f"widened by {room.w - box.w}px into empty space",
            )

    # 3. smaller than the original, which is visible but still legible
    target = room if room is not None and room.area > box.area else box
    small = attempt(target, MIN_SIZE)
    if small.fits:
        percent = round(100 * small.size / max(1, ceiling))
        return Layout(
            small, target, style.align, True,
            f"set at {small.size}pt, {percent}% of the original size",
            tight=True,
        )

    return Layout(
        small, target, style.align, False,
        f"does not fit even at {MIN_SIZE}pt - shorten the translation",
    )


# -------------------------------------------------------------------- draw


def _outside(alpha: np.ndarray) -> np.ndarray:
    """Which pixels are outside the glyphs rather than inside a counter.

    The region of "no ink" that reaches the edge of the tile. What is left over
    is the enclosed space inside an ``a``, an ``o``, a ``B`` - and that space is
    background, not somewhere a stroke belongs.
    """
    solid = (alpha > 0).astype(np.uint8)
    # One pixel of margin so a glyph flush with the tile edge cannot fence the
    # exterior off from the corner the flood starts at.
    padded = cv2.copyMakeBorder(solid, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
    _, labels = cv2.connectedComponents((padded == 0).astype(np.uint8), connectivity=4)
    return (labels == labels[0, 0])[1:-1, 1:-1]


def _stroked(size, fitted, align, text_color, outline) -> Image.Image:
    """Glyphs with a stroke that stays out of their counters.

    PIL's ``stroke_width`` dilates the glyph and paints the fill back over it,
    which is right everywhere except inside a closed letter: past about half the
    counter's width the stroke meets itself in the middle and the hole in an
    ``a`` or a ``B`` fills solid. It reads as the letter losing its shape, and
    it gets worse the heavier the stroke - so the setting could not be used at
    the strengths it exists for.

    Drawn as two layers instead. The stroke is masked down to the pixels the
    fill's own *exterior* reaches, so it grows outwards without ever growing
    inwards, and the counters keep showing whatever is behind the text.
    """
    fill_layer = Image.new("RGBA", size, (0, 0, 0, 0))
    stroke_layer = Image.new("RGBA", size, (0, 0, 0, 0))
    fill_draw = ImageDraw.Draw(fill_layer)
    stroke_draw = ImageDraw.Draw(stroke_layer)
    font = _load(fitted.font_path, fitted.size)
    stroke = fitted.stroke if outline else 0

    # Put the ink where it was measured: the fitted height is the painted
    # extent, so centring on it lands the glyphs in the middle of the box
    # instead of a line-box's worth of empty space high.
    top = max(0, (size[1] - fitted.height) // 2) + stroke - fitted.ink_top
    for index, line in enumerate(fitted.lines):
        left, _, right, _ = font.getbbox(line)
        width = right - left
        if align == "center":
            x = (size[0] - width) // 2
        elif align == "right":
            x = size[0] - width - stroke
        else:
            x = stroke
        at = (x - left, top + index * fitted.line_height)
        if stroke:
            stroke_draw.text(
                at, line, font=font, fill=outline,
                stroke_width=stroke, stroke_fill=outline,
            )
        fill_draw.text(at, line, font=font, fill=text_color)

    if not stroke:
        return fill_layer

    fill_array = np.array(fill_layer)
    stroke_array = np.array(stroke_layer)
    allowed = _outside(fill_array[:, :, 3]) | (fill_array[:, :, 3] > 0)
    stroke_array[:, :, 3][~allowed] = 0
    return Image.alpha_composite(
        Image.fromarray(stroke_array), Image.fromarray(fill_array)
    )


def _tile(size: tuple[int, int], layout: Layout, style: Style) -> Image.Image:
    """Draw the fitted lines onto a transparent tile."""
    outline = None
    if style.outline_color and style.outline_width > 0:
        outline = tuple(style.outline_color)
    return _stroked(
        size, layout.fitted, layout.align, tuple(style.text_color), outline
    )


def paste(overlay: Image.Image, layout: Layout, style: Style, vertical: bool) -> None:
    """Add one block's text to a transparent overlay, in place."""
    box = layout.box
    size = (box.h, box.w) if vertical else (box.w, box.h)
    tile = _tile(size, layout, style)
    if vertical:
        tile = tile.transpose(Image.ROTATE_90)
    patch = Image.new("RGBA", overlay.size, (0, 0, 0, 0))
    patch.paste(tile, (box.x, box.y))
    overlay.alpha_composite(patch)


def draw(array: np.ndarray, layout: Layout, style: Style, vertical: bool) -> None:
    """Composite the laid-out text onto *array*, in place."""
    height, width = array.shape[:2]
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    paste(overlay, layout, style, vertical)
    array[:, :] = np.array(
        Image.alpha_composite(Image.fromarray(array, mode="RGBA"), overlay),
        dtype=np.uint8,
    )


# ------------------------------------------------------------------ render


def render_entry(
    source: np.ndarray,
    entry,
    *,
    font_name: str | None = None,
    only: str = "",
    paint: np.ndarray | None = None,
) -> Result:
    """Render one image. *source* is the pristine original and is never mutated.

    ``only`` renders a single block, which is what the preview uses while a knob
    is being dragged. ``paint`` is the user's manual touch-up layer.

    Three passes, not one, and the order is the point:

        erase every block -> composite the paint -> draw every translation

    Erasing all of them first keeps the old behaviour where a later inpaint can
    use an earlier block's cleaned pixels as context. Compositing the paint in
    the middle is what makes it a *background repair* layer - a stroke can fix
    anything the erase left behind and can never cover the English, whatever the
    fit ladder later does with the type. Drawing last is what that costs.
    """
    array = source.copy()
    boxes = [block.box for block in entry.blocks]
    word_boxes = [word.box for word in getattr(entry, "words", [])]
    bounds = Box.from_size(array.shape[1], array.shape[0])

    # Keyed by block so the notes come out in reading order at the end rather
    # than in "everything that failed, then everything that worked" order.
    notes: dict[str, Note] = {}
    planned: list[tuple[object, Layout, Style, Note]] = []

    for block in entry.blocks:
        if only and block.block_id != only:
            continue
        if block.skip:
            notes[block.block_id] = Note(
                block.block_id, True, "left alone at your request"
            )
            continue
        text = (block.target_text or "").strip()
        if not text:
            # Erasing here would leave a hole where the Japanese used to be,
            # which is worse than an untranslated line.
            notes[block.block_id] = Note(
                block.block_id, True, "no translation yet; left as it is"
            )
            continue

        if block.style is None:
            # Keep what was measured. Otherwise the Look panel shows a fresh
            # measurement of an image the user has already rendered, and the
            # numbers on screen are not the ones that produced the file.
            block.style = measure(source, block, boxes)
        style = block.style
        box = block.box.clamp(bounds)
        if box.w < 2 or box.h < 2:
            notes[block.block_id] = Note(
                block.block_id, False, "box is too small to draw in"
            )
            continue

        erased = erase(
            array, box, style, word_limit(_bleed_box(array, box), word_boxes)
        )
        if not erased.ok:
            notes[block.block_id] = Note(block.block_id, False, erased.message)
            continue

        room = growth_room(source, box, style, boxes, vertical=block.vertical)
        try:
            font_path = resolve_font(style.font or font_name)
        except Exception as exc:
            notes[block.block_id] = Note(block.block_id, False, f"font: {exc}")
            continue
        layout = plan(
            text, box, style,
            vertical=block.vertical, font_path=font_path, room=room,
        )
        if not layout.fits:
            notes[block.block_id] = Note(block.block_id, False, layout.note)
            continue
        planned.append((block, layout, style, erased))

    composite(array, paint)
    base = array.copy()

    overlay = Image.new("RGBA", (array.shape[1], array.shape[0]), (0, 0, 0, 0))
    for block, layout, style, erased in planned:
        paste(overlay, layout, style, block.vertical)
        message = f"{len(layout.fitted.lines)} line(s) at {layout.fitted.size}pt"
        if layout.note:
            message += f" - {layout.note}"
        if erased.tight and not layout.tight:
            message += f" - {erased.message}"
        notes[block.block_id] = Note(
            block.block_id, True, message, tight=layout.tight or erased.tight
        )

    array[:, :] = np.array(
        Image.alpha_composite(Image.fromarray(array, mode="RGBA"), overlay),
        dtype=np.uint8,
    )

    ordered = [
        notes[block.block_id] for block in entry.blocks if block.block_id in notes
    ]
    return Result(array, ordered, base=base, overlay=np.array(overlay, dtype=np.uint8))


def render_job_image(
    job, entry, *, font_name: str | None = None, paint: np.ndarray | None = None
) -> Result:
    """Render one job image from its pristine pixels.

    The paint layer is loaded from the workspace unless the caller passes one -
    the editor holds a live copy while a stroke is being drawn, and reading the
    file back mid-stroke would drop it.
    """
    source = load_rgba(job.source_path(entry))
    if source is None:
        return Result(
            np.zeros((1, 1, 4), dtype=np.uint8),
            [Note("", False, f"could not read {job.source_path(entry)}")],
        )
    if paint is None:
        from util.imagetools.paint import load_layer

        paint = load_layer(job, entry, source.shape)
    return render_entry(source, entry, font_name=font_name, paint=paint)


def write_entry(job, entry, array: np.ndarray) -> Path:
    """Write a rendered image over the editable PNG, stashing the original first.

    Over the editable PNG on purpose: that is the file the Images tab patches
    back into the game, so rendering slots into the existing loop with no extra
    step. The stash is what makes it reversible - and what lets every later
    render start clean.
    """
    original = job.original_path(entry)
    live = job.image_path(entry)
    if not original.is_file() and live.is_file():
        original.parent.mkdir(parents=True, exist_ok=True)
        original.write_bytes(live.read_bytes())
    save_rgba(array, live)
    return live


def restore_entry(job, entry) -> bool:
    """Put the original pixels back. Returns False if there is no stash."""
    original = job.original_path(entry)
    if not original.is_file():
        return False
    live = job.image_path(entry)
    live.parent.mkdir(parents=True, exist_ok=True)
    live.write_bytes(original.read_bytes())
    return True
