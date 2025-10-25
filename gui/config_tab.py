"""
Configuration Tab - Handles environment variables, global settings, and engine configurations
"""

import os
from pathlib import Path
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, 
    QSpinBox, QDoubleSpinBox, QComboBox, QPushButton, QGroupBox,
    QLabel, QFileDialog, QMessageBox, QScrollArea, QTextEdit,
    QCheckBox, QApplication, QTabWidget, QFrame
)
from PyQt5.QtCore import Qt, pyqtSignal
from dotenv import load_dotenv, set_key

from gui.rpgmaker_tab import RPGMakerTab
from gui.wolf_tab import WolfTab


def create_section_header(title):
    """Create a clean section header without boxes."""
    label = QLabel(title)
    label.setStyleSheet("""
        QLabel {
            font-size: 13px;
            font-weight: bold;
            color: #007acc;
            padding: 8px 0px 5px 0px;
            background-color: transparent;
        }
    """)
    return label

def create_horizontal_line():
    """Create a horizontal separator line."""
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setFrameShadow(QFrame.Sunken)
    line.setStyleSheet("QFrame { color: #555555; margin: 5px 0px; }")
    return line


class ConfigTab(QWidget):
    """Configuration tab for managing environment variables, global settings, and engine configs."""
    
    config_changed = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        self.env_file_path = Path(".env")
        self.init_ui()
        self.load_from_env()
        
    def init_ui(self):
        """Initialize the user interface with tabs for different config categories."""
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # Create tab widget for different configuration categories
        self.config_tabs = QTabWidget()
        
        # Tab 1: API & Translation Settings
        api_tab = self.create_api_translation_tab()
        self.config_tabs.addTab(api_tab, "API & Translation")
        
        # Tab 2: Performance & Formatting
        perf_tab = self.create_performance_formatting_tab()
        self.config_tabs.addTab(perf_tab, "Performance & Format")
        
        # Tab 3: RPG Maker MV/MZ Engine
        self.mvmz_tab = RPGMakerTab("MVMZ")
        self.config_tabs.addTab(self.mvmz_tab, "RPG Maker MV/MZ")
        
        # Tab 4: RPG Maker Ace Engine
        self.ace_tab = RPGMakerTab("ACE")
        self.config_tabs.addTab(self.ace_tab, "RPG Maker Ace")
        
        # Tab 5: Wolf RPG Engine
        self.wolf_tab = WolfTab()
        self.config_tabs.addTab(self.wolf_tab, "Wolf RPG")
        
        main_layout.addWidget(self.config_tabs)
        
        # Bottom buttons row
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)
        
        self.save_button = QPushButton("💾 Save Configuration")
        self.save_button.clicked.connect(self.save_to_env)
        self.save_button.setMinimumHeight(35)
        
        self.load_button = QPushButton("📂 Load from File")
        self.load_button.clicked.connect(self.load_from_file_dialog)
        self.load_button.setMinimumHeight(35)
        
        self.reset_button = QPushButton("🔄 Reset to Defaults")
        self.reset_button.clicked.connect(self.reset_to_defaults)
        self.reset_button.setMinimumHeight(35)
        
        button_layout.addWidget(self.save_button)
        button_layout.addWidget(self.load_button)
        button_layout.addWidget(self.reset_button)
        button_layout.addStretch()
        
        main_layout.addLayout(button_layout)
        self.setLayout(main_layout)
    
    def create_api_translation_tab(self):
        """Create compact API and translation settings tab."""
        widget = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        
        content = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(5)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # API Configuration Section
        layout.addWidget(create_section_header("🔑 API Configuration"))
        api_form = QFormLayout()
        api_form.setSpacing(5)
        api_form.setContentsMargins(0, 0, 0, 10)
        
        self.api_url_edit = QLineEdit()
        self.api_url_edit.setPlaceholderText("Leave blank for OpenAI API")
        api_form.addRow("API URL:", self.api_url_edit)
        
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.api_key_edit.setPlaceholderText("Enter your API key")
        api_form.addRow("API Key:", self.api_key_edit)
        
        self.organization_edit = QLineEdit()
        self.organization_edit.setPlaceholderText("Optional organization key")
        api_form.addRow("Organization:", self.organization_edit)
        
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.addItems([
            "gpt-4.1-mini", "gpt-4.1", "gpt-5",
            "deepseek-chat", "claude-3-sonnet-20240229",
            "gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-pro"
        ])
        api_form.addRow("Model:", self.model_combo)
        
        layout.addLayout(api_form)
        layout.addWidget(create_horizontal_line())
        
        # Translation Settings Section
        layout.addWidget(create_section_header("🌐 Translation Settings"))
        trans_form = QFormLayout()
        trans_form.setSpacing(5)
        trans_form.setContentsMargins(0, 0, 0, 10)
        
        self.language_combo = QComboBox()
        self.language_combo.addItems([
            "English", "Spanish", "French", "German", "Italian",
            "Portuguese", "Russian", "Chinese", "Korean", "Japanese"
        ])
        trans_form.addRow("Target Language:", self.language_combo)
        
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(30, 300)
        self.timeout_spin.setValue(120)
        self.timeout_spin.setSuffix(" sec")
        trans_form.addRow("Timeout:", self.timeout_spin)
        
        layout.addLayout(trans_form)
        layout.addWidget(create_horizontal_line())
        
        # UI Settings Section
        layout.addWidget(create_section_header("🎨 UI Settings"))
        ui_form = QFormLayout()
        ui_form.setSpacing(5)
        ui_form.setContentsMargins(0, 0, 0, 10)
        
        font_layout = QHBoxLayout()
        self.font_scale_spin = QDoubleSpinBox()
        self.font_scale_spin.setRange(0.5, 3.0)
        self.font_scale_spin.setSingleStep(0.1)
        self.font_scale_spin.setValue(1.0)
        self.font_scale_spin.setDecimals(1)
        self.font_scale_spin.setSuffix("x")
        self.font_scale_spin.valueChanged.connect(self.on_font_scale_changed)
        font_layout.addWidget(self.font_scale_spin)
        
        # Quick preset buttons (smaller)
        for label, value in [("S", 0.8), ("M", 1.0), ("L", 1.5), ("XL", 2.0)]:
            btn = QPushButton(label)
            btn.clicked.connect(lambda checked, v=value: self.font_scale_spin.setValue(v))
            btn.setMaximumWidth(40)
            font_layout.addWidget(btn)
        
        ui_form.addRow("Font Scale:", font_layout)
        
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["Dark", "Light", "System"])
        self.theme_combo.setCurrentText("Dark")
        ui_form.addRow("Theme:", self.theme_combo)
        
        layout.addLayout(ui_form)
        layout.addStretch()
        
        content.setLayout(layout)
        scroll.setWidget(content)
        
        wrapper = QVBoxLayout()
        wrapper.setContentsMargins(0, 0, 0, 0)
        wrapper.addWidget(scroll)
        widget.setLayout(wrapper)
        return widget
    
    def create_performance_formatting_tab(self):
        """Create compact performance and formatting settings tab."""
        widget = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        
        content = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(5)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Performance Settings Section
        layout.addWidget(create_section_header("⚡ Performance Settings"))
        perf_form = QFormLayout()
        perf_form.setSpacing(5)
        perf_form.setContentsMargins(0, 0, 0, 10)
        
        self.file_threads_spin = QSpinBox()
        self.file_threads_spin.setRange(1, 10)
        self.file_threads_spin.setValue(1)
        perf_form.addRow("File Threads:", self.file_threads_spin)
        
        self.threads_spin = QSpinBox()
        self.threads_spin.setRange(1, 20)
        self.threads_spin.setValue(1)
        perf_form.addRow("Threads per File:", self.threads_spin)
        
        self.batch_size_spin = QSpinBox()
        self.batch_size_spin.setRange(1, 100)
        self.batch_size_spin.setValue(30)
        perf_form.addRow("Batch Size:", self.batch_size_spin)
        
        self.frequency_penalty_spin = QDoubleSpinBox()
        self.frequency_penalty_spin.setRange(0.0, 2.0)
        self.frequency_penalty_spin.setSingleStep(0.05)
        self.frequency_penalty_spin.setValue(0.05)
        perf_form.addRow("Frequency Penalty:", self.frequency_penalty_spin)
        
        layout.addLayout(perf_form)
        layout.addWidget(create_horizontal_line())
        
        # Text Formatting Section
        layout.addWidget(create_section_header("📝 Text Formatting"))
        format_form = QFormLayout()
        format_form.setSpacing(5)
        format_form.setContentsMargins(0, 0, 0, 10)
        
        self.width_spin = QSpinBox()
        self.width_spin.setRange(20, 200)
        self.width_spin.setValue(60)
        self.width_spin.setSuffix(" chars")
        format_form.addRow("Dialogue Width:", self.width_spin)
        
        self.list_width_spin = QSpinBox()
        self.list_width_spin.setRange(20, 200)
        self.list_width_spin.setValue(100)
        self.list_width_spin.setSuffix(" chars")
        format_form.addRow("List Width:", self.list_width_spin)
        
        self.note_width_spin = QSpinBox()
        self.note_width_spin.setRange(20, 200)
        self.note_width_spin.setValue(75)
        self.note_width_spin.setSuffix(" chars")
        format_form.addRow("Note Width:", self.note_width_spin)
        
        layout.addLayout(format_form)
        layout.addWidget(create_horizontal_line())
        
        # Custom API Pricing Section
        layout.addWidget(create_section_header("💰 Custom API Pricing"))
        price_form = QFormLayout()
        price_form.setSpacing(5)
        price_form.setContentsMargins(0, 0, 0, 10)
        
        self.input_cost_spin = QDoubleSpinBox()
        self.input_cost_spin.setRange(0.0, 100.0)
        self.input_cost_spin.setDecimals(4)
        self.input_cost_spin.setSingleStep(0.1)
        self.input_cost_spin.setValue(2.0)
        self.input_cost_spin.setSuffix(" per 1M tokens")
        price_form.addRow("Input Cost:", self.input_cost_spin)
        
        self.output_cost_spin = QDoubleSpinBox()
        self.output_cost_spin.setRange(0.0, 100.0)
        self.output_cost_spin.setDecimals(4)
        self.output_cost_spin.setSingleStep(0.1)
        self.output_cost_spin.setValue(8.0)
        self.output_cost_spin.setSuffix(" per 1M tokens")
        price_form.addRow("Output Cost:", self.output_cost_spin)
        
        layout.addLayout(price_form)
        layout.addStretch()
        
        content.setLayout(layout)
        scroll.setWidget(content)
        
        wrapper = QVBoxLayout()
        wrapper.setContentsMargins(0, 0, 0, 0)
        wrapper.addWidget(scroll)
        widget.setLayout(wrapper)
        return widget
        
    def load_from_env(self):
        """Load configuration from .env file."""
        if self.env_file_path.exists():
            load_dotenv(self.env_file_path)
            
        # Load API settings
        self.api_url_edit.setText(os.getenv("api", ""))
        self.api_key_edit.setText(os.getenv("key", ""))
        self.organization_edit.setText(os.getenv("organization", ""))
        self.model_combo.setCurrentText(os.getenv("model", "gpt-4.1"))
        
        # Load translation settings
        self.language_combo.setCurrentText(os.getenv("language", "English"))
        self.timeout_spin.setValue(int(os.getenv("timeout", "120")))
        
        # Load performance settings
        self.file_threads_spin.setValue(int(os.getenv("fileThreads", "1")))
        self.threads_spin.setValue(int(os.getenv("threads", "1")))
        self.batch_size_spin.setValue(int(os.getenv("batchsize", "30")))
        self.frequency_penalty_spin.setValue(float(os.getenv("frequency_penalty", "0.05")))
        
        # Load formatting settings
        self.width_spin.setValue(int(os.getenv("width", "60")))
        self.list_width_spin.setValue(int(os.getenv("listWidth", "100")))
        self.note_width_spin.setValue(int(os.getenv("noteWidth", "75")))
        
        # Load custom API settings
        self.input_cost_spin.setValue(float(os.getenv("input_cost", "2.0")))
        self.output_cost_spin.setValue(float(os.getenv("output_cost", "8.0")))
        
        # Load UI settings
        self.font_scale_spin.setValue(float(os.getenv("font_scale", "1.0")))
        self.theme_combo.setCurrentText(os.getenv("theme", "Dark"))
        
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
            set_key(self.env_file_path, "theme", self.theme_combo.currentText())
            
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
        self.model_combo.setCurrentText("gpt-4.1")
        
        # Translation settings
        self.language_combo.setCurrentText("English")
        self.timeout_spin.setValue(120)
        
        # Performance settings
        self.file_threads_spin.setValue(1)
        self.threads_spin.setValue(1)
        self.batch_size_spin.setValue(30)
        self.frequency_penalty_spin.setValue(0.05)
        
        # Formatting settings
        self.width_spin.setValue(60)
        self.list_width_spin.setValue(100)
        self.note_width_spin.setValue(75)
        
        # Custom API settings
        self.input_cost_spin.setValue(2.0)
        self.output_cost_spin.setValue(8.0)
        
        # UI settings
        self.font_scale_spin.setValue(1.0)
        self.theme_combo.setCurrentText("Dark")
        
        # Reset engine tabs
        self.mvmz_tab.reset_to_defaults()
        self.ace_tab.reset_to_defaults()
        self.wolf_tab.reset_to_defaults()
        
        # Apply font scaling
        self.apply_font_scaling(1.0)
        
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
            "theme": self.theme_combo.currentText()
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
