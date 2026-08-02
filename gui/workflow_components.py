"""Reusable presentation components for guided workflows."""

from __future__ import annotations

import re

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from gui.theme import COLORS, Geometry, Spacing


def set_widget_state(widget: QWidget, name: str, value: str | bool) -> None:
    """Set a dynamic property and immediately refresh QSS matching."""

    widget.setProperty(name, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def make_workflow_button(
    text: str,
    *,
    variant: str = "secondary",
    tooltip: str = "",
) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName("workflowButton")
    button.setProperty("variant", variant)
    button.setCursor(Qt.PointingHandCursor)
    button.setMinimumHeight(Geometry.CONTROL)
    if tooltip:
        button.setToolTip(tooltip)
    c = COLORS
    button.setStyleSheet(f"""
        QPushButton#workflowButton {{
            background-color: {c.surface_1};
            color: {c.text_secondary};
            border: 1px solid {c.border_strong};
            border-radius: 4px;
            padding: 6px 14px;
            font-size: 12px;
            font-weight: 600;
        }}
        QPushButton#workflowButton:hover {{
            background-color: {c.surface_hover};
            color: {c.text_primary};
            border-color: {c.accent_text};
        }}
        QPushButton#workflowButton:focus {{ border-color: {c.focus}; }}
        QPushButton#workflowButton:pressed {{ background-color: {c.canvas}; }}
        QPushButton#workflowButton[variant="primary"] {{
            background-color: {c.accent};
            color: {c.on_accent};
            border-color: {c.accent};
        }}
        QPushButton#workflowButton[variant="primary"]:hover {{
            background-color: {c.accent_hover};
            border-color: {c.accent_text};
        }}
        QPushButton#workflowButton[variant="quiet"] {{
            background-color: transparent;
            border-color: {c.border_strong};
            color: {c.text_muted};
        }}
        QPushButton#workflowButton[variant="quiet"]:hover {{
            background-color: {c.surface_hover};
            color: {c.text_primary};
        }}
        QPushButton#workflowButton[variant="danger"] {{
            background-color: {c.surface_1};
            color: {c.danger};
            border-color: {c.danger};
        }}
        QPushButton#workflowButton[variant="danger"]:hover {{
            background-color: {c.danger_surface};
            color: {c.danger_hover};
        }}
        QPushButton#workflowButton:disabled {{
            background-color: {c.surface_1};
            color: {c.text_disabled};
            border-color: {c.border_strong};
        }}
    """)
    return button


class WorkflowStepRail(QWidget):
    """Vertical direct-navigation rail with explicit step state."""

    step_requested = pyqtSignal(int)
    activity_requested = pyqtSignal()

    def __init__(self, labels: list[str], parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("workflowStepRail")
        self.setFixedWidth(Geometry.STEP_RAIL_WIDTH)
        self._labels = labels
        self.buttons: list[QPushButton] = []
        self._number_labels: list[QLabel] = []
        self._text_labels: list[QLabel] = []
        self._button_layouts: list[QHBoxLayout] = []
        self._done: set[int] = set()
        self._current = 0
        self._compact = False

        root = QVBoxLayout(self)
        root.setContentsMargins(Spacing.SM, Spacing.MD, Spacing.SM, 0)
        root.setSpacing(Spacing.XS)
        self._root_layout = root

        title = QLabel("RPG MAKER")
        title.setObjectName("workflowRailTitle")
        title.setStyleSheet(
            f"color:{COLORS.text_muted};font-size:10px;font-weight:600;"
            "letter-spacing:1px;padding:0 8px 6px 8px;"
        )
        root.addWidget(title)
        self.title_label = title

        for index, label in enumerate(labels):
            display_step = index + 1
            button = QPushButton()
            button.setObjectName("workflowStepButton")
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.setMinimumHeight(44)
            button.setCursor(Qt.PointingHandCursor)
            button.setProperty("stepState", "pending")
            button.setAccessibleName(f"Step {display_step}: {label}")

            button_row = QHBoxLayout(button)
            button_row.setContentsMargins(Spacing.MD, 0, Spacing.MD, 0)
            button_row.setSpacing(Spacing.MD)
            number_label = QLabel(str(display_step))
            number_label.setObjectName("workflowStepNumber")
            number_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            number_label.setFixedWidth(20)
            number_label.setAttribute(Qt.WA_TransparentForMouseEvents)
            button_row.addWidget(number_label)
            text_label = QLabel(label)
            text_label.setObjectName("workflowStepLabel")
            text_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            text_label.setAttribute(Qt.WA_TransparentForMouseEvents)
            button_row.addWidget(text_label, 1)

            button.clicked.connect(lambda _checked=False, i=index: self.step_requested.emit(i))
            root.addWidget(button)
            self.buttons.append(button)
            self._number_labels.append(number_label)
            self._text_labels.append(text_label)
            self._button_layouts.append(button_row)

        root.addStretch(1)
        self.activity_host = QWidget()
        self.activity_host.setObjectName("workflowActivityHost")
        self.activity_host.setFixedHeight(Geometry.CONTROL + (Spacing.SM * 2))
        activity_layout = QVBoxLayout(self.activity_host)
        activity_layout.setContentsMargins(0, 0, 0, 0)
        activity_layout.setSpacing(0)
        self.activity_button = QToolButton(self.activity_host)
        self.activity_button.setObjectName("workflowActivityToggle")
        self.activity_button.setText("Activity")
        self.activity_button.setToolTip("Show or hide workflow activity and detailed log")
        self.activity_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.activity_button.setCursor(Qt.PointingHandCursor)
        self.activity_button.clicked.connect(self.activity_requested)
        activity_layout.addWidget(self.activity_button)
        root.addWidget(self.activity_host)

        self.setStyleSheet(self._stylesheet())
        self.set_current(0)

    def _stylesheet(self) -> str:
        c = COLORS
        return f"""
            QWidget#workflowStepRail {{
                background-color: {c.chrome};
                border-right: 1px solid {c.border};
            }}
            QPushButton#workflowStepButton {{
                background-color: transparent;
                border: none;
                border-left: 3px solid transparent;
                border-radius: 4px;
                padding: 0;
                min-height: 44px;
                max-height: 44px;
            }}
            QPushButton#workflowStepButton:hover {{
                background-color: {c.surface_1};
            }}
            QPushButton#workflowStepButton:checked {{
                background-color: {c.surface_1};
                border-left-color: {c.accent_text};
            }}
            QToolButton#workflowActivityToggle {{
                background-color: transparent;
                color: {c.text_muted};
                border: none;
                border-top: 1px solid {c.border};
                border-radius: 0;
                padding: 6px 10px;
                text-align: left;
            }}
            QToolButton#workflowActivityToggle:hover,
            QToolButton#workflowActivityToggle:checked {{
                background-color: {c.surface_hover};
                color: {c.text_primary};
                border-top-color: {c.accent_text};
            }}
        """

    def set_current(self, index: int) -> None:
        self._current = max(0, min(index, len(self.buttons) - 1))
        for button_index, button in enumerate(self.buttons):
            button.blockSignals(True)
            button.setChecked(button_index == self._current)
            button.blockSignals(False)
        self._refresh_labels()

    def set_done(self, done: set[int]) -> None:
        self._done = set(done)
        for index, button in enumerate(self.buttons):
            set_widget_state(
                button,
                "stepState",
                "complete" if index in self._done else "pending",
            )
        self._refresh_labels()

    def labels_require_compact_mode(self) -> bool:
        """Return whether the expanded label column would clip at this font."""

        available = Geometry.STEP_RAIL_WIDTH - 72
        return any(
            text_label.fontMetrics().horizontalAdvance(label) > available
            for label, text_label in zip(self._labels, self._text_labels)
        )

    def set_step_visible(self, index: int, visible: bool) -> None:
        if 0 <= index < len(self.buttons):
            self.buttons[index].setVisible(visible)

    def set_compact(self, compact: bool) -> None:
        if compact == self._compact:
            return
        self._compact = compact
        self.setFixedWidth(
            Geometry.STEP_RAIL_COMPACT_WIDTH if compact else Geometry.STEP_RAIL_WIDTH
        )
        self._root_layout.setContentsMargins(
            Spacing.XS if compact else Spacing.SM,
            Spacing.MD,
            Spacing.XS if compact else Spacing.SM,
            0,
        )
        self.title_label.setVisible(not compact)
        self.activity_button.setText("Log" if compact else "Activity")
        for number_label, text_label, button_layout in zip(
            self._number_labels, self._text_labels, self._button_layouts
        ):
            text_label.setVisible(not compact)
            if compact:
                number_label.setMinimumWidth(0)
                number_label.setMaximumWidth(16777215)
            else:
                number_label.setFixedWidth(20)
            number_label.setSizePolicy(
                QSizePolicy.Fixed if not compact else QSizePolicy.Expanding,
                QSizePolicy.Preferred,
            )
            number_label.setAlignment(
                (Qt.AlignRight if not compact else Qt.AlignCenter) | Qt.AlignVCenter
            )
            button_layout.setContentsMargins(
                Spacing.MD if not compact else 0,
                0,
                Spacing.MD if not compact else 0,
                0,
            )
        self._refresh_labels()

    def _refresh_labels(self) -> None:
        for index, (label, button, number_label, text_label) in enumerate(
            zip(self._labels, self.buttons, self._number_labels, self._text_labels)
        ):
            complete = index in self._done
            current = index == self._current
            state = str(button.property("stepState") or "pending")
            color = (
                COLORS.text_primary
                if current
                else COLORS.success
                if complete
                else COLORS.warning
                if state == "warning"
                else COLORS.text_muted
            )
            weight = 600 if current else 500
            number_label.setStyleSheet(
                f"color:{color};font-size:12px;font-weight:{weight};background:transparent;"
            )
            text_label.setStyleSheet(
                f"color:{color};font-size:12px;font-weight:{weight};background:transparent;"
            )
            display_step = index + 1
            number_label.setText("✓" if complete else str(display_step))
            text_label.setText(label)
            button.setToolTip(f"Step {display_step}: {label}")
            if self._compact:
                text_label.hide()
            else:
                text_label.show()


class WorkflowPageHeader(QWidget):
    help_requested = pyqtSignal()

    def __init__(
        self,
        step: int,
        title: str,
        purpose: str,
        *,
        optional: bool = False,
        total_steps: int = 9,
        show_help: bool = True,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("workflowPageHeader")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(Spacing.XS)

        eyebrow = QLabel(f"STEP {step + 1} OF {total_steps}")
        eyebrow.setObjectName("workflowEyebrow")
        root.addWidget(eyebrow)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(Spacing.SM)
        title_label = QLabel(title)
        title_label.setObjectName("workflowPageTitle")
        title_row.addWidget(title_label, 1)
        if optional:
            badge = QLabel("OPTIONAL")
            badge.setObjectName("workflowOptionalBadge")
            badge.setStyleSheet(
                f"color:{COLORS.text_muted};border:1px solid {COLORS.border};"
                f"background:{COLORS.surface_1};border-radius:8px;padding:2px 8px;"
                "font-size:10px;font-weight:600;"
            )
            title_row.addWidget(badge, 0, Qt.AlignVCenter)
        help_button = None
        if show_help:
            help_button = make_workflow_button("?  Help", variant="quiet")
            help_button.setObjectName("workflowHelpButton")
            help_button.setMinimumWidth(72)
            help_button.clicked.connect(self.help_requested)
            title_row.addWidget(help_button)
        root.addLayout(title_row)

        purpose_label = QLabel(purpose)
        purpose_label.setObjectName("workflowPagePurpose")
        purpose_label.setWordWrap(True)
        root.addWidget(purpose_label)

        self.title_label = title_label
        self.purpose_label = purpose_label
        self.help_button = help_button
        self.title_row = title_row

    def add_trailing_widget(self, widget: QWidget) -> None:
        """Insert a page-specific control immediately before Help."""

        index = max(0, self.title_row.count() - (1 if self.help_button else 0))
        self.title_row.insertWidget(index, widget, 0, Qt.AlignVCenter)


class TaskCard(QFrame):
    """Standard title/description/content/action container."""

    def __init__(
        self,
        title: str = "",
        description: str = "",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("workflowTaskCard")
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(Spacing.LG, Spacing.MD, Spacing.LG, Spacing.MD)
        self.root.setSpacing(Spacing.SM)
        if title:
            label = QLabel(title)
            label.setObjectName("workflowTaskTitle")
            self.root.addWidget(label)
        if description:
            label = QLabel(description)
            label.setObjectName("workflowTaskDescription")
            label.setWordWrap(True)
            label.setStyleSheet(f"color:{COLORS.text_muted};font-size:12px;")
            self.root.addWidget(label)

    def add_widget(self, widget: QWidget, stretch: int = 0) -> None:
        self.root.addWidget(widget, stretch)

    def add_layout(self, layout, stretch: int = 0) -> None:
        self.root.addLayout(layout, stretch)


class WorkflowStageCard(QFrame):
    """Numbered stage that turns a utility page into a readable task sequence."""

    def __init__(
        self,
        number: int,
        title: str,
        description: str = "",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("workflowStageCard")
        root = QVBoxLayout(self)
        root.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        root.setSpacing(Spacing.SM)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(Spacing.SM)
        number_label = QLabel(str(number))
        number_label.setObjectName("workflowStageNumber")
        number_label.setAlignment(Qt.AlignCenter)
        number_label.setFixedSize(24, 24)
        header.addWidget(number_label, 0, Qt.AlignTop)

        copy = QVBoxLayout()
        copy.setContentsMargins(0, 0, 0, 0)
        copy.setSpacing(Spacing.XS)
        title_label = QLabel(title)
        title_label.setObjectName("workflowStageTitle")
        title_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        copy.addWidget(title_label)
        # This label is made visible before the nested layouts are attached to
        # the card. Give it a parent up front so Qt cannot briefly map it as an
        # independent top-level window during application startup.
        description_label = QLabel(description, self)
        description_label.setObjectName("workflowStageDescription")
        description_label.setWordWrap(True)
        description_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        description_label.setVisible(bool(description))
        copy.addWidget(description_label)
        header.addLayout(copy, 1)
        root.addLayout(header)

        self.body = QVBoxLayout()
        # Align controls with the title copy, not with the numbered badge.
        self.body.setContentsMargins(Spacing.XXL, 0, 0, 0)
        self.body.setSpacing(Spacing.SM)
        # Let the contents decide whether the body should grow. Editors and
        # file lists still advertise an expanding size policy, while compact
        # control groups keep their natural height instead of developing large
        # gaps on tall windows.
        root.addLayout(self.body)

        self.number_label = number_label
        self.title_label = title_label
        self.description_label = description_label
        self.setStyleSheet(
            f"QFrame#workflowStageCard{{background:{COLORS.surface_1};"
            f"border:1px solid {COLORS.border};border-radius:6px;}}"
            f"QLabel#workflowStageNumber{{background:{COLORS.accent};"
            f"color:{COLORS.on_accent};border:none;border-radius:12px;"
            "font-size:12px;font-weight:700;}"
            f"QLabel#workflowStageTitle{{color:{COLORS.text_primary};border:none;"
            "font-size:14px;font-weight:650;}"
            f"QLabel#workflowStageDescription{{color:{COLORS.text_muted};border:none;"
            "font-size:12px;}"
        )

    def add_widget(self, widget: QWidget, stretch: int = 0) -> None:
        self.body.addWidget(widget, stretch)

    def add_layout(self, layout, stretch: int = 0) -> None:
        self.body.addLayout(layout, stretch)


class StatusBanner(QFrame):
    """Semantic status with icon and text; color is never the only signal."""

    ICONS = {"info": "i", "success": "✓", "warning": "!", "error": "×"}

    def __init__(self, text: str = "", kind: str = "info", parent=None):
        super().__init__(parent)
        self.setObjectName("workflowStatusBanner")
        row = QHBoxLayout(self)
        row.setContentsMargins(Spacing.MD, Spacing.SM, Spacing.MD, Spacing.SM)
        row.setSpacing(Spacing.SM)
        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setFixedWidth(20)
        self.text_label = QLabel()
        self.text_label.setWordWrap(True)
        row.addWidget(self.icon_label)
        row.addWidget(self.text_label, 1)
        self.set_status(text, kind)

    def set_status(self, text: str, kind: str = "info") -> None:
        kind = kind if kind in self.ICONS else "info"
        color = {
            "info": COLORS.accent_text,
            "success": COLORS.success,
            "warning": COLORS.warning,
            "error": COLORS.danger,
        }[kind]
        self.icon_label.setText(self.ICONS[kind])
        self.text_label.setText(text)
        self.setStyleSheet(
            f"QFrame#workflowStatusBanner{{background:{COLORS.surface_1};"
            f"border:1px solid {COLORS.border};border-left:3px solid {color};"
            "border-radius:4px;}"
            f"QFrame#workflowStatusBanner QLabel{{color:{COLORS.text_secondary};"
            "background:transparent;}"
        )
        self.icon_label.setStyleSheet(f"color:{color};font-weight:700;")


class WorkflowActivityPanel(QWidget):
    """Collapsible detailed activity log used by the workflow shell."""

    collapse_requested = pyqtSignal()
    clear_requested = pyqtSignal()

    _ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")

    def __init__(
        self,
        log: QTextEdit | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("workflowActivityPanel")
        self.setMinimumWidth(240)
        self.setMaximumWidth(420)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QWidget()
        header.setObjectName("workflowActivityHeader")
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(Spacing.MD, Spacing.SM, Spacing.SM, Spacing.SM)
        header_row.setSpacing(Spacing.SM)
        self.summary_label = QLabel("Activity · Idle")
        self.summary_label.setObjectName("workflowActivitySummary")
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet(
            f"color:{COLORS.text_primary};font-size:11px;font-weight:600;"
        )
        header_row.addWidget(self.summary_label)
        header_row.addStretch()
        collapse = QToolButton()
        collapse.setText("×")
        collapse.setToolTip("Hide activity panel")
        collapse.setObjectName("workflowActivityClose")
        collapse.setFixedSize(32, 32)
        collapse.clicked.connect(self.collapse_requested)
        header_row.addWidget(collapse)
        root.addWidget(header)

        self.log = log or QTextEdit()
        self.log.setParent(self)
        self.log.setObjectName("workflowActivityLog")
        self.log.setReadOnly(True)
        self.log.setFrameShape(QFrame.NoFrame)
        self.log.setFont(QFont("Consolas", 9))
        root.addWidget(self.log, 1)

        clear = make_workflow_button("Clear activity", variant="quiet")
        clear.setObjectName("workflowActivityClear")
        clear.clicked.connect(self.clear_requested)
        root.addWidget(clear)

        self.setStyleSheet(
            f"QWidget#workflowActivityPanel{{background:{COLORS.canvas};"
            f"border-left:1px solid {COLORS.border};}}"
            f"QTextEdit#workflowActivityLog{{background:{COLORS.canvas};"
            f"color:{COLORS.text_secondary};border:none;padding:12px;}}"
            f"QToolButton#workflowActivityClose{{background:transparent;"
            f"color:{COLORS.text_muted};border:none;border-radius:4px;padding:0;"
            "min-width:32px;max-width:32px;min-height:32px;max-height:32px;}"
            f"QToolButton#workflowActivityClose:hover{{background:{COLORS.surface_hover};"
            f"color:{COLORS.text_primary};}}"
        )

    @classmethod
    def clean_message(cls, message: str) -> str:
        """Strip terminal formatting that is unreadable in a Qt text widget."""
        return cls._ANSI_RE.sub("", str(message or "")).replace("\r", "").rstrip("\n")

    @staticmethod
    def message_kind(message: str) -> str:
        """Classify a log line for consistent workflow colors and summaries."""
        text = str(message or "")
        lowered = text.casefold()
        error_text = re.sub(
            r"\b(?:0|no)\s+(?:errors?|failures?|failed)\b", "", lowered
        )
        if (
            any(mark in text for mark in ("❌", "✗"))
            or "traceback" in error_text
            or "exception" in error_text
            or re.search(r"\b(error|fatal|failure)\b", error_text)
            or re.search(r"\bfailed\b", error_text)
        ):
            return "error"
        if (
            "⚠" in text
            or re.search(r"\b(warn(?:ing)?|mismatch(?:es)?|skipped)\b", lowered)
        ):
            return "warning"
        if (
            any(mark in text for mark in ("✅", "✔", "✓"))
            or re.search(
                r"\b(success(?:ful(?:ly)?)?|succeeded|complete(?:d)?|finished|ready)\b",
                lowered,
            )
        ):
            return "success"
        return "info"

    def add_status_widget(self, widget: QWidget) -> None:
        """Insert a workflow-specific status row above the shared log widget."""
        self.layout().insertWidget(self.layout().indexOf(self.log), widget)

    def append_message(self, message: str, kind: str | None = None) -> tuple[str, str]:
        """Append one plain-text message with shared severity-aware styling."""
        clean = self.clean_message(message)
        resolved_kind = kind or self.message_kind(clean)
        color = {
            "info": COLORS.text_secondary,
            "success": COLORS.success,
            "warning": COLORS.warning,
            "error": COLORS.danger,
        }.get(resolved_kind, COLORS.text_secondary)

        cursor = self.log.textCursor()
        cursor.movePosition(QTextCursor.End)
        if not self.log.document().isEmpty():
            cursor.insertBlock()
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        if resolved_kind in {"success", "warning", "error"}:
            fmt.setFontWeight(QFont.DemiBold)
        cursor.insertText(clean, fmt)
        self.log.setTextCursor(cursor)
        self.log.ensureCursorVisible()

        summary = clean.strip().replace("\n", " ")
        if summary:
            self.set_summary(
                summary[:72] + ("…" if len(summary) > 72 else ""),
                resolved_kind,
            )
        return clean, resolved_kind

    def clear_activity(self) -> None:
        self.log.clear()
        self.set_summary("Idle", "info")

    def set_summary(self, text: str, kind: str = "info") -> None:
        color = {
            "info": COLORS.text_muted,
            "success": COLORS.success,
            "warning": COLORS.warning,
            "error": COLORS.danger,
        }.get(kind, COLORS.text_muted)
        self.summary_label.setText(f"Activity · {text}")
        self.summary_label.setStyleSheet(
            f"color:{color};font-size:11px;font-weight:600;"
        )


class DisclosureSection(QWidget):
    """A state-preserving show/hide container for optional or advanced fields."""

    def __init__(self, title: str, content: QWidget, *, expanded: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("workflowDisclosure")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(Spacing.SM)
        self.toggle = QToolButton()
        self.toggle.setObjectName("workflowDisclosureToggle")
        self.toggle.setCheckable(True)
        self.toggle.setChecked(expanded)
        self.toggle.setText(("▾  " if expanded else "▸  ") + title)
        self.toggle.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.toggle.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.toggle.setMinimumHeight(Geometry.CONTROL)
        root.addWidget(self.toggle)
        self.content = content
        root.addWidget(content)
        content.setVisible(expanded)
        self.toggle.toggled.connect(lambda checked: self._set_expanded(title, checked))
        self.setStyleSheet(
            f"QToolButton#workflowDisclosureToggle{{background:transparent;"
            f"color:{COLORS.text_secondary};border:1px solid {COLORS.border};"
            "border-radius:4px;text-align:left;padding:6px 10px;font-weight:600;}"
            f"QToolButton#workflowDisclosureToggle:hover{{background:{COLORS.surface_hover};"
            f"color:{COLORS.text_primary};border-color:{COLORS.accent_text};}}"
        )

    def _set_expanded(self, title: str, expanded: bool) -> None:
        self.toggle.setText(("▾  " if expanded else "▸  ") + title)
        self.content.setVisible(expanded)
