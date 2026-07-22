"""
Configuration Tab - Handles environment variables, global settings, and engine configurations
"""

import os
from pathlib import Path
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit,
    QSpinBox, QDoubleSpinBox, QComboBox, QPushButton, QGroupBox,
    QLabel, QFileDialog, QMessageBox, QScrollArea, QTextEdit,
    QCheckBox, QApplication, QTabWidget, QFrame, QStackedWidget, QToolButton,
    QMenu, QDialog, QDialogButtonBox, QSizePolicy,
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer, QThread
from PyQt5.QtGui import QIcon
from dotenv import load_dotenv, set_key, dotenv_values

from gui.rpgmaker_tab import RPGMakerTab
from gui.wolf_tab import WolfTab
from gui.csv_tab import CSVTab
from gui.srpg_tab import SRPGTab
from util import api_keys as api_key_vault


class ModelFetchThread(QThread):
    """Background thread that fetches model lists from OpenAI, Anthropic, or Gemini."""
    models_fetched = pyqtSignal(list)
    fetch_error = pyqtSignal(str)

    # Fallback list shown when no API key is set or a fetch fails
    DEFAULTS = [
        "gpt-4.1-mini", "gpt-4.1", "gpt-4o", "gpt-4o-mini",
        "o3", "o4-mini",
        "claude-opus-4-5", "claude-sonnet-4-6", "claude-sonnet-4-5", "claude-haiku-4-5",
        "gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-pro",
        "deepseek-chat",
        "mistral-medium-3.5",  # free-tier recommendation; avoid -latest (older 3.1)
    ]

    def __init__(self, api_key, api_url, parent=None):
        super().__init__(parent)
        self.api_key = api_key
        self.api_url = api_url.strip()

    def run(self):
        models = []
        errors = []
        _url = self.api_url.lower()
        # Only attempt each provider's fetcher when the configured URL matches.
        # Avoids sending a DeepSeek (or other) key to Anthropic and getting a
        # spurious 401 authentication error.
        fetchers = [self._fetch_openai]
        if not _url or "anthropic" in _url:
            fetchers.append(self._fetch_anthropic)
        if not _url or "googleapis" in _url or "gemini" in _url:
            fetchers.append(self._fetch_gemini)
        for fetcher in fetchers:
            try:
                models.extend(fetcher())
            except Exception as exc:
                errors.append(str(exc))
        if models:
            self.models_fetched.emit(sorted(set(models)))
        else:
            self.fetch_error.emit("\n".join(errors))

    def _fetch_openai(self):
        import openai
        kwargs = {"api_key": self.api_key}
        if self.api_url:
            kwargs["base_url"] = self.api_url
        client = openai.OpenAI(**kwargs)
        all_models = [m.id for m in client.models.list()]
        # When using a custom URL (non-OpenAI provider like DeepSeek), return all
        # model IDs unfiltered.  For the default OpenAI endpoint, keep only the
        # GPT / o-series models to avoid a cluttered list.
        if self.api_url:
            return sorted(all_models)
        prefixes = ("gpt-", "o1", "o2", "o3", "o4", "chatgpt")
        return sorted(m for m in all_models if any(m.lower().startswith(p) for p in prefixes))

    def _fetch_anthropic(self):
        import anthropic
        client = anthropic.Anthropic(api_key=self.api_key)
        return sorted(m.id for m in client.models.list(limit=100))

    def _fetch_gemini(self):
        import openai
        base = self.api_url or "https://generativelanguage.googleapis.com/v1beta/openai/"
        client = openai.OpenAI(api_key=self.api_key, base_url=base)
        return sorted(
            m.id for m in client.models.list()
            if "gemini" in m.id.lower()
        )


