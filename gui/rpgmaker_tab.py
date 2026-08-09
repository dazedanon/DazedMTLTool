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
from gui.theme import COLORS
from gui.ui_components import SectionCard, configure_action_button
try:
    from .config_integration import ConfigIntegration
except ImportError:
    # Fallback if config_integration is not available
    ConfigIntegration = None
try:
    # Prefer importing the project's canonical defaults if available
    from util.defaults import DEFAULTS as CANONICAL_DEFAULTS
except Exception:
    CANONICAL_DEFAULTS = None


def create_section_label(text):
    """Create a section label for grouping settings."""
    from gui.qt_icons import make_section_header

    return make_section_header(
        text,
        "QLabel {"
        "font-size: 13px;"
        "font-weight: bold;"
        "color: #007acc;"
        "padding: 6px 0px 4px 0px;"
        "background-color: transparent;"
        "}",
    )


class RPGMakerTab(QWidget):
    """RPG Maker MV/MZ configuration tab."""
    
    # Default configuration values for RPG Maker MV/MZ
    DEFAULT_CONFIG = {
        # General settings
        "FIRSTLINESPEAKERS": False,
        "INLINE401SPEAKERS": False,
        "FACENAME101": False,
        "BRFLAG": False,
        "FIXTEXTWRAP": True,
        "IGNORETLTEXT": False,
        "TLSYSTEMVARIABLES": False,
        "TLSYSTEMSWITCHES": False,
        
        # Main Codes (enabled by default)
        "CODE401": True,   # Show Text
        "CODE405": True,   # Show Text (line 4+)
        "CODE102": True,   # Show Choices
        
        # Optional codes (disabled by default)
        "CODE101": False,  # Show Text (face)
        "CODE408": False,  # Show Text (line continuation)
        
        # Variable codes (disabled by default)
        "CODE122": False,  # Control Variables
        "CODE122_VAR_MIN": 0,  # Minimum variable ID to translate
        "CODE122_VAR_MAX": 2000,  # Maximum variable ID to translate
        
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

        # Load configuration from the module when available. We must avoid
        # auto-applying/writing to the module at startup. Therefore:
        # - Set the UI state from the module config if present
        # - Otherwise fall back to DEFAULT_CONFIG
        # - Only after the UI is initialized and set, connect auto-apply
        try:
            # Ensure signals are not connected yet (safe no-op if not)
            self.disconnect_auto_apply()

            loaded_config = None
            if self.config_integration:
                module_path = Path("modules") / "rpgmakermvmz.py"
                loaded_config = self.config_integration.read_current_config(module_path)

            # Use loaded module config if available, otherwise use canonical defaults
            if loaded_config:
                self.set_config(loaded_config)
            else:
                # Prefer project-level canonical defaults when present
                defaults = CANONICAL_DEFAULTS if CANONICAL_DEFAULTS is not None else self.DEFAULT_CONFIG
                # Ensure boolean values (set_config expects booleans)
                self.set_config(defaults)

        except Exception:
            # On any problem while reading module config, fall back to canonical/defaults
            defaults = CANONICAL_DEFAULTS if CANONICAL_DEFAULTS is not None else self.DEFAULT_CONFIG
            self.set_config(defaults)

        # Now connect auto-apply so user changes will update the module
        self.connect_auto_apply()
        
    def _create_checkbox_with_description(self, label_text, description_text, tooltip_text=None):
        """Create a checkbox with description on the same line."""
        container = QHBoxLayout()
        container.setSpacing(8)
        container.setContentsMargins(0, 2, 0, 2)
        
        checkbox = QCheckBox(label_text)
        checkbox.setStyleSheet("QCheckBox { font-size: 11px; }")
        checkbox.setMinimumWidth(175)
        if tooltip_text:
            checkbox.setToolTip(tooltip_text)
        container.addWidget(checkbox)
        
        if description_text:
            desc_label = QLabel(f"— {description_text}")
            desc_label.setStyleSheet("color: #888888; font-size: 10px;")
            desc_label.setWordWrap(True)
            container.addWidget(desc_label, 1)
        
        return checkbox, container
    
    def init_ui(self):
        """Initialize the user interface with three-column layout."""
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)
        
        # Three-column layout
        columns_layout = QHBoxLayout()
        columns_layout.setSpacing(30)
        
        # ==================== COLUMN 1: PROCESSING ====================
        col1 = QVBoxLayout()
        col1.setSpacing(4)
        
        self.first_line_speakers_cb, layout = self._create_checkbox_with_description(
            "First Line = Speaker", "Treats first line as speaker name", "First line of text is treated as speaker."
        )
        col1.addLayout(layout)
        
        self.inline401speakers_cb, layout = self._create_checkbox_with_description(
            "Inline 401 Speaker", "Detect Name「dialogue」 speaker format", "Extracts speaker from Name\u300cdialogue\u300d inline format in 401 lines."
        )
        col1.addLayout(layout)

        self.facename101_cb, layout = self._create_checkbox_with_description(
            "Face → Speaker", "Use face image as speaker name", "Uses face filenames to identify speakers."
        )
        col1.addLayout(layout)
        
        self.brflag_cb, layout = self._create_checkbox_with_description(
            "<br> Line Breaks", "Use br instead of newlines", "For games using <br> instead of \\n."
        )
        col1.addLayout(layout)
        
        self.fixtextwrap_cb, layout = self._create_checkbox_with_description(
            "Dazed Text Wrap", "Re-wrap text to fit dialogue box", "Re-wraps translated text based on width settings."
        )
        col1.addLayout(layout)
        
        self.ignoretltext_cb, layout = self._create_checkbox_with_description(
            "Skip Translated", "Skip lines without Japanese text", "Skips already translated content."
        )
        col1.addLayout(layout)

        self.tlsystemvariables_cb, layout = self._create_checkbox_with_description(
            "System Variables", "Translate variable names in System.json", "Translates the variables array in System.json. Can break stuff."
        )
        col1.addLayout(layout)

        self.tlsystemswitches_cb, layout = self._create_checkbox_with_description(
            "System Switches", "Translate switch names in System.json", "Translates the switches array in System.json."
        )
        col1.addLayout(layout)

        self.join408_cb, layout = self._create_checkbox_with_description(
            "Merge 408 Lines", "Join multi-line comments together", "Joins CODE408 lines into one string."
        )
        col1.addLayout(layout)

        col1.addStretch()
        
        # ==================== COLUMN 2: DIALOGUE ====================
        col2 = QVBoxLayout()
        col2.setSpacing(4)
        
        self.code401_cb, layout = self._create_checkbox_with_description(
            "Show Text (401)", "Standard dialogue text boxes", "Translates standard message window text."
        )
        col2.addLayout(layout)
        
        self.code101_cb, layout = self._create_checkbox_with_description(
            "Speakers (101)", "Speaker name field in Show Text", "Translates speaker names from Show Text header."
        )
        col2.addLayout(layout)
        
        self.code405_cb, layout = self._create_checkbox_with_description(
            "Scrolling Text (405)", "Credits, intros, scroll text", "Text that scrolls across the screen."
        )
        col2.addLayout(layout)
        
        self.code102_cb, layout = self._create_checkbox_with_description(
            "Choices (102)", "Player choice menus (Yes/No)", "Player choice selection menus."
        )
        col2.addLayout(layout)
        
        col2.addSpacing(15)
        
        # Extended Content in column 2
        col2.addWidget(create_section_label("📝 Extended Content"))
        
        self.code408_cb, layout = self._create_checkbox_with_description(
            "Comment Text (408)",
            "Recognized player-facing comment text",
            "Continuation lines from supported 108/408 comment blocks.",
        )
        self.code408_cb.setStyleSheet("QCheckBox { font-size: 11px; color: #ffaa66; }")
        col2.addLayout(layout)
        
        self.code122_cb, layout = self._create_checkbox_with_description(
            "Variables (122)", "Text stored in game variables", "String values in game variables."
        )
        col2.addLayout(layout)
        
        # Variable Range
        var_layout = QHBoxLayout()
        var_layout.setContentsMargins(20, 4, 0, 0)
        var_layout.setSpacing(8)
        lbl = QLabel("Variables ID Range:")
        lbl.setStyleSheet("color: #888; font-size: 10px;")
        var_layout.addWidget(lbl)
        from PyQt5.QtWidgets import QLineEdit
        from PyQt5.QtGui import QIntValidator
        
        self.code122_var_min_spin = QLineEdit()
        self.code122_var_min_spin.setValidator(QIntValidator(0, 99999))
        self.code122_var_min_spin.setText("0")
        self.code122_var_min_spin.setFixedWidth(60)
        self.code122_var_min_spin.setAlignment(Qt.AlignCenter)
        self.code122_var_min_spin.setStyleSheet("QLineEdit { padding: 4px; font-size: 11px; }")
        var_layout.addWidget(self.code122_var_min_spin)
        dash_lbl = QLabel("-")
        dash_lbl.setStyleSheet("font-size: 11px;")
        var_layout.addWidget(dash_lbl)
        self.code122_var_max_spin = QLineEdit()
        self.code122_var_max_spin.setValidator(QIntValidator(1, 99999))
        self.code122_var_max_spin.setText("2000")
        self.code122_var_max_spin.setFixedWidth(60)
        self.code122_var_max_spin.setAlignment(Qt.AlignCenter)
        self.code122_var_max_spin.setStyleSheet("QLineEdit { padding: 4px; font-size: 11px; }")
        var_layout.addWidget(self.code122_var_max_spin)
        var_layout.addStretch()
        col2.addLayout(var_layout)
        
        col2.addStretch()
        
        # ==================== COLUMN 3: ACTORS & SCRIPTS ====================
        col3 = QVBoxLayout()
        col3.setSpacing(4)
        
        self.code320_cb, layout = self._create_checkbox_with_description(
            "Change Name (320)", "Actor name change commands", "Dynamic character name changes."
        )
        col3.addLayout(layout)
        
        self.code324_cb, layout = self._create_checkbox_with_description(
            "Nickname (324)", "Actor nickname/title changes", "Character nickname changes."
        )
        col3.addLayout(layout)
        
        self.code325_cb, layout = self._create_checkbox_with_description(
            "Profile (325)", "Actor profile/biography text", "Profile/biography text."
        )
        col3.addLayout(layout)
        
        col3.addSpacing(15)
        
        col3.addWidget(create_section_label("🔧 Scripts & Plugins"))
        
        self.code355655_cb, layout = self._create_checkbox_with_description(
            "Scripts (355/655)", "Text in inline JavaScript calls", "Text within script commands."
        )
        col3.addLayout(layout)
        
        self.code356_cb, layout = self._create_checkbox_with_description(
            "Plugin MV (356)", "MV plugin command parameters", "MV-style plugin parameters."
        )
        col3.addLayout(layout)
        
        self.code357_cb, layout = self._create_checkbox_with_description(
            "Plugin MZ (357)", "MZ plugin command parameters", "MZ-style plugin parameters."
        )
        col3.addLayout(layout)
        
        self.code657_cb, layout = self._create_checkbox_with_description(
            "Plugin Ext (657)", "Extended multi-line plugin data", "Extended plugin command lines."
        )
        col3.addLayout(layout)
        
        self.code111_cb, layout = self._create_checkbox_with_description(
            "Conditionals (111)", "Text in conditional branch checks", "Text in conditional branches."
        )
        col3.addLayout(layout)
        
        self.code108_cb, layout = self._create_checkbox_with_description(
            "Comments (108)", "Event comment blocks (plugins)", "Comment blocks for plugins."
        )
        col3.addLayout(layout)
        
        col3.addStretch()
        
        processing_card = SectionCard(
            "Processing and speaker detection",
            "Choose how RPG Maker text is identified, attributed, wrapped, and skipped.",
        )
        processing_card.add_layout(col1)
        dialogue_card = SectionCard(
            "Dialogue and extended content",
            "Select player-visible event text and optional variable or comment sources.",
        )
        dialogue_card.add_layout(col2)
        script_card = SectionCard(
            "Actors, scripts, and plugins",
            "Enable advanced command text only when the game displays it to players.",
        )
        script_card.add_layout(col3)
        columns_layout.addWidget(processing_card, 1)
        columns_layout.addWidget(dialogue_card, 1)
        columns_layout.addWidget(script_card, 1)
        main_layout.addLayout(columns_layout, 1)
        
        # ==================== WORKFLOW GUIDE ====================
        workflow_card = SectionCard(
            "Recommended translation order",
            "Use this sequence when working outside the guided RPG Maker workflow.",
        )
        main_layout.addWidget(workflow_card)
        
        workflow_text = QLabel(
            "<table style='font-size: 11px; color: #aaa;' cellspacing='4'>"
            "<tr><td><b style='color:#007acc'>1.</b></td><td>Parse Speakers → Glossary</td>"
            "<td width='30'></td><td><b style='color:#007acc'>6.</b></td><td>Replace any \\\\n[0-999] variables with actor names</td></tr>"
            "<tr><td><b style='color:#007acc'>2.</b></td><td>Identify speaker genders (use Copilot with map files)</td>"
            "<td></td><td><b style='color:#007acc'>7.</b></td><td>Translate Maps & CommonEvents</td></tr>"
            "<tr><td><b style='color:#007acc'>3.</b></td><td>Translate Actors.json, MapInfos.json</td>"
            "<td></td><td><b style='color:#007acc'>8.</b></td><td>Edit plugins for menus/text</td></tr>"
            "<tr><td><b style='color:#007acc'>4.</b></td><td>Translate Items, System, Weapons, etc.</td>"
            "<td></td><td><b style='color:#007acc'>9.</b></td><td>Translate CODE 122 vars, 356 plugins as needed</td></tr>"
            "<tr><td><b style='color:#007acc'>5.</b></td><td>Find speaker names (101, brackets, first lines)</td>"
            "<td></td><td><b style='color:#007acc'>10.</b></td><td>Playtest → OCR → Search → Fix → Repeat</td></tr>"
            "</table>"
            "<div style='margin-top: 8px; color: #cc9944;'>⚠️ Some text (e.g. CODE 122 variables) may only update on a new save file.</div>"
        )
        workflow_text.setWordWrap(True)
        workflow_text.setTextFormat(Qt.RichText)
        workflow_text.setStyleSheet("background-color: #252525; padding: 12px; border-radius: 5px;")
        workflow_card.add_widget(workflow_text)
        
        # Reset button
        button_layout = QHBoxLayout()
        from gui.qt_icons import apply_button_icon

        self.reset_button = QPushButton()
        configure_action_button(self.reset_button, variant="quiet")
        apply_button_icon(
            self.reset_button, "🔄 Reset to defaults", color=COLORS.text_secondary
        )
        self.reset_button.clicked.connect(self.reset_to_defaults_with_message)
        self.reset_button.setMinimumHeight(32)
        self.reset_button.setMinimumWidth(160)
        self.reset_button.setStyleSheet("font-size: 11px;")
        button_layout.addWidget(self.reset_button)
        button_layout.addStretch()
        main_layout.addLayout(button_layout)
        
        self.setLayout(main_layout)
        
    def reset_to_defaults(self):
        """Reset all settings to default values."""
        # Temporarily disconnect signals to avoid multiple apply calls
        self.disconnect_auto_apply()
        # Prefer canonical defaults when available (imported as CANONICAL_DEFAULTS)
        defaults = CANONICAL_DEFAULTS if 'CANONICAL_DEFAULTS' in globals() and CANONICAL_DEFAULTS is not None else self.DEFAULT_CONFIG

        # Set the UI state from the defaults dictionary using set_config
        # This keeps the logic centralized and ensures correct types.
        self.set_config(defaults)

        # Reconnect signals and apply changes once
        self.connect_auto_apply()
        # Apply to module (silent)
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
            self.inline401speakers_cb.stateChanged.disconnect()
            self.facename101_cb.stateChanged.disconnect()
            self.brflag_cb.stateChanged.disconnect()
            self.fixtextwrap_cb.stateChanged.disconnect()
            self.ignoretltext_cb.stateChanged.disconnect()
            self.tlsystemvariables_cb.stateChanged.disconnect()
            self.tlsystemswitches_cb.stateChanged.disconnect()
            self.join408_cb.stateChanged.disconnect()
            
            # Main Codes
            self.code401_cb.stateChanged.disconnect()
            self.code405_cb.stateChanged.disconnect()
            self.code102_cb.stateChanged.disconnect()
            
            # Optional codes
            self.code101_cb.stateChanged.disconnect()
            self.code408_cb.stateChanged.disconnect()
            
            # Variable codes
            self.code122_cb.stateChanged.disconnect()
            self.code122_var_min_spin.editingFinished.disconnect()
            self.code122_var_max_spin.editingFinished.disconnect()
            
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
        self.inline401speakers_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.facename101_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.brflag_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.fixtextwrap_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.ignoretltext_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.tlsystemvariables_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.tlsystemswitches_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.join408_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))

        # Main Codes
        self.code401_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.code405_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.code102_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        
        # Optional codes
        self.code101_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.code408_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        
        # Variable codes
        self.code122_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.code122_var_min_spin.editingFinished.connect(lambda: self.apply_to_module(show_messages=False))
        self.code122_var_max_spin.editingFinished.connect(lambda: self.apply_to_module(show_messages=False))
        
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
            "INLINE401SPEAKERS": self.inline401speakers_cb.isChecked(),
            "FACENAME101": self.facename101_cb.isChecked(),
            "BRFLAG": self.brflag_cb.isChecked(),
            "FIXTEXTWRAP": self.fixtextwrap_cb.isChecked(),
            "IGNORETLTEXT": self.ignoretltext_cb.isChecked(),
            "TLSYSTEMVARIABLES": self.tlsystemvariables_cb.isChecked(),
            "TLSYSTEMSWITCHES": self.tlsystemswitches_cb.isChecked(),
            "JOIN408": self.join408_cb.isChecked(),

            # Main Codes
            "CODE401": self.code401_cb.isChecked(),
            "CODE405": self.code405_cb.isChecked(),
            "CODE102": self.code102_cb.isChecked(),
            
            # Optional codes
            "CODE101": self.code101_cb.isChecked(),
            "CODE408": self.code408_cb.isChecked(),
            
            # Variable codes
            "CODE122": self.code122_cb.isChecked(),
            "CODE122_VAR_MIN": int(self.code122_var_min_spin.text() or 0),
            "CODE122_VAR_MAX": int(self.code122_var_max_spin.text() or 2000),
            
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
        self.inline401speakers_cb.setChecked(config.get("INLINE401SPEAKERS", False))
        self.facename101_cb.setChecked(config.get("FACENAME101", False))
        self.brflag_cb.setChecked(config.get("BRFLAG", False))
        self.fixtextwrap_cb.setChecked(config.get("FIXTEXTWRAP", True))
        self.ignoretltext_cb.setChecked(config.get("IGNORETLTEXT", False))
        self.tlsystemvariables_cb.setChecked(config.get("TLSYSTEMVARIABLES", False))
        self.tlsystemswitches_cb.setChecked(config.get("TLSYSTEMSWITCHES", False))
        self.join408_cb.setChecked(config.get("JOIN408", False))

        # Main Codes
        self.code401_cb.setChecked(config.get("CODE401", True))
        self.code405_cb.setChecked(config.get("CODE405", True))
        self.code102_cb.setChecked(config.get("CODE102", True))
        
        # Optional codes
        self.code101_cb.setChecked(config.get("CODE101", False))
        self.code408_cb.setChecked(config.get("CODE408", False))
        
        # Variable codes
        self.code122_cb.setChecked(config.get("CODE122", False))
        self.code122_var_min_spin.setText(str(config.get("CODE122_VAR_MIN", 0)))
        self.code122_var_max_spin.setText(str(config.get("CODE122_VAR_MAX", 2000)))
        
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
        
        # Check if any Main Codes are enabled
        main_codes_enabled = (
            self.code401_cb.isChecked() or 
            self.code405_cb.isChecked() or 
            self.code102_cb.isChecked()
        )
        
        if not main_codes_enabled:
            warnings.append("No Main Codes are enabled. You may not get any translated content.")
            
        # Check for high-cost options
        if self.code408_cb.isChecked():
            warnings.append(
                "CODE 408 (supported comment text) is enabled. Only recognized player-facing "
                "108 markers and their continuation lines will be translated."
            )
            
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
        """Apply current configuration to the RPG Maker MV/MZ module."""
        try:
            config = self.get_config()
            module_filename = "rpgmakermvmz.py"
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
        """Load configuration from the RPG Maker MV/MZ module file."""
        if not self.config_integration:
            return

        try:
            module_filename = "rpgmakermvmz.py"
            module_path = Path("modules") / module_filename
            config = self.config_integration.read_current_config(module_path)
            if config:
                self.disconnect_auto_apply()
                try:
                    self.set_config(config)
                finally:
                    self.connect_auto_apply()
                QMessageBox.information(self, "Success", f"Configuration loaded from {module_filename}")
            else:
                QMessageBox.warning(self, "Warning", f"No configuration found in {module_filename}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load from module:\n{str(e)}")

    def refresh_from_module(self) -> bool:
        """Reload current module config into the UI without applying or showing dialogs."""
        if not self.config_integration:
            return False

        try:
            module_path = Path("modules") / "rpgmakermvmz.py"
            config = self.config_integration.read_current_config(module_path)
            if not config:
                return False

            self.disconnect_auto_apply()
            self.set_config(config)
            self.connect_auto_apply()
            return True
        except Exception:
            try:
                self.connect_auto_apply()
            except Exception:
                pass
            return False
