"""Len's end-to-end, skill-driven translation handoff."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import QSettings, QThread, QTimer, Qt, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QPlainTextEdit, QProgressBar, QScrollArea, QVBoxLayout, QWidget,
)

from gui.ui_components import PageHeader, SectionCard, make_action_button, make_page_layout, set_status_text
from gui.workflow_components import DisclosureSection
from util.len_translation import BUNDLED_SKILL, MODES, STAGES, LenProject, load_project, prepare_project
from util.len_progress import PHASES, STATES, empty_progress, estimate_display, metric_display, read_progress
from util.paths import APP_NAME, ORG_NAME
from util.len_api import create_estimate, estimate_summary


class LenEstimateWorker(QThread):
    ready = pyqtSignal(object, object)
    failed = pyqtSignal(str)

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.project = project

    def run(self):
        try:
            self.ready.emit(self.project, create_estimate(self.project))
        except Exception as exc:
            self.failed.emit(str(exc))


class LenTranslationTab(QWidget):
    def __init__(self, parent=None, *, settings=None, skill_root: Path = BUNDLED_SKILL, open_version_tracking=None, open_api_settings=None, open_batch_history=None):
        super().__init__(parent)
        self.settings = settings if settings is not None else QSettings(ORG_NAME, APP_NAME)
        self.skill_root = skill_root
        self._open_version_tracking = open_version_tracking
        self._open_api_settings = open_api_settings
        self._open_batch_history = open_batch_history
        self._api_estimate = None
        self._estimate_worker = None
        self._loaded_game = ""
        self._context_dialog = None
        self._references_dialog = None
        self._prepared: LenProject | None = None
        self._build_ui()
        self.game_edit.setText(self.settings.value("len_method/game_root", "", type=str))
        self._load_game()
        self.progress_timer = QTimer(self)
        self.progress_timer.setInterval(3000)
        self.progress_timer.timeout.connect(self._refresh_visible_progress)
        self.progress_timer.start()

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
        self.instructions_edit.setPlaceholderText("Game-specific requests, reference-game paths, or known issues to fix…")
        self.instructions_edit.setMaximumHeight(100)
        self.instructions_edit.textChanged.connect(self._invalidate)
        form.addRow("Instructions", self.instructions_edit)
        project_card.add_layout(form)
        root.addWidget(project_card)
        self.mode_explanation = QLabel()
        self.mode_explanation.setWordWrap(True)
        root.addWidget(self.mode_explanation)
        self.api_card = SectionCard("API setup and estimate", "Uses the same saved provider and model as the API GUI.")
        api_actions = QHBoxLayout()
        self.api_settings_button = make_action_button("API settings")
        self.api_settings_button.setEnabled(self._open_api_settings is not None)
        self.api_settings_button.clicked.connect(lambda: self._open_api_settings() if self._open_api_settings else None)
        self.api_estimate_button = make_action_button("Estimate prepared requests")
        self.api_estimate_button.clicked.connect(self._estimate_api)
        self.api_history_button = make_action_button("Batch history")
        self.api_history_button.setEnabled(self._open_batch_history is not None)
        self.api_history_button.clicked.connect(lambda: self._open_batch_history() if self._open_batch_history else None)
        for button in (self.api_settings_button, self.api_estimate_button, self.api_history_button):
            api_actions.addWidget(button)
        self.api_card.add_layout(api_actions)
        self.api_quote = QLabel()
        self.api_quote.setTextFormat(Qt.PlainText)
        self.api_quote.setWordWrap(True)
        self.api_card.add_widget(self.api_quote)
        self.api_accept = QCheckBox("I reviewed this estimate and want the API Batch Translation handoff")
        self.api_accept.toggled.connect(self._refresh_mode)
        self.api_card.add_widget(self.api_accept)
        root.addWidget(self.api_card)

        handoff_card = SectionCard(
            "2. Copy the selected handoff",
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
            "Counts come from saved translation records. Phase checkpoints are reported by your assistant. "
            "Translation, review and in-game QA are tracked separately.",
        )
        self.progress_phase = QLabel("Current phase: Not reported")
        self.progress_updated = QLabel("Waiting for the first progress update.")
        self.progress_warning = QLabel()
        self.progress_estimate = QLabel()
        for label in (self.progress_phase, self.progress_updated, self.progress_warning, self.progress_estimate):
            label.setTextFormat(Qt.PlainText)
            label.setWordWrap(True)
            evidence_card.add_widget(label)
        self.progress_warning.hide()
        metrics = QGridLayout()
        self.progress_bars = {}
        self.progress_counts = {}
        for row, (key, title) in enumerate((
            ("translated", "Text translated"), ("reviewed", "Text reviewed"), ("images", "Images translated"),
        )):
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setFormat("Not measured")
            bar.setEnabled(False)
            count = QLabel()
            count.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.progress_bars[key] = bar
            self.progress_counts[key] = count
            metrics.addWidget(QLabel(title), row, 0)
            metrics.addWidget(bar, row, 1)
            metrics.addWidget(count, row, 2)
        metrics.setColumnStretch(1, 1)
        evidence_card.add_layout(metrics)
        phases = QGridLayout()
        self.progress_phases = {}
        for index, (key, title) in enumerate(PHASES.items()):
            label = QLabel(f"{title}: Pending")
            label.setWordWrap(True)
            self.progress_phases[key] = label
            phases.addWidget(label, index // 3, index % 3)
        evidence_card.add_layout(phases)
        self.progress_blocker = QLabel()
        self.progress_next = QLabel()
        for label in (self.progress_blocker, self.progress_next):
            label.setTextFormat(Qt.PlainText)
            label.setWordWrap(True)
            evidence_card.add_widget(label)
        self.progress_text = QPlainTextEdit()
        self.progress_text.setReadOnly(True)
        self.progress_text.setMaximumHeight(220)
        self.progress_text.setPlaceholderText("Your assistant’s progress report will appear here once work begins.")
        self.progress_details = DisclosureSection("View detailed log", self.progress_text)
        evidence_card.add_widget(self.progress_details)
        refresh = make_action_button("Refresh progress", variant="quiet")
        refresh.clicked.connect(self._refresh_progress)
        evidence_card.add_widget(refresh)
        root.addWidget(evidence_card)

    def _invalidate(self, *_):
        self._prepared = None
        self._api_estimate = None
        if not hasattr(self, "copy_button"):
            return
        self.api_accept.setChecked(False)
        self._refresh_mode()
        for button in (self.open_game_button, self.open_skill_button, self.open_workspace_button):
            button.setEnabled(False)
        self.preview.clear()
        self._refresh_progress()
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
            api_estimate={**self._api_estimate, "approved": self.api_accept.isChecked()} if self._api_estimate else None,
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
            self._api_estimate = project.api_estimate
            self.api_accept.setChecked(False)
            for button in (self.copy_button, self.review_button, self.references_button, self.git_button):
                button.setEnabled(True)
            self._refresh_mode()
            self._refresh_progress()
            set_status_text(self.status, "Ready. Copy the starting prompt and paste it into your coding assistant.", "info")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            set_status_text(self.status, f"Could not load this project: {exc}", "error")

    def _copy(self):
        """Prepare or refresh the selected project and copy its complete starting prompt."""
        self._prepared = None
        self.preview.clear()
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
            self._refresh_mode()

    def _refresh_mode(self, *_):
        api = self.mode_combo.currentData() == "api"
        preparing = self.stage_combo.currentData() == "prepare"
        self.api_card.setVisible(api)
        self.mode_explanation.setText(
            "API Batch Translation: prepare the extraction and prompts first, review the cost estimate here, then copy the API handoff. Preparation sends no translation requests."
            if api else
            "Agent / Sub Direct Translation: your coding assistant authors the translation. DazedTL sends no translation API requests; your assistant's usage limits still apply. Delegation follows your task instructions."
        )
        busy = self._estimate_worker is not None and self._estimate_worker.isRunning()
        self.api_estimate_button.setEnabled(bool(self._loaded_game) and not busy)
        self.api_accept.setEnabled(self._api_estimate is not None and not busy)
        if self._api_estimate is None and not busy:
            self.api_quote.setText("Estimate unavailable until extraction and guidance produce the complete request plan. Choose ‘Prepare extraction and guidance’ for the preparation-only prompt, then return here. No paid calls are authorized by that prompt.")
        elif self._api_estimate is not None:
            self.api_quote.setText(estimate_summary(self._api_estimate))
        self.copy_button.setText("Copy preparation-only prompt" if preparing else "Copy API translation prompt" if api else "Copy direct translation prompt")
        self.copy_button.setEnabled(bool(self._loaded_game) and not busy and
                                    (not api or preparing or self._api_estimate is not None and self.api_accept.isChecked()))

    def _estimate_api(self):
        try:
            project = replace(self._project(), api_estimate=None)
            self._api_estimate = None
            self.api_accept.setChecked(False)
            self.api_quote.setText("Estimating the saved request plan. No translation requests are sent.")
            worker = LenEstimateWorker(project, self)
            self._estimate_worker = worker
            worker.ready.connect(self._estimate_ready)
            worker.failed.connect(self._estimate_failed)
            worker.finished.connect(self._estimate_finished)
            worker.start()
            self._refresh_mode()
        except (OSError, ValueError) as exc:
            self._estimate_failed(str(exc))

    def _estimate_ready(self, project, estimate):
        if not self._loaded_game or replace(self._project(), api_estimate=None) != project:
            return
        self._api_estimate = estimate
        self.api_accept.setChecked(False)
        self._refresh_mode()

    def _estimate_failed(self, message):
        self._api_estimate = None
        self.api_quote.setText("Could not estimate: " + message)
        set_status_text(self.status, "Could not estimate: " + message, "error")

    def _estimate_finished(self):
        worker = self._estimate_worker
        self._estimate_worker = None
        if worker is not None:
            worker.deleteLater()
        self._refresh_mode()

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

    def showEvent(self, event):
        super().showEvent(event)
        if hasattr(self, "progress_text"):
            self._refresh_progress()

    def _refresh_visible_progress(self):
        if self.isVisible():
            self._refresh_progress()

    def _render_progress(self, snapshot, *, include_images=True, error=""):
        updated = snapshot["updated_at"]
        current = PHASES.get(snapshot["phase"], "No active phase" if updated else "Not reported")
        self.progress_phase.setText(f"Current phase: {current}")
        self.progress_estimate.setText(estimate_display(snapshot) if updated else "Estimate: waiting for the first measured milestone.")
        self.progress_updated.setText(
            "Last updated: " + datetime.fromisoformat(updated).astimezone().strftime("%Y-%m-%d %H:%M %Z")
            if updated else "Waiting for the first progress update."
        )
        warning = error or " ".join(snapshot.get("warnings", []))
        set_status_text(self.progress_warning, warning, "warning")
        self.progress_warning.setVisible(bool(warning))
        for key, bar in self.progress_bars.items():
            metric = snapshot["metrics"]["images" if key == "images" else "text"]
            excluded = key == "images" and not include_images
            value, label, counts = metric_display(metric, "reviewed" if key == "reviewed" else "translated", excluded=excluded)
            bar.setValue(value)
            bar.setFormat(label)
            bar.setEnabled(not warning and not excluded and (metric.get("discovered", metric["total"]) or 0) > 0)
            self.progress_counts[key].setText(counts)
        for key, label in self.progress_phases.items():
            label.setText(f"{PHASES[key]}: {STATES[snapshot['phases'][key]]}")
            label.setEnabled(not warning)
        self.progress_blocker.setText("Blocker: " + (snapshot["blocker"] or "None reported"))
        self.progress_blocker.setVisible(bool(updated))
        self.progress_next.setText("Next: " + snapshot["next_action"])
        self.progress_next.setVisible(bool(snapshot["next_action"]))

    def _refresh_progress(self):
        project = None
        log = ""
        try:
            if self._loaded_game:
                project = self._project()
                report = project.workspace / "status.md"
                if report.is_file():
                    log = report.read_text(encoding="utf-8")
                # Poll metadata only; hashing large source/image artifacts belongs
                # to the reporting helper, not the GUI thread.
                self._render_progress(read_progress(project, check_hashes=False), include_images=project.include_images)
            else:
                self._render_progress(empty_progress(LenProject(Path.cwd())))
        except (OSError, ValueError, TypeError) as exc:
            self._render_progress(empty_progress(project or LenProject(Path.cwd())),
                                  include_images=project.include_images if project else True,
                                  error=f"Could not read progress: {exc}")
        if self.progress_text.toPlainText() != log:
            self.progress_text.setPlainText(log)
