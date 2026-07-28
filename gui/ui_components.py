"""Application-wide components governed by docs/gui-ux-contract.md."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from PyQt5.QtCore import QItemSelectionModel, Qt
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from gui.theme import Geometry, Spacing


UX_CONTRACT_VERSION = "1.4"
ButtonVariant = Literal["primary", "secondary", "quiet", "danger"]


class CheckableFileList(QListWidget):
    """A checkable file scope with predictable Ctrl/Shift range behavior.

    Checkmarks remain the authoritative scope used by actions. Row selection is
    the visible gesture scope: a plain click toggles one row, Ctrl-click adds or
    removes one row, and Shift-click applies the clicked state across the range
    from the most recent non-Shift click.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._selection_anchor_row = -1

    @staticmethod
    def _is_checkable(item: QListWidgetItem | None) -> bool:
        return bool(item and item.flags() & Qt.ItemIsUserCheckable)

    @staticmethod
    def _opposite_check_state(item: QListWidgetItem) -> Qt.CheckState:
        return Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked

    def _set_current_without_changing_selection(self, item: QListWidgetItem) -> None:
        self.setCurrentItem(item, QItemSelectionModel.NoUpdate)

    def mousePressEvent(self, event) -> None:
        item = self.itemAt(event.pos())
        if (
            event.button() != Qt.LeftButton
            or item is None
            or not self._is_checkable(item)
        ):
            super().mousePressEvent(event)
            return

        row = self.row(item)
        modifiers = event.modifiers()
        shift = bool(modifiers & Qt.ShiftModifier)
        control = bool(modifiers & Qt.ControlModifier)
        next_state = self._opposite_check_state(item)

        if shift:
            anchor = self._selection_anchor_row
            if not 0 <= anchor < self.count():
                anchor = self.currentRow() if self.currentRow() >= 0 else row
            first, last = sorted((anchor, row))
            if not control:
                self.clearSelection()
            for index in range(first, last + 1):
                range_item = self.item(index)
                if self._is_checkable(range_item) and not range_item.isHidden():
                    range_item.setSelected(True)
                    range_item.setCheckState(next_state)
            self._set_current_without_changing_selection(item)
        elif control:
            item.setSelected(not item.isSelected())
            item.setCheckState(next_state)
            self._set_current_without_changing_selection(item)
            self._selection_anchor_row = row
        else:
            self.clearSelection()
            item.setSelected(True)
            item.setCheckState(next_state)
            self._set_current_without_changing_selection(item)
            self._selection_anchor_row = row

        event.accept()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_A and event.modifiers() & Qt.ControlModifier:
            self.selectAll()
            for row in range(self.count()):
                item = self.item(row)
                if self._is_checkable(item) and not item.isHidden():
                    item.setCheckState(Qt.Checked)
            if self.currentRow() >= 0:
                self._selection_anchor_row = self.currentRow()
            event.accept()
            return

        if event.key() == Qt.Key_Space:
            items = [item for item in self.selectedItems() if self._is_checkable(item)]
            current = self.currentItem()
            if not items and self._is_checkable(current):
                items = [current]
            if items:
                reference = current if current in items else items[0]
                next_state = self._opposite_check_state(reference)
                for item in items:
                    item.setCheckState(next_state)
                event.accept()
                return

        super().keyPressEvent(event)


def refresh_style(widget: QWidget) -> None:
    """Re-evaluate QSS after changing a semantic dynamic property."""

    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def action_button_width_hint(button: QPushButton) -> int:
    """Return a content width that includes the contract's visual padding."""

    text_width = button.fontMetrics().horizontalAdvance(button.text())
    if not button.icon().isNull():
        text_width += button.iconSize().width() + Spacing.SM
    return max(button.sizeHint().width(), text_width + Spacing.XL)


def configure_action_button(
    button: QPushButton,
    *,
    variant: ButtonVariant = "secondary",
    tooltip: str = "",
) -> QPushButton:
    """Apply the shared action-button contract to an existing button."""

    button.setObjectName("appActionButton")
    button.setProperty("variant", variant)
    button.setCursor(Qt.PointingHandCursor)
    button.setMinimumHeight(Geometry.CONTROL)
    if tooltip:
        button.setToolTip(tooltip)
    refresh_style(button)
    return button


def make_action_button(
    text: str,
    *,
    variant: ButtonVariant = "secondary",
    tooltip: str = "",
) -> QPushButton:
    """Create an application action with a semantic visual role."""

    return configure_action_button(
        QPushButton(text), variant=variant, tooltip=tooltip
    )


def configure_icon_button(
    button: QPushButton,
    *,
    accessible_name: str,
    tooltip: str = "",
    size: int = Geometry.CONTROL_COMPACT,
    variant: ButtonVariant = "secondary",
) -> QPushButton:
    """Apply the compact icon-only contract and accessibility metadata."""

    button.setObjectName("appIconButton")
    button.setProperty("variant", variant)
    button.setAccessibleName(accessible_name)
    button.setToolTip(tooltip or accessible_name)
    button.setCursor(Qt.PointingHandCursor)
    button.setFixedSize(size, size)
    refresh_style(button)
    return button


