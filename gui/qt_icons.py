"""Centralized icon helpers backed by qtawesome.

qtawesome renders icons from bundled fonts (Material Design Icons, etc.) into
real ``QIcon``/``QPixmap`` objects, so they look identical on Windows and Linux
and avoid the emoji "tofu" problem on Linux font stacks.

Everything degrades gracefully: if qtawesome is unavailable the helpers fall
back to the legacy ``platform_glyph`` text so the UI still renders.
"""

from __future__ import annotations

import re

from PyQt5.QtCore import QSize, Qt
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QWidget

try:
    import qtawesome as qta

    HAS_QTA = True
except Exception:  # pragma: no cover - only when the optional dep is missing
    qta = None  # type: ignore[assignment]
    HAS_QTA = False

# Neutral light gray that matches the app's default text on dark surfaces.
DEFAULT_COLOR = "#cccccc"
ACCENT_COLOR = "#007acc"

# Map the emoji/symbols used across the GUI to Material Design Icon names.
# Multi-character keys (e.g. "►►", "⚙️" with variation selector) are matched
# before single characters, so order-independent longest-match lookup works.
EMOJI_ICON: dict[str, str] = {
    "►►": "mdi6.fast-forward",
    "⚙️": "mdi6.cog",
    "🖥️": "mdi6.monitor",
    "🖼️": "mdi6.image-multiple-outline",
    "⚔️": "mdi6.sword-cross",
    "⚠️": "mdi6.alert-outline",
    "🌐": "mdi6.web",
    "⚡": "mdi6.lightning-bolt",
    "⚙": "mdi6.cog",
    "🔧": "mdi6.wrench-outline",
    "🔑": "mdi6.key-variant",
    "📝": "mdi6.text-box-outline",
    "💰": "mdi6.currency-usd",
    "🖥": "mdi6.monitor",
    "📁": "mdi6.folder-open-outline",
    "📂": "mdi6.folder-open-outline",
    "📄": "mdi6.file-document-outline",
    "🗺": "mdi6.map-outline",
    "❓": "mdi6.help-circle-outline",
    "💬": "mdi6.message-text-outline",
    "🖼": "mdi6.image-multiple-outline",
    "🎮": "mdi6.gamepad-variant-outline",
    "📚": "mdi6.bookshelf",
    "👤": "mdi6.account",
    "📋": "mdi6.clipboard-text-outline",
    "📊": "mdi6.table-column",
    "📤": "mdi6.export",
    "📥": "mdi6.import",
    "🔄": "mdi6.refresh",
    "↺": "mdi6.refresh",
    "↻": "mdi6.refresh",
    "⇄": "mdi6.swap-horizontal",
    "🔍": "mdi6.magnify",
    "💾": "mdi6.content-save",
    "🗑️": "mdi6.delete-outline",
    "🗑": "mdi6.delete-outline",
    "➕": "mdi6.plus",
    "🛑": "mdi6.stop-circle-outline",
    "⚔": "mdi6.sword-cross",
    "⬇": "mdi6.download",
    "⬆": "mdi6.upload",
    "↓": "mdi6.import",
    "↑": "mdi6.export",
    "►": "mdi6.play",
    "▶": "mdi6.play",
    "◆": "mdi6.diamond-stone",
    "☑": "mdi6.checkbox-marked-outline",
    "☐": "mdi6.checkbox-blank-outline",
    "▼": "mdi6.chevron-down",
    "◄": "mdi6.chevron-left",
    "←": "mdi6.arrow-left",
    "→": "mdi6.arrow-right",
    "✓": "mdi6.check-bold",
    "✔": "mdi6.check-bold",
    "✅": "mdi6.check-circle-outline",
    "✗": "mdi6.close-thick",
    "✕": "mdi6.close-thick",
    "❌": "mdi6.close-circle-outline",
    "⚠": "mdi6.alert-outline",
}

# Leading symbol/emoji cluster at the start of a button/header label.
_LEADING_SYMBOLS = re.compile(
    r"^[\s]*("
    r"[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U00002190-\U000021FF"
    r"\U00002300-\U000023FF\U000025A0-\U000025FF\U00002B00-\U00002BFF"
    r"\uFE0F\u2028\u2029]+"
    r")\s*"
)


# File-list categories -> (icon name, tint color).
_FILE_CATEGORY_ICONS: dict[str, tuple[str, str]] = {
    "core": ("mdi6.file-document-outline", "#9cdcfe"),
    "map": ("mdi6.map-outline", "#c5c5c0"),
    "other": ("mdi6.help-circle-outline", "#888888"),
}


def file_category_icon(category: str) -> QIcon:
    """Return the list icon for a file category (``core`` / ``map`` / other)."""
    name, color = _FILE_CATEGORY_ICONS.get(category, _FILE_CATEGORY_ICONS["other"])
    return get_icon(name, color=color)


