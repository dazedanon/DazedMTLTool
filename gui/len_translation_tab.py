"""Len's end-to-end, skill-driven translation handoff."""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import QSettings, QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QPlainTextEdit, QScrollArea, QVBoxLayout, QWidget,
)

from gui.ui_components import PageHeader, SectionCard, make_action_button, make_page_layout, set_status_text
from gui.workflow_components import DisclosureSection
from util.len_translation import BUNDLED_SKILL, MODES, STAGES, LenProject, load_project, prepare_project
from util.paths import APP_NAME, ORG_NAME


class LenTranslationTab(QWidget):
    def __init__(self, parent=None, *, settings=None, skill_root: Path = BUNDLED_SKILL, open_version_tracking=None):
        super().__init__(parent)
        self.settings = settings if settings is not None else QSettings(ORG_NAME, APP_NAME)
        self.skill_root = skill_root
        self._open_version_tracking = open_version_tracking
        self._loaded_game = ""
        self._context_dialog = None
        self._references_dialog = None
        self._prepared: LenProject | None = None
        self._build_ui()
        self.game_edit.setText(self.settings.value("len_method/game_root", "", type=str))
        self._load_game()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        content = QWidget()
        root = make_page_layout(content)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        root.addWidget(PageHeader(
            "Len’s Method",
            "Translate a whole game with Len’s game-translation skill: extraction, glossary, "
            "translation, images, layout, patching and playtesting.",
        ))

        project_card = SectionCard(
            "1. Choose the game and scope",
            "Your AI assistant follows the engine-specific playbook and uses the bundled tools. "
            "Choose the game’s root folder, including its executable and assets.",
        )
        form = QFormLayout()
        self.game_edit = QLineEdit()
        self.game_edit.setPlaceholderText("Game folder")
        self.game_edit.textChanged.connect(self._game_changed)
        self.game_edit.editingFinished.connect(self._load_game)
        browse = make_action_button("Browse…")
        browse.clicked.connect(self._browse)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.game_edit, 1)
        folder_row.addWidget(browse)
        form.addRow("Game folder", folder_row)
        self.stage_combo = QComboBox()
        for key, title in STAGES.items():
            self.stage_combo.addItem(title, key)
        self.stage_combo.currentIndexChanged.connect(self._invalidate)
        form.addRow("Task", self.stage_combo)
        self.mode_combo = QComboBox()
        for key, title in MODES.items():
            self.mode_combo.addItem(title, key)
        self.mode_combo.currentIndexChanged.connect(self._invalidate)
        form.addRow("Translation mode", self.mode_combo)
        self.images_check = QCheckBox("Include all images containing Japanese text")
        self.images_check.setChecked(True)
        self.images_check.toggled.connect(self._invalidate)
        form.addRow("Image scope", self.images_check)
        self.base_check = QCheckBox("Include DazedTL’s base glossary")
        self.base_check.setChecked(True)
        self.base_check.setToolTip("Disable when the shared stock terms do not fit this game.")
        self.base_check.toggled.connect(self._invalidate)
        form.addRow("Glossary", self.base_check)
        self.instructions_edit = QPlainTextEdit()
        self.instructions_edit.setPlaceholderText("Game-specific requests, provider/model for API mode, or known issues to fix…")
        self.instructions_edit.setMaximumHeight(100)
        self.instructions_edit.textChanged.connect(self._invalidate)
        form.addRow("Instructions", self.instructions_edit)
        project_card.add_layout(form)
        root.addWidget(project_card)

        handoff_card = SectionCard(
            "2. Start with one prompt",
            "Copy the prompt and paste it into your coding assistant with the game folder open. "
            "Your assistant will preserve the original, set up local Git and translation guidance, then carry out the selected task.",
        )
        actions = QHBoxLayout()
        self.copy_button = make_action_button("Copy starting prompt", variant="primary")
        self.copy_button.clicked.connect(self._copy)
        self.open_game_button = make_action_button("Open game folder")
        self.open_game_button.clicked.connect(lambda: self._open("game"))
        for button in (self.copy_button, self.open_game_button):
            button.setEnabled(False)
            actions.addWidget(button)
        actions.addStretch()
        handoff_card.add_layout(actions)
        self.status = QLabel()
        self.status.setWordWrap(True)
        handoff_card.add_widget(self.status)

        preview_content = QWidget()
        preview_layout = QVBoxLayout(preview_content)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMinimumHeight(180)
        self.preview.setPlaceholderText("Your copied prompt will appear here.")
        preview_layout.addWidget(self.preview)
        project_actions = QHBoxLayout()
        self.open_skill_button = make_action_button("Open Len’s skill")
        self.open_skill_button.clicked.connect(lambda: self._open("skill"))
        self.open_workspace_button = make_action_button("Open workspace")
        self.open_workspace_button.clicked.connect(lambda: self._open("workspace"))
        for button in (self.open_skill_button, self.open_workspace_button):
            button.setEnabled(False)
            project_actions.addWidget(button)
        project_actions.addStretch()
        preview_layout.addLayout(project_actions)
        handoff_card.add_widget(DisclosureSection("View copied prompt and project files", preview_content))
        root.addWidget(handoff_card)

        context_card = SectionCard(
            "Project guidance",
            "The starting prompt includes setup. Use these tools whenever you want to review or edit "
            "the shared glossary and skills, or add translations from an earlier game as references.",
        )
        context_actions = QHBoxLayout()
        self.review_button = make_action_button("Review glossary && skills")
        self.review_button.clicked.connect(self._review_context)
        self.references_button = make_action_button("Reference translations")
        self.references_button.clicked.connect(self._review_references)
        self.git_button = make_action_button("Git version tracking")
        self.git_button.clicked.connect(self._review_git)
        self.git_button.setVisible(self._open_version_tracking is not None)
        for button in (self.review_button, self.references_button, self.git_button):
            button.setEnabled(False)
            context_actions.addWidget(button)
        context_actions.addStretch()
        context_card.add_layout(context_actions)
        self.guidance_section = DisclosureSection("Optional: project tools and references", context_card)
        root.addWidget(self.guidance_section)

        evidence_card = SectionCard(
            "3. Review progress and playtest results",
            "The assistant records completed work, remaining issues and QA evidence in status.md. "
            "Review string coverage, image coverage and in-game checks separately before calling the game complete.",
        )
        self.progress_text = QPlainTextEdit()
        self.progress_text.setReadOnly(True)
        self.progress_text.setMaximumHeight(150)
        self.progress_text.setPlaceholderText("Your assistant’s progress report will appear here once work begins.")
        evidence_card.add_widget(self.progress_text)
        refresh = make_action_button("Reload progress report", variant="quiet")
        refresh.clicked.connect(self._refresh_progress)
        evidence_card.add_widget(refresh)
        root.addWidget(evidence_card)

    def _invalidate(self, *_):
        self._prepared = None
        if not hasattr(self, "copy_button"):
            return
        self.copy_button.setEnabled(bool(self._loaded_game))
        for button in (self.open_game_button, self.open_skill_button, self.open_workspace_button):
            button.setEnabled(False)
        self.preview.clear()
        self.progress_text.clear()
        message = "Copy the starting prompt for the selected task." if self._loaded_game else "Choose a game folder to get started."
        set_status_text(self.status, message, "info")

    def _game_changed(self, *_):
        self._loaded_game = ""
        self._invalidate()
        if not hasattr(self, "review_button"):
            return
        for button in (self.review_button, self.references_button, self.git_button):
            button.setEnabled(False)
        if self._context_dialog is not None:
            self._context_dialog.editors.invalidate()
            self._context_dialog.close()
        if self._references_dialog is not None:
            self._references_dialog.references.clear()
            self._references_dialog.close()

    def _project(self) -> LenProject:
        raw = self.game_edit.text().strip()
        if not raw:
            raise ValueError("Choose a game folder first.")
        return LenProject(
            Path(raw).expanduser().resolve(),
            stage=self.stage_combo.currentData(), mode=self.mode_combo.currentData(),
            include_images=self.images_check.isChecked(), instructions=self.instructions_edit.toPlainText(),
            include_glossary_base=self.base_check.isChecked(),
        )

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose game folder", self.game_edit.text())
        if folder:
            self.game_edit.setText(folder)
            self._load_game()

    def _load_game(self):
        if not self.game_edit.text().strip():
            return
        try:
            project = load_project(Path(self.game_edit.text().strip()))
            if self._loaded_game == str(project.game_root):
                return
            self.stage_combo.setCurrentIndex(self.stage_combo.findData(project.stage))
            self.mode_combo.setCurrentIndex(self.mode_combo.findData(project.mode))
            self.images_check.setChecked(project.include_images)
            self.base_check.setChecked(project.include_glossary_base)
            self.instructions_edit.setPlainText(project.instructions)
            self._loaded_game = str(project.game_root)
            for button in (self.copy_button, self.review_button, self.references_button, self.git_button):
                button.setEnabled(True)
            self._refresh_progress()
            set_status_text(self.status, "Ready. Copy the starting prompt and paste it into your coding assistant.", "info")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            set_status_text(self.status, f"Could not load this project: {exc}", "error")

    def _copy(self):
        """Prepare or refresh the selected project and copy its complete starting prompt."""
        self._invalidate()
        try:
            project = self._project()
            self.copy_button.setEnabled(False)
            path = prepare_project(project, self.skill_root)
            prompt = path.read_text(encoding="utf-8")
            QApplication.clipboard().setText(prompt)
            self._loaded_game = str(project.game_root)
            self.settings.setValue("len_method/game_root", str(project.game_root))
            self._prepared = project
            self.preview.setPlainText(prompt)
            for button in (self.review_button, self.references_button, self.git_button):
                button.setEnabled(True)
            for button in (self.open_game_button, self.open_skill_button, self.open_workspace_button):
                button.setEnabled(True)
            self._refresh_progress()
            set_status_text(self.status, "Starting prompt copied. Paste it into your coding assistant to begin or continue the selected task.", "success")
        except Exception as exc:
            set_status_text(self.status, f"Could not prepare the starting prompt: {exc}", "error")
        finally:
            self.copy_button.setEnabled(bool(self._loaded_game))

    def _review_context(self):
        from gui.translation_context_dialog import TranslationContextDialog

        if self._context_dialog is None:
            self._context_dialog = TranslationContextDialog(
                self, game_root_fn=lambda: self._loaded_game,
            )
            self._context_dialog.context_changed.connect(self._invalidate)
        if self._context_dialog.reload_context():
            self._context_dialog.show()
            self._context_dialog.raise_()

    def _review_references(self):
        from gui.reference_games_dialog import ReferenceGamesDialog

        if self._references_dialog is None:
            self._references_dialog = ReferenceGamesDialog(self, game_root_fn=lambda: self._loaded_game)
            self._references_dialog.references_changed.connect(self._invalidate)
        self._references_dialog.reload()
        self._references_dialog.show()
        self._references_dialog.raise_()

    def _review_git(self):
        if self._loaded_game and self._open_version_tracking is not None:
            self._open_version_tracking(self._loaded_game)

    def _open(self, target):
        if self._prepared is None:
            return
        paths = {"game": self._prepared.game_root, "workspace": self._prepared.workspace,
                 "skill": self.skill_root / "SKILL.md"}
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths[target]))):
            set_status_text(self.status, f"Could not open {paths[target]}", "error")

    def _refresh_progress(self):
        self.progress_text.clear()
        if not self.game_edit.text().strip():
            return
        try:
            report = self._project().workspace / "status.md"
            if report.is_file():
                self.progress_text.setPlainText(report.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            set_status_text(self.status, f"Could not read progress: {exc}", "error")
