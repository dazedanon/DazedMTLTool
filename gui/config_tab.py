"""
Configuration Tab - Handles environment variables, global settings, and engine configurations
"""

import os
from pathlib import Path
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, 
    QSpinBox, QDoubleSpinBox, QComboBox, QPushButton, QGroupBox,
    QLabel, QFileDialog, QMessageBox, QScrollArea, QTextEdit,
    QCheckBox, QApplication, QTabWidget, QFrame, QStackedWidget, QToolButton
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QIcon
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
        """Initialize the user interface with horizontal icon navigation at top."""
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Create top navigation bar
        nav_bar = QWidget()
        nav_bar.setFixedHeight(50)
        nav_bar.setStyleSheet("""
            QWidget {
                background-color: #2d2d30;
            }
        """)
        nav_layout = QHBoxLayout()
        nav_layout.setContentsMargins(10, 0, 10, 0)
        nav_layout.setSpacing(5)
        
        # Create navigation buttons
        self.nav_buttons = []
        
        # General Settings button
        btn_general = self.create_nav_button("🔧", "General Settings")
        btn_general.clicked.connect(lambda: self.switch_page(0))
        nav_layout.addWidget(btn_general)
        self.nav_buttons.append(btn_general)
        
        # RPG Maker MV/MZ button
        btn_mvmz = self.create_nav_button("🎮", "RPG Maker MV/MZ")
        btn_mvmz.clicked.connect(lambda: self.switch_page(1))
        nav_layout.addWidget(btn_mvmz)
        self.nav_buttons.append(btn_mvmz)
        
        # RPG Maker Ace button
        btn_ace = self.create_nav_button("🎲", "RPG Maker Ace")
        btn_ace.clicked.connect(lambda: self.switch_page(2))
        nav_layout.addWidget(btn_ace)
        self.nav_buttons.append(btn_ace)
        
        # Wolf RPG button
        btn_wolf = self.create_nav_button("🐺", "Wolf RPG")
        btn_wolf.clicked.connect(lambda: self.switch_page(3))
        nav_layout.addWidget(btn_wolf)
        self.nav_buttons.append(btn_wolf)
        
        nav_layout.addStretch()
        nav_bar.setLayout(nav_layout)
        
        # Create stacked widget for content pages
        self.content_stack = QStackedWidget()
        
        # Page 1: General Settings
        general_tab = self.create_general_settings_tab()
        self.content_stack.addWidget(general_tab)
        
        # Page 2: RPG Maker MV/MZ Engine
        self.mvmz_tab = RPGMakerTab("MVMZ")
        self.content_stack.addWidget(self.mvmz_tab)
        
        # Page 3: RPG Maker Ace Engine
        self.ace_tab = RPGMakerTab("ACE")
        self.content_stack.addWidget(self.ace_tab)
        
        # Page 4: Wolf RPG Engine
        self.wolf_tab = WolfTab()
        self.content_stack.addWidget(self.wolf_tab)
        
        # Add navigation bar and content to main layout
        main_layout.addWidget(nav_bar)
        main_layout.addWidget(self.content_stack)
        self.setLayout(main_layout)
        
        # Select first page by default
        self.switch_page(0)
    
    def create_nav_button(self, icon_text, tooltip):
        """Create a navigation button for the top bar."""
        btn = QToolButton()
        btn.setText(icon_text)
        btn.setToolTip(tooltip)
        btn.setFixedSize(50, 50)
        btn.setCheckable(True)
        btn.setStyleSheet("""
            QToolButton {
                background-color: transparent;
                border: none;
                border-bottom: 3px solid transparent;
                color: #cccccc;
                font-size: 24px;
                padding: 5px;
            }
            QToolButton:hover {
                background-color: #3e3e42;
            }
            QToolButton:checked {
                background-color: #37373d;
                border-bottom: 3px solid #007acc;
                color: #ffffff;
            }
        """)
        return btn
    
    def switch_page(self, index):
        """Switch to the specified page and update button states."""
        self.content_stack.setCurrentIndex(index)
        
        # Update button checked states
        for i, btn in enumerate(self.nav_buttons):
            btn.setChecked(i == index)
    
    def create_general_settings_tab(self):
        """Create combined general settings tab with API, Translation, Performance, and UI settings."""
        widget = QWidget()
        
        content = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(8)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # Create a two-column layout for better space utilization
        columns_layout = QHBoxLayout()
        columns_layout.setSpacing(30)
        
        # LEFT COLUMN
        left_column = QVBoxLayout()
        left_column.setSpacing(8)
        
        # API Configuration Section
        left_column.addWidget(create_section_header("🔑 API Configuration"))
        api_form = QFormLayout()
        api_form.setSpacing(6)
        api_form.setContentsMargins(0, 0, 0, 12)
        api_form.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        api_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        
        api_url_label = QLabel("API URL:")
        api_url_label.setFixedWidth(150)
        api_url_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.api_url_edit = QLineEdit()
        self.api_url_edit.setPlaceholderText("Leave blank for OpenAI API")
        self.api_url_edit.setFixedWidth(350)  # Large
        api_form.addRow(api_url_label, self.api_url_edit)
        
        api_key_label = QLabel("API Key:")
        api_key_label.setFixedWidth(150)
        api_key_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.api_key_edit.setPlaceholderText("Enter your API key")
        self.api_key_edit.setFixedWidth(350)  # Large
        api_form.addRow(api_key_label, self.api_key_edit)
        
        org_label = QLabel("Organization:")
        org_label.setFixedWidth(150)
        org_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.organization_edit = QLineEdit()
        self.organization_edit.setPlaceholderText("Optional organization key")
        self.organization_edit.setFixedWidth(350)  # Large
        api_form.addRow(org_label, self.organization_edit)
        
        model_label = QLabel("Model:")
        model_label.setFixedWidth(150)
        model_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.addItems([
            "gpt-4.1-mini", "gpt-4.1", "gpt-5",
            "deepseek-chat", "claude-3-sonnet-20240229",
            "gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-pro"
        ])
        self.model_combo.setFixedWidth(200)  # Medium
        api_form.addRow(model_label, self.model_combo)
        
        left_column.addLayout(api_form)
        left_column.addWidget(create_horizontal_line())
        
        # Translation Settings Section
        left_column.addWidget(create_section_header("🌐 Translation Settings"))
        trans_form = QFormLayout()
        trans_form.setSpacing(6)
        trans_form.setContentsMargins(0, 0, 0, 12)
        trans_form.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        trans_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        
        lang_label = QLabel("Target Language:")
        lang_label.setFixedWidth(150)
        lang_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.language_combo = QComboBox()
        self.language_combo.addItems([
            "English", "Spanish", "French", "German", "Italian",
            "Portuguese", "Russian", "Chinese", "Korean", "Japanese"
        ])
        self.language_combo.setFixedWidth(200)  # Medium
        trans_form.addRow(lang_label, self.language_combo)
        
        timeout_label = QLabel("Timeout:")
        timeout_label.setFixedWidth(150)
        timeout_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setButtonSymbols(QSpinBox.NoButtons)
        self.timeout_spin.setRange(30, 300)
        self.timeout_spin.setValue(90)
        self.timeout_spin.setSuffix(" sec")
        self.timeout_spin.setFixedWidth(120)  # Small
        trans_form.addRow(timeout_label, self.timeout_spin)
        
        left_column.addLayout(trans_form)
        left_column.addWidget(create_horizontal_line())
        
        # Performance Settings Section
        left_column.addWidget(create_section_header("⚡ Performance Settings"))
        perf_form = QFormLayout()
        perf_form.setSpacing(6)
        perf_form.setContentsMargins(0, 0, 0, 12)
        perf_form.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        perf_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        
        file_threads_label = QLabel("File Threads:")
        file_threads_label.setFixedWidth(150)
        file_threads_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.file_threads_spin = QSpinBox()
        self.file_threads_spin.setButtonSymbols(QSpinBox.NoButtons)
        self.file_threads_spin.setRange(1, 10)
        self.file_threads_spin.setValue(1)
        self.file_threads_spin.setFixedWidth(120)  # Small
        perf_form.addRow(file_threads_label, self.file_threads_spin)
        
        threads_label = QLabel("Threads per File:")
        threads_label.setFixedWidth(150)
        threads_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.threads_spin = QSpinBox()
        self.threads_spin.setButtonSymbols(QSpinBox.NoButtons)
        self.threads_spin.setRange(1, 20)
        self.threads_spin.setValue(1)
        self.threads_spin.setFixedWidth(120)  # Small
        perf_form.addRow(threads_label, self.threads_spin)
        
        batch_label = QLabel("Batch Size:")
        batch_label.setFixedWidth(150)
        batch_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.batch_size_spin = QSpinBox()
        self.batch_size_spin.setButtonSymbols(QSpinBox.NoButtons)
        self.batch_size_spin.setRange(1, 100)
        self.batch_size_spin.setValue(30)
        self.batch_size_spin.setFixedWidth(120)  # Small
        perf_form.addRow(batch_label, self.batch_size_spin)
        
        freq_label = QLabel("Frequency Penalty:")
        freq_label.setFixedWidth(150)
        freq_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.frequency_penalty_spin = QDoubleSpinBox()
        self.frequency_penalty_spin.setButtonSymbols(QDoubleSpinBox.NoButtons)
        self.frequency_penalty_spin.setRange(0.0, 2.0)
        self.frequency_penalty_spin.setSingleStep(0.05)
        self.frequency_penalty_spin.setValue(0.05)
        self.frequency_penalty_spin.setFixedWidth(120)  # Small
        perf_form.addRow(freq_label, self.frequency_penalty_spin)
        
        left_column.addLayout(perf_form)
        left_column.addStretch()
        
        # RIGHT COLUMN
        right_column = QVBoxLayout()
        right_column.setSpacing(8)
        
        # Text Formatting Section
        right_column.addWidget(create_section_header("📝 Text Formatting"))
        format_form = QFormLayout()
        format_form.setSpacing(6)
        format_form.setContentsMargins(0, 0, 0, 12)
        format_form.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        format_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        
        dialogue_label = QLabel("Dialogue Width:")
        dialogue_label.setFixedWidth(150)
        dialogue_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.width_spin = QSpinBox()
        self.width_spin.setButtonSymbols(QSpinBox.NoButtons)
        self.width_spin.setRange(20, 200)
        self.width_spin.setValue(60)
        self.width_spin.setSuffix(" chars")
        self.width_spin.setFixedWidth(120)  # Small
        format_form.addRow(dialogue_label, self.width_spin)
        
        list_label = QLabel("List Width:")
        list_label.setFixedWidth(150)
        list_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.list_width_spin = QSpinBox()
        self.list_width_spin.setButtonSymbols(QSpinBox.NoButtons)
        self.list_width_spin.setRange(20, 200)
        self.list_width_spin.setValue(100)
        self.list_width_spin.setSuffix(" chars")
        self.list_width_spin.setFixedWidth(120)  # Small
        format_form.addRow(list_label, self.list_width_spin)
        
        note_label = QLabel("Note Width:")
        note_label.setFixedWidth(150)
        note_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.note_width_spin = QSpinBox()
        self.note_width_spin.setButtonSymbols(QSpinBox.NoButtons)
        self.note_width_spin.setRange(20, 200)
        self.note_width_spin.setValue(75)
        self.note_width_spin.setSuffix(" chars")
        self.note_width_spin.setFixedWidth(120)  # Small
        format_form.addRow(note_label, self.note_width_spin)
        
        right_column.addLayout(format_form)
        right_column.addWidget(create_horizontal_line())
        
        # Custom API Pricing Section
        right_column.addWidget(create_section_header("💰 Custom API Pricing"))
        
        pricing_note = QLabel("Only used if model isn't in built-in pricing list")
        pricing_note.setStyleSheet("color: #888888; font-style: italic; font-size: 9px;")
        pricing_note.setWordWrap(True)
        right_column.addWidget(pricing_note)
        
        price_form = QFormLayout()
        price_form.setSpacing(6)
        price_form.setContentsMargins(0, 3, 0, 12)
        price_form.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        price_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        
        input_label = QLabel("Input Cost:")
        input_label.setFixedWidth(150)
        input_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.input_cost_spin = QDoubleSpinBox()
        self.input_cost_spin.setButtonSymbols(QDoubleSpinBox.NoButtons)
        self.input_cost_spin.setRange(0.0, 100.0)
        self.input_cost_spin.setDecimals(4)
        self.input_cost_spin.setSingleStep(0.1)
        self.input_cost_spin.setValue(2.0)
        self.input_cost_spin.setSuffix(" per 1M tokens")
        self.input_cost_spin.setFixedWidth(200)  # Medium
        price_form.addRow(input_label, self.input_cost_spin)
        
        output_label = QLabel("Output Cost:")
        output_label.setFixedWidth(150)
        output_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.output_cost_spin = QDoubleSpinBox()
        self.output_cost_spin.setButtonSymbols(QDoubleSpinBox.NoButtons)
        self.output_cost_spin.setRange(0.0, 100.0)
        self.output_cost_spin.setDecimals(4)
        self.output_cost_spin.setSingleStep(0.1)
        self.output_cost_spin.setValue(8.0)
        self.output_cost_spin.setSuffix(" per 1M tokens")
        self.output_cost_spin.setFixedWidth(200)  # Medium
        price_form.addRow(output_label, self.output_cost_spin)
        
        right_column.addLayout(price_form)
        right_column.addStretch()
        
        # Add columns to layout
        columns_layout.addLayout(left_column, 1)
        columns_layout.addLayout(right_column, 1)
        
        layout.addLayout(columns_layout)
        
        # Add buttons at the bottom of General Settings tab
        layout.addSpacing(15)
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)
        
        save_button = QPushButton("💾 Save Configuration")
        save_button.clicked.connect(self.save_to_env)
        save_button.setMinimumHeight(32)
        save_button.setStyleSheet("font-weight: bold;")
        
        load_button = QPushButton("📂 Load from File")
        load_button.clicked.connect(self.load_from_file_dialog)
        load_button.setMinimumHeight(32)
        
        reset_button = QPushButton("🔄 Reset to Defaults")
        reset_button.clicked.connect(self.reset_to_defaults)
        reset_button.setMinimumHeight(32)
        
        button_layout.addWidget(save_button)
        button_layout.addWidget(load_button)
        button_layout.addWidget(reset_button)
        button_layout.addStretch()
        
        layout.addLayout(button_layout)
        
        content.setLayout(layout)
        widget.setLayout(QVBoxLayout())
        widget.layout().setContentsMargins(0, 0, 0, 0)
        widget.layout().addWidget(content)
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
        self.timeout_spin.setValue(int(os.getenv("timeout", "90")))
        
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
        self.timeout_spin.setValue(90)
        
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
        
        # Reset engine tabs
        self.mvmz_tab.reset_to_defaults()
        self.ace_tab.reset_to_defaults()
        self.wolf_tab.reset_to_defaults()
        
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
            "output_cost": self.output_cost_spin.value()
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
