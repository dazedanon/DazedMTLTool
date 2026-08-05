"""The three-step editor: the gates, the ordering, and the brushes.

These are about *sequencing*, not about pixels - the rendering itself is pinned
down in ``test_imagetools_render``. What is tested here is the part the user
actually walks through: that a step stays shut until the one before it has
produced something, that confirming moves on to work that still needs doing, and
that a brush stroke made on one image is still there after switching away,
changing the font and writing the file.

Modal dialogs are patched out. Offscreen Qt cannot run one - ``exec_()`` on a
QMessageBox is a hard crash, not an exception - so every test that reaches a
confirmation answers it here instead.
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("IMGTL_FILES_DIR", tempfile.mkdtemp(prefix="imgtl-editor-"))

# The semi-manual image workflow's dependencies are downloaded on demand
# (util/imagetools/resources.py), so a checkout that has never opened it does
# not have them. Skip rather than fail: an ImportError here would read as
# "this branch broke the suite" on a tree where nothing is wrong.
if importlib.util.find_spec("cv2") is None:
    raise unittest.SkipTest(
        "semi-manual image extras are not installed - run "
        "python -m util.imagetools.resources --default"
    )

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PyQt5.QtCore import QPointF, Qt  # noqa: E402
from PyQt5.QtWidgets import QApplication, QMessageBox  # noqa: E402

from gui.image_text_editor import (  # noqa: E402
    STEP_OCR,
    STEP_RENDER,
    STEP_TRANSLATE,
    ImageTextEditor,
)
from gui.imagetext_canvas import TOOL_ERASER, TOOL_PENCIL, TOOL_SELECT  # noqa: E402
from util.imagetools import inpaint as inpaintmod  # noqa: E402
from util.imagetools import paint, render  # noqa: E402
from util.imagetools import style as stylemod  # noqa: E402
from util.imagetools.geometry import Box  # noqa: E402
from util.imagetools.job import (  # noqa: E402
    CONFIRMED,
    NEEDS_REVIEW,
    PENDING,
    RENDERED,
    Job,
    TextBlock,
)


def picture(path: Path, text_box: Box) -> None:
    """A white card with a row of dark strokes in it: the shape of text."""
    array = np.zeros((80, 240, 4), dtype=np.uint8)
    array[:, :] = (255, 255, 255, 255)
    for index in range((text_box.w + 13) // 14):
        left = text_box.x + index * 14 + 4
        array[text_box.y : text_box.y2, left : left + 5] = (0, 0, 0, 255)
    array[:, :] = cv2.GaussianBlur(array, (3, 3), 0)
    render.save_rgba(array, path)


class EditorTestCase(unittest.TestCase):
    """Three images, all read, none confirmed - the state after step one runs."""

    NAMES = ("one.png", "two.png", "three.png")

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="imgtl-editor-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.workspace = self.root / "images"
        self.workspace.mkdir(parents=True)
        for name in self.NAMES:
            picture(self.workspace / name, Box(40, 28, 200, 52))

        job = Job(self.workspace)
        job.sync(list(self.NAMES))
        for entry in job.images:
            entry.blocks = [
                TextBlock("b-" + entry.name[:3], Box(38, 26, 202, 54), "元の文字", "")
            ]
            entry.status = NEEDS_REVIEW
        job.save()

        for name, replacement in (
            ("question", lambda *a, **k: QMessageBox.Yes),
            ("information", lambda *a, **k: None),
            ("warning", lambda *a, **k: None),
        ):
            patcher = patch.object(QMessageBox, name, staticmethod(replacement))
            patcher.start()
            self.addCleanup(patcher.stop)

        self.dialog = ImageTextEditor(self.root, self.workspace, list(self.NAMES))
        self.addCleanup(self._shut_down)

    def _shut_down(self):
        self.dialog.render_step.stop_worker()
        self.dialog.ocr_step.stop_worker()
        self.dialog.close()
        self.app.processEvents()

    # ---------------------------------------------------------------- helpers
    def rows(self, step):
        return [step.list.item(r).data(Qt.UserRole) for r in range(step.list.count())]

    def translate_everything(self):
        for entry in self.dialog.job.images:
            entry.status = CONFIRMED
            for block in entry.blocks:
                block.target_text = "Hello"
        self.dialog.reload_lists()
        self.dialog.refresh_gates()

    def open_render(self):
        self.translate_everything()
        self.dialog.goto_step(STEP_RENDER)
        worker = self.dialog.render_step.worker
        if worker is not None:
            worker.wait(30_000)
        self.app.processEvents()
        return self.dialog.render_step


class GateTests(EditorTestCase):
    def test_the_later_steps_start_shut(self):
        self.assertTrue(self.dialog.tabs.isTabEnabled(STEP_OCR))
        self.assertFalse(self.dialog.tabs.isTabEnabled(STEP_TRANSLATE))
        self.assertFalse(self.dialog.tabs.isTabEnabled(STEP_RENDER))

    def test_next_is_dead_until_something_is_confirmed(self):
        self.assertFalse(self.dialog.ocr_step.next_button.isEnabled())
        self.dialog.ocr_step.confirm_current()
        self.assertTrue(self.dialog.ocr_step.next_button.isEnabled())

    def test_confirming_opens_translation_and_nothing_else(self):
        self.dialog.ocr_step.confirm_current()
        self.assertTrue(self.dialog.tabs.isTabEnabled(STEP_TRANSLATE))
        self.assertFalse(
            self.dialog.tabs.isTabEnabled(STEP_RENDER),
            "render opened before a single translation came back",
        )

    def test_a_translation_opens_the_render_step(self):
        self.dialog.ocr_step.confirm_current()
        self.dialog.job.images[0].blocks[0].target_text = "Hello"
        self.dialog.refresh_gates()
        self.assertTrue(self.dialog.tabs.isTabEnabled(STEP_RENDER))

    def test_a_skipped_block_is_not_a_translation(self):
        """A block marked "leave this alone" has a target but nothing to draw."""
        self.dialog.ocr_step.confirm_current()
        block = self.dialog.job.images[0].blocks[0]
        block.target_text = "Hello"
        block.skip = True
        self.dialog.refresh_gates()
        self.assertFalse(self.dialog.tabs.isTabEnabled(STEP_RENDER))


class OcrStepTests(EditorTestCase):
    def test_unread_images_sort_last_and_are_greyed(self):
        entry = self.dialog.job.find("two.png")
        entry.blocks = []
        entry.status = PENDING
        self.dialog.reload_lists()
        step = self.dialog.ocr_step
        self.assertEqual(self.rows(step)[-1], "two.png")
        row = self.list_row(step, "two.png")
        self.assertEqual(step.list.item(row).foreground().color().name(), "#6e6e76")

    def list_row(self, step, relpath):
        return self.rows(step).index(relpath)

    def test_the_job_order_is_not_disturbed_by_the_display_order(self):
        """The exchange file and Job.sync both key off ``index``."""
        entry = self.dialog.job.find("one.png")
        entry.blocks = []
        entry.status = PENDING
        self.dialog.reload_lists()
        self.assertEqual(
            [e.relpath for e in self.dialog.job.images],
            sorted(self.NAMES),
        )

    def test_confirm_moves_to_the_next_image_that_needs_one(self):
        step = self.dialog.ocr_step
        step.select_relpath("one.png")
        step.confirm_current()
        self.assertEqual(self.dialog.job.find("one.png").status, CONFIRMED)
        self.assertNotEqual(step.current_relpath(), "one.png")

    def test_confirm_steps_over_an_already_confirmed_neighbour(self):
        """Advancing by one row stalls on a confirmed neighbour, which is how
        the old button made you click past work you had already done."""
        step = self.dialog.ocr_step
        order = self.rows(step)
        self.dialog.job.find(order[1]).status = CONFIRMED
        self.dialog.reload_lists()
        step.select_relpath(order[0])
        step.confirm_current()
        self.assertEqual(step.current_relpath(), order[2])

    def test_an_image_with_no_boxes_cannot_be_confirmed(self):
        step = self.dialog.ocr_step
        entry = self.dialog.job.find("two.png")
        entry.blocks = []
        entry.status = PENDING
        self.dialog.reload_lists()
        step.select_relpath("two.png")
        step.confirm_current()
        self.assertEqual(entry.status, PENDING)

    def test_processing_nothing_highlighted_reads_nothing(self):
        step = self.dialog.ocr_step
        step.list.clearSelection()
        step._read_selected()
        self.assertIsNone(step.worker)

    def test_editing_a_confirmed_image_un_confirms_it(self):
        step = self.dialog.ocr_step
        step.select_relpath("one.png")
        step.confirm_current()
        entry = self.dialog.job.find("one.png")
        step.select_relpath("one.png")
        step.canvas.select([entry.blocks[0].block_id])
        step._delete()
        self.assertEqual(entry.status, NEEDS_REVIEW)


class TranslateStepTests(EditorTestCase):
    def test_export_writes_into_the_game_workspace_and_the_mirror(self):
        self.dialog.ocr_step.confirm_current()
        self.dialog.goto_step(STEP_TRANSLATE)
        written = self.dialog.translate_step.export_only()
        self.assertIsNotNone(written)
        target, mirror = written
        self.assertTrue(target.is_file())
        self.assertIn(".dazedtl", str(target))
        self.assertIsNotNone(mirror)
        self.assertIn(
            os.environ["IMGTL_FILES_DIR"], str(mirror),
            "the export escaped the redirect and would land in the real files/",
        )

    def test_export_with_nothing_confirmed_writes_nothing(self):
        self.dialog.goto_step(STEP_TRANSLATE)
        # The "confirm them all now?" prompt is answered Yes by the patch, so
        # the images that have been *read* go; the point is that it does not
        # crash and does not invent images that were never looked at.
        for entry in self.dialog.job.images:
            entry.blocks = []
            entry.status = PENDING
        self.assertIsNone(self.dialog.translate_step.export_only())

    def test_loading_translations_fills_the_targets_in(self):
        import json

        self.dialog.ocr_step.confirm_current()
        self.dialog.goto_step(STEP_TRANSLATE)
        step = self.dialog.translate_step
        _target, mirror = step.export_only()
        data = json.loads(mirror.read_text(encoding="utf-8"))
        for image in data["images"]:
            for region in image["regions"]:
                region["target"] = "Hello there"
        mirror.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        step.load_translations(verbose=False)
        filled = [
            block for entry in self.dialog.job.images
            for block in entry.blocks if block.target_text
        ]
        self.assertTrue(filled)
        self.assertTrue(self.dialog.tabs.isTabEnabled(STEP_RENDER))

    def test_the_settings_panel_reads_the_real_env(self):
        step = self.dialog.translate_step
        step.reload_settings()
        self.assertTrue(step.language_combo.currentText())
        self.assertIsInstance(step._missing_env(), list)

    def test_the_log_drops_the_terminal_dressing(self):
        """The shared worker writes for a console; this is not one."""
        step = self.dialog.translate_step
        step.log.clear()
        step._last_log = ""
        for line in (
            "📁 Found 1 files to process:",
            "   • image_text.json",
            "🔧 Using module: Image Text",
            "📊 Estimate only: No",
            "\x1b[34m[1.8s]\x1b[33m[Input: 2908][Cost: $0.0046]\x1b[39m image_text.json",
            "💰 [1.8s][Input: 2908][Cost: $0.0046] TOTAL",
            "💰 [1.8s][Input: 2908][Cost: $0.0046] TOTAL",
        ):
            step.append_log(line)
        text = step.log.toPlainText()
        self.assertNotIn("\x1b", text, "raw escape codes reached the log")
        self.assertNotIn("Using module", text)
        self.assertNotIn("Found 1 files", text)
        self.assertIn("$0.0046", text, "the cost was thrown out with the noise")
        self.assertEqual(text.count("TOTAL"), 1, "the grand total was printed twice")

    def test_the_log_shows_what_was_actually_translated(self):
        step = self.dialog.translate_step
        for entry in self.dialog.job.images:
            for block in entry.blocks:
                block.target_text = "Attack!"
        step.log.clear()
        step._last_log = ""
        step._log_translations()
        text = step.log.toPlainText()
        self.assertIn("元の文字", text, "the Japanese it came from is not shown")
        self.assertIn("Attack!", text, "the English it came back as is not shown")
        self.assertIn("one.png", text)


class RenderStepTests(EditorTestCase):
    def test_only_translated_images_are_listed(self):
        self.translate_everything()
        self.dialog.job.find("two.png").blocks[0].target_text = ""
        self.dialog.reload_lists()
        self.assertNotIn("two.png", self.rows(self.dialog.render_step))

    def test_entering_the_step_previews_every_image(self):
        step = self.open_render()
        self.assertEqual(
            set(step.previews) & set(self.NAMES), set(self.NAMES),
            "some images had no preview waiting when the step opened",
        )

    def test_the_preview_is_the_real_render(self):
        step = self.open_render()
        step.select_relpath("one.png")
        entry = step.current_entry()
        direct = render.render_entry(step.array, entry, paint=step.layer).array
        self.assertTrue((step.previews["one.png"] == direct).all())

    def test_editing_the_translation_redraws(self):
        step = self.open_render()
        step.select_relpath("one.png")
        entry = step.current_entry()
        step.canvas.select([entry.blocks[0].block_id])
        before = step.previews["one.png"].copy()
        step.target_edit.setPlainText("Something else entirely")
        step.refresh_preview()
        self.assertFalse((step.previews["one.png"] == before).all())

    def test_turning_a_knob_marks_the_style_as_the_users(self):
        step = self.open_render()
        step.select_relpath("one.png")
        entry = step.current_entry()
        step.canvas.select([entry.blocks[0].block_id])
        block = step.current_block()
        self.assertIsNotNone(block)
        self.assertFalse(block.style.locked)
        step.cap_spin.setValue(step.cap_spin.value() + 5)
        self.assertTrue(block.style.locked)
        self.assertEqual(step.style_summary.text(), "Set by you.")

    def test_confirm_marks_and_moves_on(self):
        step = self.open_render()
        order = self.rows(step)
        step.select_relpath(order[0])
        step.confirm_current()
        self.assertIn(order[0], step.approved)
        self.assertNotEqual(step.current_relpath(), order[0])

    def test_render_writes_the_files_and_keeps_the_originals(self):
        step = self.open_render()
        before = (self.workspace / "one.png").read_bytes()
        step._render_all()
        self.assertEqual(self.dialog.job.find("one.png").status, RENDERED)
        self.assertNotEqual((self.workspace / "one.png").read_bytes(), before)
        self.assertEqual(
            self.dialog.job.original_path(self.dialog.job.find("one.png")).read_bytes(),
            before,
        )

    def test_undo_render_puts_the_picture_back(self):
        step = self.open_render()
        before = (self.workspace / "one.png").read_bytes()
        step._render_all()
        step.select_relpath("one.png")
        step._restore_current()
        self.assertEqual((self.workspace / "one.png").read_bytes(), before)

    def test_render_selected_falls_back_to_the_confirmed_ones(self):
        step = self.open_render()
        step.list.clearSelection()
        step.approved = {"one.png"}
        with patch.object(render, "write_entry", wraps=render.write_entry) as spy:
            step._render_selected()
        written = {call.args[1].relpath for call in spy.call_args_list}
        self.assertEqual(written, {"one.png"})


class BrushTests(EditorTestCase):
    MAGENTA = [255, 0, 255, 255]

    def drag(self, canvas, a, b, modifiers=Qt.NoModifier):
        """What press -> move -> release does, without synthesising events."""
        canvas._snapshot()
        canvas._apply(QPointF(*a), QPointF(*a), modifiers)
        canvas._apply(QPointF(*a), QPointF(*b), modifiers)
        canvas.painted.emit()

    def magenta(self, array):
        return int(
            (
                (array[:, :, 0] == 255)
                & (array[:, :, 1] == 0)
                & (array[:, :, 2] == 255)
            ).sum()
        )

    def paint_on(self, step, relpath="one.png"):
        step.select_relpath(relpath)
        step.canvas.set_tool(TOOL_PENCIL)
        step.canvas.set_brush_size(12)
        step.canvas.set_brush_colour(self.MAGENTA)
        self.drag(step.canvas, (10, 70), (230, 70))
        step.refresh_preview()

    def test_a_stroke_shows_up_in_the_preview(self):
        step = self.open_render()
        self.paint_on(step)
        self.assertGreater(self.magenta(step.previews["one.png"]), 0)

    def test_a_stroke_survives_a_font_change(self):
        """The layer is composited on every render, not baked into one."""
        step = self.open_render()
        self.paint_on(step)
        entry = step.current_entry()
        step.canvas.select([entry.blocks[0].block_id])
        if step.font_combo.count() > 1:
            # Picking a family fires _style_edited, which is the real path.
            step.font_combo.setCurrentIndex(1)
        step.refresh_preview()
        self.assertGreater(self.magenta(step.previews["one.png"]), 0)

    def test_a_stroke_survives_switching_images(self):
        """Confirm advances on its own, so "the user will save it" never happens."""
        step = self.open_render()
        self.paint_on(step)
        painted = int((step.layer[:, :, 3] > 0).sum())
        self.assertGreater(painted, 0)
        step.select_relpath("two.png")
        step.select_relpath("one.png")
        self.assertEqual(int((step.layer[:, :, 3] > 0).sum()), painted)

    def test_a_stroke_reaches_the_written_png(self):
        step = self.open_render()
        self.paint_on(step)
        step._render_all()
        written = render.load_rgba(self.workspace / "one.png")
        self.assertGreater(self.magenta(written), 0)

    def test_the_layer_is_written_beside_the_job(self):
        step = self.open_render()
        self.paint_on(step)
        self.dialog.save_now()
        self.assertTrue(
            paint.layer_path(self.dialog.job, self.dialog.job.find("one.png")).is_file()
        )

    def test_the_eraser_takes_the_stroke_back_off(self):
        step = self.open_render()
        self.paint_on(step)
        step.canvas.set_tool(TOOL_ERASER)
        step.canvas.set_brush_size(60)
        self.drag(step.canvas, (0, 70), (240, 70))
        self.assertTrue(paint.is_clear(step.layer))

    def test_ctrl_with_the_eraser_paints_instead_of_clearing(self):
        step = self.open_render()
        step.select_relpath("one.png")
        step.canvas.set_tool(TOOL_ERASER)
        step.canvas.set_brush_size(8)
        step.canvas.set_brush_colour(self.MAGENTA)
        self.drag(step.canvas, (60, 40), (180, 40), Qt.ControlModifier)
        self.assertFalse(
            paint.is_clear(step.layer),
            "Ctrl+eraser cleared instead of painting the background",
        )

    def test_the_background_probe_knows_the_local_colour(self):
        step = self.open_render()
        step.select_relpath("one.png")
        entry = step.current_entry()
        step.canvas.select([entry.blocks[0].block_id])
        step._style_for(entry.blocks[0])
        box = entry.blocks[0].box
        colour = step._background_at((box.x + box.w // 2, box.y + box.h // 2))
        self.assertIsNotNone(colour)

    def test_undo_steps_back_through_the_strokes(self):
        step = self.open_render()
        self.paint_on(step)
        painted = int((step.layer[:, :, 3] > 0).sum())
        step.canvas.set_brush_colour([0, 255, 0, 255])
        self.drag(step.canvas, (10, 20), (230, 20))
        self.assertGreater(int((step.layer[:, :, 3] > 0).sum()), painted)
        self.assertTrue(step.canvas.undo())
        self.assertEqual(int((step.layer[:, :, 3] > 0).sum()), painted)

    def test_undo_with_nothing_to_undo_says_no(self):
        step = self.open_render()
        step.select_relpath("one.png")
        self.assertFalse(step.canvas.undo())

    def test_picking_a_tool_leaves_the_view_usable(self):
        """A paint drag must not also pan the view or drag a box out of place."""
        from PyQt5.QtWidgets import QGraphicsView

        step = self.open_render()
        step.canvas.set_tool(TOOL_PENCIL)
        self.assertEqual(step.canvas.dragMode(), QGraphicsView.NoDrag)
        step.canvas.set_tool(TOOL_SELECT)
        self.assertEqual(step.canvas.dragMode(), QGraphicsView.ScrollHandDrag)

    def test_the_probe_loads_the_pencil(self):
        step = self.open_render()
        step.select_relpath("one.png")
        colour = paint.probe(step.canvas.pixels, (2, 2))
        step.canvas.set_brush_colour(colour)
        self.assertEqual(step.canvas.brush_colour[:3], colour[:3])

    def test_a_stroke_is_on_screen_before_the_mouse_comes_up(self):
        """The whole complaint about the old brush.

        Every segment scheduled a full re-render on a debounce, and every
        segment restarted the debounce, so nothing was drawn until the drag
        stopped. Now the canvas recombines the render's own pieces as it goes.
        """
        step = self.open_render()
        step.select_relpath("one.png")
        step.canvas.set_tool(TOOL_PENCIL)
        step.canvas.set_brush_size(12)
        step.canvas.set_brush_colour(self.MAGENTA)
        self.assertEqual(self.magenta(step.canvas.pixels), 0)
        step.canvas._snapshot()
        step.canvas._apply(QPointF(10, 70), QPointF(230, 70), Qt.NoModifier)
        # No painted.emit(), no re-render, no timer: mid-drag exactly.
        self.assertGreater(self.magenta(step.canvas.pixels), 0)

    def test_painting_does_not_write_into_the_cached_preview(self):
        """The canvas paints on its own copy, not on the step's cache."""
        step = self.open_render()
        self.paint_on(step)
        cached = step.previews["one.png"]
        self.assertIsNot(cached, step.canvas.pixels)
        step.canvas.set_brush_colour([0, 255, 0, 255])
        before = cached.copy()
        step.canvas._apply(QPointF(10, 10), QPointF(230, 10), Qt.NoModifier)
        self.assertTrue((cached == before).all())

    def test_the_brush_is_one_width_wherever_it_is_shown(self):
        step = self.open_render()
        step.canvas.set_tool(TOOL_PENCIL)
        step._brush_size_chosen(33)
        self.assertEqual(step.canvas.brush_size, 33)
        self.assertEqual(step.brush_slider.value(), 33)
        self.assertEqual(step.brush_spin.value(), 33)
        # ... and the canvas resizing itself pushes the number back out
        step.canvas.set_brush_size(7)
        step.canvas.size_changed.emit(7)
        self.assertEqual(step.brush_slider.value(), 7)
        self.assertEqual(step.brush_spin.value(), 7)

    def test_holding_space_lends_the_mouse_to_the_hand(self):
        from PyQt5.QtGui import QKeyEvent
        from PyQt5.QtWidgets import QGraphicsView

        step = self.open_render()
        step.canvas.set_tool(TOOL_PENCIL)
        self.assertEqual(step.canvas.dragMode(), QGraphicsView.NoDrag)
        step.canvas.keyPressEvent(
            QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Space, Qt.NoModifier)
        )
        self.assertEqual(step.canvas.dragMode(), QGraphicsView.ScrollHandDrag)
        step.canvas.keyReleaseEvent(
            QKeyEvent(QKeyEvent.KeyRelease, Qt.Key_Space, Qt.NoModifier)
        )
        # The tool is still the pencil, so the brush comes straight back.
        self.assertEqual(step.canvas.tool, TOOL_PENCIL)
        self.assertEqual(step.canvas.dragMode(), QGraphicsView.NoDrag)


