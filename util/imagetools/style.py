"""What the source text looked like, measured from the pixels.

The hard part of image translation was never "what colour should the English
be" - it was that every earlier attempt asked a vision model to *guess* it. Ask
instead what the pixels say, from a box a human has confirmed, and almost all of
it comes back exact: across the 18 test regions the text colour was recovered
exactly every time, and 17 of 18 backgrounds turned out to be transparent or
flat, which erase perfectly and for free.

The one thing measurement cannot recover is the typeface, so that stays the
user's knob. Everything else is a number with a confidence beside it, and the
Style panel exists to correct the minority that are wrong rather than to enter
the majority that are right.

Two rules keep this honest:

* **Sample the background from outside the box.** A confirmed box hugs the
  glyphs, so a ring drawn inside it is all ink and reports "no background
  found" on every region.
* **Never let the detector decide what ink is.** An edge mask outlines glyphs;
  erasing an outline leaves the glyph's interior behind as a ghost. Ink is
  decided by distance from the measured background, which covers the whole
  stroke.

No PyQt in here: it runs on a worker thread and in tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from util.imagetools.geometry import Box

# Erase strategies, safest first. The first three are exact reconstructions;
# the last two are the "sacrifices" - they are offered, never chosen silently.
BG_TRANSPARENT = "transparent"    # clear to alpha 0
BG_SOLID = "solid"                # fill one sampled colour
BG_VGRADIENT = "vgradient"        # fill per-row sampled colours
BG_HGRADIENT = "hgradient"        # fill per-column sampled colours
BG_PATCH = "patch"                # clone a clean strip from above or below
BG_INPAINT = "inpaint"            # reconstruct from the surrounding artwork
BG_KEEP = "keep"                  # leave the pixels; hide them behind the type

BACKGROUNDS = (
    BG_TRANSPARENT,
    BG_SOLID,
    BG_VGRADIENT,
    BG_HGRADIENT,
    BG_PATCH,
    BG_INPAINT,
    BG_KEEP,
)

BACKGROUND_LABELS = {
    BG_TRANSPARENT: "Clear to transparent",
    BG_SOLID: "Fill with one colour",
    BG_VGRADIENT: "Fill row by row (gradient)",
    BG_HGRADIENT: "Fill column by column (gradient)",
    BG_PATCH: "Clone a clean strip",
    BG_INPAINT: "Reconstruct the artwork",
    BG_KEEP: "Leave it, draw over the top",
}

ALPHA_OPAQUE = 24                 # alpha at or below this counts as transparent
# How far two pixels' opacity may differ and still count as the same surface.
# Antialiasing moves alpha by a few counts; a translucent panel and the opaque
# glyph cut into it differ by tens.
ALPHA_TOLERANCE = 20
# A reference colour that disagrees with more of the box than this is not the
# background of the box. See ``_settled``.
UNTRUSTED_SHARE = 0.70
# Relief in the alpha channel is a single plane, so it gets its own threshold
# rather than the three-channel sum ``_local_ink`` uses for colour.
ALPHA_RELIEF = 20
ALIGNMENTS = ("left", "center", "right")

# A component must be at least this large before thickness can disqualify it.
# Dense kanji are small and locally solid; icons and artwork are big and solid.
MIN_BLOB_AREA = 300

MAX_OUTLINE = 5


@dataclass
class Style:
    """Everything the renderer needs, and where each number came from."""

    background: str = BG_KEEP
    # Which reconstruction fills the hole, when the background is BG_INPAINT.
    # Empty means the built-in fast one; see ``util.imagetools.inpaint``.
    inpaint_method: str = ""
    fill: list[int] | None = None
    row_colors: list[list[int]] = field(default_factory=list)
    column_colors: list[list[int]] = field(default_factory=list)
    donor: Box | None = None
    text_color: list[int] = field(default_factory=lambda: [255, 255, 255, 255])
    outline_color: list[int] | None = None
    outline_width: int = 0
    cap_height: int = 12
    align: str = "center"
    # The one thing pixels cannot tell us. Empty means "whatever the dialog is
    # set to"; a value here is a per-block override.
    font: str = ""
    # The typographic knobs, in Photoshop's units and with Photoshop's
    # defaults, so a number copied off that panel means the same thing here.
    # None of these is measured - measurement recovers the *size* of the
    # Japanese, and a face set 90% wide is indistinguishable from a narrower
    # face at 100%. They start neutral and stay there until somebody says
    # otherwise, which is why they are absent from ``measure``.
    scale_x: int = 100          # horizontal stretch, percent
    scale_y: int = 100          # vertical stretch, percent of the cap height
    tracking: int = 0           # letter spacing, thousandths of an em
    bold: bool = False
    italic: bool = False
    confidence: float = 0.0
    notes: list[str] = field(default_factory=list)
    # Set once the user touches the Style panel. A locked style is never
    # re-measured, so re-running measurement on a re-read image cannot quietly
    # undo a correction the user made.
    locked: bool = False

    def to_dict(self) -> dict:
        data = {
            "background": self.background,
            "fill": self.fill,
            "inpaint_method": self.inpaint_method,
            "text_color": self.text_color,
            "outline_color": self.outline_color,
            "outline_width": self.outline_width,
            "cap_height": self.cap_height,
            "align": self.align,
            "font": self.font,
            "scale_x": self.scale_x,
            "scale_y": self.scale_y,
            "tracking": self.tracking,
            "bold": self.bold,
            "italic": self.italic,
            "confidence": round(self.confidence, 3),
            "notes": list(self.notes),
            "locked": self.locked,
        }
        if self.row_colors:
            data["row_colors"] = self.row_colors
        if self.column_colors:
            data["column_colors"] = self.column_colors
        if self.donor is not None:
            data["donor"] = self.donor.as_xywh()
        return data

    @staticmethod
    def from_dict(data: dict) -> "Style":
        return Style(
            background=str(data.get("background") or BG_KEEP),
            inpaint_method=str(data.get("inpaint_method") or ""),
            fill=data.get("fill"),
            row_colors=[list(row) for row in data.get("row_colors") or []],
            column_colors=[list(col) for col in data.get("column_colors") or []],
            donor=Box.from_any(data["donor"]) if data.get("donor") else None,
            text_color=list(data.get("text_color") or [255, 255, 255, 255]),
            outline_color=data.get("outline_color"),
            outline_width=int(data.get("outline_width") or 0),
            cap_height=int(data.get("cap_height") or 12),
            align=str(data.get("align") or "center"),
            font=str(data.get("font") or ""),
            # ``or`` rather than a plain get, so a job written before these
            # existed - or one where a knob was reset to nothing - reads back as
            # the neutral value rather than as a zero-width, zero-height block.
            scale_x=int(data.get("scale_x") or 100),
            scale_y=int(data.get("scale_y") or 100),
            tracking=int(data.get("tracking") or 0),
            bold=bool(data.get("bold")),
            italic=bool(data.get("italic")),
            confidence=float(data.get("confidence") or 0.0),
            notes=[str(note) for note in data.get("notes") or []],
            locked=bool(data.get("locked")),
        )


# -------------------------------------------------------------------- colour


def median_color(pixels: np.ndarray) -> list[int]:
    if pixels.size == 0:
        return [0, 0, 0, 255]
    return [int(v) for v in np.median(pixels.reshape(-1, pixels.shape[-1]), axis=0)]


def dominant_color(pixels: np.ndarray, step: int = 12) -> list[int]:
    """Median of the most populated coarse colour bucket.

    Preferred over a plain median because a glyph's antialiased rim drags the
    median towards the background; bucketing first finds the colour the artist
    actually used and then measures only pixels of that colour.
    """
    flat = pixels.reshape(-1, pixels.shape[-1])
    if flat.shape[0] == 0:
        return [0, 0, 0, 255]
    buckets = flat[:, :3].astype(np.int32) // step
    keys = buckets[:, 0] * 100000 + buckets[:, 1] * 1000 + buckets[:, 2]
    values, counts = np.unique(keys, return_counts=True)
    winner = values[int(np.argmax(counts))]
    return median_color(flat[keys == winner])


def spread(pixels: np.ndarray) -> float:
    """Mean absolute deviation from the median across RGB, in 0-255 units."""
    flat = pixels.reshape(-1, pixels.shape[-1])
    if flat.shape[0] == 0:
        return 0.0
    rgb = flat[:, :3].astype(np.float32)
    return float(np.mean(np.abs(rgb - np.median(rgb, axis=0))))


def distance(a, b) -> int:
    return sum(abs(int(a[i]) - int(b[i])) for i in range(3))


def flat_share(pixels: np.ndarray, colour, tolerance: int = 20) -> float:
    """What fraction of *pixels* are essentially *colour*."""
    flat = pixels.reshape(-1, pixels.shape[-1])
    if flat.shape[0] == 0:
        return 0.0
    reference = np.array(colour[:3], dtype=np.int16)
    difference = np.abs(flat[:, :3].astype(np.int16) - reference).sum(axis=1)
    return float(np.mean(difference <= tolerance))


def ring(array: np.ndarray, box: Box, pad: int) -> np.ndarray:
    """Pixels in the frame just *outside* box - the local background.

    Outside, not inside: a confirmed box is drawn tight around the glyphs, so
    an inner ring samples ink and every region comes back "complex".
    """
    bounds = Box.from_size(array.shape[1], array.shape[0])
    outer = box.expand(pad, bounds)
    rows, cols = outer.slices()
    patch = array[rows, cols]
    mask = np.ones(patch.shape[:2], dtype=bool)
    inner = Box(box.x - outer.x, box.y - outer.y, box.x2 - outer.x, box.y2 - outer.y)
    ir, ic = inner.slices()
    mask[ir, ic] = False
    return patch[mask]


def side_ring(array: np.ndarray, box: Box, pad: int = 10) -> np.ndarray:
    """Pixels immediately left and right of *box*, on its own rows.

    A line of text sits on a horizontal band far more often than a vertical one,
    so its true neighbours are beside it. The full frame is not a substitute: on
    a title set in a coloured header the frame above and below the box is the
    plain page, out-votes the band by area, and reports the page colour as this
    region's background - which then erases nothing.
    """
    height, width = array.shape[:2]
    rows = slice(max(0, box.y), min(height, box.y2))
    parts = []
    left = array[rows, max(0, box.x - pad) : max(0, box.x)]
    right = array[rows, min(width, box.x2) : min(width, box.x2 + pad)]
    for part in (left, right):
        if part.size:
            parts.append(part.reshape(-1, part.shape[-1]))
    if not parts:
        return np.empty((0, 4), dtype=array.dtype)
    return np.concatenate(parts, axis=0)


# ---------------------------------------------------------------- background


def _sample_row_colors(array: np.ndarray, box: Box, pad: int = 3) -> list[list[int]]:
    """Per-row background sampled left and right of *box*.

    Returns ``[]`` unless every row is horizontally uniform - that uniformity is
    exactly what makes a per-row fill safe on a vertical gradient.
    """
    height, width = array.shape[:2]
    left_x2 = max(0, box.x - pad)
    left_x = max(0, left_x2 - 8)
    right_x = min(width, box.x2 + pad)
    right_x2 = min(width, right_x + 8)
    if (left_x2 - left_x) < 2 and (right_x2 - right_x) < 2:
        return []

    out: list[list[int]] = []
    for y in range(max(0, box.y), min(height, box.y2)):
        parts = []
        if left_x2 - left_x >= 2:
            parts.append(array[y, left_x:left_x2])
        if right_x2 - right_x >= 2:
            parts.append(array[y, right_x:right_x2])
        samples = np.concatenate(parts, axis=0)
        opaque = samples[samples[:, 3] > ALPHA_OPAQUE]
        if opaque.shape[0] < 2 or spread(opaque) > 8.0:
            return []
        out.append(median_color(opaque))
    return out


def sample_column_colors(
    crop: np.ndarray, mask: np.ndarray, known_share: float = 0.25
) -> list[list[int]] | None:
    """Background colour per column, read from the pixels the glyphs miss.

    Sampled from *inside* the box, unlike every other background probe here,
    because a heading set in a coloured header band has no clean margin to
    sample: the band is barely taller than the text. What it does have is
    background between and around the glyphs of every column, and on a
    left-to-right gradient one colour per column is the exact answer.

    Returns ``None`` when the columns disagree with themselves, which is what
    separates a gradient from artwork - and artwork must be reconstructed, not
    painted over in stripes.
    """
    height, width = mask.shape
    # Grow the mask before deciding what counts as clean. An antialiased glyph
    # fades into the background over two or three pixels, and a median that
    # includes that fade lands between the ink and the paper - which paints the
    # glyph back in, a shade off, as a legible ghost.
    covered = cv2.dilate(
        mask.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    ) > 0
    colours: list[list[int] | None] = []
    for x in range(width):
        column = crop[:, x]
        clean = column[~covered[:, x]]
        clean = clean[clean[:, 3] > ALPHA_OPAQUE]
        if clean.shape[0] < max(3, height // 8):
            colours.append(None)
            continue
        if spread(clean) > 9.0:
            return None
        colours.append(median_color(clean))

    known = [i for i, colour in enumerate(colours) if colour is not None]
    if len(known) < max(2, width * known_share):
        return None
    # No long guesses. A short gap between strokes is safely interpolated, but a
    # run of columns with nothing clean in them is not a gradient that happens
    # to be hidden - it is something else sitting in the box. Allowing it bit a
    # white rectangle out of an illustration whose edge clipped a caption's
    # corner: every column there was artwork, and every one was invented.
    longest = run = 0
    for index in range(width):
        run = 0 if colours[index] is not None else run + 1
        longest = max(longest, run)
    if longest > max(12, width // 12):
        return None
    # Columns buried under a stroke are filled in between the ones that are
    # not. Interpolating rather than demanding a clean sample everywhere is what
    # makes this usable: a gradient is smooth by definition, so the colour
    # halfway across a stroke is known even though no pixel of it is visible.
    # Requiring every column to speak for itself rejected a perfectly ordinary
    # heading because its strokes ran the full height of its box.
    out: list[list[int]] = []
    for index, colour in enumerate(colours):
        if colour is not None:
            out.append(colour)
            continue
        before = [k for k in known if k < index]
        after = [k for k in known if k > index]
        if not before:
            out.append(list(colours[after[0]]))
        elif not after:
            out.append(list(colours[before[-1]]))
        else:
            low, high = before[-1], after[0]
            weight = (index - low) / (high - low)
            out.append([
                int(round(colours[low][c] * (1 - weight) + colours[high][c] * weight))
                for c in range(4)
            ])
    return out


def find_donor(
    array: np.ndarray,
    box: Box,
    avoid: list[Box],
    reference: list[int] | None = None,
) -> Box | None:
    """A same-size strip above or below *box* that looks like its background.

    Cloning a strip is a guess, but a strip from a few pixels away is a far
    better guess than any average colour - *provided it really is the same
    background*. The first version skipped that check and cheerfully cloned the
    plain white page over a heading set on a blue gradient band: it erased
    nothing, and the Japanese title was still sitting there under the English.
    A candidate now has to match the colour measured just outside the box, and
    reconstruction is the honest answer when none does.
    """
    bounds = Box.from_size(array.shape[1], array.shape[0])
    step = max(2, box.h // 2)
    for offset in range(box.h, box.h * 4 + 1, step):
        for candidate in (
            Box(box.x, box.y - offset, box.x2, box.y2 - offset),
            Box(box.x, box.y + offset, box.x2, box.y2 + offset),
        ):
            if not bounds.contains(candidate):
                continue
            if any(candidate.intersects(other) for other in avoid):
                continue
            if reference is not None:
                rows, cols = candidate.slices()
                if distance(dominant_color(array[rows, cols]), reference) > 45:
                    continue
            return candidate
    return None


def adopt_background(
    array: np.ndarray, style: Style, box: Box, avoid: list[Box], name: str
) -> str:
    """Switch *style* to erase method *name*, sampling whatever it needs.

    Every method except "leave it" carries data measurement gathered for it -
    a fill colour, a row of colours, a donor strip. Picking a method off the
    panel used to change only the name, so a block measured as flat and then
    switched to "row by row" reached the renderer with no rows in it and came
    back as "no way to erase a 'vgradient' background": a message about an
    internal state the user never set, on a choice they had just made.

    So the sampling happens when the choice is made. Returns "" on success, or
    a sentence saying what this image will not give up - which is a real answer
    ("there is no clean margin beside this box to read a gradient from") rather
    than a report that a list was empty.
    """
    style.background = name
    if name in (BG_TRANSPARENT, BG_INPAINT, BG_KEEP):
        return ""

    rows_slice, cols_slice = box.slices()
    crop = array[rows_slice, cols_slice]

    if name == BG_SOLID:
        if style.fill:
            return ""
        outside = ring(array, box, pad=6)
        outside = outside[outside[:, 3] > ALPHA_OPAQUE] if outside.size else outside
        if outside.shape[0] < 8:
            style.fill = [255, 255, 255, 255]
            return (
                "There is no margin around this box to read a colour from, so "
                "the fill is white. Set it by hand, or use the pencil."
            )
        style.fill = dominant_color(outside)
        return ""

    if name == BG_VGRADIENT:
        if style.row_colors:
            return ""
        rows = _sample_row_colors(array, box)
        if not rows:
            return (
                "The strips either side of this box are not one colour per row, "
                "so there is no vertical gradient to copy. Try “Reconstruct the "
                "artwork”, or paint it in with the pencil."
            )
        style.row_colors = rows
        style.fill = rows[len(rows) // 2]
        return ""

    if name == BG_HGRADIENT:
        if style.column_colors:
            return ""
        columns = sample_column_colors(crop, drop_thick_shapes(_local_ink(crop)))
        if not columns:
            return (
                "The background between the glyphs disagrees with itself down "
                "the columns, which means this is artwork rather than a "
                "left-to-right gradient. Try “Reconstruct the artwork”."
            )
        style.column_colors = columns
        style.fill = columns[len(columns) // 2]
        return ""

    if name == BG_PATCH:
        if style.donor is not None:
            return ""
        style.donor = find_donor(array, box, [b for b in avoid if b != box])
        if style.donor is None:
            return (
                "There is no clean strip above or below this block to clone "
                "from. Try “Reconstruct the artwork”."
            )
        return ""

    return ""


def classify_background(
    array: np.ndarray, box: Box, avoid: list[Box] | None = None
) -> Style:
    """Decide how this region's background can be put back, and how sure we are."""
    style = Style()
    avoid = [other for other in (avoid or []) if other.as_tuple() != box.as_tuple()]

    samples = np.empty((0, 4), dtype=np.uint8)
    for factor in (3, 2, 1):
        pad = max(2, min(box.h, box.w) // factor)
        samples = ring(array, box, pad)
        if samples.shape[0] >= 24:
            break

    opaque = samples[samples[:, 3] > ALPHA_OPAQUE] if samples.size else samples
    opaque_share = (opaque.shape[0] / samples.shape[0]) if samples.shape[0] else 0.0

    if samples.shape[0] < 24:
        style.background = BG_KEEP
        style.confidence = 0.2
        style.notes.append("region touches the image edge; too little background to sample")
        return style

    if opaque_share < 0.12:
        style.background = BG_TRANSPARENT
        style.fill = [0, 0, 0, 0]
        style.confidence = 0.98
        return style

    if spread(opaque) < 7.0:
        style.background = BG_SOLID
        style.fill = dominant_color(opaque)
        style.confidence = 0.95
        return style

    # Which neighbours were sampled now starts to matter, so prefer the ones
    # beside the box over the ones around it.
    beside = side_ring(array, box)
    beside = beside[beside[:, 3] > ALPHA_OPAQUE] if beside.size else beside
    nearby = dominant_color(beside if beside.shape[0] >= 24 else opaque)

    # Spread is a mean, so a neighbouring icon clipping the corner of the frame
    # drags it over the threshold and a plainly white background reads as
    # "complex" - which then gets cloned, and the clone drags the icon in with
    # it. Asking what *share* of the frame is one colour survives an intruder.
    share = flat_share(opaque, nearby)
    if share >= 0.90:
        style.background = BG_SOLID
        style.fill = nearby
        style.confidence = 0.9 if share >= 0.97 else 0.8
        if share < 0.97:
            style.notes.append(
                f"{round((1 - share) * 100)}% of the surrounding frame is something else"
            )
        return style

    rows = _sample_row_colors(array, box)
    if rows:
        style.background = BG_VGRADIENT
        style.row_colors = rows
        style.fill = rows[len(rows) // 2]
        style.confidence = 0.75
        style.notes.append("background varies down the image but not across it")
        return style

    rows_slice, cols_slice = box.slices()
    crop = array[rows_slice, cols_slice]
    columns = sample_column_colors(crop, drop_thick_shapes(_local_ink(crop)))
    if columns:
        style.background = BG_HGRADIENT
        style.column_colors = columns
        style.fill = columns[len(columns) // 2]
        style.confidence = 0.75
        style.notes.append("background varies across the image but not down it")
        return style

    # Cloning is offered in the panel but never chosen here, and the reason is
    # worth writing down. A donor strip is only safe when it is flat - and when
    # it is flat, a solid fill does the same job without the risk. When it is
    # not flat it drags whatever it contains into the region: on the test
    # artwork it lifted the edge of a circle from 38px away and left it sitting
    # beside the translation. Reconstruction handles the same case without
    # importing anything.
    style.background = BG_INPAINT
    style.fill = nearby
    style.confidence = 0.35
    style.notes.append("text sits on artwork; the erase is a reconstruction, so check it")
    return style


# ---------------------------------------------------------------------- ink


def _unlike(crop: np.ndarray, reference: np.ndarray, tolerance: int) -> np.ndarray:
    """Pixels that differ from *reference* in colour **or** in how opaque they are.

    Alpha is in here because on a sprite it carries text as often as colour
    does. A caption cut out of a translucent panel is the panel's own colour
    everywhere - what makes it a caption is that it is 70% there and the panel
    is 100% there, and a reading that looks only at RGB cannot see it at all.
    That is not a corner case: it is how the black bar behind a name plate is
    drawn in every RPG Maker battle graphic we have.

    *reference* broadcasts against the crop, so one colour, a colour per row and
    a colour per column all come through here.
    """
    rgb = crop[:, :, :3].astype(np.int16)
    coloured = np.abs(rgb - reference[..., :3]).sum(axis=2) > tolerance
    if reference.shape[-1] < 4:
        return coloured
    opacity = np.abs(
        crop[:, :, 3].astype(np.int16) - reference[..., 3]
    ) > ALPHA_TOLERANCE
    return coloured | opacity


def _settled(selection: np.ndarray, crop: np.ndarray) -> np.ndarray:
    """Trim solid shapes out of a raw ink selection - without coming back empty.

    ``drop_thick_shapes`` exists to keep icons and artwork out of the erase, and
    it does that by deleting components that are both large and thick. Feed it a
    selection that covers most of the box and it deletes the box, because that
    is one large thick component - and the erase then reports "nothing to erase"
    and changes not a single pixel.

    Which is exactly what happened whenever the fill colour was not really this
    box's background. Switching a block to "clone a clean strip" leaves the fill
    unset; switching it to "fill with one colour" on a block measured somewhere
    else leaves a colour that matches nothing here. Either way every pixel reads
    as ink, the whole box is one blob, and the user gets a silent no-op on a
    choice they just made.

    So a selection that claims almost the whole box is treated as evidence that
    the reference colour is wrong, not that the box is solid text, and the
    polarity-aware reading is asked instead. It has no reference colour to be
    wrong about.
    """
    trimmed = drop_thick_shapes(selection)
    if int(trimmed.sum()) >= 4 and float(selection.mean()) <= UNTRUSTED_SHARE:
        return trimmed
    fallback = drop_thick_shapes(_local_ink(crop) & (crop[:, :, 3] > ALPHA_OPAQUE))
    return fallback if int(fallback.sum()) >= 4 else trimmed


def _holes(mask: np.ndarray) -> np.ndarray:
    """The enclosed empty regions of *mask* - counters, and the inside of rings."""
    solid = mask.astype(np.uint8)
    padded = cv2.copyMakeBorder(solid, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
    _, labels = cv2.connectedComponents((padded == 0).astype(np.uint8), connectivity=4)
    enclosed = (labels != 0) & (labels != labels[0, 0])
    return enclosed[1:-1, 1:-1]


def _with_counters(
    mask: np.ndarray, crop: np.ndarray, background: list[int] | None
) -> np.ndarray:
    """Put the fill back inside type that was read as an outline.

    White glyphs with a black stroke are the commonest thing in game UI, and
    they defeat a single-polarity reading: over an illustration the "lighter"
    mask holds the artwork as well as the glyphs and so loses to the "darker"
    one, which is the *stroke*. Everything downstream then measures the stroke -
    the erase covers a ring instead of a letter, and the translation comes back
    in the outline's colour. On battle3_2.png that is why "Fran" rendered solid
    black over a name that is white.

    A ring's hole is not a counter, and the pixels tell the two apart: the
    inside of an outlined glyph is one flat colour that is *not* the local
    background, while the inside of an "o" is the background, whatever the
    background happens to be doing. Only the first is filled in.
    """
    holes = _holes(mask)
    if not holes.any() or float(holes.mean()) > 0.5:
        return mask
    inside = crop[holes]
    if inside.shape[0] < 12 or spread(inside) > 14.0:
        return mask
    if background is None or distance(dominant_color(inside), background) <= 90:
        return mask
    return mask | holes


def ink_mask(crop: np.ndarray, style: Style, tolerance: int = 24) -> np.ndarray:
    """Which pixels inside the crop are source glyphs.

    Deliberately generous: an antialiased rim left behind shows up as a coloured
    ghost exactly where the old text was, which is more obvious than a slightly
    over-eager erase.
    """
    alpha = crop[:, :, 3]
    if style.background == BG_INPAINT:
        selection = _local_ink(crop) & (alpha > ALPHA_OPAQUE)
    elif style.background == BG_TRANSPARENT or not style.fill or style.fill[3] <= ALPHA_OPAQUE:
        selection = alpha > 0
    elif style.background == BG_VGRADIENT and style.row_colors:
        rows = np.array(
            [style.row_colors[min(i, len(style.row_colors) - 1)]
             for i in range(crop.shape[0])],
            dtype=np.int16,
        )[:, None, :]
        selection = _unlike(crop, rows, tolerance) & (alpha > ALPHA_OPAQUE)
    elif style.background == BG_HGRADIENT and style.column_colors:
        columns = np.array(
            [style.column_colors[min(i, len(style.column_colors) - 1)]
             for i in range(crop.shape[1])],
            dtype=np.int16,
        )[None, :, :]
        selection = _unlike(crop, columns, tolerance) & (alpha > ALPHA_OPAQUE)
    else:
        background = np.array(style.fill, dtype=np.int16)
        selection = _unlike(crop, background, tolerance) & (alpha > ALPHA_OPAQUE)
    return _with_counters(_settled(selection, crop), crop, style.fill)


def _relief(plane: np.ndarray, kernel: np.ndarray, tolerance: int):
    """``(darker, lighter)``: what stands out below and above its surroundings.

    A closing removes everything darker than its surroundings and thinner than
    the kernel; an opening removes everything lighter. Each result is the
    background as it would be *without* the marks, so the difference is the
    marks.
    """
    image = np.ascontiguousarray(plane).astype(np.uint8)
    # OpenCV hands a single-channel result back two-dimensional whatever it was
    # given, so every one of these is squared up before the channels are summed.
    without_dark = np.atleast_3d(cv2.morphologyEx(image, cv2.MORPH_CLOSE, kernel)).astype(np.int16)
    without_light = np.atleast_3d(cv2.morphologyEx(image, cv2.MORPH_OPEN, kernel)).astype(np.int16)
    value = np.atleast_3d(image).astype(np.int16)
    return (
        (without_dark - value).sum(axis=2) > tolerance,
        (value - without_light).sum(axis=2) > tolerance,
    )


def _local_ink(crop: np.ndarray, tolerance: int = 45) -> np.ndarray:
    """Glyphs picked out against a background that has no single colour.

    One colour cannot do this job on a gradient: sample the background at the
    blue end of a band and the white end of the same band reads as ink, and the
    erase takes the band with it.

    A closing removes everything darker than its surroundings and thinner than
    the kernel; an opening removes everything lighter. Each result is the
    background as it would be *without* the text, so the difference is the text.
    Both run because the polarity is not known in advance - the same picture can
    hold white glyphs on a blue band and blue glyphs on white paper.

    Each filter, though, also reports the *other* one's background wholesale:
    over white paper the opening reports the paper, all of it. The smaller of
    the two masks is therefore the text and the larger is the paper - unless
    both are small, in which case the region really does hold light and dark
    marks and they are unioned. Without that rule the two are unioned into
    something close to the whole crop, which is how an early version picked
    white paper as the text colour.

    A plain blur will not do either: on a line of text the window holds more
    text than background, so the average *is* the text and the reading inverts.
    """
    span = max(5, min(31, min(crop.shape[0], crop.shape[1]) // 2))
    if span % 2 == 0:
        span += 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (span, span))
    darker, lighter = _relief(
        np.ascontiguousarray(crop[:, :, :3]), kernel, tolerance
    )
    # The same two filters over the alpha channel. Text is often cut *into* a
    # translucent panel rather than drawn on it, and then the only thing that
    # separates the glyphs from the panel is that they are a different degree of
    # there. Skipped when the crop has one opacity throughout, which is the
    # usual case and where both masks would be empty anyway - so this cannot
    # change the reading of an ordinary opaque image.
    alpha = np.ascontiguousarray(crop[:, :, 3])
    if int(alpha.max()) - int(alpha.min()) > ALPHA_TOLERANCE:
        thinner, thicker = _relief(alpha[:, :, None], kernel, ALPHA_RELIEF)
        darker = darker | thinner
        lighter = lighter | thicker
    if darker.mean() <= 0.35 and lighter.mean() <= 0.35:
        return darker | lighter
    return darker if darker.mean() <= lighter.mean() else lighter


def drop_thick_shapes(selection: np.ndarray) -> np.ndarray:
    """Remove solid blobs - icons, badges, artwork - while keeping glyph strokes.

    Thickness alone is not enough to disqualify a component: a dense kanji is
    locally solid too, and excluding it punches a hole in the erase mask that
    reappears as a ghost. Only shapes that are both thick *and* large go.
    """
    if not selection.any():
        return selection
    solid = selection.astype(np.uint8) * 255
    count, labels, stats, _ = cv2.connectedComponentsWithStats(solid, connectivity=8)
    if count <= 1:
        return selection
    dist = cv2.distanceTransform(solid, cv2.DIST_L2, 3)
    keep = np.ones(count, dtype=bool)
    keep[0] = False
    for index in range(1, count):
        x, y, w, h, area = stats[index]
        if area < MIN_BLOB_AREA:
            continue
        component = labels[y : y + h, x : x + w] == index
        stroke = float(dist[y : y + h, x : x + w][component].max())
        if stroke > max(5.0, min(w, h) * 0.45):
            keep[index] = False
    return keep[labels]


def ink_opacity(crop: np.ndarray, mask: np.ndarray) -> int:
    """How opaque the glyphs themselves are, 0-255.

    Read as a high percentile of the ink's alpha rather than a median, because
    everything that moves a glyph's alpha moves it *down*: the antialiased rim,
    and the holes where type is cut out of a translucent panel. The pixels that
    are most there are the ones speaking for the type.

    This used to come out of ``dominant_color``, which picks a bucket by colour
    and then takes the median of all four channels inside it - so the opacity of
    the English was decided by whatever alpha happened to sit on the winning
    *colour*. On battle3_2.png that was twenty-three pixels of a black outline
    lying across a 70% band, and the whole translation was drawn at 70% because
    of them, with no control on the panel to put it back.
    """
    if not mask.any():
        return 255
    return int(np.percentile(crop[:, :, 3][mask], 90))


def _peel(mask: np.ndarray, radius: int) -> np.ndarray:
    """*mask* with *radius* pixels taken off every edge."""
    if radius <= 0 or not mask.any():
        return mask
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (radius * 2 + 1, radius * 2 + 1)
    )
    return cv2.erode(mask.astype(np.uint8), kernel) > 0


def _inner(mask: np.ndarray) -> np.ndarray:
    """As deep inside the strokes as there is room to go.

    How deep is not a constant. Peeling a fixed two pixels reads the fill colour
    of a big outlined heading correctly and destroys a 13px caption, whose
    strokes are two pixels wide to begin with - there, the "core" left over is a
    handful of junction pixels and the colour comes back as a grey average of
    the text and the paper. So peel as far as the strokes can afford: a core has
    to keep a real share of the ink to be speaking for it.
    """
    if not mask.any():
        return mask
    floor = max(12, int(mask.sum() * 0.15))
    for radius in (2, 1):
        peeled = _peel(mask, radius)
        if int(peeled.sum()) >= floor:
            return peeled
    return mask


def measure_outline(
    crop: np.ndarray, mask: np.ndarray, fill_color: list[int], style: Style
) -> tuple[list[int] | None, int]:
    """A stroke, drop shadow or glow: a second colour hugging the glyph's edge.

    Measured *inside* the ink, not outside it. An outline contrasts with the
    background by definition, so it is part of the ink mask - looking for it in
    the band beyond the mask finds the background every time, which is what the
    first version did and why it never reported one.

    All three effects are measured and redrawn the same way, as a stroke. At the
    sizes UI text is set, a soft glow and a hard outline of the same colour land
    within a pixel of each other, and pretending to tell them apart would add a
    knob that changes nothing.
    """
    if not mask.any():
        return None, 0
    inner = _inner(mask)
    rim = mask & ~inner
    # No room to peel means the strokes are one or two pixels wide, and text
    # that thin does not carry a visible stroke around it.
    if int(inner.sum()) < 12 or int(rim.sum()) < 12:
        return None, 0

    colour = dominant_color(crop[rim])
    if distance(colour, fill_color) <= 140:
        return None, 0

    background = style.fill[:3] if style.fill and style.fill[3] > ALPHA_OPAQUE else None
    if background is not None:
        if distance(colour, background) <= 60:
            # An "outline" the colour of what is behind it is not one.
            return None, 0
        # Every glyph has a rim that differs from its fill - that is what
        # antialiasing is. What separates a real stroke from a soft edge is
        # where the rim colour *sits*: a soft edge lies on the line between the
        # fill and the background, and a stroke is off it entirely.
        direct = distance(fill_color, background)
        detour = distance(fill_color, colour) + distance(colour, background)
        if detour <= direct * 1.25 + 20:
            return None, 0

    width = 1
    for radius in range(2, MAX_OUTLINE + 1):
        band = _peel(mask, radius - 1) & ~_peel(mask, radius)
        pixels = crop[band]
        if pixels.shape[0] < 12 or distance(dominant_color(pixels), colour) > 90:
            break
        width = radius
    return colour, width


def _count_bands(mask: np.ndarray, axis: int) -> int:
    """How many separate lines of text the region holds.

    Thresholds on ink density rather than looking for empty rows: tightly set
    lines leave descenders and antialiasing in the gap, and "any ink at all"
    reports a whole paragraph as one line.
    """
    profile = mask.sum(axis=axis).astype(np.float32)
    if profile.size == 0 or profile.max() <= 0:
        return 0
    threshold = profile.max() * 0.18
    bands, previous = 0, False
    for value in profile:
        filled = value > threshold
        if filled and not previous:
            bands += 1
        previous = filled
    return bands


def measure_cap_height(mask: np.ndarray, vertical: bool, lines: int = 0) -> int:
    """Typical glyph extent along the axis that sets the font size.

    Component heights alone are unreliable: on a solid background antialiasing
    joins stacked lines into one blob, which reports a paragraph as a single
    enormous glyph. Counting bands bounds the estimate to something physically
    possible.
    """
    extent = mask.shape[1] if vertical else mask.shape[0]
    if not mask.any():
        return max(5, extent // max(1, lines or 1))
    solid = mask.astype(np.uint8) * 255
    count, _, stats, _ = cv2.connectedComponentsWithStats(solid, connectivity=8)
    dims = [
        stats[i][2] if vertical else stats[i][3]
        for i in range(1, count)
        if stats[i][4] >= 10
    ]
    estimate = int(np.median(dims)) if dims else extent

    bands = max(lines, _count_bands(mask, axis=0 if vertical else 1))
    if bands > 1:
        estimate = min(estimate, max(6, int(extent / bands * 0.85)))
    return max(5, min(estimate, extent))


def detect_alignment(lines: list[Box], vertical: bool = False) -> str:
    """Read a block's alignment off its own line edges.

    A paragraph is set flush against whichever edge its lines agree on, and the
    translation should follow: re-centring a left-aligned caption is the single
    most obvious sign that text was replaced. One line agrees with nothing, so
    it stays centred in the box it already occupied.
    """
    if len(lines) < 2:
        return "center"
    if vertical:
        starts = np.array([line.y for line in lines], dtype=np.float32)
        ends = np.array([line.y2 for line in lines], dtype=np.float32)
    else:
        starts = np.array([line.x for line in lines], dtype=np.float32)
        ends = np.array([line.x2 for line in lines], dtype=np.float32)
    middles = (starts + ends) / 2.0
    spreads = {
        "left": float(starts.std()),
        "right": float(ends.std()),
        "center": float(middles.std()),
    }
    # Ties go to centre: it is the safe default when a block is too short or too
    # regular to tell the cases apart.
    return min(spreads, key=lambda key: (spreads[key], key != "center"))


def _bands(profile: np.ndarray) -> list[tuple[int, int]]:
    """Runs where the ink density is high enough to be a line of text."""
    if profile.size == 0 or profile.max() <= 0:
        return []
    threshold = profile.max() * 0.18
    runs: list[tuple[int, int]] = []
    start = None
    for index, value in enumerate(profile):
        if value > threshold and start is None:
            start = index
        elif value <= threshold and start is not None:
            runs.append((start, index))
            start = None
    if start is not None:
        runs.append((start, int(profile.size)))
    return runs


def alignment_from_ink(mask: np.ndarray, vertical: bool = False) -> str:
    """Alignment read off the ink, for a block that has no line geometry.

    Blocks arrive without line boxes more often than they should - rebuilt from
    an exchange file, or drawn by hand around text the OCR missed - and
    defaulting those to centred is visible: re-centring a left-aligned caption
    is the most obvious sign that the text was replaced.
    """
    if vertical or not mask.any():
        return "center"
    runs = _bands(mask.sum(axis=1).astype(np.float32))
    if len(runs) < 2:
        return "center"
    boxes = []
    for top, bottom in runs:
        columns = np.where(mask[top:bottom].any(axis=0))[0]
        if columns.size:
            boxes.append(Box(int(columns[0]), top, int(columns[-1]) + 1, bottom))
    return detect_alignment(boxes)


# ------------------------------------------------------------------ measure


def measure(array: np.ndarray, block, others: list[Box] | None = None) -> Style:
    """Measure one confirmed block. *others* are the sibling boxes to avoid."""
    bounds = Box.from_size(array.shape[1], array.shape[0])
    box = block.box.clamp(bounds)
    if box.w < 2 or box.h < 2:
        style = Style()
        style.notes.append("box is too small to measure")
        return style

    style = classify_background(array, box, others)
    rows, cols = box.slices()
    crop = array[rows, cols]

    mask = ink_mask(crop, style)
    if mask.sum() < 4:
        # Nothing separated from the background: either the box is off the text
        # or the contrast is below the threshold. Say so rather than reporting a
        # confident black-on-white.
        style.notes.append("almost no ink found in this box - check that it covers the text")
        style.confidence = min(style.confidence, 0.3)
        style.cap_height = max(5, (box.w if block.vertical else box.h))
        return style

    # The fill colour comes from as deep inside the strokes as there is room
    # for, so a white-on-black outlined glyph reports white rather than a grey
    # average of the two. Its opacity is measured over the whole of the ink
    # instead: colour and transparency are separate properties of the type and
    # reading both off one bucket of pixels gets the second one wrong.
    core = _inner(mask)
    style.text_color = dominant_color(crop[core])[:3] + [ink_opacity(crop, mask)]
    style.outline_color, style.outline_width = measure_outline(
        crop, mask, style.text_color, style
    )
    if style.outline_color is not None:
        # One piece of type, one opacity: a stroke drawn at a different alpha to
        # the fill it hugs shows as a seam down the middle of every glyph.
        style.outline_color = list(style.outline_color[:3]) + [style.text_color[3]]
    style.cap_height = measure_cap_height(
        mask, block.vertical, len(block.lines)
    )
    if block.lines:
        style.align = detect_alignment(
            [line.box for line in block.lines], block.vertical
        )
    else:
        # A block can reach here with no line geometry - rebuilt from an
        # exchange file, or drawn by hand around text the OCR missed. The ink
        # still knows where its lines start and end.
        style.align = alignment_from_ink(mask, block.vertical)
    return style


def ensure(array: np.ndarray, entry) -> int:
    """Measure every block on an image that has no style yet. Returns the count.

    Locked styles are skipped, which is what makes a correction survive a
    re-measure of the image around it.
    """
    boxes = [block.box for block in entry.blocks]
    measured = 0
    for block in entry.blocks:
        if block.style is not None and (block.style.locked or block.style.confidence > 0):
            continue
        block.style = measure(array, block, boxes)
        measured += 1
    return measured
