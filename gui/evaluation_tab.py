#!/usr/bin/env python3
"""Blinded, budget-capped translation model evaluation page."""

from __future__ import annotations

import html
import os
import re
import threading
from pathlib import Path

from PyQt5.QtCore import QEvent, Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QBrush, QColor
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QAction,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QFrame,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QSizePolicy,
    QWidget,
)

from gui.ui_components import (
    PageHeader,
    SectionCard,
    configure_action_button,
    configure_icon_button,
    make_page_layout,
    set_status_text,
)
from gui.config_tab import API_URL_PRESETS, ConfigComboBox, ConfigMenu, ModelFetchThread
from gui.theme import COLORS
from util import api_keys as api_key_vault
from util import evaluation
from util.skills import load_clipboard_skill


class _EvaluationWorker(QThread):
    done = pyqtSignal(bool, str, object)
    log = pyqtSignal(str)

    def __init__(self, task, parent=None, stop_event=None):
        super().__init__(parent)
        self._task = task
        self._graceful_shutdown_only = stop_event is not None
        self._stop_event = stop_event or threading.Event()

    def request_stop(self):
        self._stop_event.set()
        self.requestInterruption()

    def stop(self):
        """Propagate application shutdown to nested model workers."""
        self.request_stop()

    def run(self):
        try:
            payload = self._task(self.log.emit)
            self.done.emit(True, "", payload)
        except Exception as exc:
            import traceback

            self.log.emit(traceback.format_exc())
            self.done.emit(False, str(exc), None)


class _EvaluationReadWorker(QThread):
    """Run startup/history reads without blocking the Qt event loop."""

    loaded = pyqtSignal(object, str)

    def __init__(self, task, parent=None):
        super().__init__(parent)
        self._task = task

    def run(self):
        try:
            self.loaded.emit(self._task(), "")
        except Exception as exc:
            self.loaded.emit(None, str(exc))


class _IgnoreClosedComboWheel:
    """Let a containing scroll area own wheel gestures over closed combos."""

    def wheelEvent(self, event):
        if self.view().isVisible():
            super().wheelEvent(event)
            return
        event.ignore()


class _EvaluationComboBox(_IgnoreClosedComboWheel, QComboBox):
    pass


class _EvaluationModelComboBox(_IgnoreClosedComboWheel, ConfigComboBox):
    pass