class ViewTests(EditorTestCase):
    """Looking at the picture: the two toggles above the canvas."""

    def open_render(self):
        self.translate_everything()
        self.dialog.goto_step(STEP_RENDER)
        return self.dialog.render_step

    def test_hiding_the_boxes_leaves_them_clickable(self):
        step = self.open_render()
        step.select_relpath("one.png")
        entry = step.current_entry()
        item = step.canvas.items_by_id[entry.blocks[0].block_id]
        step.boxes_box.setChecked(False)
        self.assertTrue(item.ghost)
        # Still in the scene, still hit-testable, still selectable.
        self.assertTrue(item.isVisible())
        step.canvas.select([entry.blocks[0].block_id])
        self.assertEqual(step.canvas.selected_ids(), [entry.blocks[0].block_id])
        step.boxes_box.setChecked(True)
        self.assertFalse(item.ghost)

    def test_show_original_swaps_the_picture_and_puts_it_back(self):
        step = self.open_render()
        step.select_relpath("one.png")
        rendered = step.canvas.pixels.copy()
        step.original_box.setChecked(True)
        self.assertTrue((step.canvas.pixels == step.array).all())
        step.original_box.setChecked(False)
        self.assertTrue((step.canvas.pixels == rendered).all())

    def test_the_brushes_stand_down_while_the_original_is_up(self):
        """They paint onto the render, which is not what is being shown."""
        step = self.open_render()
        step.canvas.set_tool(TOOL_PENCIL)
        step.original_box.setChecked(True)
        self.assertEqual(step.canvas.tool, TOOL_SELECT)
        self.assertFalse(step.pencil_tool.isEnabled())
        step.original_box.setChecked(False)
        self.assertTrue(step.pencil_tool.isEnabled())

    def test_the_original_text_is_shown_beside_the_translation(self):
        step = self.open_render()
        step.select_relpath("one.png")
        entry = step.current_entry()
        step.canvas.select([entry.blocks[0].block_id])
        self.assertEqual(step.source_view.toPlainText(), entry.blocks[0].source_text)
        self.assertTrue(step.source_view.isReadOnly())

    def test_every_installed_face_is_offered(self):
        step = self.open_render()
        labels = [step.font_combo.itemText(i) for i in range(step.font_combo.count())]
        self.assertEqual(labels[0], "Default")
        self.assertGreater(len(labels), 8, "only the hand-picked handful is listed")
        # Named the way the face names itself, not by an eight-character filename.
        self.assertTrue(
            any(" " in label for label in labels[1:]),
            "no font reported a real family name",
        )


