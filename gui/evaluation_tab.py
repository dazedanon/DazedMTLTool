#!/usr/bin/env python3
"""Blinded, budget-capped translation model evaluation page."""

from __future__ import annotations

import os
from pathlib import Path

from PyQt5.QtCore import QEvent, Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
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
    make_page_layout,
    set_status_text,
)
from gui.config_tab import API_URL_PRESETS, ConfigComboBox, ConfigMenu, ModelFetchThread
from util import api_keys as api_key_vault
from util import evaluation
from util.skills import load_clipboard_skill


class _EvaluationWorker(QThread):
    done = pyqtSignal(bool, str, object)
    log = pyqtSignal(str)

    def __init__(self, task, parent=None):
        super().__init__(parent)
        self._task = task

    def run(self):
        try:
            payload = self._task(self.log.emit)
            self.done.emit(True, "", payload)
        except Exception as exc:
            import traceback

            self.log.emit(traceback.format_exc())
            self.done.emit(False, str(exc), None)


class EvaluationTab(QWidget):
    """Prepare, submit, and review a user-defined model comparison."""

    COLUMNS = (
        "Model", "API URL", "Mode", "Status", "Estimate", "Actual", "Valid",
        "Consistency", "Meaning Accuracy", "Glossary & Prompt",
        "Natural & Contextual", "Best overall",
    )
    COLUMN_LABELS = {
        "Meaning Accuracy": "Meaning\nAccuracy",
        "Glossary & Prompt": "Glossary &\nPrompt",
        "Natural & Contextual": "Natural &\nContextual",
        "Best overall": "Best\noverall",
    }
    COLUMN_TOOLTIPS = {
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.project_root = Path(
            getattr(parent, "project_root", None) or Path(__file__).resolve().parent.parent
        )
        self.current_run_dir: Path | None = None
        self._last_review_path: Path | None = None
        self._worker: _EvaluationWorker | None = None
        self._candidate_widgets: list[dict] = []
        self._content_inventory: dict = {}
        self._content_source_items: dict[str, QTreeWidgetItem] = {}
        self._content_map_items: dict[str, QTreeWidgetItem] = {}
        self._custom_content_selection: dict | None = None
        self._active_content_preset = "balanced"
        self._init_ui()
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(60_000)
        self._poll_timer.timeout.connect(self.refresh_results)
        QTimer.singleShot(0, self._load_latest)

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

        self.history_combo = QComboBox()
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
        self.content_preset_combo = QComboBox()
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
        self._update_source_resolution()

        options = QGridLayout()
        options.setHorizontalSpacing(12)
        options.setVerticalSpacing(8)

        self.test_size_combo = QComboBox()
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
        self.refresh_btn = QPushButton("Refresh results")
        self.export_btn = QPushButton("Export blind review")
        self.copy_review_skill_btn = QPushButton("Copy review skill")
        self.import_btn = QPushButton("Import reviewed CSV")
        configure_action_button(self.prepare_btn, variant="primary")
        for button in (
            self.submit_btn, self.refresh_btn, self.export_btn,
            self.copy_review_skill_btn, self.import_btn,
        ):
            configure_action_button(button, variant="secondary")
        self.copy_review_skill_btn.setToolTip(
            "Copy instructions for an AI helper to review the blinded CSV. "
            "AI judgments can be biased and should be treated as a second opinion."
        )
        self.prepare_btn.clicked.connect(self.prepare_benchmark)
        self.submit_btn.clicked.connect(self.submit_batches)
        self.refresh_btn.clicked.connect(self.refresh_results)
        self.export_btn.clicked.connect(self.export_review)
        self.copy_review_skill_btn.clicked.connect(self.copy_review_skill)
        self.import_btn.clicked.connect(self.import_review)
        for column, button in enumerate((
            self.prepare_btn, self.submit_btn, self.refresh_btn,
        )):
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            actions.addWidget(button, 0, column * 2, 1, 2)
        for column in range(6):
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
        results.add_widget(self.table, 2)

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
        return super().eventFilter(watched, event)

    def _refresh_responsive_geometry(self):
        if hasattr(self, "setup_card"):
            self.setup_card.setMinimumHeight(0)
            self.setup_card.setMinimumHeight(self.setup_card.sizeHint().height())
        self._resize_result_columns()

    def _resize_result_columns(self):
        """Keep every result column visible within the table viewport."""
        if not hasattr(self, "table"):
            return
        viewport_width = max(0, self.table.viewport().width() - 1)
        if not viewport_width:
            return
        weights = (
            1.55, 1.65, 0.60, 0.82, 0.68, 0.62, 0.60, 0.90,
            0.95, 1.02, 1.12, 0.82,
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
        preferred = Path(select_run).resolve() if select_run else (
            self.current_run_dir.resolve() if self.current_run_dir else None
        )
        runs = evaluation.list_runs(self.project_root)
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

    def _open_run(self, run_dir: str | Path, *, refresh_history: bool = True):
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
            self._open_run(selected)

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
            "API base URL. Custom URLs use the OpenAI-compatible Batch API format."
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

        key_combo = QComboBox()
        key_combo.setMinimumWidth(220)
        key_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        model_combo = ConfigComboBox()
        # Model discovery is optional for chat-only local servers. Keep the
        # suggestions, but allow an operator to enter a server-specific ID.
        model_combo.setEditable(True)
        model_combo.setMaxVisibleItems(12)
        model_combo.setToolTip(
            "Models available from the selected API URL and saved key"
        )
        model_combo.setMinimumWidth(260)
        model_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        execution_combo = QComboBox()
        execution_combo.addItem("Batch", "batch")
        execution_combo.addItem("Live", "live")
        execution_index = execution_combo.findData(execution)
        execution_combo.setCurrentIndex(max(0, execution_index))
        execution_combo.setToolTip(
            "Batch is cheaper and asynchronous. Live also supports chat-only local servers."
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
        self._refresh_model_suggestions(widgets)
        self._refresh_candidate_key(widgets, prefer_provider=True)
        self._schedule_candidate_model_scan(widgets)

    def _on_candidate_endpoint_changed(self, widgets: dict):
        self._refresh_model_suggestions(widgets)
        self._refresh_candidate_key(widgets)
        self._schedule_candidate_model_scan(widgets)

    def _on_candidate_key_changed(self, widgets: dict):
        key_name = widgets["key"].currentText().strip()
        endpoint = api_key_vault.get_endpoint(key_name) or ""
        if endpoint:
            widgets["endpoint"].setText(endpoint)
            widgets["endpoint"].setCursorPosition(0)
            self._refresh_model_suggestions(widgets)
        self._schedule_candidate_model_scan(widgets)

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
            secret = api_key_vault.get_secret(candidate.get("key_name", "")) or ""
            credentials[candidate["id"]] = secret
        return credentials

    def _set_busy(self, busy: bool):
        for button in (
            self.prepare_btn, self.submit_btn, self.refresh_btn,
            self.export_btn, self.copy_review_skill_btn, self.import_btn,
            self.export_evaluation_btn, self.import_evaluation_btn,
        ):
            button.setEnabled(not busy)
        if not busy:
            self._update_actions()
            self._update_history_actions()

    def _run_task(self, task, on_done):
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, "Evaluation busy", "An evaluation operation is still running.")
            return
        self._set_busy(True)
        worker = _EvaluationWorker(task, self)
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
            # The result signal arrives while QThread.isRunning() is still
            # true. Restore actions only after the actual thread-finished
            # signal so _update_actions() cannot disable them again.
            self._set_busy(False)

    def _load_latest(self):
        self._refresh_keys()
        self._refresh_history()
        latest = evaluation.latest_run(self.project_root)
        if latest:
            self._open_run(latest, refresh_history=False)
            self._refresh_history(latest)
        else:
            selected = self._selected_history_run()
            if selected is not None:
                self._open_run(selected, refresh_history=False)

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

        self._run_task(task, done)

    def submit_batches(self):
        if not self.current_run_dir:
            return
        state, manifest = evaluation.load_run(self.current_run_dir)
        if state["status"] not in {"prepared", "partially_submitted"}:
            return
        lines = [
            f"{candidate['label']} ({candidate.get('execution', 'batch').title()}): "
            f"${candidate['estimate']['cost_usd']:.2f} estimated; "
            f"${candidate['estimate']['maximum_cost_usd']:.2f} ceiling"
            for candidate in state["candidates"] if not candidate.get("batch_id")
        ]
        answer = QMessageBox.question(
            self,
            "Run evaluation?",
            "This sends paid requests. Batch rows create asynchronous provider "
            "jobs; Live rows run immediately and require the app to remain open. The same "
            f"{len(manifest['executions'])} requests are used for every model.\n\n"
            + "\n".join(lines)
            + f"\n\nHard budget: ${state['budget_usd_per_model']:.2f} per model.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        credentials = self._credentials(state)
        set_status_text(self.status_label, "Starting evaluation requests…", "info")

        def task(log):
            return evaluation.submit_run(
                self.current_run_dir,
                credentials,
                log,
                should_stop=lambda: QThread.currentThread().isInterruptionRequested(),
            )

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
                set_status_text(
                    self.status_label,
                    "Batch jobs were submitted. This page checks them every 60 seconds while open.",
                    "success",
                )
                self._poll_timer.start()

        self._run_task(task, done)

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
                "using saved keys with matching names. Continue?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
            state = evaluation.resume_imported_run(self.current_run_dir)
        credentials = self._credentials(state)

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

    def export_review(self):
        if not self.current_run_dir:
            return
        try:
            coverage = evaluation.blind_review_coverage(self.current_run_dir)
        except Exception as exc:
            QMessageBox.warning(self, "Blind review", str(exc))
            return
        eligible = coverage["eligible_segments"]
        total = coverage["total_segments"]
        excluded = coverage["excluded_segments"]
        eligible_samples = coverage["eligible_samples"]
        total_samples = coverage["total_samples"]
        excluded_samples = coverage["excluded_samples"]
        coverage_message = (
            f"Blind review coverage: {eligible_samples:,}/{total_samples:,} "
            f"whole samples containing {eligible:,}/{total:,} lines will be "
            f"exported. {excluded_samples:,} samples are omitted because at "
            "least one model has an invalid or missing line in them."
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
            path = evaluation.export_blind_review(self.current_run_dir, selected)
            self._last_review_path = Path(path)
            self._append_log(f"Blinded review exported: {path}")
            set_status_text(
                self.status_label,
                f"Blind review exported with {eligible_samples:,}/{total_samples:,} "
                f"complete samples ({eligible:,}/{total:,} lines). "
                f"{excluded_samples:,} samples were omitted because at least "
                "one model had an invalid or missing line. "
                "Fill in the ranking column, then import the reviewed CSV.",
                "success",
            )
            self._update_actions()
            QMessageBox.information(
                self, "Blind review",
                f"Exported {eligible_samples:,} of {total_samples:,} samples "
                f"containing {eligible:,} lines; {excluded_samples:,} samples "
                f"and {excluded:,} lines were excluded because at least one model "
                "lacked a valid translation. "
                "Rank every candidate in the ranking column, for example A>B>C. "
                "Use = for tied tiers, such as A=B>C or A>B=C. Labels are "
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

    def _display_state(self, state: dict):
        self.table.setRowCount(len(state.get("candidates", [])))
        human_review = state.get("human_review") or {}
        human_points = human_review.get("points")
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
            if isinstance(human_points, dict):
                review_score = human_points.get(candidate["id"], "—")
            elif candidate["id"] in legacy_wins:
                review_score = f"{legacy_wins[candidate['id']]} wins"
            else:
                review_score = "—"
            quality_scores = [
                (quality_points.get(metric) or {}).get(candidate["id"], "—")
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
        if state.get("status") in {"submitted", "partially_submitted"}:
            self._poll_timer.start()
        self._update_actions(state)

    def _update_actions(self, state: dict | None = None):
        if state is None and self.current_run_dir:
            try:
                state, _manifest = evaluation.load_run(self.current_run_dir)
            except Exception:
                state = None
        status = state.get("status") if state else ""
        busy = self._worker is not None and self._worker.isRunning()
        self.prepare_btn.setEnabled(not busy)
        self.submit_btn.setEnabled(
            not busy and status in {"prepared", "partially_submitted"}
        )
        self.refresh_btn.setEnabled(
            not busy and status in {
                "submitted", "partially_submitted", "imported_paused"
            }
        )
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
