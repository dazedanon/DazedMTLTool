"""Guide / Quickstart tab - markdown-driven in-app documentation."""

from __future__ import annotations

import json
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from util.paths import HELP_DIR
from gui.theme import COLORS
from gui.ui_components import (
    PageHeader,
    SectionCard,
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

def _md_to_html(source: str) -> str:
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
        self._build_ui()
        self.reload()

    def _build_ui(self) -> None:
        root = make_page_layout(self)
        root.addWidget(PageHeader(
            "Guide & Quickstart",
            "Learn the requirements, follow the translation workflow, and use practical examples."
        ))

        body = QHBoxLayout()
        body.setSpacing(12)

        topics_card = SectionCard(
            "Browse topics",
            "Choose a guide section for requirements, workflows, examples, and troubleshooting.",
        )
        topics_card.setMinimumWidth(260)
        topics_card.setMaximumWidth(360)

        self.section_list = QListWidget()
        self.section_list.setStyleSheet(_LIST_STYLE)
        self.section_list.currentRowChanged.connect(self._on_section_changed)
        topics_card.add_widget(self.section_list, 1)
        body.addWidget(topics_card)

        article_card = SectionCard(
            "Read the guide",
            "Follow the documented path, then open the relevant tool when you are ready.",
        )
        article_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.setStyleSheet(_BROWSER_STYLE)
        article_card.add_widget(self.browser, 1)
        body.addWidget(article_card, 1)

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

        reload_btn = make_action_button("Reload guide", variant="quiet")
        reload_btn.setToolTip(
            "Reload data/help/index.json and the current section after editing the guide files"
        )
        reload_btn.clicked.connect(self.reload)
        footer.addWidget(reload_btn)

        equalize_button_widths((self.btn_workflow, self.btn_config), minimum=176)

        root.addLayout(footer)

    def reload(self) -> None:
        """Reload the section index and re-select the current (or first) section."""
        previous_id = None
        row = self.section_list.currentRow()
        if 0 <= row < len(self._sections):
            previous_id = self._sections[row].get("id")

        self._sections = self._load_index()
        self.section_list.blockSignals(True)
        self.section_list.clear()
        select_row = 0
        for i, section in enumerate(self._sections):
            title = section.get("title") or section.get("id") or f"Section {i + 1}"
            item = QListWidgetItem(title)
            item.setData(Qt.UserRole, section)
            self.section_list.addItem(item)
            if previous_id and section.get("id") == previous_id:
                select_row = i
        self.section_list.blockSignals(False)

        if self._sections:
            self.section_list.setCurrentRow(select_row)
        else:
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
        return [s for s in data if isinstance(s, dict) and s.get("file")]

    def _on_section_changed(self, row: int) -> None:
        if row < 0 or row >= len(self._sections):
            return
        section = self._sections[row]
        rel = section.get("file", "")
        path = self.help_dir / rel
        if not path.is_file():
            self.browser.setHtml(
                _md_to_html(f"# Missing file\n\nCould not find `{rel}` under `data/help/`.")
            )
            return
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            self.browser.setHtml(_md_to_html(f"# Read error\n\n{exc}"))
            return
        self.browser.setHtml(_md_to_html(source))
        self.browser.verticalScrollBar().setValue(0)

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