class ShellTests(EditorTestCase):
    def test_the_editor_opens_on_the_image_it_was_given(self):
        self.dialog.close()
        self.dialog = ImageTextEditor(self.root, self.workspace, ["three.png"])
        self.assertEqual(self.dialog.ocr_step.current_relpath(), "three.png")

    def test_the_whole_workspace_is_listed_even_when_one_image_is_asked_for(self):
        """Highlighting one image and pressing "Edit text..." used to delete
        every other image's boxes and confirmations, then autosave over them."""
        self.dialog.close()
        self.dialog = ImageTextEditor(self.root, self.workspace, ["three.png"])
        self.assertEqual(len(self.dialog.job.images), len(self.NAMES))
        self.assertEqual(set(self.rows(self.dialog.ocr_step)), set(self.NAMES))

    def test_the_steps_follow_each_other_to_the_same_image(self):
        self.translate_everything()
        self.dialog.ocr_step.select_relpath("three.png")
        self.assertEqual(self.dialog.render_step.current_relpath(), "three.png")

    def test_closing_saves(self):
        self.dialog.job.images[0].blocks[0].source_text = "changed by hand"
        self.dialog.close()
        self.app.processEvents()
        self.assertEqual(
            Job.load(self.workspace).find("one.png").blocks[0].source_text,
            "changed by hand",
        )


