"""Relabelling a text plate: find the plate, measure the type, swap it.

Grown out of the home-screen menu tiles and reused by the other label families.

## The invariant

**An edit may only touch pixels that were part of the plate.**

A plain rectangular fill breaks it. These plates have rounded corners, torn
grunge edges and photographs pressed right against them, so a rectangle painted
over the glyph bounds squares the corners off and spills onto the photo - which
is exactly how ``shokuji.png`` and ``youbou.png`` first came out, with a black
slab visibly larger than the bar it replaced.

The fix is a clip applied at paint time, not a cleverer box. For each row inside
the box the paint runs only between the first and last pixel of the plate's own
tone *on that row*: a rounded corner has a short run and stays rounded, a row
above or below the plate has no run at all and is left alone, and grunge outside
the box is never reached because the box bounds the paint.

Things that were tried and are worse, recorded so they are not tried again:

* Row and column projections to find the plate - a bright photograph and a
  character's eyelashes both read as type.
* One connected component as an edit mask - a character tall enough to touch
  both plate edges *cuts the plate in two*: 食事 splits its plate into three
  pieces and the largest is a sliver.
* Dropping small components to ignore grunge - the flecks on a torn edge are the
  same colour as type and often the same size as a stroke of a thin kana.

## The steps

1. **Find the plate** as the largest connected blob of one flat tone, for its
   bounding box.
2. **Measure the type** inside that box, then grow until the rows and columns
   just outside are clean - antialiased tips fall under the stroke threshold and
   survive as a ghost otherwise.
3. **Paint through the per-row clip** with the modal colour inside the box.
4. **Fit the English** to the box and centre it.

Plates the blob search gets wrong are pinned by the caller as a **seed**: a
rectangle saying which blob and what tone, not how big the edit may be.
"""
from __future__ import annotations

from collections import deque


