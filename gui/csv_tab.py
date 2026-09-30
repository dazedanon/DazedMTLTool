"""
CSV Tab - Configuration for CSV translation settings
"""

from pathlib import Path
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QCheckBox, 
    QPushButton, QLabel, QMessageBox, QSpinBox, QFrame, QComboBox
)
from PyQt5.QtCore import Qt, pyqtSignal
from gui.theme import COLORS
from gui.ui_components import SectionCard, configure_action_button
try:
    from .config_integration import ConfigIntegration
except ImportError:
    ConfigIntegration = None


def create_section_label(text):
    """Create a section label for grouping settings."""
    from gui.qt_icons import make_section_header

    return make_section_header(
        text,
        "QLabel {"
        "font-size: 12px;"
        "font-weight: bold;"
        "color: #007acc;"
        "padding: 5px 0px 3px 0px;"
        "background-color: transparent;"
        "}",
    )


def create_horizontal_line():
    """Create a horizontal separator line."""
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setFrameShadow(QFrame.Sunken)
    line.setStyleSheet("QFrame { color: #555555; margin: 5px 0px; }")
    return line


class CSVTab(QWidget):
    """CSV configuration tab for managing CSV translation settings."""
    
    # Default configuration values (0-indexed internally)
    DEFAULT_CONFIG = {
        # Delimiter
        "CSV_DELIMITER": ",",
        
        # Column settings (stored as 0-indexed)
        "SOURCE_COLUMN": 0,
        "TARGET_COLUMN": 1,
        "SPEAKER_COLUMN": -1,  # -1 means no speaker column
        
        # Row settings
        "SKIP_HEADER_ROW": True,
        "USE_TARGET_IF_NOT_EMPTY": False,
        "SKIP_IF_TARGET_TRANSLATED": False,
        
        # Output settings
        "WRITE_TO_NEXT_COLUMN": False,
        
        # Special parsing
        "PARSE_NAME_TAGS": False,
        "PARSE_M_MARKERS": False,
        "REMOVE_FURIGANA": False,
        "SKIP_COMMENT_ROWS": False,
    }
    
    config_changed = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        self.config_integration = ConfigIntegration() if ConfigIntegration else None
        self.init_ui()
        
        # Load configuration from module
        try:
            self.disconnect_auto_apply()
            loaded_config = None
            if self.config_integration:
                module_path = Path("modules") / "csv.py"
                loaded_config = self.read_csv_config(module_path)
            
            if loaded_config:
                self.set_config(loaded_config)
            else:
                self.set_config(self.DEFAULT_CONFIG)
        except Exception:
            self.set_config(self.DEFAULT_CONFIG)
        
        self.connect_auto_apply()
    
    def init_ui(self):
        """Initialize the user interface."""
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)
        
        presets_card = SectionCard(
            "Choose a starting preset",
            "Apply a common CSV layout, then refine the column, row, output, and parsing settings below.",
        )
        main_layout.addWidget(presets_card)
        
        preset_layout = QHBoxLayout()
        preset_layout.setSpacing(15)
        
        preset_tpp = QPushButton("Translator++")
        configure_action_button(preset_tpp, variant="secondary")
        preset_tpp.setToolTip("Source col 1, Target col 2, skip header, use target if not empty")
        preset_tpp.clicked.connect(self.apply_preset_tpp)
        preset_layout.addWidget(preset_tpp, 1)  # stretch factor 1 for equal spacing
        
        preset_simple = QPushButton("Simple")
        configure_action_button(preset_simple, variant="secondary")
        preset_simple.setToolTip("Source col 1, Target col 2, no special processing")
        preset_simple.clicked.connect(self.apply_preset_simple)
        preset_layout.addWidget(preset_simple, 1)
        
        preset_speaker = QPushButton("Speaker & Text")
        configure_action_button(preset_speaker, variant="secondary")
        preset_speaker.setToolTip("Speaker col 3, Text col 10, with furigana removal")
        preset_speaker.clicked.connect(self.apply_preset_speaker)
        preset_layout.addWidget(preset_speaker, 1)
        
        presets_card.add_layout(preset_layout)
        
        # Two-column layout
        columns_layout = QHBoxLayout()
        columns_layout.setSpacing(40)
        
        # LEFT COLUMN
        left_column = QVBoxLayout()
        left_column.setSpacing(8)
        
        # Column Settings
        left_column.addWidget(create_section_label("📊 Column Settings"))
        
        column_form = QFormLayout()
        column_form.setSpacing(8)
        column_form.setContentsMargins(0, 0, 0, 10)
        
        # Source Column
        source_label = QLabel("Source Column:")
        source_label.setToolTip("Which column contains the source text to translate (1 = first column)")
        self.source_column_spin = QSpinBox()
        self.source_column_spin.setRange(1, 100)
        self.source_column_spin.setValue(1)
        self.source_column_spin.setMinimumWidth(100)
        column_form.addRow(source_label, self.source_column_spin)
        
        # Target Column
        target_label = QLabel("Target Column:")
        target_label.setToolTip("Which column to write translations to (1 = first column)")
        self.target_column_spin = QSpinBox()
        self.target_column_spin.setRange(1, 100)
        self.target_column_spin.setValue(2)
        self.target_column_spin.setMinimumWidth(100)
        column_form.addRow(target_label, self.target_column_spin)
        
        # Speaker Column
        speaker_label = QLabel("Speaker Column:")
        speaker_label.setToolTip("Which column contains speaker names (None = disabled)")
        self.speaker_column_spin = QSpinBox()
        self.speaker_column_spin.setRange(0, 100)
        self.speaker_column_spin.setValue(0)
        self.speaker_column_spin.setSpecialValueText("None")
        self.speaker_column_spin.setMinimumWidth(100)
        column_form.addRow(speaker_label, self.speaker_column_spin)
        
        left_column.addLayout(column_form)
        left_column.addWidget(create_horizontal_line())
        
        # Row Settings
        left_column.addWidget(create_section_label("📝 Row Settings"))
        
        self.skip_header_cb = QCheckBox("Skip Header Row")
        self.skip_header_cb.setToolTip("Skip the first row (usually contains column headers)")
        left_column.addWidget(self.skip_header_cb)
        
        self.use_target_if_not_empty_cb = QCheckBox("Use Target if Not Empty")
        self.use_target_if_not_empty_cb.setToolTip("If target column already has text, use that instead of source (T++ style)")
        left_column.addWidget(self.use_target_if_not_empty_cb)

        self.skip_if_target_translated_cb = QCheckBox("Skip if Target Translated")
        self.skip_if_target_translated_cb.setToolTip(
            "Check candidate rows in batches matching the global Batch Size setting. "
            "Skip a batch when every target is already translated (non-empty, no Japanese). "
            "If any row still needs work, translate only the unfinished rows in that batch."
        )
        left_column.addWidget(self.skip_if_target_translated_cb)
        
        left_column.addStretch()
        
        # RIGHT COLUMN
        right_column = QVBoxLayout()
        right_column.setSpacing(8)
        
        # Output Settings
        right_column.addWidget(create_section_label("📤 Output Settings"))
        
        self.write_next_column_cb = QCheckBox("Write to Next Column")
        self.write_next_column_cb.setToolTip("Write translation to the column after target instead of overwriting")
        right_column.addWidget(self.write_next_column_cb)
        
        # CSV Delimiter
        delim_layout = QHBoxLayout()
        delim_label = QLabel("Delimiter:")
        delim_label.setToolTip("Character used to separate columns in the CSV file")
        self.csv_delimiter_combo = QComboBox()
        self.csv_delimiter_combo.addItems([",", ";", "Tab"])
        self.csv_delimiter_combo.setMinimumWidth(80)
        delim_layout.addWidget(delim_label)
        delim_layout.addWidget(self.csv_delimiter_combo)
        delim_layout.addStretch()
        right_column.addLayout(delim_layout)
        
        right_column.addWidget(create_horizontal_line())
        
        # Special Parsing
        right_column.addWidget(create_section_label("🔧 Special Parsing"))
        
        self.parse_name_tags_cb = QCheckBox("Parse :name[] Tags")
        self.parse_name_tags_cb.setToolTip("Extract speaker names from :name[Speaker] tags in text")
        right_column.addWidget(self.parse_name_tags_cb)
        
        self.parse_m_markers_cb = QCheckBox("Parse \\M Markers")
        self.parse_m_markers_cb.setToolTip("Handle \\M escape sequences in text")
        right_column.addWidget(self.parse_m_markers_cb)
        
        self.remove_furigana_cb = QCheckBox("Remove Furigana ＜＝＞")
        self.remove_furigana_cb.setToolTip("Remove furigana annotations like ＜漢字＝かんじ＞")
        right_column.addWidget(self.remove_furigana_cb)
        
        self.skip_comment_rows_cb = QCheckBox("Skip Comment Rows")
        self.skip_comment_rows_cb.setToolTip("Skip rows where first column contains 'comment'")
        right_column.addWidget(self.skip_comment_rows_cb)
        
        right_column.addStretch()
        
        rows_card = SectionCard(
            "Columns and rows",
            "Map source, target, and speaker columns, then choose which rows are reused or skipped.",
        )
        rows_card.add_layout(left_column)
        output_card = SectionCard(
            "Output and special parsing",
            "Choose where translations are written and enable only the markers used by this CSV format.",
        )
        output_card.add_layout(right_column)
        columns_layout.addWidget(rows_card, 1)
        columns_layout.addWidget(output_card, 1)
        main_layout.addLayout(columns_layout)
        
        # Bottom buttons
        main_layout.addSpacing(12)
        button_layout = QHBoxLayout()
        button_layout.setSpacing(8)
        
        from gui.qt_icons import apply_button_icon

        self.reset_button = QPushButton()
        configure_action_button(self.reset_button, variant="quiet")
        apply_button_icon(
            self.reset_button, "🔄 Reset to defaults", color=COLORS.text_secondary
        )
        self.reset_button.clicked.connect(self.reset_to_defaults_with_message)
        self.reset_button.setMinimumWidth(180)
        self.reset_button.setMinimumHeight(32)
        
        button_layout.addWidget(self.reset_button)
        button_layout.addStretch()
        
        main_layout.addLayout(button_layout)
        self.setLayout(main_layout)
    
    def apply_preset_tpp(self):
        """Apply Translator++ preset."""
        self.disconnect_auto_apply()
        self.source_column_spin.setValue(1)  # Display as 1-based
        self.target_column_spin.setValue(2)
        self.speaker_column_spin.setValue(0)  # 0 = None
        self.skip_header_cb.setChecked(True)
        self.use_target_if_not_empty_cb.setChecked(True)
        self.skip_if_target_translated_cb.setChecked(False)
        self.write_next_column_cb.setChecked(False)
        self.parse_name_tags_cb.setChecked(False)
        self.parse_m_markers_cb.setChecked(False)
        self.remove_furigana_cb.setChecked(False)
        self.skip_comment_rows_cb.setChecked(False)
        self.connect_auto_apply()
        self.apply_to_module(show_messages=False)
    
    def apply_preset_simple(self):
        """Apply simple two-column preset."""
        self.disconnect_auto_apply()
        self.source_column_spin.setValue(1)  # Display as 1-based
        self.target_column_spin.setValue(2)
        self.speaker_column_spin.setValue(0)  # 0 = None
        self.skip_header_cb.setChecked(False)
        self.use_target_if_not_empty_cb.setChecked(False)
        self.skip_if_target_translated_cb.setChecked(False)
        self.write_next_column_cb.setChecked(False)
        self.parse_name_tags_cb.setChecked(False)
        self.parse_m_markers_cb.setChecked(False)
        self.remove_furigana_cb.setChecked(False)
        self.skip_comment_rows_cb.setChecked(False)
        self.connect_auto_apply()
        self.apply_to_module(show_messages=False)
    
    def apply_preset_speaker(self):
        """Apply speaker & text preset (like old format 4)."""
        self.disconnect_auto_apply()
        self.source_column_spin.setValue(10)  # Display as 1-based (was 9)
        self.target_column_spin.setValue(10)
        self.speaker_column_spin.setValue(3)  # Display as 1-based (was 2, 0=None so 3=col2)
        self.skip_header_cb.setChecked(False)
        self.use_target_if_not_empty_cb.setChecked(False)
        self.skip_if_target_translated_cb.setChecked(False)
        self.write_next_column_cb.setChecked(False)
        self.parse_name_tags_cb.setChecked(False)
        self.parse_m_markers_cb.setChecked(False)
        self.remove_furigana_cb.setChecked(True)
        self.skip_comment_rows_cb.setChecked(False)
        self.connect_auto_apply()
        self.apply_to_module(show_messages=False)
    
    def reset_to_defaults(self):
        """Reset all settings to default values."""
        self.disconnect_auto_apply()
        self.set_config(self.DEFAULT_CONFIG)
        self.connect_auto_apply()
        self.apply_to_module(show_messages=False)
    
    def reset_to_defaults_with_message(self):
        """Reset to defaults and show confirmation."""
        self.reset_to_defaults()
        QMessageBox.information(
            self,
            "Reset Complete",
            "All CSV settings have been reset to their default values."
        )
    
    def disconnect_auto_apply(self):
        """Disconnect all widgets from auto-apply."""
        try:
            self.source_column_spin.valueChanged.disconnect()
            self.target_column_spin.valueChanged.disconnect()
            self.speaker_column_spin.valueChanged.disconnect()
            self.csv_delimiter_combo.currentIndexChanged.disconnect()
            self.skip_header_cb.stateChanged.disconnect()
            self.use_target_if_not_empty_cb.stateChanged.disconnect()
            self.skip_if_target_translated_cb.stateChanged.disconnect()
            self.write_next_column_cb.stateChanged.disconnect()
            self.parse_name_tags_cb.stateChanged.disconnect()
            self.parse_m_markers_cb.stateChanged.disconnect()
            self.remove_furigana_cb.stateChanged.disconnect()
            self.skip_comment_rows_cb.stateChanged.disconnect()
        except TypeError:
            pass
    
    def connect_auto_apply(self):
        """Connect all widgets to auto-apply changes."""
        self.source_column_spin.valueChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.target_column_spin.valueChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.speaker_column_spin.valueChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.csv_delimiter_combo.currentIndexChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.skip_header_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.use_target_if_not_empty_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.skip_if_target_translated_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.write_next_column_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.parse_name_tags_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.parse_m_markers_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.remove_furigana_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.skip_comment_rows_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
    
    def get_config(self):
        """Get current configuration as dictionary (converts UI 1-based to internal 0-based)."""
        # Convert from 1-based UI to 0-based internal
        # Source/Target: UI shows 1-100, internal uses 0-99
        # Speaker: UI shows 0 (None) or 1-100, internal uses -1 (None) or 0-99
        speaker_ui = self.speaker_column_spin.value()
        speaker_internal = speaker_ui - 1 if speaker_ui > 0 else -1
        
        # Get delimiter value
        delim_index = self.csv_delimiter_combo.currentIndex()
        delim_values = [",", ";", "\t"]
        delimiter = delim_values[delim_index] if delim_index < len(delim_values) else ","
        
        return {
            "SOURCE_COLUMN": self.source_column_spin.value() - 1,
            "TARGET_COLUMN": self.target_column_spin.value() - 1,
            "SPEAKER_COLUMN": speaker_internal,
            "CSV_DELIMITER": delimiter,
            "SKIP_HEADER_ROW": self.skip_header_cb.isChecked(),
            "USE_TARGET_IF_NOT_EMPTY": self.use_target_if_not_empty_cb.isChecked(),
            "SKIP_IF_TARGET_TRANSLATED": self.skip_if_target_translated_cb.isChecked(),
            "WRITE_TO_NEXT_COLUMN": self.write_next_column_cb.isChecked(),
            "PARSE_NAME_TAGS": self.parse_name_tags_cb.isChecked(),
            "PARSE_M_MARKERS": self.parse_m_markers_cb.isChecked(),
            "REMOVE_FURIGANA": self.remove_furigana_cb.isChecked(),
            "SKIP_COMMENT_ROWS": self.skip_comment_rows_cb.isChecked(),
        }
    
    def set_config(self, config):
        """Set configuration from dictionary (converts internal 0-based to UI 1-based)."""
        # Convert from 0-based internal to 1-based UI
        # Source/Target: internal uses 0-99, UI shows 1-100
        # Speaker: internal uses -1 (None) or 0-99, UI shows 0 (None) or 1-100
        speaker_internal = config.get("SPEAKER_COLUMN", -1)
        speaker_ui = speaker_internal + 1 if speaker_internal >= 0 else 0
        
        self.source_column_spin.setValue(config.get("SOURCE_COLUMN", 0) + 1)
        self.target_column_spin.setValue(config.get("TARGET_COLUMN", 1) + 1)
        self.speaker_column_spin.setValue(speaker_ui)
        
        # Set delimiter
        delimiter = config.get("CSV_DELIMITER", ",")
        if delimiter == "\t":
            self.csv_delimiter_combo.setCurrentIndex(2)
        elif delimiter == ";":
            self.csv_delimiter_combo.setCurrentIndex(1)
        else:
            self.csv_delimiter_combo.setCurrentIndex(0)
        
        self.skip_header_cb.setChecked(config.get("SKIP_HEADER_ROW", True))
        self.use_target_if_not_empty_cb.setChecked(config.get("USE_TARGET_IF_NOT_EMPTY", False))
        self.skip_if_target_translated_cb.setChecked(config.get("SKIP_IF_TARGET_TRANSLATED", False))
        self.write_next_column_cb.setChecked(config.get("WRITE_TO_NEXT_COLUMN", False))
        self.parse_name_tags_cb.setChecked(config.get("PARSE_NAME_TAGS", False))
        self.parse_m_markers_cb.setChecked(config.get("PARSE_M_MARKERS", False))
        self.remove_furigana_cb.setChecked(config.get("REMOVE_FURIGANA", False))
        self.skip_comment_rows_cb.setChecked(config.get("SKIP_COMMENT_ROWS", False))
    
    def read_csv_config(self, module_path: Path) -> dict:
        """Read current configuration from csv.py module file."""
        if not module_path.exists():
            return {}
        
        config = {}
        
        try:
            with open(module_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            import re
            
            # Read integer values
            int_patterns = {
                "SOURCE_COLUMN": r'^SOURCE_COLUMN\s*=\s*(-?\d+)',
                "TARGET_COLUMN": r'^TARGET_COLUMN\s*=\s*(-?\d+)',
                "SPEAKER_COLUMN": r'^SPEAKER_COLUMN\s*=\s*(-?\d+)',
            }
            
            # Read string values (delimiter)
            string_patterns = {
                "CSV_DELIMITER": r'^CSV_DELIMITER\s*=\s*["\'](.+?)["\']',
            }
            
            # Read boolean values
            bool_patterns = {
                "SKIP_HEADER_ROW": r'^SKIP_HEADER_ROW\s*=\s*(True|False)',
                "USE_TARGET_IF_NOT_EMPTY": r'^USE_TARGET_IF_NOT_EMPTY\s*=\s*(True|False)',
                "SKIP_IF_TARGET_TRANSLATED": r'^SKIP_IF_TARGET_TRANSLATED\s*=\s*(True|False)',
                "WRITE_TO_NEXT_COLUMN": r'^WRITE_TO_NEXT_COLUMN\s*=\s*(True|False)',
                "PARSE_NAME_TAGS": r'^PARSE_NAME_TAGS\s*=\s*(True|False)',
                "PARSE_M_MARKERS": r'^PARSE_M_MARKERS\s*=\s*(True|False)',
                "REMOVE_FURIGANA": r'^REMOVE_FURIGANA\s*=\s*(True|False)',
                "SKIP_COMMENT_ROWS": r'^SKIP_COMMENT_ROWS\s*=\s*(True|False)',
            }
            
            for line in content.split('\n'):
                line = line.strip()
                
                for key, pattern in int_patterns.items():
                    match = re.match(pattern, line)
                    if match:
                        config[key] = int(match.group(1))
                
                for key, pattern in string_patterns.items():
                    match = re.match(pattern, line)
                    if match:
                        config[key] = match.group(1)
                
                for key, pattern in bool_patterns.items():
                    match = re.match(pattern, line)
                    if match:
                        config[key] = match.group(1) == 'True'
                        
        except Exception as e:
            print(f"Error reading CSV config: {e}")
        
        return config
    
    def apply_to_module(self, show_messages=True):
        """Apply current configuration to the csv.py module file."""
        if not self.config_integration:
            if show_messages:
                QMessageBox.warning(self, "Error", "Config integration not available")
            return
        
        module_path = Path("modules") / "csv.py"
        
        if not module_path.exists():
            if show_messages:
                QMessageBox.warning(self, "Error", f"Module file not found: {module_path}")
            return
        
        try:
            config = self.get_config()
            
            with open(module_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Update configuration values
            updated_content = self._update_csv_config(content, config)
            
            with open(module_path, 'w', encoding='utf-8') as f:
                f.write(updated_content)
            
            self.config_changed.emit()
            
            if show_messages:
                QMessageBox.information(self, "Success", "CSV configuration applied successfully!")
                
        except Exception as e:
            if show_messages:
                QMessageBox.critical(self, "Error", f"Failed to apply configuration:\n{str(e)}")
    
    def _update_csv_config(self, content: str, config: dict) -> str:
        """Update configuration values in the module content."""
        import re
        
        lines = content.split('\n')
        updated_lines = []
        
        for line in lines:
            updated_line = line
            
            for key, value in config.items():
                # Match lines like: CONFIG_NAME = value  # comment
                pattern = rf'^({re.escape(key)})\s*=\s*.*?(#.*)?$'
                match = re.match(pattern, line.strip())
                
                if match:
                    comment = match.group(2) if match.group(2) else ""
                    if comment:
                        comment = "  " + comment
                    
                    # Format value appropriately
                    if isinstance(value, bool):
                        value_str = str(value)
                    elif isinstance(value, str):
                        # String values need quotes
                        value_str = f'"{value}"'
                    else:
                        value_str = str(value)
                    
                    updated_line = f"{key} = {value_str}{comment}"
                    break
            
            updated_lines.append(updated_line)
        
        return '\n'.join(updated_lines)
