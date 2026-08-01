"""
Configuration Tab - Handles environment variables, global settings, and engine configurations
"""

import os
from pathlib import Path
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout, QLineEdit,
    QSpinBox, QDoubleSpinBox, QComboBox, QPushButton, QGroupBox,
    QLabel, QFileDialog, QMessageBox, QTextEdit,
    QCheckBox, QApplication, QTabWidget, QFrame, QStackedWidget, QToolButton,
    QMenu, QDialog, QDialogButtonBox, QListView, QSizePolicy, QScrollArea,
)
from PyQt5.QtCore import Qt, QPoint, pyqtSignal, QTimer, QThread
from PyQt5.QtGui import QColor, QIcon, QPainter, QPalette, QPolygon
from dotenv import load_dotenv, set_key, dotenv_values

from gui.rpgmaker_tab import RPGMakerTab
from gui.wolf_tab import WolfTab
from gui.csv_tab import CSVTab
from gui.srpg_tab import SRPGTab
from util import api_keys as api_key_vault
from gui.theme import COLORS, Geometry, Spacing
from gui.ui_components import PageHeader, configure_action_button, set_status_text


API_URL_PRESETS = (
    ("OpenAI", "https://api.openai.com/v1"),
    ("Claude (Anthropic)", "https://api.anthropic.com/v1"),
    ("Gemini", "https://generativelanguage.googleapis.com/v1beta/openai/"),
    ("DeepSeek", "https://api.deepseek.com/v1/"),
    ("Mistral", "https://api.mistral.ai/v1/"),
    ("Nvidia", "https://integrate.api.nvidia.com/v1/"),
)


class ModelFetchThread(QThread):
    """Background thread that fetches model lists from OpenAI, Anthropic, or Gemini."""
    models_fetched = pyqtSignal(list)
    fetch_error = pyqtSignal(str)

    # Fallback list shown when no API key is set or a fetch fails
    DEFAULTS = [
        "gpt-5.6-terra", "gpt-4.1-mini", "gpt-4.1", "gpt-4o", "gpt-4o-mini",
        "o3", "o4-mini",
        "claude-sonnet-5", "claude-opus-4-5", "claude-sonnet-4-6",
        "claude-sonnet-4-5", "claude-haiku-4-5",
        "gemini-3.6-flash", "gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-pro",
        "deepseek-chat",
        "mistral-medium-3.5",  # free-tier recommendation; avoid -latest (older 3.1)
    ]

    def __init__(self, api_key, api_url, parent=None, provider=None):
        super().__init__(parent)
        self.api_key = api_key
        self.api_url = api_url.strip()
        self.provider = (provider or "").strip().lower()

    def run(self):
        models = []
        errors = []
        _url = self.api_url.lower()
        # Only attempt each provider's fetcher when the configured URL matches.
        # Avoids sending a DeepSeek (or other) key to Anthropic and getting a
        # spurious 401 authentication error.
        provider_fetchers = {
            "openai": self._fetch_openai,
            "anthropic": self._fetch_anthropic,
            "gemini": self._fetch_gemini,
        }
        if self.provider:
            fetcher = provider_fetchers.get(self.provider)
            if fetcher is None:
                self.fetch_error.emit(
                    f"Unsupported model-list provider: {self.provider}"
                )
                return
            fetchers = [fetcher]
        else:
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
        # The SDK requires a non-empty value even when a local server ignores
        # authentication entirely.
        kwargs = {"api_key": self.api_key or "not-needed"}
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
        kwargs = {"api_key": self.api_key}
        if self.api_url:
            base_url = self.api_url.rstrip("/")
            if "api.anthropic.com" in base_url.lower() and base_url.endswith("/v1"):
                base_url = base_url[:-3]
            kwargs["base_url"] = base_url
        client = anthropic.Anthropic(**kwargs)
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


class ConfigComboBox(QComboBox):
    """Combo box with a platform-independent visible dropdown indicator."""

    _POPUP_COLOR = QColor("#353539")

    def __init__(self, parent=None):
        super().__init__(parent)
        # Force Qt's list-view popup instead of its menu-style popup. The
        # latter ignores maxVisibleItems and can allocate a screen-tall menu
        # with large blank scrolling regions.
        self.setStyleSheet("QComboBox { combobox-popup: 0; }")
        view = QListView()
        view.setObjectName("configComboPopup")
        view.setAutoFillBackground(True)
        view.setAttribute(Qt.WA_StyledBackground, True)
        view.viewport().setAutoFillBackground(True)
        view.viewport().setAttribute(Qt.WA_StyledBackground, True)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        view.setTextElideMode(Qt.ElideRight)
        view.setStyleSheet("""
            QListView#configComboPopup {
                background-color: #353539;
                color: #f2f2f2;
                border: 1px solid #56565b;
                outline: none;
                padding: 2px;
            }
            QListView#configComboPopup::item {
                background-color: #353539;
                color: #f2f2f2;
                min-height: 26px;
                padding: 3px 8px;
            }
            QListView#configComboPopup::item:selected {
                background-color: #007acc;
                color: #ffffff;
            }
            QListView#configComboPopup::item:hover:!selected {
                background-color: #45454a;
            }
        """)
        self.setView(view)
        self.setMaxVisibleItems(12)
        self._apply_popup_palette()

    def _popup_height_limit(self) -> int:
        visible_rows = min(max(1, self.maxVisibleItems()), max(1, self.count()))
        row_height = self.view().sizeHintForRow(0) if self.count() else -1
        if row_height <= 0:
            row_height = self.fontMetrics().height() + 12
        return visible_rows * row_height + self.view().frameWidth() * 2 + 6

    def _apply_popup_palette(self):
        for widget in (self.view(), self.view().viewport()):
            widget.setAutoFillBackground(True)
            widget.setAttribute(Qt.WA_StyledBackground, True)
            widget.setAttribute(Qt.WA_OpaquePaintEvent, True)
            palette = widget.palette()
            palette.setColor(QPalette.Base, self._POPUP_COLOR)
            palette.setColor(QPalette.Window, self._POPUP_COLOR)
            palette.setColor(QPalette.AlternateBase, self._POPUP_COLOR)
            palette.setColor(QPalette.Text, QColor("#f2f2f2"))
            palette.setColor(QPalette.Highlight, QColor("#007acc"))
            palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
            widget.setPalette(palette)

    def showPopup(self):
        self._apply_popup_palette()
        self.view().setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        super().showPopup()
        self._apply_popup_palette()
        popup = self.view().window()
        popup.setWindowOpacity(1.0)
        popup.setAttribute(Qt.WA_TranslucentBackground, False)
        popup.setAutoFillBackground(True)
        palette = popup.palette()
        palette.setColor(QPalette.Window, self._POPUP_COLOR)
        palette.setColor(QPalette.Base, self._POPUP_COLOR)
        popup.setPalette(palette)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#d8d8d8" if self.isEnabled() else "#858585"))
        center_x = self.width() - 13
        center_y = self.height() // 2 + 1
        painter.drawPolygon(QPolygon([
            QPoint(center_x - 4, center_y - 2),
            QPoint(center_x + 4, center_y - 2),
            QPoint(center_x, center_y + 3),
        ]))