class OpacityTests(EditorTestCase):
    """The transparency of the type is a knob, not something that just happens.

    It reached the renderer measured off the source glyphs and there was nothing
    on the panel that could change it, so a block whose ink was read as 70%
    there drew its whole translation at 70% with no way back.
    """

    def block_on_screen(self):
        step = self.open_render()
        step.select_relpath("one.png")
        entry = step.current_entry()
        step.canvas.select([entry.blocks[0].block_id])
        return step, step.current_block()

    def test_the_panel_shows_the_measured_opacity(self):
        step, block = self.block_on_screen()
        alpha = step._style_for(block).text_color[3]
        self.assertEqual(step.opacity_spin.value(), max(1, round(alpha * 100 / 255)))

    def test_turning_it_down_reaches_the_style_and_the_render(self):
        step, block = self.block_on_screen()
        before = step.previews["one.png"].copy()
        step.opacity_spin.setValue(40)
        self.assertAlmostEqual(step._style_for(block).text_color[3], 102, delta=2)
        step.refresh_preview()
        self.assertFalse((step.previews["one.png"] == before).all())

    def test_the_stroke_takes_the_same_opacity_as_the_fill(self):
        step, block = self.block_on_screen()
        step.outline_box.setChecked(True)
        step.opacity_spin.setValue(50)
        style = step._style_for(block)
        self.assertEqual(style.outline_color[3], style.text_color[3])


