"""Generic project-context setup and guidance review dialog."""

from __future__ import annotations

from collections.abc import Callable

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from gui.setup_skills_editors import SetupSkillsEditors
from gui.theme import Geometry, Spacing
from gui.ui_components import PageHeader, SectionCard, configure_action_button
from gui.workflow_components import StatusBanner


class TranslationContextDialog(QDialog):
    """Modeless editor for one generic project's portable translation context."""

    context_changed = pyqtSignal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        game_root_fn: Callable[[], str],
        copy_setup_fn: Callable[[], bool] | None = None,
    ):
        super().__init__(parent)
        self._game_root_fn = game_root_fn
        self._copy_setup_fn = copy_setup_fn

        self.setWindowTitle("Project translation context")
        self.setWindowModality(Qt.WindowModal)
        self.setMinimumSize(860, 640)
        self.resize(1040, 760)
        self.setSizeGripEnabled(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            Spacing.XL, Spacing.LG, Spacing.XL, Spacing.LG
        )
        layout.setSpacing(Spacing.LG)
        layout.addWidget(
            PageHeader(
                "Project context",
                "Generate and review the terminology, voice, and translation frame "
                "used for this project.",
            )
        )

        setup_card = SectionCard(
            "Generic setup" if copy_setup_fn else "Selected project",
            ("Use this when the project does not fit an engine-specific Workflow. "
             "The copied skill discovers the file structure before writing guidance.")
            if copy_setup_fn else
            "Your assistant prepares this guidance as part of the main task. Review or edit it below whenever needed.",
            compact=True,
        )
        self.project_path = QLineEdit()
        self.project_path.setReadOnly(True)
        self.project_path.setPlaceholderText("Choose a project in the main window")
        setup_card.add_widget(self.project_path)

        self.status_banner = StatusBanner(
            "Choose a project folder to review its guidance.", "info"
        )
        setup_card.add_widget(self.status_banner)

        setup_actions = QHBoxLayout()
        setup_actions.setContentsMargins(0, 0, 0, 0)
        setup_actions.setSpacing(Spacing.SM)
        self.copy_setup_button = QPushButton("Copy generic setup skill")
        configure_action_button(
            self.copy_setup_button,
            variant="primary",
            tooltip="Copy instructions that inspect this project and write all three guidance files",
        )
        self.copy_setup_button.setMinimumWidth(Geometry.ACTION_WIDE)
        self.copy_setup_button.clicked.connect(self._copy_setup)
        self.copy_setup_button.setVisible(copy_setup_fn is not None)
        setup_actions.addWidget(self.copy_setup_button)

        self.reload_button = QPushButton("Reload guidance")
        configure_action_button(
            self.reload_button,
            variant="secondary",
            tooltip="Reload Glossary, Game frame, Quirks, and custom skills from disk",
        )
        self.reload_button.setMinimumWidth(Geometry.ACTION)
        self.reload_button.clicked.connect(self.reload_context)
        setup_actions.addWidget(self.reload_button)
        setup_actions.addStretch(1)
        setup_card.add_layout(setup_actions)
        layout.addWidget(setup_card)

        guidance_card = SectionCard(
            "Guidance files",
            "Reload after the AI helper finishes. Review each tab and save only "
            "the corrections you make here.",
            compact=True,
        )
        guidance_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.editors = SetupSkillsEditors(
            self,
            game_root_fn=self._current_root,
            log_fn=self._handle_editor_message,
        )
        guidance_card.add_widget(self.editors, 1)
        layout.addWidget(guidance_card, 1)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_button = QPushButton("Close")
        configure_action_button(close_button, variant="quiet")
        close_button.clicked.connect(self.close)
        close_row.addWidget(close_button)
        layout.addLayout(close_row)

    def _current_root(self) -> str:
        return str(self._game_root_fn() or "").strip()

    def reload_context(self) -> bool:
        """Reload the selected project's guidance and update dialog state."""
        root = self._current_root()
        self.project_path.setText(root)
        self.project_path.setCursorPosition(0)
        enabled = bool(root)
        self.copy_setup_button.setEnabled(enabled and self._copy_setup_fn is not None)
        self.reload_button.setEnabled(enabled)
        if not enabled:
            self.editors.invalidate()
            self.status_banner.set_status(
                "Choose a project folder in the main window first.", "warning"
            )
            return False

        loaded = self.editors.reload_all()
        if loaded:
            self.status_banner.set_status(
                "Guidance loaded. An empty tab means that file has not been generated yet.",
                "success",
            )
            self.context_changed.emit()
        return loaded

    def _copy_setup(self) -> None:
        if self._copy_setup_fn is not None and self._copy_setup_fn():
            self.reload_context()
            self.status_banner.set_status(
                "Setup skill copied. Run it in your AI helper with this project accessible, "
                "then reload the guidance files.",
                "success",
            )

    def _handle_editor_message(self, message: str) -> None:
        text = str(message or "").strip()
        kind = (
            "error"
            if text.startswith("❌")
            else "warning"
            if text.startswith("⚠")
            else "success"
        )
        self.status_banner.set_status(text, kind)
        self.context_changed.emit()