class ConfigMenu(QMenu):
    """Popup menu with the same fully opaque surface as config dropdowns."""

    _BACKGROUND = QColor("#353539")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("""
            QMenu {
                background-color: #353539;
                color: #f2f2f2;
                border: 1px solid #56565b;
                padding: 2px;
            }
            QMenu::item {
                background-color: #353539;
                color: #f2f2f2;
                min-height: 26px;
                padding: 3px 9px;
            }
            QMenu::item:selected {
                background-color: #007acc;
                color: #ffffff;
            }
        """)
        self._apply_opaque_background()

    def _apply_opaque_background(self):
        self.setWindowOpacity(1.0)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(QPalette.Window, self._BACKGROUND)
        palette.setColor(QPalette.Base, self._BACKGROUND)
        palette.setColor(QPalette.Button, self._BACKGROUND)
        palette.setColor(QPalette.Text, QColor("#f2f2f2"))
        palette.setColor(QPalette.ButtonText, QColor("#f2f2f2"))
        palette.setColor(QPalette.Highlight, QColor("#007acc"))
        palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
        self.setPalette(palette)

    def showEvent(self, event):
        self._apply_opaque_background()
        super().showEvent(event)
        self._apply_opaque_background()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), self._BACKGROUND)
        painter.end()
        super().paintEvent(event)


