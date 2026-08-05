"""The manual touch-up layer: two brushes, one file per image.

Measurement gets the background right often enough to be worth automating and
not often enough to be trusted blind. A caption sitting on a hand-drawn gradient,
a glyph whose antialiased tail reaches outside every box, an inpaint that guessed
a plausible-but-wrong shape - each is a ten-second fix by hand and an afternoon's
work to detect. So the fix is by hand.

**Strokes go under the English, never over it.** The layer is composited between
the erase pass and the draw pass, which makes it a *background repair* layer:
paint can fix anything the erase left behind, and can never end up sitting on top
of the translation when the type is later moved, resized or re-fitted. That
ordering is the whole reason ``render_entry`` runs in two passes.

Kept free of Qt so the renderer, the tests and any headless run can use it. The
canvas turns mouse events into calls on ``stroke``/``wipe``; everything below
here is numpy.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

# ``render`` imports ``composite`` from here, so the PNG helpers are pulled in
# where they are used rather than at module scope - the two modules would
# otherwise import each other.

PAINT_DIRNAME = "paint"
#: The eraser's own layer. Kept apart from the paint rather than encoded into
#: it, because the two say opposite things about the same pixel and an RGBA
#: image has nowhere to put "take this away" - alpha 0 already means "I did not
#: touch this". One more small PNG beside the first is cheaper than a sentinel
#: colour everything downstream would have to know about.
CUT_DIRNAME = "cut"

# Nothing at or below this alpha counts as painted. Matches the renderer's own
# transparency threshold so a stroke the eye cannot see is not kept on disk.
PAINT_OPAQUE = 8

# Brush width in pixels, edge to edge - not a radius. A radius cannot express a
# one-pixel brush, and touching up a single stray antialiased pixel is most of
# what these are for.
MIN_SIZE = 1
MAX_SIZE = 400
DEFAULT_SIZE = 12


def layer_path(job, entry) -> Path:
    """Beside the job, mirroring the image's own relative path.

    Under ``.dazedtl/paint`` rather than next to the PNG: the workspace is what
    the Images tab patches back into the game, and a stray paint file in it
    would be copied into the game folder.
    """
    return job.work / PAINT_DIRNAME / entry.relpath


def cut_path(job, entry) -> Path:
    """Where this image's erased-to-transparent marks live."""
    return job.work / CUT_DIRNAME / entry.relpath


def blank(shape: tuple[int, ...]) -> np.ndarray:
    height, width = shape[:2]
    return np.zeros((height, width, 4), dtype=np.uint8)


def is_clear(layer: np.ndarray | None) -> bool:
    return layer is None or not bool((layer[:, :, 3] > PAINT_OPAQUE).any())


def load_layer(job, entry, shape: tuple[int, ...]) -> np.ndarray:
    """This image's strokes, or a blank layer. Never None - the caller paints."""
    return _read(layer_path(job, entry), shape)


def load_cut(job, entry, shape: tuple[int, ...]) -> np.ndarray:
    """This image's erased-to-transparent marks, or a blank layer."""
    return _read(cut_path(job, entry), shape)


def _read(path: Path, shape: tuple[int, ...]) -> np.ndarray:
    from util.imagetools.render import load_rgba

    if path.is_file():
        stored = load_rgba(path)
        if stored is not None and stored.shape[:2] == tuple(shape[:2]):
            return np.ascontiguousarray(stored)
        # A layer whose size no longer matches the image is from before the
        # picture was replaced. Silently dropping it beats pasting old strokes
        # at the wrong coordinates.
    return blank(shape)


def save_layer(job, entry, layer: np.ndarray | None) -> Path | None:
    """Write the layer, or delete the file once the last stroke is gone.

    Returns the path written, or None when nothing is on it. Erasing every
    stroke has to remove the file: leaving a fully transparent PNG behind means
    the next session loads a layer, and "is there paint on this image?" stops
    being answerable from the workspace.
    """
    return _write(layer_path(job, entry), layer)


