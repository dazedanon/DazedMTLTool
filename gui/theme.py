"""Shared dark theme and visual tokens for the DazedTL interface.

The application used to rely on a mixture of application-wide QSS, platform
palette defaults, and per-widget styles.  This module makes the dark palette a
real contract that can also be applied by headless visual tests.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from PyQt5.QtGui import QColor, QPalette


@dataclass(frozen=True)
class Colors:
    canvas: str = "#1E1E1E"
    chrome: str = "#252526"
    surface_1: str = "#2D2D30"
    surface_2: str = "#353539"
    surface_hover: str = "#3E3E42"
    border: str = "#45454A"
    border_strong: str = "#5A5A60"
    text_primary: str = "#F2F2F2"
    text_secondary: str = "#C8C8C8"
    text_muted: str = "#A6A6A6"
    text_disabled: str = "#77777A"
    on_accent: str = "#FFFFFF"
    accent: str = "#0E639C"
    accent_hover: str = "#1177BB"
    accent_pressed: str = "#0B527F"
    accent_text: str = "#75BEFF"
    focus: str = "#75BEFF"
    success: str = "#73C991"
    warning: str = "#F2C94C"
    danger: str = "#F48771"
    danger_fill: str = "#A1260D"
    danger_surface: str = "#3A2020"
    danger_hover: str = "#FF9B8B"
    selection: str = "#264F78"


COLORS = Colors()


class Spacing:
    XS = 4
    SM = 8
    MD = 12
    LG = 16
    XL = 24
    XXL = 32


class Geometry:
    CONTROL_COMPACT = 32
    CONTROL = 36
    CONTROL_PROMINENT = 40
    ACTION = 192
    ACTION_WIDE = 240
    ACTION_MAX = 384
    FORM_LABEL = 112
    FIELD_COMPACT = 112
    FIELD_MEDIUM = 240
    ICON = 16
    ICON_LARGE = 20
    RADIUS_CONTROL = 4
    RADIUS_CARD = 6
    STEP_RAIL_WIDTH = 176
    STEP_RAIL_COMPACT_WIDTH = 56
    ACTIVITY_WIDTH = 300
    CONTENT_MAX_WIDTH = 1040


def application_stylesheet() -> str:
    """Return the canonical application QSS.

    Object-name rules used by the workflow intentionally live here so a
    standalone workflow render and the integrated application cannot drift.
    """

    c = COLORS
    return f"""
        QMainWindow, QWidget {{
            background-color: {c.canvas};
            color: {c.text_primary};
        }}
        QLabel {{
            background: transparent;
            color: {c.text_secondary};
        }}
        QLabel:disabled {{ color: {c.text_disabled}; }}
        QToolTip {{
            background-color: {c.surface_2};
            color: {c.text_primary};
            border: 1px solid {c.border_strong};
            padding: 4px 6px;
        }}
        QPushButton, QToolButton {{
            background-color: {c.accent};
            color: {c.on_accent};
            border: 1px solid {c.accent};
            border-radius: 4px;
            padding: 6px 14px;
            min-height: 22px;
            font-weight: 600;
        }}
        QPushButton:hover, QToolButton:hover {{
            background-color: {c.accent_hover};
            border-color: {c.accent_text};
        }}
        QPushButton:pressed, QToolButton:pressed {{
            background-color: {c.accent_pressed};
        }}
        QPushButton:focus, QToolButton:focus {{
            border: 1px solid {c.focus};
        }}
        QPushButton:disabled, QToolButton:disabled {{
            background-color: {c.surface_1};
            color: {c.text_disabled};
            border-color: {c.border};
        }}
        QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
            background-color: {c.surface_2};
            color: {c.text_primary};
            border: 1px solid {c.border};
            border-radius: 4px;
            padding: 4px 8px;
            min-height: 26px;
            selection-background-color: {c.selection};
            selection-color: {c.on_accent};
        }}
        QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{
            border-color: {c.border_strong};
        }}
        QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
            border-color: {c.focus};
        }}
        QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled,
        QComboBox:disabled {{
            background-color: {c.surface_1};
            color: {c.text_disabled};
            border-color: {c.border};
        }}
        QComboBox::drop-down {{
            width: 24px;
            border: none;
            border-left: 1px solid {c.border};
            background-color: {c.surface_1};
        }}
        QComboBox::drop-down:hover {{ background-color: {c.surface_hover}; }}
        QComboBox QAbstractItemView {{
            background-color: {c.surface_2};
            color: {c.text_primary};
            border: 1px solid {c.border_strong};
            selection-background-color: {c.selection};
            selection-color: {c.on_accent};
            outline: none;
        }}
        QCheckBox {{
            background: transparent;
            color: {c.text_secondary};
            spacing: 8px;
            min-height: 28px;
        }}
        QCheckBox:disabled {{ color: {c.text_disabled}; }}
        QCheckBox::indicator {{
            width: 16px;
            height: 16px;
            background-color: {c.surface_2};
            border: 1px solid {c.border_strong};
            border-radius: 3px;
        }}
        QCheckBox::indicator:hover {{ border-color: {c.focus}; }}
        QCheckBox::indicator:checked {{
            background-color: {c.accent};
            border-color: {c.accent_text};
        }}
        QCheckBox::indicator:disabled {{
            background-color: {c.surface_1};
            border-color: {c.border};
        }}
        QTextEdit, QPlainTextEdit, QListWidget, QTreeWidget, QTableWidget {{
            background-color: {c.canvas};
            color: {c.text_secondary};
            border: 1px solid {c.border};
            border-radius: 4px;
            selection-background-color: {c.selection};
            selection-color: {c.on_accent};
        }}
        QListWidget::item, QTreeWidget::item {{
            padding: 4px 6px;
        }}
        QListWidget::item:hover, QTreeWidget::item:hover {{
            background-color: {c.surface_hover};
        }}
        QListWidget::item:selected, QTreeWidget::item:selected {{
            background-color: {c.selection};
            color: {c.on_accent};
        }}
        QScrollArea, QScrollArea > QWidget > QWidget {{
            background-color: {c.canvas};
            border: none;
        }}
        QScrollBar:vertical {{
            background: {c.chrome};
            width: 12px;
            border: none;
        }}
        QScrollBar::handle:vertical {{
            background: {c.border_strong};
            min-height: 24px;
            margin: 2px;
            border-radius: 4px;
        }}
        QScrollBar::handle:vertical:hover {{ background: {c.accent_hover}; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        QScrollBar:horizontal {{
            background: {c.chrome};
            height: 12px;
            border: none;
        }}
        QScrollBar::handle:horizontal {{
            background: {c.border_strong};
            min-width: 24px;
            margin: 2px;
            border-radius: 4px;
        }}
        QScrollBar::handle:horizontal:hover {{ background: {c.accent_hover}; }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
        QGroupBox {{
            color: {c.text_primary};
            background: transparent;
            border: 1px solid {c.border};
            border-radius: 6px;
            margin-top: 12px;
            padding: 12px;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 4px;
            color: {c.text_primary};
            background-color: {c.canvas};
            font-weight: 600;
        }}
        QTabWidget::pane {{
            border: 1px solid {c.border};
            background-color: {c.canvas};
        }}
        QTabBar::tab {{
            background-color: {c.surface_1};
            color: {c.text_muted};
            padding: 8px 16px;
            border: 1px solid {c.border};
            border-bottom: none;
        }}
        QTabBar::tab:selected {{
            background-color: {c.canvas};
            color: {c.text_primary};
            border-top: 2px solid {c.accent_text};
        }}
        QTabBar::tab:hover {{ color: {c.text_primary}; }}
        QProgressBar {{
            background-color: {c.surface_2};
            color: {c.text_primary};
            border: 1px solid {c.border};
            border-radius: 4px;
            text-align: center;
            min-height: 16px;
        }}
        QProgressBar::chunk {{
            background-color: {c.accent};
            border-radius: 3px;
        }}
        QMenuBar, QMenu {{
            background-color: {c.chrome};
            color: {c.text_primary};
        }}
        QMenuBar {{ border-bottom: 1px solid {c.border}; }}
        QMenu {{ border: 1px solid {c.border_strong}; }}
        QMenuBar::item:selected, QMenu::item:selected {{
            background-color: {c.selection};
        }}
        QMenu::item {{ padding: 6px 20px; }}
        QSplitter::handle {{ background-color: {c.border}; }}
        QSplitter::handle:hover {{ background-color: {c.accent_hover}; }}

        QWidget#workflowRoot, QWidget#workflowPage, QWidget#workflowPageContent {{
            background-color: {c.canvas};
        }}
        QWidget#workflowEngineBar {{
            background-color: {c.chrome};
            border-bottom: 1px solid {c.border};
        }}
        QLabel#workflowEngineLabel {{
            color: {c.text_muted};
            font-size: 12px;
            font-weight: 600;
        }}
        QComboBox#workflowEngineSelector {{ min-width: 220px; }}
        QWidget#workflowStepRail, QWidget#workflowFooter,
        QWidget#workflowActivityHeader {{
            background-color: {c.chrome};
        }}
        QWidget#workflowTaskCard, QWidget#tbox, QWidget#cbbox {{
            background-color: {c.surface_1};
            border: 1px solid {c.border};
            border-radius: 6px;
        }}
        QLabel#workflowEyebrow {{
            color: {c.accent_text};
            font-size: 11px;
            font-weight: 600;
            letter-spacing: 0.5px;
        }}
        QLabel#workflowPageTitle {{
            color: {c.text_primary};
            font-size: 18px;
            font-weight: 600;
        }}
        QLabel#workflowPagePurpose {{
            color: {c.text_muted};
            font-size: 12px;
        }}
        QLabel#workflowTaskTitle {{
            color: {c.text_primary};
            font-size: 14px;
            font-weight: 600;
        }}
    """


def dark_palette() -> QPalette:
    """Build palette roles for widgets that do not fully honor QSS."""

    c = COLORS
    palette = QPalette()
    roles = {
        QPalette.Window: c.canvas,
        QPalette.WindowText: c.text_primary,
        QPalette.Base: c.surface_2,
        QPalette.AlternateBase: c.surface_1,
        QPalette.ToolTipBase: c.surface_2,
        QPalette.ToolTipText: c.text_primary,
        QPalette.Text: c.text_primary,
        QPalette.Button: c.surface_1,
        QPalette.ButtonText: c.text_primary,
        QPalette.BrightText: c.on_accent,
        QPalette.Highlight: c.selection,
        QPalette.HighlightedText: c.on_accent,
    }
    if hasattr(QPalette, "PlaceholderText"):
        roles[QPalette.PlaceholderText] = c.text_disabled
    for role, color in roles.items():
        palette.setColor(role, QColor(color))
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor(c.text_disabled))
    palette.setColor(QPalette.Disabled, QPalette.WindowText, QColor(c.text_disabled))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(c.text_disabled))
    return palette


def scaled_stylesheet(stylesheet: str, scale: float) -> str:
    """Scale pixel font declarations from an immutable QSS source."""

    return re.sub(
        r"font-size:\s*(\d+(?:\.\d+)?)px",
        lambda match: (
            f"font-size: {max(6, round(float(match.group(1)) * scale))}px"
        ),
        stylesheet,
    )


def apply_application_theme(app, *, font_scale: float = 1.0) -> None:
    """Apply the canonical dark QPalette and stylesheet to a QApplication."""

    app.setPalette(dark_palette())
    app.setStyleSheet(scaled_stylesheet(application_stylesheet(), font_scale))


def relative_luminance(color: str) -> float:
    """Return WCAG relative luminance for a hex color."""

    raw = color.lstrip("#")
    channels = [int(raw[index:index + 2], 16) / 255 for index in (0, 2, 4)]
    linear = [
        value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        for value in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(foreground: str, background: str) -> float:
    """Return the WCAG contrast ratio for two hex colors."""

    lighter, darker = sorted(
        (relative_luminance(foreground), relative_luminance(background)),
        reverse=True,
    )
    return (lighter + 0.05) / (darker + 0.05)