class ReconstructionTests(EditorTestCase):
    """Which reconstruction fills the hole is a choice, and an honest one."""

    def block_on_screen(self):
        step = self.open_render()
        step.select_relpath("one.png")
        entry = step.current_entry()
        step.canvas.select([entry.blocks[0].block_id])
        return step, step.current_block()

    def test_the_choice_only_applies_to_reconstruction(self):
        step, _block = self.block_on_screen()
        step.bg_combo.setCurrentIndex(step.bg_combo.findData(stylemod.BG_SOLID))
        self.assertFalse(step.inpaint_combo.isEnabled())
        step.bg_combo.setCurrentIndex(step.bg_combo.findData(stylemod.BG_INPAINT))
        self.assertTrue(step.inpaint_combo.isEnabled())

    def test_every_backend_is_offered_and_the_choice_sticks(self):
        step, block = self.block_on_screen()
        step.bg_combo.setCurrentIndex(step.bg_combo.findData(stylemod.BG_INPAINT))
        self.assertEqual(step.inpaint_combo.count(), len(inpaintmod.METHODS))
        step.inpaint_combo.setCurrentIndex(
            step.inpaint_combo.findData(inpaintmod.NS)
        )
        self.assertEqual(step._style_for(block).inpaint_method, inpaintmod.NS)

    def test_a_backend_that_is_not_installed_says_so_on_the_panel(self):
        step, _block = self.block_on_screen()
        step.bg_combo.setCurrentIndex(step.bg_combo.findData(stylemod.BG_INPAINT))
        step.inpaint_combo.setCurrentIndex(
            step.inpaint_combo.findData(inpaintmod.LAMA)
        )
        if not inpaintmod.available(inpaintmod.LAMA):
            self.assertIn("lama", step.style_notes.text())


if __name__ == "__main__":
    unittest.main()
