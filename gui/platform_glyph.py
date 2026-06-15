"""Linux fallbacks for emoji that PyQt5 often cannot render (tofu boxes).

Only replaces glyphs known to fail on typical Linux font stacks.
Windows/macOS get the original strings unchanged.
"""

from __future__ import annotations

import re
import sys

from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QColor, QFont, QIcon, QPainter, QPixmap

# Toolbar buttons, section headers, mixed labels
_LINUX_EMOJI_FALLBACKS: dict[str, str] = {
    "\U00002795": "+",       # ➕ add
    "\U0001F4C1": "\u2302",  # 📁 folder → ⌂
    "\U0001F4C2": "\u2302",  # 📂 open folder
    "\U0001F504": "\u21bb",  # 🔄 refresh → ↻
    "\U0001F4DD": "",        # 📝 memo (section headers)
    "\U0001F6D1": "\u25a0",  # 🛑 stop → ■
    "\U0001F4E5": "\u2193",  # 📥 inbox tray → ↓
    "\U0001F527": "\u2699",  # 🔧 wrench → ⚙
    "\U0001F511": "",        # 🔑 key (section headers)
    "\U0001F310": "",        # 🌐 globe (section headers)
    "\U0001F5A5": "",        # 🖥 desktop (section headers)
    "\U00002699\uFE0F": "\u2699",  # ⚙️ → ⚙
    "\U0000270F\uFE0F": "\u270E",  # ✏️ → ✎
}

# Icon-only nav tabs — never empty; BMP symbols so metrics match across the bar
_LINUX_NAV_FALLBACKS: dict[str, str] = {
    "\U0001F310": "\u25ce",  # 🌐 Translation → ◎
    "\U0001F527": "\u2699",  # 🔧 General → ⚙
    "\U0001F3AE": "\u25c6",  # 🎮 MV/MZ → ◆
    "\U0001F43A": "\u25c8",  # 🐺 Wolf → ◈
    "\U0001F4C4": "\u2630",  # 📄 CSV → ☰
    "\U00002694\uFE0F": "\u2694",  # ⚔️ SRPG → ⚔
    "\U00002694": "\u2694",
    "\U0001F504": "\u21bb",  # 🔄 Update → ↻
    "\U00002699\uFE0F": "\u2699",  # ⚙️ Config → ⚙
    "\U000026A1": "\u26a1",  # ⚡ Workflow
}


def _apply_fallbacks(text: str, mapping: dict[str, str]) -> str:
    out = text
    for emoji, replacement in mapping.items():
        out = out.replace(emoji, replacement)
    out = re.sub(r"  +", " ", out)
    return out.strip()


def platform_glyph(text: str) -> str:
    """Return UI text with unsupported emoji swapped on Linux only."""
    if not sys.platform.startswith("linux") or not text:
        return text
    return _apply_fallbacks(text, _LINUX_EMOJI_FALLBACKS)


def platform_nav_glyph(icon: str) -> str:
    """Linux fallback for icon-only nav tabs (never returns empty)."""
    if not sys.platform.startswith("linux") or not icon:
        return icon

    out = _apply_fallbacks(icon, _LINUX_NAV_FALLBACKS)
    if not out:
        out = _apply_fallbacks(icon, _LINUX_EMOJI_FALLBACKS)
    return out or icon


def _linux_nav_pixmap(glyph: str, *, size: int, font_px: int, color: QColor) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    font = QFont("DejaVu Sans")
    font.setPixelSize(font_px)
    painter.setFont(font)
    painter.setPen(color)
    painter.drawText(pixmap.rect(), Qt.AlignCenter, glyph)
    painter.end()
    return pixmap


def _linux_nav_icon(icon_text: str, *, size: int, font_px: int, normal_color: QColor | None = None) -> QIcon:
    """Render a nav glyph into a fixed-size pixmap so every tab aligns the same."""
    glyph = platform_nav_glyph(icon_text)
    gray_color = normal_color or QColor("#cccccc")
    white_color = QColor("#ffffff") if normal_color is None else normal_color.lighter(125)
    icon = QIcon()
    gray = _linux_nav_pixmap(glyph, size=size, font_px=font_px, color=gray_color)
    white = _linux_nav_pixmap(glyph, size=size, font_px=font_px, color=white_color)
    icon.addPixmap(gray, QIcon.Normal, QIcon.Off)
    icon.addPixmap(gray, QIcon.Disabled, QIcon.Off)
    icon.addPixmap(white, QIcon.Active, QIcon.Off)
    icon.addPixmap(white, QIcon.Selected, QIcon.Off)
    return icon


def _nav_toolbutton_stylesheet(*, horizontal: bool, icon_only: bool, update_available: bool = False) -> str:
    border_prop = "border-bottom" if horizontal else "border-left"
    accent = "#ff5252" if update_available else "#007acc"
    text_color = "#ff5252" if update_available else "#cccccc"
    checked_color = "#ff8a80" if update_available else "#ffffff"
    if icon_only:
        return f"""
            QToolButton {{
                background-color: transparent;
                border: none;
                {border_prop}: 3px solid transparent;
                color: {text_color};
                padding: 0px;
                margin: 0px;
            }}
            QToolButton:hover {{
                background-color: #3e3e42;
            }}
            QToolButton:checked {{
                background-color: #37373d;
                {border_prop}: 3px solid {accent};
                color: {checked_color};
            }}
        """

    font_size = "18px" if sys.platform.startswith("linux") else "24px"
    return f"""
        QToolButton {{
            background-color: transparent;
            border: none;
            {border_prop}: 3px solid transparent;
            color: {text_color};
            font-size: {font_size};
            font-family: 'DejaVu Sans Mono', monospace;
            padding: 0px;
            margin: 0px;
        }}
        QToolButton:hover {{
            background-color: #3e3e42;
        }}
        QToolButton:checked {{
            background-color: #37373d;
            {border_prop}: 3px solid {accent};
            color: {checked_color};
        }}
    """


def configure_nav_toolbutton(
    btn,
    icon_text: str,
    *,
    horizontal: bool = False,
    update_available: bool = False,
) -> None:
    """Apply nav icon — on Linux render BMP symbols into fixed pixmaps for alignment."""
    if sys.platform.startswith("linux"):
        # Scale to the button cell (leave room for the 3px active border).
        icon_dim = max(28, min(btn.width(), btn.height()) - 8)
        font_px = max(22, int(icon_dim * 0.78))
        normal_color = QColor("#ff5252") if update_available else None
        btn.setIcon(_linux_nav_icon(icon_text, size=icon_dim, font_px=font_px, normal_color=normal_color))
        btn.setIconSize(QSize(icon_dim, icon_dim))
        btn.setText("")
        btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
        btn.setStyleSheet(_nav_toolbutton_stylesheet(
            horizontal=horizontal, icon_only=True, update_available=update_available,
        ))
        return

    btn.setIcon(QIcon())
    btn.setText(icon_text)
    btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
    btn.setStyleSheet(_nav_toolbutton_stylesheet(
        horizontal=horizontal, icon_only=False, update_available=update_available,
    ))
