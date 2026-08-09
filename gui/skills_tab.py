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
    QSizePolicy,
)

from util.paths import PROMPT_PATH, SKILLS_DIR, TRANSLATION_CONTEXTS_PATH
from util.skills.contexts import reload_contexts
from gui.theme import COLORS
from gui.ui_components import (
    PageHeader,
    SectionCard,
    equalize_button_widths,
    make_action_button,
    make_page_layout,
    set_status_text,
)


class _PlainPasteTextEdit(QTextEdit):
    """QTextEdit that always pastes as plain text."""

    def insertFromMimeData(self, source):  # noqa: N802
        self.insertPlainText(source.text())


_EDITOR_STYLE = (
    f"QTextEdit{{background-color:{COLORS.canvas};color:{COLORS.text_secondary};"
    f"border:1px solid {COLORS.border};border-radius:4px;padding:10px;"
    f"selection-background-color:{COLORS.selection};}}"
)

_HINT_STYLE = f"color:{COLORS.text_muted};font-size:12px;"
_PATH_STYLE = f"color:{COLORS.accent_text};font-size:12px;font-family:Consolas,monospace;"


class SkillsTab(QWidget):
    """Edit ``data/skills/*.md`` and ``data/translation_contexts.json``."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pages: dict[str, dict] = {}
        self._build_ui()
        self.reload_all()

    def _build_ui(self):
        root = make_page_layout(self)
        root.addWidget(PageHeader(
            "Skills & Prompts",
            "Edit shared AI instructions and translation contexts used across projects. "
            "Game-specific guidance remains in Workflow Step 2."
        ))

        editor_card = SectionCard(
            "Edit shared instructions",
            "Choose an instruction set, review its scope and file path, then save only intentional changes.",
        )
        editor_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root.addWidget(editor_card, 1)
        self.tabs = QTabWidget()
        editor_card.add_widget(self.tabs, 1)

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
                "Returns paste-ready glossary, quirks, and game skill sections followed by manual settings."
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
            key="wolf_precheck_repair",
            tab_title="WOLF Check Repair",
            path=SKILLS_DIR / "wolf_precheck_repair.md",
            hint=(
                "Clipboard skill generated from WOLF Check issues. Keep the "
                "{{TRANSLATED_DIR}}, {{GAME_ROOT}}, and {{ISSUES}} placeholders."
            ),
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
        reload_btn = make_action_button("Reload all files", variant="quiet")
        reload_btn.clicked.connect(self.reload_all)
        btn_row.addWidget(reload_btn)
        btn_row.addStretch()
        open_btn = make_action_button("Open skills folder")
        open_btn.clicked.connect(self._open_skills_folder)
        btn_row.addWidget(open_btn)
        equalize_button_widths((reload_btn, open_btn), minimum=176)
        editor_card.add_layout(btn_row)

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
        save_btn = make_action_button("Save changes", variant="primary")
        save_btn.clicked.connect(lambda _=False, k=key: self._save_page(k))
        row.addWidget(save_btn)

        reload_btn = make_action_button("Reload file", variant="quiet")
        reload_btn.clicked.connect(lambda _=False, k=key: self._reload_page(k))
        row.addWidget(reload_btn)

        status = QLabel("")
        status.setObjectName("appStatusText")
        row.addWidget(status)
        row.addStretch()
        layout.addLayout(row)
        equalize_button_widths((save_btn, reload_btn), minimum=160)

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
                set_status_text(status, f"Missing: {path.name}", "warning")
                return
            editor.setPlainText(path.read_text(encoding="utf-8"))
            set_status_text(status, "Loaded", "success")
        except Exception as exc:
            set_status_text(status, f"Load failed: {exc}", "error")

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
                set_status_text(status, "Invalid JSON", "error")
                return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
            if key == "contexts":
                reload_contexts()
            set_status_text(status, f"Saved {path.name}", "success")
        except Exception as exc:
            QMessageBox.warning(self, "Save failed", str(exc))
            set_status_text(status, f"Save failed: {exc}", "error")

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
