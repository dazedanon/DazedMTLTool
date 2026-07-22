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
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from util.paths import HELP_DIR

try:
    import markdown as _markdown
except ImportError:  # pragma: no cover - dependency should be installed via requirements
    _markdown = None


_BROWSER_CSS = """
body {
    color: #d4d4d4;
    background-color: #1e1e1e;
    font-family: Segoe UI, sans-serif;
    font-size: 14px;
    line-height: 1.45;
    margin: 12px 16px;
}
h1, h2, h3, h4 {
    color: #ffffff;
    font-weight: 600;
    margin-top: 1.1em;
    margin-bottom: 0.4em;
}
h1 { font-size: 22px; }
h2 { font-size: 18px; border-bottom: 1px solid #3c3c3c; padding-bottom: 4px; }
h3 { font-size: 15px; color: #e0e0e0; }
p, li { color: #d4d4d4; }
a { color: #569cd6; }
code {
    background-color: #2d2d30;
    color: #ce9178;
    padding: 1px 5px;
    border-radius: 3px;
    font-family: Consolas, monospace;
    font-size: 13px;
}
pre {
    background-color: #252526;
    border: 1px solid #3c3c3c;
    border-radius: 4px;
    padding: 10px 12px;
    overflow-x: auto;
}
pre code {
    background: transparent;
    color: #d4d4d4;
    padding: 0;
}
table {
    border-collapse: collapse;
    margin: 10px 0;
    width: 100%;
}
th, td {
    border: 1px solid #3c3c3c;
    padding: 6px 10px;
    text-align: left;
    vertical-align: top;
}
th { background-color: #2d2d30; color: #ffffff; }
strong { color: #ffffff; }
hr { border: none; border-top: 1px solid #3c3c3c; margin: 16px 0; }
blockquote {
    border-left: 3px solid #007acc;
    margin: 10px 0;
    padding: 4px 12px;
    color: #9d9d9d;
    background-color: #252526;
}
"""

_LIST_STYLE = """
QListWidget {
    background-color: #252526;
    color: #cccccc;
    border: 1px solid #3c3c3c;
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
    background-color: #094771;
    color: #ffffff;
}
QListWidget::item:hover:!selected {
    background-color: #2a2d2e;
}
"""

_BROWSER_STYLE = """
QTextBrowser {
    background-color: #1e1e1e;
    color: #d4d4d4;
    border: 1px solid #3c3c3c;
    border-radius: 4px;
    padding: 0;
}
"""

_BTN_STYLE = """
QPushButton {
    background-color: #0e639c;
    color: #ffffff;
    border: none;
    border-radius: 4px;
    padding: 8px 14px;
    font-size: 13px;
}
QPushButton:hover { background-color: #1177bb; }
QPushButton:pressed { background-color: #0a4d78; }
"""

_SECONDARY_BTN_STYLE = """
QPushButton {
    background-color: #3c3c3c;
    color: #d4d4d4;
    border: 1px solid #555555;
    border-radius: 4px;
    padding: 8px 14px;
    font-size: 13px;
}
QPushButton:hover { background-color: #4a4a4a; }
"""


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
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(10)

        title = QLabel("Guide / Quickstart")
        title.setStyleSheet("color:#ffffff;font-size:18px;font-weight:bold;")
        root.addWidget(title)

        intro = QLabel(
            "In-app docs for requirements, Workflow, and copy-paste examples. "
            "Edit markdown under data/help/ to keep this up to date."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#9d9d9d;font-size:13px;")
        root.addWidget(intro)

        body = QHBoxLayout()
        body.setSpacing(12)

        self.section_list = QListWidget()
        self.section_list.setFixedWidth(200)
        self.section_list.setStyleSheet(_LIST_STYLE)
        self.section_list.currentRowChanged.connect(self._on_section_changed)
        body.addWidget(self.section_list)

        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.setStyleSheet(_BROWSER_STYLE)
        body.addWidget(self.browser, 1)

        root.addLayout(body, 1)

        footer = QHBoxLayout()
        footer.setSpacing(8)

        self.btn_workflow = QPushButton("Open Workflow")
        self.btn_workflow.setStyleSheet(_BTN_STYLE)
        self.btn_workflow.setCursor(Qt.PointingHandCursor)
        self.btn_workflow.clicked.connect(self._open_workflow)
        footer.addWidget(self.btn_workflow)

        self.btn_config = QPushButton("Open Configuration")
        self.btn_config.setStyleSheet(_SECONDARY_BTN_STYLE)
        self.btn_config.setCursor(Qt.PointingHandCursor)
        self.btn_config.clicked.connect(self._open_config)
        footer.addWidget(self.btn_config)

        footer.addStretch()

        reload_btn = QPushButton("Reload")
        reload_btn.setFixedWidth(90)
        reload_btn.setStyleSheet(_SECONDARY_BTN_STYLE)
        reload_btn.setToolTip("Reload data/help/index.json and the current section")
        reload_btn.clicked.connect(self.reload)
        footer.addWidget(reload_btn)

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
            page = getattr(pw, "PAGE_CONFIG", 5)
            pw.switch_page(page)
