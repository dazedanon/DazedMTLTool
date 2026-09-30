"""The picture, the boxes over it, and the two brushes.

Split out of ``image_text_editor`` when the editor grew a third step: the canvas
is used twice, once on the review step against the pristine pixels and once on
the render step against the preview, and it is the one part of the editor with
no opinion about which step it is on.

``Canvas`` is the review view - numbered, movable, resizable blocks over an
image. ``PaintCanvas`` adds the manual touch-up tools on top of it, because
measurement gets the background right often enough to automate and not often
enough to trust, and the leftover cases are ten-second fixes by hand.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PyQt5.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import (
    QColorDialog,
    QGraphicsItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QPushButton,
    QStyle,
)

from util.imagetools import paint as paintmod
from util.imagetools.geometry import Box
from util.imagetools.job import TextBlock

# Qt's default UI face (MS Shell Dlg 2 on Windows) renders U+2661 WHITE HEART
# as U+2261 IDENTICAL TO - three dashes. Game text is full of hearts, stars and
# notes, and a reviewer checking OCR against the picture cannot confirm a
# character the panel is drawing wrongly. QFontMetrics.inFont() is no help: it
# claimed every installed family had the glyph. These do render it, checked by
# rendering them and looking.
TEXT_FONT_CANDIDATES = ("Meiryo", "Yu Gothic UI", "Segoe UI", "MS Gothic", "Noto Sans CJK JP")

TOOL_SELECT = "select"
TOOL_PENCIL = "pencil"
TOOL_ERASER = "eraser"

UNDO_DEPTH = 20


def text_font(point_size: float = 11.0) -> QFont:
    from PyQt5.QtGui import QFontDatabase

    installed = set(QFontDatabase().families())
    for family in TEXT_FONT_CANDIDATES:
        if family in installed:
            font = QFont(family)
            font.setPointSizeF(point_size)
            return font
    font = QFont()
    font.setPointSizeF(point_size)
    return font


def to_pixmap(array: np.ndarray) -> QPixmap:
    height, width = array.shape[:2]
    contiguous = np.ascontiguousarray(array)
    image = QImage(contiguous.data, width, height, 4 * width, QImage.Format_RGBA8888)
    return QPixmap.fromImage(image.copy())


def font_choices() -> list[tuple[str, str]]:
    """``(label, path)`` for every font the renderer can use, "" meaning default.

    Everything installed on the machine, named the way the font names itself and
    sorted alphabetically. The list used to be eight hand-picked files, which
    was fine until the first game whose UI was set in something else.
    """
    from util.imagetools.fonts import available_fonts, font_name

    seen: set[str] = set()
    named: list[tuple[str, str]] = []
    for path in available_fonts():
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        named.append((font_name(str(path)), str(path)))
    # By name, then by path so two files claiming one name keep a stable order.
    named.sort(key=lambda pair: (pair[0].casefold(), pair[1].casefold()))
    return [("Default", "")] + named


class ColourButton(QPushButton):
    """A button that shows a colour and opens a picker when pressed."""

    picked = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._colour: list[int] | None = None
        # Tall enough for its own label. At 22 the hex code lost its descenders
        # to the bottom edge, which is a small thing that looks like a broken
        # widget every time the panel is opened.
        self.setMinimumHeight(26)
        self.clicked.connect(self._choose)

    def colour(self) -> list[int] | None:
        return list(self._colour) if self._colour else None

    def set_colour(self, rgba: list[int] | None) -> None:
        self._colour = list(rgba) if rgba else None
        if not self._colour:
            self.setText("none")
            self.setStyleSheet("")
            return
        red, green, blue = self._colour[:3]
        # Label the swatch with a readable contrast, not a fixed colour: a hex
        # code in black on a black swatch is the same as no label at all.
        ink = "#000000" if (red * 299 + green * 587 + blue * 114) / 1000 > 140 else "#ffffff"
        self.setText(f"#{red:02x}{green:02x}{blue:02x}")
        self.setStyleSheet(
            f"background-color: rgb({red},{green},{blue}); color: {ink};"
        )

    def _choose(self) -> None:
        current = QColor(*(self._colour[:3] if self._colour else (255, 255, 255)))
        chosen = QColorDialog.getColor(current, self, "Colour")
        if not chosen.isValid():
            return
        alpha = self._colour[3] if self._colour and len(self._colour) > 3 else 255
        self.set_colour([chosen.red(), chosen.green(), chosen.blue(), alpha])
        self.picked.emit(self.colour())


# --------------------------------------------------------------------------
# boxes


class BoxItem(QGraphicsRectItem):
    """One text block on the canvas: movable, resizable, numbered."""

    HANDLE = 9.0

    def __init__(self, block: TextBlock, ordinal: int, canvas: "Canvas"):
        super().__init__()
        self.block = block
        self.canvas = canvas
        self._resizing = False
        self.ghost = not canvas.boxes_visible
        self.setFlags(
            QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        box = block.box
        self.setRect(0.0, 0.0, float(box.w), float(box.h))
        self.setPos(float(box.x), float(box.y))

        self.ordinal = ordinal
        self.restyle()

    # ------------------------------------------------------------- painting
    def restyle(self) -> None:
        if getattr(self, "ghost", False):
            # Still here, still clickable, just not drawn. Hiding the item
            # outright takes it out of hit-testing too, and "let me see the
            # picture" then also means "and stop being able to touch it".
            self.setPen(QPen(Qt.NoPen))
            self.setBrush(QBrush(Qt.NoBrush))
            self.colour = QColor(0, 0, 0, 0)
            self.setZValue(1)
            return
        flagged = bool(self.block.flags)
        colour = QColor(224, 168, 62) if flagged else QColor(79, 142, 247)
        if self.block.skip:
            colour = QColor(140, 140, 148)
        width = 2.0 if self.isSelected() else 1.5
        pen = QPen(QColor(255, 255, 255) if self.isSelected() else colour)
        pen.setWidthF(width)
        pen.setCosmetic(True)          # constant on screen at any zoom
        self.setPen(pen)
        fill = QColor(colour)
        fill.setAlpha(60 if self.isSelected() else 32)
        self.setBrush(QBrush(fill))
        self.colour = colour
        self.setZValue(5 if self.isSelected() else 1)

    def boundingRect(self) -> QRectF:
        # The badge is drawn above the rect in device space; give the scene a
        # generous margin so it is never clipped as stale paint area.
        return super().boundingRect().adjusted(-2, -24, 2, 2)

    def paint(self, painter, option, widget=None):
        if self.ghost:
            return
        # Drop Qt's dashed selection frame; restyle() already shows selection
        # with a white pen, and the two together read as noise.
        option.state &= ~QStyle.State_Selected
        super().paint(painter, option, widget)

        # Everything below is drawn in DEVICE pixels so it keeps a constant
        # screen size at any zoom. Mixing scene units with an
        # ItemIgnoresTransformations child does not work: the plate scales one
        # way and the digit on it the other, and they drift apart.
        transform = painter.worldTransform()
        rect = self.rect()
        painter.save()
        painter.resetTransform()

        font = QFont()
        font.setPointSizeF(7.0)
        font.setBold(True)
        painter.setFont(font)
        text = str(self.ordinal)
        metrics = painter.fontMetrics()
        width = metrics.horizontalAdvance(text) + 6
        height = metrics.height() + 1
        corner = transform.map(rect.topLeft())
        plate = QRectF(corner.x(), corner.y() - height, width, height)
        painter.setPen(QPen(Qt.NoPen))
        painter.setBrush(QBrush(self.colour))
        painter.drawRect(plate)
        painter.setPen(QPen(QColor(255, 255, 255)))
        painter.drawText(plate, Qt.AlignCenter, text)

        if self.isSelected():
            far = transform.map(rect.bottomRight())
            painter.setBrush(QBrush(QColor(255, 255, 255)))
            painter.setPen(QPen(QColor(79, 142, 247)))
            painter.drawRect(
                QRectF(far.x() - self.HANDLE, far.y() - self.HANDLE,
                       self.HANDLE, self.HANDLE)
            )
        painter.restore()

    # ------------------------------------------------------------- geometry
    def _on_handle(self, pos: QPointF) -> bool:
        rect = self.rect()
        size = self.HANDLE / max(0.01, self.canvas.scale_factor())
        return (
            pos.x() >= rect.right() - size
            and pos.y() >= rect.bottom() - size
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._on_handle(event.pos()):
            self._resizing = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resizing:
            pos = event.pos()
            self.setRect(0.0, 0.0, max(4.0, pos.x()), max(4.0, pos.y()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resizing:
            self._resizing = False
            self.commit()
            event.accept()
            return
        super().mouseReleaseEvent(event)
        self.commit()

    def commit(self) -> None:
        """Write the item's geometry back to the block and trigger a save."""
        rect = self.rect()
        pos = self.pos()
        box = Box.from_xywh(round(pos.x()), round(pos.y()),
                            max(1, round(rect.width())), max(1, round(rect.height())))
        if box.as_xywh() != self.block.box.as_xywh():
            self.block.box = box
            style = self.block.style
            if style is not None and not style.locked:
                # It was measured for the old rectangle and no longer describes
                # this one - most obviously the background, which is sampled
                # from just outside the edges that just moved.
                self.block.style = None
            self.canvas.geometry_changed.emit()


