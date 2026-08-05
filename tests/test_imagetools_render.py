"""Measuring the source text's look, erasing it, and drawing the translation.

The fixtures are synthetic on purpose: a test that asserts "this looks right"
against a game asset tells you nothing when it fails. Here the background, the
ink colour and the glyph positions are known exactly, so a failure names the
thing that broke.

Several of these pin down bugs that were found by looking at real output and
would never have been found by reading the code:

* an erase that left the antialiased rim behind, so the old text stayed legible
  as a faint outline of itself
* a clone donor sampled from a different surface, which erased nothing
* a background probe that averaged instead of counting, so one intruding icon
  reclassified a plainly flat frame as artwork
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

# The semi-manual image workflow's dependencies are downloaded on demand
# (util/imagetools/resources.py), so a checkout that has never opened it does
# not have them. Skip rather than fail: an ImportError here would read as
# "this branch broke the suite" on a tree where nothing is wrong.
if importlib.util.find_spec("cv2") is None:
    raise unittest.SkipTest(
        "semi-manual image extras are not installed - run "
        "python -m util.imagetools.resources --default"
    )

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("IMGTL_FILES_DIR", tempfile.mkdtemp(prefix="imgtl-render-"))

from util.imagetools import job as jobmod  # noqa: E402
from util.imagetools import inpaint as inpaintmod  # noqa: E402
from util.imagetools import paint, render, style as stylemod  # noqa: E402
from util.imagetools.geometry import Box  # noqa: E402
from util.imagetools.job import ImageEntry, Job, TextBlock  # noqa: E402
from util.imagetools.ocr import Line  # noqa: E402
from util.imagetools.style import Style  # noqa: E402


# -------------------------------------------------------------------- fixtures


def canvas(width: int, height: int, colour=(255, 255, 255, 255)) -> np.ndarray:
    array = np.zeros((height, width, 4), dtype=np.uint8)
    array[:, :] = colour
    return array


def bar(array: np.ndarray, box: Box, colour) -> None:
    """A solid rectangle: an icon, a badge, a swatch. Explicitly *not* text."""
    rows, cols = box.slices()
    array[rows, cols] = colour


def glyphs(
    array: np.ndarray,
    box: Box,
    colour,
    stroke: int = 5,
    pitch: int = 14,
    soft: bool = True,
) -> None:
    """Vertical strokes across *box*: the shape of text, not a slab.

    A filled rectangle is not a stand-in for glyphs, and testing against one is
    misleading in both directions. The toolkit deliberately excludes shapes that
    are both thick *and* large, so an icon beside a label survives the erase - a
    slab fixture therefore measures as an icon, and a test built on one quietly
    asserts that text is left alone.

    ``soft`` blurs the result, because real glyphs have an antialiased edge and
    that edge is exactly where the erase went wrong.
    """
    count = max(1, (box.w + pitch - 1) // pitch)
    for index in range(count):
        centre = box.x + index * pitch + pitch // 2
        left = max(box.x, centre - stroke // 2)
        right = min(box.x2, left + stroke)
        if right <= left:
            continue
        array[box.y : box.y2, left:right] = colour
    if soft:
        region = box.expand(3, Box.from_size(array.shape[1], array.shape[0]))
        rows, cols = region.slices()
        array[rows, cols] = cv2.GaussianBlur(array[rows, cols], (3, 3), 0)


def block(box: Box, target: str = "Hello", lines=None, angle: float = 0.0) -> TextBlock:
    return TextBlock("b1", box, "元", target, angle, list(lines or []))


def entry_of(blocks: list[TextBlock], name: str = "a.png") -> ImageEntry:
    entry = ImageEntry(name)
    entry.blocks = blocks
    return entry


def has_font() -> bool:
    try:
        from util.imagetools.fonts import default_font

        return bool(default_font())
    except Exception:
        return False


needs_font = unittest.skipUnless(has_font(), "no TrueType font on this machine")


# ------------------------------------------------------------------ measuring


class BackgroundTests(unittest.TestCase):
    def test_glyphs_floating_on_transparency_are_recognised(self):
        array = canvas(120, 60, (0, 0, 0, 0))
        glyphs(array, Box(30, 20, 90, 40), (20, 20, 20, 255))
        style = stylemod.classify_background(array, Box(28, 18, 92, 42))
        self.assertEqual(style.background, stylemod.BG_TRANSPARENT)
        self.assertGreater(style.confidence, 0.9)

    def test_a_flat_field_is_filled_with_its_own_colour(self):
        array = canvas(120, 60, (12, 34, 56, 255))
        glyphs(array, Box(30, 20, 90, 40), (240, 240, 240, 255))
        style = stylemod.classify_background(array, Box(28, 18, 92, 42))
        self.assertEqual(style.background, stylemod.BG_SOLID)
        self.assertEqual(style.fill[:3], [12, 34, 56])

    def test_one_intruder_in_the_frame_does_not_make_a_flat_field_artwork(self):
        """An icon clipping the corner used to reclassify plain paper.

        Spread is a mean, so a handful of very different pixels drag it over the
        threshold; counting what share of the frame is one colour does not care.
        """
        array = canvas(240, 120, (255, 255, 255, 255))
        glyphs(array, Box(60, 50, 140, 70), (10, 10, 10, 255))
        bar(array, Box(147, 40, 240, 90), (0, 90, 200, 255))     # the intruder
        style = stylemod.classify_background(array, Box(58, 48, 142, 72))
        self.assertEqual(style.background, stylemod.BG_SOLID)
        self.assertEqual(style.fill[:3], [255, 255, 255])
        self.assertTrue(
            any("something else" in note for note in style.notes), style.notes
        )

    def test_a_left_to_right_band_is_filled_column_by_column(self):
        array = canvas(200, 60, (255, 255, 255, 255))
        for x in range(200):
            array[10:50, x] = (x, 200, 255, 255)
        glyphs(array, Box(20, 18, 180, 42), (255, 255, 255, 255), pitch=24)
        style = stylemod.classify_background(array, Box(20, 18, 180, 42))
        self.assertEqual(style.background, stylemod.BG_HGRADIENT)
        self.assertEqual(len(style.column_colors), 160)

    def test_a_clone_donor_from_a_different_surface_is_refused(self):
        """The bug: white paper was cloned over a heading on a coloured band."""
        array = canvas(200, 200, (255, 255, 255, 255))
        array[40:90, :] = (0, 120, 220, 255)
        box = Box(20, 45, 180, 85)
        self.assertIsNone(stylemod.find_donor(array, box, [], [0, 120, 220]))
        # ... while a strip of the same surface is accepted
        array[100:150, :] = (0, 120, 220, 255)
        self.assertIsNotNone(stylemod.find_donor(array, box, [], [0, 120, 220]))


class InkTests(unittest.TestCase):
    def test_text_colour_is_recovered_exactly(self):
        array = canvas(160, 80, (255, 255, 255, 255))
        glyphs(array, Box(40, 30, 120, 50), (237, 98, 43, 255))
        measured = stylemod.measure(array, block(Box(38, 28, 122, 52)))
        self.assertEqual(measured.text_color[:3], [237, 98, 43])

    def test_a_contrasting_halo_is_reported_as_an_outline(self):
        array = canvas(200, 80, (255, 255, 255, 255))
        glyphs(array, Box(40, 26, 160, 54), (0, 0, 0, 255), stroke=9, soft=False)
        glyphs(array, Box(40, 30, 160, 50), (255, 240, 0, 255), stroke=5, soft=False)
        measured = stylemod.measure(array, block(Box(38, 24, 162, 56)))
        self.assertEqual(measured.text_color[:3], [255, 240, 0])
        self.assertIsNotNone(measured.outline_color)
        self.assertEqual(measured.outline_color[:3], [0, 0, 0])
        self.assertGreaterEqual(measured.outline_width, 1)

    def test_a_halo_the_colour_of_the_background_is_not_an_outline(self):
        """Blue text fading into white paper: there is no stroke to redraw."""
        array = canvas(160, 80, (255, 255, 255, 255))
        glyphs(array, Box(40, 30, 120, 50), (20, 40, 200, 255))
        measured = stylemod.measure(array, block(Box(38, 28, 122, 52)))
        self.assertIsNone(measured.outline_color)

    def test_cap_height_is_bounded_by_the_number_of_lines(self):
        array = canvas(160, 90, (255, 255, 255, 255))
        glyphs(array, Box(30, 20, 130, 36), (0, 0, 0, 255))
        glyphs(array, Box(30, 46, 130, 62), (0, 0, 0, 255))
        measured = stylemod.measure(array, block(Box(28, 18, 132, 64)))
        self.assertLess(measured.cap_height, 30)

    def test_an_icon_sharing_the_box_is_left_out_of_the_ink(self):
        array = canvas(200, 80, (255, 255, 255, 255))
        bar(array, Box(20, 20, 60, 60), (0, 0, 0, 255))        # a solid icon
        glyphs(array, Box(80, 34, 180, 44), (0, 0, 0, 255))    # text strokes
        style = Style(background=stylemod.BG_SOLID, fill=[255, 255, 255, 255])
        mask = stylemod.ink_mask(array[18:62, 18:182], style)
        self.assertFalse(mask[:, :40].any(), "the icon should not be treated as ink")
        self.assertTrue(mask[:, 65:].any(), "the strokes should be")


class AlignmentTests(unittest.TestCase):
    def test_lines_agreeing_on_their_left_edge_read_as_left_aligned(self):
        lines = [Box(10, 0, 90, 12), Box(10, 14, 60, 26), Box(10, 28, 74, 40)]
        self.assertEqual(stylemod.detect_alignment(lines), "left")

    def test_lines_agreeing_on_their_centre_read_as_centred(self):
        lines = [Box(10, 0, 90, 12), Box(20, 14, 80, 26), Box(15, 28, 85, 40)]
        self.assertEqual(stylemod.detect_alignment(lines), "center")

    def test_a_single_line_is_centred_in_its_own_box(self):
        self.assertEqual(stylemod.detect_alignment([Box(0, 0, 10, 10)]), "center")

    def test_alignment_can_be_read_off_the_ink_with_no_line_boxes(self):
        """Blocks arrive without line geometry: rebuilt, or drawn by hand."""
        array = canvas(200, 90, (255, 255, 255, 255))
        glyphs(array, Box(20, 20, 180, 36), (0, 0, 0, 255))   # a long line
        glyphs(array, Box(20, 50, 90, 66), (0, 0, 0, 255))    # a short one, flush left
        measured = stylemod.measure(array, block(Box(18, 18, 182, 68)))
        self.assertEqual(measured.align, "left")

    def test_ink_alignment_needs_more_than_one_line_to_have_an_opinion(self):
        array = canvas(200, 60, (255, 255, 255, 255))
        glyphs(array, Box(20, 20, 90, 40), (0, 0, 0, 255))
        measured = stylemod.measure(array, block(Box(18, 18, 92, 42)))
        self.assertEqual(measured.align, "center")


class MeasureCacheTests(unittest.TestCase):
    def test_ensure_measures_once_and_leaves_a_locked_style_alone(self):
        array = canvas(160, 80, (255, 255, 255, 255))
        glyphs(array, Box(40, 30, 120, 50), (0, 0, 0, 255))
        entry = ImageEntry("a.png")
        entry.blocks = [block(Box(38, 28, 122, 52)), block(Box(10, 10, 30, 20))]
        entry.blocks[1].block_id = "b2"
        entry.blocks[1].style = Style(text_color=[1, 2, 3, 255], locked=True)

        self.assertEqual(stylemod.ensure(array, entry), 1)
        self.assertEqual(entry.blocks[1].style.text_color[:3], [1, 2, 3])
        self.assertEqual(stylemod.ensure(array, entry), 0, "should not re-measure")


# -------------------------------------------------------------------- erasing


class EraseTests(unittest.TestCase):
    def test_glyphs_on_transparency_are_cleared_to_nothing(self):
        array = canvas(120, 60, (0, 0, 0, 0))
        glyphs(array, Box(30, 20, 90, 40), (20, 20, 20, 255))
        box = Box(28, 18, 92, 42)
        style = stylemod.classify_background(array, box)
        render.erase(array, box, style)
        self.assertEqual(int(array[:, :, 3].sum()), 0)

    def test_glyphs_on_a_flat_field_are_filled_with_it(self):
        array = canvas(120, 60, (12, 34, 56, 255))
        glyphs(array, Box(30, 20, 90, 40), (240, 240, 240, 255))
        box = Box(28, 18, 92, 42)
        style = stylemod.classify_background(array, box)
        render.erase(array, box, style)
        self.assertTrue((array[:, :, :3] == [12, 34, 56]).all())

    def test_no_antialiased_rim_survives_the_erase(self):
        """The regression that left erased text legible as its own outline.

        Only the inpaint path used to grow its mask, so every exact strategy
        left the glyph's soft edge behind - a few per cent off the background,
        below any sane ink threshold, and perfectly visible on a flat field.
        """
        array = canvas(200, 100, (143, 208, 255, 255))
        glyphs(array, Box(50, 40, 150, 60), (255, 255, 255, 255))
        box = Box(46, 36, 154, 64)
        style = stylemod.classify_background(array, box)
        render.erase(array, box, style)
        rows, cols = box.slices()
        difference = np.abs(
            array[rows, cols][:, :, :3].astype(int) - np.array([143, 208, 255])
        ).sum(axis=2)
        self.assertLessEqual(int(difference.max()), 20)

    def test_an_icon_inside_the_box_survives(self):
        array = canvas(200, 80, (255, 255, 255, 255))
        bar(array, Box(20, 20, 60, 60), (0, 0, 0, 255))
        glyphs(array, Box(80, 34, 180, 44), (0, 0, 0, 255))
        box = Box(18, 18, 182, 62)
        style = stylemod.classify_background(array, box)
        render.erase(array, box, style)
        self.assertTrue((array[25:55, 25:55, :3] == 0).all(), "icon was erased")
        self.assertTrue((array[36:42, 100:160, :3] == 255).all(), "text survived")

    def test_a_background_it_cannot_reconstruct_is_reported_not_guessed(self):
        array = canvas(80, 40, (255, 255, 255, 255))
        glyphs(array, Box(10, 10, 70, 30), (0, 0, 0, 255))
        style = Style(background="something-else", fill=[255, 255, 255, 255])
        note = render.erase(array, Box(8, 8, 72, 32), style)
        self.assertFalse(note.ok)

    def test_artwork_inside_the_box_but_outside_every_word_is_spared(self):
        """A caption's corner overlapping a circle used to bite a hole in it.

        The block rectangle is only the bounds of its lines, so on an
        illustrated page it routinely contains a piece of the illustration.
        Word geometry is what tells the two apart.
        """
        array = canvas(240, 80, (255, 255, 255, 255))
        glyphs(array, Box(20, 30, 160, 50), (0, 0, 0, 255))
        cv2.circle(array, (200, 40), 26, (0, 60, 200, 255), 3)   # a thin arc
        box = Box(18, 28, 222, 52)
        words = [Box(20, 30, 90, 50), Box(95, 30, 160, 50)]
        style = stylemod.classify_background(array, box)
        limit = render.word_limit(box.expand(render.ERASE_BLEED), words)
        self.assertIsNotNone(limit, "the words should account for the block")
        render.erase(array, box, style, limit)
        arc = (array[28:52, 180:222, :3] != 255).any(axis=2)
        self.assertTrue(arc.any(), "the illustration was erased with the text")

    def test_a_box_the_words_do_not_account_for_falls_back_to_the_box(self):
        """A hand-drawn box, or one widened to catch missed text, has no words."""
        target = Box(0, 0, 200, 40)
        self.assertIsNone(render.word_limit(target, []))
        self.assertIsNone(render.word_limit(target, [Box(0, 0, 20, 10)]))

    def test_keeping_the_background_changes_no_pixels(self):
        array = canvas(80, 40, (255, 255, 255, 255))
        glyphs(array, Box(10, 10, 70, 30), (0, 0, 0, 255))
        before = array.copy()
        note = render.erase(array, Box(8, 8, 72, 32), Style(background=stylemod.BG_KEEP))
        self.assertTrue(note.ok)
        self.assertTrue((array == before).all())


# --------------------------------------------------------------------- fitting


@needs_font
class FitTests(unittest.TestCase):
    def setUp(self):
        from util.imagetools.fonts import default_font

        self.font = default_font()

    def test_text_that_fits_keeps_the_measured_size(self):
        style = Style(cap_height=20, align="center")
        layout = render.plan(
            "Go", Box(0, 0, 200, 30), style, vertical=False, font_path=self.font
        )
        self.assertTrue(layout.fits)
        self.assertFalse(layout.tight)
        self.assertGreaterEqual(layout.fitted.size, 14)

    def test_a_long_line_grows_into_space_that_is_free(self):
        style = Style(cap_height=20, align="center")
        box = Box(0, 0, 60, 26)
        room = Box(0, 0, 260, 26)
        layout = render.plan(
            "Continue the adventure", box, style,
            vertical=False, font_path=self.font, room=room,
        )
        self.assertTrue(layout.fits)
        self.assertEqual(layout.box, room)
        self.assertIn("widened", layout.note)

    def test_shrinking_below_the_original_size_is_reported(self):
        style = Style(cap_height=40, align="center")
        layout = render.plan(
            "A rather long sentence indeed", Box(0, 0, 120, 44), style,
            vertical=False, font_path=self.font,
        )
        self.assertTrue(layout.fits)
        self.assertTrue(layout.tight, "a large shrink should be flagged")
        self.assertIn("%", layout.note)

    def test_text_that_cannot_fit_at_all_says_so(self):
        style = Style(cap_height=10, align="center")
        layout = render.plan(
            "Every single word of this will never come close to fitting here",
            Box(0, 0, 24, 10), style, vertical=False, font_path=self.font,
        )
        self.assertFalse(layout.fits)
        self.assertIn("shorten", layout.note)


class GrowthTests(unittest.TestCase):
    def test_a_label_grows_only_into_matching_empty_pixels(self):
        array = canvas(300, 60, (255, 255, 255, 255))
        array[:, 220:] = (0, 0, 0, 255)                      # artwork on the right
        style = Style(background=stylemod.BG_SOLID, fill=[255, 255, 255, 255])
        box = Box(100, 20, 140, 40)
        room = render.growth_room(array, box, style, [])
        self.assertGreater(room.w, box.w, "it should have grown")
        self.assertLessEqual(room.x2, 220, "never over the artwork")
        # ... and not without limit: a label that doubles is its own problem
        self.assertLessEqual(room.w, int(box.w * render.GROWTH_LIMIT))

    def test_a_neighbouring_block_blocks_growth(self):
        array = canvas(300, 60, (255, 255, 255, 255))
        style = Style(background=stylemod.BG_SOLID, fill=[255, 255, 255, 255])
        box = Box(100, 20, 140, 40)
        room = render.growth_room(array, box, style, [box, Box(160, 20, 200, 40)])
        self.assertLessEqual(room.x2, 160)

    def test_a_rotated_strip_is_never_grown_sideways(self):
        array = canvas(300, 60, (255, 255, 255, 255))
        style = Style(background=stylemod.BG_SOLID, fill=[255, 255, 255, 255])
        box = Box(100, 20, 140, 40)
        self.assertEqual(render.growth_room(array, box, style, [], vertical=True), box)


# -------------------------------------------------------------------- rendering


@needs_font
class RenderTests(unittest.TestCase):
    def _entry(self, blocks: list[TextBlock]) -> ImageEntry:
        entry = ImageEntry("a.png")
        entry.blocks = blocks
        return entry

    def test_the_source_array_is_never_touched(self):
        array = canvas(200, 80, (255, 255, 255, 255))
        glyphs(array, Box(40, 30, 160, 50), (0, 0, 0, 255))
        before = array.copy()
        render.render_entry(array, self._entry([block(Box(38, 28, 162, 52))]))
        self.assertTrue((array == before).all())

    def test_a_block_marked_skip_is_left_exactly_as_it_was(self):
        array = canvas(200, 80, (255, 255, 255, 255))
        glyphs(array, Box(40, 30, 160, 50), (0, 0, 0, 255))
        item = block(Box(38, 28, 162, 52))
        item.skip = True
        result = render.render_entry(array, self._entry([item]))
        self.assertTrue((result.array == array).all())
        self.assertTrue(all(note.ok for note in result.notes))

    def test_an_untranslated_block_is_left_alone_rather_than_emptied(self):
        """Erasing without drawing would leave a hole where the Japanese was."""
        array = canvas(200, 80, (255, 255, 255, 255))
        glyphs(array, Box(40, 30, 160, 50), (0, 0, 0, 255))
        result = render.render_entry(
            array, self._entry([block(Box(38, 28, 162, 52), target="")])
        )
        self.assertTrue((result.array == array).all())

    def test_the_translation_lands_in_the_block_and_the_old_text_goes(self):
        array = canvas(240, 80, (255, 255, 255, 255))
        glyphs(array, Box(40, 30, 200, 50), (0, 0, 0, 255))
        item = block(Box(38, 28, 202, 52), target="Hello")
        result = render.render_entry(array, self._entry([item]))
        self.assertTrue(all(note.ok for note in result.notes), result.notes)
        rows, cols = item.box.slices()
        painted = result.array[rows, cols]
        ink = (painted[:, :, :3] < 128).all(axis=2)
        self.assertTrue(ink.any(), "nothing was drawn")
        # The source strokes covered a quarter of the box on every row; five
        # letters set once must cover distinctly less than that. The margin is
        # not what it once was because the type now stands at the cap height it
        # was measured at rather than a third short of it.
        self.assertLess(ink.mean(), 0.20)

    def test_the_measured_style_is_kept_on_the_block(self):
        array = canvas(200, 80, (255, 255, 255, 255))
        glyphs(array, Box(40, 30, 160, 50), (0, 0, 0, 255))
        item = block(Box(38, 28, 162, 52))
        render.render_entry(array, self._entry([item]))
        self.assertIsNotNone(item.style)
        self.assertEqual(item.style.background, stylemod.BG_SOLID)

    def test_a_rotated_block_is_drawn_down_the_strip(self):
        array = canvas(80, 240, (255, 255, 255, 255))
        glyphs(array, Box(30, 40, 50, 200), (0, 0, 0, 255), pitch=40)
        item = block(Box(28, 38, 52, 202), target="Hello", angle=-90.0)
        result = render.render_entry(array, self._entry([item]))
        self.assertTrue(all(note.ok for note in result.notes), result.notes)
        rows, cols = item.box.slices()
        ink = (result.array[rows, cols][:, :, :3] < 128).all(axis=2)
        used = np.argwhere(ink)
        self.assertTrue(used.size, "nothing was drawn")
        # Drawn along the strip, so it runs further down than across.
        self.assertGreater(np.ptp(used[:, 0]), np.ptp(used[:, 1]))


# ------------------------------------------------------------------ the files


@needs_font
class WriteTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="imgtl-write-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.job = Job(self.root)
        self.entry = ImageEntry("a.png")
        self.entry.blocks = [block(Box(38, 28, 202, 52), target="Hello")]
        self.job.images = [self.entry]

        array = canvas(240, 80, (255, 255, 255, 255))
        glyphs(array, Box(40, 30, 200, 50), (0, 0, 0, 255))
        render.save_rgba(array, self.root / "a.png")

    def test_the_original_is_stashed_before_the_first_write(self):
        original = (self.root / "a.png").read_bytes()
        result = render.render_job_image(self.job, self.entry)
        render.write_entry(self.job, self.entry, result.array)
        self.assertEqual(self.job.original_path(self.entry).read_bytes(), original)
        self.assertNotEqual((self.root / "a.png").read_bytes(), original)

    def test_rendering_twice_gives_the_same_file(self):
        """Rendering reads the stash, so a second pass cannot compound."""
        result = render.render_job_image(self.job, self.entry)
        render.write_entry(self.job, self.entry, result.array)
        first = (self.root / "a.png").read_bytes()
        result = render.render_job_image(self.job, self.entry)
        render.write_entry(self.job, self.entry, result.array)
        self.assertEqual((self.root / "a.png").read_bytes(), first)

    def test_restore_puts_the_original_back(self):
        original = (self.root / "a.png").read_bytes()
        result = render.render_job_image(self.job, self.entry)
        render.write_entry(self.job, self.entry, result.array)
        self.assertTrue(render.restore_entry(self.job, self.entry))
        self.assertEqual((self.root / "a.png").read_bytes(), original)

    def test_restore_without_a_stash_says_no(self):
        self.assertFalse(render.restore_entry(self.job, self.entry))

    def test_a_non_ascii_filename_round_trips(self):
        """cv2.imwrite fails silently on these; imencode + tofile does not."""
        target = self.root / "カットイン_図解.png"
        array = canvas(20, 10, (1, 2, 3, 255))
        render.save_rgba(array, target)
        self.assertTrue(target.is_file())
        back = render.load_rgba(target)
        self.assertIsNotNone(back)
        self.assertEqual(list(back[0, 0]), [1, 2, 3, 255])


class StylePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="imgtl-job-"))
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_a_style_survives_a_save_and_load(self):
        job = Job(self.root)
        entry = ImageEntry("a.png")
        item = block(Box(0, 0, 10, 10), lines=[Line("x", Box(0, 0, 10, 5))])
        item.style = Style(
            background=stylemod.BG_HGRADIENT,
            column_colors=[[1, 2, 3, 255], [4, 5, 6, 255]],
            text_color=[9, 9, 9, 255],
            outline_color=[0, 0, 0, 255],
            outline_width=2,
            cap_height=17,
            align="right",
            font="C:/fonts/x.ttf",
            locked=True,
        )
        entry.blocks = [item]
        job.images = [entry]
        job.save()

        back = Job.load(self.root).images[0].blocks[0].style
        self.assertEqual(back.background, stylemod.BG_HGRADIENT)
        self.assertEqual(back.column_colors, [[1, 2, 3, 255], [4, 5, 6, 255]])
        self.assertEqual(back.outline_width, 2)
        self.assertEqual(back.cap_height, 17)
        self.assertEqual(back.align, "right")
        self.assertEqual(back.font, "C:/fonts/x.ttf")
        self.assertTrue(back.locked)

    def test_a_block_with_no_style_stays_that_way(self):
        job = Job(self.root)
        entry = ImageEntry("a.png")
        entry.blocks = [block(Box(0, 0, 10, 10))]
        job.images = [entry]
        job.save()
        self.assertIsNone(Job.load(self.root).images[0].blocks[0].style)

    def test_the_typographic_knobs_survive_a_save_and_load(self):
        job = Job(self.root)
        entry = ImageEntry("a.png")
        item = block(Box(0, 0, 10, 10))
        item.style = Style(
            scale_x=140, scale_y=80, tracking=-25, bold=True, italic=True
        )
        entry.blocks = [item]
        job.images = [entry]
        job.save()
        back = Job.load(self.root).images[0].blocks[0].style
        self.assertEqual(
            (back.scale_x, back.scale_y, back.tracking, back.bold, back.italic),
            (140, 80, -25, True, True),
        )

    def test_a_job_written_before_they_existed_reads_back_neutral(self):
        """Absent means 100%, not 0% - or every old job renders at no size."""
        back = Style.from_dict({"background": stylemod.BG_KEEP})
        self.assertEqual((back.scale_x, back.scale_y, back.tracking), (100, 100, 0))
        self.assertFalse(back.bold or back.italic)


# ---------------------------------------------------------------------- paint


def magenta(array: np.ndarray) -> int:
    return int(
        (
            (array[:, :, 0] == 255) & (array[:, :, 1] == 0) & (array[:, :, 2] == 255)
        ).sum()
    )


class BrushTests(unittest.TestCase):
    def setUp(self):
        self.layer = paint.blank((60, 120, 4))

    def test_a_stroke_paints_the_exact_colour(self):
        """Not "about right". The first version composited in int16, and
        255*255 wrapped negative - a solid red brush came out three counts off,
        which no screenshot would catch."""
        base = canvas(120, 60, (200, 200, 200, 255))
        paint.stroke(self.layer, (10, 30), (100, 30), 5, [255, 0, 255, 255])
        paint.composite(base, self.layer)
        self.assertGreater(magenta(base), 0)
        painted = base[self.layer[:, :, 3] > 0]
        self.assertTrue((painted[:, :3] == [255, 0, 255]).all())

    def test_a_drag_leaves_a_continuous_line(self):
        """Circles stamped at each mouse position leave a dotted trail as soon
        as the pointer moves faster than the event rate."""
        paint.stroke(self.layer, (10, 30), (100, 30), 3, [0, 0, 0, 255])
        row = self.layer[30, 10:101, 3]
        self.assertTrue((row > 0).all())

    def test_a_click_without_a_drag_still_paints(self):
        paint.stroke(self.layer, (50, 30), (50, 30), 6, [0, 0, 0, 255])
        self.assertGreater(int((self.layer[:, :, 3] > 0).sum()), 0)

    def test_wipe_removes_only_what_it_covers(self):
        paint.stroke(self.layer, (10, 30), (100, 30), 4, [0, 0, 0, 255])
        before = int((self.layer[:, :, 3] > 0).sum())
        paint.wipe(self.layer, (10, 30), (40, 30), 5)
        after = int((self.layer[:, :, 3] > 0).sum())
        self.assertLess(after, before)
        self.assertGreater(after, 0)

    def test_painting_over_transparency_makes_it_opaque(self):
        """A stroke over a cleared-to-transparent block looks perfect against
        the editor's dark canvas and is invisible in the written PNG."""
        clear = canvas(120, 60, (0, 0, 0, 0))
        paint.stroke(self.layer, (50, 30), (50, 30), 5, [10, 20, 30, 255])
        paint.composite(clear, self.layer)
        self.assertEqual(list(clear[30, 50]), [10, 20, 30, 255])

    def test_composite_ignores_a_layer_of_the_wrong_size(self):
        base = canvas(40, 40)
        before = base.copy()
        paint.composite(base, paint.blank((80, 80, 4)))
        self.assertTrue((base == before).all())

    def test_probe_reads_the_pixel_under_the_point(self):
        base = canvas(20, 20, (1, 2, 3, 255))
        base[7, 9] = (250, 240, 230, 255)
        self.assertEqual(paint.probe(base, (9, 7)), [250, 240, 230, 255])
        self.assertIsNone(paint.probe(base, (99, 7)))


class PaintFileTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="imgtl-paint-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.job = Job(self.root)
        self.entry = ImageEntry("a.png")
        self.job.images = [self.entry]

    def test_a_layer_round_trips(self):
        layer = paint.blank((40, 60, 4))
        paint.stroke(layer, (5, 20), (55, 20), 3, [7, 8, 9, 255])
        self.assertIsNotNone(paint.save_layer(self.job, self.entry, layer))
        back = paint.load_layer(self.job, self.entry, (40, 60, 4))
        self.assertTrue((back == layer).all())

    def test_an_empty_layer_is_not_written(self):
        """Leaving a fully transparent PNG behind means the next session loads
        a layer, and "is this image painted on?" stops being answerable."""
        self.assertIsNone(paint.save_layer(self.job, self.entry, paint.blank((10, 10, 4))))
        self.assertFalse(paint.layer_path(self.job, self.entry).exists())

    def test_erasing_the_last_stroke_deletes_the_file(self):
        layer = paint.blank((40, 60, 4))
        paint.stroke(layer, (5, 20), (55, 20), 3, [7, 8, 9, 255])
        paint.save_layer(self.job, self.entry, layer)
        paint.wipe(layer, (0, 20), (60, 20), 30)
        self.assertIsNone(paint.save_layer(self.job, self.entry, layer))
        self.assertFalse(paint.layer_path(self.job, self.entry).exists())

    def test_a_layer_from_a_different_sized_image_is_dropped(self):
        layer = paint.blank((40, 60, 4))
        paint.stroke(layer, (5, 20), (55, 20), 3, [7, 8, 9, 255])
        paint.save_layer(self.job, self.entry, layer)
        back = paint.load_layer(self.job, self.entry, (80, 120, 4))
        self.assertEqual(back.shape, (80, 120, 4))
        self.assertTrue(paint.is_clear(back))

    def test_the_layer_lives_beside_the_job_not_beside_the_image(self):
        """The workspace is what the Images tab patches into the game; a stray
        paint file in it would be copied across with the real assets."""
        path = paint.layer_path(self.job, self.entry)
        self.assertEqual(path.parent.name, paint.PAINT_DIRNAME)
        self.assertIn(jobmod.JOB_DIRNAME, path.parts)


