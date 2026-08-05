"""The editor: three steps from a folder of Japanese pictures to English ones.

    Textboxes / OCR  ->  Translation  ->  Render
    read + confirm       settings + run   look + touch up + write

Three panes per step - image list, canvas, side panel - modelled on the danbooru
translation tool, which solves the same problem and has the shape proven in daily
use. The parts worth copying wholesale were: numbered boxes so reading order is
visible, an amber highlight on anything questionable, click a box and edit its
text in a side panel, no Save button (autosave on a debounce), and a status gate
that only lets *reviewed* work move on.

Two things are different here. The boxes come from an OCR engine that groups
lines into paragraphs only about 80% correctly, so **merge and split are
first-class actions** rather than an afterthought. And this tool edits the image
itself, so it carries the whole loop rather than half of it - including the
translation, which runs here through the project's own engine rather than in
another tab.

**The steps are gated.** There is nothing to translate until boxes have been
confirmed and nothing to render until a translation has come back, so tabs two
and three stay dark until they mean something. That is the whole reason this is
three tabs rather than the row of eight buttons it used to be: the row let you
press Render first and find out by reading a dialog.

This module is the shell. The steps live in ``gui.imagetext_steps``, the picture
and the brushes in ``gui.imagetext_canvas``.
"""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
)

# Re-exported: these lived here before the file was split, and nothing outside
# should have to care that they moved.
from gui.imagetext_canvas import (  # noqa: F401
    TEXT_FONT_CANDIDATES,
    BoxItem,
    Canvas,
    ColourButton,
    PaintCanvas,
    font_choices,
    load_array,
    text_font,
    to_pixmap,
)
from gui.imagetext_steps import (  # noqa: F401
    STATUS_MARK,
    OcrStep,
    ReadWorker,
    RenderStep,
    TranslateStep,
)
from util.imagetools.job import Job

SAVE_DEBOUNCE_MS = 700
# Long enough that dragging a spin box does not re-render on every tick, short
# enough that letting go feels instant.
PREVIEW_DEBOUNCE_MS = 250

STEP_OCR = 0
STEP_TRANSLATE = 1
STEP_RENDER = 2


class ImageTextEditor(QDialog):
    def __init__(self, game_root: Path, workspace: Path, relpaths: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Image text — read, translate, render")
        # A dialog gets a close box and nothing else by default, and this one is
        # a workspace: the render step is judged by looking at pixels, and the
        # first thing anyone does with it is try to make it bigger.
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint
        )
        self.setSizeGripEnabled(True)
        self.resize(1320, 860)
        self.game_root = Path(game_root)
        self.workspace = Path(workspace)
        self.job = Job.load(self.workspace)
        added, removed = self.job.sync(relpaths)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(SAVE_DEBOUNCE_MS)
        self._save_timer.timeout.connect(self.save_now)

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(PREVIEW_DEBOUNCE_MS)
        self._preview_timer.timeout.connect(self._redraw_preview)

        self._build()
        self.reload_lists()
        if self.job.images:
            # Open on what the caller asked for. The list shows the whole
            # workspace - a job covers every editable image, not just the rows
            # that happened to be highlighted - so the request survives as the
            # starting position rather than as a filter.
            wanted = self._first_of(relpaths)
            if wanted:
                self.ocr_step.select_relpath(wanted)
        self.refresh_gates()
        if added or removed:
            self.schedule_save()
        self.status(f"{len(self.job.images)} image(s). " + self.counts_text())

    # ------------------------------------------------------------- layout
    def _build(self) -> None:
        outer = QVBoxLayout(self)

        self.tabs = QTabWidget()
        self.ocr_step = OcrStep(self)
        self.translate_step = TranslateStep(self)
        self.render_step = RenderStep(self)
        self.tabs.addTab(self.ocr_step, "1 · Textboxes / OCR")
        self.tabs.addTab(self.translate_step, "2 · Translation")
        self.tabs.addTab(self.render_step, "3 · Render")
        self.tabs.setTabEnabled(STEP_TRANSLATE, False)
        self.tabs.setTabEnabled(STEP_RENDER, False)
        self.tabs.currentChanged.connect(self._tab_changed)
        outer.addWidget(self.tabs, 1)

        # Keep the same picture under the cursor as the work moves between
        # steps: nothing is more disorienting than confirming an image, pressing
        # Next and landing on a different one.
        self.ocr_step.image_chosen.connect(
            lambda relpath: self.render_step.select_relpath(relpath, quiet=True)
        )
        self.render_step.image_chosen.connect(
            lambda relpath: self.ocr_step.select_relpath(relpath, quiet=True)
        )

        bottom = QHBoxLayout()
        self.status_label = QLabel("")
        bottom.addWidget(self.status_label, 1)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        bottom.addWidget(close_button)
        outer.addLayout(bottom)

    def _first_of(self, relpaths: list[str]) -> str | None:
        wanted = {str(p).replace("\\", "/").lower() for p in relpaths}
        for entry in self.job.images:
            if entry.relpath.replace("\\", "/").lower() in wanted:
                return entry.relpath
        return None

    # ------------------------------------------------------------- services
    def status(self, text: str) -> None:
        self.status_label.setText(text)

    def counts_text(self) -> str:
        counts = self.job.counts()
        parts = [f"{count} {name.replace('_', ' ')}" for name, count in sorted(counts.items())]
        return " · ".join(parts)

    def reload_lists(self) -> None:
        self.ocr_step.reload_list()
        self.render_step.reload_list()
        self.translate_step._refresh_summary()

    def schedule_save(self) -> None:
        self._save_timer.start()

    def save_now(self) -> None:
        try:
            self.job.save()
            self.render_step.save_layer()
        except Exception as exc:
            self.status(f"Could not save: {exc}")
        self.refresh_gates()

    def schedule_preview(self) -> None:
        self._preview_timer.start()

    def _redraw_preview(self) -> None:
        if self.tabs.currentIndex() == STEP_RENDER:
            self.render_step.refresh_preview()

    # ------------------------------------------------------------- gating
    def can_translate(self) -> bool:
        return bool(self.job.confirmed())

    def can_render(self) -> bool:
        return any(
            block.target_text.strip() and not block.skip
            for entry in self.job.images
            for block in entry.blocks
        )

    def refresh_gates(self) -> None:
        """Light the later tabs up as the work that justifies them lands."""
        translate = self.can_translate()
        render = self.can_render()
        self.tabs.setTabEnabled(STEP_TRANSLATE, translate)
        self.tabs.setTabEnabled(STEP_RENDER, render)
        self.ocr_step.next_button.setEnabled(translate)
        self.ocr_step.next_button.setToolTip(
            "Go on to the translation settings."
            if translate else
            "Confirm at least one image first — nothing that has not been "
            "looked at is ever sent to the translator."
        )
        self.translate_step.next_button.setEnabled(render)
        self.translate_step.next_button.setToolTip(
            "Go on to the preview and the render."
            if render else
            "No translations have come back yet."
        )

    def goto_step(self, index: int) -> None:
        self.tabs.setTabEnabled(index, True)
        self.tabs.setCurrentIndex(index)

    def _tab_changed(self, index: int) -> None:
        if index == STEP_TRANSLATE:
            self.translate_step.reload_settings()
        elif index == STEP_RENDER:
            self.render_step.enter()

    # ------------------------------------------------------------- lifecycle
    def closeEvent(self, event):
        self.ocr_step.stop_worker()
        self.translate_step.shutdown()
        self.render_step.stop_worker()
        if self._save_timer.isActive():
            self._save_timer.stop()
        self.save_now()
        super().closeEvent(event)
