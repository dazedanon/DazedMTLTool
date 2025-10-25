"""
RPG Maker MV/MZ Tab - Configuration for RPG Maker specific settings
"""

import json
from pathlib import Path
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QCheckBox, 
    QPushButton, QGroupBox, QLabel, QMessageBox, QScrollArea,
    QTextEdit, QSpinBox, QFrame, QGridLayout
)
from PyQt5.QtCore import Qt, pyqtSignal

try:
    from .config_integration import ConfigIntegration
except ImportError:
    # Fallback if config_integration is not available
    ConfigIntegration = None


def create_section_label(text):
    """Create a section label for grouping checkboxes."""
    label = QLabel(text)
    label.setStyleSheet("""
        QLabel {
            font-size: 12px;
            font-weight: bold;
            color: #007acc;
            padding: 5px 0px 3px 0px;
            background-color: transparent;
        }
    """)
    return label


class RPGMakerTab(QWidget):
    """RPG Maker MV/MZ & Ace configuration tab.

    This widget now supports both MV/MZ and Ace engines. Pass engine="ACE" to
    target rpgmakerace.py; otherwise it will default to MV/MZ (rpgmakermvmz.py).
    """
    
    # Default configuration values for RPG Maker MV/MZ
    DEFAULT_CONFIG = {
        # General settings
        "FIRSTLINESPEAKERS": False,
        "FACENAME101": False,
        "NAMES": False,
        "BRFLAG": False,
        "FIXTEXTWRAP": True,
        "IGNORETLTEXT": False,
        
        # Main dialogue codes (enabled by default)
        "CODE401": True,   # Show Text
        "CODE405": True,   # Show Text (line 4+)
        "CODE102": True,   # Show Choices
        
        # Optional codes (disabled by default)
        "CODE101": False,  # Show Text (face)
        "CODE408": False,  # Show Text (line continuation)
        
        # Variable codes (disabled by default)
        "CODE122": False,  # Control Variables
        
        # Other codes (all disabled by default)
        "CODE103": False,  # Input Number
        "CODE104": False,  # Select Item
        "CODE111": False,  # Conditional Branch
        "CODE117": False,  # Common Event
        "CODE119": False,  # Set Movement Route
        "CODE121": False,  # Control Switches
        "CODE125": False,  # Change Gold
        "CODE126": False,  # Change Items
        "CODE127": False,  # Change Weapons
        "CODE128": False,  # Change Armors
        "CODE129": False,  # Change Party Member
        "CODE132": False,  # Change Battle BGM
        "CODE133": False,  # Change Victory ME
        "CODE134": False,  # Change Save Access
        "CODE135": False,  # Change Menu Access
        "CODE136": False,  # Change Encounter
        "CODE137": False,  # Change Formation Access
        "CODE138": False,  # Change Window Color
        "CODE139": False,  # Change Defeat ME
        "CODE140": False,  # Change Vehicle BGM
        "CODE201": False,  # Transfer Player
        "CODE202": False,  # Set Vehicle Location
        "CODE203": False,  # Set Event Location
        "CODE204": False,  # Scroll Map
        "CODE205": False,  # Set Move Route
        "CODE206": False,  # Get On/Off Vehicle
        "CODE211": False,  # Change Transparency
        "CODE212": False,  # Show Animation
        "CODE213": False,  # Show Balloon Icon
        "CODE214": False,  # Erase Event
        "CODE216": False,  # Change Player Followers
        "CODE217": False,  # Gather Followers
        "CODE221": False,  # Fadeout Screen
        "CODE222": False,  # Fadein Screen
        "CODE223": False,  # Tint Screen
        "CODE224": False,  # Flash Screen
        "CODE225": False,  # Shake Screen
        "CODE230": False,  # Wait
        "CODE231": False,  # Show Picture
        "CODE232": False,  # Move Picture
        "CODE233": False,  # Rotate Picture
        "CODE234": False,  # Tint Picture
        "CODE235": False,  # Erase Picture
        "CODE236": False,  # Set Weather Effect
        "CODE241": False,  # Play BGM
        "CODE242": False,  # Fadeout BGM
        "CODE243": False,  # Save BGM
        "CODE244": False,  # Resume BGM
        "CODE245": False,  # Play BGS
        "CODE246": False,  # Fadeout BGS
        "CODE249": False,  # Play ME
        "CODE250": False,  # Play SE
        "CODE251": False,  # Stop SE
        "CODE261": False,  # Show Movie
        "CODE281": False,  # Change Map Name Display
        "CODE282": False,  # Change Tileset
        "CODE283": False,  # Change Battle Background
        "CODE284": False,  # Change Parallax
        "CODE285": False,  # Get Location Info
        "CODE301": False,  # Battle Processing
        "CODE302": False,  # Shop Processing
        "CODE303": False,  # Name Input Processing
        "CODE311": False,  # Change HP
        "CODE312": False,  # Change MP
        "CODE313": False,  # Change State
        "CODE314": False,  # Recover All
        "CODE315": False,  # Change EXP
        "CODE316": False,  # Change Level
        "CODE317": False,  # Change Parameters
        "CODE318": False,  # Change Skills
        "CODE319": False,  # Change Equipment
        "CODE320": False,  # Change Name
        "CODE321": False,  # Change Class
        "CODE322": False,  # Change Actor Graphic
        "CODE323": False,  # Change Vehicle Graphic
        "CODE324": False,  # Change Nickname
        "CODE325": False,  # Change Profile
        "CODE326": False,  # Change TP
        "CODE331": False,  # Change Enemy HP
        "CODE332": False,  # Change Enemy MP
        "CODE333": False,  # Change Enemy State
        "CODE334": False,  # Enemy Recover All
        "CODE335": False,  # Enemy Appear
        "CODE336": False,  # Enemy Transform
        "CODE337": False,  # Show Battle Animation
        "CODE339": False,  # Force Action
        "CODE340": False,  # Abort Battle
        "CODE351": False,  # Open Menu Screen
        "CODE352": False,  # Open Save Screen
        "CODE353": False,  # Game Over
        "CODE354": False,  # Return to Title Screen
        "CODE355": False,  # Script
        "CODE356": False,  # Plugin Command
    }
    
    config_changed = pyqtSignal()
    
    def __init__(self, engine: str = "MVMZ"):
        super().__init__()
        self.engine = engine.upper()
        self.config_integration = ConfigIntegration() if ConfigIntegration else None
        self.init_ui()
        self.connect_auto_apply()  # Connect auto-apply before setting defaults
        self.reset_to_defaults()
        
    def init_ui(self):
        """Initialize the user interface with compact two-column layout."""
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(10)
        
        # Title and description
        title = "RPG Maker MV/MZ" if self.engine != "ACE" else "RPG Maker Ace"
        title_label = QLabel(f"{title} Translation Settings")
        title_label.setStyleSheet("font-size: 15px; font-weight: bold; color: #007acc;")
        main_layout.addWidget(title_label)

        description_label = QLabel(
            "Enable event codes to translate. Only enable what you need to reduce translation time and costs."
        )
        description_label.setWordWrap(True)
        description_label.setStyleSheet("color: #888888; font-size: 10px; margin-bottom: 5px;")
        main_layout.addWidget(description_label)
        
        # Two-column layout for checkboxes
        columns_layout = QHBoxLayout()
        columns_layout.setSpacing(40)
        
        # LEFT COLUMN
        left_column = QVBoxLayout()
        left_column.setSpacing(5)
        
        # General Configuration
        left_column.addWidget(create_section_label("⚙️ General Options"))
        self.first_line_speakers_cb = QCheckBox("First Line Speakers")
        self.first_line_speakers_cb.setToolTip("Enable if first line of CODE401 contains speaker name")
        left_column.addWidget(self.first_line_speakers_cb)
        
        self.facename101_cb = QCheckBox("Face Name in CODE101")
        self.facename101_cb.setToolTip("Enable to translate face names in CODE101")
        left_column.addWidget(self.facename101_cb)
        
        self.names_cb = QCheckBox("Translate Names")
        self.names_cb.setToolTip("Enable to translate character names")
        left_column.addWidget(self.names_cb)
        
        self.brflag_cb = QCheckBox("Line Break Flag")
        self.brflag_cb.setToolTip("Enable line break handling")
        left_column.addWidget(self.brflag_cb)
        
        self.fixtextwrap_cb = QCheckBox("Fix Text Wrap")
        self.fixtextwrap_cb.setToolTip("Automatically fix text wrapping issues")
        left_column.addWidget(self.fixtextwrap_cb)
        
        self.ignoretltext_cb = QCheckBox("Ignore TL Text")
        self.ignoretltext_cb.setToolTip("Ignore already translated text")
        left_column.addWidget(self.ignoretltext_cb)
        
        left_column.addSpacing(15)
        
        # Main Dialogue Codes
        left_column.addWidget(create_section_label("💬 Main Dialogue (Recommended)"))
        self.code401_cb = QCheckBox("CODE401 - Show Text")
        left_column.addWidget(self.code401_cb)
        
        self.code405_cb = QCheckBox("CODE405 - Show Text (line 4+)")
        left_column.addWidget(self.code405_cb)
        
        self.code102_cb = QCheckBox("CODE102 - Show Choices")
        left_column.addWidget(self.code102_cb)
        
        left_column.addSpacing(15)
        
        # Optional Dialogue Codes
        left_column.addWidget(create_section_label("📝 Optional Dialogue"))
        self.code101_cb = QCheckBox("CODE101 - Show Text (face)")
        left_column.addWidget(self.code101_cb)
        
        self.code408_cb = QCheckBox("CODE408 - Show Text (continuation)")
        self.code408_cb.setToolTip("Can significantly increase costs")
        self.code408_cb.setStyleSheet("QCheckBox { color: #ff9999; }")
        left_column.addWidget(self.code408_cb)
        
        self.code122_cb = QCheckBox("CODE122 - Control Variables")
        left_column.addWidget(self.code122_cb)
        
        left_column.addStretch()
        
        # RIGHT COLUMN  
        right_column = QVBoxLayout()
        right_column.setSpacing(5)
        
        # Plugins / Scripts / Other Codes
        right_column.addWidget(create_section_label("🔧 Plugins / Scripts / Other"))
        
        self.code355655_cb = QCheckBox("CODE355/655 - Script/Plugin Commands (MZ)")
        right_column.addWidget(self.code355655_cb)
        
        self.code357_cb = QCheckBox("CODE357 - Plugin Commands")
        right_column.addWidget(self.code357_cb)
        
        self.code657_cb = QCheckBox("CODE657 - Plugin Commands (Extended)")
        right_column.addWidget(self.code657_cb)
        
        self.code356_cb = QCheckBox("CODE356 - System Settings")
        right_column.addWidget(self.code356_cb)
        
        self.code320_cb = QCheckBox("CODE320 - Change Name")
        right_column.addWidget(self.code320_cb)
        
        self.code324_cb = QCheckBox("CODE324 - Change Nickname")
        right_column.addWidget(self.code324_cb)
        
        self.code325_cb = QCheckBox("CODE325 - Change Profile")
        right_column.addWidget(self.code325_cb)
        
        self.code111_cb = QCheckBox("CODE111 - Conditional Branch")
        right_column.addWidget(self.code111_cb)
        
        self.code108_cb = QCheckBox("CODE108 - Comments")
        right_column.addWidget(self.code108_cb)
        
        right_column.addStretch()
        
        # Add both columns
        columns_layout.addLayout(left_column, 1)
        columns_layout.addLayout(right_column, 1)
        main_layout.addLayout(columns_layout)
        
        # Bottom buttons
        main_layout.addSpacing(12)
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)
        
        self.reset_button = QPushButton("🔄 Reset to Defaults")
        self.reset_button.clicked.connect(self.reset_to_defaults_with_message)
        self.reset_button.setMaximumWidth(180)
        self.reset_button.setMinimumHeight(32)
        
        self.apply_button = QPushButton("✓ Apply Settings")
        self.apply_button.clicked.connect(self.apply_to_module)
        self.apply_button.setMaximumWidth(180)
        self.apply_button.setMinimumHeight(32)
        self.apply_button.setStyleSheet("font-weight: bold;")
        
        button_layout.addWidget(self.reset_button)
        button_layout.addWidget(self.apply_button)
        button_layout.addStretch()
        
        main_layout.addLayout(button_layout)
        self.setLayout(main_layout)
        
    def reset_to_defaults(self):
        """Reset all settings to default values."""
        # Temporarily disconnect signals to avoid multiple apply calls
        self.disconnect_auto_apply()
        
        # Apply default values from the DEFAULT_CONFIG constant
        self.first_line_speakers_cb.setChecked(self.DEFAULT_CONFIG["FIRSTLINESPEAKERS"])
        self.facename101_cb.setChecked(self.DEFAULT_CONFIG["FACENAME101"])
        self.names_cb.setChecked(self.DEFAULT_CONFIG["NAMES"])
        self.brflag_cb.setChecked(self.DEFAULT_CONFIG["BRFLAG"])
        self.fixtextwrap_cb.setChecked(self.DEFAULT_CONFIG["FIXTEXTWRAP"])
        self.ignoretltext_cb.setChecked(self.DEFAULT_CONFIG["IGNORETLTEXT"])
        
        # Main dialogue codes
        self.code401_cb.setChecked(self.DEFAULT_CONFIG["CODE401"])
        self.code405_cb.setChecked(self.DEFAULT_CONFIG["CODE405"])
        self.code102_cb.setChecked(self.DEFAULT_CONFIG["CODE102"])
        
        # Optional codes
        self.code101_cb.setChecked(self.DEFAULT_CONFIG["CODE101"])
        self.code408_cb.setChecked(self.DEFAULT_CONFIG["CODE408"])
        
        # Variable codes
        self.code122_cb.setChecked(self.DEFAULT_CONFIG["CODE122"])
        
        # Plugins / Scripts / Other codes
        self.code355655_cb.setChecked(self.DEFAULT_CONFIG.get("CODE355655", False))
        self.code357_cb.setChecked(self.DEFAULT_CONFIG.get("CODE357", False))
        self.code657_cb.setChecked(self.DEFAULT_CONFIG.get("CODE657", False))
        self.code356_cb.setChecked(self.DEFAULT_CONFIG.get("CODE356", False))
        self.code320_cb.setChecked(self.DEFAULT_CONFIG.get("CODE320", False))
        self.code324_cb.setChecked(self.DEFAULT_CONFIG.get("CODE324", False))
        self.code325_cb.setChecked(self.DEFAULT_CONFIG.get("CODE325", False))
        self.code111_cb.setChecked(self.DEFAULT_CONFIG.get("CODE111", False))
        self.code108_cb.setChecked(self.DEFAULT_CONFIG.get("CODE108", False))
                
        # Reconnect signals and apply changes once
        self.connect_auto_apply()
        self.apply_to_module(show_messages=False)
        
    def reset_to_defaults_with_message(self):
        """Reset to defaults and show confirmation message (for button clicks)."""
        self.reset_to_defaults()
        QMessageBox.information(
            self, 
            "Reset Complete", 
            "All settings have been reset to their default values and applied to the module."
        )
        
    def disconnect_auto_apply(self):
        """Disconnect all checkboxes from auto-apply to prevent multiple calls."""
        try:
            # General settings checkboxes
            self.first_line_speakers_cb.stateChanged.disconnect()
            self.facename101_cb.stateChanged.disconnect()
            self.names_cb.stateChanged.disconnect()
            self.brflag_cb.stateChanged.disconnect()
            self.fixtextwrap_cb.stateChanged.disconnect()
            self.ignoretltext_cb.stateChanged.disconnect()
            
            # Main dialogue codes
            self.code401_cb.stateChanged.disconnect()
            self.code405_cb.stateChanged.disconnect()
            self.code102_cb.stateChanged.disconnect()
            
            # Optional codes
            self.code101_cb.stateChanged.disconnect()
            self.code408_cb.stateChanged.disconnect()
            
            # Variable codes
            self.code122_cb.stateChanged.disconnect()
            
            # Plugins / Scripts / Other codes
            self.code355655_cb.stateChanged.disconnect()
            self.code357_cb.stateChanged.disconnect()
            self.code657_cb.stateChanged.disconnect()
            self.code356_cb.stateChanged.disconnect()
            self.code320_cb.stateChanged.disconnect()
            self.code324_cb.stateChanged.disconnect()
            self.code325_cb.stateChanged.disconnect()
            self.code111_cb.stateChanged.disconnect()
            self.code108_cb.stateChanged.disconnect()
        except TypeError:
            # Ignore if signals are not connected
            pass
        
    def connect_auto_apply(self):
        """Connect all checkboxes to auto-apply changes when modified."""
        # General settings checkboxes
        self.first_line_speakers_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.facename101_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.names_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.brflag_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.fixtextwrap_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.ignoretltext_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        
        # Main dialogue codes
        self.code401_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.code405_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.code102_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        
        # Optional codes
        self.code101_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.code408_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        
        # Variable codes
        self.code122_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        
        # Plugins / Scripts / Other codes
        self.code355655_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.code357_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.code657_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.code356_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.code320_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.code324_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.code325_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.code111_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.code108_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
            
    def get_config(self):
        """Get current configuration as dictionary."""
        config = {
            # General settings
            "FIRSTLINESPEAKERS": self.first_line_speakers_cb.isChecked(),
            "FACENAME101": self.facename101_cb.isChecked(),
            "NAMES": self.names_cb.isChecked(),
            "BRFLAG": self.brflag_cb.isChecked(),
            "FIXTEXTWRAP": self.fixtextwrap_cb.isChecked(),
            "IGNORETLTEXT": self.ignoretltext_cb.isChecked(),
            
            # Main dialogue codes
            "CODE401": self.code401_cb.isChecked(),
            "CODE405": self.code405_cb.isChecked(),
            "CODE102": self.code102_cb.isChecked(),
            
            # Optional codes
            "CODE101": self.code101_cb.isChecked(),
            "CODE408": self.code408_cb.isChecked(),
            
            # Variable codes
            "CODE122": self.code122_cb.isChecked(),
            
            # Plugins / Scripts / Other codes
            "CODE355655": self.code355655_cb.isChecked(),
            "CODE357": self.code357_cb.isChecked(),
            "CODE657": self.code657_cb.isChecked(),
            "CODE356": self.code356_cb.isChecked(),
            "CODE320": self.code320_cb.isChecked(),
            "CODE324": self.code324_cb.isChecked(),
            "CODE325": self.code325_cb.isChecked(),
            "CODE111": self.code111_cb.isChecked(),
            "CODE108": self.code108_cb.isChecked(),
        }
            
        return config
        
    def set_config(self, config):
        """Set configuration from dictionary."""
        # General settings
        self.first_line_speakers_cb.setChecked(config.get("FIRSTLINESPEAKERS", False))
        self.facename101_cb.setChecked(config.get("FACENAME101", False))
        self.names_cb.setChecked(config.get("NAMES", False))
        self.brflag_cb.setChecked(config.get("BRFLAG", False))
        self.fixtextwrap_cb.setChecked(config.get("FIXTEXTWRAP", True))
        self.ignoretltext_cb.setChecked(config.get("IGNORETLTEXT", False))
        
        # Main dialogue codes
        self.code401_cb.setChecked(config.get("CODE401", True))
        self.code405_cb.setChecked(config.get("CODE405", True))
        self.code102_cb.setChecked(config.get("CODE102", True))
        
        # Optional codes
        self.code101_cb.setChecked(config.get("CODE101", False))
        self.code408_cb.setChecked(config.get("CODE408", False))
        
        # Variable codes
        self.code122_cb.setChecked(config.get("CODE122", False))
        
        # Plugins / Scripts / Other codes
        self.code355655_cb.setChecked(config.get("CODE355655", False))
        self.code357_cb.setChecked(config.get("CODE357", False))
        self.code657_cb.setChecked(config.get("CODE657", False))
        self.code356_cb.setChecked(config.get("CODE356", False))
        self.code320_cb.setChecked(config.get("CODE320", False))
        self.code324_cb.setChecked(config.get("CODE324", False))
        self.code325_cb.setChecked(config.get("CODE325", False))
        self.code111_cb.setChecked(config.get("CODE111", False))
        self.code108_cb.setChecked(config.get("CODE108", False))
            
    def load_from_file(self, file_path):
        """Load configuration from file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            self.set_config(config)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load RPG Maker config:\n{str(e)}")
            
    def validate(self):
        """Validate current configuration."""
        warnings = []
        errors = []
        
        # Check if any main dialogue codes are enabled
        main_codes_enabled = (
            self.code401_cb.isChecked() or 
            self.code405_cb.isChecked() or 
            self.code102_cb.isChecked()
        )
        
        if not main_codes_enabled:
            warnings.append("No main dialogue codes are enabled. You may not get any translated content.")
            
        # Check for high-cost options
        if self.code408_cb.isChecked():
            warnings.append("CODE 408 (Comments) is enabled. This can significantly increase translation costs!")
            
        # Check for conflicting options
        if self.brflag_cb.isChecked() and self.fixtextwrap_cb.isChecked():
            warnings.append("Both BR tags and text wrapping are enabled. This might cause formatting issues.")
            
        return len(errors) == 0, warnings, errors
        
    def validate_and_show_report(self):
        """Validate and show a detailed report."""
        is_valid, warnings, errors = self.validate()
        
        report = []
        
        if errors:
            report.append("<b>Errors:</b>")
            for error in errors:
                report.append(f"• {error}")
            report.append("")
            
        if warnings:
            report.append("<b>Warnings:</b>")
            for warning in warnings:
                report.append(f"• {warning}")
            report.append("")
            
        # Add enabled codes summary
        enabled_codes = []
        config = self.get_config()
        for key, value in config.items():
            if key.startswith("CODE") and value:
                enabled_codes.append(key)
                
        if enabled_codes:
            report.append("<b>Enabled Codes:</b>")
            report.append(", ".join(enabled_codes))
        else:
            report.append("<b>No codes enabled!</b>")
            
        if not report:
            report.append("Configuration is valid with no issues.")
            
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Validation Report")
        msg_box.setTextFormat(Qt.RichText)
        msg_box.setText("<br>".join(report))
        
        if errors:
            msg_box.setIcon(QMessageBox.Critical)
        elif warnings:
            msg_box.setIcon(QMessageBox.Warning)
        else:
            msg_box.setIcon(QMessageBox.Information)
            
        msg_box.exec_()
        
        return is_valid
        
    def apply_to_module(self, show_messages=False):
        """Apply current configuration to the correct RPG Maker module (MV/MZ or Ace)."""
        try:
            config = self.get_config()
            # Select module filename based on engine
            module_filename = "rpgmakermvmz.py" if self.engine != "ACE" else "rpgmakerace.py"
            module_path = Path(__file__).parent.parent / "modules" / module_filename
            
            if not module_path.exists():
                if show_messages:
                    QMessageBox.critical(
                        self, 
                        "Error", 
                        "modules/rpgmakermvmz.py not found!\n\n"
                        "Make sure you're running the GUI from the correct directory."
                    )
                return
                
            # Read the current file
            with open(module_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Update each configuration value
            for key, value in config.items():
                # Convert boolean to Python boolean string
                value_str = str(value)
                
                # Find and replace the line with this configuration
                import re
                pattern = rf'^{key}\s*=\s*.*$'
                replacement = f'{key} = {value_str}'
                
                content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
            
            # Write the updated content back
            with open(module_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            # Emit signal for other components (silent)
            self.config_changed.emit()
            
            if show_messages:
                QMessageBox.information(
                    self, 
                    "Success", 
                    f"Configuration has been applied to modules/{module_filename}\n\n"
                    "The module will now use these settings when running translations."
                )
                
        except Exception as e:
            if show_messages:
                QMessageBox.critical(self, "Error", f"Failed to apply configuration:\n{str(e)}")
            # Silent failure for auto-apply - just emit signal anyway
            self.config_changed.emit()
        
    def load_from_module(self):
        """Load configuration from the actual module file based on engine."""
        if not self.config_integration:
            return

        try:
            module_filename = "rpgmakermvmz.py" if self.engine != "ACE" else "rpgmakerace.py"
            module_path = Path("modules") / module_filename
            config = self.config_integration.read_current_config(module_path)
            if config:
                self.set_config(config)
                QMessageBox.information(self, "Success", f"Configuration loaded from {module_filename}")
            else:
                QMessageBox.warning(self, "Warning", f"No configuration found in {module_filename}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load from module:\n{str(e)}")