class PaintOrderTests(unittest.TestCase):
    """Where a stroke lands in the pipeline, which is the whole design."""

    def setUp(self):
        self.array = canvas(240, 80, (255, 255, 255, 255))
        glyphs(self.array, Box(40, 30, 200, 50), (0, 0, 0, 255))
        self.entry = ImageEntry("a.png")
        self.entry.blocks = [block(Box(38, 28, 202, 52), target="Hello")]
        # The fixture is only useful if the block actually renders.
        self.assertTrue(render.render_entry(self.array, self.entry).notes[0].ok)

    def test_paint_covers_what_the_erase_left_behind(self):
        layer = paint.blank(self.array.shape)
        paint.stroke(layer, (40, 45), (238, 45), 12, [255, 0, 255, 255])
        result = render.render_entry(self.array, self.entry, paint=layer)
        self.assertGreater(magenta(result.array), 0)

    def test_the_translation_is_drawn_on_top_of_the_paint(self):
        """The decided ordering: a stroke repairs background and can never end
        up sitting on the English when the fit ladder moves the type."""
        layer = paint.blank(self.array.shape)
        paint.stroke(layer, (0, 45), (240, 45), 40, [255, 0, 255, 255])
        result = render.render_entry(self.array, self.entry, paint=layer)
        # The glyphs the renderer drew are still their own colour, not magenta.
        drawn = result.array[(layer[:, :, 3] > 0)]
        overpainted = ((drawn[:, 0] == 255) & (drawn[:, 1] == 0) & (drawn[:, 2] == 255))
        self.assertLess(
            overpainted.mean(), 1.0,
            "the text was buried under the paint instead of drawn over it",
        )
        self.assertGreater((~overpainted).sum(), 0)

    def test_no_paint_renders_exactly_as_before(self):
        plain = render.render_entry(self.array, self.entry)
        with_empty = render.render_entry(
            self.array, self.entry, paint=paint.blank(self.array.shape)
        )
        self.assertTrue((plain.array == with_empty.array).all())

    def test_a_cut_takes_the_picture_out_altogether(self):
        """Not a colour over it - alpha to nothing, the way an eraser works."""
        cut = paint.blank(self.array.shape)
        paint.stroke(cut, (10, 10), (230, 10), 8, [255, 255, 255, 255])
        result = render.render_entry(self.array, self.entry, cut=cut)
        marked = cut[:, :, 3] > 0
        self.assertGreater(int(marked.sum()), 0)
        self.assertEqual(int(result.array[marked][:, 3].max()), 0)

    def test_paint_goes_back_over_a_cut(self):
        """The two brushes have to be usable together, not against each other."""
        cut = paint.blank(self.array.shape)
        layer = paint.blank(self.array.shape)
        paint.stroke(cut, (10, 10), (230, 10), 12, [255, 255, 255, 255])
        paint.stroke(layer, (10, 10), (230, 10), 6, [255, 0, 255, 255])
        result = render.render_entry(self.array, self.entry, paint=layer, cut=cut)
        self.assertGreater(magenta(result.array), 0)

    def test_no_cut_renders_exactly_as_before(self):
        plain = render.render_entry(self.array, self.entry)
        with_empty = render.render_entry(
            self.array, self.entry, cut=paint.blank(self.array.shape)
        )
        self.assertTrue((plain.array == with_empty.array).all())

    def test_notes_stay_in_reading_order(self):
        """Erase and draw run as separate passes now; the notes must not come
        back as "everything that failed, then everything that worked"."""
        entry = ImageEntry("a.png")
        entry.blocks = [
            block(Box(38, 28, 202, 52), target="Hello"),
            TextBlock("b2", Box(0, 0, 1, 1), "元", "Too small", 0.0, []),
            TextBlock("b3", Box(38, 28, 202, 52), "元", "", 0.0, []),
        ]
        result = render.render_entry(self.array, entry)
        self.assertEqual(
            [note.block_id for note in result.notes], ["b1", "b2", "b3"]
        )


class PaintJobTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="imgtl-paintjob-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.job = Job(self.root)
        self.entry = ImageEntry("a.png")
        self.entry.blocks = [block(Box(38, 28, 202, 52), target="Hello")]
        self.job.images = [self.entry]
        array = canvas(240, 80, (255, 255, 255, 255))
        glyphs(array, Box(40, 30, 200, 50), (0, 0, 0, 255))
        render.save_rgba(array, self.root / "a.png")

    def test_render_job_image_picks_the_layer_up_off_disk(self):
        layer = paint.blank((80, 240, 4))
        paint.stroke(layer, (10, 70), (230, 70), 6, [255, 0, 255, 255])
        paint.save_layer(self.job, self.entry, layer)
        result = render.render_job_image(self.job, self.entry)
        self.assertGreater(magenta(result.array), 0)

    def test_a_caller_holding_a_live_layer_wins_over_the_file(self):
        """The editor holds a layer while a stroke is in progress; reading the
        file back mid-stroke would drop it."""
        paint.save_layer(self.job, self.entry, paint.blank((80, 240, 4)))
        live = paint.blank((80, 240, 4))
        paint.stroke(live, (10, 70), (230, 70), 6, [255, 0, 255, 255])
        result = render.render_job_image(self.job, self.entry, paint=live)
        self.assertGreater(magenta(result.array), 0)

    def test_painting_does_not_break_re_render(self):
        layer = paint.blank((80, 240, 4))
        paint.stroke(layer, (10, 70), (230, 70), 6, [255, 0, 255, 255])
        paint.save_layer(self.job, self.entry, layer)
        render.write_entry(
            self.job, self.entry, render.render_job_image(self.job, self.entry).array
        )
        first = (self.root / "a.png").read_bytes()
        render.write_entry(
            self.job, self.entry, render.render_job_image(self.job, self.entry).array
        )
        self.assertEqual((self.root / "a.png").read_bytes(), first)


@needs_font
class SizingTests(unittest.TestCase):
    """Type reaching the edges of its block, which for a long time it did not.

    The height budget used to be the font's nominal line box - about 1.15 times
    the point size - while what lands on the image is the ink, which for a line
    of capitals is nearer 0.7 of it. So the ladder refused every size that would
    actually have fitted, the type stopped a third of the box short of the
    bottom, and raising "Font size" past that point changed nothing at all.
    """

    def setUp(self):
        from util.imagetools.fonts import default_font

        self.font = default_font()

    def test_a_size_is_the_height_the_capitals_really_stand(self):
        from PIL import ImageFont

        from util.imagetools.fonts import size_for_cap

        for wanted in (12, 20, 34, 60):
            size = size_for_cap(self.font, wanted)
            _, top, _, bottom = ImageFont.truetype(self.font, size).getbbox("H")
            self.assertLessEqual(bottom - top, wanted)
            # And within a pixel of it, not merely under it.
            self.assertGreaterEqual(bottom - top, wanted - 2)

    def test_one_line_uses_nearly_all_the_height_it_is_given(self):
        from util.imagetools.fonts import fit_text

        fitted = fit_text(
            "Attack", max_width=400, max_height=40,
            font_path=self.font, target_cap_height=40,
        )
        self.assertTrue(fitted.fits)
        self.assertGreaterEqual(fitted.height, 34)
        self.assertLessEqual(fitted.height, 40)

    def test_asking_for_more_gives_more_until_the_box_says_no(self):
        from util.imagetools.fonts import fit_text

        def at(cap):
            return fit_text(
                "Go", max_width=600, max_height=200,
                font_path=self.font, target_cap_height=cap,
            ).size

        self.assertLess(at(20), at(40))
        self.assertLess(at(40), at(80))

    def test_the_stroke_is_paid_for_out_of_the_same_budget(self):
        from util.imagetools.fonts import fit_text

        plain = fit_text(
            "Attack", max_width=200, max_height=30,
            font_path=self.font, target_cap_height=30,
        )
        heavy = fit_text(
            "Attack", max_width=200, max_height=30,
            font_path=self.font, target_cap_height=30, stroke_width=5,
        )
        self.assertTrue(heavy.fits)
        self.assertLess(heavy.size, plain.size)
        self.assertLessEqual(heavy.height, 30)

    def test_the_drawn_ink_lands_inside_the_block(self):
        """The budget is only worth anything if the render honours it."""
        array = canvas(240, 80, (255, 255, 255, 255))
        glyphs(array, Box(40, 30, 200, 50), (0, 0, 0, 255))
        item = block(Box(38, 28, 202, 52), target="Attack")
        item.style = stylemod.measure(array, item, [item.box])
        item.style.cap_height = 24            # taller than the 24px box allows
        item.style.locked = True
        result = render.render_entry(array, entry_of([item]))
        self.assertTrue(all(note.ok for note in result.notes), result.notes)
        changed = (result.array != array).any(axis=2)
        rows = np.nonzero(changed.any(axis=1))[0]
        self.assertTrue(rows.size, "nothing was drawn")
        self.assertGreaterEqual(rows.min(), item.box.y - render.ERASE_BLEED)
        self.assertLessEqual(rows.max(), item.box.y2 + render.ERASE_BLEED)


