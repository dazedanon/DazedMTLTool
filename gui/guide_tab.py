"""Guide / Quickstart tab - markdown-driven in-app documentation."""

from __future__ import annotations

import json
import re
from html import unescape
from pathlib import Path
from urllib.parse import unquote, urlsplit

from PyQt5.QtCore import QEvent, QTimer, QUrl, Qt
from PyQt5.QtGui import QColor, QImageReader
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QStyle,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from util.paths import HELP_DIR
from gui.theme import COLORS
from gui.ui_components import (
    PageHeader,
    equalize_button_widths,
    make_action_button,
    make_page_layout,
)

try:
    import markdown as _markdown
except ImportError:  # pragma: no cover - dependency should be installed via requirements
    _markdown = None


def _theme_css(source: str) -> str:
    for name, value in sorted(vars(COLORS).items(), key=lambda item: -len(item[0])):
        source = source.replace(f"${name}", value)
    return source


_BROWSER_CSS = _theme_css("""
body {
    color: $text_secondary;
    background-color: $canvas;
    font-family: Segoe UI, sans-serif;
    font-size: 14px;
    line-height: 1.45;
    margin: 12px 16px;
}
h1, h2, h3, h4 {
    color: $text_primary;
    font-weight: 600;
    margin-top: 1.1em;
    margin-bottom: 0.4em;
}
h1 { font-size: 22px; }
h2 { font-size: 18px; border-bottom: 1px solid $border; padding-bottom: 4px; }
h3 { font-size: 15px; color: $text_primary; }
p, li { color: $text_secondary; }
a { color: $accent_text; }
code {
    background-color: $surface_1;
    color: $warning;
    padding: 1px 5px;
    border-radius: 3px;
    font-family: Consolas, monospace;
    font-size: 13px;
}
pre {
    background-color: $chrome;
    border: 1px solid $border;
    border-radius: 4px;
    padding: 10px 12px;
    overflow-x: auto;
}
pre code {
    background: transparent;
    color: $text_secondary;
    padding: 0;
}
table {
    border-collapse: collapse;
    margin: 10px 0;
    width: 100%;
}
th, td {
    border: 1px solid $border;
    padding: 6px 10px;
    text-align: left;
    vertical-align: top;
}
th { background-color: $surface_1; color: $text_primary; }
strong { color: $text_primary; }
hr { border: none; border-top: 1px solid $border; margin: 16px 0; }
blockquote {
    border-left: 3px solid $accent;
    margin: 10px 0;
    padding: 4px 12px;
    color: $text_muted;
    background-color: $chrome;
}
img {
    display: block;
    max-width: 100%;
    height: auto;
}
""")

_LIST_STYLE = _theme_css("""
QListWidget {
    background-color: $chrome;
    color: $text_secondary;
    border: 1px solid $border;
    border-radius: 4px;
    outline: none;
    font-size: 13px;
    padding: 4px;
}
QListWidget::item {
    padding: 8px 10px;
    border-radius: 3px;
}
QListWidget::item:selected {
    background-color: $selection;
    color: $on_accent;
}
QListWidget::item:hover:!selected {
    background-color: $surface_hover;
}
""")

_BROWSER_STYLE = _theme_css("""
QTextBrowser {
    background-color: $canvas;
    color: $text_secondary;
    border: 1px solid $border;
    border-radius: 4px;
    padding: 0;
}
""")

_IMG_TAG_RE = re.compile(r"<img\b(?P<attrs>[^>]*)>", re.IGNORECASE)
_IMG_SRC_RE = re.compile(
    r"\bsrc\s*=\s*(?P<quote>['\"])(?P<src>.*?)(?P=quote)",
    re.IGNORECASE,
)
_IMG_PARAGRAPH_RE = re.compile(
    r"<p>\s*(?P<image><img\b[^>]*>)\s*</p>",
    re.IGNORECASE,
)


def _fit_local_images(body: str, help_dir: Path, max_width: int) -> str:
    """Give Qt explicit image widths because its rich text ignores max-width."""

    root = help_dir.resolve()

    def fit(match: re.Match[str]) -> str:
        attrs = match.group("attrs")
        src_match = _IMG_SRC_RE.search(attrs)
        if src_match is None or re.search(r"\bwidth\s*=", attrs, re.IGNORECASE):
            return match.group(0)
        src = unescape(src_match.group("src"))
        split = urlsplit(src)
        if split.scheme or split.netloc:
            return match.group(0)
        path = (root / unquote(split.path)).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            return match.group(0)
        size = QImageReader(str(path)).size()
        if not size.isValid() or size.width() <= 0:
            return match.group(0)
        width = min(size.width(), max(1, max_width))
        height = max(1, round(size.height() * width / size.width()))
        return f'<img width="{width}" height="{height}"{attrs}>'

    fitted = _IMG_TAG_RE.sub(fit, body)
    return _IMG_PARAGRAPH_RE.sub(
        r'<p style="line-height:100%;margin:12px 0 6px 0;">\g<image></p>',
        fitted,
    )