def get_icon(name: str, color: str = DEFAULT_COLOR, **kwargs) -> QIcon:
    """Return a qtawesome ``QIcon`` (empty ``QIcon`` if unavailable)."""
    if not HAS_QTA:
        return QIcon()
    try:
        return qta.icon(name, color=color, **kwargs)
    except Exception:
        return QIcon()


def get_pixmap(name: str, size: int, color: str = DEFAULT_COLOR) -> QPixmap:
    """Render a qtawesome icon to a square ``QPixmap`` (empty if unavailable)."""
    if not HAS_QTA:
        return QPixmap()
    try:
        return qta.icon(name, color=color).pixmap(QSize(size, size))
    except Exception:
        return QPixmap()


def two_state_icon(
    name: str,
    size: int,
    *,
    off_color: str,
    on_color: str,
    disabled_color: str | None = None,
) -> QIcon:
    """Build a nav ``QIcon`` whose On (checked) pixmap uses a brighter color."""
    icon = QIcon()
    if not HAS_QTA:
        return icon
    off_pix = get_pixmap(name, size, off_color)
    on_pix = get_pixmap(name, size, on_color)
    dis_pix = get_pixmap(name, size, disabled_color or off_color)
    icon.addPixmap(off_pix, QIcon.Normal, QIcon.Off)
    icon.addPixmap(on_pix, QIcon.Active, QIcon.Off)
    icon.addPixmap(on_pix, QIcon.Normal, QIcon.On)
    icon.addPixmap(on_pix, QIcon.Active, QIcon.On)
    icon.addPixmap(on_pix, QIcon.Selected, QIcon.On)
    icon.addPixmap(dis_pix, QIcon.Disabled, QIcon.Off)
    return icon


def split_leading_symbol(text: str) -> tuple[str | None, str]:
    """Split a leading emoji/symbol cluster from *text*.

    Returns ``(icon_name_or_None, remaining_text)``. The icon name is resolved
    from :data:`EMOJI_ICON` using a longest-match on the leading cluster, then a
    first-character fallback.
    """
    match = _LEADING_SYMBOLS.match(text)
    if not match:
        return None, text
    cluster = match.group(1).strip()
    rest = text[match.end():].strip()

    if cluster in EMOJI_ICON:
        return EMOJI_ICON[cluster], rest
    # Try progressively shorter prefixes, then the first character.
    for length in range(len(cluster), 0, -1):
        prefix = cluster[:length]
        if prefix in EMOJI_ICON:
            return EMOJI_ICON[prefix], rest
    if cluster and cluster[0] in EMOJI_ICON:
        return EMOJI_ICON[cluster[0]], rest
    return None, rest


def icon_for_emoji(emoji: str) -> str | None:
    """Return the MDI icon name mapped to *emoji*, or ``None``."""
    name, _ = split_leading_symbol(emoji)
    return name


def apply_button_icon(btn, raw_text: str, color: str = DEFAULT_COLOR) -> None:
    """Set a labeled button's icon from its leading emoji and strip the emoji.

    Falls back to the legacy ``platform_glyph`` text when qtawesome is missing or
    no icon mapping exists.
    """
    from gui.platform_glyph import platform_glyph

    icon_name, rest = split_leading_symbol(raw_text)
    if HAS_QTA and icon_name and rest:
        btn.setIcon(get_icon(icon_name, color=color))
        btn.setText(rest)
        return
    if HAS_QTA and icon_name and not rest:
        # Icon-only button.
        btn.setIcon(get_icon(icon_name, color=color))
        btn.setText("")
        return
    btn.setText(platform_glyph(raw_text))


def make_section_header(
    title: str,
    text_stylesheet: str,
    *,
    icon_color: str = ACCENT_COLOR,
    icon_px: int = 15,
) -> QWidget:
    """Build a section header row: a qtawesome icon (from the leading emoji) plus
    the styled title text.

    When qtawesome is unavailable, falls back to a plain ``QLabel`` using the
    legacy ``platform_glyph`` text so behavior is unchanged.
    """
    from gui.platform_glyph import platform_glyph

    icon_name, rest = split_leading_symbol(title)

    if not (HAS_QTA and icon_name):
        label = QLabel(platform_glyph(title))
        label.setStyleSheet(text_stylesheet)
        return label

    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)

    icon_label = QLabel()
    icon_label.setPixmap(get_pixmap(icon_name, icon_px, icon_color))
    icon_label.setStyleSheet("background: transparent; padding: 0;")
    icon_label.setAlignment(Qt.AlignVCenter)
    layout.addWidget(icon_label, 0, Qt.AlignVCenter)

    text_label = QLabel(rest)
    text_label.setStyleSheet(text_stylesheet)
    layout.addWidget(text_label, 0, Qt.AlignVCenter)
    layout.addStretch()

    return container