@needs_font
class TypographyTests(unittest.TestCase):
    """Tracking, width and height, in Photoshop's units and with its defaults.

    None of these is measured off the image - measurement recovers the *size*
    of the Japanese, and a face set 90% wide is indistinguishable from a
    narrower face at 100%. They start neutral, and what matters is that neutral
    really is neutral: a job written before they existed has to render exactly
    as it did, or every image in it comes back changed.
    """

    def setUp(self):
        from util.imagetools.fonts import default_font

        self.font = default_font()

    def _fit(self, **extra):
        from util.imagetools.fonts import fit_text

        return fit_text(
            "Restore", max_width=400, max_height=60, font_path=self.font,
            target_cap_height=30, **extra,
        )

    def test_the_defaults_change_nothing(self):
        plain = self._fit()
        neutral = self._fit(tracking=0, width_scale=100)
        self.assertEqual((plain.size, plain.width, plain.height),
                         (neutral.size, neutral.width, neutral.height))
        self.assertEqual(neutral.step, 0.0)

    def test_tracking_widens_the_line_and_narrowing_it_pulls_it_in(self):
        loose = self._fit(tracking=200)
        plain = self._fit()
        tight = self._fit(tracking=-50)
        self.assertGreater(loose.width, plain.width)
        self.assertLess(tight.width, plain.width)

    def test_tracking_is_relative_to_the_type_not_absolute(self):
        """So a setting survives the fit ladder dropping the size."""
        from util.imagetools.fonts import tracking_px

        self.assertAlmostEqual(tracking_px(20, 100), 2.0)
        self.assertAlmostEqual(tracking_px(40, 100), 4.0)

    def test_a_width_scale_is_reported_in_the_fitted_width(self):
        plain = self._fit()
        wide = self._fit(width_scale=150)
        self.assertGreater(wide.width, plain.width)
        self.assertEqual(wide.height, plain.height, "width scaling moved the height")

    def test_a_narrow_scale_fits_text_that_would_not_have(self):
        """The reason it exists: a long translation in a plate that cannot grow."""
        from util.imagetools.fonts import fit_text

        wide = fit_text(
            "Restores a moderate amount of HP", max_width=150, max_height=26,
            font_path=self.font, target_cap_height=18, allow_wrap=False,
            min_size=14,
        )
        narrow = fit_text(
            "Restores a moderate amount of HP", max_width=150, max_height=26,
            font_path=self.font, target_cap_height=18, allow_wrap=False,
            min_size=14, width_scale=60,
        )
        self.assertFalse(wide.fits)
        self.assertTrue(narrow.fits)

    def test_the_drawn_tile_really_is_stretched(self):
        """Not merely budgeted for - the pixels have to move too."""
        def ink(scale):
            fitted = self._fit(width_scale=scale)
            layout = render.Layout(fitted, Box(0, 0, 400, 60), "left", True)
            tile = np.array(render._tile((400, 60), layout, Style(cap_height=30)))
            columns = np.nonzero((tile[:, :, 3] > 0).any(axis=0))[0]
            return int(columns.max() - columns.min())

        self.assertGreater(ink(150), int(ink(100) * 1.3))
        self.assertLess(ink(60), int(ink(100) * 0.8))

    def test_height_is_applied_through_the_size_not_by_stretching(self):
        """A taller cap means real outlines, not a resampled bitmap."""
        tall = render.plan(
            "Restore", Box(0, 0, 400, 90),
            Style(cap_height=20, scale_y=200), vertical=False, font_path=self.font,
        )
        plain = render.plan(
            "Restore", Box(0, 0, 400, 90),
            Style(cap_height=20), vertical=False, font_path=self.font,
        )
        self.assertGreater(tall.fitted.size, plain.fitted.size)
        self.assertEqual(tall.fitted.width_scale, 100)


class VariantTests(unittest.TestCase):
    """Bold and Italic are files, not a switch."""

    def setUp(self):
        from util.imagetools import fonts

        self.fonts = fonts

    def test_a_family_with_a_bold_cut_resolves_to_a_different_file(self):
        regular = self.fonts.resolve_font(None)
        if not self.fonts.has_variant(regular, bold=True):
            self.skipTest(f"no bold cut of {regular} on this machine")
        bold = self.fonts.variant(regular, bold=True)
        self.assertNotEqual(Path(bold), Path(regular))
        self.assertIn("bold", self.fonts.font_family_style(bold)[1].lower())

    def test_asking_for_a_cut_that_does_not_exist_gives_the_face_back(self):
        regular = self.fonts.resolve_font(None)
        with patch.object(self.fonts, "_family_index", lambda: {}):
            self.assertEqual(self.fonts.variant(regular, bold=True), regular)
            self.assertFalse(self.fonts.has_variant(regular, bold=True))

    def test_semibold_is_not_bold(self):
        """Matched by word, not by substring - they are different weights."""
        self.assertEqual(self.fonts._flags("Semibold"), (False, False))
        self.assertEqual(self.fonts._flags("Bold"), (True, False))
        self.assertEqual(self.fonts._flags("Bold Italic"), (True, True))
        self.assertEqual(self.fonts._flags("Oblique"), (False, True))
        self.assertEqual(self.fonts._flags(""), (False, False))

    def test_the_renderer_asks_for_the_cut_the_style_names(self):
        seen = []
        entry = ImageEntry("a.png", 0)
        entry.blocks = [TextBlock("b1", Box(2, 2, 118, 40), "元", "Hi")]
        entry.blocks[0].style = Style(
            background=stylemod.BG_KEEP, cap_height=18, bold=True, italic=True
        )
        source = canvas(120, 44, (255, 255, 255, 255))
        with patch.object(render, "variant", lambda path, b, i: seen.append((b, i)) or path):
            render.render_entry(source, entry)
        self.assertEqual(seen, [(True, True)])