# --------------------------------------------------------------------------
# canvas


class Canvas(QGraphicsView):
    """Zoomable image with the block overlay on top."""

    selection_changed = pyqtSignal()
    geometry_changed = pyqtSignal()
    box_added = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(QBrush(QColor(28, 30, 36)))
        self.pixmap_item: QGraphicsPixmapItem | None = None
        self.items_by_id: dict[str, BoxItem] = {}
        self.entry = None
        self.pixels: np.ndarray | None = None
        self.adding = False
        self.boxes_visible = True
        self._draft: QGraphicsRectItem | None = None
        self._origin = QPointF()
        self._banding = False
        self._scene.selectionChanged.connect(self._on_selection)

    def scale_factor(self) -> float:
        return float(self.transform().m11()) or 1.0

    # ------------------------------------------------------------- contents
    def show_image(self, entry, array: np.ndarray | None) -> None:
        # Drop our handles BEFORE clearing the scene. Clearing deletes the C++
        # items and emits selectionChanged on the way, which re-enters
        # refresh_styles - and touching a deleted item there is an instant
        # hard crash rather than an exception.
        self.items_by_id = {}
        self.pixmap_item = None
        self._scene.blockSignals(True)
        try:
            self._scene.clear()
        finally:
            self._scene.blockSignals(False)
        self.entry = entry
        self.pixels = array
        if entry is None or array is None:
            self._scene.setSceneRect(QRectF(0, 0, 1, 1))
            return
        self.pixmap_item = self._scene.addPixmap(to_pixmap(array))
        self.pixmap_item.setZValue(0)
        # A little margin so a badge on a block flush with the top edge is not
        # clipped out of view.
        self._scene.setSceneRect(
            QRectF(self.pixmap_item.pixmap().rect()).adjusted(-18, -18, 18, 18)
        )
        self.rebuild_boxes()
        self.fit()

    def rebuild_boxes(self) -> None:
        """Rebuild the overlay from the entry's blocks.

        Signals stay blocked for the whole swap: removing a selected item
        emits selectionChanged mid-loop, and the handler would iterate the very
        dict being rebuilt.
        """
        old = list(self.items_by_id.values())
        self.items_by_id = {}
        self._scene.blockSignals(True)
        try:
            for item in old:
                item.setSelected(False)
                self._scene.removeItem(item)
            if self.entry is not None:
                for ordinal, block in enumerate(self.entry.blocks, start=1):
                    item = BoxItem(block, ordinal, self)
                    # Never setVisible(False) to hide a box - hiding is done by
                    # the item's ``ghost`` flag (set from ``boxes_visible`` in its
                    # constructor), which stops it drawing while keeping it
                    # clickable. setVisible(False) here left a rebuilt-while-hidden
                    # box actually invisible, and re-ticking "Show boxes" only
                    # clears ghost, so the box stayed gone until the next image
                    # switch rebuilt it visible.
                    self._scene.addItem(item)
                    self.items_by_id[block.block_id] = item
        finally:
            self._scene.blockSignals(False)

    def set_pixels(self, array: np.ndarray | None) -> None:
        """Swap the picture under the boxes, leaving the overlay alone.

        Kept apart from ``show_image`` because the preview toggles many times a
        second while a knob is being dragged, and rebuilding the box items each
        time would drop the selection the user is working on.
        """
        if self.pixmap_item is None or array is None:
            return
        self.pixels = array
        self.pixmap_item.setPixmap(to_pixmap(array))

    def set_boxes_visible(self, visible: bool) -> None:
        """Hide the overlay so the picture can be judged on its own.

        Hidden, not gone: the items keep their geometry and stay clickable, so
        a block can still be picked and its text edited while the frames are out
        of the way. ``setVisible(False)`` would take them out of hit-testing as
        well, which turns a look-at-it toggle into a stop-touching-it toggle.
        """
        self.boxes_visible = bool(visible)
        for item in self.items_by_id.values():
            item.ghost = not self.boxes_visible
            item.restyle()
            item.update()
        self.viewport().update()

    def refresh_styles(self) -> None:
        for item in list(self.items_by_id.values()):
            item.restyle()
        self.viewport().update()

    def selected_ids(self) -> list[str]:
        return [
            item.block.block_id
            for item in self._scene.selectedItems()
            if isinstance(item, BoxItem)
        ]

    def select(self, block_ids: list[str]) -> None:
        wanted = set(block_ids)
        for block_id, item in self.items_by_id.items():
            item.setSelected(block_id in wanted)
        self.refresh_styles()

    def fit(self) -> None:
        if self.pixmap_item is not None:
            self.fitInView(self.pixmap_item, Qt.KeepAspectRatio)

    # ------------------------------------------------------------- events
    def _on_selection(self) -> None:
        self.refresh_styles()
        self.selection_changed.emit()

    def wheelEvent(self, event):
        step = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(step, step)
        self.viewport().update()

    def set_adding(self, adding: bool) -> None:
        self.adding = adding
        self.setDragMode(
            QGraphicsView.NoDrag if adding else QGraphicsView.ScrollHandDrag
        )
        self.setCursor(Qt.CrossCursor if adding else Qt.ArrowCursor)

    def mousePressEvent(self, event):
        if self.adding and event.button() == Qt.LeftButton:
            self._origin = self.mapToScene(event.pos())
            self._draft = self._scene.addRect(QRectF(self._origin, self._origin))
            pen = QPen(QColor(255, 255, 255))
            pen.setCosmetic(True)
            self._draft.setPen(pen)
            event.accept()
            return
        if event.button() == Qt.LeftButton and event.modifiers() & Qt.ControlModifier:
            # Ctrl + drag is a rubber-band multi-select. A plain drag pans the
            # view (ScrollHandDrag), so the modifier is what frees the drag to
            # sweep a rectangle instead; Qt's RubberBandDrag ticks every
            # selectable box it crosses. Restored on release.
            self._banding = True
            self.setDragMode(QGraphicsView.RubberBandDrag)
            super().mousePressEvent(event)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._draft is not None:
            self._draft.setRect(QRectF(self._origin, self.mapToScene(event.pos())).normalized())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._draft is not None:
            rect = self._draft.rect().normalized()
            self._scene.removeItem(self._draft)
            self._draft = None
            self.set_adding(False)
            if rect.width() >= 4 and rect.height() >= 4:
                self.box_added.emit(
                    Box.from_xywh(round(rect.x()), round(rect.y()),
                                  round(rect.width()), round(rect.height()))
                )
            event.accept()
            return
        if self._banding:
            self._banding = False
            super().mouseReleaseEvent(event)
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            return
        super().mouseReleaseEvent(event)


