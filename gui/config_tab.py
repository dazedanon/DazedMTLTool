"""
Configuration Tab - Handles environment variables and global settings
"""

import os
from pathlib import Path
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, 
    QSpinBox, QDoubleSpinBox, QComboBox, QPushButton, QGroupBox,
    QLabel, QFileDialog, QMessageBox, QScrollArea, QTextEdit,
    QCheckBox, QApplication
)
from PyQt5.QtCore import Qt, pyqtSignal
from dotenv import load_dotenv, set_key


class ConfigTab(QWidget):
    """Configuration tab for managing environment variables and global settings."""
    
    config_changed = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        self.env_file_path = Path(".env")
        self.init_ui()
        self.load_from_env()
        
    def init_ui(self):
        """Initialize the user interface."""
        main_layout = QVBoxLayout()
        
        # Create scroll area
        scroll_area = QScrollArea()
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout()
        
        # API Configuration Group
        api_group = self.create_api_group()
        scroll_layout.addWidget(api_group)
        
        # Translation Settings Group
        translation_group = self.create_translation_group()
        scroll_layout.addWidget(translation_group)
        
        # Performance Settings Group
        performance_group = self.create_performance_group()
        scroll_layout.addWidget(performance_group)
        
        # Text Formatting Group
        formatting_group = self.create_formatting_group()
        scroll_layout.addWidget(formatting_group)
        
        # Custom API Settings Group
        custom_api_group = self.create_custom_api_group()
        scroll_layout.addWidget(custom_api_group)
        
        # UI Settings Group
        ui_group = self.create_ui_settings_group()
        scroll_layout.addWidget(ui_group)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.save_button = QPushButton("Save Configuration")
        self.save_button.clicked.connect(self.save_to_env)
        
        self.load_button = QPushButton("Load from File")
        self.load_button.clicked.connect(self.load_from_file_dialog)
        
        self.reset_button = QPushButton("Reset to Defaults")
        self.reset_button.clicked.connect(self.reset_to_defaults)
        
        button_layout.addWidget(self.save_button)
        button_layout.addWidget(self.load_button)
        button_layout.addWidget(self.reset_button)
        button_layout.addStretch()
        
        scroll_layout.addLayout(button_layout)
        
        scroll_content.setLayout(scroll_layout)
        scroll_area.setWidget(scroll_content)
        scroll_area.setWidgetResizable(True)
        
        main_layout.addWidget(scroll_area)
        self.setLayout(main_layout)
        
    def create_api_group(self):
        """Create API configuration group."""
        group = QGroupBox("API Configuration")
        layout = QFormLayout()
        
        # API URL
        self.api_url_edit = QLineEdit()
        self.api_url_edit.setPlaceholderText("Leave blank for OpenAI API")
        layout.addRow("API URL:", self.api_url_edit)
        
        # API Key
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.api_key_edit.setPlaceholderText("Enter your API key")
        layout.addRow("API Key:", self.api_key_edit)
        
        # Organization
        self.organization_edit = QLineEdit()
        self.organization_edit.setPlaceholderText("Organization key")
        layout.addRow("Organization:", self.organization_edit)
        
        # Model
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.addItems([
            "gpt-3.5-turbo",
            "gpt-3.5-turbo-1106", 
            "gpt-4",
            "gpt-4-1106-preview",
            "gpt-4-turbo",
            "claude-3-sonnet-20240229",
            "claude-3-opus-20240229"
        ])
        layout.addRow("Model:", self.model_combo)
        
        group.setLayout(layout)
        return group
        
    def create_translation_group(self):
        """Create translation settings group."""
        group = QGroupBox("Translation Settings")
        layout = QFormLayout()
        
        # Language
        self.language_combo = QComboBox()
        self.language_combo.addItems([
            "English", "Spanish", "French", "German", "Italian",
            "Portuguese", "Russian", "Chinese", "Korean", "Japanese"
        ])
        layout.addRow("Target Language:", self.language_combo)
        
        # Timeout
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(30, 300)
        self.timeout_spin.setValue(120)
        self.timeout_spin.setSuffix(" seconds")
        layout.addRow("Timeout:", self.timeout_spin)
        
        group.setLayout(layout)
        return group
        
    def create_performance_group(self):
        """Create performance settings group."""
        group = QGroupBox("Performance Settings")
        layout = QFormLayout()
        
        # File Threads
        self.file_threads_spin = QSpinBox()
        self.file_threads_spin.setRange(1, 10)
        self.file_threads_spin.setValue(1)
        layout.addRow("File Threads:", self.file_threads_spin)
        
        # Threads per File
        self.threads_spin = QSpinBox()
        self.threads_spin.setRange(1, 20)
        self.threads_spin.setValue(1)
        layout.addRow("Threads per File:", self.threads_spin)
        
        # Batch Size
        self.batch_size_spin = QSpinBox()
        self.batch_size_spin.setRange(1, 100)
        self.batch_size_spin.setValue(10)
        layout.addRow("Batch Size:", self.batch_size_spin)
        
        # Frequency Penalty
        self.frequency_penalty_spin = QDoubleSpinBox()
        self.frequency_penalty_spin.setRange(0.0, 2.0)
        self.frequency_penalty_spin.setSingleStep(0.1)
        self.frequency_penalty_spin.setValue(0.2)
        layout.addRow("Frequency Penalty:", self.frequency_penalty_spin)
        
        group.setLayout(layout)
        return group
        
    def create_formatting_group(self):
        """Create text formatting settings group."""
        group = QGroupBox("Text Formatting")
        layout = QFormLayout()
        
        # Dialogue Width
        self.width_spin = QSpinBox()
        self.width_spin.setRange(20, 200)
        self.width_spin.setValue(60)
        self.width_spin.setSuffix(" characters")
        layout.addRow("Dialogue Width:", self.width_spin)
        
        # List Width
        self.list_width_spin = QSpinBox()
        self.list_width_spin.setRange(20, 200)
        self.list_width_spin.setValue(100)
        self.list_width_spin.setSuffix(" characters")
        layout.addRow("List Width:", self.list_width_spin)
        
        # Note Width
        self.note_width_spin = QSpinBox()
        self.note_width_spin.setRange(20, 200)
        self.note_width_spin.setValue(75)
        self.note_width_spin.setSuffix(" characters")
        layout.addRow("Note Width:", self.note_width_spin)
        
        group.setLayout(layout)
        return group
        
    def create_custom_api_group(self):
        """Create custom API settings group."""
        group = QGroupBox("Custom API Pricing")
        layout = QFormLayout()
        
        # Input Cost
        self.input_cost_spin = QDoubleSpinBox()
        self.input_cost_spin.setRange(0.0, 1.0)
        self.input_cost_spin.setDecimals(4)
        self.input_cost_spin.setSingleStep(0.0001)
        self.input_cost_spin.setValue(0.002)
        self.input_cost_spin.setSuffix(" per 1K tokens")
        layout.addRow("Input Cost:", self.input_cost_spin)
        
        # Output Cost
        self.output_cost_spin = QDoubleSpinBox()
        self.output_cost_spin.setRange(0.0, 1.0)
        self.output_cost_spin.setDecimals(4)
        self.output_cost_spin.setSingleStep(0.0001)
        self.output_cost_spin.setValue(0.002)
        self.output_cost_spin.setSuffix(" per 1K tokens")
        layout.addRow("Output Cost:", self.output_cost_spin)
        
        group.setLayout(layout)
        return group
        
    def create_ui_settings_group(self):
        """Create UI settings group."""
        group = QGroupBox("User Interface Settings")
        layout = QFormLayout()
        
        # Font Scale
        self.font_scale_spin = QDoubleSpinBox()
        self.font_scale_spin.setRange(0.5, 3.0)
        self.font_scale_spin.setSingleStep(0.1)
        self.font_scale_spin.setValue(1.0)
        self.font_scale_spin.setDecimals(1)
        self.font_scale_spin.setSuffix("x")
        self.font_scale_spin.setToolTip("Scale factor for all fonts in the GUI (1.0 = normal, 1.5 = 150% larger)")
        self.font_scale_spin.valueChanged.connect(self.on_font_scale_changed)
        
        # Font scale presets
        font_layout = QHBoxLayout()
        font_layout.addWidget(self.font_scale_spin)
        
        # Quick preset buttons
        small_btn = QPushButton("Small")
        small_btn.clicked.connect(lambda: self.font_scale_spin.setValue(0.8))
        small_btn.setMaximumWidth(60)
        
        normal_btn = QPushButton("Normal")
        normal_btn.clicked.connect(lambda: self.font_scale_spin.setValue(1.0))
        normal_btn.setMaximumWidth(60)
        
        large_btn = QPushButton("Large")
        large_btn.clicked.connect(lambda: self.font_scale_spin.setValue(1.5))
        large_btn.setMaximumWidth(60)
        
        xlarge_btn = QPushButton("X-Large")
        xlarge_btn.clicked.connect(lambda: self.font_scale_spin.setValue(2.0))
        xlarge_btn.setMaximumWidth(60)
        
        font_layout.addWidget(small_btn)
        font_layout.addWidget(normal_btn)
        font_layout.addWidget(large_btn)
        font_layout.addWidget(xlarge_btn)
        
        layout.addRow("Font Scale:", font_layout)
        
        # DPI Awareness
        self.dpi_aware_cb = QCheckBox("High DPI Scaling")
        self.dpi_aware_cb.setToolTip("Enable automatic scaling for high DPI displays")
        self.dpi_aware_cb.setChecked(True)
        layout.addRow("", self.dpi_aware_cb)
        
        # Theme selection
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["Dark", "Light", "System"])
        self.theme_combo.setCurrentText("Dark")
        layout.addRow("Theme:", self.theme_combo)
        
        # Show font tip
        self.show_font_tip_cb = QCheckBox("Show font size tip on startup")
        self.show_font_tip_cb.setToolTip("Display helpful font sizing information when the GUI starts")
        self.show_font_tip_cb.setChecked(True)
        layout.addRow("", self.show_font_tip_cb)
        
        group.setLayout(layout)
        return group
        
    def on_font_scale_changed(self, value):
        """Handle font scale change."""
        self.config_changed.emit()
        # Apply font scaling immediately
        self.apply_font_scaling(value)
        
    def apply_font_scaling(self, scale_factor):
        """Apply font scaling to the entire application."""
        app = QApplication.instance()
        if app:
            # Get the default font
            font = app.font()
            base_size = 9  # Base font size
            new_size = int(base_size * scale_factor)
            font.setPointSize(new_size)
            app.setFont(font)
            
            # Emit signal to notify other components
            self.config_changed.emit()
        
    def load_from_env(self):
        """Load configuration from .env file."""
        if self.env_file_path.exists():
            load_dotenv(self.env_file_path)
            
        # Load API settings
        self.api_url_edit.setText(os.getenv("api", ""))
        self.api_key_edit.setText(os.getenv("key", ""))
        self.organization_edit.setText(os.getenv("organization", ""))
        self.model_combo.setCurrentText(os.getenv("model", "gpt-4"))
        
        # Load translation settings
        self.language_combo.setCurrentText(os.getenv("language", "English"))
        self.timeout_spin.setValue(int(os.getenv("timeout", "120")))
        
        # Load performance settings
        self.file_threads_spin.setValue(int(os.getenv("fileThreads", "1")))
        self.threads_spin.setValue(int(os.getenv("threads", "1")))
        self.batch_size_spin.setValue(int(os.getenv("batchsize", "10")))
        self.frequency_penalty_spin.setValue(float(os.getenv("frequency_penalty", "0.2")))
        
        # Load formatting settings
        self.width_spin.setValue(int(os.getenv("width", "60")))
        self.list_width_spin.setValue(int(os.getenv("listWidth", "100")))
        self.note_width_spin.setValue(int(os.getenv("noteWidth", "75")))
        
        # Load custom API settings
        self.input_cost_spin.setValue(float(os.getenv("input_cost", "0.002")))
        self.output_cost_spin.setValue(float(os.getenv("output_cost", "0.002")))
        
        # Load UI settings
        self.font_scale_spin.setValue(float(os.getenv("font_scale", "1.0")))
        self.dpi_aware_cb.setChecked(os.getenv("dpi_aware", "true").lower() == "true")
        self.theme_combo.setCurrentText(os.getenv("theme", "Dark"))
        self.show_font_tip_cb.setChecked(os.getenv("show_font_tip", "true").lower() == "true")
        
        # Apply font scaling
        self.apply_font_scaling(self.font_scale_spin.value())
        
    def save_to_env(self):
        """Save configuration to .env file."""
        try:
            # Ensure .env file exists
            if not self.env_file_path.exists():
                self.env_file_path.touch()
                
            # Save API settings
            set_key(self.env_file_path, "api", self.api_url_edit.text())
            set_key(self.env_file_path, "key", self.api_key_edit.text())
            set_key(self.env_file_path, "organization", self.organization_edit.text())
            set_key(self.env_file_path, "model", self.model_combo.currentText())
            
            # Save translation settings
            set_key(self.env_file_path, "language", self.language_combo.currentText())
            set_key(self.env_file_path, "timeout", str(self.timeout_spin.value()))
            
            # Save performance settings
            set_key(self.env_file_path, "fileThreads", str(self.file_threads_spin.value()))
            set_key(self.env_file_path, "threads", str(self.threads_spin.value()))
            set_key(self.env_file_path, "batchsize", str(self.batch_size_spin.value()))
            set_key(self.env_file_path, "frequency_penalty", str(self.frequency_penalty_spin.value()))
            
            # Save formatting settings
            set_key(self.env_file_path, "width", str(self.width_spin.value()))
            set_key(self.env_file_path, "listWidth", str(self.list_width_spin.value()))
            set_key(self.env_file_path, "noteWidth", str(self.note_width_spin.value()))
            
            # Save custom API settings
            set_key(self.env_file_path, "input_cost", str(self.input_cost_spin.value()))
            set_key(self.env_file_path, "output_cost", str(self.output_cost_spin.value()))
            
            # Save UI settings
            set_key(self.env_file_path, "font_scale", str(self.font_scale_spin.value()))
            set_key(self.env_file_path, "dpi_aware", str(self.dpi_aware_cb.isChecked()).lower())
            set_key(self.env_file_path, "theme", self.theme_combo.currentText())
            set_key(self.env_file_path, "show_font_tip", str(self.show_font_tip_cb.isChecked()).lower())
            
            QMessageBox.information(self, "Success", "Configuration saved successfully!")
            self.config_changed.emit()
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save configuration:\n{str(e)}")
            
    def load_from_file_dialog(self):
        """Load configuration from a file via dialog."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Load Configuration", "", "Environment Files (*.env);;All Files (*)"
        )
        
        if file_path:
            self.load_from_file(file_path)
            
    def load_from_file(self, file_path):
        """Load configuration from a specific file."""
        try:
            load_dotenv(file_path, override=True)
            self.load_from_env()
            QMessageBox.information(self, "Success", f"Configuration loaded from {Path(file_path).name}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load configuration:\n{str(e)}")
            
    def reset_to_defaults(self):
        """Reset all settings to default values."""
        # API settings
        self.api_url_edit.clear()
        self.api_key_edit.clear()
        self.organization_edit.clear()
        self.model_combo.setCurrentText("gpt-4")
        
        # Translation settings
        self.language_combo.setCurrentText("English")
        self.timeout_spin.setValue(120)
        
        # Performance settings
        self.file_threads_spin.setValue(1)
        self.threads_spin.setValue(1)
        self.batch_size_spin.setValue(10)
        self.frequency_penalty_spin.setValue(0.2)
        
        # Formatting settings
        self.width_spin.setValue(60)
        self.list_width_spin.setValue(100)
        self.note_width_spin.setValue(75)
        
        # Custom API settings
        self.input_cost_spin.setValue(0.002)
        self.output_cost_spin.setValue(0.002)
        
        # UI settings
        self.font_scale_spin.setValue(1.0)
        self.dpi_aware_cb.setChecked(True)
        self.theme_combo.setCurrentText("Dark")
        self.show_font_tip_cb.setChecked(True)
        
        # Apply font scaling
        self.apply_font_scaling(1.0)
        
    def get_config(self):
        """Get current configuration as dictionary."""
        return {
            "api": self.api_url_edit.text(),
            "key": self.api_key_edit.text(),
            "organization": self.organization_edit.text(),
            "model": self.model_combo.currentText(),
            "language": self.language_combo.currentText(),
            "timeout": self.timeout_spin.value(),
            "fileThreads": self.file_threads_spin.value(),
            "threads": self.threads_spin.value(),
            "batchsize": self.batch_size_spin.value(),
            "frequency_penalty": self.frequency_penalty_spin.value(),
            "width": self.width_spin.value(),
            "listWidth": self.list_width_spin.value(),
            "noteWidth": self.note_width_spin.value(),
            "input_cost": self.input_cost_spin.value(),
            "output_cost": self.output_cost_spin.value(),
            "font_scale": self.font_scale_spin.value(),
            "dpi_aware": self.dpi_aware_cb.isChecked(),
            "theme": self.theme_combo.currentText(),
            "show_font_tip": self.show_font_tip_cb.isChecked()
        }
        
    def validate(self):
        """Validate the current configuration."""
        errors = []
        
        # Check required fields
        if not self.api_key_edit.text().strip():
            errors.append("API Key is required")
            
        if not self.model_combo.currentText().strip():
            errors.append("Model is required")
            
        # Check numeric ranges
        if self.timeout_spin.value() < 30:
            errors.append("Timeout should be at least 30 seconds")
            
        if self.threads_spin.value() > 10 and "gpt-4" in self.model_combo.currentText().lower():
            errors.append("Too many threads for GPT-4 - recommended: 1-2")
            
        if errors:
            QMessageBox.warning(self, "Validation Errors", "\n".join(errors))
            return False
            
        return True
