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
    
    config_changed = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        self.config_integration = ConfigIntegration() if ConfigIntegration else None
        self.init_ui()
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
        self.reset_button.clicked.connect(self.reset_to_defaults)
        
        self.validate_button = QPushButton("Validate Settings")
        self.validate_button.clicked.connect(self.validate_and_show_report)
        
        self.apply_button = QPushButton("Apply to Module")
        self.apply_button.clicked.connect(self.apply_to_module)
        self.apply_button.setToolTip("Apply current settings to the rpgmakermvmz.py module file")
        
        button_layout.addWidget(self.reset_button)
        button_layout.addWidget(self.validate_button)
        button_layout.addWidget(self.apply_button)
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
        # General config defaults
        self.first_line_speakers_cb.setChecked(False)
        self.facename_101_cb.setChecked(False)
        self.names_cb.setChecked(False)
        self.br_flag_cb.setChecked(False)
        self.fix_textwrap_cb.setChecked(True)
        self.ignore_tl_text_cb.setChecked(False)
        
        # Main dialogue codes (enabled by default)
        self.code_401_cb.setChecked(True)
        self.code_405_cb.setChecked(True)
        self.code_102_cb.setChecked(True)
        
        # Optional codes (disabled by default)
        self.code_101_cb.setChecked(False)
        self.code_408_cb.setChecked(False)
        
        # Variable codes (disabled by default)
        self.code_122_cb.setChecked(False)
        
        # Other codes (all disabled by default)
        for cb in self.other_code_checkboxes.values():
            cb.setChecked(False)
            
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
        
    def apply_to_module(self):
        """Apply current configuration to the rpgmakermvmz.py module."""
        if not self.config_integration:
            QMessageBox.warning(self, "Warning", "Configuration integration not available")
            return
            
        try:
            config = self.get_config()
            success = self.config_integration.update_rpgmaker_config(config)
            
            if success:
                QMessageBox.information(
                    self, 
                    "Success", 
                    "Configuration has been applied to modules/rpgmakermvmz.py\n\n"
                    "The module will now use these settings when running translations."
                )
            else:
                QMessageBox.warning(self, "Warning", "Failed to apply configuration to module")
                
        except FileNotFoundError:
            QMessageBox.critical(
                self, 
                "Error", 
                "modules/rpgmakermvmz.py not found!\n\n"
                "Make sure you're running the GUI from the correct directory."
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to apply configuration:\n{str(e)}")
        
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