def save_cut(job, entry, cut: np.ndarray | None) -> Path | None:
    """Write the erased-to-transparent marks, or delete the file once empty."""
    return _write(cut_path(job, entry), cut)


def _write(path: Path, layer: np.ndarray | None) -> Path | None:
    from util.imagetools.render import save_rgba

    if is_clear(layer):
        try:
            path.unlink()
        except OSError:
            pass
        return None
    save_rgba(np.ascontiguousarray(layer), path)
    return path


# ------------------------------------------------------------------ brushes


def clamp_size(size) -> int:
    return int(max(MIN_SIZE, min(MAX_SIZE, round(size))))


def _segment(layer: np.ndarray, a, b, size: int) -> np.ndarray:
    """A round-capped line *size* pixels wide, as a boolean mask over the layer.

    A one-pixel centreline dilated by a disc, rather than ``cv2.line`` at a
    thickness. Thickness is not width: OpenCV renders thickness 3 five pixels
    across and thickness 1 not at all for a click that does not move, so a brush
    built on it lies about its own footprint - which the ring drawn around the
    cursor then contradicts. A dilation by an ``S x S`` ellipse is ``S`` pixels
    across for every ``S`` including 1, and it is still one operation.

    Confined to the segment's own neighbourhood: a stroke is a few dozen pixels
    long and the image is a million, and this runs on every mouse-move event.
    """
    size = clamp_size(size)
    height, width = layer.shape[:2]
    start = (int(round(a[0])), int(round(a[1])))
    end = (int(round(b[0])), int(round(b[1])))
    reach = size // 2 + 1

    left = max(0, min(start[0], end[0]) - reach)
    right = min(width, max(start[0], end[0]) + reach + 1)
    top = max(0, min(start[1], end[1]) - reach)
    bottom = min(height, max(start[1], end[1]) + reach + 1)
    mask = np.zeros((height, width), dtype=bool)
    if right <= left or bottom <= top:
        return mask

    scratch = np.zeros((bottom - top, right - left), dtype=np.uint8)
    cv2.line(
        scratch,
        (start[0] - left, start[1] - top),
        (end[0] - left, end[1] - top),
        255, 1, lineType=cv2.LINE_8,
    )
    if size > 1:
        scratch = cv2.dilate(
            scratch, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
        )
    mask[top:bottom, left:right] = scratch > 0
    return mask


def stroke(layer: np.ndarray, a, b, size: int, rgba) -> None:
    """Paint one segment in *rgba*, *size* pixels wide. In place."""
    mask = _segment(layer, a, b, size)
    if not mask.any():
        return
    colour = list(rgba[:3]) + [rgba[3] if len(rgba) > 3 else 255]
    layer[mask] = np.array(colour, dtype=np.uint8)


def wipe(layer: np.ndarray, a, b, size: int) -> None:
    """Clear one segment back to nothing. In place.

    This removes the user's own paint, revealing whatever the renderer put
    there. It cannot touch the image itself - that is what the pencil loaded
    with a background colour is for.
    """
    mask = _segment(layer, a, b, size)
    if mask.any():
        layer[mask] = 0


def apply_cut(array: np.ndarray, cut: np.ndarray | None) -> None:
    """Take the marked pixels out of *array* altogether. In place.

    Alpha to zero rather than to any colour, which is the difference between
    this and the pencil: what is underneath the image in the game shows through,
    whatever that turns out to be. The colour channels go with it, because the
    RGB left under alpha 0 is what a later reconstruction would try to read as
    context and it should not find the old artwork there.

    Runs *before* the paint layer, so the pencil can put something back into a
    hole this made. Two brushes that can only fight each other would be a worse
    tool than one.
    """
    if array is None or cut is None or cut.shape[:2] != array.shape[:2]:
        return
    hit = cut[:, :, 3] > PAINT_OPAQUE
    if not hit.any():
        return
    array[hit] = 0


