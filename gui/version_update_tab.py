"""GUI for the engine-independent, Git-backed version update workflow."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gui.theme import COLORS, Spacing
from util.version_update import (
    GitWorkflowError,
    RepositoryStatus,
    UpdateExternalChange,
    UpdateFileChange,
    UpdateImageChange,
    abort_update,
    apply_official_update,
    apply_registered_original,
    bootstrap_repository,
    checkout_translation_branch,
    conflict_paths,
    continue_with_official,
    inspect_repository,
    preview_official_update,
    register_translation_branch,
)


_VERSION_HINT = re.compile(r"(?i)(?:^|[\s_\-[(])v(?:er(?:sion)?\.?)?[\s._-]*(\d+(?:\.\d+)+)")


class _WorkflowThread(QThread):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, operation: Callable[[], object], parent=None):
        super().__init__(parent)
        self.operation = operation

    def run(self):
        try:
            self.succeeded.emit(self.operation())
        except Exception as exc:  # surfaced to the GUI with the exact Git message
            self.failed.emit(str(exc))


class VersionUpdateTab(QWidget):
    """Bootstrap and operate the original/translation Git branch workflow."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("versionUpdatePage")
        self._status: RepositoryStatus | None = None
        self._preview = None
        self._worker: _WorkflowThread | None = None
        self._bootstrap_expanded = False
        self._scan_timer = QTimer(self)
        self._scan_timer.setSingleShot(True)
        self._scan_timer.setInterval(300)
        self._scan_timer.timeout.connect(self.refresh_status)
        self._build_ui()
        self.sync_from_workflow()

    def _build_ui(self):
        from gui.ui_components import PageHeader, SectionCard, configure_action_button

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setObjectName("versionUpdateScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        content = QWidget()
        content.setObjectName("versionUpdateContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(Spacing.XL, Spacing.LG, Spacing.XL, Spacing.XL)
        layout.setSpacing(Spacing.LG)
        scroll.setWidget(content)
        root.addWidget(scroll)
        self.page_scroll = scroll

        layout.addWidget(
            PageHeader(
                "Version Update",
                "Keep official releases on original and apply their exact Git commits to the translated branch.",
            )
        )

        repository_card = SectionCard(
            "1. Translated game",
            "Choose the game you are translating. The workflow selection is used automatically when available.",
            compact=True,
        )
        repository_form = QFormLayout()
        repository_form.setContentsMargins(0, 0, 0, 0)
        self.current_edit = self._folder_row(
            repository_form,
            "Translated game:",
            "Folder containing the translated working game",
        )
        self.current_edit.textChanged.connect(self._translated_game_changed)
        repository_card.add_layout(repository_form)
        refresh_row = QHBoxLayout()
        self.use_workflow_btn = QPushButton("Use workflow game")
        configure_action_button(self.use_workflow_btn, variant="quiet")
        self.use_workflow_btn.clicked.connect(
            lambda: self.sync_from_workflow(force=True)
        )
        self.use_workflow_btn.setVisible(False)
        refresh_row.addWidget(self.use_workflow_btn)
        refresh_row.addStretch()
        self.refresh_btn = QPushButton("Rescan")
        configure_action_button(self.refresh_btn, variant="quiet")
        self.refresh_btn.clicked.connect(self.refresh_status)
        refresh_row.addWidget(self.refresh_btn)
        self.switch_translation_btn = QPushButton("Switch translated branch")
        configure_action_button(self.switch_translation_btn, variant="secondary")
        self.switch_translation_btn.clicked.connect(self._switch_translation)
        self.switch_translation_btn.setVisible(False)
        refresh_row.addWidget(self.switch_translation_btn)
        self.finish_assets_btn = QPushButton("Finish asset sync")
        configure_action_button(self.finish_assets_btn, variant="primary")
        self.finish_assets_btn.clicked.connect(self._apply_registered)
        self.finish_assets_btn.setVisible(False)
        refresh_row.addWidget(self.finish_assets_btn)
        repository_card.add_layout(refresh_row)

        self.repository_status = QLabel("Select a translated game folder.")
        self.repository_status.setWordWrap(True)
        self.repository_status.setStyleSheet(f"color:{COLORS.accent_text};")
        repository_card.add_widget(self.repository_status)
        self.version_status = QLabel("")
        self.version_status.setWordWrap(True)
        self.version_status.setStyleSheet(f"color:{COLORS.text_muted};")
        repository_card.add_widget(self.version_status)
        layout.addWidget(repository_card)
        self.repository_card = repository_card

        bootstrap_card = SectionCard(
            "2. Set up version tracking",
            "This one-time setup creates the original baseline and registers the branch containing your translation.",
        )
        self.bootstrap_explanation = QLabel(
            "Version tracking has not been configured for this game."
        )
        self.bootstrap_explanation.setWordWrap(True)
        self.bootstrap_explanation.setStyleSheet(f"color:{COLORS.text_muted};")
        bootstrap_card.add_widget(self.bootstrap_explanation)
        setup_row = QHBoxLayout()
        setup_row.addStretch()
        self.show_bootstrap_btn = QPushButton("Set up version tracking")
        configure_action_button(self.show_bootstrap_btn, variant="primary")
        self.show_bootstrap_btn.clicked.connect(self._show_bootstrap_fields)
        setup_row.addWidget(self.show_bootstrap_btn)
        bootstrap_card.add_layout(setup_row)

        self.bootstrap_fields = QWidget()
        self.bootstrap_fields.setObjectName("transparentCardPanel")
        bootstrap_fields_layout = QVBoxLayout(self.bootstrap_fields)
        bootstrap_fields_layout.setContentsMargins(0, 0, 0, 0)
        bootstrap_fields_layout.setSpacing(Spacing.MD)
        bootstrap_form = QFormLayout()
        bootstrap_form.setContentsMargins(0, 0, 0, 0)
        self.original_edit = self._folder_row(
            bootstrap_form,
            "Matching original game:",
            "Clean official game for the translation's current version",
        )
        self.original_edit.textChanged.connect(self._guess_bootstrap_version)
        self.original_version_edit = QLineEdit()
        self.original_version_edit.setPlaceholderText("For example: 1.00")
        bootstrap_form.addRow("Current version:", self.original_version_edit)
        bootstrap_fields_layout.addLayout(bootstrap_form)
        bootstrap_actions = QHBoxLayout()
        bootstrap_actions.addStretch()
        self.bootstrap_btn = QPushButton("Create version tracking")
        configure_action_button(self.bootstrap_btn, variant="primary")
        self.bootstrap_btn.clicked.connect(self._bootstrap)
        bootstrap_actions.addWidget(self.bootstrap_btn)
        bootstrap_fields_layout.addLayout(bootstrap_actions)
        self.bootstrap_fields.setVisible(False)
        bootstrap_card.add_widget(self.bootstrap_fields)
        layout.addWidget(bootstrap_card)
        self.bootstrap_card = bootstrap_card

        update_card = SectionCard(
            "3. Apply an official update",
            "Choose the clean folder for the new official release, preview its impact, then apply it to the translated game.",
        )
        self.baseline_panel = QWidget()
        self.baseline_panel.setObjectName("transparentCardPanel")
        baseline_layout = QVBoxLayout(self.baseline_panel)
        baseline_layout.setContentsMargins(0, 0, 0, 0)
        baseline_layout.setSpacing(Spacing.SM)
        self.baseline_explanation = QLabel(
            "Optional: choose the previous clean official game for the most exact "
            "asset comparison. Otherwise, the current game's images and sounds are "
            "used as the starting baseline."
        )
        self.baseline_explanation.setWordWrap(True)
        self.baseline_explanation.setStyleSheet(f"color:{COLORS.text_muted};")
        baseline_layout.addWidget(self.baseline_explanation)
        baseline_form = QFormLayout()
        baseline_form.setContentsMargins(0, 0, 0, 0)
        self.baseline_edit = self._folder_row(
            baseline_form,
            "Previous official game (optional):",
            "Leave blank to use the current game's existing assets",
        )
        self.baseline_edit.textChanged.connect(lambda _text: self._invalidate_preview())
        baseline_layout.addLayout(baseline_form)
        self.baseline_panel.setVisible(False)
        update_card.add_widget(self.baseline_panel)
        update_form = QFormLayout()
        update_form.setContentsMargins(0, 0, 0, 0)
        self.new_edit = self._folder_row(
            update_form,
            "New official game:",
            "Clean folder containing the new official release",
        )
        self.new_edit.textChanged.connect(self._guess_new_version)
        self.new_edit.textChanged.connect(lambda _text: self._invalidate_preview())
        self.new_version_edit = QLineEdit()
        self.new_version_edit.setPlaceholderText("For example: 1.03")
        self.new_version_edit.textChanged.connect(lambda _text: self._invalidate_preview())
        update_form.addRow("New version:", self.new_version_edit)
        update_card.add_layout(update_form)
        self.preview_empty = QLabel(
            "Preview file-level update impact before applying it."
        )
        self.preview_empty.setWordWrap(True)
        self.preview_empty.setAlignment(Qt.AlignCenter)
        self.preview_empty.setMinimumHeight(72)
        self.preview_empty.setStyleSheet(
            f"QLabel{{background:{COLORS.canvas};color:{COLORS.text_muted};"
            f"border:1px dashed {COLORS.border_strong};border-radius:4px;padding:16px;}}"
        )
        update_card.add_widget(self.preview_empty)

        self.preview_panel = QWidget()
        self.preview_panel.setObjectName("transparentCardPanel")
        preview_layout = QVBoxLayout(self.preview_panel)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(Spacing.MD)

        self.preview_summary = QLabel()
        self.preview_summary.setWordWrap(True)
        self.preview_summary.setObjectName("updatePreviewSummary")
        preview_layout.addWidget(self.preview_summary)

        self.preview_expected = QLabel()
        self.preview_expected.setWordWrap(True)
        self.preview_expected.setStyleSheet(f"color:{COLORS.text_muted};")
        preview_layout.addWidget(self.preview_expected)

        self.preview_notice = QLabel()
        self.preview_notice.setWordWrap(True)
        preview_layout.addWidget(self.preview_notice)

        self.preview_changes = QTreeWidget()
        self.preview_changes.setHeaderLabels(["File", "Update", "Lines / type", "Result"])
        self.preview_changes.setRootIsDecorated(True)
        self.preview_changes.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.preview_changes.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.preview_changes.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.preview_changes.header().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.preview_changes.setMinimumHeight(240)
        self.preview_changes.setMaximumHeight(420)
        preview_layout.addWidget(self.preview_changes)
        self.preview_panel.setVisible(False)
        update_card.add_widget(self.preview_panel)
        update_actions = QHBoxLayout()
        self.apply_registered_btn = QPushButton("Apply registered original update")
        configure_action_button(self.apply_registered_btn, variant="secondary")
        self.apply_registered_btn.clicked.connect(self._apply_registered)
        self.apply_registered_btn.setVisible(False)
        update_actions.addWidget(self.apply_registered_btn)
        update_actions.addStretch()
        self.preview_btn = QPushButton("Preview update")
        configure_action_button(self.preview_btn, variant="secondary")
        self.preview_btn.clicked.connect(self._preview_update)
        update_actions.addWidget(self.preview_btn)
        self.update_btn = QPushButton("Apply update")
        configure_action_button(self.update_btn, variant="primary")
        self.update_btn.clicked.connect(self._apply_update)
        self.update_btn.setEnabled(False)
        update_actions.addWidget(self.update_btn)
        update_card.add_layout(update_actions)
        layout.addWidget(update_card)
        self.update_card = update_card

        recovery_card = SectionCard(
            "Interrupted update",
            "A cherry-pick is waiting. Continue by making the official version authoritative for every unresolved path, or abort and restore translation.",
        )
        self.conflict_summary = QTextEdit()
        self.conflict_summary.setReadOnly(True)
        self.conflict_summary.setMaximumHeight(150)
        recovery_card.add_widget(self.conflict_summary)
        recovery_actions = QHBoxLayout()
        self.abort_btn = QPushButton("Abort cherry-pick")
        configure_action_button(self.abort_btn, variant="danger")
        self.abort_btn.clicked.connect(self._abort)
        recovery_actions.addWidget(self.abort_btn)
        recovery_actions.addStretch()
        self.continue_btn = QPushButton("Use official conflicts and continue")
        configure_action_button(self.continue_btn, variant="primary")
        self.continue_btn.clicked.connect(self._continue)
        recovery_actions.addWidget(self.continue_btn)
        recovery_card.add_layout(recovery_actions)
        recovery_card.setVisible(False)
        layout.addWidget(recovery_card)
        self.recovery_card = recovery_card

        activity_card = SectionCard(
            "Last action",
            "Shows the completed update and any conflicts resolved with official content.",
        )
        self.activity = QTextEdit()
        self.activity.setReadOnly(True)
        self.activity.setPlaceholderText("No version update has run in this session.")
        self.activity.setMinimumHeight(150)
        activity_card.add_widget(self.activity)
        activity_card.setVisible(False)
        layout.addWidget(activity_card)
        self.activity_card = activity_card

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)
        layout.addStretch()
        self._render_status(None)

    def _workflow_game_path(self) -> str:
        parent = self.parentWidget()
        if parent is None:
            return ""
        workflow_tabs = []
        active_index = 0
        engine_combo = getattr(parent, "workflow_engine_combo", None)
        if engine_combo is not None:
            active_index = engine_combo.currentIndex()
        rpg_tab = getattr(parent, "workflow_tab", None)
        wolf_tab = getattr(parent, "wolf_workflow_tab", None)
        if active_index == 1:
            workflow_tabs.extend((wolf_tab, rpg_tab))
        else:
            workflow_tabs.extend((rpg_tab, wolf_tab))
        for tab in workflow_tabs:
            edit = getattr(tab, "folder_edit", None)
            if edit is not None and edit.text().strip():
                return edit.text().strip()

        settings = getattr(parent, "settings", None)
        if settings is not None:
            for key in (
                "workflow/last_game_folder",
                "wolf_workflow/last_game_folder",
            ):
                saved = str(settings.value(key, "") or "").strip()
                if saved:
                    return saved
        return ""

    def sync_from_workflow(self, *, force: bool = False) -> None:
        candidate = self._workflow_game_path()
        current = self.current_edit.text().strip()
        if candidate and (force or not current):
            self.current_edit.setText(candidate)
            self.refresh_status()
            current = candidate
        self.use_workflow_btn.setVisible(bool(candidate and candidate != current))

    def _translated_game_changed(self, text: str) -> None:
        self._invalidate_preview()
        self._bootstrap_expanded = False
        if hasattr(self, "bootstrap_fields"):
            self.bootstrap_fields.setVisible(False)
            self.show_bootstrap_btn.setVisible(True)
        if hasattr(self, "activity"):
            self.activity.clear()
            self.activity_card.setVisible(False)
        if hasattr(self, "baseline_edit"):
            self.baseline_edit.clear()
        candidate = self._workflow_game_path()
        if hasattr(self, "use_workflow_btn"):
            self.use_workflow_btn.setVisible(
                bool(candidate and candidate != text.strip())
            )
        self._scan_timer.start()

    def _show_bootstrap_fields(self) -> None:
        self._bootstrap_expanded = True
        self.show_bootstrap_btn.setVisible(False)
        self.bootstrap_fields.setVisible(True)
        if self.original_edit.isEnabled():
            self.original_edit.setFocus()
        else:
            self.original_version_edit.setFocus()

    def _folder_row(self, form: QFormLayout, label: str, placeholder: str) -> QLineEdit:
        from gui.ui_components import configure_action_button

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(Spacing.SM)
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        browse = QPushButton("Browse…")
        configure_action_button(browse, variant="quiet")
        browse.setMinimumWidth(112)
        browse.clicked.connect(lambda: self._choose_folder(edit))
        row.addWidget(edit, 1)
        row.addWidget(browse)
        form.addRow(label, row)
        return edit

    def _choose_folder(self, edit: QLineEdit):
        start = edit.text().strip() or str(Path.home())
        selected = QFileDialog.getExistingDirectory(self, "Select game folder", start)
        if selected:
            edit.setText(selected)

    @staticmethod
    def _version_from_path(text: str) -> str | None:
        match = _VERSION_HINT.search(Path(text).name) if text.strip() else None
        return match.group(1) if match else None

    def _guess_bootstrap_version(self, text: str):
        if not self.original_version_edit.text().strip():
            guessed = self._version_from_path(text)
            if guessed:
                self.original_version_edit.setText(guessed)

    def _guess_new_version(self, text: str):
        if not self.new_version_edit.text().strip():
            guessed = self._version_from_path(text)
            if guessed:
                self.new_version_edit.setText(guessed)

    def refresh_status(self):
        selected = self.current_edit.text().strip()
        if not selected:
            self._status = None
            self._render_status(None)
            return
        try:
            self._status = inspect_repository(selected)
            self._render_status(self._status)
        except GitWorkflowError as exc:
            self._status = None
            self.repository_status.setText(f"Repository inspection failed: {exc}")
            self.repository_status.setStyleSheet(f"color:{COLORS.danger};")
            self.version_status.setText("")
            self.bootstrap_card.setVisible(False)
            self.update_card.setVisible(False)
            self.recovery_card.setVisible(False)
            self.switch_translation_btn.setVisible(False)
            self.finish_assets_btn.setVisible(False)

    def _render_status(self, status: RepositoryStatus | None):
        if status is None:
            self.repository_status.setText("Choose a translated game folder to begin.")
            self.repository_status.setStyleSheet(f"color:{COLORS.accent_text};")
            self.version_status.setText("")
            self.refresh_btn.setVisible(False)
            self.bootstrap_card.setVisible(False)
            self.update_card.setVisible(False)
            self.recovery_card.setVisible(False)
            self.switch_translation_btn.setVisible(False)
            self.finish_assets_btn.setVisible(False)
            return

        self.refresh_btn.setVisible(True)
        if not status.selected_root.is_dir():
            self.repository_status.setText(
                "That translated game folder could not be found. Choose an existing folder."
            )
            self.repository_status.setStyleSheet(f"color:{COLORS.danger};")
            self.version_status.setText(str(status.selected_root))
            self.bootstrap_card.setVisible(False)
            self.update_card.setVisible(False)
            self.recovery_card.setVisible(False)
            self.switch_translation_btn.setVisible(False)
            self.finish_assets_btn.setVisible(False)
            return

        needs_bootstrap = not status.original_exists or not status.translation_exists
        branch_ready = status.ready
        behind = bool(
            status.original_version
            and status.translation_version
            and status.original_version != status.translation_version
        )
        if status.repo_root is None:
            self.repository_status.setText("Version tracking is not set up yet.")
            self.repository_status.setStyleSheet(f"color:{COLORS.warning};")
            self.version_status.setText(
                "No Git repository or registered version-tracking branches were detected."
            )
        elif status.pending_cherry_pick:
            self.repository_status.setText(
                "An interrupted official update needs to be finished or aborted."
            )
            self.repository_status.setStyleSheet(f"color:{COLORS.warning};")
        elif not status.worktree_clean:
            self.repository_status.setText(
                "Commit or discard the translated game's uncommitted changes before continuing."
            )
            self.repository_status.setStyleSheet(f"color:{COLORS.warning};")
        elif status.asset_sync_pending:
            if behind:
                self.repository_status.setText(
                    "An official update is registered and ready to be applied to the translated game."
                )
            else:
                self.repository_status.setText(
                    "The Git update is complete, but official game assets still need to be synchronized."
                )
            self.repository_status.setStyleSheet(f"color:{COLORS.warning};")
        elif needs_bootstrap:
            self.repository_status.setText("Version tracking setup is required.")
            self.repository_status.setStyleSheet(f"color:{COLORS.warning};")
        elif status.current_branch != status.translation_branch:
            self.repository_status.setText(
                f"Switch to {status.translation_branch} before applying an official update."
            )
            self.repository_status.setStyleSheet(f"color:{COLORS.warning};")
        elif not status.asset_manifest_available:
            self.repository_status.setText(
                "Ready for official game updates. The first preview will remember the "
                "current images and sounds unless a clean previous folder is selected."
            )
            self.repository_status.setStyleSheet(f"color:{COLORS.success};")
        else:
            self.repository_status.setText("Ready for official game updates.")
            self.repository_status.setStyleSheet(f"color:{COLORS.success};")

        if status.repo_root is not None:
            original = status.original_version or (
                "unknown" if status.original_exists else "missing"
            )
            translated = status.translation_version or (
                "unknown" if status.translation_exists else "missing"
            )
            self.version_status.setText(
                f"Original {original} · Translated {status.translation_branch or 'not registered'} {translated} · "
                f"Branch {status.current_branch or 'detached HEAD'}"
            )

        can_bootstrap = needs_bootstrap and status.worktree_clean and not status.pending_cherry_pick
        self.bootstrap_card.setVisible(can_bootstrap)
        self.show_bootstrap_btn.setVisible(can_bootstrap and not self._bootstrap_expanded)
        self.bootstrap_fields.setVisible(can_bootstrap and self._bootstrap_expanded)
        if status.original_exists and not status.translation_exists:
            self.bootstrap_explanation.setText(
                f"The original branch already exists. Register {status.current_branch or 'the current branch'} as the translated branch."
            )
            self.bootstrap_btn.setText("Register current branch")
            self.original_edit.setEnabled(False)
            if status.original_version and not self.original_version_edit.text().strip():
                self.original_version_edit.setText(status.original_version)
        else:
            self.bootstrap_explanation.setText(
                "Choose the clean original game matching this translation's current version. This is only needed once."
            )
            self.bootstrap_btn.setText("Create version tracking")
            self.original_edit.setEnabled(True)
        self.switch_translation_btn.setVisible(
            bool(
                status.translation_exists
                and status.current_branch != status.translation_branch
                and status.worktree_clean
                and not status.pending_cherry_pick
            )
        )
        self.finish_assets_btn.setVisible(
            bool(
                status.asset_sync_pending
                and status.current_branch == status.translation_branch
                and status.worktree_clean
                and not status.pending_cherry_pick
            )
        )
        self.finish_assets_btn.setText(
            "Apply registered update" if behind else "Finish asset sync"
        )
        if status.translation_branch:
            self.switch_translation_btn.setText(
                f"Switch to {status.translation_branch}"
            )
        self.update_card.setVisible(branch_ready)
        self.update_card.setEnabled(branch_ready)
        self.baseline_panel.setVisible(
            branch_ready
            and (
                not status.asset_manifest_available
                or getattr(status, "asset_baseline_repair_needed", False)
            )
        )
        self.baseline_explanation.setText(
            "Optional: select the clean official game for "
            f"version {status.original_version or 'the registered baseline'} for the "
            "most exact comparison. Leave this blank to use the current game's existing "
            "images, audio, video, and fonts as the starting asset baseline."
        )
        self.apply_registered_btn.setVisible(branch_ready and behind)
        self.recovery_card.setVisible(status.pending_cherry_pick)
        if status.pending_cherry_pick:
            paths = conflict_paths(status.selected_root)
            self.conflict_summary.setPlainText(
                "\n".join(paths) if paths else "Cherry-pick is pending without unresolved paths."
            )

    def _set_busy(self, busy: bool):
        self.progress.setVisible(busy)
        for button in (
            self.use_workflow_btn,
            self.refresh_btn,
            self.switch_translation_btn,
            self.finish_assets_btn,
            self.show_bootstrap_btn,
            self.bootstrap_btn,
            self.update_btn,
            self.preview_btn,
            self.apply_registered_btn,
            self.continue_btn,
            self.abort_btn,
        ):
            button.setEnabled(not busy)
        if not busy:
            self.update_btn.setEnabled(
                self._preview is not None
                and self._status is not None
                and self._status.ready
            )

    def _set_activity(self, text: str) -> None:
        self.activity.setPlainText(text)
        self.activity_card.setVisible(True)

    def _run(self, operation: Callable[[], object], success: Callable[[object], None]):
        if self._worker is not None and self._worker.isRunning():
            return
        self._set_busy(True)
        worker = _WorkflowThread(operation, self)
        self._worker = worker
        worker.succeeded.connect(success)
        worker.failed.connect(self._operation_failed)
        worker.finished.connect(lambda: self._set_busy(False))
        worker.finished.connect(self.refresh_status)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(lambda: setattr(self, "_worker", None))
        worker.start()

    def _bootstrap(self):
        current = self.current_edit.text().strip()
        original = self.original_edit.text().strip()
        version = self.original_version_edit.text().strip()
        if (
            self._status
            and self._status.repo_root
            and not self._status.translation_exists
        ):
            branch = self._status.current_branch
            if not branch or branch == "original":
                QMessageBox.warning(
                    self,
                    "Translated branch required",
                    "Check out the branch containing the translated game, then rescan.",
                )
                return
            answer = QMessageBox.question(
                self,
                "Use current branch?",
                f"Use {branch!r} as this game's translated branch?\n\n"
                "DazedTL will keep that branch name and apply future official updates to it.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if answer != QMessageBox.Yes:
                return
        if self._status and self._status.original_exists and not self._status.translation_exists:
            if not current or not version:
                QMessageBox.warning(
                    self,
                    "Missing translation version",
                    "Enter the version matching the current translated game.",
                )
                return
            self._run(
                lambda: register_translation_branch(current, version),
                self._show_bootstrap_result,
            )
            return
        if not current or not original or not version:
            QMessageBox.warning(
                self,
                "Missing baseline information",
                "Select both game folders and enter the matching original version.",
            )
            return
        self._run(
            lambda: bootstrap_repository(current, original, version),
            self._show_bootstrap_result,
        )

    def _show_bootstrap_result(self, result):
        lines = [
            "Branch baseline created successfully.",
            f"Original commit: {result.original_commit}",
            f"Translation commit: {result.translation_commit}",
            f"Version: {result.version}",
            f"Translated structured files normalized: {len(result.formatted_json_paths)}",
            f"Files ignored by Git: {len(result.ignored_paths)}",
            f"Formatting warnings: {len(result.json_warnings)}",
            f"GameUpdate .gitignore installed: {'yes' if result.gitignore_installed else 'already present'}",
        ]
        if result.formatted_json_paths:
            lines.extend(
                ["", "Translated structured files normalized:", *result.formatted_json_paths]
            )
        if result.ignored_paths:
            lines.extend(["", "Ignored by Git:", *result.ignored_paths])
        if result.json_warnings:
            lines.extend(["", "Formatting warnings:", *result.json_warnings])
        self._set_activity("\n".join(lines))

    def _switch_translation(self):
        current = self.current_edit.text().strip()
        self._run(
            lambda: checkout_translation_branch(current),
            lambda _result: self._set_activity(
                "Switched the selected repository to its registered translated branch."
            ),
        )

    def _apply_update(self):
        current = self.current_edit.text().strip()
        official = self.new_edit.text().strip()
        version = self.new_version_edit.text().strip()
        baseline = self.baseline_edit.text().strip()
        if not current or not official or not version:
            QMessageBox.warning(
                self,
                "Missing update information",
                "Select the new official game and enter its version.",
            )
            return
        resolved_baseline = (
            Path(baseline).expanduser().resolve() if baseline else None
        )
        if (
            self._preview is None
            or self._preview.source_root != Path(official).expanduser().resolve()
            or self._preview.version != version
            or self._preview.baseline_source_root != resolved_baseline
        ):
            QMessageBox.warning(
                self,
                "Preview required",
                "Preview the current official folder and version before applying the update.",
            )
            return
        self._run(
            lambda: apply_official_update(
                current,
                official,
                version,
                expected_tree=self._preview.proposed_tree,
                expected_original_commit=self._preview.original_commit,
                expected_translation_commit=self._preview.translation_commit,
                expected_asset_manifest=self._preview.proposed_asset_manifest,
                previous_official_game=baseline or None,
                expected_baseline_asset_manifest=(
                    self._preview.baseline_asset_manifest
                ),
            ),
            self._show_update_result,
        )

    def _preview_update(self):
        current = self.current_edit.text().strip()
        official = self.new_edit.text().strip()
        version = self.new_version_edit.text().strip()
        baseline = self.baseline_edit.text().strip()
        if not current or not official or not version:
            QMessageBox.warning(
                self,
                "Missing update information",
                "Select the new official game and enter its version.",
            )
            return
        self._run(
            lambda: preview_official_update(
                current,
                official,
                version,
                previous_official_game=baseline or None,
            ),
            self._show_preview,
        )

    def _show_preview(self, preview):
        self._preview = preview
        replacements = tuple(
            change
            for change in preview.file_changes
            if change.whole_file_replaced
            and not change.is_image
            and not change.already_present
        )
        image_warnings = tuple(
            change for change in preview.image_changes if change.warning
        )
        warning_count = (
            len(replacements) + len(image_warnings) + len(preview.json_warnings)
        )

        if warning_count:
            summary = (
                f"Version {preview.version} preview found {warning_count} warning(s)."
            )
            summary_color = COLORS.warning
        elif not preview.changed_paths and not preview.external_changes:
            summary = (
                f"Version {preview.version} preview is ready. The official folder has no "
                "file changes, so only the version will be recorded."
            )
            summary_color = COLORS.success
        elif not preview.content_change_expected:
            summary = (
                f"Version {preview.version} preview is ready. Its official changes are "
                "already present, so only the version will be recorded."
            )
            summary_color = COLORS.success
        else:
            summary = f"Version {preview.version} preview is ready."
            summary_color = COLORS.success
        self.preview_summary.setText(summary)
        self.preview_summary.setStyleSheet(
            f"QLabel#updatePreviewSummary{{background:{COLORS.surface_2};"
            f"color:{COLORS.text_primary};border-left:4px solid {summary_color};"
            "border-radius:3px;padding:10px 12px;}"
        )

        expected = (
            "Git-tracked patch: "
            f"{sum(change.change == 'Added' for change in preview.file_changes)} added · "
            f"{sum(change.change == 'Modified' for change in preview.file_changes)} modified · "
            f"{sum(change.change == 'Removed' for change in preview.file_changes)} removed. "
            "Assets outside Git (images, audio, video, fonts, and other packaged files): "
            f"{sum(change.change == 'Added' for change in preview.external_changes)} added · "
            f"{sum(change.change == 'Replaced' for change in preview.external_changes)} replaced · "
            f"{sum(change.change == 'Removed' for change in preview.external_changes)} removed."
        )
        non_image_assets = tuple(
            change
            for change in preview.external_changes
            if change.category != "Image"
        )
        if preview.already_present_paths:
            expected += (
                f" · {len(preview.already_present_paths)} already present"
            )
        if preview.preserved_translation_asset_paths:
            expected += (
                f" {len(preview.preserved_translation_asset_paths)} tracked translation "
                "asset(s) have no official baseline copy and will be preserved."
            )
        if preview.baseline_source_root is not None:
            if preview.asset_manifest_available:
                expected += " A clean previous official baseline was supplied for precise comparison."
            else:
                expected += (
                    " The selected previous official folder supplied the one-time asset "
                    "baseline; it will be remembered after this update."
                )
        elif not preview.asset_manifest_available:
            expected += (
                " The current game's existing external assets supplied the one-time "
                "baseline; it will be remembered after this update."
            )
        self.preview_expected.setText(expected)

        if warning_count:
            notices = []
            if replacements:
                notices.append(
                    f"{len(replacements)} translated file(s) will be replaced in full"
                )
            if image_warnings:
                notices.append(
                    f"{len(image_warnings)} tracked translation image(s) will be replaced or removed"
                )
            if preview.json_warnings:
                notices.append(
                    f"{len(preview.json_warnings)} structured-file warning(s)"
                )
            self.preview_notice.setText("Attention: " + " · ".join(notices))
            notice_color = COLORS.warning
        elif preview.preserved_translation_asset_paths:
            self.preview_notice.setText(
                f"Protected: {len(preview.preserved_translation_asset_paths)} tracked "
                "translation asset(s) were excluded from this update because no clean "
                "official baseline is available."
            )
            notice_color = COLORS.success
        else:
            self.preview_notice.setText(
                "No full-file translation replacements or processing warnings."
            )
            notice_color = COLORS.success
        self.preview_notice.setStyleSheet(
            f"QLabel{{background:{COLORS.canvas};color:{notice_color};"
            f"border:1px solid {COLORS.border};border-radius:4px;padding:10px;}}"
        )

        already_present = tuple(
            change for change in preview.file_changes if change.already_present
        )
        added = tuple(
            change
            for change in preview.file_changes
            if change.change == "Added"
            and not change.is_image
            and not change.already_present
        )
        removed = tuple(
            change
            for change in preview.file_changes
            if change.change == "Removed"
            and not change.is_image
            and not change.already_present
        )
        images_added = tuple(
            change
            for change in preview.image_changes
            if change.change == "Added" and not change.warning
        )
        images_removed = tuple(
            change
            for change in preview.image_changes
            if change.change == "Removed" and not change.warning
        )
        images_replaced = tuple(
            change
            for change in preview.image_changes
            if change.change == "Replaced" and not change.warning
        )
        modified = tuple(
            change
            for change in preview.file_changes
            if change.change == "Modified"
            and not change.is_image
            and not change.already_present
        )

        self.preview_changes.clear()
        self._add_change_group("Warnings — entire file replaced", replacements)
        self._add_image_group("⚠ Warnings — tracked images", image_warnings)
        if preview.preserved_translation_asset_paths:
            preserved_group = QTreeWidgetItem(
                [
                    "Preserved tracked translation assets "
                    f"({len(preview.preserved_translation_asset_paths)})",
                    "",
                    "",
                    "",
                ]
            )
            preserved_group.setFlags(
                preserved_group.flags() & ~Qt.ItemIsSelectable
            )
            self.preview_changes.addTopLevelItem(preserved_group)
            for path in preview.preserved_translation_asset_paths:
                preserved_group.addChild(
                    QTreeWidgetItem(
                        [
                            path,
                            "Preserved",
                            "Tracked asset",
                            "No official baseline; excluded from update",
                        ]
                    )
                )
            preserved_group.setExpanded(True)
        if preview.json_warnings:
            warning_group = QTreeWidgetItem(
                [f"Warnings — structured files ({len(preview.json_warnings)})", "", "", ""]
            )
            self.preview_changes.addTopLevelItem(warning_group)
            for warning in preview.json_warnings:
                warning_group.addChild(
                    QTreeWidgetItem([warning, "Warning", "—", "Could not normalize safely"])
                )
            warning_group.setExpanded(True)
        self._add_change_group("Added files", added)
        self._add_change_group("Removed files", removed)
        self._add_image_group("Images added", images_added)
        self._add_image_group("Images removed", images_removed)
        self._add_image_group("Images replaced", images_replaced)
        self._add_external_group(
            "Other game assets added",
            tuple(change for change in non_image_assets if change.change == "Added"),
        )
        self._add_external_group(
            "Other game assets removed",
            tuple(change for change in non_image_assets if change.change == "Removed"),
        )
        self._add_external_group(
            "Other game assets replaced",
            tuple(change for change in non_image_assets if change.change == "Replaced"),
        )
        self._add_change_group("Modified files", modified)
        self._add_change_group("Already present", already_present)
        self.preview_changes.setVisible(
            bool(
                preview.file_changes
                or preview.image_changes
                or preview.external_changes
                or preview.json_warnings
                or preview.preserved_translation_asset_paths
            )
        )
        self.preview_empty.setVisible(False)
        self.preview_panel.setVisible(True)
        self.preview_btn.setText("Refresh preview")
        self.update_btn.setText(
            "Apply update"
            if preview.content_change_expected
            else "Record version (no content changes)"
        )
        self.update_btn.setEnabled(True)

    def _add_change_group(
        self, title: str, changes: tuple[UpdateFileChange, ...]
    ) -> None:
        if not changes:
            return
        group = QTreeWidgetItem([f"{title} ({len(changes)})", "", "", ""])
        group.setFlags(group.flags() & ~Qt.ItemIsSelectable)
        self.preview_changes.addTopLevelItem(group)
        for change in changes:
            group.addChild(
                QTreeWidgetItem(
                    [
                        change.path,
                        change.change,
                        self._line_change_text(change),
                        change.result,
                    ]
                )
            )
        group.setExpanded(True)

    def _add_image_group(
        self, title: str, changes: tuple[UpdateImageChange, ...]
    ) -> None:
        if not changes:
            return
        group = QTreeWidgetItem([f"{title} ({len(changes)})", "", "", ""])
        group.setFlags(group.flags() & ~Qt.ItemIsSelectable)
        self.preview_changes.addTopLevelItem(group)
        for change in changes:
            group.addChild(
                QTreeWidgetItem(
                    [change.path, change.change, "Binary", change.result]
                )
            )
        group.setExpanded(True)

    def _add_external_group(
        self, title: str, changes: tuple[UpdateExternalChange, ...]
    ) -> None:
        if not changes:
            return
        group = QTreeWidgetItem([f"{title} ({len(changes)})", "", "", ""])
        group.setFlags(group.flags() & ~Qt.ItemIsSelectable)
        self.preview_changes.addTopLevelItem(group)
        for change in changes:
            group.addChild(
                QTreeWidgetItem(
                    [change.path, change.change, change.category, change.result]
                )
            )
        group.setExpanded(True)

    @staticmethod
    def _line_change_text(change: UpdateFileChange) -> str:
        if change.added_lines is None or change.deleted_lines is None:
            return "Binary"
        if change.change == "Added":
            return f"+{change.added_lines}"
        if change.change == "Removed":
            return f"−{change.deleted_lines}"
        return f"+{change.added_lines} / −{change.deleted_lines}"

    def _invalidate_preview(self):
        self._preview = None
        if hasattr(self, "update_btn"):
            self.update_btn.setEnabled(False)
            self.update_btn.setText("Apply update")
            self.preview_btn.setText("Preview update")
        if hasattr(self, "preview_changes"):
            self.preview_changes.clear()
            self.preview_changes.setVisible(True)
            self.preview_panel.setVisible(False)
            self.preview_empty.setVisible(True)

    def _apply_registered(self):
        current = self.current_edit.text().strip()
        self._run(lambda: apply_registered_original(current), self._show_update_result)

    def _continue(self):
        current = self.current_edit.text().strip()
        self._run(lambda: continue_with_official(current), self._show_update_result)

    def _abort(self):
        current = self.current_edit.text().strip()
        self._run(
            lambda: abort_update(current),
            lambda _result: self._set_activity(
                "Cherry-pick aborted. Translation was restored; the official release remains registered on original."
            ),
        )

    def _show_update_result(self, result):
        self._invalidate_preview()
        if result.content_changed:
            lines = [f"Official version {result.version} registered and applied."]
        else:
            lines = [
                f"Official version {result.version} registered; no game files changed.",
                "The translated branch already contained every file change in the official patch.",
            ]
        lines.extend(
            [
                f"Original patch commit: {result.original_commit}",
                f"Translation {'commit' if result.content_changed else 'version-marker commit'}: {result.translation_commit or 'pending'}",
            ]
        )
        if result.already_present_paths:
            lines.extend(
                [
                    "",
                    "Official patch files already present:",
                    *result.already_present_paths,
                ]
            )
        synchronized_assets = tuple(
            change
            for change in result.external_changes
            if not change.already_present
        )
        if synchronized_assets:
            lines.extend(
                [
                    "",
                    "Official assets synchronized outside Git:",
                    *(
                        f"{change.change}: {change.path}"
                        for change in synchronized_assets
                    ),
                ]
            )
        if result.official_won_paths:
            lines.extend(
                [
                    "",
                    "Official content replaced translation in these conflicts:",
                    *result.official_won_paths,
                ]
            )
        else:
            lines.extend(["", "No file conflicts required official-first resolution."])
        self._set_activity("\n".join(lines))

    def _operation_failed(self, message: str):
        self._set_activity(f"Operation failed:\n{message}")
        QMessageBox.critical(self, "Version Update failed", message)