def fill_tone(img, box):
    """The plate colour, taken as the modal colour inside the erase box.

    Sampling beside the box looks tidier but lands on the photograph whenever the
    box fills the plate's height, which is most of them. Inside the box the plate
    always outnumbers the type, so the mode is the plate.
    """
    px = img.load()
    x0, y0, x1, y1 = box
    counts: dict = {}
    for y in range(y0, y1):
        for x in range(x0, x1):
            p = px[x, y]
            if p[3] < 140:
                continue
            key = (p[0] // 4, p[1] // 4, p[2] // 4)
            bucket = counts.setdefault(key, [0, [0, 0, 0, 0]])
            bucket[0] += 1
            for i in range(4):
                bucket[1][i] += p[i]
    if not counts:
        raise ValueError("no opaque pixels in the erase box")
    n, total = max(counts.values(), key=lambda v: v[0])
    return tuple(int(c / n) for c in total)


def strip_tone(img, light_text: bool):
    """The plate's own flat colour: the most common near-extreme grey in the
    lower part of the tile."""
    px = img.load()
    width, height = img.size
    counts: dict = {}
    for y in range(int(height * 0.25), height):
        for x in range(width):
            p = px[x, y]
            if p[3] < 140 or max(p[:3]) - min(p[:3]) > 14:
                continue                       # coloured -> photo, not plate
            v = (p[0] + p[1] + p[2]) // 3
            if (v < 140) if light_text else (v > 195):
                counts[v // 3 * 3] = counts.get(v // 3 * 3, 0) + 1
    if not counts:
        raise ValueError("no plate tone")
    return max(counts.items(), key=lambda kv: kv[1])[0]


def seed_tone(img, seed):
    """The plate tone read from inside a caller-supplied seed rectangle.

    A hover plate can be mid-grey, outside the range ``strip_tone`` scans, which
    is exactly the case a seed exists to resolve.
    """
    px = img.load()
    counts: dict = {}
    for y in range(seed[1], seed[3]):
        for x in range(seed[0], seed[2]):
            p = px[x, y]
            if p[3] < 140 or max(p[:3]) - min(p[:3]) > 16:
                continue
            v = (p[0] + p[1] + p[2]) // 3
            counts[v // 3 * 3] = counts.get(v // 3 * 3, 0) + 1
    if not counts:
        raise ValueError("seed rectangle holds no flat grey")
    return max(counts.items(), key=lambda kv: kv[1])[0]


def seed_colour(img, seed):
    """Modal colour of the seed rectangle - bare plate by construction.

    Preferred over the modal colour of the erase box on seeded plates: the
    dimmed "unavailable" state is a translucent wash over a black bar, and the
    box's mode is the black underneath, so filling with that undims the plate.
    The *mode* and not the mean: a seed band usually clips a few pixels of type
    or photo at its ends, and a mean drags the fill towards them.
    """
    return fill_tone(img, seed)


def strip_rect(img, tone: int, tol: int = 14, seed=None):
    """Bounding box of the plate, as the largest connected blob of its tone."""
    px = img.load()
    width, height = img.size

    def near(x, y):
        p = px[x, y]
        return (p[3] > 140 and max(p[:3]) - min(p[:3]) <= 16
                and abs((p[0] + p[1] + p[2]) // 3 - tone) <= tol)

    starts = ([(x, y) for y in range(seed[1], seed[3]) for x in range(seed[0], seed[2])]
              if seed else [(x, y) for y in range(height) for x in range(width)])
    seen = bytearray(width * height)
    best = None
    best_area = 0
    for sx, sy in starts:
        if seen[sy * width + sx] or not near(sx, sy):
            continue
        queue = deque([(sx, sy)])
        seen[sy * width + sx] = 1
        x0 = x1 = sx
        y0 = y1 = sy
        area = 0
        while queue:
            x, y = queue.popleft()
            area += 1
            x0, x1 = min(x0, x), max(x1, x)
            y0, y1 = min(y0, y), max(y1, y)
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if 0 <= nx < width and 0 <= ny < height:
                    i = ny * width + nx
                    if not seen[i] and near(nx, ny):
                        seen[i] = 1
                        queue.append((nx, ny))
        if area < 120:
            continue
        rect = (x0, y0, x1 + 1, y1 + 1)
        if seed:
            # A character tall enough to touch both plate edges cuts the plate
            # in two - 食事 splits its plate into three pieces. Take the union of
            # every piece the seed reaches, or the box lands on one fragment.
            best = rect if best is None else (min(best[0], rect[0]), min(best[1], rect[1]),
                                              max(best[2], rect[2]), max(best[3], rect[3]))
            best_area += area
        elif area > best_area:
            best_area = area
            best = rect
    if best is None or best_area < 300:
        raise ValueError("no plate blob")
    return best


def plate_box(img, light_text: bool, seed=None):
    """``(box, tone)`` - the whole plate.

    Once the paint is clipped per row to the plate's own tone, erasing the entire
    plate is both safe and simpler than measuring the type: the silhouette is
    preserved by the clip, and no antialiased tip can survive as a ghost because
    every row of the plate is repainted. Measuring the type is only needed when
    something on the plate must be *kept* - a leading symbol, an icon.
    """
    tone = seed_tone(img, seed) if seed else strip_tone(img, light_text)
    return strip_rect(img, tone, seed=seed), tone


def locate(img, light_text: bool, seed=None, delta: int = 55):
    """``(box, tone)`` - the type's extent inside the plate, grown until clean."""
    px = img.load()
    tone = seed_tone(img, seed) if seed else strip_tone(img, light_text)
    sx0, sy0, sx1, sy1 = strip_rect(img, tone, seed=seed)

    inset = 2
    sx0, sy0, sx1, sy1 = sx0 + inset, sy0 + inset, sx1 - inset, sy1 - inset

    def level(x, y):
        p = px[x, y]
        return None if p[3] <= 140 else (p[0] + p[1] + p[2]) // 3

    xs, ys = [], []
    for y in range(sy0, sy1):
        for x in range(sx0, sx1):
            v = level(x, y)
            if v is not None and abs(v - tone) > delta:
                xs.append(x)
                ys.append(y)
    if not xs:
        raise ValueError("no type inside the plate")
    box = [min(xs), min(ys), max(xs) + 1, max(ys) + 1]

    soft = max(10, delta // 3)

    def dirty(cells):
        for x, y in cells:
            v = level(x, y)
            if v is not None and abs(v - tone) > soft:
                return True
        return False

    for _ in range(24):
        grew = False
        if box[1] > sy0 and dirty((x, box[1] - 1) for x in range(box[0], box[2])):
            box[1] -= 1
            grew = True
        if box[3] < sy1 and dirty((x, box[3]) for x in range(box[0], box[2])):
            box[3] += 1
            grew = True
        if box[0] > sx0 and dirty((box[0] - 1, y) for y in range(box[1], box[3])):
            box[0] -= 1
            grew = True
        if box[2] < sx1 and dirty((box[2], y) for y in range(box[1], box[3])):
            box[2] += 1
            grew = True
        if not grew:
            break

    return (max(sx0, box[0] - 1), max(sy0, box[1] - 1),
            min(sx1, box[2] + 1), min(sy1, box[3] + 1)), tone


def erase(img, box, tone, colour, tol: int = 26):
    """Paint ``colour`` inside ``box``, clipped per row to the plate's own run.

    On each row the paint spans only from the first to the last pixel of plate
    tone on that row, so a rounded corner stays rounded and a row holding no
    plate is left untouched. Type pixels between those two ends are painted even
    though they sit far from the tone - they are what is being erased.
    """
    px = img.load()
    x0, y0, x1, y1 = box
    touched = skipped = 0
    for y in range(y0, y1):
        left = right = None
        for x in range(x0, x1):
            p = px[x, y]
            if (p[3] > 140 and max(p[:3]) - min(p[:3]) <= 20
                    and abs((p[0] + p[1] + p[2]) // 3 - tone) <= tol):
                if left is None:
                    left = x
                right = x
        if left is None:
            skipped += 1
            continue
        for x in range(left, right + 1):
            px[x, y] = colour
            touched += 1
    return touched, skipped


def relabel(img, english: str, *, light_text: bool, font: str = "times",
            seed=None, delta: int = 55, ink=None, max_ratio: float = 0.92,
            pad: int = 1, min_size: int = 9):
    """Erase the Japanese on a plate and draw ``english`` in its place.

    Returns ``(box, fill, size)``; the image is modified in place.
    """
    import ajin

    box, tone = locate(img, light_text, seed, delta)
    fill = fill_tone(img, box)
    erase(img, box, tone, fill)
    if ink is None:
        ink = (255, 255, 255, 255) if light_text else (20, 20, 20, 255)
    height = box[3] - box[1]
    size = ajin.fit_centered(img, box, english, font, ink,
                             max_size=max(min_size, int(height * max_ratio)),
                             min_size=min_size, pad=pad)
    return box, fill, size
