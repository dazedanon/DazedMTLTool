"""SRPG Studio configuration tab.

Provides toggles for configurable flags in srpg.py so users can
enable/disable text-wrap fixing and skip-already-translated behaviour.
"""
from pathlib import Path
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QCheckBox, QPushButton, QMessageBox, QLabel, QHBoxLayout
)
from PyQt5.QtCore import pyqtSignal
from gui.theme import COLORS
from gui.ui_components import SectionCard, configure_action_button
import re
try:
    from util.defaults import DEFAULTS as CANONICAL_DEFAULTS
except Exception:
    CANONICAL_DEFAULTS = None


def create_section_label(text):
    """Create a styled section header label."""
    from gui.qt_icons import make_section_header

    return make_section_header(
        text,
        "font-size: 12px; font-weight: bold; color: #007acc; padding: 2px 0px;",
    )


class SRPGTab(QWidget):
    config_changed = pyqtSignal()

    DEFAULT_CONFIG = {
        "FIXTEXTWRAP": True,
        "IGNORETLTEXT": False,
    }

    def __init__(self):
        super().__init__()
        self.init_ui()

        defaults = CANONICAL_DEFAULTS if CANONICAL_DEFAULTS is not None else self.DEFAULT_CONFIG
        self.set_config(defaults)
        self.connect_auto_apply()

    def init_ui(self):
        """Initialize the user interface."""
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        behavior_card = SectionCard(
            "Text handling",
            "Choose how SRPG Studio text is wrapped and whether existing translations are skipped.",
        )
        main_layout.addWidget(behavior_card)

        self.fixtextwrap_cb = QCheckBox("Fix Text Wrap")
        self.fixtextwrap_cb.setToolTip(
            "Re-wrap translated text to fit the configured dialogue width (WIDTH setting)"
        )
        behavior_card.add_widget(self.fixtextwrap_cb)

        self.ignoretltext_cb = QCheckBox("Ignore Already-Translated Text")
        self.ignoretltext_cb.setToolTip(
            "Skip lines that appear to have already been translated"
        )
        behavior_card.add_widget(self.ignoretltext_cb)

        main_layout.addStretch()

        # Bottom buttons
        button_layout = QHBoxLayout()
        button_layout.setSpacing(8)

        from gui.qt_icons import apply_button_icon

        self.reset_btn = QPushButton()
        configure_action_button(self.reset_btn, variant="quiet")
        apply_button_icon(
            self.reset_btn, "🔄 Reset to defaults", color=COLORS.text_secondary
        )
        self.reset_btn.clicked.connect(self.reset_to_defaults_with_message)
        self.reset_btn.setMinimumWidth(180)
        self.reset_btn.setMinimumHeight(32)

        button_layout.addWidget(self.reset_btn)
        button_layout.addStretch()

        main_layout.addLayout(button_layout)
        self.setLayout(main_layout)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_config(self) -> dict:
        """Return current configuration as a dictionary."""
        return {
            "FIXTEXTWRAP": self.fixtextwrap_cb.isChecked(),
            "IGNORETLTEXT": self.ignoretltext_cb.isChecked(),
        }

    def set_config(self, config: dict):
        """Set configuration from dictionary (does not write to module)."""
        self.fixtextwrap_cb.setChecked(config.get("FIXTEXTWRAP", True))
        self.ignoretltext_cb.setChecked(config.get("IGNORETLTEXT", False))

    def connect_auto_apply(self):
        """Connect widget changes to auto-apply to srpg.py."""
        self.fixtextwrap_cb.stateChanged.connect(lambda: self.apply_to_module(False))
        self.ignoretltext_cb.stateChanged.connect(lambda: self.apply_to_module(False))

    def reset_to_defaults(self):
        """Reset all settings to defaults without showing a message."""
        defaults = (
            CANONICAL_DEFAULTS
            if 'CANONICAL_DEFAULTS' in globals() and CANONICAL_DEFAULTS is not None
            else self.DEFAULT_CONFIG
        )
        self.set_config(defaults)
        self.apply_to_module(False)

    def reset_to_defaults_with_message(self):
        """Reset to defaults and show a confirmation message."""
        self.reset_to_defaults()
        QMessageBox.information(
            self,
            "Reset Complete",
            "All settings have been reset to their default values.",
        )

    def apply_to_module(self, show_message: bool = False):
        """Write current configuration back to modules/srpg.py."""
        module_path = Path(__file__).parent.parent / 'modules' / 'srpg.py'
        if not module_path.exists():
            if show_message:
                QMessageBox.critical(self, 'Error', 'srpg.py not found in modules directory.')
            return
        try:
            content = module_path.read_text(encoding='utf-8')
            for key, value in self.get_config().items():
                pattern = rf'^{key}\s*=\s*.*$'
                content = re.sub(pattern, f'{key} = {value}', content, flags=re.MULTILINE)
            module_path.write_text(content, encoding='utf-8')
            self.config_changed.emit()
            if show_message:
                QMessageBox.information(self, 'Applied', 'SRPG Studio configuration applied to srpg.py.')
        except Exception as e:
            if show_message:
                QMessageBox.critical(self, 'Error', f'Failed to apply settings: {e}')