def apply_cut_segment(array: np.ndarray | None, a, b, size: int) -> None:
    """Take one brush segment straight out of *array*. In place.

    The live half of ``apply_cut``: the editor shows a cut by punching it into
    the pieces of the last render, because nothing else makes transparency
    appear under the mouse while the button is still down.
    """
    if array is None:
        return
    mask = _segment(array, a, b, size)
    if mask.any():
        array[mask] = 0


def composite(array: np.ndarray, layer: np.ndarray | None) -> None:
    """Alpha-composite the layer onto *array*. In place.

    Straight source-over, in int32. int16 is not wide enough: a fully opaque
    stroke works out 255*255 = 65025 before the divide, which wraps negative and
    turns a solid red brush into a dark blue-green one - visible only as a
    two-or-three-count colour drift, which is exactly the kind of bug that
    survives a screenshot check.

    Fully clear layers return early, which is the common case - most images are
    never painted on.
    """
    if layer is None or array is None:
        return
    if layer.shape[:2] != array.shape[:2]:
        return
    hit = layer[:, :, 3] > 0
    if not hit.any():
        return

    alpha = layer[hit, 3].astype(np.int32)[:, None]
    src = layer[hit, :3].astype(np.int32)
    dst = array[hit, :3].astype(np.int32)
    array[hit, :3] = ((src * alpha + dst * (255 - alpha)) // 255).astype(np.uint8)

    # Painting onto a transparent region has to make it opaque, or a stroke
    # over a cleared-to-transparent block is invisible in the written PNG while
    # looking perfect against the editor's dark canvas.
    flat = alpha[:, 0]
    under = array[hit, 3].astype(np.int32)
    array[hit, 3] = (flat + under * (255 - flat) // 255).clip(0, 255).astype(np.uint8)


def recomposite(display, base, overlay, layer, region=None) -> None:
    """Rebuild ``display`` from a render's parts over one rectangle. In place.

    ``base + layer + overlay``, which is the render's own order: the erased
    picture, the user's paint, then the English on top. That is what lets the
    editor show a stroke going *under* the type while it is still being drawn,
    instead of showing it over the type for a second and then correcting itself
    the moment the mouse comes up.

    ``region`` is ``(top, bottom, left, right)``. A stroke touches a few hundred
    pixels of a million, and this runs on every mouse-move event.
    """
    if display is None or base is None or display.shape != base.shape:
        return
    height, width = display.shape[:2]
    if region is None:
        top, bottom, left, right = 0, height, 0, width
    else:
        top, bottom, left, right = region
        top = max(0, top); left = max(0, left)
        bottom = min(height, bottom); right = min(width, right)
    if bottom <= top or right <= left:
        return

    view = base[top:bottom, left:right].copy()
    if layer is not None and layer.shape[:2] == base.shape[:2]:
        composite(view, layer[top:bottom, left:right])
    if overlay is not None and overlay.shape[:2] == base.shape[:2]:
        # Through PIL, not through ``composite`` above. The two disagree by a
        # count or two on partly transparent pixels - ``composite`` assumes what
        # it is painting onto is opaque, which is true of a brush stroke and not
        # of an antialiased glyph edge - and the renderer draws the text with
        # PIL. Matching it here is what makes "what the brush shows" and "what
        # the file gets" the same picture rather than nearly the same picture.
        from PIL import Image

        view[:, :] = np.array(
            Image.alpha_composite(
                Image.fromarray(view, mode="RGBA"),
                Image.fromarray(
                    np.ascontiguousarray(overlay[top:bottom, left:right]),
                    mode="RGBA",
                ),
            ),
            dtype=np.uint8,
        )
    display[top:bottom, left:right] = view


def probe(array: np.ndarray, point) -> list[int] | None:
    """The colour under a point, for the Alt-held eyedropper."""
    if array is None:
        return None
    x, y = int(round(point[0])), int(round(point[1]))
    height, width = array.shape[:2]
    if not (0 <= x < width and 0 <= y < height):
        return None
    return [int(value) for value in array[y, x][:4]]
