"""GUI for the engine-independent, Git-backed version update workflow."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from PyQt5.QtCore import QThread, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from gui.theme import COLORS, Spacing
from util.version_update import (
    GitWorkflowError,
    RepositoryStatus,
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
        self._scan_timer = QTimer(self)
        self._scan_timer.setSingleShot(True)
        self._scan_timer.setInterval(300)
        self._scan_timer.timeout.connect(self.refresh_status)
        self._build_ui()

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
                "Keep official releases on the original branch and apply their exact Git commits to translation.",
            )
        )

        repository_card = SectionCard(
            "Translation repository",
            "Select the translated game. The tool immediately detects its repository, branches, versions, and recovery state.",
            compact=True,
        )
        repository_form = QFormLayout()
        repository_form.setContentsMargins(0, 0, 0, 0)
        self.current_edit = self._folder_row(
            repository_form,
            "Translated game:",
            "Folder containing the translated working game",
        )
        self.current_edit.textChanged.connect(lambda _text: self._scan_timer.start())
        self.current_edit.textChanged.connect(lambda _text: self._invalidate_preview())
        repository_card.add_layout(repository_form)
        refresh_row = QHBoxLayout()
        refresh_row.addStretch()
        self.refresh_btn = QPushButton("Refresh repository status")
        configure_action_button(self.refresh_btn, variant="quiet")
        self.refresh_btn.clicked.connect(self.refresh_status)
        refresh_row.addWidget(self.refresh_btn)
        self.switch_translation_btn = QPushButton("Switch to translation")
        configure_action_button(self.switch_translation_btn, variant="secondary")
        self.switch_translation_btn.clicked.connect(self._switch_translation)
        self.switch_translation_btn.setVisible(False)
        refresh_row.addWidget(self.switch_translation_btn)
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
            "Create the branch baseline",
            "If original is missing, supply the clean game matching the current translation. The translated files stay in place while Git constructs both branches.",
        )
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
        bootstrap_card.add_layout(bootstrap_form)
        bootstrap_actions = QHBoxLayout()
        self.bootstrap_explanation = QLabel(
            "No original branch was detected. This is required once before version updates."
        )
        self.bootstrap_explanation.setWordWrap(True)
        self.bootstrap_explanation.setStyleSheet(f"color:{COLORS.text_muted};")
        bootstrap_actions.addWidget(self.bootstrap_explanation, 1)
        self.bootstrap_btn = QPushButton("Create original + translation branches")
        configure_action_button(self.bootstrap_btn, variant="primary")
        self.bootstrap_btn.clicked.connect(self._bootstrap)
        bootstrap_actions.addWidget(self.bootstrap_btn)
        bootstrap_card.add_layout(bootstrap_actions)
        layout.addWidget(bootstrap_card)
        self.bootstrap_card = bootstrap_card

        update_card = SectionCard(
            "Apply a new official release",
            "The new folder becomes one exact commit on original. That commit is cherry-picked into translation; conflicting files use the official version and are reported for translation review.",
        )
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
        self.preview_details = QTextEdit()
        self.preview_details.setReadOnly(True)
        self.preview_details.setMinimumHeight(180)
        self.preview_details.setPlaceholderText(
            "Preview the official release to see file changes, JSON formatting, likely overlaps, and warnings."
        )
        update_card.add_widget(self.preview_details)
        update_actions = QHBoxLayout()
        self.apply_registered_btn = QPushButton("Apply registered original update")
        configure_action_button(self.apply_registered_btn, variant="secondary")
        self.apply_registered_btn.clicked.connect(self._apply_registered)
        self.apply_registered_btn.setVisible(False)
        update_actions.addWidget(self.apply_registered_btn)
        update_actions.addStretch()
        self.preview_btn = QPushButton("Preview changes")
        configure_action_button(self.preview_btn, variant="secondary")
        self.preview_btn.clicked.connect(self._preview_update)
        update_actions.addWidget(self.preview_btn)
        self.update_btn = QPushButton("Approve and apply")
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
            "Update activity",
            "Files listed here used the new official copy and should be reviewed for translation.",
        )
        self.activity = QTextEdit()
        self.activity.setReadOnly(True)
        self.activity.setPlaceholderText("No version update has run in this session.")
        self.activity.setMinimumHeight(150)
        activity_card.add_widget(self.activity)
        layout.addWidget(activity_card)
        self.activity_card = activity_card

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)
        layout.addStretch()
        self._render_status(None)

    def _folder_row(self, form: QFormLayout, label: str, placeholder: str) -> QLineEdit:
        row = QHBoxLayout()
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        browse = QPushButton("Browse…")
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

    def _render_status(self, status: RepositoryStatus | None):
        if status is None:
            self.repository_status.setText("Select a translated game folder.")
            self.version_status.setText("")
            self.bootstrap_card.setVisible(True)
            self.update_card.setEnabled(False)
            self.recovery_card.setVisible(False)
            self.switch_translation_btn.setVisible(False)
            return

        if status.repo_root is None:
            self.repository_status.setText(
                "No Git repository found. Supply the matching original game to create the workflow."
            )
            self.version_status.setText("Original branch: missing · Translation branch: missing")
        else:
            clean = "clean" if status.worktree_clean else "uncommitted changes"
            self.repository_status.setText(
                f"Repository: {status.repo_root} · Branch: {status.current_branch or 'detached HEAD'} · {clean}"
            )
            original = status.original_version or ("unknown" if status.original_exists else "missing")
            translated = status.translation_version or (
                "unknown" if status.translation_exists else "missing"
            )
            self.version_status.setText(
                f"Original version: {original} · Translation version: {translated}"
            )
        self.repository_status.setStyleSheet(f"color:{COLORS.accent_text};")
        needs_bootstrap = not status.original_exists or not status.translation_exists
        self.bootstrap_card.setVisible(needs_bootstrap)
        if status.original_exists and not status.translation_exists:
            self.bootstrap_explanation.setText(
                "The original branch exists, but translation is missing. The current clean game tree can be registered without importing the original again."
            )
            self.bootstrap_btn.setText("Register current game as translation")
            self.original_edit.setEnabled(False)
            if status.original_version and not self.original_version_edit.text().strip():
                self.original_version_edit.setText(status.original_version)
        else:
            self.bootstrap_explanation.setText(
                "No original branch was detected. This is required once before version updates."
            )
            self.bootstrap_btn.setText("Create original + translation branches")
            self.original_edit.setEnabled(True)
        self.switch_translation_btn.setVisible(
            bool(
                status.translation_exists
                and status.current_branch != "translation"
                and status.worktree_clean
                and not status.pending_cherry_pick
            )
        )
        branch_ready = (
            status.repo_root is not None
            and status.original_exists
            and status.translation_exists
            and status.current_branch == "translation"
            and status.worktree_clean
            and not status.pending_cherry_pick
        )
        self.update_card.setEnabled(branch_ready)
        behind = bool(
            status.original_version
            and status.translation_version
            and status.original_version != status.translation_version
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
            self.refresh_btn,
            self.switch_translation_btn,
            self.bootstrap_btn,
            self.update_btn,
            self.preview_btn,
            self.apply_registered_btn,
            self.continue_btn,
            self.abort_btn,
        ):
            button.setEnabled(not busy)
        if not busy:
            self.update_btn.setEnabled(self._preview is not None)

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
        self.activity.setPlainText("\n".join(lines))

    def _switch_translation(self):
        current = self.current_edit.text().strip()
        self._run(
            lambda: checkout_translation_branch(current),
            lambda _result: self.activity.setPlainText(
                "Switched the selected repository to the translation branch."
            ),
        )

    def _apply_update(self):
        current = self.current_edit.text().strip()
        official = self.new_edit.text().strip()
        version = self.new_version_edit.text().strip()
        if not current or not official or not version:
            QMessageBox.warning(
                self,
                "Missing update information",
                "Select the new official game and enter its version.",
            )
            return
        if (
            self._preview is None
            or self._preview.source_root != Path(official).expanduser().resolve()
            or self._preview.version != version
        ):
            QMessageBox.warning(
                self,
                "Preview required",
                "Preview the current official folder and version before approving the update.",
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
            ),
            self._show_update_result,
        )

    def _preview_update(self):
        current = self.current_edit.text().strip()
        official = self.new_edit.text().strip()
        version = self.new_version_edit.text().strip()
        if not current or not official or not version:
            QMessageBox.warning(
                self,
                "Missing update information",
                "Select the new official game and enter its version.",
            )
            return
        self._run(
            lambda: preview_official_update(current, official, version),
            self._show_preview,
        )

    def _show_preview(self, preview):
        self._preview = preview
        lines = [
            f"Official version {preview.version}",
            "",
            "Official release delta (previous original → new original):",
            f"Added: {len(preview.added_paths)}",
            f"Modified: {len(preview.modified_paths)}",
            f"Deleted: {len(preview.deleted_paths)}",
            "",
            "Translation impact:",
            f"Files that would change: {len(preview.translation_change_paths)}",
            f"Official patch files already present: {len(preview.already_present_paths)}",
            "",
            "Import details:",
            f"Structured files normalized: {len(preview.formatted_json_paths)}",
            f"Files also changed by translation: {len(preview.overlapping_paths)}",
            f"Formatting warnings: {len(preview.json_warnings)}",
            f"Files ignored by Git: {len(preview.ignored_paths)}",
        ]
        if not preview.content_change_expected:
            lines.extend(
                [
                    "",
                    "No translated-game content changes are expected.",
                    "Every official patch file already matches the translation branch. Approval will only record the version with an explicit metadata-only commit.",
                ]
            )
        groups = (
            ("Official release — added files", preview.added_paths),
            ("Official release — modified files", preview.modified_paths),
            ("Official release — deleted files", preview.deleted_paths),
            ("Translation files that would change", preview.translation_change_paths),
            ("Potential translation overlaps", preview.overlapping_paths),
            (
                "Already identical in translation — no content change",
                preview.already_present_paths,
            ),
            ("Structured files normalized before commit", preview.formatted_json_paths),
            ("Warnings", preview.json_warnings),
            ("Ignored by Git", preview.ignored_paths),
        )
        for heading, paths in groups:
            if paths:
                lines.extend(["", f"{heading}:", *paths])
        self.preview_details.setPlainText("\n".join(lines))
        self.update_btn.setText(
            "Approve and apply"
            if preview.content_change_expected
            else "Record version (no content changes)"
        )
        self.update_btn.setEnabled(True)

    def _invalidate_preview(self):
        self._preview = None
        if hasattr(self, "update_btn"):
            self.update_btn.setEnabled(False)
            self.update_btn.setText("Approve and apply")
        if hasattr(self, "preview_details"):
            self.preview_details.clear()

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
            lambda _result: self.activity.setPlainText(
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
                "The translation branch already contained every file change in the official patch.",
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
        if result.official_won_paths:
            lines.extend(
                [
                    "",
                    "Official version won these conflicts; review them for translation:",
                    *result.official_won_paths,
                ]
            )
        else:
            lines.extend(["", "No file conflicts required official-first resolution."])
        self.activity.setPlainText("\n".join(lines))

    def _operation_failed(self, message: str):
        self.activity.setPlainText(f"Operation failed:\n{message}")
        QMessageBox.critical(self, "Version Update failed", message)
