"""Wolf RPG configuration tab (basic initial implementation).

Provides toggles for a subset of flags in wolf.py so users can enable/disable
what gets translated. This can be expanded later.
"""
from pathlib import Path
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QCheckBox, QPushButton, QMessageBox, QLabel, QHBoxLayout, QGridLayout
)
from PyQt5.QtCore import pyqtSignal
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

class WolfTab(QWidget):
    config_changed = pyqtSignal()

    DEFAULT_CONFIG = {
        # Dialogue/choices
        "CODE101": True,
        "CODE102": True,
        # Picture
        "CODE150": True,
        # Strings / variables
        "CODE122": True,
        # Other
        "CODE210": True,
        "CODE300": True,
        "CODE250": True,
        # Database flags
        "SCENARIOFLAG": True,
        "OPTIONSFLAG": True,
        "NPCFLAG": True,
        "DBNAMEFLAG": True,
        "DBVALUEFLAG": True,
        "ITEMFLAG": True,
        "STATEFLAG": True,
        "ENEMYFLAG": True,
        "ARMORFLAG": True,
        "WEAPONFLAG": True,
        "SKILLFLAG": True,
    }

    def __init__(self):
        super().__init__()
        # Initialize UI, set values from module/canonical defaults, then connect auto-apply
        self.init_ui()

        # Prefer canonical defaults when present; do not apply to module on init
        defaults = CANONICAL_DEFAULTS if CANONICAL_DEFAULTS is not None else self.DEFAULT_CONFIG
        # Ensure UI uses these defaults without triggering writes (connect_auto_apply is called after)
        self.set_config(defaults)
        # Now connect auto-apply handlers
        self.connect_auto_apply()

    def init_ui(self):
        """Initialize the user interface with compact two-column layout."""
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(10)
        
        # Title and description
        title = QLabel("Wolf RPG Editor Translation Settings (Legacy)")
        title.setStyleSheet("font-size: 15px; font-weight: bold; color: #007acc;")
        main_layout.addWidget(title)

        description = QLabel(
            "These toggles configure the legacy 'Wolf RPG' / 'Wolf RPG 2' modules (event-code "
            "based extraction). Only enable what you need."
        )
        description.setWordWrap(True)
        description.setStyleSheet("color: #888888; font-size: 10px; margin-bottom: 5px;")
        main_layout.addWidget(description)

        recommend = QLabel(
            "Recommended: use the Workflow tab and pick \"Wolf RPG (WolfDawn)\" for a guided, "
            "end-to-end pipeline (unpack \u2192 extract \u2192 translate \u2192 inject \u2192 package). "
            "It does not use the options below."
        )
        recommend.setWordWrap(True)
        recommend.setStyleSheet(
            "color:#c8c8c8;font-size:11px;background-color:#26333a;"
            "border-left:3px solid #007acc;padding:6px 8px;margin-bottom:6px;"
        )
        main_layout.addWidget(recommend)
        
        # Two-column layout for checkboxes
        columns_layout = QHBoxLayout()
        columns_layout.setSpacing(40)
        
        # LEFT COLUMN
        left_column = QVBoxLayout()
        left_column.setSpacing(5)
        
        # Dialogue & Choices
        left_column.addWidget(create_section_label("💬 Dialogue & Choices"))
        self.code101_cb = QCheckBox("CODE101 - Show Text")
        self.code101_cb.setToolTip("Enable translation of dialogue text")
        left_column.addWidget(self.code101_cb)
        
        self.code102_cb = QCheckBox("CODE102 - Show Choices")
        self.code102_cb.setToolTip("Enable translation of choice options")
        left_column.addWidget(self.code102_cb)
        
        left_column.addSpacing(15)
        
        # Pictures & Variables
        left_column.addWidget(create_section_label("🖼️ Pictures & Variables"))
        self.code150_cb = QCheckBox("CODE150 - Show Picture")
        self.code150_cb.setToolTip("Enable translation of picture-related text")
        left_column.addWidget(self.code150_cb)
        
        self.code122_cb = QCheckBox("CODE122 - String Operations")
        self.code122_cb.setToolTip("Enable translation of string variables")
        left_column.addWidget(self.code122_cb)
        
        left_column.addSpacing(15)
        
        # Other Event Codes
        left_column.addWidget(create_section_label("🎮 Other Event Codes"))
        self.code210_cb = QCheckBox("CODE210 - Conditional Branch")
        left_column.addWidget(self.code210_cb)
        
        self.code300_cb = QCheckBox("CODE300 - Set Variable")
        left_column.addWidget(self.code300_cb)
        
        self.code250_cb = QCheckBox("CODE250 - Sound Effect")
        left_column.addWidget(self.code250_cb)
        
        left_column.addStretch()
        
        # RIGHT COLUMN
        right_column = QVBoxLayout()
        right_column.setSpacing(5)
        
        # Database Sections
        right_column.addWidget(create_section_label("📚 Database Sections"))
        
        # Database flags in compact 2-column grid
        db_grid = QGridLayout()
        db_grid.setSpacing(5)
        db_grid.setHorizontalSpacing(25)
        db_grid.setVerticalSpacing(6)
        
        database_flags = [
            ("SCENARIOFLAG", "Scenario Text"),
            ("OPTIONSFLAG", "Options"),
            ("NPCFLAG", "NPC Data"),
            ("DBNAMEFLAG", "Database Names"),
            ("DBVALUEFLAG", "Database Values"),
            ("ITEMFLAG", "Items"),
            ("STATEFLAG", "States"),
            ("ENEMYFLAG", "Enemies"),
            ("ARMORFLAG", "Armor"),
            ("WEAPONFLAG", "Weapons"),
            ("SKILLFLAG", "Skills"),
        ]
        
        self.db_checkboxes = {}
        for idx, (key, label) in enumerate(database_flags):
            cb = QCheckBox(label)
            db_grid.addWidget(cb, idx // 2, idx % 2)
            self.db_checkboxes[key] = cb
        
        right_column.addLayout(db_grid)
        right_column.addStretch()
        
        # Add both columns
        columns_layout.addLayout(left_column, 1)
        columns_layout.addLayout(right_column, 1)
        main_layout.addLayout(columns_layout)
        
        # Bottom buttons
        main_layout.addSpacing(12)
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)
        
        from gui.qt_icons import apply_button_icon

        self.reset_btn = QPushButton()
        apply_button_icon(self.reset_btn, "🔄 Reset to Defaults", color="#cccccc")
        self.reset_btn.clicked.connect(self.reset_to_defaults_with_message)
        self.reset_btn.setMaximumWidth(180)
        self.reset_btn.setMinimumHeight(32)
        
        button_layout.addWidget(self.reset_btn)
        button_layout.addStretch()
        
        main_layout.addLayout(button_layout)
        self.setLayout(main_layout)
        
        # Note: auto-apply connections are established by connect_auto_apply()
        pass


    def get_config(self):
        """Get current configuration as dictionary."""
        config = {
            "CODE101": self.code101_cb.isChecked(),
            "CODE102": self.code102_cb.isChecked(),
            "CODE150": self.code150_cb.isChecked(),
            "CODE122": self.code122_cb.isChecked(),
            "CODE210": self.code210_cb.isChecked(),
            "CODE300": self.code300_cb.isChecked(),
            "CODE250": self.code250_cb.isChecked(),
        }
        # Add database checkboxes
        for key, cb in self.db_checkboxes.items():
            config[key] = cb.isChecked()
        return config

    def set_config(self, config: dict):
        """Set configuration from dictionary (does not write to module)."""
        self.code101_cb.setChecked(config.get("CODE101", False))
        self.code102_cb.setChecked(config.get("CODE102", False))
        self.code150_cb.setChecked(config.get("CODE150", False))
        self.code122_cb.setChecked(config.get("CODE122", False))
        self.code210_cb.setChecked(config.get("CODE210", False))
        self.code300_cb.setChecked(config.get("CODE300", False))
        self.code250_cb.setChecked(config.get("CODE250", False))
        for key, cb in self.db_checkboxes.items():
            cb.setChecked(config.get(key, False))

    def connect_auto_apply(self):
        """Connect widget changes to auto-apply behavior."""
        self.code101_cb.stateChanged.connect(lambda: self.apply_to_module(False))
        self.code102_cb.stateChanged.connect(lambda: self.apply_to_module(False))
        self.code150_cb.stateChanged.connect(lambda: self.apply_to_module(False))
        self.code122_cb.stateChanged.connect(lambda: self.apply_to_module(False))
        self.code210_cb.stateChanged.connect(lambda: self.apply_to_module(False))
        self.code300_cb.stateChanged.connect(lambda: self.apply_to_module(False))
        self.code250_cb.stateChanged.connect(lambda: self.apply_to_module(False))
        for cb in self.db_checkboxes.values():
            cb.stateChanged.connect(lambda: self.apply_to_module(False))

    def reset_to_defaults(self):
        """Reset all settings to default values without showing message."""
        defaults = CANONICAL_DEFAULTS if 'CANONICAL_DEFAULTS' in globals() and CANONICAL_DEFAULTS is not None else self.DEFAULT_CONFIG
        self.set_config(defaults)
        # Apply changes after resetting
        self.apply_to_module(False)
    
    def reset_to_defaults_with_message(self):
        """Reset to defaults and show confirmation message."""
        self.reset_to_defaults()
        QMessageBox.information(
            self,
            "Reset Complete",
            "All settings have been reset to their default values."
        )

    def apply_to_module(self, show_message=False):
        """Apply current configuration to wolf.py module."""
        module_path = Path(__file__).parent.parent / 'modules' / 'wolf.py'
        if not module_path.exists():
            if show_message:
                QMessageBox.critical(self, 'Error', 'wolf.py not found in modules directory.')
            return
        try:
            content = module_path.read_text(encoding='utf-8')
            for key, value in self.get_config().items():
                pattern = rf'^{key}\s*=\s*.*$'
                content = re.sub(pattern, f'{key} = {value}', content, flags=re.MULTILINE)
            module_path.write_text(content, encoding='utf-8')
            self.config_changed.emit()
            if show_message:
                QMessageBox.information(self, 'Applied', 'Wolf configuration applied to wolf.py')
        except Exception as e:
            if show_message:
                QMessageBox.critical(self, 'Error', f'Failed to apply settings: {e}')