# --------------------------------------------------------------------------
# painting


class PaintCanvas(Canvas):
    """The canvas with a pencil, an eraser and an eyedropper on it.

    The strokes go into an RGBA layer the renderer composites *under* the
    English, so a stroke is background repair: it can fix anything the erase
    left behind and can never end up on top of the translation when the fit
    ladder later moves the type.

    Photoshop's muscle memory where it costs nothing: ``B``/``E``/``V`` pick the
    tool, ``[`` and ``]`` size the brush, holding Alt turns whatever is selected
    into an eyedropper, and Ctrl+Z steps back.

    The eraser has the three behaviours the job needs, in the order of how often
    they are wanted:

    * on its own it removes *your own* marks - paint and cuts alike - and puts
      back whatever the renderer had there;
    * with **Ctrl** it erases the picture itself to transparency, which is what
      Photoshop's eraser does by default and the only way to take out something
      that should not be replaced by anything;
    * with **Shift** it paints the block's own measured background over the
      pixels, which is what covers a stubborn glyph on a surface that has to
      stay opaque.
    """

    painted = pyqtSignal()               # a stroke finished; re-render and save
    stroking = pyqtSignal()              # mid-stroke; the layer changed
    probed = pyqtSignal(object)          # rgba sampled from the picture
    tool_changed = pyqtSignal(str)
    size_changed = pyqtSignal(int)       # the brush was resized from the canvas

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.tool = TOOL_SELECT
        self.brush_size = paintmod.DEFAULT_SIZE
        self.brush_colour: list[int] = [255, 255, 255, 255]
        self.layer: np.ndarray | None = None
        # Where Ctrl+eraser records what it took out of the picture. Its own
        # layer because it says the opposite of what ``layer`` says.
        self.cut: np.ndarray | None = None
        # The render taken apart, so a stroke can be shown under the English
        # without re-rendering. Set by the step after every real render.
        self.base: np.ndarray | None = None
        self.overlay: np.ndarray | None = None
        # Set by the render step: given a scene point, the measured background
        # of whichever block is under it. Ctrl+eraser paints with it.
        self.background_at = None
        self._undo: list[tuple[np.ndarray, np.ndarray | None]] = []
        self._last: QPointF | None = None
        self._hover: QPointF | None = None
        self._space = False
        self._panning: QPointF | None = None
        self._sizing: tuple[float, int] | None = None

    # ------------------------------------------------------------- state
    def set_layer(self, layer: np.ndarray | None, cut: np.ndarray | None = None) -> None:
        self.layer = layer
        self.cut = cut
        self._undo.clear()

    def show_image(self, entry, array) -> None:
        # A private copy, always. ``_show_segment`` writes into ``self.pixels``,
        # and the array it is handed is the step's cached preview - painting
        # would quietly corrupt the cache for every image visited afterwards.
        super().show_image(entry, None if array is None else np.array(array, copy=True))

    def set_pixels(self, array) -> None:
        super().set_pixels(None if array is None else np.array(array, copy=True))

    def set_render(self, base, overlay) -> None:
        """Hand over the pieces of the last real render, for live strokes.

        ``base`` is copied because a cut is shown by punching the hole straight
        into it - the only way the transparency appears under the mouse rather
        than a debounce later - and the array handed over is the step's own.
        """
        self.base = None if base is None else np.array(base, copy=True)
        self.overlay = overlay

    def set_tool(self, tool: str) -> None:
        if tool == self.tool:
            return
        self.tool = tool
        self._refresh_mode()
        self.tool_changed.emit(tool)

    def painting(self) -> bool:
        return self.tool in (TOOL_PENCIL, TOOL_ERASER)

    def _refresh_mode(self) -> None:
        """Drag mode and cursor, from the tool and whatever is being held."""
        if self._space:
            # Space beats the tool, the way it does in every paint program:
            # the brush stays selected and the hand borrows the mouse.
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            self.setCursor(Qt.OpenHandCursor)
        elif self.painting():
            # A paint drag must not also pan the view or drag a box out of place.
            self.setDragMode(QGraphicsView.NoDrag)
            self.setCursor(Qt.BlankCursor)
        else:
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            self.setCursor(Qt.ArrowCursor)
        self.viewport().update()

    def set_brush_size(self, size: int) -> None:
        size = paintmod.clamp_size(size)
        if size == self.brush_size:
            return
        self.brush_size = size
        self.viewport().update()

    def set_brush_colour(self, rgba) -> None:
        if rgba:
            self.brush_colour = list(rgba[:3]) + [rgba[3] if len(rgba) > 3 else 255]

    def can_undo(self) -> bool:
        return bool(self._undo)

    def undo(self) -> bool:
        if not self._undo or self.layer is None:
            return False
        paint, cut = self._undo.pop()
        self.layer[:, :] = paint
        if self.cut is not None and cut is not None:
            self.cut[:, :] = cut
        self.painted.emit()
        return True

    # ------------------------------------------------------------- painting
    def _probing(self, modifiers) -> bool:
        return bool(modifiers & Qt.AltModifier)

    def _stroke_colour(self, point: QPointF, modifiers) -> list[int] | None:
        """What a painting segment lays down, or None when it only clears."""
        if self.tool == TOOL_PENCIL:
            return list(self.brush_colour)
        # Eraser with Shift: a pencil loaded with the local background, which is
        # the thing that covers a glyph on a surface that has to stay opaque.
        if not (modifiers & Qt.ShiftModifier):
            return None
        colour = None
        if callable(self.background_at):
            colour = self.background_at((point.x(), point.y()))
        return list(colour) if colour else list(self.brush_colour)

    def _cutting(self, modifiers) -> bool:
        return self.tool == TOOL_ERASER and bool(modifiers & Qt.ControlModifier)

    def _apply(self, a: QPointF, b: QPointF, modifiers) -> None:
        """Lay one segment down and show it immediately."""
        if self.layer is None:
            return
        start, end = (a.x(), a.y()), (b.x(), b.y())
        if self._cutting(modifiers):
            if self.cut is None:
                return
            paintmod.stroke(self.cut, start, end, self.brush_size, [255, 255, 255, 255])
            # Punched into the render's own pieces as well, so the hole is under
            # the mouse now instead of after the next full render. The next
            # render overwrites these anyway - this is a preview, not a result.
            paintmod.apply_cut_segment(self.base, start, end, self.brush_size)
        else:
            colour = self._stroke_colour(b, modifiers)
            if colour is None:
                # The plain eraser undoes the user's own marks, both kinds. An
                # eraser that removed paint but left a cut behind would look
                # like it had done nothing on exactly the pixels it cleared.
                paintmod.wipe(self.layer, start, end, self.brush_size)
                if self.cut is not None:
                    paintmod.wipe(self.cut, start, end, self.brush_size)
            else:
                paintmod.stroke(self.layer, start, end, self.brush_size, colour)
        self._show_segment(a, b)
        self.stroking.emit()

    def _show_segment(self, a: QPointF, b: QPointF) -> None:
        """Repaint the pixels this segment touched, and nothing else.

        The full render is far too slow to run per mouse-move event, so it used
        to run on a debounce - which meant that for as long as the button was
        down there was no brush, no trail and no moving cursor, and the tool
        looked hung. Recombining three arrays over the segment's own rectangle
        is fast enough to do every event, and it is the same arithmetic the
        renderer does, so what appears under the mouse is the real result.
        """
        if self.pixels is None or self.base is None or self.pixmap_item is None:
            return
        reach = self.brush_size // 2 + 2
        left = int(min(a.x(), b.x())) - reach
        right = int(max(a.x(), b.x())) + reach + 1
        top = int(min(a.y(), b.y())) - reach
        bottom = int(max(a.y(), b.y())) + reach + 1
        paintmod.recomposite(
            self.pixels, self.base, self.overlay, self.layer,
            (top, bottom, left, right),
        )
        self.pixmap_item.setPixmap(to_pixmap(self.pixels))

    def _snapshot(self) -> None:
        """Both layers together: one stroke is one step back, whichever it hit."""
        if self.layer is None:
            return
        self._undo.append(
            (self.layer.copy(), None if self.cut is None else self.cut.copy())
        )
        if len(self._undo) > UNDO_DEPTH:
            self._undo.pop(0)

    # ------------------------------------------------------------- events
    def mousePressEvent(self, event):
        point = self.mapToScene(event.pos())
        if event.button() == Qt.MiddleButton:
            # The other half of the pan convention. Space is Photoshop's; the
            # wheel button is everyone else's, and both cost one branch.
            self._panning = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        if (
            event.button() == Qt.RightButton
            and self.painting()
            and self._probing(event.modifiers())
        ):
            self._sizing = (event.pos().x(), self.brush_size)
            event.accept()
            return
        if self._space:
            super().mousePressEvent(event)
            return
        if event.button() == Qt.LeftButton and self._probing(event.modifiers()):
            colour = paintmod.probe(self.pixels, (point.x(), point.y()))
            if colour:
                self.set_brush_colour(colour)
                self.probed.emit(colour)
            event.accept()
            return
        if event.button() == Qt.LeftButton and self.painting():
            if self.layer is None:
                event.accept()
                return
            self._snapshot()
            self._last = point
            self._apply(point, point, event.modifiers())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning is not None:
            delta = event.pos() - self._panning
            self._panning = event.pos()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - delta.x()
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - delta.y()
            )
            event.accept()
            return
        if self._sizing is not None:
            # Photoshop's Alt-drag: right and the brush grows, left and it
            # shrinks, one pixel of width per pixel of travel.
            origin, started = self._sizing
            self.set_brush_size(started + int(event.pos().x() - origin))
            self.size_changed.emit(self.brush_size)
            event.accept()
            return

        self._hover = self.mapToScene(event.pos())
        if self._last is not None:
            point = self._hover
            self._apply(self._last, point, event.modifiers())
            self._last = point
            self.viewport().update()
            event.accept()
            return
        if self.painting():
            self.viewport().update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._panning is not None and event.button() == Qt.MiddleButton:
            self._panning = None
            self._refresh_mode()
            event.accept()
            return
        if self._sizing is not None and event.button() == Qt.RightButton:
            self._sizing = None
            event.accept()
            return
        if self._last is not None:
            self._last = None
            # Only now. Everything during the drag was shown from the pieces of
            # the last render; this is what asks for a new one.
            self.painted.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        self._hover = None
        self.viewport().update()
        super().leaveEvent(event)

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_Space and not event.isAutoRepeat():
            self._space = True
            self._refresh_mode()
            return
        if key == Qt.Key_B:
            self.set_tool(TOOL_PENCIL)
            return
        if key == Qt.Key_E:
            self.set_tool(TOOL_ERASER)
            return
        if key == Qt.Key_V:
            self.set_tool(TOOL_SELECT)
            return
        if key in (Qt.Key_BracketLeft, Qt.Key_BracketRight):
            step = max(1, self.brush_size // 6)
            self.set_brush_size(
                self.brush_size + (step if key == Qt.Key_BracketRight else -step)
            )
            self.size_changed.emit(self.brush_size)
            return
        if key == Qt.Key_Z and event.modifiers() & Qt.ControlModifier:
            self.undo()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self._space = False
            self._refresh_mode()
            return
        super().keyReleaseEvent(event)

    def drawForeground(self, painter, rect):
        """The brush ring, in scene units so it shows its true size.

        A brush whose cursor does not match its footprint is unusable at any
        zoom other than 1:1, and the render step is used zoomed in. Below a few
        pixels the ring is smaller than the pointer it replaces, so a crosshair
        comes with it - otherwise a one-pixel brush is an invisible cursor.
        """
        super().drawForeground(painter, rect)
        if not self.painting() or self._hover is None or self._space:
            return
        radius = self.brush_size / 2.0
        pen = QPen(QColor(255, 255, 255, 200))
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(self._hover, radius, radius)
        pen.setColor(QColor(0, 0, 0, 140))
        painter.setPen(pen)
        painter.drawEllipse(self._hover, radius + 1, radius + 1)

        arm = 6.0 / max(0.01, self.scale_factor())
        if radius < arm:
            pen.setColor(QColor(255, 255, 255, 220))
            painter.setPen(pen)
            centre = self._hover
            painter.drawLine(
                QPointF(centre.x() - arm, centre.y()),
                QPointF(centre.x() + arm, centre.y()),
            )
            painter.drawLine(
                QPointF(centre.x(), centre.y() - arm),
                QPointF(centre.x(), centre.y() + arm),
            )


def load_array(path: Path) -> np.ndarray | None:
    """Read a PNG as RGBA. One implementation, shared with the renderer."""
    from util.imagetools import render as rendermod

    return rendermod.load_rgba(path)