class EvaluationTab(QWidget):
    """Prepare, submit, and review a user-defined model comparison."""

    COLUMNS = (
        "Model", "API URL", "Mode", "Status", "Likely upper", "Actual",
        "No-cache", "Cache read", "Valid", "Consistency", "Meaning Accuracy",
        "Glossary & Prompt",
        "Natural & Contextual", "Best overall",
    )
    COLUMN_LABELS = {
        "Meaning Accuracy": "Meaning\nAccuracy",
        "Glossary & Prompt": "Glossary &\nPrompt",
        "Natural & Contextual": "Natural &\nContextual",
        "Best overall": "Best\noverall",
        "Cache read": "Cache\nread",
    }
    COLUMN_TOOLTIPS = {
        "Actual": (
            "Total provider cost calculated from the returned token usage."
        ),
        "No-cache": (
            "Calculated cost for the same provider tokens without prompt "
            "caching or prewarm requests."
        ),
        "Cache read": (
            "Share of evaluation input tokens served from the provider cache."
        ),
        "Valid": (
            "Lines that passed automatic output and game-code checks.\n"
            "This does not measure translation quality."
        ),
        "Consistency": (
            "Repeated samples translated exactly the same every run.\n"
            "Higher means more repeatable, not better."
        ),
        "Meaning Accuracy": (
            "Blind ranking for preserving the original meaning,\n"
            "including intent, polarity, subjects, and quantities."
        ),
        "Glossary & Prompt": (
            "Blind ranking for correct glossary terms\n"
            "and system-prompt rules."
        ),
        "Natural & Contextual": (
            "Blind ranking for fluent, context-appropriate English\n"
            "and consistent character voice."
        ),
        "Best overall": (
            "Overall blind ranking across all quality factors.\n"
            "Ties split points; samples are weighted by line count."
        ),
    }
    BENCHMARK_SIZE_TOOLTIPS = {
        "Total test lines": (
            "Number of unique Japanese lines included in the primary blinded "
            "comparison. More lines improve coverage but increase cost and review work."
        ),
        "Lines per sample": (
            "Maximum contiguous same-scene lines grouped into one translation request "
            "and one blinded review row. Larger samples provide more local context but "
            "make each review decision broader."
        ),
        "Repeated samples": (
            "Number of selected samples translated more than once to measure "
            "consistency. These extra attempts increase cost but do not add new "
            "blind-review rows."
        ),
        "Runs per repeated sample": (
            "Total translation attempts for each repeated sample, including the first. "
            "Consistency requires exact normalized agreement across every attempt."
        ),
    }
    PROVIDER_PRESETS = API_URL_PRESETS
    MODEL_SUGGESTIONS = {
        "openai": ("gpt-5.6-terra", "gpt-5", "gpt-4.1", "gpt-4.1-mini"),
        "gemini": ("gemini-3.6-flash", "gemini-3.5-flash", "gemini-2.5-flash"),
        "anthropic": ("claude-sonnet-5", "claude-sonnet-4-6", "claude-haiku-4-5"),
    }
    TEST_TEMPLATES = (
        ("Quick — 120 lines", 120, 10, 3, 3),
        ("Standard — 360 lines (recommended)", 360, 10, 12, 3),
        ("Thorough — 600 lines", 600, 10, 18, 3),
    )
    CONTENT_PRESETS = (
        ("Balanced — dialogue/events + database", "balanced"),
        ("Dialogue/events only", "events"),
        ("Database only", "database"),
        ("Custom source selection", "custom"),
    )
    COMPARISON_MODEL_COLORS = (
        COLORS.series_blue,
        COLORS.series_green,
        COLORS.series_gold,
        COLORS.series_purple,
        COLORS.series_cyan,
        COLORS.series_orange,
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.project_root = Path(
            getattr(parent, "project_root", None) or Path(__file__).resolve().parent.parent
        )
        self.current_run_dir: Path | None = None
        self._last_review_path: Path | None = None
        self._worker: _EvaluationWorker | None = None
        self._worker_cancelable = False
        self._worker_uses_translation_runtime = False
        self._candidate_widgets: list[dict] = []
        self._content_inventory: dict = {}
        self._content_source_items: dict[str, QTreeWidgetItem] = {}
        self._content_map_items: dict[str, QTreeWidgetItem] = {}
        self._custom_content_selection: dict | None = None
        self._active_content_preset = "balanced"
        self._initial_load_scheduled = False
        self._history_load_worker: _EvaluationReadWorker | None = None
        self._inventory_load_worker: _EvaluationReadWorker | None = None
        self._comparison_load_worker: _EvaluationReadWorker | None = None
        self._comparison_data: dict | None = None
        self._comparison_run_dir: Path | None = None
        self._comparison_generation = 0
        self._comparison_filtered_samples: list[dict] = []
        self._comparison_visible_candidates: list[str] = []
        self._pending_inventory_selection: str | None = None
        self._inventory_load_generation = 0
        self._init_ui()
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(60_000)
        self._poll_timer.timeout.connect(self.refresh_results)

    def _workflow_game_root(self) -> str:
        """Return the same configured game root used by normal translation."""
        translation_tab = getattr(self.parent_window, "translation_tab", None)
        settings = getattr(translation_tab, "settings", None)
        if settings is None:
            settings = getattr(self.parent_window, "settings", None)
        if settings is None:
            return ""
        for key in ("workflow/last_game_folder", "last_game_folder"):
            value = str(settings.value(key, "") or "").strip()
            if value:
                return value
        return ""

    def _evaluation_game_root(self, selected: str | Path) -> Path | None:
        return evaluation.resolve_evaluation_game_root(
            selected, fallback_game_root=self._workflow_game_root()
        )

    def _configured_model(self) -> str:
        config_tab = getattr(self.parent_window, "config_tab", None)
        model_combo = getattr(config_tab, "model_combo", None)
        if model_combo is not None:
            model = model_combo.currentText().strip()
            if model:
                return model
        return str(os.getenv("model") or evaluation.DEFAULT_CANDIDATES[0]["model"])

    def _default_candidate(self) -> dict:
        key_name = api_key_vault.get_active_name()
        endpoint = api_key_vault.get_endpoint(key_name) or ""
        if not endpoint:
            config_tab = getattr(self.parent_window, "config_tab", None)
            endpoint_edit = getattr(config_tab, "api_url_edit", None)
            if endpoint_edit is not None:
                endpoint = endpoint_edit.text().strip()
        return {
            "endpoint": endpoint or evaluation.DEFAULT_CANDIDATES[0]["endpoint"],
            "model": self._configured_model(),
            "execution": "batch",
            "key_name": key_name,
        }

    def _init_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.page_scroll = QScrollArea()
        self.page_scroll.setWidgetResizable(True)
        self.page_scroll.setFrameShape(QFrame.NoFrame)
        self.page_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        page = QWidget()
        layout = make_page_layout(page)
        self.page_scroll.setWidget(page)
        outer.addWidget(self.page_scroll)
        layout.addWidget(PageHeader(
            "Translation Evaluation",
            "Compare batch or live models on the same Japanese game text. No normal translation cache is reused.",
        ))

        self.history_combo = _EvaluationComboBox()
        self.history_combo.setSizeAdjustPolicy(
            QComboBox.AdjustToMinimumContentsLengthWithIcon
        )
        self.history_combo.setMinimumContentsLength(32)
        self.history_combo.setMinimumWidth(300)
        self.history_combo.setMaxVisibleItems(15)
        self.history_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.history_combo.setToolTip("Choose a saved evaluation to view")
        self.history_combo.currentIndexChanged.connect(
            self._update_history_actions
        )
        self.history_combo.activated.connect(
            lambda _index: self._open_selected_history()
        )
        self.export_evaluation_btn = QPushButton("Export evaluation")
        self.import_evaluation_btn = QPushButton("Import evaluation")
        for button in (
            self.export_evaluation_btn,
            self.import_evaluation_btn,
        ):
            configure_action_button(button, variant="secondary")
            button.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.export_evaluation_btn.clicked.connect(self._export_evaluation_archive)
        self.import_evaluation_btn.clicked.connect(self._import_evaluation_archive)

        setup = SectionCard(
            "Benchmark setup",
            "Add at least two models. Preparing scans the selected game offline; running always shows each model's projected cost first.",
            compact=True,
        )
        self.setup_card = setup
        layout.addWidget(setup)
        self.candidate_grid = QGridLayout()
        self.candidate_grid.setHorizontalSpacing(12)
        self.candidate_grid.setVerticalSpacing(8)
        for column, text in enumerate((
            "API URL", "Saved API key", "Model", "Run as", "", ""
        )):
            label = QLabel(text)
            label.setStyleSheet("font-weight: 600;")
            self.candidate_grid.addWidget(label, 0, column)
        self.candidate_grid.setColumnMinimumWidth(0, 320)
        self.candidate_grid.setColumnMinimumWidth(3, 104)
        self.candidate_grid.setColumnMinimumWidth(4, 72)
        self.candidate_grid.setColumnMinimumWidth(5, 88)
        self.candidate_grid.setColumnStretch(1, 2)
        self.candidate_grid.setColumnStretch(2, 3)
        setup.add_layout(self.candidate_grid)

        candidate = self._default_candidate()
        self._add_candidate_row(
            candidate["endpoint"], candidate["model"], candidate["execution"],
            key_name=candidate["key_name"],
        )
        self.add_model_btn = QPushButton("Add model")
        configure_action_button(self.add_model_btn, variant="secondary")
        self.add_model_btn.clicked.connect(
            lambda: self._add_candidate_row(
                "https://api.openai.com/v1", "", "batch"
            )
        )
        setup.add_widget(self.add_model_btn)

        source_row = QGridLayout()
        source_row.setHorizontalSpacing(12)
        default_source = self._workflow_game_root() or str(self.project_root / "files")
        self.source_edit = QLineEdit(default_source)
        self.source_edit.setPlaceholderText("Select an RPG Maker MV/MZ game folder…")
        self.source_edit.setToolTip(
            "Select the folder containing the game. Evaluation automatically finds "
            "data/ (MZ) or www/data/ (MV). A direct JSON data folder also works."
        )
        self.source_edit.editingFinished.connect(self._update_source_resolution)
        self.source_btn = QPushButton("Browse")
        configure_action_button(self.source_btn, variant="secondary")
        self.source_btn.clicked.connect(self._browse_source)
        source_row.addWidget(QLabel("RPG Maker game:"), 0, 0)
        source_row.addWidget(self.source_edit, 0, 1)
        source_row.addWidget(self.source_btn, 0, 2)
        source_row.setColumnMinimumWidth(0, 132)
        source_row.setColumnStretch(1, 1)
        setup.add_layout(source_row)
        self.source_resolution_label = QLabel()
        self.source_resolution_label.setWordWrap(True)
        setup.add_widget(self.source_resolution_label)

        content_grid = QGridLayout()
        content_grid.setHorizontalSpacing(12)
        content_grid.setVerticalSpacing(8)
        content_label = QLabel("Content selection ⓘ")
        content_label.setStyleSheet("font-weight: 600;")
        content_label.setToolTip(
            "Choose which RPG Maker source types may be sampled. Every model in "
            "the evaluation receives the same selected lines."
        )
        self.content_preset_combo = _EvaluationComboBox()
        for label, preset in self.CONTENT_PRESETS:
            self.content_preset_combo.addItem(label, preset)
        self.content_preset_combo.setToolTip(
            "Balanced keeps the general-purpose dialogue, database, and control-code "
            "mix. Choose Custom to select individual source types or map files."
        )
        content_grid.addWidget(content_label, 0, 0)
        content_grid.addWidget(self.content_preset_combo, 0, 1)
        content_grid.setColumnStretch(1, 1)

        self.content_tree = QTreeWidget()
        self.content_tree.setHeaderLabels(("Eligible source", "Japanese lines"))
        self.content_tree.setRootIsDecorated(True)
        self.content_tree.setAlternatingRowColors(True)
        self.content_tree.setMinimumHeight(190)
        self.content_tree.setMaximumHeight(250)
        self.content_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.content_tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        content_grid.addWidget(self.content_tree, 1, 0, 1, 2)
        self.content_preview_label = QLabel()
        self.content_preview_label.setWordWrap(True)
        content_grid.addWidget(self.content_preview_label, 2, 0, 1, 2)
        setup.add_layout(content_grid)
        self.content_preset_combo.currentIndexChanged.connect(
            self._on_content_preset_changed
        )
        self.content_tree.itemChanged.connect(
            lambda _item, _column: self._on_content_tree_changed()
        )
        self._populate_content_tree({})
        self._apply_content_selection(
            evaluation.normalize_content_selection({"preset": "balanced"})
        )
        set_status_text(
            self.source_resolution_label,
            "Open Evaluation to scan the selected game's available content.",
            "neutral",
        )

        options = QGridLayout()
        options.setHorizontalSpacing(12)
        options.setVerticalSpacing(8)

        self.test_size_combo = _EvaluationComboBox()
        for label, lines, sample_size, repeated_samples, repetitions in self.TEST_TEMPLATES:
            self.test_size_combo.addItem(
                label, (lines, sample_size, repeated_samples, repetitions)
            )
        self.test_size_combo.addItem("Custom", None)
        self.test_size_combo.setCurrentIndex(1)
        self.test_size_combo.currentIndexChanged.connect(
            self._apply_test_template
        )
        self.budget_spin = QDoubleSpinBox()
        self.budget_spin.setRange(1.0, 100.0)
        self.budget_spin.setDecimals(2)
        self.budget_spin.setValue(evaluation.DEFAULT_BUDGET_USD)
        self.budget_spin.setPrefix("$")

        option_widgets = (
            ("Test template", self.test_size_combo),
            ("Budget per model", self.budget_spin),
        )
        for index, (label_text, widget) in enumerate(option_widgets):
            widget.setMinimumWidth(132)
            widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            label = QLabel(label_text)
            label.setStyleSheet("font-weight: 600;")
            column = index * 2
            options.addWidget(label, 0, column, 1, 2)
            options.addWidget(widget, 1, column, 1, 2)

        self.custom_target_spin = QSpinBox()
        self.custom_target_spin.setRange(60, 5_000)
        self.custom_target_spin.setValue(360)
        self.custom_target_spin.setSuffix(" lines")
        self.custom_sample_size_spin = QSpinBox()
        self.custom_sample_size_spin.setRange(1, 2_147_483_647)
        self.custom_sample_size_spin.setValue(evaluation.DEFAULT_SAMPLE_SIZE)
        self.custom_sample_size_spin.setSuffix(" lines")
        self.custom_repeated_samples_spin = QSpinBox()
        self.custom_repeated_samples_spin.setRange(0, 500)
        self.custom_repeated_samples_spin.setValue(
            evaluation.DEFAULT_STABILITY_SAMPLES
        )
        self.custom_repeated_samples_spin.setSuffix(" samples")
        self.custom_repetitions_spin = QSpinBox()
        self.custom_repetitions_spin.setRange(1, 10)
        self.custom_repetitions_spin.setValue(evaluation.DEFAULT_REPETITIONS)
        self.custom_repetitions_spin.setSuffix(" runs")
        custom_widgets = (
            ("Total test lines", self.custom_target_spin),
            ("Lines per sample", self.custom_sample_size_spin),
            ("Repeated samples", self.custom_repeated_samples_spin),
            ("Runs per repeated sample", self.custom_repetitions_spin),
        )
        self.benchmark_size_labels = {}
        for index, (label_text, widget) in enumerate(custom_widgets):
            tooltip = self.BENCHMARK_SIZE_TOOLTIPS[label_text]
            label = QLabel(f"{label_text} ⓘ")
            label.setStyleSheet("font-weight: 600;")
            label.setToolTip(tooltip)
            widget.setToolTip(tooltip)
            self.benchmark_size_labels[label_text] = label
            options.addWidget(label, 2, index)
            options.addWidget(widget, 3, index)
            options.setColumnStretch(index, 1)
        setup.add_layout(options)
        self._apply_test_template()
        self.custom_target_spin.valueChanged.connect(
            lambda _value: self._update_content_preview()
        )

        actions = QGridLayout()
        actions.setHorizontalSpacing(8)
        self.prepare_btn = QPushButton("Prepare benchmark")
        self.submit_btn = QPushButton("Run evaluation")
        self.cancel_btn = QPushButton("Stop live evaluation")
        self.refresh_btn = QPushButton("Refresh results")
        self.export_btn = QPushButton("Export blind review")
        self.copy_review_skill_btn = QPushButton("Copy review skill")
        self.import_btn = QPushButton("Import reviewed CSV")
        configure_action_button(self.prepare_btn, variant="primary")
        for button in (
            self.submit_btn, self.cancel_btn, self.refresh_btn, self.export_btn,
            self.copy_review_skill_btn, self.import_btn,
        ):
            configure_action_button(button, variant="secondary")
        self.copy_review_skill_btn.setToolTip(
            "Copy instructions for an AI helper to review the blinded CSV. "
            "AI judgments can be biased and should be treated as a second opinion."
        )
        self.export_btn.setToolTip(
            "Choose which models to compare, then export their translations "
            "with randomized labels. Models with no usable output are unavailable."
        )
        self.prepare_btn.clicked.connect(self.prepare_benchmark)
        self.submit_btn.clicked.connect(self.submit_batches)
        self.cancel_btn.clicked.connect(self.cancel_evaluation)
        self.refresh_btn.clicked.connect(self.refresh_results)
        self.export_btn.clicked.connect(self.export_review)
        self.copy_review_skill_btn.clicked.connect(self.copy_review_skill)
        self.import_btn.clicked.connect(self.import_review)
        for column, button in enumerate((
            self.prepare_btn, self.submit_btn, self.cancel_btn, self.refresh_btn,
        )):
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            actions.addWidget(button, 0, column * 2, 1, 2)
        for column in range(8):
            actions.setColumnStretch(column, 1)
        for column, button in enumerate((
            self.export_btn, self.copy_review_skill_btn, self.import_btn,
        )):
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            actions.addWidget(button, 1, column * 2, 1, 2)
        setup.add_layout(actions)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        set_status_text(
            self.status_label,
            "Prepare the test set before any provider requests are sent.",
            "neutral",
        )
        setup.add_widget(self.status_label)

        results = SectionCard(
            "Evaluation results",
            "Choose a saved run or inspect the current one. Translation quality is decided from the blinded CSV, not model names.",
        )
        layout.addWidget(results, 1)
        history_bar = QGridLayout()
        history_bar.setHorizontalSpacing(8)
        history_bar.addWidget(QLabel("Saved evaluation:"), 0, 0)
        history_bar.addWidget(self.history_combo, 0, 1)
        history_bar.addWidget(self.export_evaluation_btn, 0, 2)
        history_bar.addWidget(self.import_evaluation_btn, 0, 3)
        history_bar.setColumnStretch(1, 1)
        results.add_layout(history_bar)
        self.results_tabs = QTabWidget()
        self.results_tabs.setMinimumHeight(540)
        summary_page = QWidget()
        summary_layout = QVBoxLayout(summary_page)
        summary_layout.setContentsMargins(0, 8, 0, 0)
        summary_layout.setSpacing(8)
        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        for name, label in self.COLUMN_LABELS.items():
            index = self.COLUMNS.index(name)
            self.table.horizontalHeaderItem(index).setText(label)
        for name, tooltip in self.COLUMN_TOOLTIPS.items():
            index = self.COLUMNS.index(name)
            item = self.table.horizontalHeaderItem(index)
            item.setText(f"{item.text()} ⓘ")
            item.setToolTip(tooltip)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.setTextElideMode(Qt.ElideMiddle)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(1)
        header.setMinimumHeight(header.fontMetrics().lineSpacing() * 2 + 12)
        for index in range(len(self.COLUMNS)):
            header.setSectionResizeMode(index, QHeaderView.Fixed)
        self.table.viewport().installEventFilter(self)
        summary_layout.addWidget(self.table, 1)
        self.results_tabs.addTab(summary_page, "Score summary")

        comparison_page = QWidget()
        comparison_layout = QVBoxLayout(comparison_page)
        comparison_layout.setContentsMargins(10, 10, 10, 10)
        comparison_layout.setSpacing(10)
        comparison_toolbar = QGridLayout()
        comparison_toolbar.setHorizontalSpacing(10)
        comparison_toolbar.setVerticalSpacing(8)
        self.comparison_search = QLineEdit()
        self.comparison_search.setPlaceholderText(
            "Search source, translations, scenes, or review notes…"
        )
        self.comparison_search.setClearButtonEnabled(True)
        self.comparison_filter = _EvaluationComboBox()
        for label, value in (
            ("All samples", "all"),
            ("Reviewed", "reviewed"),
            ("Ties", "ties"),
            ("Has notes", "notes"),
            ("Missing or invalid", "problems"),
        ):
            self.comparison_filter.addItem(label, value)
        self.comparison_models_btn = QToolButton()
        self.comparison_models_btn.setText("Models")
        self.comparison_models_btn.setPopupMode(QToolButton.InstantPopup)
        self.comparison_models_menu = QMenu(self.comparison_models_btn)
        self.comparison_models_btn.setMenu(self.comparison_models_menu)
        self.comparison_reveal_models = QCheckBox("Show model names")
        self.comparison_reveal_models.setToolTip(
            "Before importing a blind review, hiding names helps avoid model-name bias."
        )
        self.comparison_previous_btn = QPushButton("←")
        self.comparison_next_btn = QPushButton("→")
        configure_icon_button(
            self.comparison_previous_btn,
            accessible_name="Previous comparison sample",
            tooltip="Previous sample",
        )
        configure_icon_button(
            self.comparison_next_btn,
            accessible_name="Next comparison sample",
            tooltip="Next sample",
        )
        self.comparison_counter = QLabel("—")
        self.comparison_counter.setAlignment(Qt.AlignCenter)
        self.comparison_counter.setMinimumWidth(72)
        self.comparison_status = QLabel(
            "Choose a completed evaluation to compare model outputs."
        )
        self.comparison_status.setWordWrap(True)
        self.comparison_status.setStyleSheet(f"color: {COLORS.text_muted};")
        comparison_toolbar.addWidget(self.comparison_search, 0, 0)
        comparison_toolbar.addWidget(self.comparison_filter, 0, 1)
        comparison_toolbar.addWidget(self.comparison_models_btn, 0, 2)
        comparison_toolbar.addWidget(self.comparison_reveal_models, 0, 3)
        comparison_toolbar.addWidget(self.comparison_status, 1, 0, 1, 2)
        navigation = QHBoxLayout()
        navigation.setSpacing(6)
        navigation.addStretch(1)
        navigation.addWidget(self.comparison_previous_btn)
        navigation.addWidget(self.comparison_counter)
        navigation.addWidget(self.comparison_next_btn)
        comparison_toolbar.addLayout(navigation, 1, 2, 1, 2)
        comparison_toolbar.setColumnStretch(0, 1)
        comparison_layout.addLayout(comparison_toolbar)

        self.comparison_splitter = QSplitter(Qt.Horizontal)
        self.comparison_splitter.setObjectName("evaluationComparisonSplitter")
        self.comparison_sample_list = QListWidget()
        self.comparison_sample_list.setAlternatingRowColors(True)
        self.comparison_sample_list.setWordWrap(True)
        self.comparison_sample_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff
        )
        self.comparison_sample_list.setMinimumWidth(280)
        self.comparison_sample_list.setMaximumWidth(380)
        self.comparison_splitter.addWidget(self.comparison_sample_list)

        comparison_detail = QWidget()
        detail_layout = QVBoxLayout(comparison_detail)
        detail_layout.setContentsMargins(12, 0, 0, 0)
        detail_layout.setSpacing(10)
        self.comparison_sample_heading = QLabel("Select a sample")
        self.comparison_sample_heading.setStyleSheet(
            f"color: {COLORS.text_primary}; font-weight: 600; font-size: 14px;"
        )
        self.comparison_sample_heading.setTextInteractionFlags(
            Qt.TextSelectableByMouse
        )
        detail_layout.addWidget(self.comparison_sample_heading)
        self.comparison_sample_meta = QLabel()
        self.comparison_sample_meta.setStyleSheet(f"color: {COLORS.text_muted};")
        self.comparison_sample_meta.setTextInteractionFlags(Qt.TextSelectableByMouse)
        detail_layout.addWidget(self.comparison_sample_meta)

        self.comparison_review_card = QFrame()
        self.comparison_review_card.setObjectName("evaluationReviewCard")
        self.comparison_review_card.setStyleSheet(f"""
            QFrame#evaluationReviewCard {{
                background-color: {COLORS.surface_1};
                border: 1px solid {COLORS.border};
                border-radius: 6px;
            }}
            QLabel#evaluationReviewTitle {{
                color: {COLORS.text_primary};
                font-weight: 600;
            }}
            QLabel#evaluationReviewMetric {{
                color: {COLORS.text_muted};
                font-weight: 600;
            }}
        """)
        review_layout = QGridLayout(self.comparison_review_card)
        review_layout.setContentsMargins(12, 10, 12, 10)
        review_layout.setHorizontalSpacing(16)
        review_layout.setVerticalSpacing(5)
        review_title = QLabel("Blind review verdict")
        review_title.setObjectName("evaluationReviewTitle")
        self.comparison_review_status = QLabel()
        self.comparison_review_status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        review_layout.addWidget(review_title, 0, 0)
        review_layout.addWidget(self.comparison_review_status, 0, 1)
        self.comparison_review_metric_labels = {}
        self.comparison_review_values = {}
        metric_rows = (
            ("overall", "Overall"),
            ("meaning_accuracy", "Meaning accuracy"),
            ("glossary_prompt", "Glossary & prompt"),
            ("natural_contextual", "Natural & contextual"),
        )
        for row, (metric, label_text) in enumerate(metric_rows, start=1):
            label = QLabel(label_text)
            label.setObjectName("evaluationReviewMetric")
            value = QLabel("—")
            value.setTextFormat(Qt.RichText)
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            review_layout.addWidget(label, row, 0)
            review_layout.addWidget(value, row, 1)
            self.comparison_review_metric_labels[metric] = label
            self.comparison_review_values[metric] = value
        self.comparison_review_notes = QLabel()
        self.comparison_review_notes.setWordWrap(True)
        self.comparison_review_notes.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.comparison_review_notes.setStyleSheet(
            f"color: {COLORS.text_secondary}; border-top: 1px solid {COLORS.border}; "
            "padding-top: 7px;"
        )
        review_layout.addWidget(self.comparison_review_notes, 5, 0, 1, 2)
        review_layout.setColumnStretch(1, 1)
        detail_layout.addWidget(self.comparison_review_card)
        self.comparison_table = QTableWidget(0, 0)
        self.comparison_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.comparison_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.comparison_table.setWordWrap(True)
        self.comparison_table.setAlternatingRowColors(True)
        self.comparison_table.verticalHeader().setVisible(True)
        self.comparison_table.verticalHeader().setDefaultAlignment(Qt.AlignCenter)
        self.comparison_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.comparison_table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.comparison_table.viewport().installEventFilter(self)
        detail_layout.addWidget(self.comparison_table, 1)
        self.comparison_splitter.addWidget(comparison_detail)
        self.comparison_splitter.setStretchFactor(0, 0)
        self.comparison_splitter.setStretchFactor(1, 1)
        comparison_layout.addWidget(self.comparison_splitter, 1)
        self.comparison_splitter.hide()
        self._comparison_tab_index = self.results_tabs.addTab(
            comparison_page, "Output comparison"
        )
        self.results_tabs.setTabEnabled(self._comparison_tab_index, False)
        self.results_tabs.currentChanged.connect(self._on_results_tab_changed)
        self.comparison_search.textChanged.connect(
            self._refresh_comparison_sample_list
        )
        self.comparison_filter.currentIndexChanged.connect(
            self._refresh_comparison_sample_list
        )
        self.comparison_reveal_models.toggled.connect(
            self._refresh_comparison_presenter
        )
        self.comparison_sample_list.currentRowChanged.connect(
            self._display_comparison_selection
        )
        self.comparison_previous_btn.clicked.connect(
            lambda: self._move_comparison_selection(-1)
        )
        self.comparison_next_btn.clicked.connect(
            lambda: self._move_comparison_selection(1)
        )
        results.add_widget(self.results_tabs, 2)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(150)
        self.log.setPlaceholderText("Evaluation activity…")
        results.add_widget(self.log, 1)
        QTimer.singleShot(0, self._refresh_responsive_geometry)
        self._update_actions()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._refresh_responsive_geometry)

    def eventFilter(self, watched, event):
        if (
            hasattr(self, "table")
            and watched is self.table.viewport()
            and event.type() == QEvent.Resize
        ):
            QTimer.singleShot(0, self._resize_result_columns)
        if (
            hasattr(self, "comparison_table")
            and watched is self.comparison_table.viewport()
            and event.type() == QEvent.Resize
        ):
            QTimer.singleShot(0, self._resize_comparison_columns)
        return super().eventFilter(watched, event)

    def _refresh_responsive_geometry(self):
        if hasattr(self, "setup_card"):
            self.setup_card.setMinimumHeight(0)
            self.setup_card.setMinimumHeight(self.setup_card.sizeHint().height())
        self._resize_result_columns()
        self._resize_comparison_controls()
        self._resize_comparison_columns()

    def _resize_comparison_controls(self):
        if not hasattr(self, "comparison_filter"):
            return
        peer_dropdowns = (
            self.comparison_filter,
            self.comparison_models_btn,
        )
        peer_height = max(widget.sizeHint().height() for widget in (
            self.comparison_search, *peer_dropdowns,
        ))
        peer_width = max(widget.sizeHint().width() for widget in peer_dropdowns)
        for widget in (self.comparison_search, *peer_dropdowns):
            widget.setFixedHeight(peer_height)
        for widget in peer_dropdowns:
            widget.setFixedWidth(peer_width)

    def _resize_result_columns(self):
        """Keep every result column visible within the table viewport."""
        if not hasattr(self, "table"):
            return
        viewport_width = max(0, self.table.viewport().width() - 1)
        if not viewport_width:
            return
        weights = (
            1.55, 1.65, 0.60, 0.82, 0.68, 0.62, 0.68, 0.68,
            0.60, 0.90, 0.95, 1.02, 1.12, 0.82,
        )
        column_count = len(weights)
        compact_minimum = 32
        if viewport_width < compact_minimum * column_count:
            base_width, remainder = divmod(viewport_width, column_count)
            widths = [
                base_width + int(index < remainder)
                for index in range(column_count)
            ]
        else:
            distributable = viewport_width - compact_minimum * column_count
            total_weight = sum(weights)
            widths = [
                compact_minimum + int(distributable * weight / total_weight)
                for weight in weights
            ]
            remainder = viewport_width - sum(widths)
            for index in range(remainder):
                widths[index % column_count] += 1

        for index, width in enumerate(widths):
            self.table.setColumnWidth(index, width)

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_keys()
        if not self._initial_load_scheduled:
            self._initial_load_scheduled = True
            QTimer.singleShot(0, self._start_initial_load)

    def _append_log(self, message: str):
        if message:
            self.log.append(str(message).rstrip())

    def _selected_history_run(self) -> Path | None:
        value = self.history_combo.currentData(Qt.UserRole)
        return Path(str(value)) if value else None

    def _update_history_actions(self):
        busy = self._worker is not None and self._worker.isRunning()
        has_selection = self._selected_history_run() is not None
        selected_status = str(
            self.history_combo.currentData(Qt.UserRole + 1) or ""
        )
        self.history_combo.setEnabled(not busy and has_selection)
        self.export_evaluation_btn.setEnabled(
            not busy and has_selection and selected_status != "prepared"
        )
        self.import_evaluation_btn.setEnabled(not busy)

    def _refresh_history(self, select_run: str | Path | None = None):
        self._populate_history(
            evaluation.list_runs(self.project_root), select_run=select_run
        )

    def _populate_history(
        self,
        runs: list[dict],
        *,
        select_run: str | Path | None = None,
    ):
        preferred = Path(select_run).resolve() if select_run else (
            self.current_run_dir.resolve() if self.current_run_dir else None
        )
        runs = list(runs)
        listed_paths = {
            Path(run["run_dir"]).resolve() for run in runs
        }
        if preferred is not None and preferred not in listed_paths:
            try:
                current = evaluation.run_history_entry(preferred)
            except (OSError, ValueError, KeyError):
                current = None
            if current is not None and current.get("status") in {"prepared", "failed"}:
                runs.insert(0, current)
        self.history_combo.blockSignals(True)
        self.history_combo.clear()
        selected_index = -1
        for index, run in enumerate(runs):
            run_dir = Path(run["run_dir"]).resolve()
            created = str(run.get("created_at") or "").replace("T", " ")[:16]
            models = ", ".join(run.get("models") or []) or "—"
            modes = ", ".join(dict.fromkeys(
                str(mode).title() for mode in run.get("modes") or []
            )) or "Batch"
            status = str(run.get("status") or "unknown").replace("_", " ").title()
            lines = int(run.get("selected_segments", 0) or 0)
            reviewed_samples = int(
                run.get("reviewed_samples", run.get("reviewed", 0)) or 0
            )
            reviewed_lines = int(
                run.get("reviewed_lines", reviewed_samples) or 0
            )
            label = (
                f"{created or run_dir.name}  ·  {models}  ·  {modes}  ·  "
                f"{status}  ·  {lines:,} lines"
            )
            if run.get("review_complete"):
                label += "  ·  Review complete"
                if reviewed_lines != lines:
                    label += f" ({reviewed_lines:,} eligible lines)"
            elif reviewed_lines:
                label += f"  ·  {reviewed_lines:,} lines reviewed"
            self.history_combo.addItem(label, str(run_dir))
            self.history_combo.setItemData(index, label, Qt.ToolTipRole)
            self.history_combo.setItemData(
                index, str(run.get("status") or ""), Qt.UserRole + 1
            )
            if preferred is not None and run_dir == preferred:
                selected_index = index
        if selected_index < 0 and runs:
            selected_index = 0
        self.history_combo.setCurrentIndex(selected_index)
        self.history_combo.blockSignals(False)
        self._update_history_actions()

    def _open_run(
        self,
        run_dir: str | Path,
        *,
        refresh_history: bool = True,
        defer_inventory: bool = False,
    ):
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(
                self, "Evaluation busy", "Wait for the current evaluation operation to finish."
            )
            return
        path = Path(run_dir)
        try:
            state, manifest = evaluation.load_run(path)
        except Exception as exc:
            QMessageBox.warning(self, "Evaluation history", str(exc))
            return
        self.current_run_dir = path
        canonical_review = path / "blind_review.csv"
        self._last_review_path = canonical_review if canonical_review.is_file() else None
        source_dir = Path(str(manifest.get("source_dir") or ""))
        saved_game_root_text = str(manifest.get("game_root") or "").strip()
        saved_game_root = Path(saved_game_root_text) if saved_game_root_text else None
        display_source = (
            saved_game_root
            if saved_game_root is not None and saved_game_root.is_dir()
            else source_dir
        )
        if display_source.is_dir():
            self.source_edit.setText(str(display_source))
            if defer_inventory:
                self._start_initial_inventory(str(display_source))
            else:
                self._update_source_resolution()
        self._restore_benchmark_setup(state, manifest)
        self.log.clear()
        self._append_log(f"Opened evaluation: {state.get('run_id', path.name)}")
        self._display_state(state)
        set_status_text(
            self.status_label,
            f"Viewing saved evaluation {state.get('run_id', path.name)}.",
            "neutral",
        )
        try:
            evaluation.sync_run_history(path)
        except Exception as history_exc:
            self._append_log(f"Could not sync Batch History: {history_exc}")
        if refresh_history:
            self._refresh_history(path)

    def _open_selected_history(self):
        selected = self._selected_history_run()
        if selected is not None:
            try:
                self._open_run(selected, defer_inventory=True)
            except Exception as exc:
                # Qt invokes this method from a native input callback. Never
                # let a malformed/stale saved run escape that boundary because
                # some PyQt/Python combinations abort on an unhandled slot
                # exception.
                self._append_log(f"Could not open saved evaluation: {exc}")
                QMessageBox.warning(self, "Open evaluation", str(exc))

    def _export_evaluation_archive(self):
        selected = self._selected_history_run()
        if selected is None:
            return
        default = str(self.project_root / f"{selected.name}.dazedeval")
        output, _ = QFileDialog.getSaveFileName(
            self,
            "Export evaluation",
            default,
            "Dazed evaluation (*.dazedeval);;ZIP archive (*.zip)",
        )
        if not output:
            return
        try:
            archive = evaluation.export_run_archive(selected, output)
            self._append_log(f"Evaluation exported: {archive}")
            QMessageBox.information(
                self,
                "Evaluation exported",
                f"Saved {archive.name}. API secrets were not included.",
            )
        except Exception as exc:
            QMessageBox.warning(self, "Export evaluation", str(exc))

    def _import_evaluation_archive(self):
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Import evaluation",
            str(self.project_root),
            "Dazed evaluation (*.dazedeval *.zip)",
        )
        if not selected:
            return
        try:
            run_dir = evaluation.import_run_archive(self.project_root, selected)
            self._open_run(run_dir)
            self._append_log(f"Evaluation imported: {run_dir}")
        except Exception as exc:
            QMessageBox.warning(self, "Import evaluation", str(exc))

    def _browse_source(self):
        selected = QFileDialog.getExistingDirectory(
            self, "Select RPG Maker MV/MZ game folder", self.source_edit.text()
        )
        if selected:
            self.source_edit.setText(selected)
            self._update_source_resolution()

    def _update_source_resolution(self):
        # A user-driven source change takes precedence over an in-flight
        # first-open scan. Its eventual result must not overwrite this choice.
        self._inventory_load_generation += 1
        self._pending_inventory_selection = None
        selected = self.source_edit.text().strip()
        if not selected:
            self._refresh_content_inventory(None)
            set_status_text(
                self.source_resolution_label,
                "Select a game folder. Evaluation will find its data/ or www/data/ files.",
                "neutral",
            )
            return
        try:
            data_dir = evaluation.resolve_rpgmaker_data_dir(selected)
        except (FileNotFoundError, ValueError):
            self._refresh_content_inventory(None)
            set_status_text(
                self.source_resolution_label,
                "No MV/MZ data found yet. Choose the game folder, or its data/ or "
                "www/data/ folder.",
                "warning",
            )
            return
        self._refresh_content_inventory(data_dir)
        game_root = self._evaluation_game_root(selected)
        if game_root is None:
            set_status_text(
                self.source_resolution_label,
                f"Game data found: {data_dir}\nTranslation context could not be "
                "resolved. Select the game folder itself so Evaluation can use "
                "the same glossary and game skills as normal translation.",
                "warning",
            )
            return
        set_status_text(
            self.source_resolution_label,
            f"Game data found: {data_dir}\nTranslation context: {game_root} "
            f"(glossary: {game_root / 'glossary.txt'})",
            "success",
        )

    def _refresh_content_inventory(self, data_dir: Path | None):
        if data_dir is None:
            self._content_inventory = {}
            self._populate_content_tree({})
            return
        try:
            inventory = evaluation.content_inventory(data_dir)
        except Exception as exc:
            self._content_inventory = {}
            self._populate_content_tree({})
            set_status_text(
                self.content_preview_label,
                f"Could not scan selectable content: {exc}",
                "warning",
            )
            return
        inventory["source_dir"] = str(data_dir.resolve())
        self._content_inventory = inventory
        self._populate_content_tree(inventory)

    def _populate_content_tree(self, inventory: dict):
        try:
            selection = (
                self._content_selection()
                if self._content_source_items
                else evaluation.normalize_content_selection({
                    "preset": self._active_content_preset
                })
            )
        except ValueError:
            selection = self._custom_content_selection or {
                "preset": "custom",
                "sources": list(evaluation.ALL_CONTENT_SOURCES),
                "include_code_heavy": True,
            }
        counts = inventory.get("source_counts") or {}
        map_counts = inventory.get("map_files") or {}
        self.content_tree.blockSignals(True)
        self.content_tree.clear()
        self._content_source_items = {}
        self._content_map_items = {}
        for _group_id, group_label, sources in evaluation.CONTENT_SOURCE_GROUPS:
            group_count = sum(int(counts.get(source_id, 0)) for source_id, _ in sources)
            group = QTreeWidgetItem([group_label, f"{group_count:,}"])
            group.setFlags(
                group.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate
            )
            self.content_tree.addTopLevelItem(group)
            for source_id, source_label in sources:
                source = QTreeWidgetItem([
                    source_label, f"{int(counts.get(source_id, 0)):,}"
                ])
                source.setFlags(source.flags() | Qt.ItemIsUserCheckable)
                source.setData(0, Qt.UserRole, source_id)
                group.addChild(source)
                self._content_source_items[source_id] = source
                if source_id == "map_events" and map_counts:
                    source.setFlags(
                        source.flags() | Qt.ItemIsAutoTristate
                    )
                    for filename, count in map_counts.items():
                        map_item = QTreeWidgetItem([filename, f"{int(count):,}"])
                        map_item.setFlags(map_item.flags() | Qt.ItemIsUserCheckable)
                        map_item.setData(0, Qt.UserRole, filename)
                        source.addChild(map_item)
                        self._content_map_items[filename] = map_item
            group.setExpanded(True)

        characteristics = QTreeWidgetItem(["Characteristics", ""])
        self.content_tree.addTopLevelItem(characteristics)
        self.code_heavy_item = QTreeWidgetItem([
            "Include control-code-heavy event lines",
            f"{int(inventory.get('code_heavy_segments', 0)):,}",
        ])
        self.code_heavy_item.setFlags(
            self.code_heavy_item.flags() | Qt.ItemIsUserCheckable
        )
        self.code_heavy_item.setToolTip(
            0,
            "Include event lines containing RPG Maker control codes. These are useful "
            "for testing runtime safety as well as translation quality.",
        )
        characteristics.addChild(self.code_heavy_item)
        characteristics.setExpanded(True)
        self.content_tree.blockSignals(False)
        self._apply_content_selection(selection)

    def _apply_content_selection(self, selection: dict):
        selection = evaluation.normalize_content_selection(selection)
        sources = set(selection["sources"])
        selected_maps = set(selection.get("map_files") or [])
        self.content_tree.blockSignals(True)
        for source_id, item in self._content_source_items.items():
            item.setCheckState(
                0, Qt.Checked if source_id in sources else Qt.Unchecked
            )
        if "map_events" in sources:
            for filename, item in self._content_map_items.items():
                item.setCheckState(
                    0,
                    Qt.Checked
                    if not selected_maps or filename in selected_maps
                    else Qt.Unchecked,
                )
        self.code_heavy_item.setCheckState(
            0, Qt.Checked if selection["include_code_heavy"] else Qt.Unchecked
        )
        self.content_tree.blockSignals(False)
        self.content_tree.setEnabled(selection["preset"] == "custom")
        self._update_content_preview()

    def _content_selection(self) -> dict:
        preset = str(self.content_preset_combo.currentData() or "balanced")
        if preset != "custom":
            return evaluation.normalize_content_selection({"preset": preset})
        sources = [
            source_id for source_id, item in self._content_source_items.items()
            if item.checkState(0) != Qt.Unchecked
        ]
        map_files = [
            filename for filename, item in self._content_map_items.items()
            if item.checkState(0) == Qt.Checked
        ]
        return evaluation.normalize_content_selection({
            "preset": "custom",
            "sources": sources,
            "map_files": map_files,
            "include_code_heavy": self.code_heavy_item.checkState(0) == Qt.Checked,
        })

    def _on_content_preset_changed(self, _index: int | None = None):
        preset = str(self.content_preset_combo.currentData() or "balanced")
        if self._active_content_preset == "custom":
            try:
                self._custom_content_selection = self._content_selection()
            except ValueError:
                pass
        self._active_content_preset = preset
        if preset == "custom":
            selection = self._custom_content_selection or {
                "preset": "custom",
                "sources": list(evaluation.ALL_CONTENT_SOURCES),
                "include_code_heavy": True,
            }
        else:
            selection = evaluation.normalize_content_selection({"preset": preset})
        self._apply_content_selection(selection)

    def _on_content_tree_changed(self):
        if self.content_preset_combo.currentData() == "custom":
            try:
                self._custom_content_selection = self._content_selection()
            except ValueError:
                pass
        self._update_content_preview()

    def _selected_content_count(self, selection: dict | None = None) -> int:
        if not self._content_inventory:
            return 0
        selection = selection or self._content_selection()
        counts = self._content_inventory.get("source_counts") or {}
        code_counts = self._content_inventory.get("code_heavy_source_counts") or {}
        total = sum(int(counts.get(source_id, 0)) for source_id in selection["sources"])
        if "map_events" in selection["sources"] and selection.get("map_files"):
            total -= int(counts.get("map_events", 0))
            total += sum(
                int((self._content_inventory.get("map_files") or {}).get(name, 0))
                for name in selection["map_files"]
            )
        if not selection["include_code_heavy"]:
            excluded_code = sum(
                int(code_counts.get(source_id, 0))
                for source_id in selection["sources"]
            )
            if "map_events" in selection["sources"] and selection.get("map_files"):
                excluded_code -= int(code_counts.get("map_events", 0))
                excluded_code += sum(
                    int((self._content_inventory.get("map_file_code_heavy_counts") or {}).get(name, 0))
                    for name in selection["map_files"]
                )
            total -= excluded_code
        return max(0, total)

    def _update_content_preview(self):
        if not hasattr(self, "content_preview_label"):
            return
        try:
            selection = self._content_selection()
        except ValueError as exc:
            set_status_text(self.content_preview_label, str(exc), "warning")
            return
        available = self._selected_content_count(selection)
        requested = (
            self.custom_target_spin.value()
            if hasattr(self, "custom_target_spin") else evaluation.DEFAULT_SEGMENTS
        )
        if not self._content_inventory:
            set_status_text(
                self.content_preview_label,
                "Choose a valid game folder to see eligible source counts.",
                "neutral",
            )
        elif available < 60:
            set_status_text(
                self.content_preview_label,
                f"Only {available:,} eligible lines match this selection; at least "
                "60 are required. Select more sources.",
                "warning",
            )
        elif requested > available:
            set_status_text(
                self.content_preview_label,
                f"{requested:,} lines requested, but only {available:,} match. "
                f"Preparing will ask to reduce the test to {available:,} lines.",
                "warning",
            )
        else:
            set_status_text(
                self.content_preview_label,
                f"{requested:,} lines will be sampled from {available:,} eligible "
                "lines using a reproducible, game-specific ordering.",
                "success",
            )

    def _add_candidate_row(
        self, endpoint: str = "https://api.openai.com/v1", model: str = "",
        execution: str = "batch", *, key_name: str = "",
    ):
        endpoint = self._endpoint_for_legacy_provider(endpoint)
        endpoint_edit = QLineEdit(endpoint)
        endpoint_edit.setCursorPosition(0)
        endpoint_edit.setPlaceholderText("https://provider.example/v1")
        endpoint_edit.setToolTip(
            "API base URL. Custom URLs use OpenAI-compatible requests; Batch "
            "mode also requires the provider to expose OpenAI's Batch API."
        )
        endpoint_edit.setMinimumWidth(220)
        endpoint_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        preset_btn = QToolButton()
        preset_btn.setText("Presets")
        preset_btn.setToolTip("Choose an official provider API URL")
        preset_btn.setPopupMode(QToolButton.InstantPopup)
        preset_menu = ConfigMenu(preset_btn)
        preset_btn.setMenu(preset_menu)

        endpoint_field = QWidget()
        endpoint_layout = QHBoxLayout(endpoint_field)
        endpoint_layout.setContentsMargins(0, 0, 0, 0)
        endpoint_layout.setSpacing(6)
        endpoint_layout.setAlignment(Qt.AlignVCenter)
        endpoint_layout.addWidget(endpoint_edit, 1)
        endpoint_layout.addWidget(preset_btn)
        endpoint_field.setObjectName("evaluationEndpointField")
        endpoint_field.setStyleSheet(
            "QWidget#evaluationEndpointField { background-color: transparent; }"
        )
        endpoint_field.setMinimumWidth(320)
        endpoint_field.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        key_combo = _EvaluationComboBox()
        key_combo.setMinimumWidth(220)
        key_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        model_combo = _EvaluationModelComboBox()
        # Model discovery is optional for chat-only local servers. Keep the
        # suggestions, but allow an operator to enter a server-specific ID.
        model_combo.setEditable(True)
        model_combo.setMaxVisibleItems(12)
        model_combo.setToolTip(
            "Models available from the selected API URL and saved key"
        )
        model_combo.setMinimumWidth(260)
        model_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        execution_combo = _EvaluationComboBox()
        execution_combo.addItem("Batch", "batch")
        execution_combo.addItem("Live", "live")
        if evaluation.is_openrouter_endpoint(endpoint):
            execution = "live"
        execution_index = execution_combo.findData(execution)
        execution_combo.setCurrentIndex(max(0, execution_index))
        if evaluation.is_openrouter_endpoint(endpoint):
            execution_combo.setToolTip(
                "OpenRouter supports live chat requests but does not expose "
                "the OpenAI Batch API required by Evaluation."
            )
        else:
            execution_combo.setToolTip(
                "Batch is cheaper and asynchronous. Live also supports "
                "chat-only local servers."
            )
        execution_combo.setMinimumWidth(104)

        scan_btn = QPushButton("Scan")
        scan_btn.setToolTip("Fetch models available to this saved API key")
        configure_action_button(scan_btn, variant="secondary")

        remove_btn = QPushButton("Remove")
        configure_action_button(remove_btn, variant="quiet")

        widgets = {
            "endpoint_field": endpoint_field,
            "endpoint": endpoint_edit,
            "preset": preset_btn,
            "key": key_combo,
            "model": model_combo,
            "execution": execution_combo,
            "scan": scan_btn,
            "remove": remove_btn,
            "model_fetch_thread": None,
            "model_fetch_request_id": 0,
            "model_fetch_pending": False,
            "force_model_scan": False,
            "last_model_scan_signature": None,
        }
        scan_timer = QTimer(self)
        scan_timer.setSingleShot(True)
        widgets["scan_timer"] = scan_timer
        self._candidate_widgets.append(widgets)
        for label, preset_endpoint in self.PROVIDER_PRESETS:
            action = preset_menu.addAction(label)
            action.triggered.connect(
                lambda _checked=False, row=widgets, url=preset_endpoint: self._apply_endpoint_preset(
                    row, url
                )
            )
        endpoint_edit.editingFinished.connect(
            lambda row=widgets: self._on_candidate_endpoint_changed(row)
        )
        key_combo.currentIndexChanged.connect(
            lambda _index, row=widgets: self._on_candidate_key_changed(row)
        )
        scan_btn.clicked.connect(
            lambda _checked=False, row=widgets: self._schedule_candidate_model_scan(
                row, delay_ms=0, force=True
            )
        )
        scan_timer.timeout.connect(
            lambda row=widgets: self._fetch_candidate_models(row)
        )
        remove_btn.clicked.connect(lambda _checked=False, row=widgets: self._remove_candidate_row(row))
        self._refresh_model_suggestions(widgets, model)
        self._refresh_candidate_key(widgets, preferred_name=key_name)
        self._reflow_candidate_rows()
        self._schedule_candidate_model_scan(widgets, delay_ms=350)

    def _clear_candidate_rows(self):
        for widgets in list(self._candidate_widgets):
            widgets["scan_timer"].stop()
            for name in (
                "endpoint_field", "key", "model", "execution", "scan", "remove"
            ):
                widget = widgets[name]
                self.candidate_grid.removeWidget(widget)
                widget.deleteLater()
        self._candidate_widgets.clear()

    def _apply_test_template(self, _index: int | None = None):
        values = self.test_size_combo.currentData()
        custom = values is None
        if values is not None:
            target, sample_size, repeated_samples, repetitions = values
            self.custom_target_spin.setValue(int(target))
            self.custom_sample_size_spin.setValue(int(sample_size))
            self.custom_repeated_samples_spin.setValue(int(repeated_samples))
            self.custom_repetitions_spin.setValue(int(repetitions))
        for widget in (
            self.custom_target_spin,
            self.custom_sample_size_spin,
            self.custom_repeated_samples_spin,
            self.custom_repetitions_spin,
        ):
            widget.setEnabled(custom)

    def _restore_benchmark_setup(self, state: dict, manifest: dict):
        """Populate Benchmark setup from a saved run's immutable inputs."""
        candidates = list(state.get("candidates") or [])
        if candidates:
            self._clear_candidate_rows()
            for candidate in candidates:
                self._add_candidate_row(
                    candidate.get("endpoint") or "https://api.openai.com/v1",
                    str(candidate.get("model") or ""),
                    str(candidate.get("execution") or "batch"),
                    key_name=str(candidate.get("key_name") or ""),
                )
                if state.get("credential_binding_required"):
                    # Import archives are data, not authority to select one of
                    # this machine's secrets. Require a deliberate local choice.
                    self._candidate_widgets[-1]["key"].setCurrentIndex(-1)

        requested = int(manifest.get("requested_segments", 0) or 0)
        sample_size = int(
            manifest.get("sample_size") or manifest.get("batch_size")
            or evaluation.DEFAULT_SAMPLE_SIZE
        )
        repetitions = int(
            manifest.get("repetitions") or evaluation.DEFAULT_REPETITIONS
        )
        repeated_samples_value = manifest.get("requested_stability_samples")
        if repeated_samples_value is None:
            repeated_samples = len(manifest.get("stability_request_ids") or [])
        else:
            repeated_samples = int(repeated_samples_value or 0)
        matched = False
        for index in range(self.test_size_combo.count()):
            values = self.test_size_combo.itemData(index)
            if values == (requested, sample_size, repeated_samples, repetitions):
                self.test_size_combo.setCurrentIndex(index)
                matched = True
                break
        if not matched:
            self.test_size_combo.setCurrentIndex(
                self.test_size_combo.count() - 1
            )
            self.custom_target_spin.setValue(max(60, requested))
            self.custom_sample_size_spin.setValue(sample_size)
            self.custom_repeated_samples_spin.setValue(repeated_samples)
            self.custom_repetitions_spin.setValue(repetitions)
            self._apply_test_template()
        saved_selection = evaluation.normalize_content_selection(
            manifest.get("content_selection") or {"preset": "balanced"}
        )
        preset = saved_selection["preset"]
        if preset == "custom":
            self._custom_content_selection = saved_selection
        preset_index = self.content_preset_combo.findData(preset)
        self.content_preset_combo.setCurrentIndex(max(0, preset_index))
        self._active_content_preset = preset
        self._apply_content_selection(saved_selection)
        budget = float(state.get("budget_usd_per_model", 0) or 0)
        if budget > 0:
            self.budget_spin.setValue(budget)

    def _remove_candidate_row(self, widgets: dict):
        if len(self._candidate_widgets) <= 1:
            QMessageBox.information(
                self, "Model required", "Keep at least one model in Benchmark setup."
            )
            return
        if widgets not in self._candidate_widgets:
            return
        self._candidate_widgets.remove(widgets)
        widgets["scan_timer"].stop()
        for name in (
            "endpoint_field", "key", "model", "execution", "scan", "remove"
        ):
            widget = widgets[name]
            self.candidate_grid.removeWidget(widget)
            widget.deleteLater()
        self._reflow_candidate_rows()

    def _reflow_candidate_rows(self):
        for row_index, widgets in enumerate(self._candidate_widgets, start=1):
            for column, name in enumerate((
                "endpoint_field", "key", "model", "execution", "scan", "remove"
            )):
                self.candidate_grid.addWidget(widgets[name], row_index, column)
            widgets["remove"].setEnabled(len(self._candidate_widgets) > 1)
        QTimer.singleShot(0, self._refresh_responsive_geometry)

    def _refresh_model_suggestions(self, widgets: dict, preferred: str = ""):
        combo = widgets["model"]
        current = preferred or combo.currentText().strip()
        provider = self._provider_for_endpoint(widgets["endpoint"].text())
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(self.MODEL_SUGGESTIONS.get(provider, ()))
        current_index = combo.findText(current) if current else -1
        if current and current_index < 0:
            combo.addItem(current)
            current_index = combo.findText(current)
        combo.setCurrentIndex(current_index if current_index >= 0 else 0)
        combo.blockSignals(False)

    @classmethod
    def _endpoint_for_legacy_provider(cls, endpoint: str) -> str:
        presets = dict(cls.PROVIDER_PRESETS)
        lookup = {
            "openai": presets["OpenAI"],
            "gemini": presets["Gemini"],
            "anthropic": presets["Claude (Anthropic)"],
        }
        value = str(endpoint or "").strip()
        return lookup.get(value.lower(), value)

    @staticmethod
    def _provider_for_endpoint(endpoint: str) -> str:
        url = str(endpoint or "").strip().lower()
        if "anthropic.com" in url:
            return "anthropic"
        if "generativelanguage.googleapis.com" in url or "gemini" in url:
            return "gemini"
        return "openai"

    def _apply_endpoint_preset(self, widgets: dict, endpoint: str):
        widgets["endpoint"].setText(endpoint)
        widgets["endpoint"].setCursorPosition(0)
        self._apply_endpoint_execution_support(widgets)
        self._refresh_model_suggestions(widgets)
        self._refresh_candidate_key(widgets, prefer_provider=True)
        self._schedule_candidate_model_scan(widgets)

    def _on_candidate_endpoint_changed(self, widgets: dict):
        self._apply_endpoint_execution_support(widgets)
        self._refresh_model_suggestions(widgets)
        self._refresh_candidate_key(widgets)
        self._schedule_candidate_model_scan(widgets)

    def _on_candidate_key_changed(self, widgets: dict):
        key_name = widgets["key"].currentText().strip()
        endpoint = api_key_vault.get_endpoint(key_name) or ""
        if endpoint:
            widgets["endpoint"].setText(endpoint)
            widgets["endpoint"].setCursorPosition(0)
            self._apply_endpoint_execution_support(widgets)
            self._refresh_model_suggestions(widgets)
        self._schedule_candidate_model_scan(widgets)

    @staticmethod
    def _apply_endpoint_execution_support(widgets: dict):
        execution = widgets["execution"]
        if evaluation.is_openrouter_endpoint(widgets["endpoint"].text()):
            live_index = execution.findData("live")
            execution.setCurrentIndex(max(0, live_index))
            execution.setToolTip(
                "OpenRouter supports live chat requests but does not expose "
                "the OpenAI Batch API required by Evaluation."
            )
            return
        execution.setToolTip(
            "Batch is cheaper and asynchronous. Live also supports chat-only "
            "local servers."
        )

    def _schedule_candidate_model_scan(
        self, widgets: dict, *, delay_ms: int = 450, force: bool = False
    ):
        """Debounce automatic model discovery and invalidate stale responses."""
        if widgets not in self._candidate_widgets:
            return
        widgets["model_fetch_request_id"] += 1
        widgets["force_model_scan"] = bool(
            widgets.get("force_model_scan") or force
        )
        widgets["scan_timer"].start(max(0, int(delay_ms)))

    def _fetch_candidate_models(self, widgets: dict):
        """Fetch the selected provider's models without exposing the saved secret."""
        if widgets not in self._candidate_widgets:
            return
        running = widgets.get("model_fetch_thread")
        if running is not None and running.isRunning():
            widgets["model_fetch_pending"] = True
            return
        interactive = bool(widgets.get("force_model_scan"))
        widgets["force_model_scan"] = False
        key_name = widgets["key"].currentText().strip()
        entry = api_key_vault.get_entry(key_name) if key_name else None
        if entry is None:
            if interactive:
                QMessageBox.warning(
                    self, "No API key", "Select a saved API key before scanning models."
                )
            return
        secret = str(entry.get("secret") or "")
        if not secret and not entry.get("keyless"):
            if interactive:
                QMessageBox.warning(
                    self, "No API key", "The selected saved API key has no secret."
                )
            return

        endpoint = widgets["endpoint"].text().strip()
        if not endpoint:
            if interactive:
                QMessageBox.warning(
                    self, "No API URL", "Enter an API URL or choose a preset first."
                )
            return
        provider = self._provider_for_endpoint(endpoint)
        # Include an in-memory fingerprint so updating a saved secret under the
        # same name also refreshes the model list. The secret is never logged or
        # persisted in evaluation state.
        signature = (provider, endpoint, key_name, hash(secret))
        if (
            not interactive
            and widgets.get("last_model_scan_signature") == signature
        ):
            return
        request_id = widgets["model_fetch_request_id"]
        widgets["last_model_scan_signature"] = signature
        widgets["model_fetch_pending"] = False
        widgets["model_fetch_interactive"] = interactive
        widgets["scan"].setEnabled(False)
        widgets["scan"].setText("…")
        self._append_log(
            f"Scanning {provider} models available to saved key “{key_name}”…"
        )

        worker = ModelFetchThread(
            secret, endpoint, parent=self, provider=provider
        )
        widgets["model_fetch_thread"] = worker
        worker.models_fetched.connect(
            lambda models, row=widgets, rid=request_id: self._apply_candidate_models(
                row, models, rid
            )
        )
        worker.fetch_error.connect(
            lambda error, row=widgets, rid=request_id: self._candidate_model_fetch_error(
                row, error, rid
            )
        )
        worker.finished.connect(
            lambda row=widgets, thread=worker: self._candidate_model_fetch_finished(
                row, thread
            )
        )
        worker.start()

    def _apply_candidate_models(
        self, widgets: dict, models: list[str], request_id: int | None = None
    ):
        if widgets not in self._candidate_widgets or (
            request_id is not None
            and request_id != widgets.get("model_fetch_request_id")
        ):
            return
        combo = widgets["model"]
        current = combo.currentText().strip()
        unique_models = sorted(set(models), key=str.casefold)
        if current and current not in unique_models:
            # Editable model IDs are authoritative for local servers whose
            # /models endpoint omits aliases or returns only a subset.
            unique_models.append(current)
            unique_models.sort(key=str.casefold)
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(unique_models)
        current_index = combo.findText(current) if current else -1
        combo.setCurrentIndex(current_index if current_index >= 0 else 0)
        combo.blockSignals(False)
        combo.setToolTip(
            "Models available from the selected API URL and saved key"
        )
        selected = combo.currentText().strip() or "none"
        self._append_log(
            f"Found {len(unique_models):,} models; selected “{selected}”."
        )

    def _candidate_model_fetch_error(
        self, widgets: dict, error: str, request_id: int | None = None
    ):
        if widgets not in self._candidate_widgets or (
            request_id is not None
            and request_id != widgets.get("model_fetch_request_id")
        ):
            return
        message = error.strip() or "The provider returned no models."
        self._append_log(f"Model scan failed: {message}")
        widgets["model"].setToolTip(f"Automatic model scan failed: {message}")
        if widgets.get("model_fetch_interactive"):
            QMessageBox.warning(
                self, "Model scan",
                f"Could not fetch models from the selected API:\n{message}"
            )

    def _candidate_model_fetch_finished(self, widgets: dict, worker: QThread):
        if widgets.get("model_fetch_thread") is worker:
            widgets["model_fetch_thread"] = None
        worker.deleteLater()
        if widgets not in self._candidate_widgets:
            return
        widgets["scan"].setEnabled(True)
        widgets["scan"].setText("Scan")
        widgets["remove"].setEnabled(len(self._candidate_widgets) > 1)
        if widgets.get("model_fetch_pending"):
            widgets["model_fetch_pending"] = False
            QTimer.singleShot(0, lambda row=widgets: self._fetch_candidate_models(row))

    def _refresh_candidate_key(
        self, widgets: dict, names: list[str] | None = None,
        *, prefer_provider: bool = False, preferred_name: str = "",
    ):
        names = api_key_vault.list_names() if names is None else names
        active = api_key_vault.get_active_name()
        combo = widgets["key"]
        previous = preferred_name or combo.currentText()
        target_endpoint = widgets["endpoint"].text()
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(names)
        previous_matches = previous in names and self._key_matches(
            target_endpoint, previous, api_key_vault.get_endpoint(previous) or ""
        )
        preferred = previous if previous in names and (
            not prefer_provider or previous_matches
        ) else next((
            name for name in names
            if self._key_matches(
                target_endpoint, name, api_key_vault.get_endpoint(name) or ""
            )
        ), "")
        if not preferred and active in names:
            preferred = active
        if preferred:
            combo.setCurrentText(preferred)
        combo.blockSignals(False)

    @classmethod
    def _key_matches(cls, target_endpoint: str, name: str, endpoint: str) -> bool:
        target = str(target_endpoint or "").strip().lower().rstrip("/")
        saved = str(endpoint or "").strip().lower().rstrip("/")
        if target and saved and target == saved:
            return True
        haystack = f"{name} {saved}".lower()
        service = next((
            token for token in (
                "anthropic", "gemini", "googleapis", "deepseek", "mistral", "nvidia"
            )
            if token in target
        ), "openai" if "openai.com" in target else "")
        if service in {"gemini", "googleapis"}:
            return "gemini" in haystack or "googleapis" in haystack
        if service == "anthropic":
            return "anthropic" in haystack or "claude" in haystack
        if service:
            return service in haystack
        return bool(saved and target and saved == target)

    def _refresh_keys(self):
        api_key_vault.ensure_vault()
        names = api_key_vault.list_names()
        for widgets in self._candidate_widgets:
            self._refresh_candidate_key(widgets, names)
            self._schedule_candidate_model_scan(widgets)

    def _candidate_config(self) -> list[dict]:
        candidates = []
        for widgets in self._candidate_widgets:
            endpoint = widgets["endpoint"].text().strip()
            provider = self._provider_for_endpoint(endpoint)
            key_name = widgets["key"].currentText().strip()
            model = widgets["model"].currentText().strip()
            candidates.append({
                "provider": provider,
                "key_name": key_name,
                "endpoint": endpoint,
                "keyless": api_key_vault.is_keyless(key_name),
                "execution": widgets["execution"].currentData(),
                "model": model,
                "label": model,
            })
        return candidates

    def _credentials(self, state: dict) -> dict[str, str]:
        credentials = {}
        for candidate in state.get("candidates", []):
            if candidate.get("status") in {"completed", "failed"}:
                continue
            key_name = str(candidate.get("key_name") or "")
            if state.get("imported_from_run_id"):
                saved_endpoint = str(
                    api_key_vault.get_endpoint(key_name) or ""
                ).strip().rstrip("/")
                candidate_endpoint = str(
                    candidate.get("endpoint") or ""
                ).strip().rstrip("/")
                if not saved_endpoint or saved_endpoint != candidate_endpoint:
                    raise ValueError(
                        f"The selected key for {candidate.get('label') or candidate.get('id')} "
                        "is not saved for that exact API URL."
                    )
            secret = api_key_vault.get_secret(key_name) or ""
            credentials[candidate["id"]] = secret
        return credentials

    def _bind_imported_credentials(self, state: dict) -> dict:
        if not state.get("credential_binding_required"):
            return state
        bindings = {}
        for index, candidate in enumerate(state.get("candidates") or []):
            if candidate.get("status") in {"completed", "failed"}:
                continue
            key_name = ""
            if index < len(self._candidate_widgets):
                key_name = self._candidate_widgets[index]["key"].currentText().strip()
            bindings[candidate["id"]] = {
                "key_name": key_name,
                "endpoint": api_key_vault.get_endpoint(key_name) or "",
                "keyless": api_key_vault.is_keyless(key_name),
            }
        return evaluation.bind_imported_credentials(
            self.current_run_dir, bindings
        )

    def _set_busy(self, busy: bool):
        for button in (
            self.prepare_btn, self.submit_btn, self.refresh_btn,
            self.export_btn, self.copy_review_skill_btn, self.import_btn,
            self.export_evaluation_btn, self.import_evaluation_btn,
        ):
            button.setEnabled(not busy)
        self.cancel_btn.setEnabled(busy and self._worker_cancelable)
        if not busy:
            self._update_actions()
            self._update_history_actions()

    def _run_task(
        self, task, on_done, *, cancelable=False,
        uses_translation_runtime=False, stop_event=None,
    ):
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, "Evaluation busy", "An evaluation operation is still running.")
            return
        self._worker_cancelable = bool(cancelable)
        self._worker_uses_translation_runtime = bool(uses_translation_runtime)
        self._set_busy(True)
        worker = _EvaluationWorker(task, self, stop_event=stop_event)
        self._worker = worker
        worker.log.connect(self._append_log)

        def finished(ok, message, payload):
            if not ok:
                set_status_text(self.status_label, message, "error")
                QMessageBox.warning(self, "Evaluation", message)
            else:
                on_done(payload)

        worker.done.connect(finished)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(self._clear_worker)
        worker.start()

    def _clear_worker(self):
        if self.sender() is self._worker:
            self._worker = None
            self._worker_cancelable = False
            self._worker_uses_translation_runtime = False
            # The result signal arrives while QThread.isRunning() is still
            # true. Restore actions only after the actual thread-finished
            # signal so _update_actions() cannot disable them again.
            self._set_busy(False)

    def cancel_evaluation(self):
        """Request a live evaluation pause after its current SDK call returns."""
        worker = self._worker
        if (
            worker is None
            or not worker.isRunning()
            or not self._worker_cancelable
        ):
            return
        worker.request_stop()
        self.cancel_btn.setEnabled(False)
        set_status_text(
            self.status_label,
            "Stopping the live evaluation after the current request…",
            "info",
        )

    def _start_initial_load(self):
        if (
            self._history_load_worker is not None
            and self._history_load_worker.isRunning()
        ):
            return
        set_status_text(
            self.source_resolution_label,
            "Loading saved evaluations…",
            "info",
        )
        worker = _EvaluationReadWorker(
            lambda: evaluation.list_runs(self.project_root), parent=self
        )
        self._history_load_worker = worker
        worker.loaded.connect(self._on_initial_history_loaded)
        worker.finished.connect(
            lambda: self._clear_read_worker(
                "_history_load_worker", worker
            )
        )
        worker.start()

    def _clear_read_worker(self, attribute: str, worker) -> None:
        if getattr(self, attribute, None) is worker:
            setattr(self, attribute, None)
        worker.deleteLater()

    def _on_initial_history_loaded(self, runs, error: str):
        if error:
            self._append_log(f"Could not load saved evaluations: {error}")
            set_status_text(
                self.source_resolution_label,
                f"Could not load saved evaluations: {error}",
                "warning",
            )
            self._start_initial_inventory(self.source_edit.text().strip())
            return
        self._populate_history(runs or [])
        selected = self._selected_history_run()
        if selected is not None:
            self._open_run(
                selected,
                refresh_history=False,
                defer_inventory=True,
            )
        else:
            self._start_initial_inventory(self.source_edit.text().strip())

    def _start_initial_inventory(self, selected: str):
        self._inventory_load_generation += 1
        generation = self._inventory_load_generation
        if not selected:
            self._pending_inventory_selection = None
            self._refresh_content_inventory(None)
            set_status_text(
                self.source_resolution_label,
                "Select a game folder. Evaluation will find its data/ or "
                "www/data/ files.",
                "neutral",
            )
            return
        if (
            self._inventory_load_worker is not None
            and self._inventory_load_worker.isRunning()
        ):
            # Rapid history changes should not launch an unbounded set of
            # full-corpus scans. Keep only the newest requested source.
            self._pending_inventory_selection = selected
            set_status_text(
                self.source_resolution_label,
                "Finishing the current content scan before loading the newly "
                "selected evaluation…",
                "info",
            )
            return

        self._pending_inventory_selection = None
        set_status_text(
            self.source_resolution_label,
            "Scanning the selected game's available content…",
            "info",
        )

        def load_inventory():
            try:
                data_dir = evaluation.resolve_rpgmaker_data_dir(selected)
            except (FileNotFoundError, ValueError):
                return {"status": "not_found", "selected": selected}
            inventory = evaluation.content_inventory(data_dir)
            inventory["source_dir"] = str(data_dir.resolve())
            return {
                "status": "ready",
                "selected": selected,
                "data_dir": data_dir,
                "inventory": inventory,
            }

        worker = _EvaluationReadWorker(load_inventory, parent=self)
        self._inventory_load_worker = worker
        worker.loaded.connect(
            lambda payload, error, current=generation: (
                self._on_initial_inventory_loaded(current, payload, error)
            )
        )
        worker.finished.connect(
            lambda: self._inventory_worker_finished(worker)
        )
        worker.start()

    def _inventory_worker_finished(self, worker) -> None:
        if self._inventory_load_worker is not worker:
            worker.deleteLater()
            return
        self._inventory_load_worker = None
        worker.deleteLater()
        pending = self._pending_inventory_selection
        self._pending_inventory_selection = None
        if pending is not None:
            self._start_initial_inventory(pending)

    def _on_initial_inventory_loaded(self, generation, payload, error: str):
        if generation != self._inventory_load_generation:
            return
        if error:
            self._content_inventory = {}
            self._populate_content_tree({})
            set_status_text(
                self.source_resolution_label,
                f"Could not scan selectable content: {error}",
                "warning",
            )
            return
        if not payload or payload.get("status") != "ready":
            self._content_inventory = {}
            self._populate_content_tree({})
            set_status_text(
                self.source_resolution_label,
                "No MV/MZ data found yet. Choose the game folder, or its data/ or "
                "www/data/ folder.",
                "warning",
            )
            return

        selected = payload["selected"]
        data_dir = payload["data_dir"]
        inventory = payload["inventory"]
        self._content_inventory = inventory
        self._populate_content_tree(inventory)
        game_root = self._evaluation_game_root(selected)
        if game_root is None:
            set_status_text(
                self.source_resolution_label,
                f"Game data found: {data_dir}\nTranslation context could not be "
                "resolved. Select the game folder itself so Evaluation can use "
                "the same glossary and game skills as normal translation.",
                "warning",
            )
            return
        set_status_text(
            self.source_resolution_label,
            f"Game data found: {data_dir}\nTranslation context: {game_root} "
            f"(glossary: {game_root / 'glossary.txt'})",
            "success",
        )

    def prepare_benchmark(self):
        translation_worker = getattr(
            getattr(self.parent_window, "translation_tab", None),
            "translation_worker",
            None,
        )
        if translation_worker is not None and translation_worker.isRunning():
            QMessageBox.warning(
                self,
                "Translation in progress",
                "Wait for the normal translation job to finish before preparing "
                "an evaluation test set.",
            )
            return
        candidates = self._candidate_config()
        if any(not candidate["model"] for candidate in candidates):
            QMessageBox.warning(
                self, "Evaluation", "Enter a model ID for every comparison row."
            )
            return
        if any(not candidate["endpoint"] for candidate in candidates):
            QMessageBox.warning(
                self, "Evaluation", "Enter an API URL for every comparison row."
            )
            return
        missing = [c["model"] or c["provider"] for c in candidates if not c["key_name"]]
        if missing:
            QMessageBox.warning(
                self, "Evaluation", "Select saved API keys for: " + ", ".join(missing)
            )
            return
        source_text = self.source_edit.text().strip()
        if not source_text:
            QMessageBox.warning(
                self, "Evaluation", "Select an RPG Maker MV/MZ game folder."
            )
            return
        source = Path(source_text)
        game_root = self._evaluation_game_root(source)
        if game_root is None:
            QMessageBox.warning(
                self,
                "Game context required",
                "Select the RPG Maker game folder itself. Evaluation needs its "
                "glossary and game-specific skills to match normal translation.",
            )
            return
        try:
            content_selection = self._content_selection()
        except ValueError as exc:
            QMessageBox.warning(self, "Content selection", str(exc))
            return
        try:
            data_dir = evaluation.resolve_rpgmaker_data_dir(source)
        except (FileNotFoundError, ValueError) as exc:
            QMessageBox.warning(self, "Evaluation", str(exc))
            return
        if self._content_inventory.get("source_dir") != str(data_dir.resolve()):
            self._refresh_content_inventory(data_dir)
        available = self._selected_content_count(content_selection)
        if available < 60:
            QMessageBox.warning(
                self,
                "Not enough selected content",
                f"Only {available:,} eligible Japanese lines match this selection. "
                "Select more content sources; at least 60 lines are required.",
            )
            return
        requested = self.custom_target_spin.value()
        if requested > available:
            answer = QMessageBox.question(
                self,
                "Reduce benchmark size?",
                f"This selection contains {available:,} eligible Japanese lines, "
                f"fewer than the requested {requested:,}. Reduce the benchmark to "
                f"{available:,} lines and continue?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
            self.test_size_combo.setCurrentIndex(self.test_size_combo.count() - 1)
            self.custom_target_spin.setValue(available)
        values = {
            "target_segments": self.custom_target_spin.value(),
            "stability_segments": 0,
            "stability_samples": self.custom_repeated_samples_spin.value(),
            "repetitions": self.custom_repetitions_spin.value(),
            "batch_size": self.custom_sample_size_spin.value(),
            "content_selection": content_selection,
            "budget_usd": self.budget_spin.value(),
            "game_root": game_root,
        }
        set_status_text(self.status_label, "Scanning the game and preparing a fair test set…", "info")

        def task(log):
            log("Scanning eligible Japanese text across the RPG Maker project…")
            return evaluation.prepare_run(
                self.project_root, source, candidates, **values
            )

        def done(payload):
            run_dir, state = payload
            self.current_run_dir = Path(run_dir)
            self._last_review_path = None
            self._display_state(state)
            summary = state.get("corpus_summary") or {}
            set_status_text(
                self.status_label,
                f"Selected {summary.get('selected_segments', 0):,} of "
                f"{summary.get('eligible_segments', 0):,} eligible lines from "
                f"{summary.get('review_samples', 0):,} samples across "
                f"{summary.get('selected_scenes', 0):,} scenes and "
                f"{summary.get('selected_files', 0):,} files. Review the estimates, "
                "then submit the model batches together.",
                "success",
            )
            self._append_log(
                f"Selection: {summary.get('selected_segments', 0):,} lines from "
                f"{summary.get('selected_files', 0):,} of "
                f"{summary.get('eligible_files', 0):,} eligible files in "
                f"{summary.get('selected_scenes', 0):,} scenes and "
                f"{summary.get('review_samples', 0):,} review samples."
            )
            self._append_log(f"Manifest: {self.current_run_dir / 'manifest.json'}")
            self._refresh_history(self.current_run_dir)

        self._run_task(task, done, uses_translation_runtime=True)

    def submit_batches(self):
        if not self.current_run_dir:
            return
        try:
            state, manifest = evaluation.refresh_run_estimates(
                self.current_run_dir
            )
        except Exception as exc:
            QMessageBox.warning(self, "Evaluation budget", str(exc))
            return
        if state["status"] not in {"prepared", "partially_submitted"}:
            return
        lines = [
            f"{candidate['label']} ({candidate.get('execution', 'batch').title()}): "
            f"${candidate['estimate']['cost_usd']:.2f} likely upper bound; "
            f"${candidate['estimate']['maximum_cost_usd']:.2f} theoretical ceiling"
            for candidate in state["candidates"]
            if not candidate.get("batch_id")
            and candidate.get("status") in {"prepared", "running_live"}
        ]
        has_resumable_live = any(
            candidate.get("execution", "batch") == "live"
            and candidate.get("status") in {"prepared", "running_live"}
            for candidate in state["candidates"]
        )
        answer = QMessageBox.question(
            self,
            "Run evaluation?",
            "This sends paid requests. Batch rows create asynchronous provider "
            "jobs; Live rows run immediately and require the app to remain open. The same "
            f"{len(manifest['executions'])} requests are used for every model.\n\n"
            + "\n".join(lines)
            + "\n\nLive theoretical ceilings include all automatic retry attempts."
            + f"\n\nHard budget: ${state['budget_usd_per_model']:.2f} per model.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            state = self._bind_imported_credentials(state)
            credentials = self._credentials(state)
        except ValueError as exc:
            QMessageBox.warning(self, "Evaluation credentials", str(exc))
            return
        set_status_text(self.status_label, "Starting evaluation requests…", "info")

        stop_event = threading.Event()

        def task(log):
            return evaluation.submit_run(
                self.current_run_dir,
                credentials,
                log,
                should_stop=stop_event.is_set,
            )

        def done(updated):
            relocated = evaluation.locate_run(
                self.project_root, str(updated.get("run_id") or "")
            )
            if relocated is not None:
                self.current_run_dir = relocated
            self._display_state(updated)
            self._refresh_history(self.current_run_dir)
            submission_errors = updated.get("submission_errors") or []
            if submission_errors:
                details = "\n".join(
                    f"{item.get('label') or item.get('candidate_id')}: "
                    f"{item.get('error') or 'unknown error'}"
                    for item in submission_errors
                )
                set_status_text(
                    self.status_label,
                    "Some models could not start. Submitted batches will still "
                    "be checked; press Run evaluation to retry failed models.",
                    "error",
                )
                QMessageBox.warning(
                    self,
                    "Evaluation model errors",
                    "Some models could not start:\n\n" + details,
                )
            elif updated["status"] == "prepared" and stop_event.is_set():
                set_status_text(
                    self.status_label,
                    "Evaluation stopped before any requests were sent.",
                    "info",
                )
            elif updated["status"] == "completed":
                self._poll_timer.stop()
                set_status_text(
                    self.status_label,
                    "All live results were processed. Export the blinded review CSV to judge translation quality.",
                    "success",
                )
            elif updated["status"] == "failed":
                self._poll_timer.stop()
                set_status_text(
                    self.status_label,
                    "Evaluation failed because a model returned no usable requests. Check the model row and log.",
                    "error",
                )
            else:
                live_paused = any(
                    candidate.get("status") == "running_live"
                    for candidate in updated.get("candidates") or []
                )
                if live_paused:
                    set_status_text(
                        self.status_label,
                        "Live evaluation paused. Press Run evaluation to resume "
                        "from its saved request checkpoint.",
                        "info",
                    )
                else:
                    set_status_text(
                        self.status_label,
                        "Batch jobs were submitted. This page checks them every "
                        "60 seconds while open.",
                        "success",
                    )

        self._run_task(
            task,
            done,
            cancelable=has_resumable_live,
            stop_event=stop_event,
        )

    def refresh_results(self):
        if not self.current_run_dir or (
            self._worker is not None and self._worker.isRunning()
        ):
            return
        state, _manifest = evaluation.load_run(self.current_run_dir)
        if state["status"] not in {
            "submitted", "partially_submitted", "imported_paused"
        }:
            return
        if state["status"] == "imported_paused":
            answer = QMessageBox.question(
                self,
                "Reconnect imported evaluation?",
                "This will contact the API URLs stored in the imported archive "
                "using the local keys you explicitly select for those exact "
                "URLs. Continue?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        try:
            state = self._bind_imported_credentials(state)
            credentials = self._credentials(state)
            if state["status"] == "imported_paused":
                state = evaluation.resume_imported_run(self.current_run_dir)
        except ValueError as exc:
            QMessageBox.warning(self, "Evaluation credentials", str(exc))
            return

        def task(log):
            return evaluation.refresh_run(self.current_run_dir, credentials, log)

        def done(updated):
            relocated = evaluation.locate_run(
                self.project_root, str(updated.get("run_id") or "")
            )
            if relocated is not None:
                self.current_run_dir = relocated
            self._display_state(updated)
            self._refresh_history(self.current_run_dir)
            if updated["status"] == "completed":
                self._poll_timer.stop()
                set_status_text(
                    self.status_label,
                    "All results downloaded and validated. Export the blinded review CSV to judge translation quality.",
                    "success",
                )
            elif updated["status"] == "failed":
                self._poll_timer.stop()
                set_status_text(
                    self.status_label,
                    "Evaluation failed because a model returned no usable requests. Check the model row and log.",
                    "error",
                )
            else:
                set_status_text(self.status_label, "Provider batches are still processing.", "info")

        self._run_task(task, done)

    def _choose_review_candidates(self) -> list[str] | None:
        """Show the candidate selector used for a new blinded export."""
        if not self.current_run_dir:
            return None
        choices = evaluation.blind_review_candidates(self.current_run_dir)
        dialog = QDialog(self)
        dialog.setWindowTitle("Choose blind review models")
        dialog.setMinimumWidth(560)
        layout = QVBoxLayout(dialog)
        explanation = QLabel(
            "Select at least two models. Only the selected translations will "
            "appear in the blinded CSV; failed models with no usable output "
            "cannot be selected."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        tree = QTreeWidget()
        tree.setHeaderLabels(("Model", "Result", "Valid lines"))
        tree.setRootIsDecorated(False)
        tree.setAlternatingRowColors(True)
        default_ids = {
            choice["id"] for choice in choices
            if choice.get("selected_by_default")
        }
        available_ids = {
            choice["id"] for choice in choices if choice.get("available")
        }
        if len(default_ids) < 2:
            default_ids = available_ids
        for choice in choices:
            available = bool(choice.get("available"))
            status = str(choice.get("status") or "unknown").replace("_", " ").title()
            if not available:
                status = "Unavailable"
            item = QTreeWidgetItem([
                str(choice.get("label") or choice["id"]),
                status,
                f"{int(choice.get('valid_primary', 0) or 0):,}",
            ])
            item.setData(0, Qt.UserRole, choice["id"])
            if available:
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(
                    0, Qt.Checked if choice["id"] in default_ids else Qt.Unchecked
                )
            else:
                item.setDisabled(True)
                reason = str(choice.get("reason") or "No usable result")
                item.setToolTip(0, reason)
                item.setToolTip(1, reason)
            tree.addTopLevelItem(item)
        tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        layout.addWidget(tree)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)

        def accept_selection():
            selected_count = sum(
                tree.topLevelItem(index).checkState(0) == Qt.Checked
                for index in range(tree.topLevelItemCount())
            )
            if selected_count < 2:
                QMessageBox.warning(
                    dialog, "Blind review models",
                    "Select at least two models with usable translations.",
                )
                return
            dialog.accept()

        buttons.accepted.connect(accept_selection)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec_() != QDialog.Accepted:
            return None
        return [
            str(tree.topLevelItem(index).data(0, Qt.UserRole))
            for index in range(tree.topLevelItemCount())
            if tree.topLevelItem(index).checkState(0) == Qt.Checked
        ]

    def export_review(self):
        if not self.current_run_dir:
            return
        try:
            candidate_ids = self._choose_review_candidates()
            if candidate_ids is None:
                return
            coverage = evaluation.blind_review_coverage(
                self.current_run_dir, candidate_ids
            )
        except Exception as exc:
            QMessageBox.warning(self, "Blind review", str(exc))
            return
        eligible = coverage["eligible_segments"]
        total = coverage["total_segments"]
        excluded = coverage["excluded_segments"]
        eligible_samples = coverage["eligible_samples"]
        total_samples = coverage["total_samples"]
        excluded_samples = coverage["excluded_samples"]
        candidate_count = len(coverage["candidate_ids"])
        coverage_message = (
            f"Blind review coverage for {candidate_count:,} selected models: "
            f"{eligible_samples:,}/{total_samples:,} "
            f"whole samples containing {eligible:,}/{total:,} lines will be "
            f"exported. {excluded_samples:,} samples are omitted because at "
            "least one selected model has an invalid or missing line in them."
        )
        self._append_log(coverage_message)
        set_status_text(self.status_label, coverage_message, "info")
        default = str(self.current_run_dir / "blind_review.csv")
        selected, _ = QFileDialog.getSaveFileName(
            self, "Export blinded review", default, "CSV files (*.csv)"
        )
        if not selected:
            return
        try:
            path = evaluation.export_blind_review(
                self.current_run_dir, selected, candidate_ids
            )
            self._last_review_path = Path(path)
            self._append_log(f"Blinded review exported: {path}")
            set_status_text(
                self.status_label,
                f"Blind review exported for {candidate_count:,} models with "
                f"{eligible_samples:,}/{total_samples:,} "
                f"complete samples ({eligible:,}/{total:,} lines). "
                f"{excluded_samples:,} samples were omitted because at least "
                "one selected model had an invalid or missing line. "
                "Fill in the ranking column, then import the reviewed CSV.",
                "success",
            )
            self._update_actions()
            QMessageBox.information(
                self, "Blind review",
                f"Exported {candidate_count:,} selected models across "
                f"{eligible_samples:,} of {total_samples:,} samples "
                f"containing {eligible:,} lines; {excluded_samples:,} samples "
                f"and {excluded:,} lines were excluded because at least one selected model "
                "lacked a valid translation. "
                f"Rank every candidate in the ranking column, for example "
                f"{'>'.join(evaluation._blind_label(index) for index in range(candidate_count))}. "
                f"Use = for ties, such as "
                f"{'='.join(evaluation._blind_label(index) for index in range(candidate_count))}. "
                "Labels are "
                "randomized independently for every sample.",
            )
        except Exception as exc:
            QMessageBox.warning(self, "Blind review", str(exc))

    def _review_csv_path(self) -> Path | None:
        if self._last_review_path and self._last_review_path.is_file():
            return self._last_review_path.resolve()
        if self.current_run_dir:
            canonical = self.current_run_dir / "blind_review.csv"
            if canonical.is_file():
                return canonical.resolve()
        return None

    def copy_review_skill(self):
        review_path = self._review_csv_path()
        if review_path is None:
            QMessageBox.information(
                self,
                "Export required",
                "Export the blind review CSV before copying its AI review skill.",
            )
            return
        try:
            prompt = load_clipboard_skill("evaluation_csv_review.md")
            system_path, glossary_path, sfx_path = evaluation.export_blind_review_context(
                self.current_run_dir, review_path.parent
            )
            replacements = {
                "{{BLIND_REVIEW_CSV}}": str(review_path),
                "{{REVIEW_SYSTEM_PROMPT}}": str(system_path),
                "{{REVIEW_GLOSSARY}}": str(glossary_path),
                "{{REVIEW_SFX_REFERENCE}}": str(sfx_path),
            }
            missing = [token for token in replacements if token not in prompt]
            if missing:
                raise ValueError(
                    "Evaluation review skill is missing placeholders: "
                    + ", ".join(missing)
                )
            for token, value in replacements.items():
                prompt = prompt.replace(token, value)
            QApplication.clipboard().setText(prompt)
            self._append_log(f"AI review skill copied for: {review_path}")
            QMessageBox.warning(
                self,
                "AI review skill copied",
                "Paste the copied skill into your AI helper. AI translation "
                "judgments can be biased and may share preferences or failure "
                "modes with the models being evaluated. Treat the result as a "
                "second opinion, not an objective replacement for human review.",
            )
        except Exception as exc:
            QMessageBox.warning(self, "Copy review skill", str(exc))

    def import_review(self):
        if not self.current_run_dir:
            return
        if not (self.current_run_dir / "blind_key.json").is_file():
            QMessageBox.information(
                self,
                "Export required",
                "Export the blind review first. The export creates the hidden "
                "mapping needed to score the reviewed CSV.",
            )
            return
        initial_path = str(
            getattr(self, "_last_review_path", None) or self.current_run_dir
        )
        selected, _ = QFileDialog.getOpenFileName(
            self, "Import reviewed CSV", initial_path, "CSV files (*.csv)"
        )
        if not selected:
            return
        try:
            review = evaluation.import_blind_review(self.current_run_dir, selected)
            state, _manifest = evaluation.load_run(self.current_run_dir)
            self._display_state(state)
            self._refresh_history(self.current_run_dir)
            self._append_log(
                f"Imported {review['reviewed']} sample rankings covering "
                f"{review.get('reviewed_lines', review['reviewed'])} lines "
                f"({review['ties']} full "
                f"ties, {review['partial_ties']} partial ties)."
            )
        except Exception as exc:
            QMessageBox.warning(self, "Blind review", str(exc))

    def _on_results_tab_changed(self, index: int):
        if hasattr(self, "log"):
            self.log.setVisible(index != self._comparison_tab_index)
        if index == self._comparison_tab_index:
            self._start_comparison_load()

    def _invalidate_comparison(self):
        self._comparison_generation += 1
        self._comparison_data = None
        self._comparison_run_dir = None
        self._comparison_filtered_samples = []
        self._comparison_visible_candidates = []
        if not hasattr(self, "comparison_sample_list"):
            return
        self.comparison_sample_list.clear()
        self.comparison_table.clear()
        self.comparison_table.setRowCount(0)
        self.comparison_table.setColumnCount(0)
        self.comparison_splitter.hide()
        self.comparison_counter.setText("—")
        self.comparison_sample_heading.setText("Select a sample")
        self.comparison_sample_meta.clear()
        self.comparison_review_status.clear()
        self.comparison_review_notes.clear()
        for value in self.comparison_review_values.values():
            value.setText("—")
        self._set_comparison_review_metrics_visible(False)
        self.comparison_status.setText(
            "Choose a completed evaluation to compare model outputs."
        )

    def _start_comparison_load(self):
        if (
            self.results_tabs.currentIndex() != self._comparison_tab_index
            or not self.current_run_dir
            or not self.results_tabs.isTabEnabled(self._comparison_tab_index)
        ):
            return
        run_dir = self.current_run_dir.resolve()
        if self._comparison_data is not None and self._comparison_run_dir == run_dir:
            return
        running = self._comparison_load_worker
        if (
            running is not None
            and running.isRunning()
            and getattr(running, "comparison_run_dir", None) == run_dir
        ):
            return
        self._comparison_generation += 1
        generation = self._comparison_generation
        self.comparison_splitter.hide()
        self.comparison_status.setText("Loading source and model outputs…")
        worker = _EvaluationReadWorker(
            lambda path=run_dir: evaluation.load_comparison_data(path), parent=self
        )
        worker.comparison_run_dir = run_dir
        self._comparison_load_worker = worker
        worker.loaded.connect(
            lambda payload, error, active=worker, expected=generation, path=run_dir:
            self._finish_comparison_load(active, expected, path, payload, error)
        )
        worker.finished.connect(
            lambda active=worker: self._comparison_worker_finished(active)
        )
        worker.start()

    def _comparison_worker_finished(self, worker: _EvaluationReadWorker):
        if self._comparison_load_worker is worker:
            self._comparison_load_worker = None
        worker.deleteLater()

    def _finish_comparison_load(
        self,
        worker: _EvaluationReadWorker,
        generation: int,
        run_dir: Path,
        payload: object,
        error: str,
    ):
        if (
            generation != self._comparison_generation
            or self.current_run_dir is None
            or self.current_run_dir.resolve() != run_dir
        ):
            return
        if error or not isinstance(payload, dict):
            self.comparison_status.setText(
                "Could not load output comparison: "
                + (error or "comparison data is invalid")
            )
            self.comparison_splitter.hide()
            return
        self._comparison_data = payload
        self._comparison_run_dir = run_dir
        candidate_ids = [
            str(candidate["id"])
            for candidate in payload.get("candidates") or []
        ]
        self._comparison_visible_candidates = candidate_ids
        self._rebuild_comparison_model_menu()
        self.comparison_reveal_models.blockSignals(True)
        self.comparison_reveal_models.setChecked(
            bool(payload.get("has_imported_review"))
        )
        self.comparison_reveal_models.blockSignals(False)
        samples = payload.get("samples") or []
        if not samples:
            self.comparison_status.setText(
                "This evaluation has no source samples to compare."
            )
            self.comparison_splitter.hide()
            return
        self.comparison_splitter.show()
        self._refresh_comparison_sample_list()

    def _rebuild_comparison_model_menu(self):
        self.comparison_models_menu.clear()
        candidates = (self._comparison_data or {}).get("candidates") or []
        visible = set(self._comparison_visible_candidates)
        for candidate in candidates:
            candidate_id = str(candidate["id"])
            action = QAction(str(candidate.get("label") or candidate_id), self)
            action.setData(candidate_id)
            action.setCheckable(True)
            action.setChecked(candidate_id in visible)
            action.toggled.connect(
                lambda checked, value=candidate_id:
                self._toggle_comparison_candidate(value, checked)
            )
            self.comparison_models_menu.addAction(action)
        self.comparison_models_btn.setText(
            f"Models ({len(self._comparison_visible_candidates)})"
        )
        self._resize_comparison_controls()

    def _toggle_comparison_candidate(self, candidate_id: str, checked: bool):
        visible = list(self._comparison_visible_candidates)
        if checked and candidate_id not in visible:
            ordered = [
                str(candidate["id"])
                for candidate in (self._comparison_data or {}).get("candidates") or []
            ]
            visible = [value for value in ordered if value in {*visible, candidate_id}]
        elif not checked and candidate_id in visible:
            if len(visible) == 1:
                for action in self.comparison_models_menu.actions():
                    if str(action.data() or "") == candidate_id:
                        action.blockSignals(True)
                        action.setChecked(True)
                        action.blockSignals(False)
                        break
                return
            visible.remove(candidate_id)
        self._comparison_visible_candidates = visible
        self.comparison_models_btn.setText(f"Models ({len(visible)})")
        self._resize_comparison_controls()
        self._display_comparison_selection(self.comparison_sample_list.currentRow())

    def _comparison_candidate(self, candidate_id: str) -> dict:
        for candidate in (self._comparison_data or {}).get("candidates") or []:
            if str(candidate.get("id")) == candidate_id:
                return candidate
        return {"id": candidate_id, "label": candidate_id}

    def _comparison_candidate_label(self, candidate_id: str) -> str:
        candidate = self._comparison_candidate(candidate_id)
        return str(candidate.get("label") or candidate.get("model") or candidate_id)

    def _comparison_candidate_color(self, candidate_id: str) -> str:
        ordered = [
            str(candidate["id"])
            for candidate in (self._comparison_data or {}).get("candidates") or []
        ]
        try:
            index = ordered.index(candidate_id)
        except ValueError:
            index = 0
        return self.COMPARISON_MODEL_COLORS[
            index % len(self.COMPARISON_MODEL_COLORS)
        ]

    def _comparison_display_name(self, candidate_id: str, sample: dict) -> str:
        if self.comparison_reveal_models.isChecked():
            return self._comparison_candidate_label(candidate_id)
        blind_label = (sample.get("blind_labels") or {}).get(candidate_id)
        if blind_label:
            return f"Candidate {blind_label}"
        ordered = [
            str(candidate["id"])
            for candidate in (self._comparison_data or {}).get("candidates") or []
        ]
        try:
            index = ordered.index(candidate_id)
        except ValueError:
            return "Candidate"
        return f"Candidate {evaluation._blind_label(index)}"

    @staticmethod
    def _comparison_blind_label_order(label: str) -> int:
        value = 0
        normalized = str(label or "").strip().upper()
        if not normalized or any(
            not "A" <= character <= "Z" for character in normalized
        ):
            return 2_147_483_647
        for character in normalized:
            value = value * 26 + (ord(character) - ord("A") + 1)
        return value

    def _comparison_ordered_candidate_ids(self, sample: dict) -> list[str]:
        visible = list(self._comparison_visible_candidates)
        original_order = {
            candidate_id: index for index, candidate_id in enumerate(visible)
        }
        blind_labels = sample.get("blind_labels") or {}

        def order(candidate_id: str):
            label = blind_labels.get(candidate_id)
            if label:
                return (0, self._comparison_blind_label_order(label))
            return (1, original_order[candidate_id])

        return sorted(visible, key=order)

    def _comparison_table_header(self, candidate_id: str, sample: dict) -> str:
        blind_label = str(
            (sample.get("blind_labels") or {}).get(candidate_id) or ""
        )
        if self.comparison_reveal_models.isChecked():
            model = self._comparison_candidate_label(candidate_id)
            return f"{blind_label} · {model}" if blind_label else model
        if blind_label:
            return f"Candidate {blind_label}"
        return self._comparison_display_name(candidate_id, sample)

    def _format_comparison_tiers(self, tiers: list, sample: dict) -> str:
        return " > ".join(
            " = ".join(
                self._comparison_display_name(str(candidate_id), sample)
                for candidate_id in tier
            )
            for tier in tiers
        )

    def _comparison_tiers_html(self, tiers: list, sample: dict) -> str:
        rendered_tiers = []
        for tier_index, tier in enumerate(tiers):
            names = []
            for candidate_id in tier:
                candidate_id = str(candidate_id)
                name = html.escape(
                    self._comparison_display_name(candidate_id, sample)
                )
                weight = "700" if tier_index == 0 else "500"
                names.append(
                    f'<span style="color:{self._comparison_candidate_color(candidate_id)};'
                    f'font-weight:{weight};">{name}</span>'
                )
            rendered_tiers.append(
                f' <span style="color:{COLORS.text_muted};">=</span> '.join(names)
            )
        return (
            f' <span style="color:{COLORS.text_muted};">›</span> '
        ).join(rendered_tiers)

    def _set_comparison_review_metrics_visible(self, visible: bool):
        for metric in ("overall", *evaluation.REVIEW_QUALITY_METRICS):
            self.comparison_review_metric_labels[metric].setVisible(visible)
            self.comparison_review_values[metric].setVisible(visible)

    @staticmethod
    def _comparison_scene_label(scene_id: str) -> str:
        scene = str(scene_id or "").strip()
        match = re.match(
            r"^(Map\d+)(?:\.json)?:event-(\d+):page-(\d+):call-(\d+)$",
            scene,
            flags=re.IGNORECASE,
        )
        if match:
            map_name, event, page, call = match.groups()
            return f"{map_name} · Event {event} / Page {page} / Call {call}"
        return scene or "Unknown scene"

    @staticmethod
    def _comparison_stratum_label(stratum: str) -> str:
        return str(stratum or "Uncategorized").replace("_", " ").title()

    def _comparison_sample_matches(self, sample: dict) -> bool:
        selected_filter = str(self.comparison_filter.currentData() or "all")
        review = sample.get("review")
        if selected_filter == "reviewed" and not review:
            return False
        if selected_filter == "ties" and not (
            review and any(len(tier) > 1 for tier in review.get("overall") or [])
        ):
            return False
        if selected_filter == "notes" and not (
            review and str(review.get("notes") or "").strip()
        ):
            return False
        if selected_filter == "problems" and not sample.get("has_problems"):
            return False
        query = self.comparison_search.text().strip().casefold()
        if not query:
            return True
        values = [
            sample.get("id", ""), sample.get("scene_id", ""),
            sample.get("stratum", ""), *(sample.get("sources") or []),
            str((review or {}).get("notes") or ""),
        ]
        for line in sample.get("lines") or []:
            values.extend(
                output.get("translation", "")
                for output in (line.get("outputs") or {}).values()
            )
        return query in "\n".join(str(value) for value in values).casefold()

    def _refresh_comparison_sample_list(self, *_args):
        if self._comparison_data is None:
            return
        current_item = self.comparison_sample_list.currentItem()
        current_id = current_item.data(Qt.UserRole) if current_item else None
        all_samples = self._comparison_data.get("samples") or []
        sample_numbers = {
            str(sample.get("id")): index
            for index, sample in enumerate(all_samples, start=1)
        }
        samples = [
            sample for sample in all_samples
            if self._comparison_sample_matches(sample)
        ]
        self._comparison_filtered_samples = samples
        self.comparison_sample_list.blockSignals(True)
        self.comparison_sample_list.clear()
        selected_row = -1
        for index, sample in enumerate(samples):
            review = sample.get("review")
            if sample.get("has_problems"):
                status = "Needs attention"
                status_color = COLORS.danger
                marker = "⚠"
            elif review:
                tied = any(
                    len(tier) > 1 for tier in review.get("overall") or []
                )
                status = "Reviewed · Tie" if tied else "Reviewed"
                status_color = COLORS.warning if tied else COLORS.success
                marker = "●"
            elif sample.get("blind_labels"):
                status = "Awaiting review"
                status_color = COLORS.accent_text
                marker = "○"
            else:
                status = "Not reviewed"
                status_color = COLORS.text_muted
                marker = "○"
            sample_number = sample_numbers.get(str(sample.get("id")), index + 1)
            scene = self._comparison_scene_label(sample.get("scene_id", ""))
            stratum = self._comparison_stratum_label(sample.get("stratum", ""))
            line_count = len(sample.get("lines") or [])
            item = QListWidgetItem(
                f"{marker}  {sample_number}. {scene}\n"
                f"    {line_count:,} lines · {stratum} · {status}"
            )
            item.setData(Qt.UserRole, sample["id"])
            item.setForeground(QBrush(QColor(status_color)))
            tooltip = str(sample.get("scene_id") or scene)
            if review:
                tooltip += "\nOverall: " + self._format_comparison_tiers(
                    review.get("overall") or [], sample
                )
            item.setToolTip(tooltip)
            self.comparison_sample_list.addItem(item)
            if sample["id"] == current_id:
                selected_row = index
        self.comparison_sample_list.blockSignals(False)
        total = len(all_samples)
        problem_count = sum(bool(sample.get("has_problems")) for sample in samples)
        status_text = f"{len(samples):,} of {total:,} samples shown"
        if problem_count:
            status_text += f" · {problem_count:,} need attention"
        self.comparison_status.setText(status_text)
        if samples:
            self.comparison_sample_list.setCurrentRow(
                selected_row if selected_row >= 0 else 0
            )
        else:
            self._display_comparison_selection(-1)

    def _refresh_comparison_presenter(self, *_args):
        self._refresh_comparison_sample_list()

    def _move_comparison_selection(self, offset: int):
        count = self.comparison_sample_list.count()
        if not count:
            return
        row = self.comparison_sample_list.currentRow()
        self.comparison_sample_list.setCurrentRow(
            min(count - 1, max(0, row + offset))
        )

    def _display_comparison_selection(self, row: int):
        samples = self._comparison_filtered_samples
        if row < 0 or row >= len(samples):
            self.comparison_sample_heading.setText("No matching sample")
            self.comparison_sample_meta.clear()
            self.comparison_review_status.clear()
            self.comparison_review_notes.setText(
                "Adjust the search or filter to show samples."
            )
            for value in self.comparison_review_values.values():
                value.setText("—")
            self._set_comparison_review_metrics_visible(False)
            self.comparison_table.clear()
            self.comparison_table.setRowCount(0)
            self.comparison_table.setColumnCount(0)
            self.comparison_counter.setText(f"0 / {len(samples):,}")
            self.comparison_previous_btn.setEnabled(False)
            self.comparison_next_btn.setEnabled(False)
            return
        sample = samples[row]
        self.comparison_counter.setText(f"{row + 1:,} / {len(samples):,}")
        self.comparison_previous_btn.setEnabled(row > 0)
        self.comparison_next_btn.setEnabled(row + 1 < len(samples))
        self.comparison_sample_heading.setText(
            self._comparison_scene_label(sample.get("scene_id", ""))
        )
        self.comparison_sample_meta.setText(
            f"{len(sample.get('lines') or []):,} source lines  ·  "
            f"{self._comparison_stratum_label(sample.get('stratum', ''))}  ·  "
            f"Sample ID: {sample.get('id') or '—'}"
        )
        review = sample.get("review")
        if review:
            self._set_comparison_review_metrics_visible(True)
            overall = review.get("overall") or []
            tied = bool(overall and len(overall[0]) > 1)
            self.comparison_review_status.setText(
                "●  Reviewed · Tie" if tied else "●  Reviewed"
            )
            self.comparison_review_status.setStyleSheet(
                f"color: {COLORS.warning if tied else COLORS.success}; "
                "font-weight: 600;"
            )
            self.comparison_review_values["overall"].setText(
                self._comparison_tiers_html(overall, sample) or "—"
            )
            for metric in evaluation.REVIEW_QUALITY_METRICS:
                tiers = (review.get("metrics") or {}).get(metric) or []
                self.comparison_review_values[metric].setText(
                    self._comparison_tiers_html(tiers, sample) or "—"
                )
            notes = str(review.get("notes") or "").strip()
            self.comparison_review_notes.setText(
                f"Reviewer note: {notes}" if notes else "No reviewer note for this sample."
            )
        elif sample.get("blind_labels"):
            self._set_comparison_review_metrics_visible(False)
            self.comparison_review_status.setText("○  Awaiting review")
            self.comparison_review_status.setStyleSheet(
                f"color: {COLORS.accent_text}; font-weight: 600;"
            )
            for value in self.comparison_review_values.values():
                value.setText("—")
            self.comparison_review_notes.setText(
                "Candidate names stay hidden until a reviewed CSV is imported."
            )
        else:
            self._set_comparison_review_metrics_visible(False)
            self.comparison_review_status.setText("○  Not reviewed")
            self.comparison_review_status.setStyleSheet(
                f"color: {COLORS.text_muted}; font-weight: 600;"
            )
            for value in self.comparison_review_values.values():
                value.setText("—")
            self.comparison_review_notes.setText(
                "This sample was not included in the exported blind review."
            )

        candidate_ids = self._comparison_ordered_candidate_ids(sample)
        self.comparison_table.clear()
        self.comparison_table.setColumnCount(1 + len(candidate_ids))
        source_header = QTableWidgetItem("Japanese source")
        source_header.setForeground(QBrush(QColor(COLORS.text_primary)))
        self.comparison_table.setHorizontalHeaderItem(0, source_header)
        overall_tiers = (review or {}).get("overall") or []
        first_place = set(overall_tiers[0] if overall_tiers else [])
        for column, candidate_id in enumerate(candidate_ids, start=1):
            display_name = self._comparison_table_header(candidate_id, sample)
            header_text = f"★  {display_name}" if candidate_id in first_place else display_name
            header_item = QTableWidgetItem(header_text)
            header_item.setForeground(
                QBrush(QColor(self._comparison_candidate_color(candidate_id)))
            )
            if candidate_id in first_place:
                header_item.setToolTip("Ranked first overall for this sample")
            self.comparison_table.setHorizontalHeaderItem(column, header_item)
        lines = sample.get("lines") or []
        self.comparison_table.setRowCount(len(lines))
        self.comparison_table.setVerticalHeaderLabels([
            str(index) for index in range(1, len(lines) + 1)
        ])
        for line_index, line in enumerate(lines):
            source_item = QTableWidgetItem(str(line.get("source") or ""))
            source_item.setToolTip(str(line.get("segment_id") or ""))
            source_item.setForeground(QBrush(QColor(COLORS.text_primary)))
            source_item.setBackground(QBrush(QColor(COLORS.surface_1)))
            self.comparison_table.setItem(line_index, 0, source_item)
            for column, candidate_id in enumerate(candidate_ids, start=1):
                output = (line.get("outputs") or {}).get(candidate_id) or {}
                text = str(output.get("translation") or "")
                if output.get("missing"):
                    display = "⚠ Missing output"
                elif not output.get("valid", True):
                    display = "⚠ Invalid output\n" + text
                else:
                    display = text
                item = QTableWidgetItem(display)
                details = [
                    *[str(value) for value in output.get("issues") or []],
                    *[str(value) for value in output.get("warnings") or []],
                ]
                if details:
                    item.setToolTip("\n".join(details))
                if output.get("missing") or not output.get("valid", True):
                    item.setForeground(QBrush(QColor(COLORS.danger)))
                    item.setBackground(QBrush(QColor(COLORS.danger_surface)))
                elif output.get("warnings"):
                    item.setForeground(QBrush(QColor(COLORS.warning)))
                self.comparison_table.setItem(line_index, column, item)
        header = self.comparison_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        self.comparison_table.resizeRowsToContents()
        self._resize_comparison_columns()
        self._reset_comparison_table_scrollbars()
        QTimer.singleShot(0, self._reset_comparison_table_scrollbars)

    def _reset_comparison_table_scrollbars(self):
        if not hasattr(self, "comparison_table"):
            return
        self.comparison_table.horizontalScrollBar().setValue(0)
        self.comparison_table.verticalScrollBar().setValue(0)

    def _resize_comparison_columns(self):
        if not hasattr(self, "comparison_table"):
            return
        column_count = self.comparison_table.columnCount()
        viewport_width = self.comparison_table.viewport().width()
        if column_count < 2 or viewport_width <= 0:
            return
        usable_width = max(0, viewport_width - 20)
        source_width = max(220, min(320, int(usable_width * 0.24)))
        candidate_count = column_count - 1
        remaining = max(0, usable_width - source_width)
        candidate_width = max(250, remaining // candidate_count)
        self.comparison_table.setColumnWidth(0, source_width)
        for column in range(1, column_count):
            self.comparison_table.setColumnWidth(column, candidate_width)

    def _display_state(self, state: dict):
        self._invalidate_comparison()
        self.table.setRowCount(len(state.get("candidates", [])))
        human_review = state.get("human_review") or {}
        human_points = human_review.get("points")
        has_review_subset = "reviewed_candidate_ids" in human_review
        reviewed_candidate_ids = set(
            human_review.get("reviewed_candidate_ids")
            or (human_points or {}).keys()
        )
        quality_points = human_review.get("quality_points") or {}
        legacy_wins = human_review.get("wins") or {}
        for row, candidate in enumerate(state.get("candidates", [])):
            summary = candidate.get("summary") or {}
            stability = summary.get("stability") or {}
            valid = "—"
            if summary.get("total_segments"):
                valid = f"{summary.get('valid_rate', 0):.1%}"
            stable = "—"
            if stability.get("samples_with_all_repetitions"):
                stable = f"{stability.get('exact_sample_stability_rate', 0):.1%}"
            elif stability.get("segments_with_all_repetitions"):
                stable = f"{stability.get('exact_stability_rate', 0):.1%}"
            local_status = candidate.get("status", "")
            if local_status in {"completed", "failed"}:
                display_status = local_status.title()
            else:
                raw_status = candidate.get("api_status") or local_status
                display_status = str(raw_status or "").replace("_", " ").title()
            if has_review_subset and candidate["id"] not in reviewed_candidate_ids:
                review_score = "—"
            elif (
                isinstance(human_points, dict)
                and candidate["id"] in reviewed_candidate_ids
            ):
                review_score = human_points.get(candidate["id"], "—")
            elif candidate["id"] in legacy_wins:
                review_score = f"{legacy_wins[candidate['id']]} wins"
            else:
                review_score = "—"
            quality_scores = [
                (
                    (quality_points.get(metric) or {}).get(candidate["id"], "—")
                    if candidate["id"] in reviewed_candidate_ids else "—"
                )
                for metric in evaluation.REVIEW_QUALITY_METRICS
            ]
            values = (
                candidate.get("model", ""),
                candidate.get("endpoint") or candidate.get("provider", ""),
                candidate.get("execution", "batch").title(),
                display_status,
                f"${candidate.get('estimate', {}).get('cost_usd', 0):.2f}",
                (
                    f"${summary.get('actual_cost_usd', 0):.2f}"
                    if summary else "—"
                ),
                (
                    f"${summary.get('no_cache_cost_usd', 0):.2f}"
                    if "no_cache_cost_usd" in summary else "—"
                ),
                (
                    f"{summary.get('cache_read_rate', 0):.1%}"
                    if "cache_read_rate" in summary else "—"
                ),
                valid,
                stable,
                *quality_scores,
                str(review_score),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                column_name = self.COLUMNS[column]
                if column_name in self.COLUMN_TOOLTIPS:
                    item.setToolTip(self.COLUMN_TOOLTIPS[column_name])
                self.table.setItem(row, column, item)
        has_pending_batch = any(
            candidate.get("batch_id")
            and candidate.get("status") not in {"completed", "failed"}
            for candidate in state.get("candidates") or []
        )
        if has_pending_batch:
            self._poll_timer.start()
        else:
            self._poll_timer.stop()
        comparison_ready = bool(
            self.current_run_dir
            and state.get("status") in {"completed", "failed"}
        )
        self.results_tabs.setTabEnabled(
            self._comparison_tab_index, comparison_ready
        )
        if (
            comparison_ready
            and self.results_tabs.currentIndex() == self._comparison_tab_index
        ):
            QTimer.singleShot(0, self._start_comparison_load)
        self._update_actions(state)

    def _update_actions(self, state: dict | None = None):
        if state is None and self.current_run_dir:
            try:
                state, _manifest = evaluation.load_run(self.current_run_dir)
            except Exception:
                state = None
        status = state.get("status") if state else ""
        busy = self._worker is not None and self._worker.isRunning()
        candidates = state.get("candidates") if state else []
        has_pending_batch = any(
            candidate.get("batch_id")
            and candidate.get("status") not in {"completed", "failed"}
            for candidate in candidates or []
        )
        self.prepare_btn.setEnabled(not busy)
        self.submit_btn.setEnabled(
            not busy and status in {"prepared", "partially_submitted"}
        )
        self.refresh_btn.setEnabled(
            not busy and (
                status == "imported_paused"
                or (
                    status in {"submitted", "partially_submitted"}
                    and has_pending_batch
                )
            )
        )
        self.cancel_btn.setEnabled(busy and self._worker_cancelable)
        self.export_btn.setEnabled(not busy and status in {"completed", "failed"})
        self.copy_review_skill_btn.setEnabled(
            not busy
            and status in {"completed", "failed"}
            and self._review_csv_path() is not None
        )
        self.import_btn.setEnabled(
            not busy
            and status in {"completed", "failed"}
            and bool(self.current_run_dir)
        )
        self._update_history_actions()