def create_section_header(title):
    """Create a clean section header without boxes."""
    from gui.qt_icons import make_section_header

    return make_section_header(
        title,
        "QLabel {"
        "font-size: 13px;"
        "font-weight: bold;"
        "color: #007acc;"
        "padding: 8px 0px 5px 0px;"
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


class ApiKeyEditDialog(QDialog):
    """Dialog to create or overwrite a named API key (secret entered once)."""

    def __init__(self, parent=None, initial_name: str = ""):
        super().__init__(parent)
        self.setWindowTitle("API Key")
        self.setModal(True)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.name_edit = QLineEdit(initial_name)
        self.name_edit.setPlaceholderText("e.g. OpenAI, DeepSeek, Work")
        form.addRow("Name:", self.name_edit)

        self.secret_edit = QLineEdit()
        self.secret_edit.setEchoMode(QLineEdit.Password)
        self.secret_edit.setPlaceholderText("Paste API key secret")
        form.addRow("Secret:", self.secret_edit)

        layout.addLayout(form)

        hint = QLabel(
            "The name appears in the dropdown. The secret is stored locally "
            "and is never shown again in the main Config page."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888888; font-size: 11px;")
        layout.addWidget(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._name = ""
        self._secret = ""
        self.secret_edit.setFocus()

    def _accept_if_valid(self):
        name = self.name_edit.text().strip()
        secret = self.secret_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "API Key", "Enter a name for this key.")
            self.name_edit.setFocus()
            return
        if not secret:
            QMessageBox.warning(self, "API Key", "Enter the API key secret.")
            self.secret_edit.setFocus()
            return
        self._name = name
        self._secret = secret
        self.accept()

    def result_values(self) -> tuple[str, str]:
        return self._name, self._secret


class ConfigTab(QWidget):
    """Configuration tab for managing environment variables, global settings, and engine configs."""
    
    config_changed = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        self.env_file_path = Path(".env")
        # Initialize UI first so widgets/tabs exist for resetting or loading
        self.init_ui()

        # Timer for autosave indicator (created after init_ui so autosave_label exists)
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.timeout.connect(self._clear_autosave_indicator)

        # If a .env file doesn't exist, show defaults in the UI
        # (prevents showing stale values from the process/OS environment)
        if not self.env_file_path.exists():
            self.reset_to_defaults()
        else:
            self.load_from_env()
        self._update_model_placeholder()
        
        # Connect auto-save after initial load
        self.connect_auto_save()

        # Fetch latest models in the background once the UI is shown
        QTimer.singleShot(0, lambda: self.fetch_models(silent=True))

    def _is_nvidia_api_url(self, api_url: str) -> bool:
        """Return True when the configured URL points to Nvidia's OpenAI-compatible API."""
        return "integrate.api.nvidia.com" in (api_url or "").strip().lower()

    def _update_model_placeholder(self):
        """Show a manual model-entry hint only when Nvidia API is selected."""
        line_edit = self.model_combo.lineEdit()
        if not line_edit:
            return
        if self._is_nvidia_api_url(self.api_url_edit.text()):
            line_edit.setPlaceholderText("Enter Nvidia model name (e.g., deepseek-ai/deepseek-v4-pro)")
        else:
            line_edit.setPlaceholderText("")
        
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
        btn_mvmz = self.create_nav_button("🎮", "RPG Maker MV/MZ", engine_key="mvmz")
        btn_mvmz.clicked.connect(lambda: self.switch_page(1))
        nav_layout.addWidget(btn_mvmz)
        self.nav_buttons.append(btn_mvmz)
        
        # Wolf RPG button
        btn_wolf = self.create_nav_button("🐺", "Wolf RPG", engine_key="wolf")
        btn_wolf.clicked.connect(lambda: self.switch_page(2))
        nav_layout.addWidget(btn_wolf)
        self.nav_buttons.append(btn_wolf)
        
        # CSV button
        btn_csv = self.create_nav_button("📄", "CSV")
        btn_csv.clicked.connect(lambda: self.switch_page(3))
        nav_layout.addWidget(btn_csv)
        self.nav_buttons.append(btn_csv)

        # SRPG Studio button
        btn_srpg = self.create_nav_button("⚔️", "SRPG Studio", engine_key="srpg")
        btn_srpg.clicked.connect(lambda: self.switch_page(4))
        nav_layout.addWidget(btn_srpg)
        self.nav_buttons.append(btn_srpg)
        
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
        
        # Page 3: Wolf RPG Engine
        self.wolf_tab = WolfTab()
        self.content_stack.addWidget(self.wolf_tab)
        
        # Page 4: CSV Settings
        self.csv_tab = CSVTab()
        self.content_stack.addWidget(self.csv_tab)

        # Page 5: SRPG Studio Engine
        self.srpg_tab = SRPGTab()
        self.content_stack.addWidget(self.srpg_tab)
        
        # Add navigation bar and content to main layout
        main_layout.addWidget(nav_bar)
        main_layout.addWidget(self.content_stack)
        self.setLayout(main_layout)
        
        # Select first page by default
        self.switch_page(0)
    
    def create_nav_button(self, icon_text, tooltip, engine_key=None):
        """Create a navigation button for the top bar."""
        from gui.platform_glyph import configure_nav_toolbutton

        btn = QToolButton()
        btn.setToolTip(tooltip)
        btn.setFixedSize(50, 50)
        btn.setCheckable(True)
        configure_nav_toolbutton(
            btn, icon_text, horizontal=True, engine_key=engine_key,
        )
        return btn
    
    def switch_page(self, index):
        """Switch to the specified page and update button states."""
        self.content_stack.setCurrentIndex(index)
        self._refresh_engine_config_page(index)
        
        # Update button checked states
        for i, btn in enumerate(self.nav_buttons):
            btn.setChecked(i == index)

    def _refresh_engine_config_page(self, index):
        """Refresh engine config pages from their module files when shown."""
        engine_pages = {
            1: getattr(self, "mvmz_tab", None),
        }
        page = engine_pages.get(index)
        if page is not None and hasattr(page, "refresh_from_module"):
            page.refresh_from_module()
    
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

        _api_field_width = 364
        _api_btn_style = """
            QToolButton {
                background-color: #3e3e42;
                color: #cccccc;
                border: 1px solid #555555;
                border-radius: 3px;
                padding: 3px 6px;
            }
            QToolButton:hover { background-color: #505050; }
            QToolButton::menu-indicator { image: none; }
        """

        api_url_widget = QWidget()
        api_url_layout = QHBoxLayout(api_url_widget)
        api_url_layout.setContentsMargins(0, 0, 0, 0)
        api_url_layout.setSpacing(4)

        self.api_url_edit = QLineEdit()
        self.api_url_edit.setPlaceholderText("Leave blank for OpenAI API")
        self.api_url_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        api_url_preset_btn = QToolButton()
        api_url_preset_btn.setText("Presets ▾")
        api_url_preset_btn.setFixedWidth(75)
        api_url_preset_btn.setPopupMode(QToolButton.InstantPopup)
        api_url_preset_btn.setStyleSheet(_api_btn_style)

        api_url_menu = QMenu(api_url_preset_btn)
        _url_presets = [
            ("OpenAI", "https://api.openai.com/v1"),
            ("Claude (Anthropic)", "https://api.anthropic.com/v1"),
            ("Gemini", "https://generativelanguage.googleapis.com/v1beta/openai/"),
            ("DeepSeek", "https://api.deepseek.com/v1/"),
            ("Mistral", "https://api.mistral.ai/v1/"),
            ("Nvidia", "https://integrate.api.nvidia.com/v1/"),
        ]
        for _name, _url in _url_presets:
            _action = api_url_menu.addAction(_name)
            _action.triggered.connect(lambda checked, u=_url: self.api_url_edit.setText(u))
        api_url_preset_btn.setMenu(api_url_menu)
        self.api_url_edit.textChanged.connect(self._update_model_placeholder)

        api_url_layout.addWidget(self.api_url_edit, 1)
        api_url_layout.addWidget(api_url_preset_btn)
        api_url_widget.setFixedWidth(_api_field_width)

        api_form.addRow(api_url_label, api_url_widget)
        
        api_key_label = QLabel("API Key:")
        api_key_label.setFixedWidth(150)
        api_key_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        api_key_widget = QWidget()
        api_key_layout = QHBoxLayout(api_key_widget)
        api_key_layout.setContentsMargins(0, 0, 0, 0)
        api_key_layout.setSpacing(4)

        self.api_key_combo = QComboBox()
        self.api_key_combo.setEditable(False)
        self.api_key_combo.setToolTip(
            "Select a saved API key by name. Secrets stay hidden after you add them."
        )
        self.api_key_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.api_key_new_btn = QToolButton()
        self.api_key_new_btn.setText("New")
        self.api_key_new_btn.setToolTip("Add or update a named API key")
        self.api_key_new_btn.setFixedWidth(48)
        self.api_key_new_btn.clicked.connect(self._on_api_key_new)

        self.api_key_delete_btn = QToolButton()
        self.api_key_delete_btn.setText("Delete")
        self.api_key_delete_btn.setToolTip("Remove the selected API key")
        self.api_key_delete_btn.setFixedWidth(56)
        self.api_key_delete_btn.clicked.connect(self._on_api_key_delete)

        for btn in (self.api_key_new_btn, self.api_key_delete_btn):
            btn.setStyleSheet(_api_btn_style)

        api_key_layout.addWidget(self.api_key_combo, 1)
        api_key_layout.addWidget(self.api_key_new_btn)
        api_key_layout.addWidget(self.api_key_delete_btn)
        api_key_widget.setFixedWidth(_api_field_width)
        api_form.addRow(api_key_label, api_key_widget)
        
        model_label = QLabel("Model:")
        model_label.setFixedWidth(150)
        model_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        model_widget = QWidget()
        model_layout = QHBoxLayout(model_widget)
        model_layout.setContentsMargins(0, 0, 0, 0)
        model_layout.setSpacing(4)

        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.addItems(ModelFetchThread.DEFAULTS)
        self.model_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.model_refresh_btn = QToolButton()
        self.model_refresh_btn.setText("⟳")
        self.model_refresh_btn.setToolTip("Fetch latest models from the configured API")
        self.model_refresh_btn.setFixedWidth(28)
        self.model_refresh_btn.setStyleSheet(_api_btn_style)
        self.model_refresh_btn.clicked.connect(lambda: self.fetch_models(silent=False))

        model_layout.addWidget(self.model_combo, 1)
        model_layout.addWidget(self.model_refresh_btn)
        model_widget.setFixedWidth(_api_field_width)

        api_form.addRow(model_label, model_widget)
        
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

        quotes_label = QLabel("Convert Quotes:")
        quotes_label.setFixedWidth(150)
        quotes_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.convert_quotes_cb = QCheckBox('Convert 「」 / 『』 to ""')
        self.convert_quotes_cb.setChecked(True)
        self.convert_quotes_cb.setToolTip(
            "When enabled, Japanese corner brackets 「」 and 『』 are replaced "
            'with ASCII double quotes "" in translated output (and on RPG Maker '
            "source text before translation).\n\n"
            "Leaving this on is recommended - the AI often fails to keep 「」 "
            "consistent across lines."
        )
        format_form.addRow(quotes_label, self.convert_quotes_cb)
        
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
        right_column.addWidget(create_horizontal_line())

        # UI Settings Section
        right_column.addWidget(create_section_header("🖥️ UI Settings"))
        ui_form = QFormLayout()
        ui_form.setSpacing(6)
        ui_form.setContentsMargins(0, 0, 0, 12)
        ui_form.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        ui_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        font_scale_label = QLabel("Font Scale:")
        font_scale_label.setFixedWidth(150)
        font_scale_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.font_scale_spin = QDoubleSpinBox()
        self.font_scale_spin.setButtonSymbols(QDoubleSpinBox.NoButtons)
        self.font_scale_spin.setRange(0.5, 3.0)
        self.font_scale_spin.setSingleStep(0.1)
        self.font_scale_spin.setDecimals(1)
        self.font_scale_spin.setValue(1.0)
        self.font_scale_spin.setSuffix("x")
        self.font_scale_spin.setFixedWidth(120)
        self.font_scale_spin.setToolTip(
            "Scale the application font size.\n"
            "1.0 = default, 1.5 = 50% larger, 2.0 = double size.\n"
            "Takes effect immediately on save."
        )
        ui_form.addRow(font_scale_label, self.font_scale_spin)

        right_column.addLayout(ui_form)

        # Game Update defaults (written into gameupdate/patch-config.txt on copy)
        right_column.addWidget(create_section_header("📦 Game Update Defaults"))
        gu_form = QFormLayout()
        gu_form.setSpacing(6)
        gu_form.setContentsMargins(0, 0, 0, 12)
        gu_form.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        gu_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        def _gu_label(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setFixedWidth(150)
            lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            return lbl

        self.gu_forge_combo = QComboBox()
        self.gu_forge_combo.addItem("GitLab / gitgud", "gitlab")
        self.gu_forge_combo.addItem("GitHub", "github")
        self.gu_forge_combo.addItem("Forgejo / Gitea", "forgejo")
        self.gu_forge_combo.setFixedWidth(220)
        self.gu_forge_combo.setToolTip(
            "Where your patch repos live. Used when Step 1 writes patch-config.txt."
        )
        self.gu_forge_combo.currentIndexChanged.connect(self._on_gu_forge_changed)
        gu_form.addRow(_gu_label("Forge:"), self.gu_forge_combo)

        self.gu_host_edit = QLineEdit()
        self.gu_host_edit.setFixedWidth(220)
        self.gu_host_edit.setPlaceholderText("gitgud.io")
        self.gu_host_edit.setToolTip(
            "Hostname only (no https://). Leave blank to use the forge default."
        )
        gu_form.addRow(_gu_label("Host:"), self.gu_host_edit)

        self.gu_username_edit = QLineEdit()
        self.gu_username_edit.setFixedWidth(220)
        self.gu_username_edit.setPlaceholderText("your-org-or-user")
        self.gu_username_edit.setToolTip(
            "Owner / org / group for all patch repos. Set once; rarely changes."
        )
        gu_form.addRow(_gu_label("Org / username:"), self.gu_username_edit)

        self.gu_branch_edit = QLineEdit()
        self.gu_branch_edit.setFixedWidth(220)
        self.gu_branch_edit.setPlaceholderText("main")
        self.gu_branch_edit.setToolTip("Default branch to track (usually main or master).")
        gu_form.addRow(_gu_label("Branch:"), self.gu_branch_edit)

        gu_hint = QLabel(
            "Copied into each game's gameupdate/patch-config.txt when you run "
            "Copy gameupdate/ (repo= is still per-game)."
        )
        gu_hint.setWordWrap(True)
        gu_hint.setStyleSheet("color:#7a7a7a;font-size:11px;")
        right_column.addLayout(gu_form)
        right_column.addWidget(gu_hint)
        right_column.addStretch()
        
        # Add columns to layout
        columns_layout.addLayout(left_column, 1)
        columns_layout.addLayout(right_column, 1)
        
        layout.addLayout(columns_layout)
        
        # Add buttons at the bottom of General Settings tab
        layout.addSpacing(15)
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)
        
        from gui import qt_icons

        reset_button = QPushButton()
        qt_icons.apply_button_icon(reset_button, "🔄 Reset to Defaults", color="#cccccc")
        reset_button.clicked.connect(self.reset_to_defaults_with_save)
        reset_button.setMinimumHeight(32)

        save_button = QPushButton()
        qt_icons.apply_button_icon(save_button, "💾 Save Changes", color="#cccccc")
        save_button.clicked.connect(lambda: self.save_to_env(show_message=True))
        save_button.setMinimumHeight(32)

        self.autosave_label = QLabel("")
        self.autosave_label.setStyleSheet("color: #4ec9b0; font-weight: bold;")

        button_layout.addWidget(reset_button)
        button_layout.addWidget(save_button)
        button_layout.addSpacing(10)
        button_layout.addWidget(self.autosave_label)
        button_layout.addStretch()
        
        layout.addLayout(button_layout)
        
        content.setLayout(layout)
        widget.setLayout(QVBoxLayout())
        widget.layout().setContentsMargins(0, 0, 0, 0)
        widget.layout().addWidget(content)
        return widget

    # ------------------------------------------------------------------
    # Model fetching
    # ------------------------------------------------------------------

    def _active_api_key_secret(self) -> str:
        """Return the secret for the currently selected named key."""
        name = self.api_key_combo.currentText().strip()
        if not name:
            return api_key_vault.get_active_secret()
        secret = api_key_vault.get_secret(name)
        return secret if secret is not None else ""

    def _refresh_api_key_combo(self, preferred: str | None = None):
        """Reload named keys into the dropdown without firing autosave."""
        api_key_vault.ensure_vault(env_path=self.env_file_path)
        names = api_key_vault.list_names()
        active = preferred or api_key_vault.get_active_name()
        self.api_key_combo.blockSignals(True)
        self.api_key_combo.clear()
        if names:
            self.api_key_combo.addItems(names)
            if active and active in names:
                self.api_key_combo.setCurrentText(active)
            else:
                self.api_key_combo.setCurrentIndex(0)
        else:
            self.api_key_combo.setPlaceholderText("No keys saved - click New")
        self.api_key_combo.blockSignals(False)
        self.api_key_delete_btn.setEnabled(bool(names))

    def _on_api_key_selected(self, _name: str = ""):
        """Persist dropdown selection as the active vault key and mirror to .env."""
        name = self.api_key_combo.currentText().strip()
        if not name:
            return
        try:
            api_key_vault.set_active(name)
            api_key_vault.sync_active_to_env(env_path=self.env_file_path)
        except KeyError:
            return
        self.auto_save()

    def _on_api_key_new(self):
        """Open dialog to create or overwrite a named API key."""
        current = self.api_key_combo.currentText().strip()
        dialog = ApiKeyEditDialog(self, initial_name=current)
        if dialog.exec_() != QDialog.Accepted:
            return
        name, secret = dialog.result_values()
        try:
            api_key_vault.upsert_key(name, secret, make_active=True)
            api_key_vault.sync_active_to_env(env_path=self.env_file_path)
        except ValueError as exc:
            QMessageBox.warning(self, "API Key", str(exc))
            return
        self._refresh_api_key_combo(preferred=name)
        self.auto_save()

    def _on_api_key_delete(self):
        """Delete the selected named key after confirmation."""
        name = self.api_key_combo.currentText().strip()
        if not name:
            return
        reply = QMessageBox.question(
            self,
            "Delete API Key",
            f'Remove saved key "{name}"?\nThe secret will be deleted from this machine.',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        api_key_vault.delete_key(name)
        api_key_vault.sync_active_to_env(env_path=self.env_file_path)
        self._refresh_api_key_combo()
        self.auto_save()

    def fetch_models(self, silent=False):
        """Kick off background fetch of models from the configured API."""
        api_key = self._active_api_key_secret()
        api_url = self.api_url_edit.text().strip()

        if not api_key:
            if not silent:
                QMessageBox.warning(
                    self, "No API Key",
                    "Please add or select an API key before fetching models."
                )
            return

        self.model_refresh_btn.setEnabled(False)
        self.model_refresh_btn.setText("…")

        self._model_fetch_thread = ModelFetchThread(api_key, api_url, parent=self)
        self._model_fetch_thread.models_fetched.connect(self._on_models_fetched)
        self._model_fetch_thread.fetch_error.connect(self._on_models_fetch_error)
        self._model_fetch_thread.finished.connect(lambda: None)  # keep GC away
        self._model_fetch_thread.start()

    def _on_models_fetched(self, models):
        """Populate the model dropdown with freshly fetched models."""
        current = self.model_combo.currentText()
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.addItems(models)
        self.model_combo.setCurrentText(current)  # restore whatever was typed
        self.model_combo.blockSignals(False)
        self.model_refresh_btn.setEnabled(True)
        self.model_refresh_btn.setText("⟳")

    def _on_models_fetch_error(self, error):
        """Restore button and show error."""
        self.model_refresh_btn.setEnabled(True)
        self.model_refresh_btn.setText("⟳")
        QMessageBox.warning(
            self, "Fetch Error",
            f"Could not fetch models from the API:\n{error}"
        )

    def mousePressEvent(self, event):
        """Clear focus from any text/spin box when clicking on empty space,
        which triggers editingFinished and therefore auto-save."""
        focused = QApplication.focusWidget()
        if focused and isinstance(focused, (QLineEdit, QSpinBox, QDoubleSpinBox)):
            focused.clearFocus()
        super().mousePressEvent(event)

    def showEvent(self, event):
        """Reload values from disk every time this tab becomes visible."""
        super().showEvent(event)
        if self.env_file_path.exists():
            self.disconnect_auto_save()
            self.load_from_env()
            self.connect_auto_save()
        self._refresh_engine_config_page(self.content_stack.currentIndex())

    def load_from_env(self):
        """Load configuration from .env file, reading directly from disk."""
        # Use dotenv_values() to read the file directly rather than relying on
        # os.environ, which may be stale if values were changed after startup.
        env = dotenv_values(self.env_file_path) if self.env_file_path.exists() else {}

        def _get(key, default=""):
            return env.get(key, os.getenv(key, default))

        # API settings
        self.api_url_edit.setText(_get("api", "").strip())
        self._refresh_api_key_combo()
        self.model_combo.setCurrentText(_get("model", "gpt-4.1"))

        # Translation settings
        self.language_combo.setCurrentText(_get("language", "English"))
        self.timeout_spin.setValue(int(_get("timeout", "90")))

        # Performance settings
        self.file_threads_spin.setValue(int(_get("fileThreads", "1")))
        self.threads_spin.setValue(int(_get("threads", "1")))
        self.batch_size_spin.setValue(int(_get("batchsize", "30")))
        self.frequency_penalty_spin.setValue(float(_get("frequency_penalty", "0.05")))

        # Formatting settings
        self.width_spin.setValue(int(_get("width", "60")))
        self.list_width_spin.setValue(int(_get("listWidth", "100")))
        self.note_width_spin.setValue(int(_get("noteWidth", "75")))
        self.convert_quotes_cb.setChecked(
            _get("convertQuotes", "true").strip().lower() in ("true", "1", "yes")
        )

        # Custom API pricing
        self.input_cost_spin.setValue(float(_get("input_cost", "2.0")))
        self.output_cost_spin.setValue(float(_get("output_cost", "8.0")))

        # UI settings
        self.font_scale_spin.setValue(float(_get("font_scale", "1.0")))

        # Game Update defaults
        from util.gameupdate_config import (
            DEFAULT_BRANCH,
            DEFAULT_FORGE,
            default_host_for_forge,
            normalize_forge,
        )

        forge = normalize_forge(_get("gameUpdateForge", DEFAULT_FORGE))
        forge_idx = self.gu_forge_combo.findData(forge)
        self.gu_forge_combo.setCurrentIndex(forge_idx if forge_idx >= 0 else 0)
        host = _get("gameUpdateHost", "") or default_host_for_forge(forge)
        self.gu_host_edit.setText(host)
        self.gu_username_edit.setText(_get("gameUpdateUsername", ""))
        self.gu_branch_edit.setText(_get("gameUpdateBranch", DEFAULT_BRANCH) or DEFAULT_BRANCH)

    def _on_gu_forge_changed(self, _index: int = 0):
        """Fill host with the forge default when the user switches forge."""
        from util.gameupdate_config import default_host_for_forge

        forge = self.gu_forge_combo.currentData() or "gitlab"
        current = self.gu_host_edit.text().strip()
        defaults = {
            "gitgud.io",
            "gitlab.com",
            "github.com",
            "codeberg.org",
            "",
        }
        if current.lower() in defaults:
            self.gu_host_edit.setText(default_host_for_forge(str(forge)))

    def connect_auto_save(self):
        """Connect all widgets to auto-save on change."""
        # Text fields - use editingFinished to avoid saving on every keystroke
        self.api_url_edit.editingFinished.connect(self.auto_save)
        self.api_key_combo.currentTextChanged.connect(self._on_api_key_selected)

        
        # Combo boxes
        self.model_combo.currentTextChanged.connect(self.auto_save)
        self.language_combo.currentTextChanged.connect(self.auto_save)
        
        # Spin boxes — use editingFinished so saves trigger on Enter or focus-out,
        # not on every intermediate keystroke while typing.
        self.timeout_spin.editingFinished.connect(self.auto_save)
        self.file_threads_spin.editingFinished.connect(self.auto_save)
        self.threads_spin.editingFinished.connect(self.auto_save)
        self.batch_size_spin.editingFinished.connect(self.auto_save)
        self.frequency_penalty_spin.editingFinished.connect(self.auto_save)
        self.width_spin.editingFinished.connect(self.auto_save)
        self.list_width_spin.editingFinished.connect(self.auto_save)
        self.note_width_spin.editingFinished.connect(self.auto_save)
        self.convert_quotes_cb.stateChanged.connect(self._on_convert_quotes_changed)
        self.input_cost_spin.editingFinished.connect(self.auto_save)
        self.output_cost_spin.editingFinished.connect(self.auto_save)
        self.font_scale_spin.editingFinished.connect(self.auto_save)
        self.gu_forge_combo.currentIndexChanged.connect(self.auto_save)
        self.gu_host_edit.editingFinished.connect(self.auto_save)
        self.gu_username_edit.editingFinished.connect(self.auto_save)
        self.gu_branch_edit.editingFinished.connect(self.auto_save)
    
    def disconnect_auto_save(self):
        """Disconnect all widgets from auto-save."""
        try:
            self.api_url_edit.editingFinished.disconnect(self.auto_save)
            self.api_key_combo.currentTextChanged.disconnect(self._on_api_key_selected)

            self.model_combo.currentTextChanged.disconnect(self.auto_save)
            self.language_combo.currentTextChanged.disconnect(self.auto_save)
            self.timeout_spin.editingFinished.disconnect(self.auto_save)
            self.file_threads_spin.editingFinished.disconnect(self.auto_save)
            self.threads_spin.editingFinished.disconnect(self.auto_save)
            self.batch_size_spin.editingFinished.disconnect(self.auto_save)
            self.frequency_penalty_spin.editingFinished.disconnect(self.auto_save)
            self.width_spin.editingFinished.disconnect(self.auto_save)
            self.list_width_spin.editingFinished.disconnect(self.auto_save)
            self.note_width_spin.editingFinished.disconnect(self.auto_save)
            self.convert_quotes_cb.stateChanged.disconnect(self._on_convert_quotes_changed)
            self.input_cost_spin.editingFinished.disconnect(self.auto_save)
            self.output_cost_spin.editingFinished.disconnect(self.auto_save)
            self.font_scale_spin.editingFinished.disconnect(self.auto_save)
            self.gu_forge_combo.currentIndexChanged.disconnect(self.auto_save)
            self.gu_host_edit.editingFinished.disconnect(self.auto_save)
            self.gu_username_edit.editingFinished.disconnect(self.auto_save)
            self.gu_branch_edit.editingFinished.disconnect(self.auto_save)
        except (TypeError, RuntimeError):
            pass
    
    def _on_convert_quotes_changed(self, state):
        """Warn when quote conversion is disabled, then auto-save."""
        if state == Qt.Unchecked:
            QMessageBox.warning(
                self,
                "Convert Quotes Disabled",
                "The AI often struggles to keep 「」 and 『』 consistent "
                "across translated lines.\n\n"
                "Leaving conversion enabled is recommended unless you "
                "specifically need the Japanese brackets in the output.",
            )
        self.auto_save()

    def auto_save(self):
        """Auto-save configuration without showing message."""
        self.save_to_env(show_message=False)
        if hasattr(self, 'autosave_label'):
            self.autosave_label.setText("✓ Saved")
            self._autosave_timer.start(2000)

    def _clear_autosave_indicator(self):
        if hasattr(self, 'autosave_label'):
            self.autosave_label.setText("")
    
    def save_to_env(self, show_message=True):
        """Save configuration to .env file."""
        try:
            # Ensure .env file exists
            if not self.env_file_path.exists():
                self.env_file_path.touch()
            
            # Build config dict for both file and os.environ updates
            config = {
                "api": self.api_url_edit.text().strip(),
                "key": self._active_api_key_secret(),
                "model": self.model_combo.currentText(),
                "language": self.language_combo.currentText(),
                "timeout": str(self.timeout_spin.value()),
                "fileThreads": str(self.file_threads_spin.value()),
                "threads": str(self.threads_spin.value()),
                "batchsize": str(self.batch_size_spin.value()),
                "frequency_penalty": str(self.frequency_penalty_spin.value()),
                "width": str(self.width_spin.value()),
                "listWidth": str(self.list_width_spin.value()),
                "noteWidth": str(self.note_width_spin.value()),
                "convertQuotes": "true" if self.convert_quotes_cb.isChecked() else "false",
                "input_cost": str(self.input_cost_spin.value()),
                "output_cost": str(self.output_cost_spin.value()),
                "font_scale": str(self.font_scale_spin.value()),
                "gameUpdateForge": str(self.gu_forge_combo.currentData() or "gitlab"),
                "gameUpdateHost": self.gu_host_edit.text().strip(),
                "gameUpdateUsername": self.gu_username_edit.text().strip(),
                "gameUpdateBranch": self.gu_branch_edit.text().strip() or "main",
            }
            
            # Save to .env file and update os.environ so subprocesses inherit new values
            for key, value in config.items():
                set_key(self.env_file_path, key, value)
                os.environ[key] = value
            
            if show_message:
                QMessageBox.information(self, "Success", "Configuration saved successfully!")
            self.config_changed.emit()
            
        except Exception as e:
            if show_message:
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
        self.disconnect_auto_save()
        
        # API settings
        self.api_url_edit.clear()
        self._refresh_api_key_combo()
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
        self.convert_quotes_cb.setChecked(True)

        # UI settings
        self.font_scale_spin.setValue(1.0)

        # Game Update defaults
        from util.gameupdate_config import DEFAULT_BRANCH, DEFAULT_FORGE, DEFAULT_HOST

        forge_idx = self.gu_forge_combo.findData(DEFAULT_FORGE)
        self.gu_forge_combo.setCurrentIndex(forge_idx if forge_idx >= 0 else 0)
        self.gu_host_edit.setText(DEFAULT_HOST)
        self.gu_username_edit.clear()
        self.gu_branch_edit.setText(DEFAULT_BRANCH)
        
        self.connect_auto_save()
    
    def reset_to_defaults_with_save(self):
        """Reset to defaults, save, and show confirmation."""
        self.reset_to_defaults()
        self.save_to_env(show_message=False)
        
        # Custom API settings
        self.input_cost_spin.setValue(2.0)
        self.output_cost_spin.setValue(8.0)
        
        # Reset engine tabs
        self.mvmz_tab.reset_to_defaults()
        self.wolf_tab.reset_to_defaults()
        self.csv_tab.reset_to_defaults()
        
    def get_config(self):
        """Get current configuration as dictionary."""
        return {
            "api": self.api_url_edit.text(),
            "key": self._active_api_key_secret(),
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
            "convertQuotes": self.convert_quotes_cb.isChecked(),
            "input_cost": self.input_cost_spin.value(),
            "output_cost": self.output_cost_spin.value(),
            "font_scale": self.font_scale_spin.value(),
            "gameUpdateForge": str(self.gu_forge_combo.currentData() or "gitlab"),
            "gameUpdateHost": self.gu_host_edit.text().strip(),
            "gameUpdateUsername": self.gu_username_edit.text().strip(),
            "gameUpdateBranch": self.gu_branch_edit.text().strip() or "main",
        }
        
    def validate(self):
        """Validate the current configuration."""
        errors = []
        
        # Check required fields
        if not self._active_api_key_secret():
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