class ApiKeyEditDialog(QDialog):
    """Dialog to create or overwrite a named API key (secret entered once)."""

    def __init__(
        self,
        parent=None,
        initial_name: str = "",
        initial_endpoint: str = "",
        *,
        allow_blank_secret: bool = False,
        initial_keyless: bool = False,
    ):
        super().__init__(parent)
        self.setWindowTitle("API Key")
        self.setModal(True)
        self.setMinimumWidth(460)
        self._allow_blank_secret = allow_blank_secret

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.name_edit = QLineEdit(initial_name)
        self.name_edit.setPlaceholderText("e.g. OpenAI, DeepSeek, Work")
        form.addRow("Name:", self.name_edit)

        self.secret_edit = QLineEdit()
        self.secret_edit.setEchoMode(QLineEdit.Password)
        if allow_blank_secret:
            self.secret_edit.setPlaceholderText("Leave blank to keep the existing secret")
        else:
            self.secret_edit.setPlaceholderText("Paste API key secret")
        form.addRow("Secret:", self.secret_edit)

        self.keyless_cb = QCheckBox("No API key required (local model)")
        self.keyless_cb.setChecked(initial_keyless)
        self.keyless_cb.setToolTip(
            "Use this for a local OpenAI-compatible server that does not require authentication."
        )
        self.keyless_cb.toggled.connect(self._on_keyless_toggled)
        form.addRow("", self.keyless_cb)

        endpoint_wrap = QWidget()
        endpoint_row = QHBoxLayout(endpoint_wrap)
        endpoint_row.setContentsMargins(0, 0, 0, 0)
        endpoint_row.setSpacing(8)

        self.endpoint_edit = QLineEdit(initial_endpoint)
        self.endpoint_edit.setPlaceholderText("Optional - leave blank to keep the global API URL")
        endpoint_row.addWidget(self.endpoint_edit, 1)

        endpoint_preset_btn = QToolButton()
        endpoint_preset_btn.setText("Presets ▾")
        endpoint_preset_btn.setPopupMode(QToolButton.InstantPopup)
        endpoint_menu = ConfigMenu(endpoint_preset_btn)
        for label, url in (*API_URL_PRESETS, ("Clear", "")):
            action = endpoint_menu.addAction(label)
            action.triggered.connect(
                lambda checked=False, u=url: self.endpoint_edit.setText(u)
            )
        endpoint_preset_btn.setMenu(endpoint_menu)
        endpoint_row.addWidget(endpoint_preset_btn)
        form.addRow("Endpoint:", endpoint_wrap)

        layout.addLayout(form)

        hint = QLabel(
            "The name appears in the dropdown. The secret is stored locally "
            "and is never shown again on the main Config page. "
            "If you set an endpoint, selecting this key always applies that API URL."
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
        self._endpoint = ""
        self._keyless = False
        self._on_keyless_toggled(initial_keyless)
        self.secret_edit.setFocus()

    def _on_keyless_toggled(self, checked: bool):
        self.secret_edit.setEnabled(not checked)
        if checked:
            self.secret_edit.clear()
            self.secret_edit.setPlaceholderText("Not used for this local endpoint")
        elif self._allow_blank_secret:
            self.secret_edit.setPlaceholderText("Leave blank to keep the existing secret")
        else:
            self.secret_edit.setPlaceholderText("Paste API key secret")

    def _accept_if_valid(self):
        name = self.name_edit.text().strip()
        secret = self.secret_edit.text().strip()
        endpoint = self.endpoint_edit.text().strip()
        keyless = self.keyless_cb.isChecked()
        if not name:
            QMessageBox.warning(self, "API Key", "Enter a name for this key.")
            self.name_edit.setFocus()
            return
        if not secret and not keyless and not self._allow_blank_secret:
            QMessageBox.warning(self, "API Key", "Enter the API key secret.")
            self.secret_edit.setFocus()
            return
        if keyless and not endpoint:
            QMessageBox.warning(
                self, "API Key", "Enter the local model server's API endpoint."
            )
            self.endpoint_edit.setFocus()
            return
        self._name = name
        self._secret = secret
        self._endpoint = endpoint
        self._keyless = keyless
        self.accept()

    def result_values(self) -> tuple[str, str, str, bool]:
        return self._name, self._secret, self._endpoint, self._keyless


class ConfigTab(QWidget):
    """Configuration tab for managing environment variables, global settings, and engine configs."""
    
    config_changed = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        self.env_file_path = Path(".env")
        self._model_fetch_thread = None
        self._pending_model_fetch = None
        self._model_fetch_request_id = 0
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
        
        header_host = QWidget()
        header_layout = QVBoxLayout(header_host)
        header_layout.setContentsMargins(
            Spacing.XL, Spacing.LG, Spacing.XL, Spacing.SM
        )
        header_layout.addWidget(PageHeader(
            "Configuration",
            "Set shared translation defaults and engine-specific behavior."
        ))
        main_layout.addWidget(header_host)

        # Create top navigation bar
        nav_bar = QWidget()
        nav_bar.setObjectName("appSubnavBar")
        nav_bar.setFixedHeight(52)
        nav_layout = QHBoxLayout()
        nav_layout.setContentsMargins(Spacing.XL, 0, Spacing.XL, 0)
        nav_layout.setSpacing(Spacing.XS)
        
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
        self.content_stack.addWidget(self._scrollable_config_page(general_tab))
        
        # Page 2: RPG Maker MV/MZ Engine
        self.mvmz_tab = RPGMakerTab("MVMZ")
        self.content_stack.addWidget(self._scrollable_config_page(self.mvmz_tab))
        
        # Page 3: Wolf RPG Engine
        self.wolf_tab = WolfTab()
        self.content_stack.addWidget(self._scrollable_config_page(self.wolf_tab))
        
        # Page 4: CSV Settings
        self.csv_tab = CSVTab()
        self.content_stack.addWidget(self._scrollable_config_page(self.csv_tab))

        # Page 5: SRPG Studio Engine
        self.srpg_tab = SRPGTab()
        self.content_stack.addWidget(self._scrollable_config_page(self.srpg_tab))
        
        # Add navigation bar and content to main layout
        main_layout.addWidget(nav_bar)
        main_layout.addWidget(self.content_stack)
        self.setLayout(main_layout)
        
        # Select first page by default
        self.switch_page(0)
    
    def create_nav_button(self, icon_text, tooltip, engine_key=None):
        """Create a labeled secondary-navigation button."""
        btn = QPushButton(tooltip)
        btn.setObjectName("appSubnavButton")
        btn.setToolTip(tooltip)
        btn.setAccessibleName(tooltip)
        btn.setMinimumWidth(144)
        btn.setMinimumHeight(Geometry.CONTROL_PROMINENT)
        btn.setCheckable(True)
        return btn

    @staticmethod
    def _scrollable_config_page(page: QWidget) -> QScrollArea:
        """Keep every configuration category operable at large font scales."""

        scroll = QScrollArea()
        scroll.setObjectName("configPageScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(page)
        return scroll
    
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
        """Create a compact general-settings dashboard without nested scrolling."""
        widget = QWidget()
        widget.setObjectName("generalSettingsPage")
        widget.setStyleSheet("""
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
                background-color: #3e3e42;
                color: #f2f2f2;
                border: 1px solid #56565b;
                border-radius: 4px;
                padding: 1px 9px;
                min-height: 30px;
                selection-background-color: #007acc;
            }
            QLineEdit:hover, QComboBox:hover,
            QSpinBox:hover, QDoubleSpinBox:hover {
                border-color: #68686e;
            }
            QLineEdit:focus, QComboBox:focus,
            QSpinBox:focus, QDoubleSpinBox:focus {
                border-color: #007acc;
                background-color: #424247;
            }
            QComboBox::drop-down {
                subcontrol-origin: border;
                subcontrol-position: top right;
                width: 26px;
                border: none;
                border-left: 1px solid #56565b;
                border-top-right-radius: 4px;
                border-bottom-right-radius: 4px;
                background-color: #4a4a50;
            }
            QComboBox::drop-down:hover {
                background-color: #007acc;
            }
            QComboBox QLineEdit {
                background-color: #3e3e42;
                border: none;
                border-radius: 0;
                padding: 0 4px;
            }
            QComboBox QAbstractItemView, QMenu {
                background-color: #353539;
                color: #f2f2f2;
                border: 1px solid #56565b;
                selection-background-color: #007acc;
                selection-color: #ffffff;
                outline: none;
            }
            QComboBox QAbstractItemView::item, QMenu::item {
                min-height: 26px;
                padding: 3px 9px;
            }
            QMenu::item:selected {
                background-color: #007acc;
            }
            QLineEdit:disabled, QComboBox:disabled,
            QSpinBox:disabled, QDoubleSpinBox:disabled {
                background-color: #343438;
                color: #858585;
                border-color: #47474b;
            }
        """)
        page_layout = QVBoxLayout(widget)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)
        self._general_form_labels = []
        self._general_cards_by_title = {}
        self._general_label_width = None

        btn_style = (
            "QToolButton {"
            "background-color: #3e3e42; color: #cccccc;"
            "border: 1px solid #555555; border-radius: 4px; padding: 4px 8px;"
            "}"
            "QToolButton:hover { background-color: #505050; }"
            "QToolButton::menu-indicator { image: none; }"
        )

        def size_field(w: QWidget, minimum_width: int = 120) -> QWidget:
            """Give controls room to breathe while allowing them to resize."""
            w.setMinimumWidth(minimum_width)
            w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            if isinstance(w, (QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox)):
                w.setMinimumHeight(32)
            return w

        action_width = 144
        action_lane_width = action_width * 2 + 8

        def row_box(field: QWidget, *actions: QWidget) -> QWidget:
            """API row with equal field width and no visible filler widget."""
            box = QWidget()
            box.setStyleSheet("background: transparent;")
            row = QHBoxLayout(box)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)

            field.setMinimumWidth(0)
            field.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            row.addWidget(field, 1)

            for action in actions:
                action.setFixedWidth(action_width)
                action.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
                row.addWidget(action)
            used_action_width = (
                len(actions) * action_width
                + max(0, len(actions) - 1) * row.spacing()
            )
            row.addSpacing(max(0, action_lane_width - used_action_width))

            box.setMinimumHeight(32)
            box.setMinimumWidth(120)
            box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            return box

        def create_card(title: str) -> tuple[QFrame, QFormLayout]:
            card = QFrame()
            card.setObjectName("settingsCard")
            self._general_cards_by_title[title] = card
            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            card.setStyleSheet(
                "QFrame#settingsCard {"
                "background-color: #303033;"
                "border: 1px solid #444448;"
                "border-radius: 7px;"
                "}"
                "QFrame#settingsCard:hover { border-color: #505055; }"
            )

            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(16, 12, 16, 16)
            card_layout.setSpacing(8)
            header = create_section_header(title)
            if not isinstance(header, QLabel):
                header.setStyleSheet("background: transparent;")
            card_layout.addWidget(header)

            form = QFormLayout()
            form.setContentsMargins(0, 0, 0, 0)
            form.setHorizontalSpacing(12)
            form.setVerticalSpacing(7)
            form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            form.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
            form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
            form.setRowWrapPolicy(QFormLayout.WrapLongRows)
            card_layout.addLayout(form)
            card_layout.addStretch()
            return card, form

        def add_row(form: QFormLayout, label: str, field: QWidget) -> None:
            label_widget = QLabel(label)
            label_widget.setMinimumWidth(180)
            label_widget.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            label_widget.setStyleSheet("background: transparent;")
            self._general_form_labels.append(label_widget)
            form.addRow(label_widget, field)

        # ── API ──────────────────────────────────────────────────────
        api_card, api_section = create_card("🔑 API Configuration")

        self.api_url_edit = QLineEdit()
        self.api_url_edit.setPlaceholderText("Leave blank for OpenAI API")

        self.api_url_preset_btn = QToolButton()
        self.api_url_preset_btn.setText("Presets ▾")
        self.api_url_preset_btn.setMinimumWidth(144)
        self.api_url_preset_btn.setPopupMode(QToolButton.InstantPopup)
        self.api_url_preset_btn.setStyleSheet(btn_style)

        api_url_menu = ConfigMenu(self.api_url_preset_btn)
        for name, url in API_URL_PRESETS:
            action = api_url_menu.addAction(name)
            action.triggered.connect(
                lambda checked, u=url: self._select_api_url_preset(u)
            )
        self.api_url_preset_btn.setMenu(api_url_menu)
        self.api_url_edit.textChanged.connect(self._update_model_placeholder)

        add_row(
            api_section,
            "API URL:",
            row_box(self.api_url_edit, self.api_url_preset_btn),
        )

        self.api_key_combo = ConfigComboBox()
        self.api_key_combo.setEditable(False)
        self.api_key_combo.setToolTip(
            "Select a saved API key by name. Optional per-key endpoints are "
            "applied to API URL automatically. Secrets stay hidden after you add them."
        )

        self.api_key_new_btn = QToolButton()
        self.api_key_new_btn.setText("New")
        self.api_key_new_btn.setToolTip("Add or update a named API key")
        self.api_key_new_btn.setMinimumWidth(144)
        self.api_key_new_btn.setStyleSheet(btn_style)
        self.api_key_new_btn.clicked.connect(self._on_api_key_new)

        self.api_key_delete_btn = QToolButton()
        self.api_key_delete_btn.setText("Delete")
        self.api_key_delete_btn.setToolTip("Remove the selected API key")
        self.api_key_delete_btn.setMinimumWidth(144)
        self.api_key_delete_btn.setStyleSheet(btn_style)
        self.api_key_delete_btn.clicked.connect(self._on_api_key_delete)

        add_row(
            api_section,
            "API Key:",
            row_box(self.api_key_combo, self.api_key_new_btn, self.api_key_delete_btn),
        )

        self.model_combo = ConfigComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.addItems(ModelFetchThread.DEFAULTS)

        self.model_refresh_btn = QToolButton()
        self.model_refresh_btn.setText("⟳")
        self.model_refresh_btn.setToolTip("Fetch latest models from the configured API")
        self.model_refresh_btn.setMinimumWidth(144)
        self.model_refresh_btn.setStyleSheet(btn_style)
        self.model_refresh_btn.clicked.connect(lambda: self.fetch_models(silent=False))

        add_row(
            api_section,
            "Model:",
            row_box(self.model_combo, self.model_refresh_btn),
        )

        # ── TRANSLATION + FORMATTING ─────────────────────────────────
        translation_card, trans_section = create_card("🌐 Translation & Text")

        self.language_combo = ConfigComboBox()
        self.language_combo.addItems([
            "English", "Spanish", "French", "German", "Italian",
            "Portuguese", "Russian", "Chinese", "Korean", "Japanese",
        ])
        add_row(trans_section, "Target Language:", size_field(self.language_combo))

        self.timeout_spin = QSpinBox()
        self.timeout_spin.setButtonSymbols(QSpinBox.NoButtons)
        self.timeout_spin.setRange(30, 300)
        self.timeout_spin.setValue(90)
        self.timeout_spin.setSuffix(" sec")
        add_row(trans_section, "Timeout:", size_field(self.timeout_spin))

        self.width_spin = QSpinBox()
        self.width_spin.setButtonSymbols(QSpinBox.NoButtons)
        self.width_spin.setRange(20, 200)
        self.width_spin.setValue(60)
        self.width_spin.setSuffix(" chars")
        add_row(trans_section, "Dialogue Width:", size_field(self.width_spin))

        self.face_width_spin = QSpinBox()
        self.face_width_spin.setButtonSymbols(QSpinBox.NoButtons)
        self.face_width_spin.setRange(10, 200)
        self.face_width_spin.setValue(50)
        self.face_width_spin.setSuffix(" chars")
        self.face_width_spin.setToolTip(
            "Dialogue wrap width when a standard code-101 face graphic reserves window space."
        )
        self.face_width_spin.setMaximum(self.width_spin.value())
        self.width_spin.valueChanged.connect(self.face_width_spin.setMaximum)
        add_row(trans_section, "Dialogue + Face:", size_field(self.face_width_spin))

        self.list_width_spin = QSpinBox()
        self.list_width_spin.setButtonSymbols(QSpinBox.NoButtons)
        self.list_width_spin.setRange(20, 200)
        self.list_width_spin.setValue(100)
        self.list_width_spin.setSuffix(" chars")
        add_row(trans_section, "List Width:", size_field(self.list_width_spin))

        self.note_width_spin = QSpinBox()
        self.note_width_spin.setButtonSymbols(QSpinBox.NoButtons)
        self.note_width_spin.setRange(20, 200)
        self.note_width_spin.setValue(75)
        self.note_width_spin.setSuffix(" chars")
        add_row(trans_section, "Note Width:", size_field(self.note_width_spin))

        self.convert_quotes_cb = QCheckBox('Convert 「」 / 『』 to ""')
        self.convert_quotes_cb.setChecked(True)
        self.convert_quotes_cb.setToolTip(
            "When enabled, Japanese corner brackets 「」 and 『』 are replaced "
            'with ASCII double quotes "" in translated output (and on RPG Maker '
            "source text before translation).\n\n"
            "Leaving this on is recommended - the AI often fails to keep 「」 "
            "consistent across lines."
        )
        add_row(trans_section, "Convert Quotes:", self.convert_quotes_cb)

        self.use_sfx_reference_cb = QCheckBox("Use local Japanese SFX reference")
        self.use_sfx_reference_cb.setChecked(True)
        self.use_sfx_reference_cb.setToolTip(
            "Match Japanese sound effects in each translation batch and send only "
            "their possible meanings as non-authoritative context. The reference "
            "is bundled locally and does not make network requests."
        )
        add_row(trans_section, "SFX Reference:", self.use_sfx_reference_cb)

        # ── PERFORMANCE + PRICING ────────────────────────────────────
        performance_card, perf_section = create_card("⚡ Performance & Pricing")

        self.file_threads_spin = QSpinBox()
        self.file_threads_spin.setButtonSymbols(QSpinBox.NoButtons)
        self.file_threads_spin.setRange(1, 10)
        self.file_threads_spin.setValue(1)
        add_row(perf_section, "File Threads:", size_field(self.file_threads_spin))

        self.threads_spin = QSpinBox()
        self.threads_spin.setButtonSymbols(QSpinBox.NoButtons)
        self.threads_spin.setRange(1, 20)
        self.threads_spin.setValue(1)
        add_row(perf_section, "Threads per File:", size_field(self.threads_spin))

        self.batch_size_spin = QSpinBox()
        self.batch_size_spin.setButtonSymbols(QSpinBox.NoButtons)
        self.batch_size_spin.setRange(1, 100)
        self.batch_size_spin.setValue(30)
        add_row(perf_section, "Batch Size:", size_field(self.batch_size_spin))

        self.frequency_penalty_spin = QDoubleSpinBox()
        self.frequency_penalty_spin.setButtonSymbols(QDoubleSpinBox.NoButtons)
        self.frequency_penalty_spin.setRange(0.0, 2.0)
        self.frequency_penalty_spin.setSingleStep(0.05)
        self.frequency_penalty_spin.setValue(0.05)
        add_row(
            perf_section,
            "Frequency Penalty:",
            size_field(self.frequency_penalty_spin),
        )

        self.input_cost_spin = QDoubleSpinBox()
        self.input_cost_spin.setButtonSymbols(QDoubleSpinBox.NoButtons)
        self.input_cost_spin.setRange(0.0, 100.0)
        self.input_cost_spin.setDecimals(4)
        self.input_cost_spin.setSingleStep(0.1)
        self.input_cost_spin.setValue(2.0)
        self.input_cost_spin.setSuffix(" / 1M tokens")
        add_row(perf_section, "Input Cost:", size_field(self.input_cost_spin))

        self.output_cost_spin = QDoubleSpinBox()
        self.output_cost_spin.setButtonSymbols(QDoubleSpinBox.NoButtons)
        self.output_cost_spin.setRange(0.0, 100.0)
        self.output_cost_spin.setDecimals(4)
        self.output_cost_spin.setSingleStep(0.1)
        self.output_cost_spin.setValue(8.0)
        self.output_cost_spin.setSuffix(" / 1M tokens")
        add_row(perf_section, "Output Cost:", size_field(self.output_cost_spin))

        # ── INTERFACE ────────────────────────────────────────────────
        interface_card, ui_section = create_card("🖥️ Interface")

        self.font_scale_spin = QDoubleSpinBox()
        self.font_scale_spin.setButtonSymbols(QDoubleSpinBox.NoButtons)
        self.font_scale_spin.setRange(0.5, 3.0)
        self.font_scale_spin.setSingleStep(0.1)
        self.font_scale_spin.setDecimals(1)
        self.font_scale_spin.setValue(1.0)
        self.font_scale_spin.setSuffix("x")
        self.font_scale_spin.setToolTip(
            "Scale the application font size.\n"
            "1.0 = default, 1.5 = 50% larger, 2.0 = double size.\n"
            "Takes effect immediately on save."
        )
        add_row(ui_section, "Font Scale:", size_field(self.font_scale_spin))

        # ── GAME UPDATE ──────────────────────────────────────────────
        updates_card, gu_section = create_card("📦 Game Update Defaults")

        self.gu_forge_combo = ConfigComboBox()
        self.gu_forge_combo.addItem("GitLab / gitgud", "gitlab")
        self.gu_forge_combo.addItem("GitHub", "github")
        self.gu_forge_combo.addItem("Forgejo / Gitea", "forgejo")
        self.gu_forge_combo.setToolTip(
            "Where your patch repos live. Used when Step 1 writes patch-config.txt."
        )
        self.gu_forge_combo.currentIndexChanged.connect(self._on_gu_forge_changed)
        add_row(gu_section, "Forge:", size_field(self.gu_forge_combo))

        self.gu_host_edit = QLineEdit()
        self.gu_host_edit.setPlaceholderText("gitgud.io")
        self.gu_host_edit.setToolTip(
            "Hostname only (no https://). Leave blank to use the forge default."
        )
        add_row(gu_section, "Host:", size_field(self.gu_host_edit))

        self.gu_username_edit = QLineEdit()
        self.gu_username_edit.setPlaceholderText("your-org-or-user")
        self.gu_username_edit.setToolTip(
            "Owner / org / group for all patch repos. Set once; rarely changes."
        )
        add_row(gu_section, "Username:", size_field(self.gu_username_edit))

        self.gu_branch_edit = QLineEdit()
        self.gu_branch_edit.setPlaceholderText("main")
        self.gu_branch_edit.setToolTip("Default branch to track (usually main or master).")
        add_row(gu_section, "Branch:", size_field(self.gu_branch_edit))

        content = QWidget()
        content.setObjectName("generalSettingsContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(12, 8, 12, 8)
        content_layout.setSpacing(0)

        dashboard = QGridLayout()
        dashboard.setContentsMargins(0, 4, 0, 0)
        dashboard.setHorizontalSpacing(12)
        dashboard.setVerticalSpacing(12)
        dashboard.setColumnStretch(0, 1)
        dashboard.setColumnStretch(1, 1)
        dashboard.setColumnStretch(2, 1)

        # The wider API card keeps its button clusters readable. The three
        # denser sections share the second row so the whole page fits without
        # its own scroll bar.
        dashboard.addWidget(api_card, 0, 0, 1, 2)
        dashboard.addWidget(interface_card, 0, 2, 1, 1)
        dashboard.addWidget(translation_card, 1, 0, 1, 1)
        dashboard.addWidget(performance_card, 1, 1, 1, 1)
        dashboard.addWidget(updates_card, 1, 2, 1, 1)
        content_layout.addLayout(dashboard)
        content_layout.addStretch()
        page_layout.addWidget(content, 1)

        # Persistent action bar keeps save/reset in the same predictable place.
        action_bar = QFrame()
        action_bar.setObjectName("settingsActionBar")
        action_bar.setStyleSheet(
            "QFrame#settingsActionBar {"
            "background-color: #252526; border-top: 1px solid #414141;"
            "}"
        )
        button_layout = QHBoxLayout(action_bar)
        button_layout.setContentsMargins(24, 8, 24, 8)
        button_layout.setSpacing(8)

        from gui import qt_icons

        reset_button = QPushButton()
        qt_icons.apply_button_icon(
            reset_button, "🔄 Reset to defaults", color=COLORS.text_secondary
        )
        configure_action_button(reset_button, variant="quiet")
        reset_button.clicked.connect(self.reset_to_defaults_with_save)
        reset_button.setMinimumHeight(32)

        save_button = QPushButton()
        qt_icons.apply_button_icon(
            save_button, "💾 Save changes", color=COLORS.text_secondary
        )
        configure_action_button(save_button, variant="primary")
        save_button.clicked.connect(lambda: self.save_to_env(show_message=True))
        save_button.setMinimumHeight(32)

        self.autosave_label = QLabel("")
        self.autosave_label.setObjectName("appStatusText")

        button_layout.addWidget(self.autosave_label)
        button_layout.addStretch()
        button_layout.addWidget(reset_button)
        button_layout.addWidget(save_button)
        page_layout.addWidget(action_bar)

        QTimer.singleShot(0, self._update_general_label_width)
        return widget

    def _update_general_label_width(self):
        """Keep every form aligned without crowding the minimum-width layout."""
        if not hasattr(self, "_general_form_labels"):
            return
        natural_width = max(
            (
                label.fontMetrics().horizontalAdvance(label.text()) + 8
                for label in self._general_form_labels
            ),
            default=180,
        )
        label_width = min(
            320,
            max(150 if self.width() < 1150 else 180, natural_width),
        )
        if label_width == self._general_label_width:
            return
        for label in self._general_form_labels:
            label.setFixedWidth(label_width)
        self._general_label_width = label_width

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_general_form_labels"):
            QTimer.singleShot(0, self._update_general_label_width)

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

    def _active_api_key_is_optional(self) -> bool:
        """Return whether the selected vault entry is explicitly keyless."""
        name = self.api_key_combo.currentText().strip()
        return api_key_vault.is_keyless(name) if name else False

    def _apply_key_endpoint(self, name: str | None = None):
        """If the named key has an endpoint, apply it to the API URL field."""
        key_name = (name or self.api_key_combo.currentText()).strip()
        if not key_name:
            return
        endpoint = api_key_vault.get_endpoint(key_name)
        if not endpoint:
            return
        self.api_url_edit.blockSignals(True)
        self.api_url_edit.setText(endpoint)
        self.api_url_edit.blockSignals(False)
        self._update_model_placeholder()

    def _select_api_url_preset(self, url: str):
        """Apply a provider preset and immediately refresh its model list."""
        self.api_url_edit.setText(url)
        self._on_api_url_changed()

    def _on_api_url_changed(self):
        """Persist a selected endpoint and load its available models."""
        self._update_model_placeholder()
        self.auto_save()
        self.fetch_models(silent=True, select_available=True)

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
        self._apply_key_endpoint()

    def _on_api_key_selected(self, _name: str = ""):
        """Persist dropdown selection as the active vault key and mirror to .env."""
        name = self.api_key_combo.currentText().strip()
        if not name:
            return
        try:
            api_key_vault.set_active(name)
            self._apply_key_endpoint(name)
            api_key_vault.sync_active_to_env(env_path=self.env_file_path)
        except KeyError:
            return
        self.auto_save()
        self.fetch_models(silent=True, select_available=True)

    def _on_api_key_new(self):
        """Open dialog to create or overwrite a named API key."""
        current = self.api_key_combo.currentText().strip()
        existing_endpoint = api_key_vault.get_endpoint(current) or "" if current else ""
        dialog = ApiKeyEditDialog(
            self,
            initial_name=current,
            initial_endpoint=existing_endpoint or self.api_url_edit.text().strip(),
            allow_blank_secret=bool(current and api_key_vault.get_secret(current)),
            initial_keyless=bool(current and api_key_vault.is_keyless(current)),
        )
        if dialog.exec_() != QDialog.Accepted:
            return
        name, secret, endpoint, keyless = dialog.result_values()
        try:
            api_key_vault.upsert_key(
                name,
                secret,
                endpoint=endpoint,
                make_active=True,
                keep_secret_if_blank=True,
                keyless=keyless,
            )
            self._apply_key_endpoint(name)
            api_key_vault.sync_active_to_env(env_path=self.env_file_path)
        except ValueError as exc:
            QMessageBox.warning(self, "API Key", str(exc))
            return
        self._refresh_api_key_combo(preferred=name)
        self.auto_save()
        self.fetch_models(silent=True, select_available=True)

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

    def fetch_models(self, silent=False, select_available=False):
        """Kick off background fetch of models from the configured API."""
        api_key = self._active_api_key_secret()
        api_url = self.api_url_edit.text().strip()

        if not api_key and not self._active_api_key_is_optional():
            if not silent:
                QMessageBox.warning(
                    self, "No API Key",
                    "Please add or select an API key before fetching models."
                )
            return

        self._model_fetch_request_id += 1
        request = {
            "id": self._model_fetch_request_id,
            "api_key": api_key,
            "api_url": api_url,
            "silent": bool(silent),
            "select_available": bool(select_available),
        }
        current_thread = self._model_fetch_thread
        if current_thread is not None and current_thread.isRunning():
            # Keep only the newest provider choice. The old SDK request cannot
            # be canceled safely, and its result is ignored by request id.
            self._pending_model_fetch = request
            return

        self._start_model_fetch(request)

    def _start_model_fetch(self, request):
        """Start one previously validated model-list request."""
        self.model_refresh_btn.setEnabled(False)
        self.model_refresh_btn.setText("…")

        thread = ModelFetchThread(
            request["api_key"], request["api_url"], parent=self
        )
        self._model_fetch_thread = thread
        thread.models_fetched.connect(
            lambda models, req=request: self._on_model_fetch_result(req, models)
        )
        thread.fetch_error.connect(
            lambda error, req=request: self._on_model_fetch_error(req, error)
        )
        thread.finished.connect(
            lambda req=request, worker=thread: self._on_model_fetch_finished(
                req, worker
            )
        )
        thread.start()

    def _on_model_fetch_result(self, request, models):
        """Ignore stale providers and apply the latest model-list result."""
        if request["id"] != self._model_fetch_request_id:
            return
        self._on_models_fetched(
            models,
            select_available=request["select_available"],
        )

    def _on_model_fetch_error(self, request, error):
        """Ignore stale failures and keep automatic refreshes non-intrusive."""
        if request["id"] != self._model_fetch_request_id:
            return
        self._on_models_fetch_error(error, silent=request["silent"])

    def _on_model_fetch_finished(self, request, thread):
        """Release a worker and run the newest queued provider request."""
        if self._model_fetch_thread is thread:
            self._model_fetch_thread = None
        thread.deleteLater()
        pending = self._pending_model_fetch
        self._pending_model_fetch = None
        if pending is not None:
            self._start_model_fetch(pending)
        elif request["id"] == self._model_fetch_request_id:
            self.model_refresh_btn.setEnabled(True)
            self.model_refresh_btn.setText("⟳")

    def _on_models_fetched(self, models, select_available=False):
        """Populate the model dropdown with freshly fetched models."""
        current = self.model_combo.currentText()
        choose_fetched = bool(select_available and current not in models)
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.addItems(models)
        if choose_fetched and models:
            self.model_combo.setCurrentIndex(0)
        else:
            self.model_combo.setCurrentText(current)  # preserve manual model names
        self.model_combo.blockSignals(False)
        self.model_refresh_btn.setEnabled(True)
        self.model_refresh_btn.setText("⟳")
        if choose_fetched and models:
            self.auto_save()

    def _on_models_fetch_error(self, error, silent=False):
        """Restore button and show error."""
        self.model_refresh_btn.setEnabled(True)
        self.model_refresh_btn.setText("⟳")
        if not silent:
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
        self.face_width_spin.setValue(int(_get("faceWidth", "50")))
        self.list_width_spin.setValue(int(_get("listWidth", "100")))
        self.note_width_spin.setValue(int(_get("noteWidth", "75")))
        self.convert_quotes_cb.setChecked(
            _get("convertQuotes", "true").strip().lower() in ("true", "1", "yes")
        )
        self.use_sfx_reference_cb.setChecked(
            _get("useSfxReference", "true").strip().lower() in ("true", "1", "yes")
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
        self.api_url_edit.editingFinished.connect(self._on_api_url_changed)
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
        self.face_width_spin.editingFinished.connect(self.auto_save)
        self.list_width_spin.editingFinished.connect(self.auto_save)
        self.note_width_spin.editingFinished.connect(self.auto_save)
        self.convert_quotes_cb.stateChanged.connect(self._on_convert_quotes_changed)
        self.use_sfx_reference_cb.stateChanged.connect(self.auto_save)
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
            self.api_url_edit.editingFinished.disconnect(self._on_api_url_changed)
            self.api_key_combo.currentTextChanged.disconnect(self._on_api_key_selected)

            self.model_combo.currentTextChanged.disconnect(self.auto_save)
            self.language_combo.currentTextChanged.disconnect(self.auto_save)
            self.timeout_spin.editingFinished.disconnect(self.auto_save)
            self.file_threads_spin.editingFinished.disconnect(self.auto_save)
            self.threads_spin.editingFinished.disconnect(self.auto_save)
            self.batch_size_spin.editingFinished.disconnect(self.auto_save)
            self.frequency_penalty_spin.editingFinished.disconnect(self.auto_save)
            self.width_spin.editingFinished.disconnect(self.auto_save)
            self.face_width_spin.editingFinished.disconnect(self.auto_save)
            self.list_width_spin.editingFinished.disconnect(self.auto_save)
            self.note_width_spin.editingFinished.disconnect(self.auto_save)
            self.convert_quotes_cb.stateChanged.disconnect(self._on_convert_quotes_changed)
            self.use_sfx_reference_cb.stateChanged.disconnect(self.auto_save)
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
                "API_KEY_OPTIONAL": (
                    "true" if self._active_api_key_is_optional() else "false"
                ),
                "model": self.model_combo.currentText(),
                "language": self.language_combo.currentText(),
                "timeout": str(self.timeout_spin.value()),
                "fileThreads": str(self.file_threads_spin.value()),
                "threads": str(self.threads_spin.value()),
                "batchsize": str(self.batch_size_spin.value()),
                "frequency_penalty": str(self.frequency_penalty_spin.value()),
                "width": str(self.width_spin.value()),
                "faceWidth": str(min(self.width_spin.value(), self.face_width_spin.value())),
                "listWidth": str(self.list_width_spin.value()),
                "noteWidth": str(self.note_width_spin.value()),
                "convertQuotes": "true" if self.convert_quotes_cb.isChecked() else "false",
                "useSfxReference": "true" if self.use_sfx_reference_cb.isChecked() else "false",
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
        self.face_width_spin.setValue(50)
        self.list_width_spin.setValue(100)
        self.note_width_spin.setValue(75)
        self.convert_quotes_cb.setChecked(True)
        self.use_sfx_reference_cb.setChecked(True)

        # Custom API pricing
        self.input_cost_spin.setValue(2.0)
        self.output_cost_spin.setValue(8.0)

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

        # Reset engine tabs
        self.mvmz_tab.reset_to_defaults()
        self.wolf_tab.reset_to_defaults()
        self.csv_tab.reset_to_defaults()
        self.srpg_tab.reset_to_defaults()
        
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
            "faceWidth": min(self.width_spin.value(), self.face_width_spin.value()),
            "listWidth": self.list_width_spin.value(),
            "noteWidth": self.note_width_spin.value(),
            "convertQuotes": self.convert_quotes_cb.isChecked(),
            "useSfxReference": self.use_sfx_reference_cb.isChecked(),
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
        if not self._active_api_key_secret() and not self._active_api_key_is_optional():
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
