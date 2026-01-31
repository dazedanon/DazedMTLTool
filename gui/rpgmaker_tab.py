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
try:
    # Prefer importing the project's canonical defaults if available
    import set_defaults
    CANONICAL_DEFAULTS = getattr(set_defaults, 'DEFAULTS', None)
except Exception:
    CANONICAL_DEFAULTS = None


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
        "BRFLAG": False,
        "FIXTEXTWRAP": True,
        "IGNORETLTEXT": False,
        
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
                module_filename = "rpgmakermvmz.py" if self.engine != "ACE" else "rpgmakerace.py"
                module_path = Path("modules") / module_filename
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
        """Create a checkbox with an indented description label below it."""
        container = QVBoxLayout()
        container.setSpacing(1)
        container.setContentsMargins(0, 0, 0, 6)
        
        checkbox = QCheckBox(label_text)
        checkbox.setMinimumHeight(22)
        checkbox.setStyleSheet("QCheckBox { padding: 2px 0px; }")
        if tooltip_text:
            checkbox.setToolTip(tooltip_text)
        container.addWidget(checkbox)
        
        if description_text:
            desc_label = QLabel(description_text)
            desc_label.setWordWrap(True)
            desc_label.setMinimumHeight(16)
            desc_label.setStyleSheet("color: #888888; font-size: 9px; padding-left: 20px; padding-right: 5px;")
            container.addWidget(desc_label)
        
        return checkbox, container
    
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
            "Configure which event codes to translate. Only enable what you need to reduce translation time and costs."
        )
        description_label.setWordWrap(True)
        description_label.setStyleSheet("color: #888888; font-size: 10px; margin-bottom: 5px;")
        main_layout.addWidget(description_label)
        
        # Two-column layout for checkboxes
        columns_layout = QHBoxLayout()
        columns_layout.setSpacing(40)
        
        # LEFT COLUMN
        left_column = QVBoxLayout()
        left_column.setSpacing(3)
        
        # ===== DIALOGUE CONTENT SECTION =====
        left_column.addWidget(create_section_label("💬 Dialogue Content"))
        
        self.code401_cb, layout = self._create_checkbox_with_description(
            "Show Text (401)",
            "Main dialogue boxes - the primary text players see in conversation.",
            "Translates standard message window text. This is the core dialogue code."
        )
        left_column.addLayout(layout)
        
        self.code101_cb, layout = self._create_checkbox_with_description(
            "Text Setup / Speakers (101)",
            "Speaker names and face images shown with dialogue.",
            "Translates speaker names from the Show Text command's header. Enable if your game displays character names."
        )
        left_column.addLayout(layout)
        
        self.code405_cb, layout = self._create_checkbox_with_description(
            "Scrolling Text (405)",
            "Credits, story intros, and scrolling narrative text.",
            "Translates text that scrolls across the screen, commonly used for introductions or endings."
        )
        left_column.addLayout(layout)
        
        self.code102_cb, layout = self._create_checkbox_with_description(
            "Choice Options (102)",
            "Player choice menus like 'Yes/No' or dialogue options.",
            "Translates the text shown in player choice selection menus."
        )
        left_column.addLayout(layout)
        
        left_column.addSpacing(10)
        
        # ===== PROCESSING OPTIONS SECTION =====
        left_column.addWidget(create_section_label("⚙️ Processing Options"))
        
        self.first_line_speakers_cb, layout = self._create_checkbox_with_description(
            "Detect Speaker from First Line",
            "Treats the first line of dialogue as the speaker's name.",
            "Enable if your game embeds speaker names in the first line of text rather than using CODE101."
        )
        left_column.addLayout(layout)
        
        self.facename101_cb, layout = self._create_checkbox_with_description(
            "Map Face Images to Speakers",
            "Uses character face filenames to identify speakers.",
            "Maps face image filenames to speaker names for better context in translations."
        )
        left_column.addLayout(layout)
        
        self.brflag_cb, layout = self._create_checkbox_with_description(
            "Use <br> for Line Breaks",
            "Parse <br> tags instead of \\n for newlines.",
            "Some games use HTML-style <br> tags for line breaks instead of standard newline characters."
        )
        left_column.addLayout(layout)
        
        self.fixtextwrap_cb, layout = self._create_checkbox_with_description(
            "Auto-Wrap Translated Text",
            "Automatically adjusts line lengths to fit text boxes.",
            "Re-wraps translated text to match the game's text box width settings (WIDTH/NOTEWIDTH)."
        )
        left_column.addLayout(layout)
        
        self.ignoretltext_cb, layout = self._create_checkbox_with_description(
            "Skip Already-Translated Text",
            "Ignores text that doesn't match the source language.",
            "Skips text that appears to already be translated (no Japanese characters detected)."
        )
        left_column.addLayout(layout)

        self.join408_cb, layout = self._create_checkbox_with_description(
            "Merge Comment Lines (408)",
            "Combines multi-line comments into single translation units.",
            "Joins consecutive CODE408 lines into one string, similar to how CODE401 dialogue is handled."
        )
        left_column.addLayout(layout)

        self.speakers408_cb, layout = self._create_checkbox_with_description(
            "Speaker Detection in Comments",
            "Apply speaker parsing to comment text.",
            "Enables the same speaker detection logic used for dialogue (401) on comment blocks (408)."
        )
        left_column.addLayout(layout)
        # Only show SPEAKERS408 for ACE engine (rpgmakerace.py)
        if self.engine != "ACE":
            self.speakers408_cb.hide()
        
        left_column.addStretch()
        
        # RIGHT COLUMN  
        right_column = QVBoxLayout()
        right_column.setSpacing(3)
        
        # ===== EXTENDED CONTENT SECTION =====
        right_column.addWidget(create_section_label("📝 Extended Content"))
        
        self.code408_cb, layout = self._create_checkbox_with_description(
            "Comments / Event Text (408)",
            "⚠️ Plugin-based dialogue and developer comments. Can be costly!",
            "Translates comment text that some plugins use for displaying dialogue. Enable only if needed."
        )
        self.code408_cb.setStyleSheet("QCheckBox { color: #ffaa66; }")
        right_column.addLayout(layout)
        
        self.code122_cb, layout = self._create_checkbox_with_description(
            "Control Variables (122)",
            "Text stored in game variables for dynamic content.",
            "Translates string values assigned to variables. Used for dynamic dialogue or quest objectives."
        )
        right_column.addLayout(layout)
        
        # CODE122 Variable Range
        var_range_layout = QHBoxLayout()
        var_range_layout.setContentsMargins(20, 0, 0, 0)  # Indent to show it's related to CODE122
        
        var_range_label = QLabel("Variable ID Range:")
        var_range_label.setToolTip("Only variables with IDs in this range will be translated.\nUseful for limiting translation to specific game variables.")
        var_range_label.setStyleSheet("color: #888888; font-size: 10px;")
        var_range_layout.addWidget(var_range_label)
        
        self.code122_var_min_spin = QSpinBox()
        self.code122_var_min_spin.setRange(0, 99999)
        self.code122_var_min_spin.setValue(0)
        self.code122_var_min_spin.setMinimumWidth(70)
        self.code122_var_min_spin.setToolTip("Minimum variable ID (inclusive)")
        var_range_layout.addWidget(self.code122_var_min_spin)
        
        var_range_layout.addWidget(QLabel("to"))
        
        self.code122_var_max_spin = QSpinBox()
        self.code122_var_max_spin.setRange(1, 99999)
        self.code122_var_max_spin.setValue(2000)
        self.code122_var_max_spin.setMinimumWidth(70)
        self.code122_var_max_spin.setToolTip("Maximum variable ID (exclusive)")
        var_range_layout.addWidget(self.code122_var_max_spin)
        
        var_range_layout.addStretch()
        right_column.addLayout(var_range_layout)
        
        right_column.addSpacing(10)
        
        # ===== ACTOR CHANGES SECTION =====
        right_column.addWidget(create_section_label("👤 Actor Modifications"))
        
        self.code320_cb, layout = self._create_checkbox_with_description(
            "Change Actor Name (320)",
            "Commands that rename characters during gameplay.",
            "Translates text used when the game changes a character's display name via event commands."
        )
        right_column.addLayout(layout)
        
        self.code324_cb, layout = self._create_checkbox_with_description(
            "Change Nickname (324)",
            "Commands that change character titles/nicknames.",
            "Translates nickname/title changes like 'Hero' or 'The Brave' assigned during gameplay."
        )
        right_column.addLayout(layout)
        
        self.code325_cb, layout = self._create_checkbox_with_description(
            "Change Profile (325)",
            "Commands that update character biography text.",
            "Translates profile/biography text updates for characters shown in status screens."
        )
        right_column.addLayout(layout)
        
        right_column.addSpacing(10)
        
        # ===== SCRIPTS & PLUGINS SECTION =====
        right_column.addWidget(create_section_label("🔧 Scripts & Plugins"))
        
        self.code355655_cb, layout = self._create_checkbox_with_description(
            "Script Calls (355/655)",
            "Inline JavaScript code that may contain text strings.",
            "Translates text within script commands. Use carefully - may affect code execution."
        )
        right_column.addLayout(layout)
        
        self.code356_cb, layout = self._create_checkbox_with_description(
            "Plugin Commands MV (356)",
            "MV-style plugin commands with text parameters.",
            "Translates parameters passed to plugins. Common in games with custom dialogue systems."
        )
        right_column.addLayout(layout)
        
        self.code357_cb, layout = self._create_checkbox_with_description(
            "Plugin Commands MZ (357)",
            "MZ-style plugin commands with structured data.",
            "Translates the newer MZ plugin command format introduced in RPG Maker MZ."
        )
        right_column.addLayout(layout)
        
        self.code657_cb, layout = self._create_checkbox_with_description(
            "Plugin Commands Extended (657)",
            "Additional plugin command continuation lines.",
            "Translates extended plugin command data that spans multiple lines."
        )
        right_column.addLayout(layout)
        
        right_column.addSpacing(10)
        
        # ===== CONDITIONAL & COMMENTS SECTION =====
        right_column.addWidget(create_section_label("🔀 Logic & Comments"))
        
        self.code111_cb, layout = self._create_checkbox_with_description(
            "Conditional Branches (111)",
            "Text in if/else conditions and script checks.",
            "Translates text within conditional branch commands. May contain dialogue triggers."
        )
        right_column.addLayout(layout)
        
        self.code108_cb, layout = self._create_checkbox_with_description(
            "Developer Comments (108)",
            "Event comments often used by plugins for config.",
            "Translates comment blocks. Many plugins use comments for dialogue or notetags."
        )
        right_column.addLayout(layout)
        
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
            self.facename101_cb.stateChanged.disconnect()
            self.brflag_cb.stateChanged.disconnect()
            self.fixtextwrap_cb.stateChanged.disconnect()
            self.ignoretltext_cb.stateChanged.disconnect()
            self.join408_cb.stateChanged.disconnect()
            if self.engine == "ACE":
                self.speakers408_cb.stateChanged.disconnect()
            
            # Main Codes
            self.code401_cb.stateChanged.disconnect()
            self.code405_cb.stateChanged.disconnect()
            self.code102_cb.stateChanged.disconnect()
            
            # Optional codes
            self.code101_cb.stateChanged.disconnect()
            self.code408_cb.stateChanged.disconnect()
            
            # Variable codes
            self.code122_cb.stateChanged.disconnect()
            self.code122_var_min_spin.valueChanged.disconnect()
            self.code122_var_max_spin.valueChanged.disconnect()
            
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
        self.brflag_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.fixtextwrap_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.ignoretltext_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.join408_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        if self.engine == "ACE":
            self.speakers408_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))

        # Main Codes
        self.code401_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.code405_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.code102_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        
        # Optional codes
        self.code101_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.code408_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        
        # Variable codes
        self.code122_cb.stateChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.code122_var_min_spin.valueChanged.connect(lambda: self.apply_to_module(show_messages=False))
        self.code122_var_max_spin.valueChanged.connect(lambda: self.apply_to_module(show_messages=False))
        
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
            "BRFLAG": self.brflag_cb.isChecked(),
            "FIXTEXTWRAP": self.fixtextwrap_cb.isChecked(),
            "IGNORETLTEXT": self.ignoretltext_cb.isChecked(),
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
            "CODE122_VAR_MIN": self.code122_var_min_spin.value(),
            "CODE122_VAR_MAX": self.code122_var_max_spin.value(),
            
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
        
        # Only include SPEAKERS408 for ACE engine
        if self.engine == "ACE":
            config["SPEAKERS408"] = self.speakers408_cb.isChecked()
            
        return config
        
    def set_config(self, config):
        """Set configuration from dictionary."""
        # General settings
        self.first_line_speakers_cb.setChecked(config.get("FIRSTLINESPEAKERS", False))
        self.facename101_cb.setChecked(config.get("FACENAME101", False))
        self.brflag_cb.setChecked(config.get("BRFLAG", False))
        self.fixtextwrap_cb.setChecked(config.get("FIXTEXTWRAP", True))
        self.ignoretltext_cb.setChecked(config.get("IGNORETLTEXT", False))
        self.join408_cb.setChecked(config.get("JOIN408", False))
        
        # Only set SPEAKERS408 for ACE engine
        if self.engine == "ACE":
            self.speakers408_cb.setChecked(config.get("SPEAKERS408", False))

        # Main Codes
        self.code401_cb.setChecked(config.get("CODE401", True))
        self.code405_cb.setChecked(config.get("CODE405", True))
        self.code102_cb.setChecked(config.get("CODE102", True))
        
        # Optional codes
        self.code101_cb.setChecked(config.get("CODE101", False))
        self.code408_cb.setChecked(config.get("CODE408", False))
        
        # Variable codes
        self.code122_cb.setChecked(config.get("CODE122", False))
        self.code122_var_min_spin.setValue(config.get("CODE122_VAR_MIN", 0))
        self.code122_var_max_spin.setValue(config.get("CODE122_VAR_MAX", 2000))
        
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