def _md_to_html(
    source: str,
    *,
    help_dir: Path | None = None,
    image_width: int | None = None,
) -> str:
    if _markdown is not None:
        body = _markdown.markdown(
            source,
            extensions=["fenced_code", "tables", "nl2br", "sane_lists"],
        )
    else:
        escaped = (
            source.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        body = f"<pre style='white-space:pre-wrap;font-family:Segoe UI,sans-serif;'>{escaped}</pre>"
    if help_dir is not None and image_width is not None:
        body = _fit_local_images(body, help_dir, image_width)
    return (
        "<html><head><meta charset='utf-8'>"
        f"<style>{_BROWSER_CSS}</style></head>"
        f"<body>{body}</body></html>"
    )


class GuideTab(QWidget):
    """Sidebar Guide page: section list + rendered markdown from data/help/."""

    def __init__(self, parent=None, help_dir: Path | None = None):
        super().__init__(parent)
        self.parent_window = parent
        self.help_dir = Path(help_dir) if help_dir else HELP_DIR
        self._sections: list[dict] = []
        self._current_source: str | None = None
        self._image_resize_pending = False
        self._rendered_image_width = -1
        self._render_generation = 0
        self._build_ui()
        self.reload()

    def _build_ui(self) -> None:
        root = make_page_layout(self)
        root.addWidget(PageHeader(
            "Beginner's Guide",
            "Read the first group in order. Use Extra Information only when you need it."
        ))

        body = QHBoxLayout()
        body.setSpacing(12)

        self.section_list = QListWidget()
        self.section_list.setStyleSheet(_LIST_STYLE)
        self.section_list.setMinimumWidth(260)
        self.section_list.setMaximumWidth(360)
        self.section_list.currentRowChanged.connect(self._on_section_changed)
        body.addWidget(self.section_list)

        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.setStyleSheet(_BROWSER_STYLE)
        self.browser.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.browser.document().setBaseUrl(
            QUrl.fromLocalFile(f"{self.help_dir.resolve().as_posix()}/")
        )
        self.browser.installEventFilter(self)
        body.addWidget(self.browser, 1)

        root.addLayout(body, 1)

        footer = QHBoxLayout()
        footer.setSpacing(8)

        self.btn_workflow = make_action_button("Open Workflow", variant="primary")
        self.btn_workflow.clicked.connect(self._open_workflow)
        footer.addWidget(self.btn_workflow)

        self.btn_config = make_action_button("Open Configuration")
        self.btn_config.clicked.connect(self._open_config)
        footer.addWidget(self.btn_config)

        footer.addStretch()

        reload_btn = make_action_button("Refresh this page", variant="quiet")
        reload_btn.setToolTip(
            "Reload the Guide if its text was changed while DazedTL was open"
        )
        reload_btn.clicked.connect(self.reload)
        footer.addWidget(reload_btn)

        equalize_button_widths((self.btn_workflow, self.btn_config), minimum=176)

        root.addLayout(footer)

    def reload(self) -> None:
        """Reload the section index and re-select the current (or first) section."""
        previous_id = None
        row = self.section_list.currentRow()
        if 0 <= row < len(self._sections) and self._sections[row].get("file"):
            previous_id = self._sections[row].get("id")

        self._sections = self._load_index()
        self.section_list.blockSignals(True)
        self.section_list.clear()
        select_row = next(
            (i for i, section in enumerate(self._sections) if section.get("file")),
            -1,
        )
        for i, section in enumerate(self._sections):
            title = section.get("title") or section.get("id") or f"Section {i + 1}"
            if section.get("type") == "group":
                title = title.upper()
            item = QListWidgetItem(title)
            item.setData(Qt.UserRole, section)
            if section.get("type") == "group":
                # Keep group headings as labels, but leave them enabled so Qt does
                # not dim their foreground color like disabled list items.
                item.setFlags(Qt.ItemIsEnabled)
                font = item.font()
                font.setBold(True)
                font.setPointSize(font.pointSize() + 1)
                item.setFont(font)
                item.setForeground(QColor(COLORS.text_primary))
            self.section_list.addItem(item)
            if previous_id and section.get("file") and section.get("id") == previous_id:
                select_row = i
        self.section_list.blockSignals(False)

        if select_row >= 0:
            self.section_list.setCurrentRow(select_row)
        else:
            self._current_source = None
            self._render_generation += 1
            self.browser.setHtml(
                _md_to_html(
                    "# Guide unavailable\n\n"
                    f"No sections found under `{self.help_dir}`.\n"
                    "Add `index.json` and markdown files to restore this page."
                )
            )

    def _load_index(self) -> list[dict]:
        index_path = self.help_dir / "index.json"
        if not index_path.is_file():
            return []
        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(data, list):
            return []
        return [
            section
            for section in data
            if isinstance(section, dict)
            and (section.get("file") or section.get("type") == "group")
        ]

    def _on_section_changed(self, row: int) -> None:
        if row < 0 or row >= len(self._sections):
            return
        section = self._sections[row]
        if not section.get("file"):
            return
        rel = section.get("file", "")
        path = self.help_dir / rel
        if not path.is_file():
            self._current_source = None
            self._render_generation += 1
            self.browser.setHtml(
                _md_to_html(f"# Missing file\n\nCould not find `{rel}` under `data/help/`.")
            )
            return
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            self._current_source = None
            self._render_generation += 1
            self.browser.setHtml(_md_to_html(f"# Read error\n\n{exc}"))
            return
        self._current_source = source
        self._render_source(reset_scroll=True)

    def _render_source(self, *, reset_scroll: bool) -> None:
        if self._current_source is None:
            return
        scrollbar = self.browser.verticalScrollBar()
        old_maximum = scrollbar.maximum()
        old_ratio = scrollbar.value() / old_maximum if old_maximum else 0.0
        was_at_bottom = bool(old_maximum and scrollbar.value() >= old_maximum - 2)
        image_width = self._available_image_width()
        self._rendered_image_width = image_width
        self._render_generation += 1
        generation = self._render_generation
        self.browser.setHtml(
            _md_to_html(
                self._current_source,
                help_dir=self.help_dir,
                image_width=image_width,
            )
        )
        if reset_scroll:
            scrollbar.setValue(0)
        else:
            QTimer.singleShot(
                0,
                lambda: self._restore_scroll_position(
                    old_ratio,
                    was_at_bottom,
                    generation,
                ),
            )

    def _available_image_width(self) -> int:
        """Return a stable width that already reserves the vertical scrollbar."""

        scrollbar_width = self.browser.style().pixelMetric(QStyle.PM_ScrollBarExtent)
        # Account for the document body margins, browser frame, and a scrollbar
        # even before the document is tall enough to display one. Using the
        # viewport width here causes a render loop as that scrollbar appears.
        return max(160, self.browser.contentsRect().width() - scrollbar_width - 48)

    def _restore_scroll_position(
        self,
        ratio: float,
        was_at_bottom: bool,
        generation: int,
    ) -> None:
        if generation != self._render_generation:
            return
        scrollbar = self.browser.verticalScrollBar()
        if was_at_bottom:
            scrollbar.setValue(scrollbar.maximum())
        else:
            scrollbar.setValue(round(scrollbar.maximum() * ratio))

    def eventFilter(self, watched, event):
        if (
            watched is self.browser
            and event.type() == QEvent.Resize
            and self._current_source is not None
        ):
            image_width = self._available_image_width()
            if image_width != self._rendered_image_width and not self._image_resize_pending:
                self._image_resize_pending = True
                QTimer.singleShot(0, self._rerender_for_viewport)
        return super().eventFilter(watched, event)

    def _rerender_for_viewport(self) -> None:
        self._image_resize_pending = False
        self._render_source(reset_scroll=False)

    def show_section(self, section_id: str) -> bool:
        """Select a section by id. Returns True if found."""
        for i, section in enumerate(self._sections):
            if section.get("id") == section_id:
                self.section_list.setCurrentRow(i)
                return True
        return False

    def _open_workflow(self) -> None:
        pw = self.parent_window
        if pw is not None and hasattr(pw, "switch_page"):
            page = getattr(pw, "PAGE_WORKFLOW", 1)
            pw.switch_page(page)

    def _open_config(self) -> None:
        pw = self.parent_window
        if pw is not None and hasattr(pw, "switch_page"):
            page = getattr(pw, "PAGE_CONFIG", 7)
            pw.switch_page(page)
