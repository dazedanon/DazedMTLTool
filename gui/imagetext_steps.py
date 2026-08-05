"""The three steps of the image workflow, one widget each.

    Textboxes / OCR  ->  Translation  ->  Render
    read + confirm       settings + run   look + touch up + write

Each step is gated on the one before producing something, because the order is
not a suggestion: there is nothing to translate until boxes have been confirmed,
and nothing to render until a translation has come back. The gate is the whole
reason this is three tabs rather than a row of eight buttons - the old row let
you press Render first and find out by reading a dialog.

The steps share the job, the autosave debounce and the image list through the
shell that owns them (``ImageTextEditor``); they do not talk to each other
directly.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import numpy as np
from PyQt5.QtCore import QSize, Qt, QThread, pyqtSignal
from PyQt5.QtGui import QBrush, QColor
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from gui.imagetext_canvas import (
    TOOL_ERASER,
    TOOL_PENCIL,
    TOOL_SELECT,
    Canvas,
    ColourButton,
    PaintCanvas,
    font_choices,
    text_font,
)
from gui.qt_icons import get_icon
from util.imagetools import fonts as fontsmod
from util.imagetools import inpaint as inpaintmod
from util.imagetools import job as jobmod
from util.imagetools import paint as paintmod
from util.imagetools import render as rendermod
from util.imagetools import style as stylemod
from util.imagetools.geometry import Box
from util.imagetools.job import (
    CONFIRMED,
    ERROR,
    NEEDS_REVIEW,
    PENDING,
    RENDERED,
    TRANSLATED,
    ImageEntry,
    TextBlock,
    apply_flags,
)
from util.imagetools.ocr import Line, engine_status, get_engine
from util.imagetools.style import BACKGROUND_LABELS, BACKGROUNDS, Style

STATUS_MARK = {
    PENDING: "·",
    NEEDS_REVIEW: "●",
    CONFIRMED: "✓",
    TRANSLATED: "✓",
    RENDERED: "✓",
    ERROR: "✕",
}

# The same green as "Patch all" on the Images tab, so "this is the button that
# moves the work forward" means one thing across the whole tool.
GO_BUTTON = (
    "QPushButton{border:1px solid #4ec9b0;color:#4ec9b0;font-weight:bold;"
    "padding:7px 18px;}"
    "QPushButton:hover{background:#18352f;}"
    "QPushButton:disabled{border-color:#3a4a46;color:#4d5f5b;}"
)
NEXT_BUTTON = (
    "QPushButton{border:1px solid #4f8ef7;color:#4f8ef7;font-weight:bold;"
    "padding:7px 22px;}"
    "QPushButton:hover{background:#1a2740;}"
    "QPushButton:disabled{border-color:#39404d;color:#565d69;}"
)
DIM = QColor(110, 110, 118)
GREEN = QColor(120, 200, 130)
RED = QColor(230, 80, 80)

# An icon-only tool needs its selected state drawn explicitly. Qt's own
# ``:checked`` look on a flat dark theme is a barely-visible shade change, and
# what the eye was actually reading as "this one is active" was the focus ring -
# which the canvas takes away the moment it is clicked.
TOOL_BUTTON = (
    "QPushButton{border:1px solid #3a4150;border-radius:3px;padding:5px 9px;}"
    "QPushButton:hover{background:#232a36;}"
    "QPushButton:checked{border:1px solid #4f8ef7;background:#1d2c47;}"
    "QPushButton:disabled{border-color:#2b303a;}"
)


def _tool_button(icon: str, tooltip: str) -> QPushButton:
    """One canvas tool: an icon, a tooltip that names it, and a lit state."""
    button = QPushButton()
    button.setIcon(get_icon(icon))
    button.setIconSize(QSize(18, 18))
    button.setCheckable(True)
    button.setToolTip(tooltip)
    button.setStyleSheet(TOOL_BUTTON)
    # Named for the accessibility tree and for tests, since there is no label
    # on screen to find it by any more.
    button.setAccessibleName(tooltip.splitlines()[0])
    return button


def _icon_toggle(icon: str, name: str) -> QPushButton:
    """A checkable icon button that reads as pressed - Bold, Italic."""
    button = QPushButton()
    button.setIcon(get_icon(icon))
    button.setIconSize(QSize(16, 16))
    button.setCheckable(True)
    button.setFixedWidth(30)
    button.setStyleSheet(TOOL_BUTTON)
    button.setAccessibleName(name)
    return button


#: How many characters wide a dropdown may *insist* on being. The lists here
#: hold whole sentences ("LaMa - a model that invents the missing texture") and
#: a combo demands its longest item by default, which leaves the label column
#: with whatever is left and clips the label instead of the sentence. This is a
#: floor, not a width: the fields still grow to fill the panel.
COMBO_CHARS = 8


def _wide_combo() -> QComboBox:
    # The policy has to be set before the items go in - Qt works the hint out
    # once, and a combo filled first keeps the width of its longest entry.
    combo = QComboBox()
    combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLength)
    combo.setMinimumContentsLength(COMBO_CHARS)
    return combo


def _small_spin(low: int, high: int, suffix: str) -> QSpinBox:
    """A number box the width of the numbers it holds, and no wider."""
    spin = QSpinBox()
    spin.setRange(low, high)
    spin.setSuffix(suffix)
    spin.setMaximumWidth(84)
    return spin


def _row(*widgets, stretch: bool = False) -> QWidget:
    """Several small controls on one line of a form."""
    holder = QWidget()
    layout = QHBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    for widget in widgets:
        layout.addWidget(widget)
    if stretch:
        layout.addStretch(1)
    return holder

IMAGE_TEXT_ENGINE = "Image Text"


def _image_text_spec():
    """The registry row for our own translation engine.

    Looked up by exact name rather than by substring. The registry is keyed on
    display names, and several of them contain each other - "Image Text"
    contains "Text" - so a substring match here would hand ``image_text.json``
    to the plain-text engine, which translates a JSON file line by line and
    destroys it.

    Imported inside the function because ``gui.translation_tab`` is a heavy
    module and this runs once, when the user presses Translate.
    """
    from gui.translation_tab import TRANSLATION_MODULE_SPECS

    for spec in TRANSLATION_MODULE_SPECS:
        if spec[0] == IMAGE_TEXT_ENGINE:
            return spec
    raise RuntimeError(
        f"The {IMAGE_TEXT_ENGINE!r} engine is not registered in "
        "TRANSLATION_MODULE_SPECS, so there is nothing to translate with."
    )


# --------------------------------------------------------------------------
# shared


class ImageStep(QWidget):
    """A step with an image list down its left side.

    The list is per step, not shared: the review step wants unread images pushed
    to the bottom and the render step wants them gone entirely, and one widget
    cannot be in two tabs anyway. Rows carry their ``relpath`` rather than an
    index into ``job.images``, because both lists reorder and the job does not.
    """

    image_chosen = pyqtSignal(str)

    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor = editor
        self._loading = False

    @property
    def job(self):
        return self.editor.job

    # ------------------------------------------------------------- list
    def _make_list(self, multi: bool = False) -> QListWidget:
        widget = QListWidget()
        widget.setAlternatingRowColors(True)
        widget.setFont(text_font(9.0))
        if multi:
            widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        widget.currentRowChanged.connect(self._row_changed)
        return widget

    def _ordered_entries(self) -> list[ImageEntry]:
        return list(self.job.images)

    def _decorate(self, item: QListWidgetItem, entry: ImageEntry) -> None:
        pass

    def reload_list(self) -> None:
        keep = self.current_relpath()
        self._loading = True
        self.list.blockSignals(True)
        try:
            self.list.clear()
            for entry in self._ordered_entries():
                mark = STATUS_MARK.get(entry.status, "·")
                suffix = f"  ({len(entry.blocks)})" if entry.blocks else ""
                flagged = sum(1 for block in entry.blocks if block.flags)
                if flagged:
                    suffix += f" ⚠{flagged}"
                item = QListWidgetItem(f"{mark} {entry.name}{suffix}")
                item.setData(Qt.UserRole, entry.relpath)
                item.setToolTip(entry.error or entry.relpath)
                self._decorate(item, entry)
                self.list.addItem(item)
        finally:
            self.list.blockSignals(False)
            self._loading = False
        if keep is not None and self.select_relpath(keep, quiet=True):
            return
        if self.list.count():
            self.list.setCurrentRow(0)

    def current_relpath(self) -> str | None:
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    def current_entry(self) -> ImageEntry | None:
        relpath = self.current_relpath()
        if not relpath:
            return None
        try:
            return self.job.find(relpath)
        except jobmod.JobError:
            return None

    def selected_entries(self) -> list[ImageEntry]:
        out = []
        for item in self.list.selectedItems():
            try:
                out.append(self.job.find(item.data(Qt.UserRole)))
            except jobmod.JobError:
                continue
        return out

    def select_relpath(self, relpath: str, quiet: bool = False) -> bool:
        for row in range(self.list.count()):
            if self.list.item(row).data(Qt.UserRole) == relpath:
                if quiet:
                    self.list.blockSignals(True)
                self.list.setCurrentRow(row)
                if quiet:
                    self.list.blockSignals(False)
                return True
        return False

    def _row_changed(self, row: int) -> None:
        if self._loading:
            return
        self.open_current()
        relpath = self.current_relpath()
        if relpath:
            self.image_chosen.emit(relpath)

    def open_current(self) -> None:
        raise NotImplementedError

    # ------------------------------------------------------------- blocks
    # Shared rather than owned by the review step, because the render step
    # needs the same four operations on the same objects: a box that turns out
    # to be wrong is nearly always noticed while looking at the render, and
    # sending the user back a tab to fix it is what made them stop fixing it.
    # Everything here goes through ``_after_block_change`` so the flags, the
    # lists, the canvas and the autosave stay in step whichever tab called.

    def _add_box(self, box: Box) -> None:
        entry = self.current_entry()
        if entry is None:
            return
        block = TextBlock(jobmod._new_id(), box, "", "", 0.0, [])
        entry.blocks.append(block)
        self._after_block_change(entry, [block.block_id])
        # One box per press, and the button says so. A button still lit for a
        # mode nothing is in is the same bug as the tool row's.
        self.canvas.set_adding(False)
        button = getattr(self, "add_button", None)
        if button is not None:
            button.setChecked(False)

    def _merge(self) -> None:
        entry = self.current_entry()
        ids = self.canvas.selected_ids()
        if entry is None or len(ids) < 2:
            return
        chosen = [b for b in entry.blocks if b.block_id in set(ids)]
        # Reading order, so the joined text comes out in the order it is read.
        chosen.sort(key=lambda b: (b.box.y, b.box.x))
        box = chosen[0].box
        lines: list[Line] = []
        for block in chosen:
            box = box.union(block.box)
            lines.extend(block.lines or [Line(block.source_text, block.box, block.angle)])
        merged = TextBlock(
            jobmod._new_id(),
            box,
            "\n".join(b.source_text for b in chosen if b.source_text.strip()),
            # The translations go with the text they belong to. Dropping them
            # would mean re-running the translator over a paragraph whose words
            # have all already been through it.
            "\n".join(b.target_text for b in chosen if b.target_text.strip()),
            chosen[0].angle,
            lines,
        )
        first = entry.blocks.index(chosen[0])
        for block in chosen:
            entry.blocks.remove(block)
        entry.blocks.insert(first, merged)
        self._after_block_change(entry, [merged.block_id])

    def _split(self) -> None:
        entry = self.current_entry()
        block = self.current_block()
        if entry is None or block is None or block.line_count < 2:
            return
        index = entry.blocks.index(block)
        entry.blocks.remove(block)
        fresh = []
        for line in block.lines:
            fresh.append(
                TextBlock(jobmod._new_id(), line.box, line.text, "", line.angle, [line])
            )
        for offset, item in enumerate(fresh):
            entry.blocks.insert(index + offset, item)
        self._after_block_change(entry, [b.block_id for b in fresh])

    def _delete(self) -> None:
        entry = self.current_entry()
        ids = set(self.canvas.selected_ids())
        if entry is None or not ids:
            return
        entry.blocks = [b for b in entry.blocks if b.block_id not in ids]
        self._after_block_change(entry, [])

    def _after_block_change(self, entry: ImageEntry, select: list[str]) -> None:
        apply_flags(entry)
        if entry.status in jobmod.REVIEWED:
            # Editing after confirming un-confirms: the export must never
            # contain blocks nobody has looked at in their current shape.
            entry.status = NEEDS_REVIEW
        self.canvas.rebuild_boxes()
        self.canvas.select(select)
        self.editor.reload_lists()
        self._sync_panel()
        self.editor.schedule_save()

    def advance(self, wanted) -> bool:
        """Move to the next row after this one for which *wanted* is true.

        Wrapping to the top when there is nothing below, because confirming the
        last image should land on whatever was skipped rather than sit still.
        """
        count = self.list.count()
        start = self.list.currentRow()
        for offset in range(1, count + 1):
            row = (start + offset) % count
            item = self.list.item(row)
            try:
                entry = self.job.find(item.data(Qt.UserRole))
            except jobmod.JobError:
                continue
            if wanted(entry):
                self.list.setCurrentRow(row)
                return True
        return False


# --------------------------------------------------------------------------
# OCR worker


class ReadWorker(QThread):
    progress = pyqtSignal(int, int, str)
    finished_one = pyqtSignal(str, object, str)
    done = pyqtSignal(int, int)

    def __init__(self, job, entries: list[ImageEntry], parent=None):
        super().__init__(parent)
        self.job = job
        self.entries = entries
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        from gui.imagetext_canvas import load_array

        ok = failed = 0
        try:
            engine = get_engine()
        except Exception as exc:
            for entry in self.entries:
                self.finished_one.emit(entry.relpath, None, str(exc))
            self.done.emit(0, len(self.entries))
            return
        total = len(self.entries)
        for index, entry in enumerate(self.entries, start=1):
            if self._stop:
                break
            self.progress.emit(index, total, entry.name)
            array = load_array(self.job.image_path(entry))
            if array is None:
                failed += 1
                self.finished_one.emit(entry.relpath, None, "could not read the file")
                continue
            try:
                reading = engine.read(array)
            except Exception as exc:
                failed += 1
                self.finished_one.emit(entry.relpath, None, str(exc))
                continue
            ok += 1
            self.finished_one.emit(entry.relpath, reading, "")
        self.done.emit(ok, failed)


# --------------------------------------------------------------------------
# step one


class OcrStep(ImageStep):
    """Find the text, fix what the reader got wrong, confirm the image."""

    def __init__(self, editor, parent=None):
        super().__init__(editor, parent)
        self.worker: ReadWorker | None = None
        self.array: np.ndarray | None = None
        self._build()

    # ------------------------------------------------------------- layout
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Horizontal, self)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("Images — highlight the ones to read"))
        self.list = self._make_list(multi=True)
        left_layout.addWidget(self.list, 1)
        self.process_selected = QPushButton("Process selected")
        self.process_selected.setToolTip(
            "Run text detection and OCR over the highlighted images only."
        )
        self.process_selected.clicked.connect(self._read_selected)
        self.process_all = QPushButton("Process all")
        self.process_all.setToolTip(
            "Run text detection and OCR over every image, highlighted or not."
        )
        self.process_all.clicked.connect(self._read_all)
        left_layout.addWidget(self.process_selected)
        left_layout.addWidget(self.process_all)
        splitter.addWidget(left)

        centre = QWidget()
        centre_layout = QVBoxLayout(centre)
        centre_layout.setContentsMargins(0, 0, 0, 0)
        self.canvas = Canvas()
        self.canvas.selection_changed.connect(self._sync_panel)
        self.canvas.geometry_changed.connect(self.editor.schedule_save)
        self.canvas.box_added.connect(self._add_box)
        centre_layout.addWidget(self.canvas, 1)

        tools = QHBoxLayout()
        self.add_button = QPushButton("+ Add box")
        self.add_button.setCheckable(True)
        self.add_button.clicked.connect(
            lambda: self.canvas.set_adding(self.add_button.isChecked())
        )
        fit_button = QPushButton("Fit")
        fit_button.clicked.connect(self.canvas.fit)
        self.show_flagged = QCheckBox("Only flagged")
        self.show_flagged.setToolTip("Select only the blocks that need a second look.")
        self.show_flagged.stateChanged.connect(self._select_flagged)
        tools.addWidget(self.add_button)
        tools.addWidget(fit_button)
        tools.addWidget(self.show_flagged)
        tools.addStretch(1)
        centre_layout.addLayout(tools)
        splitter.addWidget(centre)

        right = QWidget()
        right.setMinimumWidth(320)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.block_title = QLabel("No block selected")
        self.block_flags = QLabel("")
        self.block_flags.setWordWrap(True)
        self.block_flags.setStyleSheet("color: #e0a83e;")
        right_layout.addWidget(self.block_title)
        right_layout.addWidget(self.block_flags)
        right_layout.addWidget(QLabel("Text found (edit if wrong)"))
        self.source_edit = QPlainTextEdit()
        self.source_edit.setPlaceholderText("what the OCR read")
        self.source_edit.setFont(text_font())
        self.source_edit.textChanged.connect(self._source_edited)
        right_layout.addWidget(self.source_edit, 1)
        self.skip_box = QCheckBox("Leave this one alone (do not translate)")
        self.skip_box.stateChanged.connect(self._skip_toggled)
        right_layout.addWidget(self.skip_box)

        buttons = QHBoxLayout()
        self.merge_button = QPushButton("Merge")
        self.merge_button.setToolTip(
            "Join the selected blocks into one paragraph, so it is translated as a whole."
        )
        self.merge_button.clicked.connect(self._merge)
        self.split_button = QPushButton("Split")
        self.split_button.setToolTip("Break this block back into its separate lines.")
        self.split_button.clicked.connect(self._split)
        self.delete_button = QPushButton("Delete")
        self.delete_button.clicked.connect(self._delete)
        buttons.addWidget(self.merge_button)
        buttons.addWidget(self.split_button)
        buttons.addWidget(self.delete_button)
        right_layout.addLayout(buttons)
        right_layout.addStretch(0)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([230, 700, 330])
        outer.addWidget(splitter, 1)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        outer.addWidget(self.progress)

        bottom = QHBoxLayout()
        self.confirm_button = QPushButton("✓ Confirm this image")
        self.confirm_button.setStyleSheet(GO_BUTTON)
        self.confirm_button.setToolTip(
            "Mark the boxes and the text on this image as checked, and move to "
            "the next one that still needs a look."
        )
        self.confirm_button.clicked.connect(self.confirm_current)
        bottom.addWidget(self.confirm_button)
        bottom.addStretch(1)
        self.next_button = QPushButton("Next: Translation →")
        self.next_button.setStyleSheet(NEXT_BUTTON)
        self.next_button.clicked.connect(lambda: self.editor.goto_step(1))
        bottom.addWidget(self.next_button)
        outer.addLayout(bottom)

    # ------------------------------------------------------------- list
    def _ordered_entries(self) -> list[ImageEntry]:
        """Read images first, unread ones after them.

        Display order only. ``entry.index`` and ``job.images`` stay sorted by
        relpath, because the exchange file and ``Job.sync`` both key off it.
        """
        def was_read(entry: ImageEntry) -> bool:
            return bool(entry.blocks) or entry.status not in (PENDING, ERROR)

        # Keyed on the predicate, not on membership: ImageEntry is a dataclass,
        # so `entry in read` compares every field of every block.
        return [e for e in self.job.images if was_read(e)] + [
            e for e in self.job.images if not was_read(e)
        ]

    def _decorate(self, item: QListWidgetItem, entry: ImageEntry) -> None:
        if entry.status == ERROR:
            item.setForeground(QBrush(RED))
        elif entry.status in (PENDING,) and not entry.blocks:
            # Greyed and at the bottom: nothing has looked at these yet, and the
            # eye should skip them while working through the ones that need it.
            item.setForeground(QBrush(DIM))
        elif entry.status in jobmod.REVIEWED:
            item.setForeground(QBrush(GREEN))

    def open_current(self) -> None:
        from gui.imagetext_canvas import load_array

        entry = self.current_entry()
        if entry is None:
            self.canvas.show_image(None, None)
            self.array = None
            return
        # The *pristine* pixels, not whatever is on disk: once an image has been
        # rendered the file holds English, and reviewing boxes against it would
        # be reading our own output back.
        self.array = load_array(self.job.source_path(entry))
        if self.array is not None:
            entry.height, entry.width = self.array.shape[:2]
        self.canvas.show_image(entry, self.array)
        self._sync_panel()
        self.editor.status(
            f"{entry.name} — {entry.status.replace('_', ' ')}. "
            + self.editor.counts_text()
        )

    # ------------------------------------------------------------- panel
    def current_block(self) -> TextBlock | None:
        entry = self.current_entry()
        ids = self.canvas.selected_ids()
        if entry is None or len(ids) != 1:
            return None
        try:
            return entry.block(ids[0])
        except Exception:
            return None

    def _sync_panel(self) -> None:
        block = self.current_block()
        selected = len(self.canvas.selected_ids())
        self.merge_button.setEnabled(selected >= 2)
        self.split_button.setEnabled(bool(block) and block.line_count > 1)
        self.delete_button.setEnabled(selected >= 1)
        if block is None:
            self.block_title.setText(
                f"{selected} blocks selected" if selected else "No block selected"
            )
            self.block_flags.setText("")
            self.source_edit.blockSignals(True)
            self.source_edit.setPlainText("")
            self.source_edit.blockSignals(False)
            self.source_edit.setEnabled(False)
            self.skip_box.setEnabled(False)
            return
        self.source_edit.setEnabled(True)
        self.skip_box.setEnabled(True)
        orientation = "vertical" if block.vertical else "horizontal"
        self.block_title.setText(
            f"{block.box.w}×{block.box.h} px · {block.angle:.0f}° {orientation} · "
            f"{block.line_count} line(s)"
        )
        self.block_flags.setText(
            "⚠ " + ", ".join(jobmod.FLAG_LABELS.get(f, f) for f in block.flags)
            if block.flags else ""
        )
        self.source_edit.blockSignals(True)
        self.source_edit.setPlainText(block.source_text)
        self.source_edit.blockSignals(False)
        self.skip_box.blockSignals(True)
        self.skip_box.setChecked(block.skip)
        self.skip_box.blockSignals(False)

    def _source_edited(self) -> None:
        block = self.current_block()
        if block is None:
            return
        block.source_text = self.source_edit.toPlainText()
        self.editor.schedule_save()

    def _skip_toggled(self) -> None:
        block = self.current_block()
        if block is None:
            return
        block.skip = self.skip_box.isChecked()
        self.canvas.refresh_styles()
        self.editor.schedule_save()

    def _select_flagged(self) -> None:
        entry = self.current_entry()
        if entry is None or not self.show_flagged.isChecked():
            return
        self.canvas.select([b.block_id for b in entry.blocks if b.flags])

    # ------------------------------------------------------------- editing
    def _add_box(self, box: Box) -> None:
        # Everything the base class does, then straight into the text field:
        # a box drawn here exists to have what the OCR missed typed into it.
        super()._add_box(box)
        self.source_edit.setFocus()

    # ------------------------------------------------------------- reading
    def _read_selected(self) -> None:
        entries = self.selected_entries()
        if not entries:
            QMessageBox.information(
                self,
                "Nothing highlighted",
                "Highlight the images you want to process, or press “Process all”.",
            )
            return
        self._read(entries)

    def _read_all(self) -> None:
        self._read(list(self.job.images))

    def _read(self, entries: list[ImageEntry]) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.worker.stop()
            return
        already = [e for e in entries if e.blocks]
        if already and QMessageBox.question(
            self,
            "Read again?",
            f"{len(already)} of the {len(entries)} image(s) have already been read.\n"
            "Reading them again replaces their boxes and any text you corrected.\n\n"
            "Continue?",
        ) != QMessageBox.Yes:
            return
        self.progress.setVisible(True)
        self.progress.setRange(0, len(entries))
        self.progress.setValue(0)
        self.process_selected.setEnabled(False)
        self.process_all.setText("Stop")
        self.worker = ReadWorker(self.job, entries, self)
        self.worker.progress.connect(self._read_progress)
        self.worker.finished_one.connect(self._read_one)
        self.worker.done.connect(self._read_done)
        self.worker.start()

    def _read_progress(self, index: int, total: int, name: str) -> None:
        self.progress.setValue(index - 1)
        self.editor.status(f"Reading {index}/{total}: {name}")

    def _read_one(self, relpath: str, reading, error: str) -> None:
        try:
            entry = self.job.find(relpath)
        except Exception:
            return
        if reading is None:
            entry.status = ERROR
            entry.error = error
        else:
            entry.adopt(reading)
            apply_flags(entry)
        self.progress.setValue(self.progress.value() + 1)
        self.editor.reload_lists()
        if entry is self.current_entry():
            self.canvas.show_image(entry, self.array)
            self._sync_panel()

    def _read_done(self, ok: int, failed: int) -> None:
        self.progress.setVisible(False)
        self.process_selected.setEnabled(True)
        self.process_all.setText("Process all")
        self.worker = None
        self.editor.save_now()
        self.editor.refresh_gates()
        note = f"Read {ok} image(s)."
        if failed:
            note += f" {failed} failed — hover a red row for the reason."
        self.editor.status(note + " " + self.editor.counts_text())

        if ok or not failed:
            return
        # Nothing at all was read. That is almost always one cause for every
        # image - no engine - rather than N separate problems, and it does not
        # fit in the status bar.
        statuses = engine_status()
        if any("ready" in text for text in statuses.values()):
            first = next(
                (e.error for e in self.job.images if e.error), "no reason recorded"
            )
            detail = "The OCR engine is installed but every image failed:\n\n" + first
        else:
            detail = (
                "No OCR engine is available.\n\n"
                + "\n".join(statuses.values())
                + "\n\nInstall it into the DazedTL environment, then restart "
                "DazedTL — a package installed while the app is open is not "
                "picked up until then."
            )
        QMessageBox.warning(self, "Could not read the images", detail)

    # ------------------------------------------------------------- confirm
    def confirm_current(self) -> None:
        entry = self.current_entry()
        if entry is None:
            return
        if not entry.blocks:
            QMessageBox.information(
                self,
                "Nothing to confirm",
                f"{entry.name} has no text boxes yet. Process it first, or add a "
                "box by hand if the reader missed the text.",
            )
            return
        entry.status = CONFIRMED
        self.editor.reload_lists()
        self.editor.save_now()
        self.editor.refresh_gates()
        # The next one that still wants looking at, not simply the next row -
        # advancing by one stalls on an already-confirmed neighbour.
        moved = self.advance(
            lambda e: bool(e.blocks) and e.status not in jobmod.REVIEWED
        )
        left = sum(
            1 for e in self.job.images
            if e.blocks and e.status not in jobmod.REVIEWED
        )
        if not moved:
            self.editor.status(
                f"{entry.name} confirmed. Every image with text is confirmed — "
                "press “Next: Translation”."
            )
        else:
            self.editor.status(f"{entry.name} confirmed. {left} still to check.")

    def stop_worker(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(3000)


# --------------------------------------------------------------------------
# step two


LANGUAGES = (
    "English", "Spanish", "French", "German", "Italian",
    "Portuguese", "Russian", "Chinese", "Korean", "Japanese",
)

ENDPOINT_PRESETS = (
    ("OpenAI", "https://api.openai.com/v1"),
    ("Claude (Anthropic)", "https://api.anthropic.com/v1"),
    ("Gemini", "https://generativelanguage.googleapis.com/v1beta/openai/"),
    ("DeepSeek", "https://api.deepseek.com/v1/"),
    ("Mistral", "https://api.mistral.ai/v1/"),
    ("Nvidia", "https://integrate.api.nvidia.com/v1/"),
)

# The shared worker writes for a terminal. QPlainTextEdit is not one, and shows
# the escape sequences as literal text wrapped around every number.
ANSI = re.compile(r"\x1b\[[0-9;]*m")

# Its preamble answers questions this step has already answered: which file
# (there is one), which module (there is one), estimate or not (two buttons).
LOG_NOISE = (
    "📁 Found",
    "   • ",
    "🔧 Using module",
    "📊 Estimate only",
)

# TranslationWorker refuses to start without these, and says so as one red line
# in a log the user has no reason to be reading yet.
REQUIRED_ENV = (
    "api", "key", "model", "language", "timeout",
    "fileThreads", "threads", "width", "listWidth",
)


class TranslateStep(QWidget):
    """Run the Image Text module here, rather than sending the user away.

    Everything below the settings is the project's own translation machinery -
    the same worker, the same subprocess runner, the same prompt, glossary, cost
    accounting and live log that the Translation tab uses. Reusing it is the
    point: an image translated here and a script translated there go through
    exactly one code path, so they cannot drift.
    """

    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.worker = None
        self._last_log = ""
        self._build()
        self.reload_settings()

    @property
    def job(self):
        return self.editor.job

    # ------------------------------------------------------------- layout
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal, self)

        left = QWidget()
        left.setMinimumWidth(360)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        api_box = QGroupBox("Translation API")
        form = QFormLayout(api_box)
        form.setLabelAlignment(Qt.AlignRight)

        key_row = QWidget()
        key_layout = QHBoxLayout(key_row)
        key_layout.setContentsMargins(0, 0, 0, 0)
        self.key_combo = QComboBox()
        self.key_combo.setToolTip(
            "The same saved keys as the Config tab. Changing it here changes it "
            "everywhere — there is one setting, shown in two places."
        )
        self.key_combo.currentIndexChanged.connect(self._key_changed)
        key_new = QToolButton()
        key_new.setText("New…")
        key_new.clicked.connect(self._new_key)
        key_layout.addWidget(self.key_combo, 1)
        key_layout.addWidget(key_new)
        form.addRow("API key", key_row)

        endpoint_row = QWidget()
        endpoint_layout = QHBoxLayout(endpoint_row)
        endpoint_layout.setContentsMargins(0, 0, 0, 0)
        self.endpoint_edit = QLineEdit()
        self.endpoint_edit.setPlaceholderText("Leave blank for the OpenAI API")
        presets = QToolButton()
        presets.setText("Presets ▾")
        presets.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(presets)
        for label, url in ENDPOINT_PRESETS:
            menu.addAction(label).triggered.connect(
                lambda _checked=False, u=url: self.endpoint_edit.setText(u)
            )
        presets.setMenu(menu)
        endpoint_layout.addWidget(self.endpoint_edit, 1)
        endpoint_layout.addWidget(presets)
        form.addRow("Endpoint", endpoint_row)

        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        form.addRow("Model", self.model_combo)

        self.language_combo = QComboBox()
        self.language_combo.addItems(LANGUAGES)
        form.addRow("Into", self.language_combo)
        left_layout.addWidget(api_box)

        mode_box = QGroupBox("How to run it")
        mode_layout = QVBoxLayout(mode_box)
        self.live_radio = QRadioButton("Live — translate now, watch it happen")
        self.live_radio.setChecked(True)
        self.batch_radio = QRadioButton(
            "Batch — Anthropic Batches API, half price, comes back later"
        )
        self.batch_radio.setToolTip(
            "Submits the whole job and polls for it. Stopping is safe: the batch "
            "keeps processing and this picks it up again next time."
        )
        mode_layout.addWidget(self.live_radio)
        mode_layout.addWidget(self.batch_radio)
        left_layout.addWidget(mode_box)

        run_row = QHBoxLayout()
        self.estimate_button = QPushButton("Estimate cost")
        self.estimate_button.setToolTip(
            "Count the tokens and price the run without sending anything."
        )
        self.estimate_button.clicked.connect(lambda: self.translate(estimate=True))
        self.translate_button = QPushButton("Translate")
        self.translate_button.setStyleSheet(GO_BUTTON)
        self.translate_button.clicked.connect(lambda: self.translate(estimate=False))
        run_row.addWidget(self.estimate_button)
        run_row.addWidget(self.translate_button, 1)
        left_layout.addLayout(run_row)

        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet("color: #9aa3b2;")
        left_layout.addWidget(self.summary_label)

        advanced = QGroupBox("If you translate it somewhere else")
        advanced_layout = QVBoxLayout(advanced)
        export_button = QPushButton("Export image_text.json only")
        export_button.setToolTip(
            "Write the exchange file without translating it, for another tool or "
            "the Translation tab's own Image Text module."
        )
        export_button.clicked.connect(self.export_only)
        import_button = QPushButton("← Load translations from file")
        import_button.setToolTip(
            "Read targets back out of image_text.json, wherever it was filled in."
        )
        import_button.clicked.connect(lambda: self.load_translations(verbose=True))
        advanced_layout.addWidget(export_button)
        advanced_layout.addWidget(import_button)
        left_layout.addWidget(advanced)
        left_layout.addStretch(1)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(QLabel("Log"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(4000)
        self.log.setFont(text_font(9.0))
        self.log.setStyleSheet("background:#11131a;color:#c8d0dc;")
        right_layout.addWidget(self.log, 1)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        right_layout.addWidget(self.progress)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_worker)
        right_layout.addWidget(self.stop_button)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([380, 880])
        outer.addWidget(splitter, 1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self.next_button = QPushButton("Next: Render →")
        self.next_button.setStyleSheet(NEXT_BUTTON)
        self.next_button.clicked.connect(lambda: self.editor.goto_step(2))
        bottom.addWidget(self.next_button)
        outer.addLayout(bottom)

    # ------------------------------------------------------------- settings
    def reload_settings(self) -> None:
        """Fill the panel from ``.env`` and the key vault, not from memory."""
        from dotenv import dotenv_values

        from util import api_keys
        from util.paths import ENV_PATH

        env = dotenv_values(ENV_PATH) if Path(ENV_PATH).exists() else {}
        self.key_combo.blockSignals(True)
        self.key_combo.clear()
        try:
            names = api_keys.list_names()
            active = api_keys.get_active_name()
        except Exception:
            names, active = [], ""
        self.key_combo.addItems(names or ["(none saved)"])
        if active and active in names:
            self.key_combo.setCurrentText(active)
        self.key_combo.blockSignals(False)

        self.endpoint_edit.setText(str(env.get("api") or ""))
        model = str(env.get("model") or "")
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        try:
            from gui.config_tab import ModelFetchThread

            self.model_combo.addItems(list(ModelFetchThread.DEFAULTS))
        except Exception:
            pass
        if model:
            if self.model_combo.findText(model) < 0:
                self.model_combo.insertItem(0, model)
            self.model_combo.setCurrentText(model)
        self.model_combo.blockSignals(False)

        language = str(env.get("language") or self.job.language or "English").capitalize()
        if self.language_combo.findText(language) < 0:
            self.language_combo.addItem(language)
        self.language_combo.setCurrentText(language)
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        confirmed = self.job.confirmed()
        blocks = sum(len(e.translatable()) for e in confirmed)
        done = sum(
            1 for e in self.job.images for b in e.blocks if b.target_text.strip()
        )
        self.summary_label.setText(
            f"{blocks} block(s) across {len(confirmed)} confirmed image(s). "
            f"{done} already translated."
        )

    def _key_changed(self) -> None:
        from util import api_keys

        name = self.key_combo.currentText()
        if not name or name == "(none saved)":
            return
        try:
            api_keys.set_active(name)
            endpoint = api_keys.get_endpoint(name)
        except Exception:
            return
        if endpoint:
            # A key with its own endpoint always applies it, the same rule the
            # Config tab uses. Two places, one behaviour.
            self.endpoint_edit.setText(endpoint)

    def _new_key(self) -> None:
        try:
            from gui.config_tab import ApiKeyEditDialog
        except Exception as exc:
            QMessageBox.warning(self, "API key", f"Could not open the key editor: {exc}")
            return
        dialog = ApiKeyEditDialog(
            self, initial_endpoint=self.endpoint_edit.text().strip()
        )
        if dialog.exec_() != dialog.Accepted:
            return
        name, secret, endpoint, keyless = dialog.result_values()
        from util import api_keys

        api_keys.upsert_key(name, secret, endpoint=endpoint, keyless=keyless)
        api_keys.set_active(name)
        self.reload_settings()

    def _save_settings(self) -> None:
        """Push the panel into ``.env`` and the vault before a run."""
        from dotenv import load_dotenv, set_key

        from util import api_keys
        from util.paths import ENV_PATH

        path = str(ENV_PATH)
        set_key(path, "api", self.endpoint_edit.text().strip())
        set_key(path, "model", self.model_combo.currentText().strip())
        set_key(path, "language", self.language_combo.currentText().strip())
        try:
            api_keys.sync_active_to_env()
        except Exception:
            pass
        self.job.language = self.language_combo.currentText().strip()
        load_dotenv(path, override=True)

    def _missing_env(self) -> list[str]:
        from dotenv import dotenv_values

        from util.paths import ENV_PATH

        env = dotenv_values(ENV_PATH) if Path(ENV_PATH).exists() else {}
        merged = {**env, **{k: v for k, v in os.environ.items() if k in REQUIRED_ENV}}
        return [
            name for name in REQUIRED_ENV
            if not str(merged.get(name) or "").strip()
            or str(merged.get(name))[:1] == "<"
        ]

    # ------------------------------------------------------------- log
    def append_log(self, message: str) -> None:
        """One line at a time, cleaned up on the way in.

        The shared worker writes for a terminal: SGR colour codes around the
        numbers, and a preamble listing the file it is about to process, the
        module it will use and whether this is an estimate. On the Translation
        tab that is orientation. Here there is exactly one file, exactly one
        module and a button that says which of the two it is, so all of it is
        noise sitting on top of the two numbers that matter.

        The worker itself is left alone: it is shared, and the tab that needs
        the preamble is entitled to keep it.
        """
        for line in str(message).rstrip("\n").splitlines() or [""]:
            line = ANSI.sub("", line).rstrip()
            if any(line.startswith(prefix) for prefix in LOG_NOISE):
                continue
            if line == self._last_log and line.strip():
                # The runner prints its grand total once as a cost line and
                # again as the success line.
                continue
            self._last_log = line
            self.log.appendPlainText(line)

    def _log_translations(self) -> None:
        """What came back, in words, beside what went out.

        The point of watching a translation run is judging it, and none of the
        cost accounting in the world helps with that. This is the only place the
        actual strings appear before the Render step draws them.
        """
        shown = 0
        for entry in self.job.images:
            # Keyed on the id, not on the block: TextBlock is a dataclass, so
            # ``block in done`` compares every field of every candidate.
            done = {
                b.block_id for b in entry.blocks
                if b.target_text.strip() and not b.skip
            }
            if not done:
                continue
            self.append_log("")
            self.append_log(f"  {entry.name}")
            for index, block in enumerate(entry.blocks, start=1):
                if block.block_id not in done:
                    continue
                source = " ".join(block.source_text.split())
                target = " ".join(block.target_text.split())
                self.append_log(f"   {index:>2}.  {source}")
                self.append_log(f"        →  {target}")
                shown += 1
        if shown:
            self.append_log("")

    # ------------------------------------------------------------- running
    def export_only(self) -> tuple[Path, Path | None] | None:
        from util.imagetools import exchange

        pending = [e for e in self.job.images if e.status == NEEDS_REVIEW]
        if pending and QMessageBox.question(
            self,
            "Confirm remaining images",
            f"{len(pending)} image(s) have been read but not confirmed.\n\n"
            "Confirm them all now and export?",
        ) == QMessageBox.Yes:
            for entry in pending:
                entry.status = CONFIRMED
        if not self.job.confirmed():
            QMessageBox.information(
                self, "Nothing to export",
                "No image has been confirmed yet. Go back to Textboxes / OCR, "
                "check the boxes, then press “Confirm this image”.",
            )
            return None
        self.editor.save_now()
        try:
            target, mirror = exchange.write(self.job)
        except Exception as exc:
            QMessageBox.warning(self, "Export failed", str(exc))
            return None
        self.editor.reload_lists()
        self.append_log(f"📄 Wrote {target}")
        if mirror is not None:
            self.append_log(f"📄 Mirrored to {mirror}")
        self._refresh_summary()
        return target, mirror

    def translate(self, estimate: bool = False) -> None:
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(
                self, "Already running", "A translation is already in progress."
            )
            return
        self._save_settings()
        missing = self._missing_env()
        if missing:
            QMessageBox.warning(
                self,
                "Settings incomplete",
                "The translator needs these settings before it can run:\n\n  "
                + "\n  ".join(missing)
                + "\n\nFill them in above, or on the Config tab for the ones "
                "that are not shown here.",
            )
            return
        written = self.export_only()
        if written is None:
            return
        target, mirror = written
        if mirror is None:
            QMessageBox.warning(
                self,
                "Cannot reach the translator",
                "The exchange file was written to\n\n"
                f"{target}\n\n"
                "but could not be mirrored into DazedTL's files/ folder, which "
                "is where the Image Text module reads from. Translate it by "
                "hand and use “Load translations from file”.",
            )
            return

        from gui.translation_tab import TranslationWorker
        from util.paths import PROJECT_ROOT

        self.log.clear()
        self._last_log = ""
        self.append_log(
            f"🖼  {'Estimating' if estimate else 'Translating'} "
            f"{mirror.name} into {self.language_combo.currentText()}"
        )
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.translate_button.setEnabled(False)
        self.estimate_button.setEnabled(False)
        self.stop_button.setEnabled(True)

        self.worker = TranslationWorker(
            Path(PROJECT_ROOT),
            _image_text_spec(),
            estimate,
            [mirror.name],
            batch_mode=self.batch_radio.isChecked() and not estimate,
        )
        self.worker.log_signal.connect(self.append_log)
        self.worker.item_progress_signal.connect(self._item_progress)
        self.worker.file_error_signal.connect(
            lambda name, error: self.append_log(f"❌ {name}: {error}")
        )
        self.worker.batch_phase_signal.connect(self._batch_phase)
        self.worker.finished_signal.connect(self._finished)
        self.worker.start()

    def _item_progress(self, _desc: str, current: int, total: int) -> None:
        if total:
            self.progress.setRange(0, total)
            self.progress.setValue(current)

    def _batch_phase(self, phase: str, payload) -> None:
        """Batch mode blocks the worker until this answers.

        ``_wait_batch_submit`` sits on an Event until ``set_batch_submit_response``
        is called, so a phase left unhandled is not a missing dialog - it is a
        thread parked forever with no sign on screen that anything is wrong.
        """
        if self.worker is None:
            return
        if phase != "submit":
            return
        cost = ""
        try:
            cost = f"\n\nEstimated cost: ${float(payload):.4f}" if payload else ""
        except (TypeError, ValueError):
            cost = f"\n\n{payload}" if payload else ""
        answer = QMessageBox.question(
            self,
            "Submit the batch?",
            "Send this job to the Batches API?" + cost + "\n\n"
            "It comes back at half price, but not immediately.",
        )
        self.worker.set_batch_submit_response(answer == QMessageBox.Yes)

    def _finished(self, success: bool, message: str) -> None:
        self.progress.setVisible(False)
        self.translate_button.setEnabled(True)
        self.estimate_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.worker = None
        self.append_log("")
        self.append_log(f"{'✅' if success else '❌'} {message}")
        if not success:
            self.editor.status(f"Translation failed: {message}")
            return
        self.load_translations(verbose=False)

    def load_translations(self, verbose: bool = True) -> None:
        from util.imagetools import exchange

        restored = (0, 0)
        try:
            # Anything the exchange knows about that the job has lost comes back
            # first, so the translations have somewhere to land.
            restored = exchange.rebuild(self.job)
            result = exchange.read(self.job)
        except Exception as exc:
            if verbose:
                QMessageBox.warning(self, "Could not load the translations", str(exc))
            else:
                self.append_log(f"❌ Could not load the translations: {exc}")
            return
        self.editor.save_now()
        self.editor.reload_lists()
        self.editor.refresh_gates()
        self._refresh_summary()
        if restored[0]:
            self.append_log(
                f"♻  Restored {restored[0]} image(s) and {restored[1]} block(s) "
                "that were missing from the job file."
            )
        for line in exchange.summarise(result):
            self.append_log(line)
        if result.applied:
            self._log_translations()
            self.append_log("→ Press “Next: Render” to see how it looks.")
        elif verbose:
            QMessageBox.information(
                self,
                "Nothing loaded",
                "\n".join(exchange.summarise(result))
                + "\n\nHas the file been translated yet?",
            )
        self.editor.status(
            f"Loaded {result.applied} translation(s). " + self.editor.counts_text()
        )

    def stop_worker(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.worker.stop()
            self.append_log("🛑 Stopping…")

    def shutdown(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(4000)


# --------------------------------------------------------------------------
# step three


class PreviewWorker(QThread):
    """Render every translated image once, so switching between them is instant.

    Off the GUI thread because the first pass over an image also *measures* it,
    which is the slow part - a dozen morphological passes per block. The panel is
    disabled while this runs, so nothing edits a style out from under it.
    """

    one = pyqtSignal(str, object, object)      # relpath, array, notes
    progress = pyqtSignal(int, int, str)
    done = pyqtSignal(int)

    def __init__(self, job, entries: list[ImageEntry], parent=None):
        super().__init__(parent)
        self.job = job
        self.entries = entries
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        total = len(self.entries)
        made = 0
        for index, entry in enumerate(self.entries, start=1):
            if self._stop:
                break
            self.progress.emit(index, total, entry.name)
            try:
                result = rendermod.render_job_image(self.job, entry)
            except Exception as exc:
                self.one.emit(
                    entry.relpath, None, [rendermod.Note("", False, str(exc))]
                )
                continue
            made += 1
            self.one.emit(entry.relpath, result.array, result.notes)
        self.done.emit(made)


class RenderStep(ImageStep):
    """See the result, fix what is wrong, write the files.

    Every field on the right was measured from the pixels and is usually already
    right; it is here so the handful that are wrong take a second to fix, not so
    the user can describe a picture they are looking at. The preview renders the
    real thing - same code path as the file that gets written - because a preview
    that is merely representative is worse than none.
    """

    def __init__(self, editor, parent=None):
        super().__init__(editor, parent)
        self.array: np.ndarray | None = None
        self.layer: np.ndarray | None = None
        # What the eraser took out of the picture, kept beside the paint rather
        # than in it - see ``util.imagetools.paint``.
        self.cut: np.ndarray | None = None
        # Which image the layer in hand belongs to. Without it, moving to the
        # next image saved the outgoing strokes against the incoming entry - or,
        # once ``confirm`` started advancing on its own, dropped them entirely.
        self._layer_of: str | None = None
        self._layer_dirty = False
        self.previews: dict[str, np.ndarray] = {}
        self.notes: dict[str, list] = {}
        self.approved: set[str] = set()
        self.worker: PreviewWorker | None = None
        self._swept = False
        self._syncing = False
        self._build()

    # ------------------------------------------------------------- layout
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Horizontal, self)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("Translated images"))
        self.list = self._make_list(multi=True)
        left_layout.addWidget(self.list, 1)
        self.restore_button = QPushButton("Undo render on this image")
        self.restore_button.setToolTip(
            "Put the original PNG back. The boxes, text and translations stay."
        )
        self.restore_button.clicked.connect(self._restore_current)
        left_layout.addWidget(self.restore_button)
        splitter.addWidget(left)

        centre = QWidget()
        centre_layout = QVBoxLayout(centre)
        centre_layout.setContentsMargins(0, 0, 0, 0)
        self.canvas = PaintCanvas()
        self.canvas.selection_changed.connect(self._sync_panel)
        self.canvas.geometry_changed.connect(self._geometry_changed)
        self.canvas.box_added.connect(self._add_box)
        self.canvas.painted.connect(self._painted)
        self.canvas.stroking.connect(self._stroking)
        self.canvas.probed.connect(self._probed)
        self.canvas.tool_changed.connect(self._tool_changed)
        self.canvas.size_changed.connect(self._brush_size_chosen)
        self.canvas.background_at = self._background_at
        centre_layout.addLayout(self._build_view_row())
        centre_layout.addWidget(self.canvas, 1)
        centre_layout.addLayout(self._build_tools())
        centre_layout.addLayout(self._build_box_row())
        splitter.addWidget(centre)

        splitter.addWidget(self._build_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([210, 690, 360])
        outer.addWidget(splitter, 1)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        outer.addWidget(self.progress)

        bottom = QHBoxLayout()
        self.confirm_button = QPushButton("✓ Confirm this image")
        self.confirm_button.setStyleSheet(GO_BUTTON)
        self.confirm_button.setToolTip(
            "Mark this one as looking right, and move to the next unchecked image."
        )
        self.confirm_button.clicked.connect(self.confirm_current)
        bottom.addWidget(self.confirm_button)
        bottom.addStretch(1)
        self.render_selected_button = QPushButton("Render selected")
        self.render_selected_button.setToolTip(
            "Write the highlighted images. With nothing highlighted, the ones "
            "you have confirmed."
        )
        self.render_selected_button.clicked.connect(self._render_selected)
        self.render_all_button = QPushButton("Render all")
        self.render_all_button.setStyleSheet(NEXT_BUTTON)
        self.render_all_button.clicked.connect(self._render_all)
        bottom.addWidget(self.render_selected_button)
        bottom.addWidget(self.render_all_button)
        outer.addLayout(bottom)

    def _build_view_row(self) -> QHBoxLayout:
        """The row above the picture: what is being looked at, not what is done to it."""
        row = QHBoxLayout()
        self.original_box = QCheckBox("Show original")
        self.original_box.setToolTip(
            "Swap back to the untouched Japanese, so the change can be judged "
            "against what was there. Nothing is edited while it is ticked."
        )
        self.original_box.stateChanged.connect(self._toggle_original)
        row.addWidget(self.original_box)

        self.boxes_box = QCheckBox("Show boxes")
        self.boxes_box.setChecked(True)
        self.boxes_box.setToolTip(
            "Hide the frames to judge the picture on its own. The blocks stay "
            "where they are and can still be clicked."
        )
        self.boxes_box.stateChanged.connect(
            lambda: self.canvas.set_boxes_visible(self.boxes_box.isChecked())
        )
        row.addWidget(self.boxes_box)
        row.addStretch(1)
        fit_button = QPushButton("Fit")
        fit_button.clicked.connect(self.canvas.fit)
        row.addWidget(fit_button)
        return row

    def _build_tools(self) -> QHBoxLayout:
        tools = QHBoxLayout()
        self.select_tool = _tool_button(
            "mdi6.cursor-default-outline",
            "Select  (V)\nMove and resize the boxes.",
        )
        self.pencil_tool = _tool_button(
            "mdi6.pencil",
            "Pencil  (B)\n"
            "Paint under the English — repair a background the erase step got "
            "wrong.\n"
            "Alt-click to pick a colour off the picture.  Alt + right-drag to "
            "resize.\nHold space or the wheel button to pan without changing tool.",
        )
        self.eraser_tool = _tool_button(
            "mdi6.eraser",
            "Eraser  (E)\n"
            "On its own: rub out your own paint and cuts.\n"
            "Ctrl: erase the picture itself to transparency, the way Photoshop's "
            "eraser does.\n"
            "Shift: paint the block's measured background, for a glyph on a "
            "surface that has to stay opaque.",
        )
        # An exclusive group, so the one in use stays lit. Three independent
        # checkable buttons let a second click on the active tool un-check it -
        # the tool did not change, so nothing put the highlight back, and the
        # row then showed no tool selected while a tool was plainly selected.
        self.tool_group = QButtonGroup(self)
        self.tool_group.setExclusive(True)
        for button, tool in (
            (self.select_tool, TOOL_SELECT),
            (self.pencil_tool, TOOL_PENCIL),
            (self.eraser_tool, TOOL_ERASER),
        ):
            self.tool_group.addButton(button)
            button.clicked.connect(lambda _c=False, t=tool: self.canvas.set_tool(t))
            tools.addWidget(button)
        self.select_tool.setChecked(True)

        tools.addSpacing(10)
        tools.addWidget(QLabel("Size"))
        self.brush_slider = QSlider(Qt.Horizontal)
        self.brush_slider.setRange(paintmod.MIN_SIZE, paintmod.MAX_SIZE)
        self.brush_slider.setValue(paintmod.DEFAULT_SIZE)
        self.brush_slider.setMinimumWidth(120)
        self.brush_slider.setToolTip(
            "Brush width in pixels, edge to edge.  ( [  and  ] , or Alt + "
            "right-drag on the image.)"
        )
        self.brush_slider.valueChanged.connect(self._brush_size_chosen)
        tools.addWidget(self.brush_slider, 1)
        self.brush_spin = QSpinBox()
        self.brush_spin.setRange(paintmod.MIN_SIZE, paintmod.MAX_SIZE)
        self.brush_spin.setValue(paintmod.DEFAULT_SIZE)
        self.brush_spin.setSuffix(" px")
        self.brush_spin.setMaximumWidth(76)
        self.brush_spin.valueChanged.connect(self._brush_size_chosen)
        tools.addWidget(self.brush_spin)

        self.brush_colour = ColourButton()
        self.brush_colour.setToolTip("What the pencil paints. Alt-click the image to sample.")
        self.brush_colour.set_colour([255, 255, 255, 255])
        self.brush_colour.picked.connect(self.canvas.set_brush_colour)
        tools.addWidget(self.brush_colour)

        self.undo_button = QPushButton("Undo stroke")
        self.undo_button.setToolTip("Step back through your brush strokes.  (Ctrl+Z)")
        self.undo_button.clicked.connect(self.canvas.undo)
        tools.addWidget(self.undo_button)
        return tools

    def _build_box_row(self) -> QHBoxLayout:
        """Create and rearrange blocks without going back to the review tab.

        The same four operations that step offers, on the same objects. A box
        that is a line too short is something you find out by looking at the
        render, and the fix belongs where the problem is visible.
        """
        row = QHBoxLayout()
        self.add_button = QPushButton("Add box")
        self.add_button.setIcon(get_icon("mdi6.vector-square"))
        self.add_button.setCheckable(True)
        self.add_button.setToolTip(
            "Drag a new block onto the picture — for text the reader never "
            "found, or a caption being written from scratch."
        )
        self.add_button.clicked.connect(
            lambda: self.canvas.set_adding(self.add_button.isChecked())
        )
        self.merge_button = QPushButton("Merge")
        self.merge_button.setIcon(get_icon("mdi6.call-merge"))
        self.merge_button.setToolTip(
            "Join the highlighted blocks into one, keeping both the source "
            "lines and the translations."
        )
        self.merge_button.clicked.connect(self._merge)
        self.split_button = QPushButton("Split")
        self.split_button.setIcon(get_icon("mdi6.call-split"))
        self.split_button.setToolTip("Break this block back into its separate lines.")
        self.split_button.clicked.connect(self._split)
        self.delete_button = QPushButton("Delete")
        self.delete_button.setIcon(get_icon("mdi6.delete-outline"))
        self.delete_button.setToolTip(
            "Remove the highlighted blocks. The picture under them is left "
            "exactly as it is."
        )
        self.delete_button.clicked.connect(self._delete)
        for button in (
            self.add_button, self.merge_button, self.split_button, self.delete_button
        ):
            row.addWidget(button)
        row.addStretch(1)
        return row

    def _brush_size_chosen(self, size: int) -> None:
        """One brush width, shown in three places that must not fight."""
        size = paintmod.clamp_size(size)
        for widget in (self.brush_slider, self.brush_spin):
            if widget.value() != size:
                widget.blockSignals(True)
                widget.setValue(size)
                widget.blockSignals(False)
        self.canvas.set_brush_size(size)

    def _toggle_original(self) -> None:
        showing = self.original_box.isChecked()
        # The brushes paint onto the render, not onto the original, so while the
        # original is up they go away rather than quietly painting on something
        # the user cannot see.
        if showing:
            self.canvas.set_tool(TOOL_SELECT)
        for button in (self.pencil_tool, self.eraser_tool):
            button.setEnabled(not showing)
        entry = self.current_entry()
        if entry is None or self.array is None:
            return
        if showing:
            self.canvas.set_pixels(self.array)
            self.editor.status(f"{entry.name} — showing the original.")
        else:
            self.canvas.set_pixels(self.previews.get(entry.relpath, self.array))
            self.editor.status(f"{entry.name}. " + self.editor.counts_text())

    def _build_panel(self) -> QWidget:
        """The block panel, inside something that can scroll.

        There are eleven rows of controls here and a 1080p screen has a fixed
        amount of room for them. Without the scroll area the rows past the
        bottom are not merely cut off - Qt compresses every row to fit and they
        draw over each other, which is the same panel reported as overflowing
        with three rows fewer.
        """
        scroller = QScrollArea()
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QScrollArea.NoFrame)
        # Never sideways: the fields grow and shrink with the panel, so a
        # horizontal bar would only ever mean something is demanding more width
        # than it should, and hiding that is how the labels got clipped.
        scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroller.setMinimumWidth(360)

        panel = self.param_panel = QWidget()
        panel.setMinimumWidth(340)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        self.block_title = QLabel("No block selected")
        layout.addWidget(self.block_title)
        layout.addWidget(QLabel("Original text"))
        # Read-only but not a label: the whole point is being able to select a
        # line of it and paste it into a dictionary, which a QLabel cannot do
        # and which is exactly what happens when a translation looks wrong.
        self.source_view = QPlainTextEdit()
        self.source_view.setReadOnly(True)
        self.source_view.setFont(text_font())
        self.source_view.setMaximumHeight(72)
        self.source_view.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
        )
        self.source_view.setStyleSheet("background:#181b22;color:#c8d0dc;")
        layout.addWidget(self.source_view)
        layout.addWidget(QLabel("Translation"))
        self.target_edit = QPlainTextEdit()
        self.target_edit.setFont(text_font())
        self.target_edit.setPlaceholderText("filled in by the translator — editable here")
        self.target_edit.setMaximumHeight(96)
        self.target_edit.textChanged.connect(self._target_edited)
        layout.addWidget(self.target_edit)

        self.style_summary = QLabel("Select a block to see how it was set.")
        self.style_summary.setWordWrap(True)
        layout.addWidget(self.style_summary)

        form = self.param_form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        # A QFormLayout gives the field column whatever its widgets ask for and
        # the label column what is left. A combo asks for its longest item, and
        # its longest item here is a sentence - so at 1080p the labels were
        # squeezed until "Reconstruct with" ran off its own cell. Capping what
        # the fields demand is what gives the labels their width back.
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        # And when the two together still will not fit - a long label beside a
        # dropdown, on a panel the user has dragged narrow - the field drops to
        # its own line rather than the label losing its last few characters.
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        form.setHorizontalSpacing(8)

        self.bg_combo = _wide_combo()
        for name in BACKGROUNDS:
            self.bg_combo.addItem(BACKGROUND_LABELS[name], name)
        self.bg_combo.setToolTip(
            "How the space under the old text is put back. The measured choice "
            "is almost always the right one; the rest are here for the images "
            "where it is not."
        )
        self.bg_combo.currentIndexChanged.connect(self._style_edited)
        form.addRow("Inpainting method", self.bg_combo)

        self.inpaint_combo = _wide_combo()
        for name in inpaintmod.METHODS:
            self.inpaint_combo.addItem(inpaintmod.METHOD_LABELS[name], name)
        self.inpaint_combo.setToolTip(
            "Which reconstruction fills the hole. The two fast ones ship with "
            "the tool and diffuse the surrounding colour inwards, which is "
            "honest on flat backgrounds and a smear on patterned ones. "
            "PatchMatch and the three models keep the pattern going, cost a "
            "download, and are slower by a factor of hundreds — anything "
            "missing says so here rather than failing at render time."
        )
        self.inpaint_combo.currentIndexChanged.connect(self._style_edited)
        form.addRow("Inpainting model", self.inpaint_combo)

        colour_row = QWidget()
        colour_layout = QHBoxLayout(colour_row)
        colour_layout.setContentsMargins(0, 0, 0, 0)
        self.colour_button = ColourButton()
        self.colour_button.picked.connect(lambda _c: self._style_edited())
        self.opacity_spin = _small_spin(1, 100, " %")
        self.opacity_spin.setToolTip(
            "How opaque the type is. Measured from the original glyphs, which "
            "matters on artwork that is itself part-transparent — type cut into "
            "a 70% name plate is 70% type, and drawing it solid is as wrong as "
            "drawing solid type at 70%."
        )
        self.opacity_spin.valueChanged.connect(self._style_edited)
        colour_layout.addWidget(self.colour_button, 1)
        colour_layout.addWidget(self.opacity_spin)
        form.addRow("Text colour", colour_row)

        outline_row = QWidget()
        outline_layout = QHBoxLayout(outline_row)
        outline_layout.setContentsMargins(0, 0, 0, 0)
        self.outline_box = QCheckBox()
        self.outline_box.stateChanged.connect(self._style_edited)
        self.outline_button = ColourButton()
        self.outline_button.picked.connect(lambda _c: self._style_edited())
        self.outline_width = _small_spin(1, stylemod.MAX_OUTLINE, " px")
        self.outline_width.valueChanged.connect(self._style_edited)
        outline_layout.addWidget(self.outline_box)
        outline_layout.addWidget(self.outline_button, 1)
        outline_layout.addWidget(self.outline_width)
        self.outline_box.setToolTip(
            "The stroke around the glyphs. Measured from inside the ink, since "
            "a stroke contrasts with the background by definition. It grows "
            "outwards from every edge, like Photoshop's “Stroke: Outside” — so "
            "the counter of an “a” stays open until the stroke is wider than "
            "half of it, and then closes."
        )
        form.addRow("Stroke", outline_row)

        self.font_combo = _wide_combo()
        for label, path in font_choices():
            self.font_combo.addItem(label, path)
        self.font_combo.setToolTip(
            "Every face installed on this machine. The one thing the pixels "
            "cannot tell us — everything else on this panel was measured; this "
            "is a choice."
        )
        # Long list, so let typing jump to a family instead of scrolling to it.
        self.font_combo.setMaxVisibleItems(24)
        self.font_combo.currentIndexChanged.connect(self._style_edited)
        form.addRow("Font family", self.font_combo)

        # Two knobs to a row from here down. Each of these is three or four
        # characters wide and each used to be given the whole panel to hold
        # them, which pushed the rest of the form off the bottom of a 1080p
        # screen for no gain at all.
        self.bold_box = _icon_toggle("mdi6.format-bold", "Bold")
        self.italic_box = _icon_toggle("mdi6.format-italic", "Italic")
        for box in (self.bold_box, self.italic_box):
            box.setToolTip(
                "Bold and Italic are separate files, not a switch — a face is "
                "offered here only when this machine has that cut of it."
            )
            box.clicked.connect(self._style_edited)
        self.align_combo = QComboBox()
        for name in stylemod.ALIGNMENTS:
            self.align_combo.addItem(name.capitalize(), name)
        self.align_combo.setMaximumWidth(110)
        self.align_combo.currentIndexChanged.connect(self._style_edited)
        form.addRow("Style", _row(self.bold_box, self.italic_box,
                                  QLabel("Align"), self.align_combo, stretch=True))

        self.cap_spin = _small_spin(5, 400, " px")
        self.cap_spin.setToolTip(
            "How tall the capitals stand, in pixels — measured off the original "
            "glyphs. Raise it and the type grows until it reaches the edges of "
            "the block, then stops, unless “Overflow” beside it is on."
        )
        self.cap_spin.valueChanged.connect(self._style_edited)
        self.overflow_box = _icon_toggle("mdi6.arrow-expand-all", "Overflow")
        self.overflow_box.setToolTip(
            "Draw the type at the size asked for even where the block cannot "
            "hold it, letting it spill outside. Off, a translation longer than "
            "the Japanese is shrunk until it fits — which is right for a label "
            "on a fixed plate and wrong when you have decided you want it "
            "bigger. What gets erased does not change either way."
        )
        self.overflow_box.clicked.connect(self._style_edited)
        self.tracking_spin = _small_spin(-200, 1000, "")
        self.tracking_spin.setSingleStep(10)
        self.tracking_spin.setToolTip(
            "Letter spacing, in thousandths of an em — Photoshop's units, so a "
            "number copied off that panel means the same thing here. Relative "
            "to the type, so it survives the fit ladder shrinking the block."
        )
        self.tracking_spin.valueChanged.connect(self._style_edited)
        form.addRow("Size", _row(self.cap_spin, self.overflow_box,
                                 QLabel("Tracking"), self.tracking_spin, stretch=True))

        self.width_spin = _small_spin(10, 400, " %")
        self.width_spin.setToolTip(
            "Horizontal scale. A real stretch of the drawn glyphs, which is "
            "what fits a long translation into a narrow plate without dropping "
            "the type below the size of every other label in the game."
        )
        self.width_spin.valueChanged.connect(self._style_edited)
        self.height_spin = _small_spin(10, 400, " %")
        self.height_spin.setToolTip(
            "Vertical scale. Height only — the letters get taller or shorter "
            "and stay exactly as wide, which is the whole point of having it "
            "separate from the size above."
        )
        self.height_spin.valueChanged.connect(self._style_edited)
        form.addRow("Width", _row(self.width_spin,
                                  QLabel("Height"), self.height_spin, stretch=True))
        layout.addLayout(form)

        self.style_notes = QLabel("")
        self.style_notes.setWordWrap(True)
        # Selectable because this is where a backend explains why it will not
        # run, and those messages name paths and exceptions that are worth
        # being able to copy rather than retype.
        self.style_notes.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.style_notes.setStyleSheet("color: #9aa3b2;")
        layout.addWidget(self.style_notes)

        row = QHBoxLayout()
        self.remeasure_button = QPushButton("Reset")
        self.remeasure_button.setToolTip(
            "Throw away everything set on this panel and read it off the image "
            "again."
        )
        self.remeasure_button.clicked.connect(self._remeasure)
        row.addWidget(self.remeasure_button)
        row.addStretch(1)
        layout.addLayout(row)

        self.render_notes = QLabel("")
        self.render_notes.setWordWrap(True)
        layout.addWidget(self.render_notes)
        layout.addStretch(1)
        scroller.setWidget(panel)
        return scroller

    # ------------------------------------------------------------- list
    def _ordered_entries(self) -> list[ImageEntry]:
        return [e for e in self.job.images if self._renderable(e)]

    @staticmethod
    def _renderable(entry: ImageEntry) -> bool:
        return any(b.target_text.strip() and not b.skip for b in entry.blocks)

    def _decorate(self, item: QListWidgetItem, entry: ImageEntry) -> None:
        if entry.relpath in self.approved or entry.status == RENDERED:
            item.setForeground(QBrush(GREEN))
        problems = [n for n in self.notes.get(entry.relpath, []) if not n.ok]
        if problems:
            item.setText(item.text() + f" ⚠{len(problems)}")
            item.setForeground(QBrush(QColor(224, 168, 62)))

    # ------------------------------------------------------------- entering
    def enter(self) -> None:
        """Called when the tab is opened. Sweeps the previews once."""
        self.reload_list()
        if self._swept:
            self.open_current()
            return
        self._swept = True
        entries = self._ordered_entries()
        if not entries:
            return
        # The one on screen first and synchronously, so there is something to
        # look at while the rest are worked through.
        self.open_current()
        rest = [e for e in entries if e.relpath != self.current_relpath()]
        if not rest:
            return
        self._set_panel_enabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, len(rest))
        self.worker = PreviewWorker(self.job, rest, self)
        self.worker.progress.connect(self._sweep_progress)
        self.worker.one.connect(self._sweep_one)
        self.worker.done.connect(self._sweep_done)
        self.worker.start()

    def _sweep_progress(self, index: int, total: int, name: str) -> None:
        self.progress.setValue(index - 1)
        self.editor.status(f"Preparing preview {index}/{total}: {name}")

    def _sweep_one(self, relpath: str, array, notes) -> None:
        if array is not None:
            self.previews[relpath] = array
        self.notes[relpath] = list(notes or [])
        self.progress.setValue(self.progress.value() + 1)

    def _sweep_done(self, made: int) -> None:
        self.progress.setVisible(False)
        self.worker = None
        self._set_panel_enabled(True)
        self.editor.reload_lists()
        self.editor.save_now()          # the sweep measured styles worth keeping
        problems = sum(
            1 for notes in self.notes.values() for note in notes if not note.ok
        )
        self.editor.status(
            f"{made} preview(s) ready."
            + (f" {problems} block(s) need attention — see the ⚠ marks." if problems else "")
        )

    def _set_panel_enabled(self, enabled: bool) -> None:
        for widget in (
            self.bg_combo, self.inpaint_combo, self.colour_button, self.opacity_spin,
            self.outline_box, self.outline_button,
            self.outline_width, self.cap_spin, self.align_combo, self.font_combo,
            self.tracking_spin, self.width_spin, self.height_spin,
            self.bold_box, self.italic_box, self.overflow_box,
            self.remeasure_button, self.target_edit,
            self.render_selected_button, self.render_all_button, self.confirm_button,
        ):
            widget.setEnabled(enabled)

    # ------------------------------------------------------------- preview
    def open_current(self) -> None:
        from gui.imagetext_canvas import load_array

        # Whatever was painted on the way out goes to disk before the layer is
        # swapped. Confirming advances on its own, so "the user will save it"
        # is not a thing that happens.
        self.save_layer()
        entry = self.current_entry()
        if entry is None:
            self.canvas.show_image(None, None)
            self.array = self.layer = self.cut = None
            self._layer_of = None
            self.canvas.set_layer(None, None)
            return
        self.array = load_array(self.job.source_path(entry))
        if self.array is None:
            self.canvas.show_image(None, None)
            return
        self.layer = paintmod.load_layer(self.job, entry, self.array.shape)
        self.cut = paintmod.load_cut(self.job, entry, self.array.shape)
        self._layer_of = entry.relpath
        self._layer_dirty = False
        self.canvas.set_layer(self.layer, self.cut)
        # No pieces from the sweep - it renders on a worker thread and keeping
        # two extra full-size arrays per image would cost more memory than the
        # previews themselves. The first refresh on this image supplies them.
        self.canvas.set_render(None, None)
        self.canvas.show_image(
            entry,
            self.array if self.original_box.isChecked()
            else self.previews.get(entry.relpath, self.array),
        )
        self.refresh_preview()
        self._sync_panel()
        self.editor.status(f"{entry.name}. " + self.editor.counts_text())

    def refresh_preview(self) -> None:
        entry = self.current_entry()
        if entry is None or self.array is None:
            return
        try:
            result = rendermod.render_entry(
                self.array, entry, paint=self.layer, cut=self.cut
            )
        except Exception as exc:
            self.render_notes.setText(f"Preview failed: {exc}")
            return
        self.previews[entry.relpath] = result.array
        self.notes[entry.relpath] = result.notes
        # The brush draws from these between renders, so they are handed over
        # before the picture is, never after.
        self.canvas.set_render(result.base, result.overlay)
        if not self.original_box.isChecked():
            self.canvas.set_pixels(result.array)
        self.render_notes.setText(self._note_text(entry))

    def invalidate(self) -> None:
        """This image's preview is stale. Redraw on the shared debounce."""
        self.editor.schedule_preview()

    def _note_text(self, entry: ImageEntry) -> str:
        by_id = {block.block_id: index for index, block in enumerate(entry.blocks, 1)}
        selected = set(self.canvas.selected_ids())
        lines = []
        for note in self.notes.get(entry.relpath, []):
            if note.ok and not note.tight and note.block_id not in selected:
                continue
            mark = "✓" if note.ok else "✕"
            lines.append(f"{mark} {by_id.get(note.block_id, '?')}. {note.message}")
        if lines:
            return "\n".join(lines)
        problems = [n for n in self.notes.get(entry.relpath, []) if not n.ok]
        return "Every block fits." if not problems else ""

    # ------------------------------------------------------------- panel
    def current_block(self) -> TextBlock | None:
        entry = self.current_entry()
        ids = self.canvas.selected_ids()
        if entry is None or len(ids) != 1:
            return None
        try:
            return entry.block(ids[0])
        except Exception:
            return None

    def _style_for(self, block: TextBlock) -> Style:
        if block.style is None:
            entry = self.current_entry()
            boxes = [b.box for b in entry.blocks] if entry else []
            if self.array is None:
                block.style = Style()
            else:
                block.style = stylemod.measure(self.array, block, boxes)
        return block.style

    def _sync_panel(self) -> None:
        block = self.current_block()
        entry = self.current_entry()
        widgets = (
            self.bg_combo, self.inpaint_combo, self.colour_button, self.opacity_spin,
            self.outline_box, self.outline_button,
            self.outline_width, self.cap_spin, self.align_combo, self.font_combo,
            self.tracking_spin, self.width_spin, self.height_spin,
            self.bold_box, self.italic_box, self.overflow_box,
            self.remeasure_button, self.target_edit,
        )
        if block is None:
            for widget in widgets:
                widget.setEnabled(False)
            self.block_title.setText("No block selected")
            self.style_summary.setText("Select a block to see how it was set.")
            self.style_notes.setText("")
            self._syncing = True
            self.target_edit.setPlainText("")
            self.source_view.setPlainText("")
            self._syncing = False
            if entry is not None:
                self.render_notes.setText(self._note_text(entry))
            return
        for widget in widgets:
            widget.setEnabled(True)
        style = self._style_for(block)
        orientation = "vertical" if block.vertical else "horizontal"
        # The number on the box, its size, and which way it runs. Deliberately
        # not the source text: that is in full, selectable, two lines below, and
        # a truncated unselectable copy of it above only asked to be read twice.
        ordinal = 1 + next(
            (i for i, b in enumerate(entry.blocks) if b.block_id == block.block_id), 0
        )
        self.block_title.setText(
            f"Block {ordinal} · {block.box.w}×{block.box.h} px · {orientation}"
        )

        self._syncing = True
        try:
            self.source_view.setPlainText(block.source_text)
            self.target_edit.setPlainText(block.target_text)
            self.bg_combo.setCurrentIndex(max(0, self.bg_combo.findData(style.background)))
            self.inpaint_combo.setCurrentIndex(
                max(0, self.inpaint_combo.findData(
                    style.inpaint_method or inpaintmod.DEFAULT
                ))
            )
            self.inpaint_combo.setEnabled(style.background == stylemod.BG_INPAINT)
            self.colour_button.set_colour(style.text_color)
            alpha = style.text_color[3] if len(style.text_color) > 3 else 255
            self.opacity_spin.setValue(max(1, round(alpha * 100 / 255)))
            self.outline_box.setChecked(bool(style.outline_color))
            self.outline_button.set_colour(style.outline_color or [0, 0, 0, 255])
            self.outline_button.setEnabled(bool(style.outline_color))
            self.outline_width.setEnabled(bool(style.outline_color))
            self.outline_width.setValue(max(1, style.outline_width))
            self.cap_spin.setValue(max(self.cap_spin.minimum(), style.cap_height))
            self.align_combo.setCurrentIndex(max(0, self.align_combo.findData(style.align)))
            self.font_combo.setCurrentIndex(max(0, self.font_combo.findData(style.font)))
            self.tracking_spin.setValue(style.tracking)
            self.width_spin.setValue(max(self.width_spin.minimum(), style.scale_x))
            self.height_spin.setValue(max(self.height_spin.minimum(), style.scale_y))
            self.bold_box.setChecked(style.bold)
            self.italic_box.setChecked(style.italic)
            self.overflow_box.setChecked(style.overflow)
            self._sync_cuts(style.font)
        finally:
            self._syncing = False

        if style.locked:
            summary = "Set by you."
        else:
            summary = f"Measured from the image · {round(style.confidence * 100)}% confident."
        self.style_summary.setText(summary)
        self.style_notes.setText("\n".join(style.notes))
        if entry is not None:
            self.render_notes.setText(self._note_text(entry))

    def _sync_cuts(self, font: str) -> None:
        """Offer Bold and Italic only where the family has that file.

        Left enabled they would be two buttons that visibly do nothing on
        roughly half the faces on the machine, which is worse than not being
        offered - a control that fails silently teaches the user to distrust
        the whole panel. Each is asked about the combination it would produce,
        so on a family with no Bold Italic the second one goes out once the
        first is pressed.
        """
        try:
            path = fontsmod.resolve_font(font or None)
        except Exception:
            path = ""
        bold, italic = self.bold_box.isChecked(), self.italic_box.isChecked()
        for box, wanted in (
            (self.bold_box, (True, italic)),
            (self.italic_box, (bold, True)),
        ):
            has = bool(path) and fontsmod.has_variant(path, *wanted)
            box.setEnabled(has)
            if not has and box.isChecked():
                box.setChecked(False)

    def _target_edited(self) -> None:
        """The translation is editable here too.

        Not a duplicate of the Translation step: this is where the user is
        standing when the preview shows a line two words too long, and making
        them go back a tab to shorten it would be the point at which the loop
        stops being usable.
        """
        if self._syncing:
            return
        block = self.current_block()
        if block is None:
            return
        block.target_text = self.target_edit.toPlainText()
        self.editor.schedule_save()
        self.invalidate()

    def _style_edited(self) -> None:
        if self._syncing:
            return
        block = self.current_block()
        if block is None:
            return
        entry = self.current_entry()
        style = self._style_for(block)
        chosen = self.bg_combo.currentData()
        if self.array is None or entry is None:
            style.background = chosen
        else:
            # Sample whatever the method needs while the image is in hand.
            # Setting only the name is how a block reached the renderer marked
            # "vgradient" with no gradient in it, and came back with a complaint
            # about its own internals.
            problem = stylemod.adopt_background(
                self.array, style, block.box,
                [b.box for b in entry.blocks if b.block_id != block.block_id],
                chosen,
            )
            if problem:
                self.style_notes.setText(problem)
        style.inpaint_method = self.inpaint_combo.currentData()
        self.inpaint_combo.setEnabled(chosen == stylemod.BG_INPAINT)
        if chosen == stylemod.BG_INPAINT and not inpaintmod.available(
            style.inpaint_method
        ):
            self.style_notes.setText(inpaintmod.status(style.inpaint_method))
        opacity = round(self.opacity_spin.value() * 255 / 100)
        style.text_color = (self.colour_button.colour() or style.text_color)[:3] + [
            opacity
        ]
        if self.outline_box.isChecked():
            style.outline_color = (
                self.outline_button.colour() or [0, 0, 0, 255]
            )[:3] + [opacity]
            style.outline_width = self.outline_width.value()
        else:
            style.outline_color = None
            style.outline_width = 0
        self.outline_button.setEnabled(self.outline_box.isChecked())
        self.outline_width.setEnabled(self.outline_box.isChecked())
        style.cap_height = self.cap_spin.value()
        style.align = self.align_combo.currentData()
        style.font = self.font_combo.currentData()
        style.tracking = self.tracking_spin.value()
        style.scale_x = self.width_spin.value()
        style.scale_y = self.height_spin.value()
        style.overflow = self.overflow_box.isChecked()
        # Before the two cuts are read, not after: whether Bold is on offer at
        # all is a property of the family just chosen, not of the one before
        # it, and a box this turns off must not still reach the style.
        self._sync_cuts(style.font)
        style.bold = self.bold_box.isChecked()
        style.italic = self.italic_box.isChecked()
        style.locked = True
        self.style_summary.setText("Set by you.")
        self.editor.schedule_save()
        self.invalidate()

    def _remeasure(self) -> None:
        block = self.current_block()
        entry = self.current_entry()
        if block is None or entry is None or self.array is None:
            return
        block.style = stylemod.measure(self.array, block, [b.box for b in entry.blocks])
        self._sync_panel()
        self.editor.schedule_save()
        self.invalidate()

    def _geometry_changed(self) -> None:
        self.editor.schedule_save()
        self.invalidate()

    # ------------------------------------------------------------- painting
    def _tool_changed(self, tool: str) -> None:
        for button, name in (
            (self.select_tool, TOOL_SELECT),
            (self.pencil_tool, TOOL_PENCIL),
            (self.eraser_tool, TOOL_ERASER),
        ):
            button.setChecked(tool == name)

    def _probed(self, rgba) -> None:
        self.brush_colour.set_colour(list(rgba))
        self.editor.status(
            f"Picked #{rgba[0]:02x}{rgba[1]:02x}{rgba[2]:02x} — the pencil is loaded with it."
        )

    def _stroking(self) -> None:
        """Mid-stroke. The canvas is already showing it; nothing else to do.

        Deliberately not a re-render and not a save. Both used to fire on every
        mouse-move event, which restarted their debounce timers on every event,
        which meant neither ever ran until the mouse stopped - so the stroke was
        invisible for exactly as long as it was being drawn.
        """
        self._layer_dirty = True

    def _painted(self) -> None:
        self._layer_dirty = True
        self.invalidate()
        self.editor.schedule_save()

    def _background_at(self, point) -> list[int] | None:
        """The measured background under a point, for Ctrl + eraser.

        Gradients are sampled at the right row or column rather than averaged:
        a header band's whole point is that its colour changes down the box, and
        painting its mean over one line of it is visible immediately.
        """
        entry = self.current_entry()
        if entry is None:
            return None
        x, y = int(round(point[0])), int(round(point[1]))
        for block in entry.blocks:
            box = block.box
            if not (box.x <= x < box.x + box.w and box.y <= y < box.y + box.h):
                continue
            style = block.style
            if style is None:
                continue
            if style.background == stylemod.BG_VGRADIENT and style.row_colors:
                row = min(len(style.row_colors) - 1, max(0, y - box.y))
                return list(style.row_colors[row])
            if style.background == stylemod.BG_HGRADIENT and style.column_colors:
                column = min(len(style.column_colors) - 1, max(0, x - box.x))
                return list(style.column_colors[column])
            if style.fill:
                return list(style.fill)
        return None

    def save_layer(self) -> None:
        """Write both brush layers against the image they were drawn on."""
        if self.layer is None or not self._layer_of or not self._layer_dirty:
            return
        try:
            entry = self.job.find(self._layer_of)
        except jobmod.JobError:
            return
        try:
            paintmod.save_layer(self.job, entry, self.layer)
            paintmod.save_cut(self.job, entry, self.cut)
            self._layer_dirty = False
        except Exception as exc:
            self.editor.status(f"Could not save the paint layer: {exc}")

    # ------------------------------------------------------------- confirm
    def confirm_current(self) -> None:
        entry = self.current_entry()
        if entry is None:
            return
        self.approved.add(entry.relpath)
        self.editor.reload_lists()
        moved = self.advance(lambda e: e.relpath not in self.approved)
        left = sum(
            1 for e in self._ordered_entries() if e.relpath not in self.approved
        )
        if not moved:
            self.editor.status(
                f"{entry.name} confirmed. Every image is confirmed — "
                "press “Render all”."
            )
        else:
            self.editor.status(f"{entry.name} confirmed. {left} still to check.")

    # ------------------------------------------------------------- writing
    def _render_selected(self) -> None:
        chosen = self.selected_entries()
        if not chosen:
            chosen = [
                e for e in self._ordered_entries() if e.relpath in self.approved
            ]
        if not chosen:
            QMessageBox.information(
                self,
                "Nothing chosen",
                "Highlight the images to write, or confirm them one at a time "
                "with the green button, or press “Render all”.",
            )
            return
        self._render(chosen)

    def _render_all(self) -> None:
        self._render(self._ordered_entries())

    def _render(self, entries: list[ImageEntry]) -> None:
        if not entries:
            QMessageBox.information(
                self, "Nothing to render",
                "No image has a translation yet. Go back to the Translation step.",
            )
            return
        if QMessageBox.question(
            self,
            "Render images",
            f"Erase the source text on {len(entries)} image(s) and write the "
            "translated PNGs?\n\n"
            "The originals are kept, so this can be undone.",
        ) != QMessageBox.Yes:
            return
        self.save_layer()
        self.progress.setVisible(True)
        self.progress.setRange(0, len(entries))
        written = 0
        problems: list[str] = []
        for index, entry in enumerate(entries, start=1):
            self.progress.setValue(index - 1)
            self.editor.status(f"Rendering {index}/{len(entries)}: {entry.name}")
            try:
                result = rendermod.render_job_image(self.job, entry)
                rendermod.write_entry(self.job, entry, result.array)
            except Exception as exc:
                entry.error = str(exc)
                problems.append(f"{entry.name}: {exc}")
                continue
            written += 1
            entry.status = RENDERED
            self.previews[entry.relpath] = result.array
            self.notes[entry.relpath] = result.notes
            for note in result.failures:
                problems.append(f"{entry.name}: {note.message}")
        self.progress.setVisible(False)
        self.editor.save_now()
        self.editor.reload_lists()
        self.editor.status(f"Rendered {written} image(s). " + self.editor.counts_text())

        note = (
            f"Wrote {written} image(s) to {self.job.root}\n\n"
            "Next: close this window, then Images tab → Patch, to put them back "
            "into the game."
        )
        if problems:
            shown = "\n".join(f"  • {line}" for line in problems[:8])
            more = f"\n  … and {len(problems) - 8} more" if len(problems) > 8 else ""
            note += f"\n\n{len(problems)} block(s) needed attention:\n{shown}{more}"
        QMessageBox.information(self, "Rendered", note)

    def _restore_current(self) -> None:
        entry = self.current_entry()
        if entry is None:
            return
        if not rendermod.restore_entry(self.job, entry):
            self.editor.status(f"{entry.name} has never been rendered; nothing to undo.")
            return
        if entry.status == RENDERED:
            entry.status = TRANSLATED
        self.approved.discard(entry.relpath)
        self.editor.reload_lists()
        self.editor.save_now()
        self.editor.status(f"{entry.name} restored to the original image.")

    def stop_worker(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(4000)
