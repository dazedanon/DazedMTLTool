"""Skills Tab - edit tool-level skills and translation contexts under data/."""

from __future__ import annotations

import json
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from util.paths import PROMPT_PATH, SKILLS_DIR, TRANSLATION_CONTEXTS_PATH
from util.skills.contexts import reload_contexts


class _PlainPasteTextEdit(QTextEdit):
    """QTextEdit that always pastes as plain text."""

    def insertFromMimeData(self, source):  # noqa: N802
        self.insertPlainText(source.text())


_EDITOR_STYLE = (
    "QTextEdit{background-color:#1e1e1e;color:#d4d4d4;"
    "border:1px solid #3c3c3c;border-radius:4px;padding:10px;"
    "selection-background-color:#264f78;}"
)

_HINT_STYLE = "color:#9d9d9d;font-size:13px;"
_PATH_STYLE = "color:#569cd6;font-size:12px;font-family:Consolas,monospace;"


class SkillsTab(QWidget):
    """Edit ``data/skills/*.md`` and ``data/translation_contexts.json``."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pages: dict[str, dict] = {}
        self._build_ui()
        self.reload_all()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(10)

        title = QLabel("Skills")
        title.setStyleSheet("color:#ffffff;font-size:18px;font-weight:bold;")
        root.addWidget(title)

        intro = QLabel(
            "Tool-level AI instructions live here. "
            "Per-game quirks, Translation Frame (game skill), and optional custom skills are edited "
            "in Workflow Step 2 (they travel with the game folder and merge into the API prompt)."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(_HINT_STYLE)
        root.addWidget(intro)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(
            "QTabWidget::pane{border:1px solid #3c3c3c;border-radius:4px;top:-1px;}"
            "QTabBar::tab{background:#2d2d30;color:#cccccc;padding:8px 14px;"
            "border:1px solid #3c3c3c;border-bottom:none;margin-right:2px;}"
            "QTabBar::tab:selected{background:#1e1e1e;color:#ffffff;"
            "border-top:2px solid #007acc;}"
        )
        root.addWidget(self.tabs, 1)

        self._add_file_page(
            key="system",
            tab_title="System",
            path=PROMPT_PATH,
            hint=(
                "Runtime system prompt for every translation API call. "
                "Honorifics, formatting, and universal quality rules live here. "
                "Do not put game-specific voice quirks here - use <game>/skills/quirks.md."
            ),
            is_json=False,
        )
        self._add_file_page(
            key="project_setup",
            tab_title="Project Setup",
            path=SKILLS_DIR / "project_setup.md",
            hint=(
                "Clipboard skill copied from Workflow. "
                "Instructs the IDE to emit glossary, speakers, quirks, and game_skill blocks."
            ),
            is_json=False,
        )
        self._add_file_page(
            key="wrap_config",
            tab_title="Wrap Config",
            path=SKILLS_DIR / "wrap_config.md",
            hint="Clipboard prompt that asks the IDE to calculate RPG Maker wrap widths.",
            is_json=False,
        )
        self._add_file_page(
            key="plugin_translation",
            tab_title="Plugin TL",
            path=SKILLS_DIR / "plugin_translation.md",
            hint="MV/MZ plugin localisation audit and approved in-place translation prompt.",
            is_json=False,
        )
        self._add_file_page(
            key="ace_script_translation",
            tab_title="Ace Script TL",
            path=SKILLS_DIR / "ace_script_translation.md",
            hint="VX Ace Ruby script localisation audit and approved in-place translation prompt.",
            is_json=False,
        )
        self._add_file_page(
            key="rpgmaker_translation_qa",
            tab_title="Translation QA",
            path=SKILLS_DIR / "rpgmaker_translation_qa.md",
            hint=(
                "Post-export RPG Maker game-data audit. Keep the {{GAME_DATA_FOLDER}}, "
                "{{GAME_ROOT}}, and {{VOCAB_FILE}} placeholders."
            ),
            is_json=False,
        )
        self._add_file_page(
            key="image_translation",
            tab_title="Image TL",
            path=SKILLS_DIR / "image_translation.md",
            hint=(
                "Clipboard skill copied from the Image Manager for deterministic bitmap UI "
                "localisation. Keep the {{ENGINE_NAME}}, {{ENGINE_CONTEXT}}, {{GAME_ROOT}}, "
                "{{EDITABLE_IMAGES_FOLDER}}, and {{VOCAB_FILE}} placeholders."
            ),
            is_json=False,
        )
        self._add_file_page(
            key="risky_codes",
            tab_title="Risky Codes",
            path=SKILLS_DIR / "risky_codes.md",
            hint="Clipboard prompt for auditing optional RPG Maker event-code translation settings.",
            is_json=False,
        )
        self._add_file_page(
            key="wolf_speakers",
            tab_title="WOLF Speakers",
            path=SKILLS_DIR / "wolf_speakers.md",
            hint="Clipboard prompt for reviewing WOLF low-confidence first-line speakers.",
            is_json=False,
        )
        self._add_file_page(
            key="contexts",
            tab_title="Contexts",
            path=TRANSLATION_CONTEXTS_PATH,
            hint=(
                "Per-call history templates used by RPG Maker / WolfDawn "
                "(names.npc, database.item, events.label_108, …). "
                "Edit carefully - keys must match what the engine modules look up."
            ),
            is_json=True,
        )

        btn_row = QHBoxLayout()
        reload_btn = QPushButton("↺  Reload All")
        reload_btn.setFixedWidth(140)
        reload_btn.clicked.connect(self.reload_all)
        btn_row.addWidget(reload_btn)
        btn_row.addStretch()
        open_btn = QPushButton("Open skills folder")
        open_btn.setFixedWidth(160)
        open_btn.clicked.connect(self._open_skills_folder)
        btn_row.addWidget(open_btn)
        root.addLayout(btn_row)

    def _add_file_page(
        self,
        *,
        key: str,
        tab_title: str,
        path: Path,
        hint: str,
        is_json: bool,
    ):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        path_lbl = QLabel(str(path))
        path_lbl.setStyleSheet(_PATH_STYLE)
        path_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(path_lbl)

        hint_lbl = QLabel(hint)
        hint_lbl.setWordWrap(True)
        hint_lbl.setStyleSheet(_HINT_STYLE)
        layout.addWidget(hint_lbl)

        editor = _PlainPasteTextEdit()
        editor.setFont(QFont("Consolas", 10))
        editor.setStyleSheet(_EDITOR_STYLE)
        layout.addWidget(editor, 1)

        row = QHBoxLayout()
        save_btn = QPushButton("💾  Save")
        save_btn.setFixedWidth(120)
        save_btn.clicked.connect(lambda _=False, k=key: self._save_page(k))
        row.addWidget(save_btn)

        reload_btn = QPushButton("↺  Reload")
        reload_btn.setFixedWidth(120)
        reload_btn.clicked.connect(lambda _=False, k=key: self._reload_page(k))
        row.addWidget(reload_btn)

        status = QLabel("")
        status.setStyleSheet("color:#6a9955;font-size:12px;")
        row.addWidget(status)
        row.addStretch()
        layout.addLayout(row)

        self.tabs.addTab(page, tab_title)
        self._pages[key] = {
            "path": path,
            "editor": editor,
            "status": status,
            "is_json": is_json,
        }

    def reload_all(self):
        for key in self._pages:
            self._reload_page(key)

    def _reload_page(self, key: str):
        page = self._pages[key]
        path: Path = page["path"]
        editor: QTextEdit = page["editor"]
        status: QLabel = page["status"]
        try:
            if not path.is_file():
                editor.setPlainText("")
                status.setText(f"Missing: {path.name}")
                status.setStyleSheet("color:#f0ad4e;font-size:12px;")
                return
            editor.setPlainText(path.read_text(encoding="utf-8"))
            status.setText("Loaded")
            status.setStyleSheet("color:#6a9955;font-size:12px;")
        except Exception as exc:
            status.setText(f"Load failed: {exc}")
            status.setStyleSheet("color:#f44747;font-size:12px;")

    def _save_page(self, key: str):
        page = self._pages[key]
        path: Path = page["path"]
        editor: QTextEdit = page["editor"]
        status: QLabel = page["status"]
        text = editor.toPlainText()
        if page["is_json"]:
            try:
                parsed = json.loads(text)
                text = json.dumps(parsed, ensure_ascii=False, indent=2) + "\n"
                editor.setPlainText(text.rstrip("\n") + "\n")
            except json.JSONDecodeError as exc:
                QMessageBox.warning(
                    self,
                    "Invalid JSON",
                    f"Cannot save {path.name}:\n{exc}",
                )
                status.setText("Invalid JSON")
                status.setStyleSheet("color:#f44747;font-size:12px;")
                return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
            if key == "contexts":
                reload_contexts()
            status.setText(f"Saved {path.name}")
            status.setStyleSheet("color:#6a9955;font-size:12px;")
        except Exception as exc:
            QMessageBox.warning(self, "Save failed", str(exc))
            status.setText(f"Save failed: {exc}")
            status.setStyleSheet("color:#f44747;font-size:12px;")

    def _open_skills_folder(self):
        folder = SKILLS_DIR
        folder.mkdir(parents=True, exist_ok=True)
        import os
        import subprocess
        import sys

        try:
            if sys.platform.startswith("win"):
                os.startfile(str(folder))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", str(folder)], check=False)
            else:
                subprocess.run(["xdg-open", str(folder)], check=False)
        except Exception as exc:
            QMessageBox.information(self, "Skills folder", f"{folder}\n\n{exc}")