class StrokeTests(unittest.TestCase):
    """The stroke grows outwards only.

    PIL's own ``stroke_width`` dilates the whole glyph, so past about half a
    counter's width the hole in an "o" or a "B" meets itself in the middle and
    fills solid. It looked like the letter losing its shape, and it got worse
    exactly as the setting got more useful.
    """

    def setUp(self):
        from util.imagetools.fonts import default_font, fit_text

        self.font = default_font()
        self.fit = fit_text

    def _tile(self, width: int, text: str = "oo", cap: int = 52, **extra):
        fitted = self.fit(
            text, max_width=300, max_height=90,
            font_path=self.font, target_cap_height=cap, stroke_width=width,
            **extra,
        )
        layout = render.Layout(fitted, Box(0, 0, 300, 90), "center", True)
        style = Style(
            text_color=[255, 255, 255, 255],
            outline_color=[0, 0, 0, 255],
            outline_width=width,
            cap_height=cap,
        )
        return np.array(render._tile((300, 90), layout, style))

    def _counter_pixels(self, tile):
        """Pixels enclosed by ink that the stroke has not reached."""
        opaque = (tile[:, :, 3] > 0).astype(np.uint8)
        padded = cv2.copyMakeBorder(opaque, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
        count, labels = cv2.connectedComponents(
            (padded == 0).astype(np.uint8), connectivity=4
        )
        inside = labels[1:-1, 1:-1]
        return int(((inside != labels[0, 0]) & (inside != 0)).sum())

    def test_a_heavy_stroke_leaves_the_counters_open(self):
        for width in (1, 3, 5):
            with self.subTest(width=width):
                self.assertGreater(
                    self._counter_pixels(self._tile(width)), 20,
                    f"the counters of “oo” closed up at stroke {width}",
                )

    def test_the_stroke_still_surrounds_the_glyphs(self):
        plain = self._tile(0)
        heavy = self._tile(5)
        self.assertGreater(
            int((heavy[:, :, 3] > 0).sum()), int((plain[:, :, 3] > 0).sum())
        )
        dark = (heavy[:, :, 0] < 60) & (heavy[:, :, 3] > 128)
        self.assertGreater(int(dark.sum()), 0, "no stroke was drawn at all")

    @staticmethod
    def _components(mask: np.ndarray) -> np.ndarray:
        count, labels = cv2.connectedComponents(
            mask.astype(np.uint8), connectivity=4
        )
        return labels

    def _run_together(self, text: str, cap: int) -> int:
        """How many letters lost the stroke that separated them from the next.

        White type over a white ground, which is what a stroke is most often
        for: the stroke is the only thing between one letter and the next, so
        two letters sharing a patch of white are two letters the reader sees
        run together.

        Counted by comparing against the same layout drawn with no stroke at
        all. Letters that already touch in the outline are one shape in both,
        so the measure adjusts itself to the face and the size rather than
        assuming a letter count.
        """
        stroked = self._tile(2, text, cap)
        fill = self._components(self._tile(0, text, cap)[:, :, 3] > 200)

        ground = np.zeros(stroked.shape, dtype=np.uint8)
        ground[:, :] = (255, 255, 255, 255)
        flat = np.array(
            Image.alpha_composite(Image.fromarray(ground), Image.fromarray(stroked))
        )
        # A white fill's antialiasing over a white ground is white, so "light"
        # is exactly the region the eye reads as not-stroke.
        light = self._components(flat[:, :, :3].min(axis=2) > 200)

        shapes = set(np.unique(fill)) - {0}
        # One light region per shape, or two shapes are sharing one.
        return len(shapes) - len({int(light[fill == shape][0]) for shape in shapes})

    def test_the_stroke_keeps_one_letter_off_the_next(self):
        """The bug this class was extended for: gaps between letters lost it.

        Two letters set close together have their antialiased rims touch, and a
        flood over "no ink" cannot pass a 30%-alpha bridge. The gap between them
        counted as enclosed - as a counter - so the stroke was taken out of it,
        and white-on-white type ran into itself.

        Small sizes especially, because the rim is a constant width and the gap
        is not: this never showed at display sizes and was at its worst at the
        ones game UI is actually set in.
        """
        for cap in (8, 9, 10, 12, 16, 24, 40):
            for text in ("hits", "its", "tsu", "Miss!", "mix", "x2", "1 turn"):
                with self.subTest(cap=cap, text=text):
                    self.assertEqual(
                        self._run_together(text, cap), 0,
                        "letters are sharing a patch of background because the "
                        "stroke between them was dropped",
                    )


class PiecesTests(unittest.TestCase):
    """``base`` and ``overlay``, which the editor's brush draws from.

    They are not decoration: recombining them has to give the render back
    exactly, or a stroke drawn live shows something the file will not contain.
    """

    def test_the_pieces_add_back_up_to_the_render(self):
        array = canvas(240, 80, (255, 255, 255, 255))
        glyphs(array, Box(40, 30, 200, 50), (0, 0, 0, 255))
        result = render.render_entry(
            array, entry_of([block(Box(38, 28, 202, 52), target="Hello")])
        )
        self.assertIsNotNone(result.base)
        self.assertIsNotNone(result.overlay)
        rebuilt = result.array.copy()
        paint.recomposite(rebuilt, result.base, result.overlay, None)
        self.assertTrue(
            (rebuilt == result.array).all(),
            "the canvas would show something the file will not contain",
        )

    def test_the_base_is_the_picture_without_a_word_of_english(self):
        array = canvas(240, 80, (255, 255, 255, 255))
        glyphs(array, Box(40, 30, 200, 50), (0, 0, 0, 255))
        result = render.render_entry(
            array, entry_of([block(Box(38, 28, 202, 52), target="Hello")])
        )
        rows, cols = Box(38, 28, 202, 52).slices()
        self.assertFalse(
            (result.base[rows, cols][:, :, :3] < 128).all(axis=2).any(),
            "the base still has ink in the block",
        )

    def test_a_stroke_shows_through_the_pieces_the_way_it_renders(self):
        array = canvas(240, 80, (255, 255, 255, 255))
        glyphs(array, Box(40, 30, 200, 50), (0, 0, 0, 255))
        entry = entry_of([block(Box(38, 28, 202, 52), target="Hello")])
        layer = paint.blank(array.shape)
        paint.stroke(layer, (10, 70), (230, 70), 6, [255, 0, 255, 255])
        result = render.render_entry(array, entry, paint=layer)
        # What the canvas does between renders: base already has the paint in
        # it, so recompositing shows the stroke without another render.
        display = result.array.copy()
        paint.recomposite(display, result.base, result.overlay, layer)
        self.assertTrue((display == result.array).all())


class BrushSizeTests(unittest.TestCase):
    """Width in pixels, edge to edge, and one really does mean one.

    The brush used to take a radius and hand it to ``cv2.line`` as a thickness,
    which draws thickness 3 five pixels across and a click that does not move at
    thickness 1 not at all. A cursor ring that disagrees with the paint is worse
    than no ring.
    """

    def setUp(self):
        self.layer = paint.blank((80, 200, 4))

    def width_of(self, size):
        layer = paint.blank((80, 200, 4))
        paint.stroke(layer, (20, 40), (180, 40), size, [255, 0, 0, 255])
        hit = layer[:, :, 3] > 0
        rows = np.nonzero(hit.any(axis=1))[0]
        return int(rows.max() - rows.min() + 1)

    def test_one_pixel_means_one_pixel(self):
        self.assertEqual(self.width_of(1), 1)

    def test_the_width_is_the_number_that_was_asked_for(self):
        for size in (2, 3, 8, 21):
            with self.subTest(size=size):
                self.assertEqual(self.width_of(size), size)

    def test_a_click_that_does_not_move_still_paints(self):
        paint.stroke(self.layer, (50, 40), (50, 40), 1, [255, 0, 0, 255])
        self.assertEqual(int((self.layer[:, :, 3] > 0).sum()), 1)

    def test_a_stroke_off_the_edge_paints_what_is_on_it(self):
        paint.stroke(self.layer, (-40, 40), (30, 40), 5, [255, 0, 0, 255])
        self.assertGreater(int((self.layer[:, :, 3] > 0).sum()), 0)

    def test_a_stroke_entirely_off_the_image_paints_nothing(self):
        paint.stroke(self.layer, (-90, -90), (-60, -60), 5, [255, 0, 0, 255])
        self.assertTrue(paint.is_clear(self.layer))

    def test_the_size_is_clamped_rather_than_trusted(self):
        self.assertEqual(paint.clamp_size(0), paint.MIN_SIZE)
        self.assertEqual(paint.clamp_size(10_000), paint.MAX_SIZE)


class AdoptBackgroundTests(unittest.TestCase):
    """Choosing an erase method samples what that method needs.

    Setting only the name is how a block reached the renderer marked
    "vgradient" with no gradient in it, and came back complaining about its own
    internals instead of about the image.
    """

    def gradient(self) -> np.ndarray:
        array = canvas(200, 120, (255, 255, 255, 255))
        for y in range(120):
            array[y, :, :3] = (40 + y, 90, 200 - y // 2)
        return array

    def test_picking_a_vertical_gradient_samples_the_rows(self):
        array = self.gradient()
        style = Style(background=stylemod.BG_SOLID, fill=[255, 255, 255, 255])
        box = Box(60, 30, 140, 70)
        problem = stylemod.adopt_background(
            array, style, box, [], stylemod.BG_VGRADIENT
        )
        self.assertEqual(problem, "")
        self.assertEqual(len(style.row_colors), box.h)

    def test_a_flat_field_says_why_a_gradient_will_not_work(self):
        array = canvas(200, 120, (255, 255, 255, 255))
        bar(array, Box(0, 0, 200, 120), (255, 255, 255, 255))
        style = Style()
        # No margin to sample: the box is the whole image.
        problem = stylemod.adopt_background(
            array, style, Box(0, 0, 200, 120), [], stylemod.BG_VGRADIENT
        )
        self.assertTrue(problem)
        self.assertNotIn("vgradient", problem)

    def test_picking_a_solid_fill_finds_a_colour(self):
        array = canvas(200, 120, (12, 200, 40, 255))
        style = Style()
        self.assertEqual(
            stylemod.adopt_background(
                array, style, Box(60, 40, 140, 80), [], stylemod.BG_SOLID
            ),
            "",
        )
        self.assertEqual(style.fill[:3], [12, 200, 40])

    def test_a_method_that_needs_nothing_is_taken_as_it_is(self):
        style = Style()
        for name in (stylemod.BG_INPAINT, stylemod.BG_KEEP, stylemod.BG_TRANSPARENT):
            self.assertEqual(
                stylemod.adopt_background(
                    canvas(40, 40), style, Box(4, 4, 36, 36), [], name
                ),
                "",
            )
            self.assertEqual(style.background, name)

    def test_an_unsatisfiable_method_explains_itself_at_render_time(self):
        """The renderer's own message, for a style that arrived from a file."""
        array = canvas(200, 80, (255, 255, 255, 255))
        glyphs(array, Box(40, 30, 160, 50), (0, 0, 0, 255))
        item = block(Box(38, 28, 162, 52), target="Hello")
        # The shape a block has after the method was picked off the panel and
        # nothing was sampled for it: a name with no rows behind it.
        item.style = Style(
            background=stylemod.BG_VGRADIENT,
            fill=[255, 255, 255, 255],
            cap_height=18,
        )
        item.style.locked = True
        result = render.render_entry(array, entry_of([item]))
        self.assertEqual(len(result.failures), 1)
        message = result.failures[0].message
        self.assertIn("gradient", message)
        self.assertNotIn("vgradient", message)


# ------------------------------------------------------------- transparency


def plate(width: int = 200, height: int = 80, panel_alpha: int = 179) -> np.ndarray:
    """A name plate: opaque white glyphs cut into a part-transparent black bar.

    The commonest thing in an RPG Maker battle graphic, and the case every
    RGB-only reading of these images gets wrong. Around the bar is nothing at
    all - alpha 0 - which is the other half of the trap, because the colour
    stored under alpha 0 is black and a reconstruction that believes it walks
    that black inwards.
    """
    array = np.zeros((height, width, 4), dtype=np.uint8)
    array[20:60, 10:190] = (0, 0, 0, panel_alpha)
    glyphs(array, Box(30, 28, 170, 52), (255, 255, 255, 255), soft=False)
    return array


class TransparencyTests(unittest.TestCase):
    """Alpha is a channel to reconstruct, not a channel to leave alone."""

    def test_reconstruction_puts_the_opacity_back_too(self):
        """The Mr. Bandu bug: colour repaired, silhouette left behind.

        Every other erase method writes all four channels, so reconstruction
        was the only one that could leave the shape of the Japanese behind in
        the alpha channel - opaque glyphs inside a 70% bar, which the game
        composites as a hard black shadow of the text that was erased.
        """
        array = plate()
        box = Box(28, 26, 172, 54)
        style = Style(background=stylemod.BG_INPAINT, fill=[0, 0, 0, 179])
        note = render.erase(array, box, style)
        self.assertTrue(note.ok)
        rows, cols = box.slices()
        inside = array[rows, cols][:, :, 3]
        # Nothing opaque survives where the glyphs were: the bar is one opacity
        # throughout again.
        self.assertLess(int(inside.max()), 200)
        self.assertGreater(int(np.median(inside)), 150)

    def test_the_repair_stays_inside_its_own_surface(self):
        array = plate(panel_alpha=255)
        array[:20, :] = (0, 0, 0, 0)              # nothing above the bar
        box = Box(28, 26, 172, 54)
        style = Style(background=stylemod.BG_INPAINT, fill=[0, 0, 0, 255])
        render.erase(array, box, style)
        rows, cols = box.slices()
        repaired = array[rows, cols]
        # The transparent margin above the bar is not blown open by the repair,
        # and the bar itself is still a bar.
        self.assertGreater(float((repaired[:, :, 3] > 128).mean()), 0.8)
        self.assertEqual(int(array[5, 100, 3]), 0)

    def test_text_cut_out_of_a_panel_by_opacity_alone_is_found(self):
        """Same colour as its panel, 40% of the opacity. Only alpha says so."""
        array = np.zeros((80, 200, 4), dtype=np.uint8)
        array[10:70, 10:190] = (30, 60, 120, 255)
        glyphs(array, Box(30, 20, 170, 60), (30, 60, 120, 100), soft=False)
        style = Style(background=stylemod.BG_SOLID, fill=[30, 60, 120, 255])
        mask = stylemod.ink_mask(array[18:62, 28:172], style)
        self.assertGreater(float(mask.mean()), 0.05)
        self.assertLess(float(mask.mean()), 0.9)

    def test_opacity_is_read_from_the_ink_not_from_a_colour_bucket(self):
        """Twenty-three stray pixels used to decide the whole translation.

        ``dominant_color`` picks a bucket by colour and then takes the median of
        all four channels inside it, so the opacity of the English was set by
        whatever alpha happened to sit on the winning *colour*. Opacity is a
        property of the ink, so it is measured over the ink.
        """
        array = plate()
        crop = array[26:54, 28:172]
        self.assertEqual(stylemod.ink_opacity(crop, crop[:, :, 3] > 200), 255)
        # Genuinely translucent type reads as translucent, not rounded up.
        faint = canvas(120, 40, (255, 255, 255, 255))
        glyphs(faint, Box(5, 5, 115, 35), (10, 10, 10, 128), soft=False)
        self.assertAlmostEqual(
            stylemod.ink_opacity(faint, faint[:, :, 3] < 200), 128, delta=6
        )

    def test_a_measured_style_does_not_inherit_its_surface_transparency(self):
        array = plate()
        item = block(Box(28, 26, 172, 54), target="Hello")
        measured = stylemod.measure(array, item, [item.box])
        self.assertEqual(measured.text_color[3], 255)


class SilentNoOpTests(unittest.TestCase):
    """A choice that erases nothing must not report success and move on."""

    def test_a_fill_colour_that_is_not_the_background_still_finds_the_ink(self):
        """Switching method left a stale fill, and the whole box read as ink.

        ``drop_thick_shapes`` then deleted it - one large thick component - and
        the erase changed not a single pixel while reporting that it was fine.
        Every method except reconstruction did this on battle3_2.png.
        """
        array = canvas(200, 90, (240, 240, 240, 255))
        glyphs(array, Box(30, 25, 170, 65), (20, 20, 20, 255))
        box = Box(28, 23, 172, 67)
        rows, cols = box.slices()
        # A fill colour that matches nothing here, as if carried over from a
        # block measured somewhere else entirely.
        style = Style(background=stylemod.BG_SOLID, fill=[12, 200, 40, 255])
        mask = stylemod.ink_mask(array[rows, cols], style)
        self.assertGreater(int(mask.sum()), 40)
        self.assertLess(float(mask.mean()), 0.9)

    def test_cloning_a_strip_erases_even_though_it_sets_no_fill_colour(self):
        array = canvas(200, 160, (240, 240, 240, 255))
        glyphs(array, Box(30, 95, 170, 135), (20, 20, 20, 255))
        box = Box(28, 93, 172, 137)
        style = Style()
        self.assertEqual(
            stylemod.adopt_background(array, style, box, [], stylemod.BG_PATCH), ""
        )
        self.assertIsNone(style.fill)
        before = array.copy()
        note = render.erase(array, box, style)
        self.assertTrue(note.ok)
        self.assertGreater(int((array != before).any(axis=2).sum()), 100)

    def test_finding_nothing_to_erase_is_reported_to_the_panel(self):
        array = canvas(120, 60, (0, 0, 0, 0))
        style = Style(background=stylemod.BG_SOLID, fill=[0, 0, 0, 0])
        note = render.erase(array, Box(10, 10, 110, 50), style)
        self.assertTrue(note.ok)
        self.assertTrue(note.tight)          # tight is what reaches the panel
        self.assertIn("nothing was erased", note.message)

    def crowded(self):
        """A box that its own text fills - a tight box around one word.

        Found on Hstatus2d.png, where the mask came to 100% of the crop. A
        diffusion fill reads only the pixels it is handed, so with none of them
        known `cv2.inpaint` returns the picture unchanged and reports no error
        at all: the block came back marked "reconstructed" with the Japanese
        still on it. Only the fast methods could hit this, because only they
        were given the tight crop.
        """
        array = canvas(260, 150, (60, 90, 140, 255))
        # a busy surround, so a widened crop has something real to read
        for step in range(0, 320, 18):
            cv2.line(array, (step, 0), (step - 60, 150), (90, 130, 190, 255), 5)
        box = Box(90, 55, 250, 130)
        # Strokes close enough together that nothing of the background shows
        # between them - a slab would not do, since a slab measures as an icon
        # and is deliberately left alone. This comes out at 100% of the crop.
        glyphs(array, box, (250, 250, 250, 255), stroke=6, pitch=8)
        return array, box

    def test_a_box_its_own_text_fills_is_still_erased(self):
        array, box = self.crowded()
        for method in (inpaintmod.TELEA, inpaintmod.NS):
            with self.subTest(method):
                trial = array.copy()
                style = Style(
                    background=stylemod.BG_INPAINT,
                    fill=[60, 90, 140, 255],
                    inpaint_method=method,
                )
                note = render.erase(trial, box, style)
                self.assertTrue(note.ok)
                rows, cols = box.slices()
                changed = int(
                    (trial[rows, cols] != array[rows, cols]).any(axis=2).sum()
                )
                self.assertGreater(
                    changed, 100,
                    f"{method} reported {note.message!r} and changed {changed} px",
                )

    def test_a_reconstruction_that_rebuilt_nothing_says_so(self):
        """The backstop: whatever the reason, silence is not an option."""
        array = canvas(120, 60, (0, 0, 0, 0))
        array[:, :, 3] = 0                      # nothing known anywhere to read
        glyphs(array, Box(20, 15, 100, 45), (255, 255, 255, 255))
        # Named rather than left to ``preferred``: a model invents something
        # plausible out of an empty crop and is right to, so the no-op this
        # exists to catch is a property of the diffusion fills.
        style = Style(
            background=stylemod.BG_INPAINT,
            fill=[0, 0, 0, 0],
            inpaint_method=inpaintmod.TELEA,
        )
        note = render.erase(array, Box(18, 13, 102, 47), style)
        self.assertTrue(note.tight)
        self.assertTrue(
            "nothing was erased" in note.message
            or "too little clean artwork" in note.message,
            note.message,
        )


#: Everything that has to be installed before it will run. Telea and
#: Navier-Stokes are not here because OpenCV is not optional.
OPTIONAL = (
    inpaintmod.PATCHMATCH,
    inpaintmod.LAMA,
    inpaintmod.LAMA_MANGA,
    inpaintmod.AOT,
)


class InpaintBackendTests(unittest.TestCase):
    """The reconstruction is pluggable, and says so when a backend is missing.

    Every optional backend is pointed at somewhere empty for the duration, so
    that these assert the *missing* path on a developer's machine and on a
    machine with the whole set installed alike. The installed path is asserted
    separately, below.
    """

    def setUp(self):
        inpaintmod.forget()
        missing = Path(tempfile.gettempdir()) / "imgtl-no-such-place"
        for method in inpaintmod.MODELS:
            os.environ[inpaintmod.model_env(method)] = str(missing / f"{method}.onnx")
        os.environ[inpaintmod.LIB_ENV] = str(missing)

    def tearDown(self):
        for method in inpaintmod.MODELS:
            os.environ.pop(inpaintmod.model_env(method), None)
        os.environ.pop(inpaintmod.LIB_ENV, None)
        inpaintmod.forget()

    def hole(self):
        rgb = np.full((40, 60, 3), 200, dtype=np.uint8)
        rgb[15:25, 20:40] = 0
        mask = np.zeros((40, 60), dtype=bool)
        mask[15:25, 20:40] = True
        return rgb, mask

    def test_the_built_in_methods_are_always_there(self):
        for name in (inpaintmod.TELEA, inpaintmod.NS):
            self.assertTrue(inpaintmod.available(name))
            self.assertIn("OpenCV", inpaintmod.status(name))

    def test_a_missing_backend_explains_itself_rather_than_failing_later(self):
        for method in OPTIONAL:
            with self.subTest(method):
                self.assertFalse(inpaintmod.available(method))
                detail = inpaintmod.status(method)
                self.assertTrue(
                    "onnxruntime" in detail
                    or "no model at" in detail
                    or "no PatchMatch library" in detail,
                    f"{method} gave no actionable reason: {detail}",
                )
                # ...and name something the user can actually go and do: a
                # place to get the file, or the command that installs it.
                self.assertTrue(
                    "http" in detail or "pip install" in detail,
                    f"{method} gave no next step: {detail}",
                )

    def test_an_unavailable_backend_still_repairs_and_says_it_did_not_run(self):
        for method in OPTIONAL:
            with self.subTest(method):
                rgb, mask = self.hole()
                filled, complaint = inpaintmod.fill(rgb, mask, method)
                self.assertIn("fast way", complaint)
                self.assertGreater(int(filled[20, 30].min()), 150)

    def test_an_unknown_method_is_repaired_rather_than_raised_over(self):
        """A style saved by a newer build must not stop the render."""
        rgb, mask = self.hole()
        filled, complaint = inpaintmod.fill(rgb, mask, "no-such-method")
        self.assertEqual(complaint, "")
        self.assertGreater(int(filled[20, 30].min()), 150)

    def test_only_the_slow_methods_ask_for_context(self):
        """Widening the crop helps a model and actively hurts a diffusion fill."""
        for method in inpaintmod.CLASSICAL:
            self.assertFalse(inpaintmod.needs_context(method))
        for method in OPTIONAL:
            self.assertTrue(inpaintmod.needs_context(method))

    def test_the_two_fast_methods_both_repair(self):
        for name in (inpaintmod.TELEA, inpaintmod.NS):
            rgb, mask = self.hole()
            filled, complaint = inpaintmod.fill(rgb, mask, name)
            self.assertEqual(complaint, "")
            self.assertGreater(int(filled[20, 30].min()), 150)

    def test_the_chosen_method_survives_a_save(self):
        for method in inpaintmod.METHODS:
            with self.subTest(method):
                style = Style(background=stylemod.BG_INPAINT, inpaint_method=method)
                self.assertEqual(
                    Style.from_dict(style.to_dict()).inpaint_method, method
                )

    def test_the_default_is_the_one_that_always_works(self):
        """With nothing installed, nothing is preferred over what ships."""
        self.assertEqual(inpaintmod.preferred(), inpaintmod.DEFAULT)
        self.assertIn(inpaintmod.DEFAULT, inpaintmod.CLASSICAL)

    def test_aot_becomes_the_default_once_it_is_installed(self):
        """What the model download buys: the good backend, without asking."""
        with patch.object(inpaintmod, "available", lambda m: m == inpaintmod.AOT):
            inpaintmod.forget()
            self.assertEqual(inpaintmod.preferred(), inpaintmod.AOT)
        inpaintmod.forget()

    def test_a_block_that_chose_nothing_gets_the_preferred_one(self):
        """An empty ``inpaint_method`` means "whatever is best here", not Telea."""
        seen = []
        array = plate(panel_alpha=255)
        style = Style(background=stylemod.BG_INPAINT, fill=[0, 0, 0, 255])
        self.assertEqual(style.inpaint_method, "")
        with patch.object(inpaintmod, "preferred", lambda: inpaintmod.NS):
            with patch.object(
                inpaintmod, "fill",
                lambda rgb, mask, method, *a, **k: (seen.append(method) or (rgb, "")),
            ):
                render.erase(array, Box(28, 26, 172, 54), style)
        self.assertEqual(seen, [inpaintmod.NS])

    def test_the_probe_is_only_paid_for_once(self):
        """It costs an ``import onnxruntime``, and it is asked per block."""
        calls = []
        inpaintmod.forget()
        with patch.object(inpaintmod, "available", lambda m: calls.append(m) or False):
            for _ in range(5):
                inpaintmod.preferred()
        self.assertEqual(len(calls), 1)
        inpaintmod.forget()

    def test_a_download_inside_the_session_is_noticed(self):
        """``forget`` is what the resource dialog calls; without it the answer
        is the one from before the model landed."""
        inpaintmod.forget()
        with patch.object(inpaintmod, "available", lambda m: False):
            self.assertEqual(inpaintmod.preferred(), inpaintmod.DEFAULT)
        with patch.object(inpaintmod, "available", lambda m: m == inpaintmod.AOT):
            self.assertEqual(inpaintmod.preferred(), inpaintmod.DEFAULT)  # cached
            inpaintmod.forget()
            self.assertEqual(inpaintmod.preferred(), inpaintmod.AOT)
        inpaintmod.forget()

    def test_asking_for_a_model_that_is_not_here_still_erases(self):
        """What matters is that it neither raises nor leaves the block alone."""
        array = plate(panel_alpha=255)
        box = Box(28, 26, 172, 54)
        style = Style(
            background=stylemod.BG_INPAINT,
            fill=[0, 0, 0, 255],
            inpaint_method=inpaintmod.LAMA,
        )
        before = array.copy()
        note = render.erase(array, box, style)
        self.assertTrue(note.ok)
        self.assertIn("reconstructed", note.message)
        self.assertIn("fast way", note.message)
        self.assertGreater(int((array != before).any(axis=2).sum()), 100)


class InstalledBackendTests(unittest.TestCase):
    """The backends that *are* installed on this machine, actually run.

    These skip where the tests above assert, and they exist because the
    expensive mistakes in this module are not crashes. Every one of these
    graphs takes NCHW float32 and hands back the same, and they disagree about
    what the numbers mean: LaMa wants 0..1 and returns 0..255, the manga
    fine-tune wants 0..1 and returns 0..1, AOT wants -1..1 both ways and has to
    have the hole zeroed or it copies the text straight back out. Get one of
    those wrong and nothing raises - the repair comes back as a white
    rectangle, or as the text it was asked to remove.
    """

    def field(self, value=128, size=192):
        """A flat field with a hole in it, and no ambiguity about the answer."""
        rgb = np.full((size, size, 3), value, dtype=np.uint8)
        mask = np.zeros((size, size), dtype=bool)
        mask[size // 3 : 2 * size // 3, size // 3 : 2 * size // 3] = True
        rgb[mask] = 255 - value            # something conspicuous to remove
        return rgb, mask

    def each(self):
        for method in OPTIONAL:
            if not inpaintmod.available(method):
                continue
            yield method

    def test_something_is_installed_or_this_says_nothing(self):
        installed = list(self.each())
        if not installed:
            self.skipTest("no optional reconstruction backend is installed")
        self.assertTrue(installed)

    def test_a_flat_field_is_repaired_flat(self):
        """A grey surround can only be repaired grey.

        This catches the number range being read differently coming out than
        going in, which is the mistake that matters: what comes back for the
        hole is then black, white or inverted, and nothing raises. It does
        *not* catch both ends being wrong together - that is an affine
        transform and its inverse, and it cancels. `ModelConventionTests`
        covers that, since no picture can.
        """
        for method in self.each():
            with self.subTest(method):
                rgb, mask = self.field()
                filled, complaint = inpaintmod.fill(rgb, mask, method)
                self.assertEqual(complaint, "")
                repaired = filled[mask].astype(int)
                self.assertLess(
                    abs(float(repaired.mean()) - 128), 24,
                    f"{method} repaired a flat grey field as "
                    f"{float(repaired.mean()):.0f}, not 128",
                )

    def test_the_picture_outside_the_mask_is_returned_untouched(self):
        """No seam along the edge of a block.

        These all repaint the whole crop, and a model asked to reproduce
        pixels it was already given comes back a shade off across every one of
        them. Only the hole may be taken from the repair.
        """
        for method in self.each():
            with self.subTest(method):
                rgb, mask = self.field()
                filled, _ = inpaintmod.fill(rgb, mask, method)
                self.assertTrue(
                    np.array_equal(filled[~mask], rgb[~mask]),
                    f"{method} altered the picture outside the mask",
                )

    def test_the_text_under_the_mask_actually_goes(self):
        for method in self.each():
            with self.subTest(method):
                rgb, mask = self.field()
                filled, _ = inpaintmod.fill(rgb, mask, method)
                left = int(np.abs(filled[mask].astype(int) - 127).min())
                self.assertLess(
                    left, 100, f"{method} left the masked block behind"
                )

    def test_a_crop_that_is_not_the_graph_size_still_goes_through(self):
        """The Carve export is fixed at 512x512 and real blocks never are."""
        for method in self.each():
            with self.subTest(method):
                rgb, mask = self.field(size=97)          # odd, and not a multiple of 8
                filled, complaint = inpaintmod.fill(rgb, mask, method)
                self.assertEqual(complaint, "")
                self.assertEqual(filled.shape, rgb.shape)

    def test_reconstruction_through_the_renderer_removes_the_glyphs(self):
        """End to end: the method reaches `erase` and the plate comes out clean."""
        for method in self.each():
            with self.subTest(method):
                array = plate(panel_alpha=255)
                box = Box(28, 26, 172, 54)
                style = Style(
                    background=stylemod.BG_INPAINT,
                    fill=[0, 0, 0, 255],
                    inpaint_method=method,
                )
                note = render.erase(array, box, style)
                self.assertTrue(note.ok)
                self.assertNotIn("fast way", note.message)
                rows, cols = box.slices()
                # the glyphs were white on black; nothing white may survive
                inside = array[rows, cols][:, :, :3]
                self.assertLess(
                    float((inside > 200).all(axis=2).mean()), 0.02,
                    f"{method} left white glyph pixels in the plate",
                )


class ModelConventionTests(unittest.TestCase):
    """What each graph expects, pinned down where a picture cannot pin it.

    These need no model installed, and they exist because of a result that was
    genuinely surprising: reading a model's numbers wrong at *both* ends is
    undetectable from its output. Going in the picture is squashed by an affine
    transform, coming out it is stretched by the inverse, and the two cancel -
    on a flat field exactly, on real artwork near enough that no threshold
    separates them. What it costs is quality, silently: the network is shown a
    washed-out picture nothing like its training data and asked to extend it.

    So the conventions are written down here as facts, each established by
    feeding the real file a picture and seeing which reading gave the
    surroundings back unchanged. Changing one of these should mean re-running
    that measurement, and having to edit this file is the reminder.
    """

    def test_the_number_ranges_are_the_measured_ones(self):
        expected = {
            # Carve's export: 0..1 in, and 0..255 back out, detected on the way
            inpaintmod.LAMA: (inpaintmod.SCALE_UNIT, False),
            # the manga fine-tune: 0..1 at both ends
            inpaintmod.LAMA_MANGA: (inpaintmod.SCALE_UNIT, False),
            # AOT follows manga-image-translator: -1..1, hole zeroed first
            inpaintmod.AOT: (inpaintmod.SCALE_SIGNED, True),
        }
        for method, (scale, zero_hole) in expected.items():
            with self.subTest(method):
                spec = inpaintmod.MODELS[method]
                self.assertEqual(spec.scale, scale)
                self.assertEqual(spec.zero_hole, zero_hole)

    def test_a_signed_output_is_never_read_as_a_unit_one(self):
        """The mistake that turns a repair into a black or white rectangle."""
        signed = np.linspace(-1.0, 1.0, 9, dtype=np.float32).reshape(3, 3, 1)
        signed = np.repeat(signed, 3, axis=2)
        pixels = inpaintmod._to_pixels(signed.copy(), inpaintmod.SCALE_SIGNED)
        self.assertEqual(int(pixels.min()), 0)
        self.assertEqual(int(pixels.max()), 255)
        self.assertAlmostEqual(int(pixels[1, 1, 0]), 127, delta=1)
        # read as 0..1 instead, everything below mid-grey is crushed to black
        wrong = inpaintmod._to_pixels(signed.copy(), inpaintmod.SCALE_UNIT)
        self.assertEqual(int(wrong[0, 0, 0]), 0)
        self.assertEqual(int(wrong[1, 1, 0]), 0)

    def test_both_unit_output_scales_are_handled(self):
        """0..1 and 0..255 are both in the wild, for the same weights."""
        unit = np.full((2, 2, 3), 0.5, dtype=np.float32)
        self.assertAlmostEqual(
            int(inpaintmod._to_pixels(unit, inpaintmod.SCALE_UNIT)[0, 0, 0]), 127,
            delta=1,
        )
        already = np.full((2, 2, 3), 200.0, dtype=np.float32)
        self.assertEqual(
            int(inpaintmod._to_pixels(already, inpaintmod.SCALE_UNIT)[0, 0, 0]), 200
        )

    def test_every_method_is_labelled_and_probeable(self):
        """A method in the list with no label is a blank row in the panel."""
        for method in inpaintmod.METHODS:
            with self.subTest(method):
                self.assertIn(method, inpaintmod.METHOD_LABELS)
                self.assertTrue(inpaintmod.status(method).startswith(f"{method}:"))

    def test_each_model_has_somewhere_to_be_put_and_somewhere_to_come_from(self):
        for method, spec in inpaintmod.MODELS.items():
            with self.subTest(method):
                self.assertTrue(spec.source.startswith("https://"))
                self.assertEqual(inpaintmod.model_path(method).name, spec.filename)
                self.assertTrue(inpaintmod.model_env(method).startswith("IMGTL_"))

    def test_the_oldest_override_still_spells_the_same(self):
        """`IMGTL_LAMA_MODEL` is in requirements.txt and in users' shells."""
        self.assertEqual(inpaintmod.MODEL_ENV, "IMGTL_LAMA_MODEL")
        self.assertEqual(inpaintmod.model_env(inpaintmod.LAMA), "IMGTL_LAMA_MODEL")


class OutlinedTypeTests(unittest.TestCase):
    """White glyphs with a black stroke - the commonest thing in game UI.

    A single-polarity reading of them over artwork finds the *stroke*, because
    the "lighter" mask holds the illustration as well as the letters and loses
    the size contest to the "darker" one. Erasing what that finds takes out a
    ring and leaves the middle of every letter behind, which reconstruction then
    surrounds with repaired artwork: a flat white slab in the shape of the
    Japanese. It is on battle1_5.png, right behind the name.
    """

    def rings(self, inside, background=(150, 150, 150, 255)) -> np.ndarray:
        array = canvas(140, 50, background)
        for index in range(4):
            left = 10 + index * 32
            cv2.rectangle(array, (left, 12), (left + 22, 38), (10, 10, 10, 255), -1)
            cv2.rectangle(array, (left + 5, 17), (left + 17, 33), inside, -1)
        return array

    def test_the_fill_inside_the_stroke_is_erased_too(self):
        array = self.rings((250, 250, 250, 255))
        style = Style(background=stylemod.BG_SOLID, fill=[150, 150, 150, 255])
        mask = stylemod.ink_mask(array[6:44, 4:136], style)
        # The pale middle of every ring, not only its stroke.
        for index in range(4):
            self.assertTrue(bool(mask[25 - 6, 10 + index * 32 + 11 - 4]),
                            f"the inside of ring {index} was left behind")

    def test_a_counter_full_of_the_background_is_left_alone(self):
        """An "o" is not an outlined glyph, and its hole is not a fill."""
        array = self.rings((150, 150, 150, 255))
        style = Style(background=stylemod.BG_SOLID, fill=[150, 150, 150, 255])
        mask = stylemod.ink_mask(array[6:44, 4:136], style)
        self.assertFalse(bool(mask[25 - 6, 20 - 4]))


if __name__ == "__main__":
    unittest.main()
