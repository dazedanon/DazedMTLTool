"""
RPG Maker MV/MZ Tab - Configuration for RPG Maker specific settings
"""

import json
from pathlib import Path
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QCheckBox, 
    QPushButton, QGroupBox, QLabel, QMessageBox, QScrollArea,
    QTextEdit, QSpinBox, QFrame
)
from PyQt5.QtCore import Qt, pyqtSignal

try:
    from .config_integration import ConfigIntegration
except ImportError:
    # Fallback if config_integration is not available
    ConfigIntegration = None


class RPGMakerTab(QWidget):
    """RPG Maker MV/MZ configuration tab."""
    
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
    
    def __init__(self):
        super().__init__()
        self.config_integration = ConfigIntegration() if ConfigIntegration else None
        self.init_ui()
        self.connect_auto_apply()  # Connect auto-apply before setting defaults
        self.reset_to_defaults()
        
    def init_ui(self):
        """Initialize the user interface."""
        main_layout = QVBoxLayout()
        
        # Create scroll area
        scroll_area = QScrollArea()
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout()
        
        # Title and description
        title_label = QLabel("RPG Maker MV/MZ Translation Settings")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #007acc;")
        scroll_layout.addWidget(title_label)
        
        description_label = QLabel(
            "Configure which RPG Maker event codes to translate and additional options. "
            "Each code represents a specific type of game content."
        )
        description_label.setWordWrap(True)
        description_label.setStyleSheet("color: #cccccc; margin-bottom: 10px;")
        scroll_layout.addWidget(description_label)
        
        # General Config Group
        general_group = self.create_general_config_group()
        scroll_layout.addWidget(general_group)
        
        # Main Dialogue Codes Group
        dialogue_group = self.create_dialogue_codes_group()
        scroll_layout.addWidget(dialogue_group)
        
        # Optional Codes Group
        optional_group = self.create_optional_codes_group()
        scroll_layout.addWidget(optional_group)
        
        # Variable Codes Group
        variable_group = self.create_variable_codes_group()
        scroll_layout.addWidget(variable_group)
        
        # Other Codes Group
        other_group = self.create_other_codes_group()
        scroll_layout.addWidget(other_group)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.reset_button = QPushButton("Reset to Defaults")
        self.reset_button.clicked.connect(self.reset_to_defaults_with_message)
        
        self.validate_button = QPushButton("Validate Settings")
        self.validate_button.clicked.connect(self.validate_and_show_report)
        
        button_layout.addWidget(self.reset_button)
        button_layout.addWidget(self.validate_button)
        button_layout.addStretch()
        
        scroll_layout.addLayout(button_layout)
        
        # Add separator
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        scroll_layout.addWidget(separator)
        
        # Add note about performance
        note_text = QTextEdit()
        note_text.setMaximumHeight(100)
        note_text.setReadOnly(True)
        note_text.setHtml("""
        <b>Performance Notes:</b><br>
        • Enable only the codes you need to reduce translation time and costs<br>
        • CODE408 can significantly increase costs as it translates comments<br>
        • Main dialogue codes (401, 405, 102) are typically required for story content<br>
        • Test with a small file first to verify settings work correctly
        """)
        scroll_layout.addWidget(note_text)
        
        scroll_content.setLayout(scroll_layout)
        scroll_area.setWidget(scroll_content)
        scroll_area.setWidgetResizable(True)
        
        main_layout.addWidget(scroll_area)
        self.setLayout(main_layout)
        
    def create_general_config_group(self):
        """Create general configuration group."""
        group = QGroupBox("General Configuration")
        layout = QVBoxLayout()
        
        # FIRSTLINESPEAKERS
        self.first_line_speakers_cb = QCheckBox("First Line Speakers")
        self.first_line_speakers_cb.setToolTip(
            "If the first line of event code 401 contains a speaker name, enable this option"
        )
        layout.addWidget(self.first_line_speakers_cb)
        
        # FACENAME101
        self.facename_101_cb = QCheckBox("Find Speakers in 101 Codes based on Face Name")
        self.facename_101_cb.setToolTip(
            "Use character face names to identify speakers in event code 101"
        )
        layout.addWidget(self.facename_101_cb)
        
        # NAMES
        self.names_cb = QCheckBox("Output Character Names List")
        self.names_cb.setToolTip(
            "Generate a list of all character names found during translation"
        )
        layout.addWidget(self.names_cb)
        
        # BRFLAG
        self.br_flag_cb = QCheckBox("Use <br> Tags")
        self.br_flag_cb.setToolTip(
            "Use <br> HTML tags instead of newlines for line breaks"
        )
        layout.addWidget(self.br_flag_cb)
        
        # FIXTEXTWRAP
        self.fix_textwrap_cb = QCheckBox("Fix Text Wrapping")
        self.fix_textwrap_cb.setToolTip(
            "Automatically fix text wrapping for better display"
        )
        layout.addWidget(self.fix_textwrap_cb)
        
        # IGNORETLTEXT
        self.ignore_tl_text_cb = QCheckBox("Ignore Already Translated Text")
        self.ignore_tl_text_cb.setToolTip(
            "Skip text that appears to already be translated"
        )
        layout.addWidget(self.ignore_tl_text_cb)
        
        group.setLayout(layout)
        return group
        
    def create_dialogue_codes_group(self):
        """Create dialogue codes group."""
        group = QGroupBox("Main Dialogue Codes (Recommended)")
        layout = QVBoxLayout()
        
        # CODE401
        self.code_401_cb = QCheckBox("CODE 401 - Show Text")
        self.code_401_cb.setToolTip(
            "Translate dialogue text displayed in message windows. Essential for story content."
        )
        layout.addWidget(self.code_401_cb)
        
        # CODE405  
        self.code_405_cb = QCheckBox("CODE 405 - Show Text (Scrolling)")
        self.code_405_cb.setToolTip(
            "Translate scrolling text messages. Used for longer dialogue passages."
        )
        layout.addWidget(self.code_405_cb)
        
        # CODE102
        self.code_102_cb = QCheckBox("CODE 102 - Show Choices")
        self.code_102_cb.setToolTip(
            "Translate choice options presented to the player."
        )
        layout.addWidget(self.code_102_cb)
        
        group.setLayout(layout)
        return group
        
    def create_optional_codes_group(self):
        """Create optional codes group."""
        group = QGroupBox("Optional Codes")
        layout = QVBoxLayout()
        
        # CODE101
        self.code_101_cb = QCheckBox("CODE 101 - Character Names")
        self.code_101_cb.setToolTip(
            "Translate character names. Enable only when names are stored in code 101."
        )
        layout.addWidget(self.code_101_cb)
        
        # CODE408
        self.code_408_cb = QCheckBox("CODE 408 - Comments (Warning: High Cost)")
        self.code_408_cb.setToolTip(
            "Translate comment text. WARNING: This can significantly increase translation costs!"
        )
        self.code_408_cb.setStyleSheet("QCheckBox { color: #ff6b6b; }")
        layout.addWidget(self.code_408_cb)
        
        group.setLayout(layout)
        return group
        
    def create_variable_codes_group(self):
        """Create variable codes group."""
        group = QGroupBox("Variable Codes")
        layout = QVBoxLayout()
        
        # CODE122
        self.code_122_cb = QCheckBox("CODE 122 - Control Variables")
        self.code_122_cb.setToolTip(
            "Translate text stored in game variables."
        )
        layout.addWidget(self.code_122_cb)
        
        group.setLayout(layout)
        return group
        
    def create_other_codes_group(self):
        """Create other codes group."""
        group = QGroupBox("Other Event Codes")
        layout = QVBoxLayout()
        
        codes_info = [
            ("355655", "Scripts", "Translate text within script commands"),
            ("357", "Picture Text", "Translate text displayed on pictures"),
            ("657", "Picture Text Extended", "Extended picture text translation"),
            ("356", "Plugin Commands", "Translate plugin command parameters"),
            ("320", "Change Name Input", "Translate name input prompts"),
            ("324", "Change Nickname", "Translate nickname changes"),
            ("111", "Conditional Branch", "Translate conditional text"),
            ("108", "Comments", "Translate comment blocks")
        ]
        
        self.other_code_checkboxes = {}
        
        for code, name, tooltip in codes_info:
            cb = QCheckBox(f"CODE {code} - {name}")
            cb.setToolTip(tooltip)
            layout.addWidget(cb)
            self.other_code_checkboxes[code] = cb
        
        group.setLayout(layout)
        return group
        
    def reset_to_defaults(self):
        """Reset all settings to default values."""
        # Temporarily disconnect signals to avoid multiple apply calls
        self.disconnect_auto_apply()
        
        # Apply default values from the DEFAULT_CONFIG constant
        self.first_line_speakers_cb.setChecked(self.DEFAULT_CONFIG["FIRSTLINESPEAKERS"])
        self.facename_101_cb.setChecked(self.DEFAULT_CONFIG["FACENAME101"])
        self.names_cb.setChecked(self.DEFAULT_CONFIG["NAMES"])
        self.br_flag_cb.setChecked(self.DEFAULT_CONFIG["BRFLAG"])
        self.fix_textwrap_cb.setChecked(self.DEFAULT_CONFIG["FIXTEXTWRAP"])
        self.ignore_tl_text_cb.setChecked(self.DEFAULT_CONFIG["IGNORETLTEXT"])
        
        # Main dialogue codes
        self.code_401_cb.setChecked(self.DEFAULT_CONFIG["CODE401"])
        self.code_405_cb.setChecked(self.DEFAULT_CONFIG["CODE405"])
        self.code_102_cb.setChecked(self.DEFAULT_CONFIG["CODE102"])
        
        # Optional codes
        self.code_101_cb.setChecked(self.DEFAULT_CONFIG["CODE101"])
        self.code_408_cb.setChecked(self.DEFAULT_CONFIG["CODE408"])
        
        # Variable codes
        self.code_122_cb.setChecked(self.DEFAULT_CONFIG["CODE122"])
        
        # Other codes - apply defaults from the constant
        for code, cb in self.other_code_checkboxes.items():
            default_key = f"CODE{code}"
            if default_key in self.DEFAULT_CONFIG:
                cb.setChecked(self.DEFAULT_CONFIG[default_key])
            else:
                cb.setChecked(False)  # Fallback to False if not in defaults
                
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
            self.facename_101_cb.stateChanged.disconnect()
            self.names_cb.stateChanged.disconnect()
            self.br_flag_cb.stateChanged.disconnect()
            self.fix_textwrap_cb.stateChanged.disconnect()
            self.ignore_tl_text_cb.stateChanged.disconnect()
            
            # Main dialogue codes
            self.code_401_cb.stateChanged.disconnect()
            self.code_405_cb.stateChanged.disconnect()
            self.code_102_cb.stateChanged.disconnect()
            
            # Optional codes
            self.code_101_cb.stateChanged.disconnect()
            self.code_408_cb.stateChanged.disconnect()
            
            # Variable codes
            self.code_122_cb.stateChanged.disconnect()
            
            # Other codes
            for cb in self.other_code_checkboxes.values():
                cb.stateChanged.disconnect()
        except TypeError:
            # Ignore if signals are not connected
            pass
        
    def connect_auto_apply(self):
        """Connect all checkboxes to auto-apply changes when modified."""
        # General settings checkboxes
        self.first_line_speakers_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.facename_101_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.names_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.br_flag_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.fix_textwrap_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.ignore_tl_text_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        
        # Main dialogue codes
        self.code_401_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.code_405_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.code_102_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        
        # Optional codes
        self.code_101_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.code_408_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        
        # Variable codes
        self.code_122_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        
        # Other codes
        for cb in self.other_code_checkboxes.values():
            cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
            
    def get_config(self):
        """Get current configuration as dictionary."""
        config = {
            # General settings
            "FIRSTLINESPEAKERS": self.first_line_speakers_cb.isChecked(),
            "FACENAME101": self.facename_101_cb.isChecked(),
            "NAMES": self.names_cb.isChecked(),
            "BRFLAG": self.br_flag_cb.isChecked(),
            "FIXTEXTWRAP": self.fix_textwrap_cb.isChecked(),
            "IGNORETLTEXT": self.ignore_tl_text_cb.isChecked(),
            
            # Main dialogue codes
            "CODE401": self.code_401_cb.isChecked(),
            "CODE405": self.code_405_cb.isChecked(),
            "CODE102": self.code_102_cb.isChecked(),
            
            # Optional codes
            "CODE101": self.code_101_cb.isChecked(),
            "CODE408": self.code_408_cb.isChecked(),
            
            # Variable codes
            "CODE122": self.code_122_cb.isChecked(),
        }
        
        # Other codes
        for code, cb in self.other_code_checkboxes.items():
            config[f"CODE{code}"] = cb.isChecked()
            
        return config
        
    def set_config(self, config):
        """Set configuration from dictionary."""
        # General settings
        self.first_line_speakers_cb.setChecked(config.get("FIRSTLINESPEAKERS", False))
        self.facename_101_cb.setChecked(config.get("FACENAME101", False))
        self.names_cb.setChecked(config.get("NAMES", False))
        self.br_flag_cb.setChecked(config.get("BRFLAG", False))
        self.fix_textwrap_cb.setChecked(config.get("FIXTEXTWRAP", True))
        self.ignore_tl_text_cb.setChecked(config.get("IGNORETLTEXT", False))
        
        # Main dialogue codes
        self.code_401_cb.setChecked(config.get("CODE401", True))
        self.code_405_cb.setChecked(config.get("CODE405", True))
        self.code_102_cb.setChecked(config.get("CODE102", True))
        
        # Optional codes
        self.code_101_cb.setChecked(config.get("CODE101", False))
        self.code_408_cb.setChecked(config.get("CODE408", False))
        
        # Variable codes
        self.code_122_cb.setChecked(config.get("CODE122", False))
        
        # Other codes
        for code, cb in self.other_code_checkboxes.items():
            cb.setChecked(config.get(f"CODE{code}", False))
            
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
            self.code_401_cb.isChecked() or 
            self.code_405_cb.isChecked() or 
            self.code_102_cb.isChecked()
        )
        
        if not main_codes_enabled:
            warnings.append("No main dialogue codes are enabled. You may not get any translated content.")
            
        # Check for high-cost options
        if self.code_408_cb.isChecked():
            warnings.append("CODE 408 (Comments) is enabled. This can significantly increase translation costs!")
            
        # Check for conflicting options
        if self.br_flag_cb.isChecked() and self.fix_textwrap_cb.isChecked():
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
        """Apply current configuration to the rpgmakermvmz.py module."""
        try:
            config = self.get_config()
            
            # Direct file modification approach (completely silent)
            module_path = Path(__file__).parent.parent / "modules" / "rpgmakermvmz.py"
            
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
                    "Configuration has been applied to modules/rpgmakermvmz.py\n\n"
                    "The module will now use these settings when running translations."
                )
                
        except Exception as e:
            if show_messages:
                QMessageBox.critical(self, "Error", f"Failed to apply configuration:\n{str(e)}")
            # Silent failure for auto-apply - just emit signal anyway
            self.config_changed.emit()
        
    def load_from_module(self):
        """Load configuration from the actual module file."""
        if not self.config_integration:
            return
            
        try:
            config = self.config_integration.read_current_config()
            if config:
                self.set_config(config)
                QMessageBox.information(self, "Success", "Configuration loaded from module file")
            else:
                QMessageBox.warning(self, "Warning", "No configuration found in module file")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load from module:\n{str(e)}")
