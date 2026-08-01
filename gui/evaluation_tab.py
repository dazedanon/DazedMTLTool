#!/usr/bin/env python3
"""Blinded, budget-capped translation model evaluation page."""

from __future__ import annotations

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
    QFrame,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolButton,
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
        "Consistency", "Human wins",
    )
    COLUMN_TOOLTIPS = {
        "Valid": (
            "Percentage of all expected line outputs that passed automatic checks "
            "for missing output, Japanese residue, placeholders, and RPG Maker "
            "control codes. This does not judge translation quality."
        ),
        "Consistency": (
            "Of the repeated sample lines with a valid result on every run, the "
            "percentage whose normalized English was exactly identical each time. "
            "Higher means less variation, not necessarily a better translation."
        ),
    }
    PROVIDER_PRESETS = API_URL_PRESETS
    MODEL_SUGGESTIONS = {
        "openai": ("gpt-5.6-terra", "gpt-5", "gpt-4.1", "gpt-4.1-mini"),
        "gemini": ("gemini-3.6-flash", "gemini-3.5-flash", "gemini-2.5-flash"),
        "anthropic": ("claude-sonnet-5", "claude-sonnet-4-6", "claude-haiku-4-5"),
    }
    TEST_SIZES = (
        ("Quick — about 120 lines", 120, 30),
        ("Standard — about 360 lines (recommended)", 360, 120),
        ("Thorough — about 600 lines", 600, 180),
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

        for candidate in evaluation.DEFAULT_CANDIDATES:
            self._add_candidate_row(
                candidate.get("endpoint") or candidate["provider"],
                candidate["model"],
                candidate.get("execution", "batch"),
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
        self._update_source_resolution()

        options = QGridLayout()
        options.setHorizontalSpacing(12)
        options.setVerticalSpacing(8)

        self.test_size_combo = QComboBox()
        for label, lines, consistency_lines in self.TEST_SIZES:
            self.test_size_combo.addItem(label, (lines, consistency_lines))
        self.test_size_combo.setCurrentIndex(1)
        self.budget_spin = QDoubleSpinBox()
        self.budget_spin.setRange(1.0, 100.0)
        self.budget_spin.setDecimals(2)
        self.budget_spin.setValue(evaluation.DEFAULT_BUDGET_USD)
        self.budget_spin.setPrefix("$")

        option_widgets = (("Test size", self.test_size_combo), ("Budget per model", self.budget_spin))
        for index, (label_text, widget) in enumerate(option_widgets):
            widget.setMinimumWidth(132)
            widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            label = QLabel(label_text)
            label.setStyleSheet("font-weight: 600;")
            options.addWidget(label, 0, index)
            options.addWidget(widget, 1, index)
            options.setColumnStretch(index, 1)
        setup.add_layout(options)

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
        for name, tooltip in self.COLUMN_TOOLTIPS.items():
            index = self.COLUMNS.index(name)
            item = self.table.horizontalHeaderItem(index)
            item.setText(f"{name} ⓘ")
            item.setToolTip(tooltip)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        for index in range(len(self.COLUMNS)):
            header.setSectionResizeMode(index, QHeaderView.Interactive)
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
        """Keep result columns balanced without crushing the compact fields."""
        if not hasattr(self, "table"):
            return
        viewport_width = max(0, self.table.viewport().width() - 8)
        if not viewport_width:
            return
        proportions = (0.18, 0.21, 0.07, 0.11, 0.09, 0.08, 0.07, 0.11, 0.08)
        minimums = (210, 240, 80, 120, 100, 90, 80, 140, 110)
        for index, (proportion, minimum) in enumerate(zip(proportions, minimums)):
            self.table.setColumnWidth(
                index, max(minimum, round(viewport_width * proportion))
            )

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
        self.history_combo.setEnabled(not busy and has_selection)
        self.export_evaluation_btn.setEnabled(not busy and has_selection)
        self.import_evaluation_btn.setEnabled(not busy)

    def _refresh_history(self, select_run: str | Path | None = None):
        preferred = Path(select_run).resolve() if select_run else (
            self.current_run_dir.resolve() if self.current_run_dir else None
        )
        runs = evaluation.list_runs(self.project_root)
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
            reviewed = int(run.get("reviewed", 0) or 0)
            label = (
                f"{created or run_dir.name}  ·  {models}  ·  {modes}  ·  "
                f"{status}  ·  {lines:,} lines"
            )
            if reviewed:
                label += f"  ·  {reviewed:,} reviewed"
            self.history_combo.addItem(label, str(run_dir))
            self.history_combo.setItemData(index, label, Qt.ToolTipRole)
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
            set_status_text(
                self.source_resolution_label,
                "Select a game folder. Evaluation will find its data/ or www/data/ files.",
                "neutral",
            )
            return
        try:
            data_dir = evaluation.resolve_rpgmaker_data_dir(selected)
        except (FileNotFoundError, ValueError):
            set_status_text(
                self.source_resolution_label,
                "No MV/MZ data found yet. Choose the game folder, or its data/ or "
                "www/data/ folder.",
                "warning",
            )
            return
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

    def _add_candidate_row(
        self, endpoint: str = "https://api.openai.com/v1", model: str = "",
        execution: str = "batch",
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
        model_combo.setEditable(False)
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
        self._refresh_candidate_key(widgets)
        self._reflow_candidate_rows()
        self._schedule_candidate_model_scan(widgets, delay_ms=350)

    def _remove_candidate_row(self, widgets: dict):
        if len(self._candidate_widgets) <= 2:
            QMessageBox.information(
                self, "Models required", "An evaluation needs at least two models."
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
            widgets["remove"].setEnabled(len(self._candidate_widgets) > 2)
        QTimer.singleShot(0, self._refresh_responsive_geometry)

    def _refresh_model_suggestions(self, widgets: dict, preferred: str = ""):
        combo = widgets["model"]
        current = preferred or combo.currentText().strip()
        provider = self._provider_for_endpoint(widgets["endpoint"].text())
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(self.MODEL_SUGGESTIONS.get(provider, ()))
        current_index = combo.findText(current) if current else -1
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
        widgets["remove"].setEnabled(len(self._candidate_widgets) > 2)
        if widgets.get("model_fetch_pending"):
            widgets["model_fetch_pending"] = False
            QTimer.singleShot(0, lambda row=widgets: self._fetch_candidate_models(row))

    def _refresh_candidate_key(
        self, widgets: dict, names: list[str] | None = None,
        *, prefer_provider: bool = False,
    ):
        names = api_key_vault.list_names() if names is None else names
        active = api_key_vault.get_active_name()
        combo = widgets["key"]
        previous = combo.currentText()
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
            self._set_busy(False)
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
        target_segments, consistency_segments = self.test_size_combo.currentData()
        values = {
            "target_segments": target_segments,
            "stability_segments": consistency_segments,
            "repetitions": evaluation.DEFAULT_REPETITIONS,
            "batch_size": evaluation.DEFAULT_BATCH_SIZE,
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
                f"{summary.get('selected_files', 0):,} files. Review the estimates, "
                "then submit the model batches together.",
                "success",
            )
            self._append_log(
                f"Selection: {summary.get('selected_segments', 0):,} lines from "
                f"{summary.get('selected_files', 0):,} of "
                f"{summary.get('eligible_files', 0):,} eligible files."
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
            return evaluation.submit_run(self.current_run_dir, credentials, log)

        def done(updated):
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
        coverage_message = (
            f"Blind review coverage: {eligible:,}/{total:,} segments will be "
            f"exported ({excluded:,} excluded)."
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
                f"Blind review exported with {eligible:,}/{total:,} segments. "
                "Fill in the winner column, then import the reviewed CSV.",
                "success",
            )
            self._update_actions()
            QMessageBox.information(
                self, "Blind review",
                f"Exported {eligible:,} of {total:,} segments; {excluded:,} were "
                "excluded because at least one model lacked a valid translation. "
                "Enter the column label for the best translation in the winner "
                "column, or enter TIE, then import the CSV. Labels are randomized "
                "independently for every line.",
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
            token = "{{BLIND_REVIEW_CSV}}"
            if token not in prompt:
                raise ValueError("Evaluation review skill is missing its CSV placeholder")
            prompt = prompt.replace(token, str(review_path))
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
                f"Imported {review['reviewed']} judgments ({review['ties']} ties)."
            )
        except Exception as exc:
            QMessageBox.warning(self, "Blind review", str(exc))

    def _display_state(self, state: dict):
        self.table.setRowCount(len(state.get("candidates", [])))
        human_wins = (state.get("human_review") or {}).get("wins") or {}
        for row, candidate in enumerate(state.get("candidates", [])):
            summary = candidate.get("summary") or {}
            stability = summary.get("stability") or {}
            valid = "—"
            if summary.get("total_segments"):
                valid = f"{summary.get('valid_rate', 0):.1%}"
            stable = "—"
            if stability.get("segments_with_all_repetitions"):
                stable = f"{stability.get('exact_stability_rate', 0):.1%}"
            local_status = candidate.get("status", "")
            if local_status in {"completed", "failed"}:
                display_status = local_status.title()
            else:
                raw_status = candidate.get("api_status") or local_status
                display_status = str(raw_status or "").replace("_", " ").title()
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
                str(human_wins.get(candidate["id"], "—")),
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
        self.export_btn.setEnabled(not busy and status == "completed")
        self.copy_review_skill_btn.setEnabled(
            not busy and status == "completed" and self._review_csv_path() is not None
        )
        self.import_btn.setEnabled(
            not busy and status == "completed" and bool(self.current_run_dir)
        )
        self._update_history_actions()
