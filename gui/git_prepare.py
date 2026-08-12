"""Shared Prepare-step UI for Git-backed game version tracking."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QInputDialog,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gui.theme import COLORS, Geometry, Spacing
from gui.workflow_components import WorkflowStageCard, make_workflow_button
from util.version_update import (
    GitWorkflowError,
    RepositoryStatus,
    bootstrap_repository,
    checkout_translation_branch,
    inspect_repository,
    local_branch_names,
    record_version_metadata,
    register_translation_branch,
)


class _GitPrepareWorker(QThread):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, operation: Callable[[], object], parent=None):
        super().__init__(parent)
        self._operation = operation

    def run(self) -> None:
        try:
            self.succeeded.emit(self._operation())
        except Exception as exc:
            self.failed.emit(str(exc))


class GitPreparationCard(WorkflowStageCard):
    """Inspect a selected game and offer the one safe setup action it needs."""

    activity = pyqtSignal(str)

    def __init__(self, number: int = 1, parent=None):
        super().__init__(
            number,
            "Set up Git version tracking",
            "Record the clean original baseline and create or register the translated branch so future game updates can be merged safely.",
            parent=parent,
        )
        self._game_root = ""
        self._status: RepositoryStatus | None = None
        self._action_kind = ""
        self._worker: _GitPrepareWorker | None = None

        self.status_label = QLabel("Choose a game in Project first.")
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("gitPreparationStatus")
        self.add_widget(self.status_label)

        self.fields = QWidget()
        self.fields.setObjectName("transparentCardPanel")
        fields_layout = QVBoxLayout(self.fields)
        fields_layout.setContentsMargins(0, 0, 0, 0)
        fields_layout.setSpacing(Spacing.SM)

        self.original_row = QWidget()
        self.original_row.setObjectName("transparentCardPanel")
        original_layout = QHBoxLayout(self.original_row)
        original_layout.setContentsMargins(0, 0, 0, 0)
        original_layout.setSpacing(Spacing.SM)
        original_layout.addWidget(QLabel("Matching original game:"))
        self.original_edit = QLineEdit()
        self.original_edit.setPlaceholderText(
            "Clean official game matching the current translation"
        )
        original_layout.addWidget(self.original_edit, 1)
        self.original_browse_btn = make_workflow_button("Browse…", variant="quiet")
        self.original_browse_btn.setMinimumWidth(112)
        self.original_browse_btn.clicked.connect(self._browse_original)
        original_layout.addWidget(self.original_browse_btn)
        fields_layout.addWidget(self.original_row)

        version_row = QHBoxLayout()
        version_row.setContentsMargins(0, 0, 0, 0)
        version_row.setSpacing(Spacing.SM)
        version_row.addWidget(QLabel("Current game version:"))
        self.version_edit = QLineEdit()
        self.version_edit.setPlaceholderText("For example: 1.00")
        self.version_edit.setMaximumWidth(220)
        version_row.addWidget(self.version_edit)
        version_row.addStretch()
        fields_layout.addLayout(version_row)
        self.add_widget(self.fields)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(Spacing.SM)
        self.rescan_btn = make_workflow_button("Rescan Git", variant="quiet")
        self.rescan_btn.clicked.connect(self.refresh_status)
        actions.addWidget(self.rescan_btn)
        self.change_branch_btn = make_workflow_button(
            "Use another branch…", variant="quiet"
        )
        self.change_branch_btn.clicked.connect(self._change_translation_branch)
        self.change_branch_btn.setVisible(False)
        actions.addWidget(self.change_branch_btn)
        actions.addStretch()
        self.action_btn = make_workflow_button(
            "Set up version tracking", variant="primary"
        )
        self.action_btn.setMinimumWidth(Geometry.ACTION_WIDE)
        self.action_btn.clicked.connect(self._start_action)
        actions.addWidget(self.action_btn)
        self.add_layout(actions)

        self._render(None)

    def set_game_root(self, game_root: str | Path | None) -> None:
        value = str(game_root or "").strip()
        if value == self._game_root:
            return
        self._game_root = value
        self.original_edit.clear()
        self.version_edit.clear()
        self.refresh_status()

    def refresh_status(self) -> None:
        if not self._game_root:
            self._status = None
            self._render(None)
            return
        try:
            self._status = inspect_repository(self._game_root)
            self._render(self._status)
        except GitWorkflowError as exc:
            self._status = None
            self._set_status(f"Git inspection failed: {exc}", COLORS.danger)
            self.fields.setVisible(False)
            self._set_action("", "Set up version tracking", False)

    def _set_status(self, text: str, color: str) -> None:
        self.status_label.setText(text)
        self.status_label.setStyleSheet(
            f"QLabel#gitPreparationStatus{{background:transparent;color:{color};}}"
        )

    def _set_action(self, kind: str, text: str, enabled: bool = True) -> None:
        self._action_kind = kind
        self.action_btn.setText(text)
        self.action_btn.setVisible(bool(kind))
        self.action_btn.setEnabled(enabled)

    def _render(self, status: RepositoryStatus | None) -> None:
        self.change_branch_btn.setVisible(False)
        self.change_branch_btn.setEnabled(True)
        if status is None:
            self._set_status("Choose a game in Project first.", COLORS.text_muted)
            self.fields.setVisible(False)
            self.rescan_btn.setEnabled(False)
            self._set_action("", "Set up version tracking", False)
            return

        self.rescan_btn.setEnabled(True)
        if not status.selected_root.is_dir():
            self._set_status("The selected game folder no longer exists.", COLORS.danger)
            self.fields.setVisible(False)
            self._set_action("", "Set up version tracking", False)
            return
        if status.pending_cherry_pick:
            self._set_status(
                "An interrupted update must be finished or aborted in Version Update first.",
                COLORS.warning,
            )
            self.fields.setVisible(False)
            self._set_action("", "Set up version tracking", False)
            return
        if not status.worktree_clean:
            self._set_status(
                "Git has uncommitted changes. Commit or discard them, then rescan.",
                COLORS.warning,
            )
            self.fields.setVisible(False)
            self._set_action("", "Set up version tracking", False)
            return

        if not status.original_exists:
            if status.repo_root:
                self._set_status(
                    "Detected an existing Git repository. Enter the current version to "
                    "create the required branches from this game folder.",
                    COLORS.warning,
                )
            else:
                self._set_status(
                    "Detected no Git repository. Enter the current version to create "
                    "version tracking from this game folder.",
                    COLORS.warning,
                )
            self.fields.setVisible(True)
            self.original_row.setVisible(False)
            self._set_action("bootstrap", "Create version tracking")
            return

        if not status.translation_exists:
            if status.current_branch == "original":
                self._set_status(
                    "The original branch is checked out. Check out the branch containing the translated game, then rescan.",
                    COLORS.warning,
                )
                self.fields.setVisible(False)
                self._set_action("", "Register translated game", False)
                return
            self._set_status(
                f"Found the original branch. Register {status.current_branch or 'the detached HEAD'} as the translated branch.",
                COLORS.warning,
            )
            self.fields.setVisible(True)
            self.original_row.setVisible(False)
            if status.original_version and not self.version_edit.text().strip():
                self.version_edit.setText(status.original_version)
            self._set_action("register", "Register translated game")
            return

        if not status.original_version or not status.translation_version:
            self._set_status(
                "Both branches exist, but legacy version metadata is incomplete.",
                COLORS.warning,
            )
            self.fields.setVisible(True)
            self.original_row.setVisible(False)
            known = status.original_version or status.translation_version
            if known and not self.version_edit.text().strip():
                self.version_edit.setText(known)
            self._set_action("metadata", "Repair version metadata")
            return

        if status.current_branch != status.translation_branch:
            self._set_status(
                f"Version tracking uses {status.translation_branch}. Switch to that branch before continuing.",
                COLORS.warning,
            )
            self.fields.setVisible(False)
            self._set_action("switch", f"Switch to {status.translation_branch}")
            return

        self._set_status(
            f"Ready · original {status.original_version} · {status.translation_branch} {status.translation_version}",
            COLORS.success,
        )
        self.fields.setVisible(False)
        self._set_action("", "Version tracking ready", False)
        self.change_branch_btn.setVisible(
            len(local_branch_names(status.selected_root)) > 1
        )

    def _browse_original(self) -> None:
        start = self.original_edit.text().strip()
        if not start and self._game_root:
            start = str(Path(self._game_root).parent)
        selected = QFileDialog.getExistingDirectory(
            self, "Select matching clean original game", start or str(Path.home())
        )
        if selected:
            self.original_edit.setText(selected)

    def _start_action(self) -> None:
        if not self._game_root or not self._action_kind:
            return
        version = self.version_edit.text().strip()
        if self._action_kind in {"bootstrap", "register", "metadata"} and not version:
            QMessageBox.warning(
                self, "Current version required", "Enter the current game version."
            )
            return
        if (
            self._action_kind in {"bootstrap", "register"}
            and self._status is not None
            and self._status.repo_root is not None
            and not self._status.translation_exists
        ):
            branch = self._status.current_branch
            if not branch:
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

        if self._action_kind == "bootstrap":
            # Prepare runs before translation, so the Project folder is the clean
            # baseline for both original and the starting translated branch.
            operation = lambda: bootstrap_repository(
                self._game_root, self._game_root, version
            )
        elif self._action_kind == "register":
            operation = lambda: register_translation_branch(self._game_root, version)
        elif self._action_kind == "metadata":
            operation = lambda: record_version_metadata(self._game_root, version)
        else:
            operation = lambda: checkout_translation_branch(self._game_root)
        self._run(operation)

    def _change_translation_branch(self) -> None:
        if self._status is None or not self._status.repo_root:
            return
        choices = local_branch_names(self._game_root)
        alternatives = tuple(
            branch for branch in choices if branch != self._status.translation_branch
        )
        if not alternatives:
            return
        branch, accepted = QInputDialog.getItem(
            self,
            "Choose translated branch",
            "Branch containing the translated game:",
            alternatives,
            0,
            False,
        )
        if not accepted or not branch:
            return
        answer = QMessageBox.question(
            self,
            "Change translated branch?",
            f"Use {branch!r} instead of {self._status.translation_branch!r}?\n\n"
            f"DazedTL will check out {branch!r} and apply future official updates there. "
            "The previously registered branch will be left unchanged.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        version = self._status.translation_version or self._status.original_version
        self._run(
            lambda: register_translation_branch(
                self._game_root,
                version,
                branch=branch,
                replace=True,
            )
        )

    def _run(self, operation: Callable[[], object]) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self.action_btn.setEnabled(False)
        self.rescan_btn.setEnabled(False)
        self.change_branch_btn.setEnabled(False)
        self._set_status("Preparing Git version tracking…", COLORS.accent_text)
        worker = _GitPrepareWorker(operation, self)
        self._worker = worker
        worker.succeeded.connect(self._operation_succeeded)
        worker.failed.connect(self._operation_failed)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(lambda: setattr(self, "_worker", None))
        worker.start()

    def _operation_succeeded(self, _result: object) -> None:
        self.activity.emit("✅ Git version tracking is ready for this game.")
        self.refresh_status()

    def _operation_failed(self, message: str) -> None:
        self.activity.emit(f"❌ Git setup failed: {message}")
        QMessageBox.critical(self, "Git setup failed", message)
        self.refresh_status()
