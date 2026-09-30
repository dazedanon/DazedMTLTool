"""Screen-sized, scrollable dialogs for longer help and warning text."""

from __future__ import annotations

import math

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QTextOption
from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QStyle,
    QTextBrowser,
    QVBoxLayout,
)

from gui.theme import COLORS, Spacing


class RichTextDialog(QDialog):
    """Keep prose readable and actions reachable at the current display scale."""

    def __init__(
        self, title, html, parent=None, *,
        icon=QStyle.SP_MessageBoxInformation,
        buttons=QDialogButtonBox.Ok,
    ):
        super().__init__(parent)
        self.setObjectName("richTextDialog")
        self.setWindowTitle(title)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setSizeGripEnabled(True)
        self.setStyleSheet(
            f"QDialog#richTextDialog {{ background-color: {COLORS.chrome}; }}"
            f"QTextBrowser#richTextDialogBody {{ background: transparent;"
            f" color: {COLORS.text_secondary}; border: none; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.MD)
        content = QHBoxLayout()
        content.setSpacing(Spacing.MD)
        self._icon = QLabel()
        self._icon_type = icon
        content.addWidget(self._icon, 0, Qt.AlignTop)

        self.browser = QTextBrowser()
        self.browser.setObjectName("richTextDialogBody")
        self.browser.setAccessibleName(title)
        self.browser.setOpenLinks(False)
        self.browser.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.browser.setHtml(html)
        content.addWidget(self.browser, 1)
        layout.addLayout(content, 1)

        self.buttons = QDialogButtonBox(buttons)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self._sized = False

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if self._sized:
            return
        self._sized = True
        self._fit_to_screen()

    def _fit_to_screen(self):
        # Qt reports logical pixels here, already accounting for OS DPI scaling.
        # Use the parent's monitor, including when the main window is not on the
        # primary display. Leave room for platform title bars and window borders.
        parent = self.parentWidget()
        screen = parent.screen() if parent is not None else self.screen()
        available = screen.availableGeometry()
        width_limit = max(1, available.width() - 48)
        height_limit = max(1, available.height() - 80)

        metrics = self.browser.fontMetrics()
        icon_size = max(24, metrics.height() * 2)
        self._icon.setPixmap(self.style().standardIcon(self._icon_type).pixmap(icon_size, icon_size))
        margins = self.layout().contentsMargins()
        horizontal_margin = margins.left() + margins.right()
        width = min(width_limit, max(560, metrics.averageCharWidth() * 90 + horizontal_margin))

        # Long confirmation captions must also fit on narrow, scaled displays.
        if self.buttons.minimumSizeHint().width() > width - horizontal_margin:
            self.buttons.setOrientation(Qt.Vertical)
        self.setMinimumSize(min(360, width), min(180, height_limit))
        self.resize(width, height_limit)
        self.layout().activate()

        # Measure a copy so the live document remains tied to the viewport when
        # the user resizes. Reserve scrollbar space to avoid a last-line cutoff
        # when a long document needs to scroll.
        document = self.browser.document().clone()
        scrollbar = self.style().pixelMetric(QStyle.PM_ScrollBarExtent)
        document.setTextWidth(max(1, self.browser.viewport().width() - scrollbar))
        body_height = max(icon_size, math.ceil(document.size().height()))
        chrome_height = (
            margins.top() + margins.bottom() + self.layout().spacing()
            + self.buttons.sizeHint().height() + self.browser.frameWidth() * 2
        )
        self.resize(width, min(height_limit, body_height + chrome_height))
        self.move(
            available.x() + (available.width() - self.width()) // 2,
            available.y() + (available.height() - self.height()) // 2,
        )