def equalize_button_widths(
    buttons: Iterable[QPushButton],
    *,
    minimum: int = Geometry.ACTION,
    maximum: int = Geometry.ACTION_MAX,
) -> int:
    """Give peer actions one exact content-aware width within contract bounds."""

    group = list(buttons)
    if not group:
        return 0
    width = min(
        max(max(action_button_width_hint(button) for button in group), minimum),
        maximum,
    )
    group_key = f"{id(group[0].parentWidget())}:{id(group[0])}"
    for button in group:
        button.setFixedWidth(width)
        button.setProperty("appEqualWidthGroup", group_key)
        button.setProperty("appEqualWidthMinimum", minimum)
        button.setProperty("appEqualWidthMaximum", maximum)
    return width


def refresh_equalized_button_widths(widgets: Iterable[QWidget]) -> None:
    """Re-measure declared peer groups after a font or theme scale change."""

    groups: dict[str, list[QPushButton]] = {}
    for widget in widgets:
        if not isinstance(widget, QPushButton):
            continue
        group = str(widget.property("appEqualWidthGroup") or "")
        if group:
            groups.setdefault(group, []).append(widget)
    for buttons in groups.values():
        for button in buttons:
            button.setMinimumWidth(0)
            button.setMaximumWidth(16777215)
        minimum = int(buttons[0].property("appEqualWidthMinimum") or 0)
        maximum = int(
            buttons[0].property("appEqualWidthMaximum") or Geometry.ACTION_MAX
        )
        equalize_button_widths(buttons, minimum=minimum, maximum=maximum)


def set_status_text(
    label: QLabel,
    text: str,
    state: Literal["neutral", "info", "success", "warning", "error"] = "neutral",
) -> None:
    """Set readable status copy and its shared semantic state."""

    label.setObjectName("appStatusText")
    label.setText(text)
    label.setProperty("state", state)
    refresh_style(label)


class PageHeader(QWidget):
    """Canonical title, purpose, and optional page-action row."""

    def __init__(
        self,
        title: str,
        purpose: str,
        *,
        eyebrow: str = "",
        actions: Iterable[QWidget] = (),
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("appPageHeader")

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(Spacing.LG)

        copy = QVBoxLayout()
        copy.setContentsMargins(0, 0, 0, 0)
        copy.setSpacing(Spacing.XS)
        if eyebrow:
            eyebrow_label = QLabel(eyebrow.upper())
            eyebrow_label.setObjectName("appPageEyebrow")
            copy.addWidget(eyebrow_label)
            self.eyebrow_label = eyebrow_label
        else:
            self.eyebrow_label = None

        self.title_label = QLabel(title)
        self.title_label.setObjectName("appPageTitle")
        copy.addWidget(self.title_label)

        self.purpose_label = QLabel(purpose)
        self.purpose_label.setObjectName("appPagePurpose")
        self.purpose_label.setWordWrap(True)
        copy.addWidget(self.purpose_label)
        root.addLayout(copy, 1)

        action_list = list(actions)
        if action_list:
            action_row = QHBoxLayout()
            action_row.setContentsMargins(0, 0, 0, 0)
            action_row.setSpacing(Spacing.SM)
            for action in action_list:
                action_row.addWidget(action)
            root.addLayout(action_row)


class SectionCard(QFrame):
    """Canonical surface for one task, decision, or coherent data view."""

    def __init__(
        self,
        title: str = "",
        description: str = "",
        *,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("appSectionCard")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self.content_layout = QVBoxLayout(self)
        self.content_layout.setContentsMargins(
            Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG
        )
        self.content_layout.setSpacing(Spacing.MD)

        self.title_label = None
        if title:
            self.title_label = QLabel(title)
            self.title_label.setObjectName("appSectionTitle")
            self.content_layout.addWidget(self.title_label)

        self.description_label = None
        if description:
            self.description_label = QLabel(description)
            self.description_label.setObjectName("appSectionDescription")
            self.description_label.setWordWrap(True)
            self.content_layout.addWidget(self.description_label)

    def add_widget(self, widget: QWidget, stretch: int = 0) -> QWidget:
        self.content_layout.addWidget(widget, stretch)
        return widget

    def add_layout(self, layout, stretch: int = 0):
        self.content_layout.addLayout(layout, stretch)
        return layout


def make_page_layout(widget: QWidget) -> QVBoxLayout:
    """Create the standard top-level layout and mark its semantic page role."""

    widget.setObjectName("appPage")
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(
        Spacing.XL, Spacing.LG, Spacing.XL, Spacing.LG
    )
    layout.setSpacing(Spacing.LG)
    return layout


def normalize_default_layout_tokens(widgets: Iterable[QWidget]) -> None:
    """Replace Qt's off-grid 6/9 px layout defaults with the 8 px token.

    Explicit non-default values are preserved. Qt-owned stacked/scroll widgets
    are skipped because their private implementation layouts are not page UI.
    """

    widget_list = list(widgets)
    for widget in widget_list:
        if widget.inherits("QStackedWidget") or widget.inherits("QAbstractScrollArea"):
            continue
        layout = widget.layout()
        if layout is None:
            continue
        if layout.spacing() == 6:
            layout.setSpacing(Spacing.SM)
        margins = layout.contentsMargins()
        if (
            margins.left(), margins.top(), margins.right(), margins.bottom()
        ) == (9, 9, 9, 9):
            layout.setContentsMargins(
                Spacing.SM, Spacing.SM, Spacing.SM, Spacing.SM
            )
    refresh_equalized_button_widths(widget_list)
