"""
Wolf RPG (WolfDawn) Workflow Tab - guided pipeline for WOLF RPG Editor games.

Mirrors the RPGMaker WorkflowTab, driven by the vendored WolfDawn ``wolf`` CLI
(see util/wolfdawn):

  Step 0  Project     - select game folder; import wolf_json/ into files/ (like RPGMaker)
  Step 1  Pre-process - optional dazedformat + gameupdate/ copy before translating
  Step 2  Setup       - Project Setup skill + vocab / quirks / game skills editors
                        (build glossary and API overlays before translating)
  Step 3  Names       - translate names.json (Phase 0). WolfDawn safe entries
                        are translated per-name; refs and verify names are skipped.
                        Harvests short name terms into vocab.txt.
  Step 4  Database    - discover content layout; translate foundation DB sheets
                        (items, skills, descriptions) before narrative custom sheets;
                        harvests short label fields (map names, titles) into vocab.txt
  Step 5  Maps/Events - .mps maps, CommonEvent, Game.dat, Evtext; speaker handling
  Step 6  Precheck    - name consistency + reconcile, then dry-run inject for
                        safety-guard skips; edit those lines before writing binaries
  Step 7  Inject      - inject every JSON into Data/ from translated/ (default)
                        or from the game's wolf_json/; translated inject also
                        refreshes wolf_json/ (full pass avoids name/DB wipe bugs);
                        wolf_json inject optionally copies those JSON into files/
                        and translated/ so tool progress is not left behind;
                        optional layout-restore re-applies source whitespace pads
  Step 8  Package     - run from a loose Data/ folder or repack Data.wolf;
                        optional save rewrite for existing .sav files
  Step 9  Fix wrap    - search translated JSON by in-game text; Relayout
                        (names-wrap / cell geometry) or Manual (width + font);
                        then Apply all translations in Step 7 and re-package

names.json is staged into files/ but is NOT translated in the bulk phases - WolfDawn
tags each name safe / refs / verify and Phase 0 translates only safe entries
(per-name, not per-category), harvests them into vocab.txt, and Step 7 injects the
result. Package (Step 8) makes the build playable; Fix wrap (Step 9) is the
playtest feedback loop.

The extracted JSON is staged in ``<game_root>/wolf_json/`` (a manifest maps each
file back to its base binary), then imported into ``files/`` for the shared
translation pipeline, mirroring how the Ace workflow uses ``ace_json/``. On
inject, the translated JSON is copied back into ``wolf_json/`` so the game
project's git history tracks both the JSON source and the updated binaries.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path

from PyQt5.QtCore import Qt, QSettings, QSize, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStyle,
    QTabWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from gui.translation_tab import (
    BATCH_COLLECT_LIVE_CHARGE_NOTE,
    BATCH_MODE_BENEFIT_NOTE,
    BATCH_MODE_LABEL,
    default_translation_mode,
)
from gui.ui_components import CheckableFileList, equalize_button_widths
from gui.workflow_tab import (
    _GAMEUPDATE_COPY_SKIP_NAMES,
    _FileCopyWorker,
    _ImportWorker,
    _make_btn,
    _make_hr,
    _make_icon_btn,
    _make_text_btn,
    _make_section_label,
)
from util.wolfdawn import names as wolf_names
from util.wolfdawn import codes as wolf_codes
from util.wolfdawn import db_classify as wolf_db
from util.wolfdawn import wrap_search as wolf_ws
import util.dazedwrap as dazedwrap

from gui.setup_skills_editors import SetupSkillsEditors
from gui.theme import COLORS, Geometry, Spacing
from gui.workflow_components import (
    WorkflowActivityPanel,
    WorkflowPageHeader,
    WorkflowStepRail,
)
from util.paths import PROJECT_ROOT, VOCAB_PATH, APP_NAME, ORG_NAME
from util.project_scanner import (
    detect_wolf_layout,
    find_wolf_text_archives,
    find_wolf_unpack_gaps,
    list_wolf_json_files,
    wolf_has_maps,
    wolf_maps_dir,
    wolf_maps_packed,
    wolf_repair_nested_data_dir,
    wolf_unpack_out_dir,
)
from util.skills import load_clipboard_skill, load_project_setup

# Workflow-level label for the non-batch (live) translation path. The Translation
# tab's own mode is called "Translate"; _workflow_mode_text() maps to that.
_TL_NORMAL_LABEL = "Normal Translate"

MANIFEST_NAME = "manifest.json"
NAMES_JSON = "names.json"
WORK_DIR_NAME = "wolf_json"

# Translation phases, keyed by the manifest ``kind`` of each extracted file.
# Mirrors RPGMaker's DB-first strategy: translate names first (they seed the
# glossary), then database descriptions, then maps and event scripts.
PHASE_NAMES_KINDS = {"names"}
PHASE_DB_KINDS = {"db"}
PHASE_MAPS_EVENTS_KINDS = {"map", "common", "gamedat", "txt", "txt-dir"}
# The speaker-format prompt is loaded from editable data/skills/wolf_speakers.md.


class _WolfTaskWorker(QThread):
    """Run a blocking WolfDawn task callable off the UI thread.

    The task receives ``log`` and ``progress`` callables and returns
    ``(success, message)``.
    """

    done = pyqtSignal(bool, str)
    log = pyqtSignal(str)
    progress = pyqtSignal(int, int, str)

    def __init__(self, task):
        super().__init__()
        self._task = task

    def run(self):
        try:
            ok, msg = self._task(
                self.log.emit,
                lambda current, total, label: self.progress.emit(current, total, label),
            )
            self.done.emit(bool(ok), str(msg))
        except Exception as exc:  # pragma: no cover - defensive
            import traceback

            self.log.emit(traceback.format_exc())
            self.done.emit(False, f"Error: {exc}")


class WolfWorkflowTab(QWidget):
    """Guided automation tab for the full WolfDawn translation pipeline."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        try:
            self.settings = QSettings(ORG_NAME, APP_NAME)
        except Exception:
            self.settings = None

        # State
        self._game_root: str = ""
        self._layout: dict = {}
        self._worker: _WolfTaskWorker | None = None
        self._import_worker: _ImportWorker | None = None
        self._buttons: list[QPushButton] = []
        self._import_buttons: list[QPushButton] = []
        self._detected_on_show: bool = False
        self._current_step_index: int = 0
        self._file_items: list[dict] = []
        self._last_import_signature: tuple[str, ...] | None = None
        self._pending_import_signature: tuple[str, ...] | None = None
        self._syncing_file_checks: bool = False
        self._gameupdate_path: str = ""
        self._tl_mode_user_selected = False
        self._last_default_translation_mode = None
        self._tl_mode_combos = []

        self._init_ui()

    def showEvent(self, event):
        """Auto-detect the saved game folder when the tab is first shown."""
        super().showEvent(event)
        if hasattr(self, "_step_rail"):
            self._step_rail.set_compact(
                self.width() < 1320
                or self._step_rail.labels_require_compact_mode()
            )
        if not self._detected_on_show and self._setting("last_game_folder", ""):
            self._detected_on_show = True
            if self.folder_edit.text().strip():
                QTimer.singleShot(100, self._detect_folder)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_step_rail"):
            self._step_rail.set_compact(
                self.width() < 1320
                or self._step_rail.labels_require_compact_mode()
            )

    # ───────────────────────────────── paths ─────────────────────────────────

    def _work_dir(self) -> Path:
        return Path(self._game_root) / WORK_DIR_NAME

    def _manifest_path(self) -> Path:
        return self._work_dir() / MANIFEST_NAME

    def _read_manifest(self) -> dict | None:
        mp = self._manifest_path()
        if not mp.is_file():
            return None
        try:
            return json.loads(mp.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _manifest_kinds(self) -> dict:
        """Return ``{json_filename: kind}`` from the manifest (used to pick which
        files a translation phase should translate)."""
        out: dict[str, str] = {}
        manifest = self._read_manifest()
        if manifest:
            for entry in manifest.get("entries", []):
                name, kind = entry.get("json"), entry.get("kind")
                if name and kind:
                    out[name] = kind
        return out

    # ─────────────────────────── pristine originals ──────────────────────────
    # WolfDawn injects by locating each Japanese `source` string inside the base
    # binary and replacing it. That only works against the *original* (untranslated)
    # binary: once a file has been injected it holds English, so re-injecting can no
    # longer find the Japanese sources and every line is reported as "drift" (a
    # silent no-op). To keep injection idempotent and re-runnable, we always inject
    # from a pristine snapshot of the binaries into the live Data/ folder.

    def _originals_dir(self) -> Path:
        return self._work_dir() / "originals"

    def _orig_base_for(self, entry: dict, data_dir: Path) -> Path:
        """Pristine-snapshot path mirroring an entry's base under originals/."""
        base = Path(entry["base"])
        try:
            rel = base.relative_to(data_dir)
        except ValueError:
            rel = Path(base.name)
        return self._originals_dir() / rel

    def _snapshot_db_dat_sibling(
        self, entry: dict, data_dir: Path, log=None
    ) -> None:
        """Snapshot the ``.dat`` sibling for a database ``.project`` entry.

        WolfDawn ``strings-inject`` on ``kind == "db"`` needs both files in the
        ``--base`` directory. The manifest only lists the ``.project`` path.
        """
        from util.wolfdawn import db_dat_sibling

        if entry.get("kind") != "db":
            return
        proj_orig = self._orig_base_for(entry, data_dir)
        dat_orig = db_dat_sibling(proj_orig)
        if dat_orig.exists():
            return
        dat_live = db_dat_sibling(Path(entry["base"]))
        if not dat_live.is_file():
            return
        try:
            dat_orig.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dat_live, dat_orig)
        except Exception as exc:
            if log:
                log(f"  ⚠ could not snapshot {dat_orig.name}: {exc}")

    def _ensure_db_dat_snapshots(
        self, entries: list[dict], data_dir: Path, log=None
    ) -> None:
        """Backfill missing database ``.dat`` files in originals/."""
        for entry in entries:
            self._snapshot_db_dat_sibling(entry, data_dir, log)

    def _snapshot_originals(self, entries: list[dict], data_dir: Path, log) -> None:
        """Copy the pristine base binaries into originals/ (only when missing, so a
        good snapshot is never clobbered by a later extract of injected data)."""
        for entry in entries:
            if entry.get("kind") == "names":
                continue
            src = Path(entry["base"])
            dst = self._orig_base_for(entry, data_dir)
            if dst.exists():
                self._snapshot_db_dat_sibling(entry, data_dir, log)
                continue
            try:
                if src.is_dir():
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                elif src.is_file():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
            except Exception as exc:
                log(f"  ⚠ could not snapshot original {src.name}: {exc}")
                continue
            self._snapshot_db_dat_sibling(entry, data_dir, log)

    def _ensure_originals(self, manifest: dict, log, progress=None, *, quiet: bool = False) -> None:
        """Make sure a pristine snapshot exists; if entries are missing it and the
        game still has its .wolf archives (packaging renames them to .wolf.bak),
        rebuild the snapshot by unpacking those archives into originals/."""
        from util import wolfdawn

        emit = (lambda _msg: None) if quiet else log
        wolf_log = None if quiet else log

        data_dir = Path(manifest["data_dir"])
        entries = manifest.get("entries", [])
        missing = [
            e for e in entries
            if e.get("kind") != "names" and not self._orig_base_for(e, data_dir).exists()
        ]
        if not missing:
            return

        root = Path(self._game_root)
        # Only the binary archives (MapData / BasicData) are needed for inject.
        archives: list[Path] = []
        for base in (root, data_dir):
            if base.is_dir():
                for pat in ("*.wolf", "*.wolf.bak"):
                    archives.extend(base.glob(pat))
        wanted = [a for a in archives if a.name.lower().startswith(("mapdata", "basicdata"))]
        if not wanted:
            emit(
                "  ⚠ No pristine originals and no .wolf archives to rebuild them from. "
                "Re-run Step 0 (Unpack + Extract) on the untranslated game so injection "
                "has an original to work from."
            )
            return

        originals = self._originals_dir()
        originals.mkdir(parents=True, exist_ok=True)
        emit("Rebuilding pristine originals from the game's .wolf archives …")
        with tempfile.TemporaryDirectory() as tmp:
            inputs: list[str] = []
            for arc in wanted:
                # unpack-all only accepts a .wolf extension; present .bak copies as .wolf.
                if arc.suffix == ".bak":
                    staged = Path(tmp) / arc.with_suffix("").name  # X.wolf.bak -> X.wolf
                    shutil.copy2(arc, staged)
                    inputs.append(str(staged))
                else:
                    inputs.append(str(arc))
            res = wolfdawn.unpack_all(
                inputs,
                str(originals),
                log_fn=wolf_log,
                progress_fn=progress,
                progress_total=len(inputs),
            )
            if not res.ok:
                emit(f"  ⚠ could not rebuild originals (unpack exit {res.returncode}).")
        self._ensure_db_dat_snapshots(entries, data_dir, None if quiet else log)

    def _restore_live_from_originals(
        self, entries: list[dict], data_dir: Path, log, *, quiet: bool = False
    ) -> None:
        """Copy pristine originals onto live Data/ binaries before names-inject.

        ``names-inject`` rewrites every DB pair, CommonEvent.dat, and every map.
        Resetting from ``wolf_json/originals/`` first keeps them on one baseline.
        """
        from util.wolfdawn import db_dat_sibling

        emit = (lambda _msg: None) if quiet else log
        restored = 0
        for entry in entries:
            if entry.get("kind") == "names":
                continue
            orig = self._orig_base_for(entry, data_dir)
            live = Path(entry["base"])
            if not orig.exists():
                emit(f"  ⚠ no pristine original for {entry['json']} — live file left as-is")
                continue
            try:
                if orig.is_dir():
                    if live.exists():
                        shutil.rmtree(live)
                    shutil.copytree(orig, live)
                else:
                    live.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(orig, live)
                    if entry.get("kind") == "db":
                        dat_orig = db_dat_sibling(orig)
                        dat_live = db_dat_sibling(live)
                        if dat_orig.is_file():
                            shutil.copy2(dat_orig, dat_live)
                restored += 1
            except Exception as exc:
                emit(f"  ⚠ could not restore {live.name} from originals: {exc}")
        if restored and not quiet:
            log(
                f"Restored {restored} live binary file(s) from {WORK_DIR_NAME}/originals/."
            )

    # ───────────────────────────────── UI setup ──────────────────────────────

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        _SCROLL_STYLE = (
            "QScrollArea{border:none;background-color:transparent;}"
            "QScrollBar:vertical{background:#252526;width:10px;border:none;}"
            "QScrollBar::handle:vertical{background:#555555;border-radius:5px;min-height:20px;}"
            "QScrollBar::handle:vertical:hover{background:#007acc;}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}"
        )

        self._step_tabs = QTabWidget()
        self._step_tabs.setDocumentMode(True)
        self._step_tabs.tabBar().setVisible(False)
        self._step_tabs.setStyleSheet("""
            QTabWidget::pane { border: none; background-color: #1e1e1e; top: 0; }
            QTabBar { height: 0; max-height: 0; }
        """)

        self._step_labels: list[str] = []
        self._step_done: set[int] = set()
        self._step_buttons: list[QToolButton] = []

        # Names curation comes before Translate so Phase 0 can seed vocab.txt.
        _tab_defs = [
            ("0  Project", self._build_step0),
            ("1  Pre-process", self._build_step1_preprocess),
            ("2  Setup", self._build_step2_setup),
            ("3  Names", self._build_step3_names),
            ("4  Database", self._build_step4_database),
            ("5  Maps/Events", self._build_step5_maps_events),
            ("6  Precheck", self._build_step6_precheck),
            ("7  Inject", self._build_step7_inject),
            ("8  Package", self._build_step8_package),
            ("9  Fix wrap", self._build_step9_relayout),
        ]
        rail_labels = [
            "Project", "Prepare", "Setup", "Names", "Database",
            "Maps & events", "Precheck", "Inject", "Package", "Fix wrap",
        ]
        self._step_labels = [label for label, _ in _tab_defs]
        self._step_rail = WorkflowStepRail(rail_labels)
        self._step_rail.title_label.setText("WOLF RPG")
        self._step_rail.step_requested.connect(self._goto_step)

        for tab_label, builder in _tab_defs:
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(0, 0, 0, 0)
            page_layout.setSpacing(0)

            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setStyleSheet(_SCROLL_STYLE)

            inner = QWidget()
            vbox = QVBoxLayout(inner)
            vbox.setContentsMargins(
                Spacing.LG, Spacing.LG, Spacing.LG, Spacing.MD
            )
            vbox.setSpacing(Spacing.MD)
            builder(vbox)
            vbox.addStretch()

            scroll.setWidget(inner)
            page_layout.addWidget(scroll, 1)

            # Navigation footer
            nav = QWidget()
            nav.setObjectName("workflowFooter")
            nav_layout = QHBoxLayout(nav)
            nav_layout.setContentsMargins(
                Spacing.LG, Spacing.SM, Spacing.LG, Spacing.SM
            )
            nav_layout.setSpacing(Spacing.SM)

            tab_idx = len(self._step_tabs)
            if tab_idx > 0:
                back_btn = _make_btn("← Back", "#3a3a3a")
                back_btn.setMinimumWidth(112)
                back_btn.clicked.connect(
                    lambda _c, i=tab_idx: self._goto_step(i - 1)
                )
                nav_layout.addWidget(back_btn)
            nav_layout.addStretch()
            if tab_idx < len(_tab_defs) - 1:
                next_btn = _make_btn("Next →", "#007acc")
                next_btn.setMinimumWidth(112)
                next_btn.clicked.connect(
                    lambda _c, i=tab_idx: self._advance_step(i)
                )
                nav_layout.addWidget(next_btn)

            page_layout.addWidget(nav)
            self._step_tabs.addTab(page, tab_label)

        self._step_tabs.currentChanged.connect(self._on_step_changed)

        steps_host = QWidget()
        steps_host_layout = QVBoxLayout(steps_host)
        steps_host_layout.setContentsMargins(0, 0, 0, 0)
        steps_host_layout.setSpacing(0)
        steps_host_layout.addWidget(self._step_tabs, 1)

        self.task_progress_row = QWidget()
        progress_layout = QVBoxLayout(self.task_progress_row)
        progress_layout.setContentsMargins(
            Spacing.MD, Spacing.SM, Spacing.MD, Spacing.XS
        )
        progress_layout.setSpacing(Spacing.XS)
        self.task_progress_label = QLabel("")
        self.task_progress_label.setStyleSheet("color:#9d9d9d;font-size:11px;background:transparent;")
        progress_layout.addWidget(self.task_progress_label)
        self.task_progress_bar = QProgressBar()
        self.task_progress_bar.setFixedHeight(16)
        self.task_progress_bar.setTextVisible(True)
        self.task_progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #3c3c3c;
                border-radius: 3px;
                text-align: center;
                background-color: #252526;
                color: #cccccc;
                font-size: 10px;
            }
            QProgressBar::chunk {
                background-color: #007acc;
                border-radius: 2px;
            }
        """)
        progress_layout.addWidget(self.task_progress_bar)
        self.task_progress_row.setVisible(False)
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setFont(QFont("Consolas", 9))
        self._activity_panel = WorkflowActivityPanel(self.log_area)
        self._activity_panel.layout().insertWidget(1, self.task_progress_row)
        self._activity_panel.clear_requested.connect(self.log_area.clear)
        self._activity_panel.collapse_requested.connect(
            lambda: self._set_activity_visible(False)
        )
        self._step_rail.activity_requested.connect(
            lambda: self._set_activity_visible(not self._activity_panel.isVisible())
        )
        self._activity_panel.setVisible(False)

        shell = QHBoxLayout()
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        shell.addWidget(self._step_rail)
        shell.addWidget(steps_host, 1)
        shell.addWidget(self._activity_panel)
        root.addLayout(shell, 1)
        self.setLayout(root)
        self._apply_theme()

    def _set_activity_visible(self, visible: bool) -> None:
        self._activity_panel.setVisible(bool(visible))
        self._step_rail.activity_button.setChecked(bool(visible))

    def _apply_theme(self):
        self.setStyleSheet("""
            QLineEdit {
                background-color: #3c3c3c; border: 1px solid #555555;
                border-radius: 4px; padding: 4px 8px; color: #cccccc; font-size: 13px;
            }
            QLineEdit:focus { border-color: #007acc; }
            QLineEdit:disabled { background-color: #2d2d30; color: #666666; }
            QCheckBox { color: #cccccc; font-size: 13px; spacing: 7px; }
            QCheckBox::indicator {
                width: 14px; height: 14px; border: 1px solid #555555;
                border-radius: 3px; background-color: #3c3c3c;
            }
            QCheckBox::indicator:checked { background-color: #007acc; border-color: #007acc; }
            QCheckBox::indicator:hover { border-color: #007acc; }
            QLabel { color: #cccccc; }
        """)

    # ─────────────────────────────── helpers ─────────────────────────────────

    def _desc(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color:#9d9d9d;font-size:12px;background:transparent;")
        return lbl

    def _page_header(
        self, step: int, title: str, purpose: str, *, optional: bool = False
    ) -> WorkflowPageHeader:
        return WorkflowPageHeader(
            step,
            title,
            purpose,
            optional=optional,
            total_steps=10,
            show_help=False,
        )

    def _subheading(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            "color:#4ec9b0;font-size:13px;font-weight:bold;background:transparent;padding-top:4px;"
        )
        return lbl

    def _register(self, btn: QPushButton) -> QPushButton:
        self._buttons.append(btn)
        return btn

    def _log(self, message: str):
        # Tabs are built before the log panel, so guard against early calls.
        if not hasattr(self, "log_area"):
            return
        self.log_area.append(message)
        sb = self.log_area.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _setting(self, key: str, default=None):
        if self.settings:
            return self.settings.value(f"wolf_workflow/{key}", default)
        return default

    def _save_setting(self, key: str, value):
        if self.settings:
            self.settings.setValue(f"wolf_workflow/{key}", value)

    def _set_busy(self, busy: bool):
        for btn in self._buttons:
            btn.setEnabled(not busy)

    def _show_task_progress(self, current: int, total: int, label: str):
        self.task_progress_row.setVisible(True)
        self.task_progress_label.setText(label)
        if total <= 0:
            self.task_progress_bar.setRange(0, 0)
            self.task_progress_bar.setFormat("")
        else:
            self.task_progress_bar.setRange(0, total)
            self.task_progress_bar.setValue(max(0, min(current, total)))
            self.task_progress_bar.setFormat(f"{current}/{total}  %p%")

    def _hide_task_progress(self):
        self.task_progress_row.setVisible(False)
        self.task_progress_label.clear()
        self.task_progress_bar.setRange(0, 100)
        self.task_progress_bar.setValue(0)
        self.task_progress_bar.setFormat("")

    def _run_task(self, task, on_done=None):
        """Run *task* in a worker thread; disables buttons until it finishes."""
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, "Busy", "A task is already running. Please wait.")
            return
        if self._import_worker is not None and self._import_worker.isRunning():
            QMessageBox.information(self, "Busy", "An import is already running. Please wait.")
            return
        self._set_busy(True)
        self._show_task_progress(0, 0, "Working …")
        worker = _WolfTaskWorker(task)
        self._worker = worker
        worker.log.connect(self._log)
        worker.progress.connect(self._show_task_progress)

        def _finished(ok: bool, msg: str):
            self._hide_task_progress()
            self._set_busy(False)
            if msg:
                self._log(("✅ " if ok else "❌ ") + msg)
            if on_done:
                try:
                    on_done(ok, msg)
                except Exception:
                    pass

        worker.done.connect(_finished)
        # Release the reference and delete the thread object only once the
        # thread has fully stopped. The built-in ``finished`` signal fires
        # after ``run()`` returns, so the QThread is never garbage-collected
        # while still running - which aborts the process with
        # "QThread: Destroyed while thread is still running".
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(self._clear_worker)
        worker.start()

    def _clear_worker(self):
        if self.sender() is self._worker:
            self._worker = None

    # ── Step 0: Project ───────────────────────────────────────────────────────

    def _build_step0(self, layout: QVBoxLayout):
        layout.addWidget(self._page_header(
            0, "Project & Files", "Select the WOLF game and import extracted text files."
        ))
        layout.addWidget(self._desc(
            "Pick the WOLF game root folder (Game.exe plus Data.wolf or a loose Data/ folder). "
            "Detection runs when you browse, press Enter, or reopen this tab. If wolf_json/ does "
            "not exist yet, the tool unpacks .wolf archives when needed and extracts text into "
            f"{WORK_DIR_NAME}/ automatically. Tick the JSON files to import, then leave this step "
            "(or click Import) to copy them into files/ for translation."
        ))

        row0 = QHBoxLayout()
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("Path to game root folder…")
        self.folder_edit.setText(self._setting("last_game_folder", "") or "")
        self.folder_edit.returnPressed.connect(self._detect_folder)
        row0.addWidget(self.folder_edit, 1)
        browse_btn = _make_icon_btn("📁", "Browse for a game project folder")
        browse_btn.clicked.connect(self._browse_folder)
        row0.addWidget(browse_btn)
        layout.addLayout(row0)

        self.detected_label = QLabel("No folder detected yet.")
        self.detected_label.setWordWrap(True)
        self.detected_label.setStyleSheet(
            "color:#6a9a6a;font-size:13px;padding:4px 8px;"
            "background-color:#1f2b1f;border:1px solid #2a4a2a;"
            "border-radius:4px;margin:4px 0;"
        )
        layout.addWidget(self.detected_label)

        self.file_list = CheckableFileList()
        self.file_list.setMinimumHeight(320)
        self.file_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.file_list.setStyleSheet(
            "QListWidget{outline:none;border:1px solid #3c3c3c;"
            "background-color:#252526;border-radius:4px;}"
            "QListWidget::item{border:none;outline:none;padding:2px 6px;"
            "color:#c8c8c8;}"
            "QListWidget::item:selected{background-color:#252526;color:#c8c8c8;}"
            "QListWidget::item:hover{background-color:#2d2d30;"
            "border-left:2px solid #007acc;}"
        )
        layout.addWidget(self.file_list, 1)

        row1 = QHBoxLayout()
        row1.setSpacing(6)
        select_all_btn = _make_text_btn("Select all", "Select all importable files", min_width=96)
        select_all_btn.clicked.connect(self._select_all_files)
        row1.addWidget(select_all_btn)
        deselect_all_btn = _make_text_btn("Clear selection", "Deselect all files", min_width=120)
        deselect_all_btn.clicked.connect(self._deselect_all_files)
        row1.addWidget(deselect_all_btn)
        sel_core = _make_text_btn("Core files", "Select databases, common events, and names", min_width=96)
        sel_core.setToolTip("Select core JSON files; deselect map scripts")
        sel_core.clicked.connect(self._select_core_only)
        row1.addWidget(sel_core)
        equalize_button_widths(
            (select_all_btn, deselect_all_btn, sel_core), minimum=120
        )
        import_btn = _make_text_btn("Import selected files", "Import selected files into files/", min_width=176)
        import_btn.setEnabled(False)
        import_btn.setToolTip("Replace files/ with exactly the checked files above")
        import_btn.clicked.connect(lambda _checked=False: self._import_files())
        self._register_import_button(import_btn)
        row1.addWidget(import_btn)
        row1.addStretch()
        layout.addLayout(row1)

    @staticmethod
    def _task_box_style() -> str:
        return (
            "QWidget#tbox{"
            "background-color:#252526;"
            "border:1px solid #3c3c3c;"
            "border-radius:6px;}"
        )

    def _build_step1_preprocess(self, layout: QVBoxLayout):
        layout.addWidget(self._page_header(
            1, "Prepare Project", "Optionally format extracted data and install GameUpdate.",
            optional=True,
        ))

        header_row = QHBoxLayout()
        header_row.addWidget(self._desc(
            "Optional preparation before translating. Paths auto-fill when a project folder "
            "is detected in Step 0."
        ))
        header_row.addStretch()
        layout.addLayout(header_row)

        hint = QLabel(
            "Format extracted JSON for clean git diffs, then copy the gameupdate/ patch "
            "files into the game root for git tracking."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#9d9d9d;font-size:13px;padding-bottom:6px;")
        layout.addWidget(hint)

        tasks_box = QGroupBox()
        tasks_box.setStyleSheet("QGroupBox{border:none;margin:0;padding:4px 0;}")
        tb = QVBoxLayout(tasks_box)
        tb.setSpacing(10)
        layout.addWidget(tasks_box)

        ta_title = QLabel("A — Format JSON files (dazedformat)")
        ta_title.setStyleSheet("color:#4ec9b0;font-size:13px;font-weight:bold;")
        tb.addWidget(ta_title)
        ta = QWidget()
        ta.setObjectName("tbox")
        ta.setStyleSheet(self._task_box_style())
        ta_inner = QVBoxLayout(ta)
        ta_inner.setContentsMargins(10, 8, 10, 8)
        ta_inner.setSpacing(4)
        ta_desc = QLabel(
            "Normalises JSON in the game's wolf_json/ folder and the tool's files/ folder "
            "by round-tripping through json.load / json.dump (indent 4). Bundled — no install."
        )
        ta_desc.setWordWrap(True)
        ta_desc.setStyleSheet("color:#9d9d9d;font-size:13px;")
        ta_inner.addWidget(ta_desc)
        ta_path_row = QHBoxLayout()
        ta_path_row.addWidget(QLabel("wolf_json/:"))
        self.pp_wolf_json_label = QLabel("(detect a project folder first)")
        self.pp_wolf_json_label.setStyleSheet("color:#7a7a7a;font-size:13px;")
        ta_path_row.addWidget(self.pp_wolf_json_label, 1)
        ta_inner.addLayout(ta_path_row)
        ta_btn_row = QHBoxLayout()
        run_dazed = _make_btn("Format extracted data", "#555")
        run_dazed.setFixedWidth(180)
        run_dazed.clicked.connect(self._run_dazedformat)
        ta_btn_row.addWidget(run_dazed)
        ta_btn_row.addStretch()
        ta_inner.addLayout(ta_btn_row)
        tb.addWidget(ta)

        tc_title = QLabel("B — Apply gameupdate/ patch files")
        tc_title.setStyleSheet("color:#4ec9b0;font-size:13px;font-weight:bold;")
        tb.addWidget(tc_title)
        tc = QWidget()
        tc.setObjectName("tbox")
        tc.setStyleSheet(self._task_box_style())
        tc_inner = QVBoxLayout(tc)
        tc_inner.setContentsMargins(10, 8, 10, 8)
        tc_inner.setSpacing(4)
        tc_desc = QLabel(
            "Copies everything from the gameupdate/ folder into the game's root folder, "
            "overwriting existing files (updater scripts, patch scripts, .gitignore, "
            "and UberWolfCli.exe). Writes patch-config.txt from Config → Game Update "
            "defaults (set your org once there; edit repo= per game)."
        )
        tc_desc.setWordWrap(True)
        tc_desc.setStyleSheet("color:#9d9d9d;font-size:13px;")
        tc_inner.addWidget(tc_desc)
        tc_src_row = QHBoxLayout()
        tc_src_row.addWidget(QLabel("Source:"))
        self.pp_gameupdate_edit = QLineEdit()
        self.pp_gameupdate_edit.setPlaceholderText("Path to gameupdate/ folder…")
        tc_src_row.addWidget(self.pp_gameupdate_edit, 1)
        browse_gu = _make_btn("", "#444")
        browse_gu.setIcon(browse_gu.style().standardIcon(QStyle.SP_DirOpenIcon))
        browse_gu.setFixedWidth(34)
        browse_gu.clicked.connect(self._browse_gameupdate)
        tc_src_row.addWidget(browse_gu)
        tc_inner.addLayout(tc_src_row)
        tc_dst_row = QHBoxLayout()
        tc_dst_row.addWidget(QLabel("Destination:"))
        self.pp_gameupdate_dst_label = QLabel("(game root folder auto-filled from project)")
        self.pp_gameupdate_dst_label.setStyleSheet("color:#7a7a7a;font-size:13px;")
        tc_dst_row.addWidget(self.pp_gameupdate_dst_label, 1)
        tc_inner.addLayout(tc_dst_row)
        tc_btn_row = QHBoxLayout()
        tc_btn_row.setSpacing(8)
        run_gu = _make_btn("Install GameUpdate", "#555")
        run_gu.setFixedWidth(180)
        run_gu.clicked.connect(self._run_gameupdate)
        tc_btn_row.addWidget(run_gu)
        run_all_btn = _make_btn("Run available tasks", "#007acc")
        run_all_btn.setFixedWidth(180)
        run_all_btn.setToolTip("Run dazedformat, then copy gameupdate/")
        run_all_btn.clicked.connect(self._run_all_preprocess)
        tc_btn_row.addWidget(run_all_btn)
        tc_btn_row.addStretch()
        tc_inner.addLayout(tc_btn_row)
        tb.addWidget(tc)

    def _register_import_button(self, button: QPushButton) -> None:
        self._import_buttons.append(button)

    def _set_import_buttons_enabled(self, enabled: bool) -> None:
        for button in self._import_buttons:
            button.setEnabled(enabled)

    def _browse_folder(self):
        start = self.folder_edit.text() or self._setting("last_game_folder", "") or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Select Game Root Folder", start)
        if folder:
            self.folder_edit.setText(folder)
            self._save_setting("last_game_folder", folder)
            self._detected_on_show = True
            self._ask_clear_old_files()
            self._detect_folder()

    def _ask_clear_old_files(self):
        """Prompt to clear files/ and translated/ when switching games."""
        msg = QMessageBox(self)
        msg.setWindowTitle("Clear Previous Translation Data?")
        msg.setText(
            "Do you want to clear the <b>files/</b> and <b>translated/</b> folders?\n\n"
            "This is recommended when switching to a new game project to avoid "
            "old translations conflicting with the new one."
        )
        msg.setIcon(QMessageBox.Question)
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg.setDefaultButton(QMessageBox.Yes)
        if msg.exec_() != QMessageBox.Yes:
            return

        base = Path(__file__).resolve().parent.parent
        cleared = 0
        errors: list[str] = []
        for folder_name in ("files", "translated"):
            target = base / folder_name
            if not target.is_dir():
                continue
            for child in target.iterdir():
                if child.name == ".gitkeep":
                    continue
                try:
                    if child.is_dir():
                        shutil.rmtree(child)
                    else:
                        child.unlink()
                    cleared += 1
                except Exception as exc:
                    errors.append(f"{child.name}: {exc}")
        if cleared:
            self._log(f"🗑  Cleared {cleared} item(s) from files/ and translated/.")
        else:
            self._log("ℹ  files/ and translated/ were already empty.")
        for err in errors:
            self._log(f"⚠  Could not remove {err}")

    def _detect_folder(self):
        folder = self.folder_edit.text().strip()
        if not folder:
            self._log("⚠  No folder path entered.")
            return
        if not Path(folder).is_dir():
            self.detected_label.setText("❌ Folder not found. Pick a valid game directory.")
            self.detected_label.setStyleSheet(
                "color:#f48771;font-size:13px;padding:4px 8px;"
                "background-color:#2b1a1a;border:1px solid #5a2a2a;"
                "border-radius:4px;margin:4px 0;"
            )
            return

        self._save_setting("last_game_folder", folder)
        self._game_root = folder
        if hasattr(self, "setup_editors"):
            self.setup_editors.reload_all()
        self.detected_label.setText("Scanning…")
        self.detected_label.setStyleSheet(
            "color:#9d9d9d;font-size:13px;padding:4px 8px;"
            "background-color:#252526;border:1px solid #3c3c3c;"
            "border-radius:4px;margin:4px 0;"
        )
        self.file_list.clear()
        self._set_import_buttons_enabled(False)
        self._last_import_signature = None
        self._pending_import_signature = None

        info = detect_wolf_layout(folder)
        self._layout = info

        if info["engine"] != "WOLF":
            self.detected_label.setText(
                "⚠  No WOLF layout found (no .wolf archives or loose Data/ with maps/CommonEvent.dat)."
            )
            self.detected_label.setStyleSheet(
                "color:#e9a12a;font-size:13px;padding:4px 8px;"
                "background-color:#2b2010;border:1px solid #5a4010;"
                "border-radius:4px;margin:4px 0;"
            )
            self._log(f"Detect: no WOLF layout found in {folder}")
            return

        parts = [f"Engine: WOLF   ·   Game root: {folder}"]
        if info.get("unpacked"):
            parts.append(f"Data/: {info['data_dir']}")
        archives = info.get("archives") or []
        if archives:
            parts.append(f"{len(archives)} .wolf archive(s)")
        self.detected_label.setText("\n".join(parts))
        self.detected_label.setStyleSheet(
            "color:#6a9a6a;font-size:13px;padding:4px 8px;"
            "background-color:#1f2b1f;border:1px solid #2a4a2a;"
            "border-radius:4px;margin:4px 0;"
        )
        self._log("Detect: " + " | ".join(parts))
        self._populate_preprocess_paths()
        QTimer.singleShot(50, self._ensure_wolf_json)

    def _ensure_wolf_json(self):
        """Create wolf_json/ when missing (unpack + extract), then refresh the import list."""
        if not self._game_root:
            return
        if self._worker is not None and self._worker.isRunning():
            return

        info = self._layout or detect_wolf_layout(self._game_root)
        self._layout = info
        gaps = info.get("unpack_gaps") or []
        if gaps or (info.get("archives") and not info.get("unpacked")):
            pending = gaps or info.get("archives") or []
            self._log(f"Auto-setup: unpacking {len(pending)} archive(s) …")
            self._unpack(
                on_done=self._on_auto_unpack_done,
                interactive=False,
                archives=pending,
            )
            return

        manifest = self._read_manifest()
        if manifest and manifest.get("entries"):
            info = self._layout or detect_wolf_layout(self._game_root)
            data_dir = info.get("data_dir")
            has_map_entries = any(e.get("kind") == "map" for e in manifest["entries"])
            if (
                not has_map_entries
                and data_dir
                and (
                    wolf_maps_packed(self._game_root, data_dir)
                    or wolf_has_maps(data_dir)
                )
            ):
                self._log(
                    "Auto-setup: maps missing from wolf_json/ — unpacking MapData if needed "
                    "and extracting map files …"
                )
                self._extract_to_work_dir(
                    supplement_maps=True,
                    on_done=lambda ok, _m: self._scan_wolf_files() if ok else None,
                )
                return
            self._scan_wolf_files()
            return

        if info.get("data_dir"):
            self._log("Auto-setup: extracting text into wolf_json/ …")
            self._extract_to_work_dir(on_done=lambda ok, _m: self._scan_wolf_files() if ok else None)
            return
        self._log("⚠  No unpacked Data/ folder and no .wolf archives to unpack.")

    def _on_auto_unpack_done(self, ok: bool, _msg: str):
        if not ok:
            return
        self._layout = detect_wolf_layout(self._game_root)
        gaps = self._layout.get("unpack_gaps") or []
        if gaps:
            names = ", ".join(a.name for a in gaps)
            self._log(f"⚠  Unpack still incomplete: {names}")
            return
        if self._layout.get("data_dir"):
            self._log("Auto-setup: extracting text into wolf_json/ …")
            self._extract_to_work_dir(on_done=lambda ok2, _m: self._scan_wolf_files() if ok2 else None)

    def _scan_wolf_files(self):
        if not self._game_root:
            return
        work_dir = self._work_dir()
        manifest = self._read_manifest()
        if not manifest or not manifest.get("entries"):
            self.file_list.clear()
            self._set_import_buttons_enabled(False)
            return

        items = list_wolf_json_files(work_dir, manifest)
        self._file_items = items
        self.file_list.clear()
        from gui.qt_icons import file_category_icon

        for item in items:
            cat = item["category"]
            lw = QListWidgetItem(f"{item['name']}  ({item['size_kb']:.1f} KB)")
            lw.setIcon(file_category_icon(cat))
            lw.setData(Qt.UserRole, item)
            lw.setFlags(lw.flags() | Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
            lw.setCheckState(Qt.Checked if item["default"] else Qt.Unchecked)
            if cat == "core":
                lw.setForeground(QColor("#9cdcfe"))
            elif cat == "map":
                lw.setForeground(QColor("#c5c5c0"))
            self.file_list.addItem(lw)

        self._set_import_buttons_enabled(bool(items))
        self._populate_preprocess_paths()
        self._log(f"Found {len(items)} importable file(s) in {WORK_DIR_NAME}/.")
        if items:
            self._log("Checked files import into files/ when you leave Step 0 or click 📥.")

    def _select_all_files(self):
        if not self.file_list.count():
            return
        self._syncing_file_checks = True
        try:
            for i in range(self.file_list.count()):
                self.file_list.item(i).setCheckState(Qt.Checked)
        finally:
            self._syncing_file_checks = False

    def _deselect_all_files(self):
        if not self.file_list.count():
            return
        self._syncing_file_checks = True
        try:
            for i in range(self.file_list.count()):
                self.file_list.item(i).setCheckState(Qt.Unchecked)
        finally:
            self._syncing_file_checks = False

    def _select_core_only(self):
        self._syncing_file_checks = True
        try:
            for i in range(self.file_list.count()):
                item = self.file_list.item(i)
                data = item.data(Qt.UserRole)
                is_core = bool(data and data.get("category") == "core")
                item.setCheckState(Qt.Checked if is_core else Qt.Unchecked)
        finally:
            self._syncing_file_checks = False

    def _selected_import_items(self) -> list[dict]:
        selected = []
        for i in range(self.file_list.count()):
            lw = self.file_list.item(i)
            if lw.checkState() == Qt.Checked:
                selected.append(lw.data(Qt.UserRole))
        return selected

    def _import_signature(self, selected: list[dict] | None = None) -> tuple[str, ...]:
        selected = selected if selected is not None else self._selected_import_items()
        return tuple(sorted(str(item.get("name", "")) for item in selected if item))

    def _auto_import_if_needed(self) -> None:
        selected = self._selected_import_items()
        signature = self._import_signature(selected)
        if not signature:
            return
        if signature in (self._last_import_signature, self._pending_import_signature):
            return
        self._log("Auto-importing checked project files into files/ before leaving Project.")
        self._import_files(confirm=False, selected=selected, signature=signature)

    def _import_files(
        self,
        confirm: bool = True,
        selected: list[dict] | None = None,
        signature: tuple[str, ...] | None = None,
    ):
        selected = selected if selected is not None else self._selected_import_items()
        if not selected:
            self._log("⚠  No files selected.")
            return

        signature = signature if signature is not None else self._import_signature(selected)
        if self._pending_import_signature == signature:
            self._log("ℹ  Import for the current selection is already running.")
            return

        if confirm and not self._confirm_import_overwrite(selected):
            self._log("ℹ  Import cancelled; files/ was left unchanged.")
            return

        self._set_import_buttons_enabled(False)
        self._pending_import_signature = signature
        worker = _ImportWorker(selected, "files")
        worker.log.connect(self._log)
        worker.done.connect(self._on_import_done)
        self._import_worker = worker
        worker.start()

    def _confirm_import_overwrite(self, selected: list[dict]) -> bool:
        files_dir = Path("files")
        existing = [
            item for item in files_dir.iterdir()
            if item.name != ".gitkeep"
        ] if files_dir.exists() else []
        if not existing:
            return True
        reply = QMessageBox.warning(
            self,
            "Import game files",
            "Importing selected game files will delete the existing contents of files/ "
            "before copying the new files.\n\n"
            f"Existing items: {len(existing)}\n"
            f"Selected files to import: {len(selected)}\n\n"
            "Continue and overwrite files/?",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        return reply == QMessageBox.Yes

    def _on_import_done(self, count: int, errors: list):
        self._set_import_buttons_enabled(bool(self.file_list.count()))
        if errors:
            self._log(f"⚠  {len(errors)} error(s) during import:")
            for e in errors[:10]:
                self._log(f"   {e}")
        else:
            self._last_import_signature = self._pending_import_signature
        self._pending_import_signature = None
        self._log(f"✅ Imported {count} file(s) into files/")
        # Step 4 discovery scans files/; refresh if we're already on Database
        # (auto-import from Step 0 often finishes after the first discovery pass).
        if getattr(self, "_current_step_index", None) == 4:
            self._refresh_db_discovery()

    def _populate_preprocess_paths(self):
        game_root = self.folder_edit.text().strip()
        work_dir = str(self._work_dir()) if self._game_root else ""
        if hasattr(self, "pp_wolf_json_label"):
            self.pp_wolf_json_label.setText(work_dir or "(no wolf_json/ yet — detect in Step 0)")
        self._gameupdate_path = str(PROJECT_ROOT / "gameupdate")
        if hasattr(self, "pp_gameupdate_edit"):
            self.pp_gameupdate_edit.setText(self._gameupdate_path)
        if hasattr(self, "pp_gameupdate_dst_label"):
            self.pp_gameupdate_dst_label.setText(game_root or "(no game folder detected)")

    def _browse_gameupdate(self):
        start = self.pp_gameupdate_edit.text() or self.folder_edit.text()
        folder = QFileDialog.getExistingDirectory(self, "Select gameupdate folder", start)
        if folder:
            self.pp_gameupdate_edit.setText(folder)

    def _run_dazedformat(self):
        if not self._game_root:
            self._log("⚠  No game folder set. Complete Step 0 first.")
            return
        work_dir = self._work_dir()
        files_dir = Path("files")

        def task(log, progress=None):
            from util.dazedformat import format_json_files

            total = 0
            errors: list[str] = []
            for label, d in ((f"{WORK_DIR_NAME}/", work_dir), ("files/", files_dir)):
                if not Path(d).is_dir():
                    continue
                log(f"Formatting JSON in {label} …")
                count, errs = format_json_files(d, log=log)
                total += count
                errors.extend(errs)
            if errors:
                return False, f"dazedformat: {total} formatted, {len(errors)} error(s)."
            if total == 0:
                return False, "No JSON files found to format."
            return True, f"dazedformat: {total} file(s) formatted successfully."

        self._run_task(task)

    def _write_gameupdate_patch_config(self, game_root: str):
        """Write gameupdate/patch-config.txt from Config → Game Update defaults."""
        from util.gameupdate_config import write_patch_config

        ok, msg = write_patch_config(game_root)
        if ok:
            self._log(f"📝 Wrote patch-config.txt from Config defaults → {msg}")
        else:
            self._log(f"ℹ  patch-config.txt: {msg}")

    def _run_gameupdate(self):
        src = self.pp_gameupdate_edit.text().strip()
        dst = self.folder_edit.text().strip()
        if not src:
            self._log("⚠  No gameupdate folder path set.")
            return
        if not dst:
            self._log("⚠  No game root folder set. Complete Step 0 first.")
            return
        if not Path(src).is_dir():
            self._log(f"⚠  gameupdate folder not found: {src}")
            return
        w = _FileCopyWorker(src, dst, skip_names=_GAMEUPDATE_COPY_SKIP_NAMES)
        w.log.connect(self._log)
        w.done.connect(self._on_gameupdate_done)
        self._import_worker = w  # reuse slot; not WolfTaskWorker
        w.start()

    def _on_gameupdate_done(self, count: int, errors: list):
        self._log(f"✅ gameupdate: copied {count} file(s).")
        for e in errors:
            self._log(f"   ⚠  {e}")
        dst = self.folder_edit.text().strip()
        if dst and not errors:
            self._write_gameupdate_patch_config(dst)

    def _run_all_preprocess(self):
        if not self._game_root:
            self._log("⚠  No game folder set. Complete Step 0 first.")
            return

        def task(log, progress=None):
            from util.dazedformat import format_json_files

            work_dir = self._work_dir()
            files_dir = Path("files")
            total = 0
            errors: list[str] = []
            for label, d in ((f"{WORK_DIR_NAME}/", work_dir), ("files/", files_dir)):
                if not Path(d).is_dir():
                    log(f"  ⏭  Skipped dazedformat on {label} (folder missing)")
                    continue
                log(f"[A] Formatting JSON in {label} …")
                count, errs = format_json_files(d, log=log)
                total += count
                errors.extend(errs)
            if errors:
                return False, f"Pre-process: formatted {total} file(s), {len(errors)} error(s)."

            src = self.pp_gameupdate_edit.text().strip()
            dst = self.folder_edit.text().strip()
            if not src or not Path(src).is_dir():
                log("  ⏭  Skipped gameupdate copy (source not found)")
            elif not dst:
                log("  ⏭  Skipped gameupdate copy (no game root)")
            else:
                log("[B] Copying gameupdate/ …")
                copied = 0
                for fp in sorted(Path(src).rglob("*")):
                    if not fp.is_file():
                        continue
                    if fp.name in _GAMEUPDATE_COPY_SKIP_NAMES:
                        log(f"  skipped {fp.relative_to(src)}")
                        continue
                    rel = fp.relative_to(src)
                    target = Path(dst) / rel
                    try:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(fp, target)
                        copied += 1
                    except Exception as exc:
                        errors.append(f"{rel}: {exc}")
                log(f"  Copied {copied} gameupdate file(s).")
                from util.gameupdate_config import write_patch_config

                ok, msg = write_patch_config(dst)
                if ok:
                    log(f"  Wrote patch-config.txt from Config defaults → {msg}")
                else:
                    log(f"  patch-config.txt: {msg}")
            if errors:
                return False, "Pre-process finished with errors (see log)."
            return True, "Pre-process: dazedformat and gameupdate copy finished."

        self._run_task(task)

    def _unpack(self, on_done=None, *, interactive: bool = True, archives=None):
        if not self._require_root():
            return
        root = Path(self._game_root)
        info = detect_wolf_layout(root)
        if archives is None:
            gaps = info.get("unpack_gaps") or find_wolf_unpack_gaps(root)
            archives = gaps if gaps else info["archives"]
        if not archives:
            self._log("Unpack: no .wolf archives found (already unpacked?).")
            if interactive:
                QMessageBox.information(self, "Unpack", "No .wolf archives found to unpack.")
            return
        root = Path(self._game_root)

        def task(log, progress=None):
            from collections import defaultdict

            from util import wolfdawn

            groups: dict[Path, list[Path]] = defaultdict(list)
            for arc in archives:
                groups[wolf_unpack_out_dir(root, arc)].append(arc)

            total = len(archives)
            done = 0
            for target, group in groups.items():
                log(f"Unpacking {len(group)} archive(s) into {target} …")
                res = wolfdawn.unpack_all(
                    [str(a) for a in group],
                    str(target),
                    log_fn=log,
                    progress_fn=(
                        (lambda c, _t, label, base=done: progress(base + min(c, 1), total, label))
                        if progress
                        else None
                    ),
                    progress_total=len(group),
                )
                done += len(group)
                if progress:
                    progress(done, total, f"Unpacked {len(group)} archive(s)")
                if not res.ok:
                    return False, f"unpack-all exited {res.returncode}"
            wolf_repair_nested_data_dir(root)
            return True, "Unpacked archives into Data/."

        self._run_task(task, on_done=on_done)

    def _ensure_text_archives_unpacked(self, data_dir: Path, log, progress=None) -> bool:
        """Unpack BasicData/MapData archives when their binaries are not loose yet."""
        from util import wolfdawn

        archives = find_wolf_text_archives(self._game_root, data_dir)
        pending: list[Path] = []
        basic = data_dir / "BasicData"
        if "BasicData" in archives and not (basic / "CommonEvent.dat").is_file():
            pending.append(archives["BasicData"])
        if "MapData" in archives and not wolf_has_maps(data_dir):
            pending.append(archives["MapData"])
        if not pending:
            return True

        ok = True
        total = len(pending)
        for idx, arc in enumerate(pending):
            if progress:
                progress(idx, total, f"Unpacking {arc.name} ({idx + 1}/{total}) …")
            log(f"Unpacking {arc.name} …")

            def scoped_progress(current, _total, label, base=idx, archive=arc):
                if not progress:
                    return
                step = min(current, 1)
                detail = label or archive.name
                progress(base + step, total, detail)

            res = wolfdawn.unpack_all(
                [str(arc)],
                str(data_dir),
                log_fn=log,
                progress_fn=scoped_progress if progress else None,
                progress_total=1,
            )
            if not res.ok:
                log(f"  ⚠ unpack failed (exit {res.returncode})")
                ok = False
            elif progress:
                progress(idx + 1, total, f"Unpacked {arc.name}")
        return ok

    def _extract_to_work_dir(
        self, *, interactive: bool = True, on_done=None, supplement_maps: bool = False
    ):
        if not self._require_root():
            return
        info = detect_wolf_layout(self._game_root)
        self._layout = info
        data_dir = info.get("data_dir")
        if not data_dir:
            if interactive:
                QMessageBox.warning(
                    self, "Extract",
                    "No unpacked Data/ folder found. Run unpack first.",
                )
            else:
                self._log("Extract: no unpacked Data/ folder found.")
            return

        work_dir = self._work_dir()
        game_root = self._game_root

        def task(log, progress=None):
            from util import wolfdawn

            if not self._ensure_text_archives_unpacked(Path(data_dir), log, progress):
                return False, "Could not unpack text archives (see log)."

            layout = detect_wolf_layout(self._game_root)
            self._layout = layout
            basic = Path(layout["basic_data"]) if layout.get("basic_data") else Path(data_dir)
            maps_dir = wolf_maps_dir(data_dir)
            work_dir.mkdir(parents=True, exist_ok=True)

            existing_manifest = self._read_manifest() if supplement_maps else None
            existing_entries = list(existing_manifest.get("entries", [])) if existing_manifest else []
            existing_json = {e["json"] for e in existing_entries if e.get("json")}

            manifest_entries: list[dict] = (
                existing_entries.copy() if supplement_maps else []
            )

            def _extract_one(base: Path, out_name: str, kind: str):
                if supplement_maps and out_name in existing_json:
                    return
                out = work_dir / out_name
                log(f"Extracting {base.name} …")
                res = wolfdawn.strings_extract(str(base), str(out), log_fn=log)
                if res.ok and out.is_file():
                    manifest_entries.append({"json": out_name, "base": str(base), "kind": kind})
                else:
                    log(f"  ⚠ skipped {base.name} (exit {res.returncode})")

            if not supplement_maps:
                ce = basic / "CommonEvent.dat"
                if ce.is_file():
                    _extract_one(ce, "CommonEvent.dat.json", "common")
                for stem in ("DataBase", "CDataBase", "SysDatabase"):
                    proj = basic / f"{stem}.project"
                    if proj.is_file():
                        _extract_one(proj, f"{stem}.project.json", "db")
                gd = basic / "Game.dat"
                if gd.is_file():
                    _extract_one(gd, "Game.dat.json", "gamedat")

            for mps in sorted(maps_dir.glob("*.mps")):
                _extract_one(mps, f"{mps.name}.json", "map")

            if not supplement_maps:
                evtext = Path(data_dir) / "Evtext"
                if evtext.is_dir() and any(evtext.glob("*.txt")):
                    out = work_dir / "Evtext.json"
                    log("Extracting Evtext/ …")
                    res = wolfdawn.strings_extract(str(evtext), str(out), log_fn=log)
                    if res.ok and out.is_file():
                        manifest_entries.append({"json": "Evtext.json", "base": str(evtext), "kind": "txt-dir"})

                log("Extracting name list …")
                names_out = work_dir / NAMES_JSON
                res = wolfdawn.names_extract(str(data_dir), str(names_out), log_fn=log)
                if res.ok and names_out.is_file():
                    manifest_entries.append({"json": NAMES_JSON, "base": str(data_dir), "kind": "names"})
            elif any(e.get("kind") == "map" for e in manifest_entries):
                log("Refreshing name list (maps were added) …")
                names_out = work_dir / NAMES_JSON
                res = wolfdawn.names_extract(str(data_dir), str(names_out), log_fn=log)
                if res.ok and names_out.is_file():
                    manifest_entries = [
                        e for e in manifest_entries if e.get("json") != NAMES_JSON
                    ]
                    manifest_entries.append({"json": NAMES_JSON, "base": str(data_dir), "kind": "names"})

            new_entries = [
                e for e in manifest_entries
                if supplement_maps and e.get("json") not in existing_json
            ] if supplement_maps else manifest_entries

            if not manifest_entries:
                return False, "Nothing was extracted. Check the Data/ folder layout."
            if supplement_maps and not new_entries:
                return True, f"No new map files to extract in {WORK_DIR_NAME}/."

            manifest = {
                "root": game_root,
                "data_dir": str(data_dir),
                "entries": manifest_entries,
            }
            (work_dir / MANIFEST_NAME).write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            snapshot_entries = new_entries if supplement_maps else manifest_entries
            self._snapshot_originals(snapshot_entries, Path(data_dir), log)
            map_count = sum(1 for e in manifest_entries if e.get("kind") == "map")
            if supplement_maps:
                added = sum(1 for e in new_entries if e.get("kind") == "map")
                return True, (
                    f"Added {added} map file(s) ({map_count} total in {WORK_DIR_NAME}/). "
                    "Import checked files into files/ from Step 0."
                )
            return True, (
                f"Extracted {len(manifest_entries)} document(s) into {WORK_DIR_NAME}/ "
                f"({map_count} map(s)). Import checked files into files/ from Step 0."
            )

        self._run_task(task, on_done=on_done)

    # ── Step 2: Setup ──────────────────────────────────────────────────────────

    def _build_step2_setup(self, layout: QVBoxLayout):
        layout.addWidget(self._page_header(
            2, "Speakers & Guidance", "Configure speaker handling and maintain project guidance."
        ))
        layout.addWidget(self._desc(
            "Copy Project Setup into Cursor/Copilot with files/ open. Paste the glossary block into the Glossary tab, "
            "quirks into Quirks, game_skill into Game skills. Speakers advice (LOWCONF_FIRSTLINE) "
            "is applied via the Step 5 checkbox - keep that step self-contained."
        ))

        actions = QHBoxLayout()
        actions.setSpacing(8)
        copy_btn = _make_btn("Copy setup skill", "#555")
        copy_btn.setFixedWidth(190)
        copy_btn.setFixedHeight(32)
        copy_btn.setToolTip(
            "Clipboard skill for the game repo IDE. Returns glossary, speakers, "
            "translation_quirks, and game_skill code blocks."
        )
        copy_btn.clicked.connect(self._copy_project_setup_prompt)
        actions.addWidget(copy_btn)
        actions.addStretch()
        layout.addLayout(actions)

        note = self._desc(
            "Do not list names.json item/skill/enemy values in the Glossary - Phase 0 "
            "(Step 3) harvests those. Focus the Glossary on characters and worldbuilding."
        )
        layout.addWidget(note)

        self.setup_editors = SetupSkillsEditors(
            self,
            game_root_fn=lambda: self.folder_edit.text().strip() or self._game_root,
            log_fn=self._log,
        )
        layout.addWidget(self.setup_editors, 1)
        self.setup_editors.reload_all()

    def _copy_project_setup_prompt(self):
        """Copy the Wolf Project Setup skill, optionally prepending known vocab speakers."""
        try:
            speakers = self._read_vocab_speakers()
            prepend = ""
            if speakers:
                speaker_lines = "\n".join(f"  {orig} ({tl})" for orig, tl in speakers)
                prepend = (
                    "<known_speakers>\n"
                    "These character names were already listed in the Glossary (vocab.txt).\n"
                    "For the glossary block '# Game Characters', prefer entries for these names, "
                    "then cross-check DataBase*.project.json and dialogue for other major names.\n"
                    "\n"
                    + speaker_lines
                    + "\n</known_speakers>\n"
                )
            prompt = load_project_setup("wolf", prepend=prepend)
            QApplication.clipboard().setText(prompt)
            self._log("📋 Project Setup skill copied. Paste it into Cursor/Copilot with files/ open.")
        except Exception as exc:
            self._log(f"❌ Could not load Project Setup skill: {exc}")

    def _read_vocab_speakers(self) -> list[tuple[str, str]]:
        """Parse '# Speakers' (or '# Game Characters') from vocab.txt as (orig, tl) pairs."""
        vocab_path = VOCAB_PATH
        if not vocab_path.exists():
            return []
        try:
            content = vocab_path.read_text(encoding="utf-8")
        except Exception:
            return []

        results = []
        for header in (r"Speakers", r"Game Characters"):
            m = re.search(
                rf"^[	 ]*#\s*{header}\s*$\r?\n(.*?)(?=^[	 ]*#|\Z)",
                content,
                re.MULTILINE | re.DOTALL,
            )
            if not m:
                continue
            for line in m.group(1).splitlines():
                line = line.strip()
                if not line:
                    continue
                pm = re.match(r"^(.+?)\s+\((.+?)\)", line)
                if pm:
                    pair = (pm.group(1), pm.group(2))
                    if pair not in results:
                        results.append(pair)
            if results:
                break
        return results

    # ── Step 4: Database ───────────────────────────────────────────────────────

    def _build_step4_database(self, layout: QVBoxLayout):
        layout.setSpacing(6)
        title = self._page_header(
            4, "Translate Database", "Translate foundation data before narrative database sheets."
        )
        title.setToolTip(
            "WOLF database files (DataBase, CDataBase, SysDatabase) hold item/skill "
            "descriptions in classic RPG games, but many games store most dialogue in "
            "custom database sheets instead of maps. Review discovery, then translate "
            "foundation sheets (items, skills, system text) before narrative custom sheets."
        )
        layout.addWidget(title)
        layout.addWidget(self._desc(
            "Review discovery → tick sheets → translate foundation first, then narrative."
        ))

        self.db_discovery_label = QLabel(
            "Open this step after extraction to see where this game's text lives."
        )
        self.db_discovery_label.setWordWrap(True)
        self.db_discovery_label.setStyleSheet(
            "color:#9cdcfe;font-size:12px;padding:6px 8px;"
            "background-color:#1a2430;border:1px solid #2a4a6a;border-radius:4px;"
        )
        layout.addWidget(self.db_discovery_label)

        disc_row = QHBoxLayout()
        disc_row.setSpacing(6)
        refresh_disc_btn = _make_btn("Refresh analysis", "#555")
        refresh_disc_btn.setToolTip("Re-scan files/ for database / map / CommonEvent line counts.")
        refresh_disc_btn.clicked.connect(self._refresh_db_discovery)
        audit_btn = _make_btn("Copy database audit", "#5a3a7a")
        audit_btn.setToolTip("Copy a DB structure prompt for Cursor/Copilot to audit sheet roles.")
        audit_btn.clicked.connect(self._copy_db_audit_prompt)
        import_btn = _make_btn("Import database profile", "#3a3a3a")
        import_btn.setToolTip("Paste JSON returned by the AI audit into db_profile.json.")
        import_btn.clicked.connect(self._import_db_profile_dialog)
        disc_row.addWidget(refresh_disc_btn)
        disc_row.addWidget(audit_btn)
        disc_row.addWidget(import_btn)
        disc_row.addStretch()
        layout.addLayout(disc_row)

        self._db_groups_list = CheckableFileList()
        self._db_groups_list.setMinimumHeight(160)
        self._db_groups_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._db_groups_list.setStyleSheet(
            "QListWidget{background-color:#252526;border:1px solid #3a3a3a;border-radius:4px;"
            "color:#cccccc;font-size:12px;padding:1px;}"
            "QListWidget::item{padding:2px 4px;}"
            "QListWidget::item:selected{background:#264f78;color:#ffffff;}"
        )
        self._db_groups_list.itemChanged.connect(self._save_db_profile_from_ui)
        self._db_groups_list.setToolTip(
            "Each sheet is foundation (translate first), system, or narrative "
            "(custom dialogue - defer until foundation is done). Tick sheets for "
            "the next database translation run."
        )
        layout.addWidget(self._db_groups_list, 1)

        grp_row = QHBoxLayout()
        grp_row.setSpacing(6)
        sel_found_btn = _make_btn("Select foundation", "#3a3a3a")
        sel_found_btn.clicked.connect(self._select_db_foundation_groups)
        sel_narr_btn = _make_btn("Select narrative", "#3a3a3a")
        sel_narr_btn.clicked.connect(self._select_db_narrative_groups)
        sel_all_db_btn = _make_btn("Select all", "#3a3a3a")
        sel_all_db_btn.clicked.connect(lambda: self._set_db_group_checks(True))
        sel_none_db_btn = _make_btn("Select none", "#3a3a3a")
        sel_none_db_btn.clicked.connect(lambda: self._set_db_group_checks(False))
        grp_row.addWidget(sel_found_btn)
        grp_row.addWidget(sel_narr_btn)
        grp_row.addWidget(sel_all_db_btn)
        grp_row.addWidget(sel_none_db_btn)
        grp_row.addStretch()
        layout.addLayout(grp_row)

        self._add_tl_mode_selector(layout)

        tl_row = QHBoxLayout()
        tl_row.setSpacing(6)
        found_btn = self._register(_make_btn("Translate foundation database", "#00a86b"))
        found_btn.setToolTip(
            "Translate foundation/system sheets (items, skills, system text). "
            "Run after Step 3 (names). Re-running skips lines already translated."
        )
        found_btn.clicked.connect(
            lambda: self._translate_db_tiers(wolf_db.FOUNDATION_TIERS, auto_start=True)
        )
        narr_btn = self._register(_make_btn("Translate narrative database", "#00a86b"))
        narr_btn.setToolTip(
            "Translate narrative custom sheets after foundation is done. "
            "Short foundation labels are merged into the Glossary."
        )
        narr_btn.clicked.connect(
            lambda: self._translate_db_tiers(wolf_db.NARRATIVE_TIERS, auto_start=True)
        )
        checked_btn = self._register(_make_btn("Translate selected sheets", "#3a3a3a"))
        checked_btn.setToolTip("Translate only the sheets currently ticked above.")
        checked_btn.clicked.connect(
            lambda: self._translate_db_checked(auto_start=True)
        )
        tl_row.addWidget(found_btn)
        tl_row.addWidget(narr_btn)
        tl_row.addWidget(checked_btn)
        tl_row.addStretch()
        layout.addLayout(tl_row)

        self._db_content_dist: wolf_db.ContentDistribution | None = None
        # Defer discovery until the step is shown - files/ may hold RPGMaker JSON.
    def _wolf_json_work_dir(self) -> Path | None:
        if not self._game_root:
            return None
        return self._work_dir()

    def _refresh_db_discovery(self):
        if not hasattr(self, "db_discovery_label"):
            return
        dist = wolf_db.analyze_content_distribution("files")
        self._db_content_dist = dist
        self.db_discovery_label.setText(wolf_db.format_discovery_summary(dist))
        self._refresh_db_groups_list(dist)

    def _refresh_db_groups_list(self, dist: wolf_db.ContentDistribution | None = None):
        if not hasattr(self, "_db_groups_list"):
            return
        if dist is None:
            dist = self._db_content_dist or wolf_db.analyze_content_distribution("files")
            self._db_content_dist = dist

        work_dir = self._wolf_json_work_dir()
        profile = wolf_db.load_db_profile(work_dir) if work_dir else {}
        checks = wolf_db.merge_profile_with_groups(profile, dist.groups)

        self._db_groups_list.blockSignals(True)
        self._db_groups_list.clear()
        if not dist.groups:
            item = QListWidgetItem("No database JSON in files/ - run Step 0 (Extract) first.")
            item.setFlags(Qt.ItemIsEnabled)
            self._db_groups_list.addItem(item)
            self._db_groups_list.blockSignals(False)
            return

        tier_labels = {
            wolf_db.TIER_FOUNDATION: "foundation",
            wolf_db.TIER_SYSTEM: "system",
            wolf_db.TIER_NARRATIVE: "narrative",
            wolf_db.TIER_UNKNOWN: "unknown",
        }
        for g in sorted(dist.groups, key=lambda x: (x.tier, -x.line_count, x.type_name)):
            tier_lbl = tier_labels.get(g.tier, g.tier)
            label = f"[{tier_lbl}] {g.type_name} ({g.line_count} lines) — {g.json_file}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, g.key)
            item.setData(Qt.UserRole + 1, g.tier)
            item.setFlags(
                Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable
            )
            checked = checks.get(g.key, g.default_checked)
            item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
            self._db_groups_list.addItem(item)
        self._db_groups_list.blockSignals(False)

    def _set_db_group_checks(self, checked: bool):
        if not hasattr(self, "_db_groups_list"):
            return
        state = Qt.Checked if checked else Qt.Unchecked
        self._db_groups_list.blockSignals(True)
        for i in range(self._db_groups_list.count()):
            item = self._db_groups_list.item(i)
            if item.flags() & Qt.ItemIsUserCheckable:
                item.setCheckState(state)
        self._db_groups_list.blockSignals(False)
        self._save_db_profile_from_ui()

    def _select_db_foundation_groups(self):
        if not hasattr(self, "_db_groups_list"):
            return
        foundation = wolf_db.FOUNDATION_TIERS
        self._db_groups_list.blockSignals(True)
        for i in range(self._db_groups_list.count()):
            item = self._db_groups_list.item(i)
            if item.flags() & Qt.ItemIsUserCheckable:
                tier = item.data(Qt.UserRole + 1)
                item.setCheckState(Qt.Checked if tier in foundation else Qt.Unchecked)
        self._db_groups_list.blockSignals(False)
        self._save_db_profile_from_ui()

    def _select_db_narrative_groups(self):
        if not hasattr(self, "_db_groups_list"):
            return
        narrative = wolf_db.NARRATIVE_TIERS
        self._db_groups_list.blockSignals(True)
        for i in range(self._db_groups_list.count()):
            item = self._db_groups_list.item(i)
            if item.flags() & Qt.ItemIsUserCheckable:
                tier = item.data(Qt.UserRole + 1)
                item.setCheckState(Qt.Checked if tier in narrative else Qt.Unchecked)
        self._db_groups_list.blockSignals(False)
        self._save_db_profile_from_ui()

    def _get_db_groups_checked(self) -> list[str]:
        keys: list[str] = []
        if not hasattr(self, "_db_groups_list"):
            return keys
        for i in range(self._db_groups_list.count()):
            item = self._db_groups_list.item(i)
            if (item.flags() & Qt.ItemIsUserCheckable) and item.checkState() == Qt.Checked:
                key = item.data(Qt.UserRole)
                if key:
                    keys.append(str(key))
        return keys

    def _save_db_profile_from_ui(self):
        work_dir = self._wolf_json_work_dir()
        if work_dir is None:
            return
        dist = self._db_content_dist or wolf_db.analyze_content_distribution("files")
        checked = set(self._get_db_groups_checked())
        foundation: list[str] = []
        narrative: list[str] = []
        defer: list[str] = []
        for g in dist.groups:
            if g.key in checked:
                if g.tier == wolf_db.TIER_NARRATIVE:
                    narrative.append(g.key)
                else:
                    foundation.append(g.key)
            else:
                defer.append(g.key)
        profile = wolf_db.load_db_profile(work_dir)
        profile.update({
            "archetype": dist.archetype,
            "foundation_groups": foundation,
            "narrative_groups": narrative,
            "defer_groups": defer,
        })
        if not profile.get("notes"):
            profile["notes"] = wolf_db.archetype_guidance(dist).split("\n")[0]
        try:
            wolf_db.save_db_profile(work_dir, profile)
        except Exception as exc:
            self._log(f"❌ Could not save db_profile.json: {exc}")

    def _copy_db_audit_prompt(self):
        dist = self._db_content_dist or wolf_db.analyze_content_distribution("files")
        try:
            QApplication.clipboard().setText(wolf_db.build_ai_audit_prompt(dist))
            self._log(
                "📋 Database structure prompt copied. Paste into Cursor/Copilot; "
                "import the returned JSON with Import AI profile JSON."
            )
        except Exception as exc:
            self._log(f"❌ Could not copy DB audit prompt: {exc}")

    def _import_db_profile_dialog(self):
        from PyQt5.QtWidgets import QInputDialog

        text, ok = QInputDialog.getMultiLineText(
            self,
            "Import AI profile",
            "Paste the JSON profile returned by the AI audit:",
            "",
        )
        if not ok or not text.strip():
            return
        work_dir = self._wolf_json_work_dir()
        if work_dir is None:
            QMessageBox.warning(self, "No game folder", "Complete Step 0 first.")
            return
        try:
            profile = wolf_db.import_ai_profile(text)
            existing = wolf_db.load_db_profile(work_dir)
            existing.update(profile)
            wolf_db.save_db_profile(work_dir, existing)
            self._log("✅ db_profile.json saved from AI audit.")
            self._refresh_db_discovery()
        except Exception as exc:
            QMessageBox.warning(self, "Import failed", str(exc))

    def _set_db_filter_env(self, *, groups: list[str] | None = None, clear: bool = False):
        if clear:
            self._write_env_values({
                "wolfDbIncludeGroups": "",
                "wolfDbIncludeTiers": "",
            })
            return
        if groups is not None:
            self._write_env_values({
                "wolfDbIncludeGroups": json.dumps(groups, ensure_ascii=False),
                "wolfDbIncludeTiers": "",
            })

    def _translate_db_tiers(self, tiers: frozenset[str], *, auto_start: bool):
        dist = self._db_content_dist or wolf_db.analyze_content_distribution("files")
        groups = wolf_db.selected_groups_for_tiers(dist.groups, tiers)
        if not groups:
            QMessageBox.information(
                self, "No sheets",
                f"No database sheets match tier(s): {', '.join(sorted(tiers))}.",
            )
            return
        self._set_db_filter_env(groups=groups)
        self._navigate_to_translation(
            kinds=PHASE_DB_KINDS, auto_start=auto_start, db_filter_active=True
        )

    def _translate_db_checked(self, *, auto_start: bool):
        groups = self._get_db_groups_checked()
        if not groups:
            QMessageBox.information(
                self, "Nothing selected",
                "Tick at least one database sheet, then try again.",
            )
            return
        self._set_db_filter_env(groups=groups)
        self._navigate_to_translation(
            kinds=PHASE_DB_KINDS, auto_start=auto_start, db_filter_active=True
        )

    # ── Step 5: Maps / Events ──────────────────────────────────────────────────

    def _build_step5_maps_events(self, layout: QVBoxLayout):
        layout.addWidget(self._page_header(
            5, "Translate Maps & Events", "Translate map dialogue, common events, and event text."
        ))
        layout.addWidget(self._desc(
            "Map scripts (.mps), common events (CommonEvent.dat), Game.dat, and Evtext - "
            "story dialogue, UI/objective strings, and other event text. Run after Steps "
            "3-4 so the Glossary and database terms are already consistent. CommonEvent.dat "
            "can be very large; Batch mode is recommended for big files."
        ))
        self._add_speaker_options(layout)
        self._add_tl_mode_selector(layout)
        p2 = self._register(_make_btn("Translate maps & events", "#00a86b"))
        p2.clicked.connect(
            lambda: self._navigate_to_translation(
                kinds=PHASE_MAPS_EVENTS_KINDS, auto_start=True, db_filter_active=False
            )
        )
        layout.addWidget(p2)

        layout.addWidget(_make_hr())
        open_btn = self._register(_make_btn("Open Translation without starting", "#3a3a3a"))
        open_btn.clicked.connect(
            lambda: self._navigate_to_translation(db_filter_active=False)
        )
        layout.addWidget(open_btn)

    # ── Legacy translate helpers (speaker options shared with maps step) ───────
    def _add_speaker_options(self, layout: QVBoxLayout):
        """Speaker handling: nameplates are automatic; the low-confidence guess is
        an AI-recommended per-game setting."""
        from util import speakers as wolf_speakers

        layout.addWidget(_make_hr())
        layout.addWidget(self._subheading("Speaker handling"))
        layout.addWidget(self._desc(
            "WolfDawn already detects who speaks on each line, so this is automatic: lines "
            "with a real nameplate (a face window precedes the name) are always reshaped into "
            "the \"[Speaker]: line\" format the prompt understands, translated, and restored to "
            "WOLF's native \"Speaker⏎line\" layout on inject. The only judgement call is whether "
            "to trust WolfDawn's low-confidence guesses (a short first line with no face window "
            "that might be a name - or might just be the start of dialogue)."
        ))
        layout.addWidget(self._desc(
            "Ask the AI managing the game repo to decide: the prompt has it inspect the "
            "extracted files/ and recommend whether low-confidence first-line names should be "
            "reshaped for this game. Then set the box below to match."
        ))

        prompt_btn = _make_btn("Copy speaker-format audit", "#5a3a7a")
        prompt_btn.clicked.connect(self._copy_wolf_speaker_prompt)
        layout.addWidget(prompt_btn)

        cfg = wolf_speakers.load_config()
        self._speaker_lo_cb = QCheckBox(
            "Reshape low-confidence first-line names (enable if the AI says this game uses them)"
        )
        self._speaker_lo_cb.setChecked(bool(cfg.get("literal_line1_lowconf", True)))
        self._speaker_lo_cb.stateChanged.connect(self._save_speaker_options)
        layout.addWidget(self._speaker_lo_cb)

    def _copy_wolf_speaker_prompt(self):
        try:
            QApplication.clipboard().setText(load_clipboard_skill("wolf_speakers.md"))
            self._log(
                "📋 Speaker-format prompt copied. Paste it into Cursor/Copilot with files/ open; "
                "set the low-confidence box to match its recommendation."
            )
        except Exception as exc:
            self._log(f"❌ Could not copy speaker prompt: {exc}")

    def _save_speaker_options(self):
        from util import speakers as wolf_speakers

        try:
            wolf_speakers.save_config({
                "literal_line1_lowconf": self._speaker_lo_cb.isChecked(),
            })
        except Exception as exc:
            self._log(f"❌ Could not save speaker options: {exc}")

    def _read_env_values(self, keys) -> dict:
        """Read a few `key='value'` pairs from .env (best effort)."""
        import re as _re
        out = {}
        env_path = Path(".env")
        if not env_path.exists():
            return out
        try:
            text = env_path.read_text(encoding="utf-8")
        except Exception:
            return out
        for key in keys:
            m = _re.search(rf"^{_re.escape(key)}\s*=\s*'([^']*)'", text, _re.MULTILINE)
            if m:
                out[key] = m.group(1)
        return out

    def _write_env_values(self, updates: dict) -> bool:
        """Update/insert `key='value'` pairs in .env. Returns True on success."""
        import re as _re
        env_path = Path(".env")
        try:
            text = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
            for key, val in updates.items():
                text, n = _re.subn(
                    rf"^({_re.escape(key)}\s*=\s*')[^']*(')",
                    rf"\g<1>{val}\g<2>",
                    text,
                    flags=_re.MULTILINE,
                )
                if n == 0:
                    text = text.rstrip("\n") + f"\n{key}='{val}'\n"
            env_path.write_text(text, encoding="utf-8")
            return True
        except Exception as exc:
            self._log(f"❌ Could not update .env: {exc}")
            return False

    def _add_tl_mode_selector(self, layout: QVBoxLayout):
        """Normal vs Batch selector for all Wolf workflow translation phases."""
        row = QHBoxLayout()
        lbl = QLabel("Translation mode:")
        lbl.setStyleSheet("color:#cccccc;font-size:12px;font-weight:bold;background:transparent;")
        self._tl_mode_combo = QComboBox()
        self._tl_mode_combos.append(self._tl_mode_combo)
        self._tl_mode_combo.addItem(_TL_NORMAL_LABEL)
        self._tl_mode_combo.addItem(BATCH_MODE_LABEL)
        self._tl_mode_combo.setFixedWidth(220)
        self._tl_mode_combo.setToolTip(
            "Normal translates live; Batch uses the Anthropic Batches API (~50% cheaper, Claude only)."
        )
        default_mode = default_translation_mode()
        self._last_default_translation_mode = default_mode
        automatic = BATCH_MODE_LABEL if default_mode == BATCH_MODE_LABEL else _TL_NORMAL_LABEL
        saved = self._setting("tl_mode", None)
        self._tl_mode_user_selected = saved in (_TL_NORMAL_LABEL, BATCH_MODE_LABEL)
        if saved not in (_TL_NORMAL_LABEL, BATCH_MODE_LABEL):
            saved = automatic
        elif saved == BATCH_MODE_LABEL and automatic != BATCH_MODE_LABEL:
            saved = automatic
            self._tl_mode_user_selected = False
        idx = self._tl_mode_combo.findText(str(saved))
        if idx >= 0:
            self._tl_mode_combo.setCurrentIndex(idx)
        self._tl_mode_combo.currentTextChanged.connect(self._on_tl_mode_changed)
        self._tl_mode_combo.activated.connect(self._mark_tl_mode_selected)
        row.addWidget(lbl)
        row.addWidget(self._tl_mode_combo)
        row.addStretch()
        layout.addLayout(row)

        self._batch_note = QLabel(BATCH_MODE_BENEFIT_NOTE + "\n" + BATCH_COLLECT_LIVE_CHARGE_NOTE)
        self._batch_note.setWordWrap(True)
        self._batch_note.setStyleSheet("color:#8fbc8f;font-size:11px;background:transparent;")
        layout.addWidget(self._batch_note)
        self._on_tl_mode_changed(self._tl_mode_combo.currentText(), save=False)

    def _on_tl_mode_changed(self, mode_text: str, save=True):
        is_batch = mode_text == BATCH_MODE_LABEL
        if hasattr(self, "_batch_note"):
            self._batch_note.setVisible(is_batch)
        if save:
            self._save_setting("tl_mode", mode_text)

    def _workflow_mode_text(self) -> str:
        """Map the selector to the Translation tab's own mode label."""
        automatic = BATCH_MODE_LABEL if default_translation_mode() == BATCH_MODE_LABEL else _TL_NORMAL_LABEL
        selected = self._setting("tl_mode", automatic) or automatic
        if selected == BATCH_MODE_LABEL and automatic == BATCH_MODE_LABEL:
            return BATCH_MODE_LABEL
        return "Translate"

    def _mark_tl_mode_selected(self, _index: int):
        self._tl_mode_user_selected = True

    def refresh_default_translation_mode(self, force=False):
        """Apply the provider-aware mode after configuration changes."""
        default_mode = default_translation_mode()
        if not force and default_mode == self._last_default_translation_mode:
            return
        self._last_default_translation_mode = default_mode
        mode = BATCH_MODE_LABEL if default_mode == BATCH_MODE_LABEL else _TL_NORMAL_LABEL
        if default_mode == "Translate" or force or not self._tl_mode_user_selected:
            for combo in self._tl_mode_combos:
                index = combo.findText(mode)
                if index >= 0:
                    combo.setCurrentIndex(index)
            self._save_setting("tl_mode", mode)

    def _navigate_to_translation(
        self,
        only: str | None = None,
        kinds: set[str] | None = None,
        auto_start: bool = False,
        db_filter_active: bool | None = None,
    ):
        """Switch to the Translation tab, select the WolfDawn module, and check files.

        Selection precedence: ``only`` (a single filename) > ``kinds`` (a phase's
        manifest kinds, e.g. ``{"db"}``) > legacy bulk (everything except
        names.json).

        When ``db_filter_active`` is False, database group/tier filters in ``.env``
        are cleared so maps/events runs are unaffected. When True, the filter set
        by :meth:`_set_db_filter_env` is kept for the DB translation run.
        """
        if db_filter_active is False:
            self._set_db_filter_env(clear=True)
        pw = self.parent_window
        tt = getattr(pw, "translation_tab", None) if pw else None
        if tt is None:
            QMessageBox.warning(self, "Translate", "Translation tab is not available.")
            return
        try:
            combo = tt.module_combo
            for i in range(combo.count()):
                if "WolfDawn" in combo.itemText(i):
                    combo.setCurrentIndex(i)
                    break
        except Exception:
            pass

        # Apply the chosen translation mode (after the module, since changing the
        # module can refresh the mode list).
        try:
            mode_combo = tt.mode_combo
            mode_idx = mode_combo.findText(self._workflow_mode_text())
            if mode_idx >= 0:
                mode_combo.setCurrentIndex(mode_idx)
        except Exception:
            pass

        kind_map = self._manifest_kinds() if kinds is not None else {}
        try:
            tt.refresh_file_lists()
            fl = tt.file_list
            for idx in range(fl.count()):
                item = fl.item(idx)
                name = item.text()
                if only is not None:
                    # Targeted run: check exactly that file.
                    check = name == only
                elif kinds is not None:
                    # Phase run: check files whose manifest kind is in this phase.
                    check = kind_map.get(name) in kinds
                else:
                    # Bulk run: everything except names.json.
                    check = name != NAMES_JSON
                item.setCheckState(Qt.Checked if check else Qt.Unchecked)
        except Exception:
            pass

        if pw and hasattr(pw, "switch_page"):
            page = getattr(pw, "PAGE_TRANSLATION", 4)
            pw.switch_page(page)
        elif pw and hasattr(pw, "content_stack"):
            pw.content_stack.setCurrentIndex(4)
            if hasattr(pw, "nav_buttons"):
                for i, btn in enumerate(pw.nav_buttons):
                    btn.setChecked(i == 4)

        if auto_start:
            QTimer.singleShot(
                150,
                lambda: tt.start_translation(skip_confirm=True) if tt is not None else None,
            )

    # ── Step 3: Names ──────────────────────────────────────────────────────────

    def _build_step3_names(self, layout: QVBoxLayout):
        layout.addWidget(self._page_header(
            3, "Translate Names", "Translate safe character and location names, then update the Glossary."
        ))
        layout.addWidget(self._desc(
            "names.json is WolfDawn's project-wide name list. Each entry has a safety badge: "
            "safe (display-only), refs (referenced by name - skipped), or verify "
            "(also in indirect literals - skipped). Phase 0 translates every safe entry "
            "individually, regardless of category, and adds them to the Glossary."
        ))

        self.names_summary_label = QLabel("Open this step after extraction to see name counts.")
        self.names_summary_label.setWordWrap(True)
        self.names_summary_label.setStyleSheet(
            "color:#9cdcfe;font-size:13px;padding:8px 10px;"
            "background-color:#1a2430;border:1px solid #2a4a6a;border-radius:4px;"
        )
        layout.addWidget(self.names_summary_label)

        refresh_btn = _make_btn("Refresh name counts", "#555")
        refresh_btn.clicked.connect(self._refresh_names_summary)
        layout.addWidget(refresh_btn)

        layout.addWidget(_make_hr())
        layout.addWidget(self._subheading("Translate names (Phase 0)"))
        layout.addWidget(self._desc(
            "Pick Normal or Batch below, then run Phase 0. Only safe entries are sent to "
            "the model; refs and verify names stay identical to source so inject skips them."
        ))
        self._add_tl_mode_selector(layout)
        tl_btn = self._register(_make_btn("Translate safe names", "#00a86b"))
        tl_btn.clicked.connect(
            lambda: self._navigate_to_translation(
                kinds=PHASE_NAMES_KINDS, auto_start=True, db_filter_active=False
            )
        )
        layout.addWidget(tl_btn)
        self._refresh_names_summary()

    def _load_names_document(self) -> tuple[dict | None, Path | None]:
        """Read names.json from files/ or wolf_json/."""
        src = self._names_json_path()
        if src is None:
            return None, None
        try:
            with open(src, "r", encoding="utf-8-sig") as f:
                return json.load(f), src
        except Exception as exc:
            self._log(f"❌ Could not read {NAMES_JSON}: {exc}")
            return None, src

    def _refresh_names_summary(self):
        if not hasattr(self, "names_summary_label"):
            return
        data, src = self._load_names_document()
        if not isinstance(data, dict):
            self.names_summary_label.setText(
                "No names.json found - run Step 0 (Extract text) first."
            )
            return
        summary = wolf_names.format_name_safety_summary(data)
        db_labels = wolf_names.derive_db_labels("files")
        categories = wolf_names.format_note_category_summary(data, db_labels=db_labels)
        where = src.parent.name if src else WORK_DIR_NAME
        self.names_summary_label.setText(
            f"{summary}\n\n{categories}\n\nSource: {where}/{NAMES_JSON}"
        )

    def _names_json_path(self) -> Path | None:
        """Locate names.json for reading (files/ then wolf_json/)."""
        for base in (Path("files"), self._work_dir()):
            p = base / NAMES_JSON
            if p.is_file():
                return p
        return None

    # ── Step 6: Precheck ───────────────────────────────────────────────────────

    def _build_step6_precheck(self, layout: QVBoxLayout):
        layout.setSpacing(6)
        title = self._page_header(
            6, "Validate Injection", "Preview injection and resolve unsafe or inconsistent text first."
        )
        title.setToolTip(
            "Reconcile names.json → Glossary spellings, report name inconsistencies, "
            "then dry-run selected JSON for safety skips (control-code mismatch, or "
            "text not Shift-JIS encodable). Fix safety rows here, then Step 7 (Inject)."
        )
        layout.addWidget(title)
        layout.addWidget(self._desc(
            "Pick files → Precheck → fix safety skips below → Step 7 Inject."
        ))

        self.precheck_list = CheckableFileList()
        self.precheck_list.setMinimumHeight(72)
        self.precheck_list.setMaximumHeight(120)
        self.precheck_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.precheck_list.setStyleSheet(
            "QListWidget{background-color:#252526;border:1px solid #3a3a3a;border-radius:4px;"
            "color:#cccccc;font-size:12px;padding:1px;}"
            "QListWidget::item{padding:2px 4px;}"
            "QListWidget::item:selected{background:#264f78;color:#ffffff;}"
        )
        layout.addWidget(self.precheck_list)

        list_row = QHBoxLayout()
        list_row.setSpacing(6)
        refresh_btn = self._register(_make_btn("Refresh files", "#3a3a3a"))
        refresh_btn.clicked.connect(self._refresh_precheck_list)
        sel_all_btn = self._register(_make_btn("Select all", "#3a3a3a"))
        sel_all_btn.clicked.connect(lambda: self._set_checklist_checks(self.precheck_list, True))
        sel_none_btn = self._register(_make_btn("Clear selection", "#3a3a3a"))
        sel_none_btn.clicked.connect(lambda: self._set_checklist_checks(self.precheck_list, False))
        precheck_btn = self._register(_make_btn("Preview selected injection", "#007acc"))
        precheck_btn.setToolTip(
            "Reconcile names → Glossary, run names-check, then dry-run inject "
            "safety guards on the ticked files."
        )
        precheck_btn.clicked.connect(self._precheck_inject_selected)
        precheck_all_btn = self._register(_make_btn("Preview all injection", "#007acc"))
        precheck_all_btn.setToolTip(
            "Same as Preview selected injection, for every injectable file in translated/."
        )
        precheck_all_btn.clicked.connect(self._precheck_inject_all)
        list_row.addWidget(refresh_btn)
        list_row.addWidget(sel_all_btn)
        list_row.addWidget(sel_none_btn)
        list_row.addStretch()
        list_row.addWidget(precheck_btn)
        list_row.addWidget(precheck_all_btn)
        layout.addLayout(list_row)

        self._inject_precheck_label = QLabel(
            "Preview injection to list safety-guard skips."
        )
        self._inject_precheck_label.setWordWrap(True)
        self._inject_precheck_label.setStyleSheet(
            "color:#9cdcfe;font-size:11px;background:transparent;padding:0;"
        )
        layout.addWidget(self._inject_precheck_label)

        self._inject_issue_list = QListWidget()
        self._inject_issue_list.setMinimumHeight(80)
        self._inject_issue_list.setMaximumHeight(140)
        self._inject_issue_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self._inject_issue_list.setWordWrap(True)
        self._inject_issue_list.setTextElideMode(Qt.ElideNone)
        self._inject_issue_list.setUniformItemSizes(False)
        self._inject_issue_list.setStyleSheet(
            "QListWidget{background-color:#252526;border:1px solid #3a3a3a;border-radius:4px;"
            "color:#cccccc;font-size:12px;padding:1px;}"
            "QListWidget::item{padding:3px 6px;}"
            "QListWidget::item:selected{background:#264f78;color:#ffffff;}"
        )
        self._inject_issue_list.currentItemChanged.connect(self._on_inject_issue_selected)
        layout.addWidget(self._inject_issue_list)

        self._inject_issue_meta = QLabel("")
        self._inject_issue_meta.setWordWrap(True)
        self._inject_issue_meta.setStyleSheet(
            "color:#808080;font-size:11px;background:transparent;padding:0;"
        )
        layout.addWidget(self._inject_issue_meta)

        self._inject_issue_edit = QTextEdit()
        self._inject_issue_edit.setPlaceholderText(
            "Select a preview result to edit its translated text, then save the line."
        )
        self._inject_issue_edit.setMinimumHeight(100)
        self._inject_issue_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._inject_issue_edit.setStyleSheet(
            "QTextEdit{background-color:#1e1e1e;color:#d4d4d4;border:1px solid #3c3c3c;"
            "border-left:3px solid #007acc;border-radius:0;padding:4px;font-size:12px;}"
        )
        layout.addWidget(self._inject_issue_edit, 1)

        edit_row = QHBoxLayout()
        edit_row.setSpacing(6)
        save_line_btn = self._register(_make_btn("Save corrected line", "#00a86b"))
        save_line_btn.clicked.connect(self._save_inject_issue_line)
        edit_row.addWidget(save_line_btn)
        edit_row.addStretch()
        layout.addLayout(edit_row)

        self._inject_precheck_issues: list = []
        self._refresh_precheck_list()

    # ── Step 7: Inject ─────────────────────────────────────────────────────────

    def _build_step7_inject(self, layout: QVBoxLayout):
        layout.addWidget(self._page_header(
            7, "Apply Translations", "Write reviewed JSON translations into the live game data."
        ))
        layout.addWidget(self._desc(
            "Apply every JSON translation to the game's Data/ binaries in one pass. "
            "Apply all translations uses translated/; Apply from wolf_json uses the game's "
            "wolf_json/ when that folder is the source of truth (and can copy those "
            "JSON into files/ and translated/ so tool progress is not left behind). "
            "A full inject keeps names.json and DB/map files in sync (partial injects "
            "can wipe name-only fields like rumor boards). Preview in Step 6 first "
            "if you want to catch safety-guard skips before writing."
        ))

        self.en_punct_cb = QCheckBox("Convert Japanese punctuation to ASCII (--en-punct)")
        self.en_punct_cb.setChecked(self._setting("en_punct", "true") == "true")
        self.en_punct_cb.setToolTip(
            "Fold fullwidth JP punctuation to ASCII on inject. "
            "Inline-code drift for \\f shrink is applied automatically."
        )
        self.en_punct_cb.stateChanged.connect(
            lambda: self._save_setting("en_punct", "true" if self.en_punct_cb.isChecked() else "false")
        )
        layout.addWidget(self.en_punct_cb)

        layout.addWidget(_make_hr())
        layout.addWidget(self._subheading("Files that will be injected"))

        self.inject_list = QListWidget()
        self.inject_list.setMaximumHeight(220)
        self.inject_list.setStyleSheet(
            "QListWidget{background-color:#252526;border:1px solid #3a3a3a;border-radius:4px;"
            "color:#cccccc;font-size:12px;padding:2px;}"
            "QListWidget::item{padding:3px 4px;}"
            "QListWidget::item:selected{background:#264f78;color:#ffffff;}"
        )
        layout.addWidget(self.inject_list)

        self._inject_count_label = QLabel("")
        self._inject_count_label.setStyleSheet("color:#9cdcfe;font-size:12px;")
        layout.addWidget(self._inject_count_label)

        list_row = QHBoxLayout()
        refresh_btn = self._register(_make_btn("Refresh files", "#3a3a3a"))
        refresh_btn.clicked.connect(self._refresh_inject_list)
        list_row.addWidget(refresh_btn)
        list_row.addStretch()
        layout.addLayout(list_row)

        btn_row = QHBoxLayout()
        inject_all_btn = self._register(_make_btn("Apply all translations", "#00a86b"))
        inject_all_btn.setToolTip(
            "Always injects every file in translated/ that the manifest knows about. "
            "names.json runs first; DB/map injects keep name-only fields. "
            "After inject, copies those JSON files into the game's wolf_json/."
        )
        inject_all_btn.clicked.connect(self._inject_all)
        inject_wolf_btn = self._register(_make_btn("Apply from wolf_json", "#007acc"))
        inject_wolf_btn.setToolTip(
            "Inject every injectable JSON from the game's wolf_json/ folder instead "
            "of translated/. Use when wolf_json/ is the source of truth (e.g. after "
            "editing or restoring committed game-repo JSON). Asks whether to copy "
            "those JSON into files/ and translated/ so tool progress is not left behind."
        )
        inject_wolf_btn.clicked.connect(self._inject_all_from_wolf_json)
        layout_restore_btn = self._register(_make_btn("Restore source layout", "#3a3a3a"))
        layout_restore_btn.setToolTip(
            "Re-run wolf layout-restore on every injectable translated JSON. "
            "Copies unambiguous positional whitespace pads from source onto text "
            "(e.g. status-card <pad>\\nNAME). Safe to re-run; already-fixed lines are no-ops."
        )
        layout_restore_btn.clicked.connect(self._layout_restore_all)
        btn_row.addWidget(inject_all_btn)
        btn_row.addWidget(inject_wolf_btn)
        btn_row.addStretch()
        btn_row.addWidget(layout_restore_btn)
        layout.addLayout(btn_row)

        layout.addWidget(_make_hr())
        layout.addWidget(self._desc(
            "Next: Step 8 (Package) so you can playtest, then Step 9 (Fix wrapping) "
            "to paste overflowing in-game text, wrap, and apply all translations again."
        ))
        self._refresh_inject_list()

    def _build_step9_relayout(self, layout: QVBoxLayout):
        """Search-first fix wrapping: find a sheet, wrap, then reapply translations."""
        layout.setSpacing(6)
        title = self._page_header(
            9, "Fix Text Layout", "Find overflow and correct wrapping or cell geometry after playtesting."
        )
        title.setToolTip(
            "Paste overflowing in-game text to find it in translated JSON. "
            "Relayout: cell width + max lines (names.json → wolf names-wrap). "
            "Manual: wrap width + body font; emphasis \\f[N] scales with the body. "
            "Then apply all translations (Step 7) and re-package."
        )
        layout.addWidget(title)
        layout.addWidget(self._desc(
            "Paste overflowing text → choose a result → relayout or wrap → apply again."
        ))

        search_row = QHBoxLayout()
        search_row.setSpacing(6)
        self._wrap_search_edit = QLineEdit()
        self._wrap_search_edit.setPlaceholderText(
            'Paste in-game text, e.g. "there\'s a pure" or "gatekeeper just randomly"'
        )
        search_btn = _make_btn("Find text", "#007acc")
        search_btn.clicked.connect(self._run_wrap_search)
        self._wrap_search_edit.returnPressed.connect(self._run_wrap_search)
        search_row.addWidget(self._wrap_search_edit, 1)
        search_row.addWidget(search_btn)
        layout.addLayout(search_row)

        self._wrap_results_list = QListWidget()
        self._wrap_results_list.setMinimumHeight(72)
        self._wrap_results_list.setMaximumHeight(110)
        self._wrap_results_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self._wrap_results_list.setWordWrap(True)
        self._wrap_results_list.setTextElideMode(Qt.ElideNone)
        self._wrap_results_list.setUniformItemSizes(False)
        self._wrap_results_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._wrap_results_list.setStyleSheet(
            "QListWidget{background-color:#252526;border:1px solid #3a3a3a;border-radius:4px;"
            "color:#cccccc;font-size:12px;padding:1px;}"
            "QListWidget::item{padding:3px 6px;}"
            "QListWidget::item:selected{background:#264f78;color:#ffffff;}"
        )
        self._wrap_results_list.currentItemChanged.connect(self._on_wrap_hit_selected)
        layout.addWidget(self._wrap_results_list)

        self._wrap_detail_label = QLabel("Select a search result to edit.")
        self._wrap_detail_label.setWordWrap(True)
        self._wrap_detail_label.setStyleSheet(
            "color:#9cdcfe;font-size:11px;background:transparent;padding:0;"
        )
        layout.addWidget(self._wrap_detail_label)

        # Mode + active controls on one row to cut vertical chrome.
        controls_row = QHBoxLayout()
        controls_row.setSpacing(8)
        mode_lbl = QLabel("Mode:")
        mode_lbl.setStyleSheet("color:#cccccc;font-size:12px;background:transparent;")
        self._wrap_mode_combo = QComboBox()
        self._wrap_mode_combo.addItem("Relayout", "relayout")
        self._wrap_mode_combo.addItem("Manual", "manual")
        self._wrap_mode_combo.setMinimumWidth(110)
        saved_mode = str(self._setting("wrap_fix_mode", "relayout") or "relayout")
        idx = self._wrap_mode_combo.findData(saved_mode)
        self._wrap_mode_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._wrap_mode_combo.setToolTip(
            "Relayout: names use wolf names-wrap; DB/dialogue wrap to cell width "
            "and shrink \\f[N] to fit Max lines.\n"
            "Manual: force wrap width and body font; emphasis \\f[N] scales with the body."
        )
        self._wrap_mode_combo.currentIndexChanged.connect(self._on_wrap_mode_changed)
        controls_row.addWidget(mode_lbl)
        controls_row.addWidget(self._wrap_mode_combo)

        # Relayout controls: cell width + max lines
        self._wrap_relayout_row = QWidget()
        relayout_row = QHBoxLayout(self._wrap_relayout_row)
        relayout_row.setContentsMargins(0, 0, 0, 0)
        relayout_row.setSpacing(6)
        w_lbl = QLabel("Width:")
        w_lbl.setStyleSheet("color:#cccccc;font-size:12px;background:transparent;")
        self._wrap_width_spin = QSpinBox()
        self._wrap_width_spin.setRange(0, 200)
        try:
            self._wrap_width_spin.setValue(int(self._setting("wrap_fix_width", 36) or 36))
        except (TypeError, ValueError):
            self._wrap_width_spin.setValue(36)
        self._wrap_width_spin.setFixedWidth(64)
        self._wrap_width_spin.setToolTip(
            "Cell width in halfwidth cells (ASCII=1, fullwidth=2). 0 = auto "
            "(names: measure from JP). N > 0 forces wolf names-wrap --width."
        )
        self._wrap_width_spin.valueChanged.connect(self._on_wrap_width_changed)
        lines_lbl = QLabel("Lines:")
        lines_lbl.setStyleSheet("color:#cccccc;font-size:12px;background:transparent;")
        self._wrap_max_lines_spin = QSpinBox()
        self._wrap_max_lines_spin.setRange(0, 20)
        try:
            self._wrap_max_lines_spin.setValue(
                int(self._setting("wrap_fix_max_lines", 0) or 0)
            )
        except (TypeError, ValueError):
            self._wrap_max_lines_spin.setValue(0)
        self._wrap_max_lines_spin.setFixedWidth(64)
        self._wrap_max_lines_spin.setToolTip(
            "Max soft lines (0 = auto). Names: wolf names-wrap --lines. "
            "DB/dialogue: wrap to width, then shrink \\f[N] to fit. "
            "Saved per sheet in wolfdawn-roles.json."
        )
        self._wrap_max_lines_spin.valueChanged.connect(self._on_wrap_max_lines_changed)
        relayout_row.addWidget(w_lbl)
        relayout_row.addWidget(self._wrap_width_spin)
        relayout_row.addWidget(lines_lbl)
        relayout_row.addWidget(self._wrap_max_lines_spin)
        controls_row.addWidget(self._wrap_relayout_row)

        # Manual controls: wrap width + font size
        self._wrap_manual_row = QWidget()
        manual_row = QHBoxLayout(self._wrap_manual_row)
        manual_row.setContentsMargins(0, 0, 0, 0)
        manual_row.setSpacing(6)
        mw_lbl = QLabel("Width:")
        mw_lbl.setStyleSheet("color:#cccccc;font-size:12px;background:transparent;")
        self._wrap_manual_width_spin = QSpinBox()
        self._wrap_manual_width_spin.setRange(10, 200)
        try:
            self._wrap_manual_width_spin.setValue(
                int(self._setting("wrap_fix_manual_width", 36) or 36)
            )
        except (TypeError, ValueError):
            self._wrap_manual_width_spin.setValue(36)
        self._wrap_manual_width_spin.setFixedWidth(64)
        self._wrap_manual_width_spin.setToolTip(
            "Hard wrap width in halfwidth cells for Manual mode (dazedwrap)."
        )
        self._wrap_manual_width_spin.valueChanged.connect(self._on_wrap_manual_width_changed)
        font_lbl = QLabel("Font:")
        font_lbl.setStyleSheet("color:#cccccc;font-size:12px;background:transparent;")
        self._wrap_font_spin = QSpinBox()
        self._wrap_font_spin.setRange(0, 32)
        self._wrap_font_spin.setSpecialValueText("0 (keep)")
        try:
            saved_font = int(self._setting("wrap_fix_font", 18) or 18)
        except (TypeError, ValueError):
            saved_font = 18
        self._wrap_font_spin.setValue(max(0, saved_font))
        self._wrap_font_spin.setFixedWidth(80)
        self._wrap_font_spin.setToolTip(
            "Body \\f[N] on Wrap. 0 = leave fonts alone (width only). "
            "N > 0 scales emphasis and sets a leading \\f[body]."
        )
        self._wrap_font_spin.valueChanged.connect(self._on_wrap_font_changed)
        self._wrap_font_detect_label = QLabel("")
        self._wrap_font_detect_label.setStyleSheet(
            "color:#858585;font-size:11px;background:transparent;"
        )
        manual_row.addWidget(mw_lbl)
        manual_row.addWidget(self._wrap_manual_width_spin)
        manual_row.addWidget(font_lbl)
        manual_row.addWidget(self._wrap_font_spin)
        manual_row.addWidget(self._wrap_font_detect_label, 1)
        controls_row.addWidget(self._wrap_manual_row, 1)
        controls_row.addStretch()
        layout.addLayout(controls_row)

        self._sync_wrap_mode_controls()

        self._wrap_preview_label = QLabel("Wrap preview")
        self._wrap_preview_label.setStyleSheet(
            "color:#858585;font-size:11px;background:transparent;padding:0;"
        )
        layout.addWidget(self._wrap_preview_label)

        self._wrap_preview = QTextEdit()
        self._wrap_preview.setReadOnly(True)
        self._wrap_preview.setMinimumHeight(140)
        self._wrap_preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._wrap_preview.setPlaceholderText(
            "Wrap preview — select a hit to see \\c / \\f styling."
        )
        self._wrap_preview.setStyleSheet(
            "QTextEdit{background-color:#1e1e1e;color:#b5cea8;border:1px solid #3c3c3c;"
            "border-left:3px solid #007acc;font-family:monospace;font-size:12px;padding:4px;}"
        )
        layout.addWidget(self._wrap_preview, 1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        wrap_row_btn = _make_btn("Rewrap this line", "#00a86b")
        wrap_row_btn.clicked.connect(self._wrap_current_row)
        wrap_group_btn = _make_btn("Rewrap matching group", "#00a86b")
        wrap_group_btn.clicked.connect(self._wrap_current_group)
        inject_btn = _make_btn("Apply all translations", "#007acc")
        inject_btn.setToolTip(
            "Always injects every translated file (same as Step 7). "
            "Partial injects can wipe name-only DB fields."
        )
        inject_btn.clicked.connect(self._inject_all)
        btn_row.addWidget(wrap_row_btn)
        btn_row.addWidget(wrap_group_btn)
        btn_row.addWidget(inject_btn)
        self._wrap_status_label = QLabel("")
        self._wrap_status_label.setWordWrap(True)
        self._wrap_status_label.setStyleSheet(
            "color:#8fbc8f;font-size:11px;background:transparent;"
        )
        btn_row.addWidget(self._wrap_status_label, 1)
        layout.addLayout(btn_row)

        self._current_wrap_hit: wolf_ws.WrapHit | None = None
        self._current_wrap_hit_id: dict | None = None
        self._current_wrap_path: Path | None = None
        self._current_wrap_doc: dict | None = None
        self._current_wrap_text: str = ""

    def _translated_and_files_dirs(self) -> tuple[Path, Path]:
        root = self._tool_root()
        return root / "translated", root / "files"

    def _wrap_search_extra_dirs(self) -> list[Path]:
        work = self._wolf_json_work_dir()
        return [work] if work is not None else []

    def _wrap_profile_width(self, sheet_name: str, *, kind: str | None = None) -> int:
        work = self._wolf_json_work_dir()
        if work is not None:
            profile = wolf_ws.load_wrap_profile(work)
            if kind in ("map", "common"):
                geom = wolf_ws.get_format_geometry(
                    profile, self._current_wrap_speaker_src()
                )
                if geom.get("width"):
                    return int(geom["width"])
            return wolf_ws.get_sheet_width(
                profile,
                sheet_name,
                default=int(self._setting("wrap_fix_width", 36) or 36),
            )
        try:
            return int(self._setting("wrap_fix_width", 36) or 36)
        except (TypeError, ValueError):
            return 36

    def _current_wrap_speaker_src(self) -> str:
        kw = self._current_wrap_speaker_kw()
        return str(kw.get("speaker_src") or "")

    def _load_dialogue_geometry_into_spins(self):
        """Load wrap settings for this line's ``speaker_src`` format bucket."""
        work = self._wolf_json_work_dir()
        width = None
        max_lines = None
        font = None
        speaker_src = self._current_wrap_speaker_src()
        if work is not None:
            geom = wolf_ws.get_format_geometry(
                wolf_ws.load_wrap_profile(work), speaker_src
            )
            width = geom.get("width")
            max_lines = geom.get("max_lines")
            font = geom.get("font")
        if width is None:
            try:
                width = int(self._setting("wrap_fix_width", 36) or 36)
            except (TypeError, ValueError):
                width = 36
        if max_lines is None:
            max_lines = 0
        self._wrap_width_spin.blockSignals(True)
        self._wrap_width_spin.setValue(int(width))
        self._wrap_width_spin.blockSignals(False)
        if hasattr(self, "_wrap_manual_width_spin"):
            self._wrap_manual_width_spin.blockSignals(True)
            self._wrap_manual_width_spin.setValue(int(width))
            self._wrap_manual_width_spin.blockSignals(False)
        if hasattr(self, "_wrap_max_lines_spin"):
            self._wrap_max_lines_spin.blockSignals(True)
            self._wrap_max_lines_spin.setValue(int(max_lines))
            self._wrap_max_lines_spin.blockSignals(False)
        if font is not None and hasattr(self, "_wrap_font_spin"):
            self._wrap_font_spin.blockSignals(True)
            self._wrap_font_spin.setValue(int(font))
            self._wrap_font_spin.blockSignals(False)

    def _remember_sheet_width(
        self,
        sheet_name: str,
        width: int,
        json_file: str,
        *,
        max_lines: int | None = None,
        font: int | None = None,
        kind: str | None = None,
        speaker_src: str | None = None,
    ):
        work = self._wolf_json_work_dir()
        if work is None:
            return
        if kind in ("map", "common"):
            src = speaker_src if speaker_src is not None else self._current_wrap_speaker_src()
            wolf_ws.set_format_geometry(
                work,
                src,
                width=width,
                max_lines=max_lines,
                font=font,
            )
            return
        wolf_ws.set_sheet_width(
            work,
            sheet_name,
            width,
            json_file=json_file,
            max_lines=max_lines,
        )

    def _wrap_mode(self) -> str:
        combo = getattr(self, "_wrap_mode_combo", None)
        if combo is not None:
            data = combo.currentData()
            if data:
                return str(data)
        return str(self._setting("wrap_fix_mode", "relayout") or "relayout")

    def _current_wrap_line_text(self) -> str:
        """Return the selected line's text from the loaded document (or cache)."""
        if self._current_wrap_doc is not None and self._current_wrap_hit_id is not None:
            line = wolf_ws.locate_line(self._current_wrap_doc, self._current_wrap_hit_id)
            if line is not None:
                return str(line.get("text") or "")
        return getattr(self, "_current_wrap_text", "") or ""

    def _on_wrap_mode_changed(self, _index: int = 0):
        mode = self._wrap_mode()
        self._save_setting("wrap_fix_mode", mode)
        self._sync_wrap_mode_controls()
        self._update_wrap_preview()
        hit = self._current_wrap_hit
        doc = self._current_wrap_doc
        if hit is not None and doc is not None and hasattr(self, "_wrap_detail_label"):
            text = self._current_wrap_line_text() or hit.text
            self._wrap_detail_label.setText(
                self._format_wrap_detail(hit, doc, text, self._active_wrap_width())
            )

    def _sync_wrap_mode_controls(self):
        mode = self._wrap_mode()
        is_manual = mode == "manual"
        if hasattr(self, "_wrap_relayout_row"):
            self._wrap_relayout_row.setVisible(not is_manual)
        if hasattr(self, "_wrap_manual_row"):
            self._wrap_manual_row.setVisible(is_manual)

    def _active_wrap_width(self) -> int:
        if self._wrap_mode() == "manual" and hasattr(self, "_wrap_manual_width_spin"):
            return int(self._wrap_manual_width_spin.value())
        if hasattr(self, "_wrap_width_spin"):
            return int(self._wrap_width_spin.value())
        return 36

    def _wrap_font_value(self) -> int | None:
        """Body ``\\f[N]`` for Manual wrap, or ``None`` when 0 (leave fonts alone)."""
        spin = getattr(self, "_wrap_font_spin", None)
        if spin is not None:
            value = int(spin.value())
            return value if value > 0 else None
        try:
            value = int(self._setting("wrap_fix_font", 18) or 18)
        except (TypeError, ValueError):
            return 18
        return value if value > 0 else None

    def _on_wrap_manual_width_changed(self, value: int):
        self._save_setting("wrap_fix_manual_width", value)
        self._update_wrap_preview()
        hit = self._current_wrap_hit
        doc = self._current_wrap_doc
        if hit is not None and doc is not None and hasattr(self, "_wrap_detail_label"):
            text = self._current_wrap_line_text() or hit.text
            self._wrap_detail_label.setText(
                self._format_wrap_detail(hit, doc, text, value)
            )

    def _on_wrap_font_changed(self, value: int):
        self._save_setting("wrap_fix_font", value)
        self._update_wrap_preview()
        hit = self._current_wrap_hit
        doc = self._current_wrap_doc
        if hit is not None and doc is not None and hasattr(self, "_wrap_detail_label"):
            text = self._current_wrap_line_text() or hit.text
            self._wrap_detail_label.setText(
                self._format_wrap_detail(hit, doc, text, self._active_wrap_width())
            )

    def _wrap_max_lines_value(self) -> int:
        spin = getattr(self, "_wrap_max_lines_spin", None)
        if spin is not None:
            return int(spin.value())
        try:
            return int(self._setting("wrap_fix_max_lines", 0) or 0)
        except (TypeError, ValueError):
            return 0

    def _on_wrap_max_lines_changed(self, value: int):
        self._save_setting("wrap_fix_max_lines", value)

    def _on_wrap_width_changed(self, value: int):
        self._save_setting("wrap_fix_width", value)
        self._update_wrap_preview()
        hit = self._current_wrap_hit
        doc = self._current_wrap_doc
        if hit is not None and doc is not None and hasattr(self, "_wrap_detail_label"):
            text = self._current_wrap_line_text() or hit.text
            self._wrap_detail_label.setText(self._format_wrap_detail(hit, doc, text, value))

    def _load_names_geometry_into_spins(self, hit: wolf_ws.WrapHit):
        """Prefer wolfdawn-roles.json, then wrap_profile, for names category geometry."""
        width = None
        max_lines = None
        font = None
        if self._current_wrap_path is not None:
            roles = wolf_names.load_name_wrap_roles(
                wolf_names.roles_json_path_for_names(self._current_wrap_path)
            )
            role = wolf_names.get_name_wrap_role(roles, hit.sheet_name)
            if role:
                if role.get("width"):
                    try:
                        width = int(role["width"])
                    except (TypeError, ValueError):
                        pass
                if role.get("maxLines") is not None:
                    try:
                        max_lines = int(role["maxLines"])
                    except (TypeError, ValueError):
                        pass
                if role.get("font"):
                    try:
                        font = int(role["font"])
                    except (TypeError, ValueError):
                        pass
        work = self._wolf_json_work_dir()
        if work is not None:
            profile = wolf_ws.load_wrap_profile(work)
            if width is None:
                # 0 = JP auto for names-wrap; do not fall back to DB default 36.
                width = wolf_ws.get_sheet_width(profile, hit.sheet_name, default=0)
            if max_lines is None:
                max_lines = wolf_ws.get_sheet_max_lines(profile, hit.sheet_name, default=0)
        if width is None:
            width = 0
        if max_lines is None:
            max_lines = 0
        self._wrap_width_spin.blockSignals(True)
        self._wrap_width_spin.setValue(int(width))
        self._wrap_width_spin.blockSignals(False)
        if hasattr(self, "_wrap_manual_width_spin") and width > 0:
            self._wrap_manual_width_spin.blockSignals(True)
            self._wrap_manual_width_spin.setValue(int(width))
            self._wrap_manual_width_spin.blockSignals(False)
        if hasattr(self, "_wrap_max_lines_spin"):
            self._wrap_max_lines_spin.blockSignals(True)
            self._wrap_max_lines_spin.setValue(int(max_lines))
            self._wrap_max_lines_spin.blockSignals(False)
        if font is not None and hasattr(self, "_wrap_font_spin"):
            self._wrap_font_spin.blockSignals(True)
            self._wrap_font_spin.setValue(int(font))
            self._wrap_font_spin.blockSignals(False)

    def _format_wrap_detail(
        self,
        hit: wolf_ws.WrapHit,
        doc: dict | None,
        text: str,
        width: int,
    ) -> str:
        kind_labels = {
            "db": "Database sheet",
            "names": "Names category",
            "gamedat": "Game.dat",
            "map": "Map dialogue",
            "common": "CommonEvent dialogue",
        }
        kind_lbl = kind_labels.get(hit.kind, hit.kind)
        scope = (
            wolf_ws.scope_stats(doc, hit, width)
            if doc is not None
            else wolf_ws.ScopeStats(label=wolf_ws.scope_label(hit, doc), total=0, overflow=0)
        )
        overflow_note = (
            f" · {scope.overflow} of {scope.total} lines overflow at width {width}"
            if scope.total
            else ""
        )
        if hit.kind == "names":
            mode = self._wrap_mode()
            if mode == "manual":
                font = self._wrap_font_value()
                font_note = (
                    "fonts unchanged"
                    if font is None
                    else f"body \\f[{font}], emphasis \\f scales with body"
                )
                return (
                    f"{kind_lbl}: {hit.sheet_name}  ·  {hit.json_file}  ·  "
                    f"entry #{hit.row}  ·  Manual wrap={width}, {font_note}"
                )
            lines = self._wrap_max_lines_value()
            geom = (
                f"width={'auto' if width <= 0 else width}"
                + (f", max lines={lines}" if lines > 0 else ", max lines=auto")
            )
            return (
                f"{kind_lbl}: {hit.sheet_name}  ·  {hit.json_file}  ·  "
                f"entry #{hit.row}  ·  Relayout {geom}  ·  "
                "Wrap all in group → wolf names-wrap (JP slots + \\f shrink)"
            )
        if hit.kind == "db":
            return (
                f"{kind_lbl}: {hit.sheet_name}  ·  {hit.json_file}  ·  "
                f"row {hit.row}  ·  {hit.field_name}{overflow_note}"
            )
        if hit.kind in ("map", "common"):
            fmt = wolf_ws.wrap_format_label(self._current_wrap_speaker_src())
            return (
                f"{kind_lbl}: {scope.label}  ·  {hit.json_file}  ·  "
                f"{hit.field_name}{overflow_note}  ·  "
                f"shared wrap: {fmt}"
            )
        return (
            f"{kind_lbl}: {hit.sheet_name}  ·  {hit.json_file}  ·  "
            f"{hit.field_name}{overflow_note}"
        )

    def _current_wrap_speaker_kw(self) -> dict[str, str]:
        """speaker_src / speaker for nameplate-aware wrap preview."""
        line = None
        if self._current_wrap_doc is not None and self._current_wrap_hit_id is not None:
            line = wolf_ws.locate_line(
                self._current_wrap_doc, self._current_wrap_hit_id
            )
        if isinstance(line, dict):
            return {
                "speaker_src": str(line.get("speaker_src") or ""),
                "speaker": str(line.get("speaker") or ""),
            }
        return {"speaker_src": "", "speaker": ""}

    def _update_wrap_preview(self):
        if not hasattr(self, "_wrap_preview"):
            return
        text = self._current_wrap_line_text()
        if not text.strip() and self._current_wrap_hit is None:
            self._wrap_preview.clear()
            if hasattr(self, "_wrap_preview_label"):
                self._wrap_preview_label.setText("Wrap preview")
                self._wrap_preview_label.setStyleSheet(
                    "color:#858585;font-size:11px;background:transparent;"
                )
            return
        if self._current_wrap_hit is not None and not text.strip():
            text = self._current_wrap_hit.text
        width = self._active_wrap_width()
        body_font = self._wrap_font_value() if self._wrap_mode() == "manual" else None
        plate_kw = self._current_wrap_speaker_kw()
        # Manual: preview scaled fonts. Relayout + max lines: preview fit-to-box.
        preview_src = text
        preview_width = width
        if body_font is not None and preview_src.strip():
            prefix, nameplate, body = wolf_ws.split_nameplate_body(
                preview_src, **plate_kw
            )
            work = body if nameplate else preview_src
            work, _ = wolf_codes.scale_font_sizes(work, body_font)
            preview_src = (
                wolf_ws.join_nameplate_body(prefix, nameplate, work)
                if nameplate
                else work
            )
        elif self._wrap_mode() == "relayout" and width > 0:
            max_lines = self._wrap_max_lines_value()
            if max_lines > 0 and preview_src.strip():
                box_font = None
                line = None
                if self._current_wrap_doc and self._current_wrap_hit_id:
                    line = wolf_ws.locate_line(
                        self._current_wrap_doc, self._current_wrap_hit_id
                    )
                if isinstance(line, dict):
                    source = line.get("source")
                    if isinstance(source, str) and wolf_codes.detect_font_sizes(source):
                        box_font = wolf_codes.infer_base_font_size(source)
                preview_src, _ = wolf_ws.fit_text_to_box(
                    preview_src,
                    width,
                    max_lines=max_lines,
                    box_font=box_font,
                    **plate_kw,
                )
                # Soft breaks are already final; don't reflow at the narrow cell width.
                _, nameplate, body = wolf_ws.split_nameplate_body(
                    preview_src, **plate_kw
                )
                measure = body if nameplate else preview_src
                preview_width = max(
                    width,
                    dazedwrap.max_line_visible_length(measure),
                )
        summary = wolf_ws.wrap_preview_summary(
            preview_src, preview_width, **plate_kw
        )
        preview_html = wolf_ws.format_wrap_preview_html(
            preview_src if self._wrap_mode() == "relayout" else text,
            preview_width,
            body_font=body_font,
            **plate_kw,
        )
        info = wolf_ws.wrap_preview_info(preview_src, preview_width, **plate_kw)
        if hasattr(self, "_wrap_preview_label"):
            if summary:
                soft = wolf_ws.count_body_soft_lines(preview_src, **plate_kw)
                max_lines = self._wrap_max_lines_value()
                if (
                    self._wrap_mode() == "relayout"
                    and max_lines > 0
                    and soft > 0
                ):
                    summary = f"{summary}  ·  {soft}/{max_lines} soft lines"
                self._wrap_preview_label.setText(summary)
                over_lines = (
                    self._wrap_mode() == "relayout"
                    and max_lines > 0
                    and soft > max_lines
                )
                color = (
                    "#ce9178"
                    if info.get("needs_wrap") or over_lines
                    else "#8fbc8f"
                )
                self._wrap_preview_label.setStyleSheet(
                    f"color:{color};font-size:11px;background:transparent;"
                )
            else:
                self._wrap_preview_label.setText("Wrap preview")
                self._wrap_preview_label.setStyleSheet(
                    "color:#858585;font-size:11px;background:transparent;"
                )
        self._wrap_preview.setHtml(preview_html)
        over_lines = False
        if self._wrap_mode() == "relayout":
            max_lines = self._wrap_max_lines_value()
            over_lines = (
                max_lines > 0
                and wolf_ws.count_body_soft_lines(preview_src, **plate_kw) > max_lines
            )
        border = "#ce9178" if info.get("needs_wrap") or over_lines else "#007acc"
        self._wrap_preview.setStyleSheet(
            "QTextEdit{background-color:#1e1e1e;color:#d4d4d4;border:1px solid #3c3c3c;"
            f"border-left:3px solid {border};padding:6px;}}"
        )

    def _run_wrap_search(self):
        query = self._wrap_search_edit.text().strip()
        if not query:
            return
        tdir, fdir = self._translated_and_files_dirs()
        extra = self._wrap_search_extra_dirs()
        hits = wolf_ws.search_translated_text(
            query, tdir, files_dir=fdir, extra_dirs=extra,
        )
        self._wrap_results_list.clear()
        self._current_wrap_hit = None
        self._current_wrap_text = ""
        if not hits:
            where = "translated/, files/"
            if extra:
                where += f", {WORK_DIR_NAME}/"
            item = QListWidgetItem(f"No matches in {where}.")
            item.setFlags(Qt.ItemIsEnabled)
            self._wrap_results_list.addItem(item)
            self._wrap_detail_label.setText("No matches.")
            self._update_wrap_preview()
            return
        width = self._active_wrap_width()
        list_w = max(self._wrap_results_list.viewport().width(), 320)
        metrics = self._wrap_results_list.fontMetrics()
        for hit in hits:
            summary = hit.summary(width)
            item = QListWidgetItem(summary)
            item.setData(Qt.UserRole, hit.hit_id)
            item.setData(Qt.UserRole + 1, hit)
            # Size for wrapped two-line (or more) summaries without eliding.
            text_w = max(list_w - 24, 200)
            br = metrics.boundingRect(0, 0, text_w, 4000, Qt.TextWordWrap, summary)
            item.setSizeHint(QSize(list_w, max(br.height() + 16, 48)))
            self._wrap_results_list.addItem(item)
        self._wrap_results_list.setCurrentRow(0)
        self._wrap_status_label.setText(f"Found {len(hits)} match(es).")

    def _on_wrap_hit_selected(self, current: QListWidgetItem | None, _previous):
        if current is None:
            return
        hit = current.data(Qt.UserRole + 1)
        if not isinstance(hit, wolf_ws.WrapHit):
            return
        self._current_wrap_hit = hit
        self._current_wrap_hit_id = hit.hit_id
        tdir, fdir = self._translated_and_files_dirs()
        extra = self._wrap_search_extra_dirs()
        path, doc, line = wolf_ws.load_hit_from_id(
            tdir, hit.hit_id, files_dir=fdir, extra_dirs=extra,
        )
        self._current_wrap_path = path
        self._current_wrap_doc = doc
        if hit.kind == "names":
            self._load_names_geometry_into_spins(hit)
        elif hit.kind in ("map", "common"):
            self._load_dialogue_geometry_into_spins()
        else:
            w = self._wrap_profile_width(hit.sheet_name, kind=hit.kind)
            self._wrap_width_spin.blockSignals(True)
            self._wrap_width_spin.setValue(w)
            self._wrap_width_spin.blockSignals(False)
            if hasattr(self, "_wrap_max_lines_spin"):
                work = self._wolf_json_work_dir()
                max_lines = 0
                if work is not None:
                    max_lines = wolf_ws.get_sheet_max_lines(
                        wolf_ws.load_wrap_profile(work), hit.sheet_name, default=0
                    )
                self._wrap_max_lines_spin.blockSignals(True)
                self._wrap_max_lines_spin.setValue(max_lines)
                self._wrap_max_lines_spin.blockSignals(False)
        if line is not None:
            text = str(line.get("text") or hit.text)
        else:
            text = hit.text
        self._current_wrap_text = text
        self._wrap_detail_label.setText(
            self._format_wrap_detail(hit, doc, text, self._active_wrap_width())
        )
        self._sync_wrap_font_controls(text)
        self._update_wrap_preview()

    def _sync_wrap_font_controls(self, text: str):
        if not hasattr(self, "_wrap_font_spin"):
            return
        sizes = wolf_codes.detect_font_sizes(text)
        base = wolf_codes.infer_base_font_size(text) if sizes else None
        keep_fonts = int(self._wrap_font_spin.value()) <= 0
        if sizes and base is not None:
            # Don't overwrite an explicit "0 (keep)" choice when selecting a line.
            if not keep_fonts:
                self._wrap_font_spin.blockSignals(True)
                self._wrap_font_spin.setValue(base)
                self._wrap_font_spin.blockSignals(False)
            shown = ", ".join(f"\\f[{s}]" for s in sizes[:4])
            if len(sizes) > 4:
                shown += ", …"
            keep_note = " — Wrap keeps these" if keep_fonts else f" (body ≈ \\f[{base}])"
            self._wrap_font_detect_label.setText(f"In text: {shown}{keep_note}")
        elif keep_fonts:
            self._wrap_font_detect_label.setText(
                "No \\f[N] — Wrap will not add any (font = 0)"
            )
        else:
            self._wrap_font_detect_label.setText(
                "No \\f[N] yet — Wrap adds leading body \\f"
            )

    def _wrap_current_row(self):
        if not self._current_wrap_hit_id or not self._current_wrap_path or not self._current_wrap_doc:
            QMessageBox.information(self, "Fix wrapping", "Select a search result first.")
            return

        if self._wrap_mode() == "manual":
            width = self._active_wrap_width()
            font = self._wrap_font_value()
            changed = wolf_ws.wrap_hit_manual(
                self._current_wrap_path,
                self._current_wrap_doc,
                self._current_wrap_hit_id,
                width,
                font=font,
            )
            if self._current_wrap_hit:
                self._remember_sheet_width(
                    self._current_wrap_hit.sheet_name,
                    width,
                    self._current_wrap_hit.json_file,
                    font=font,
                    kind=self._current_wrap_hit.kind,
                )
            path, doc, line = wolf_ws.load_hit_from_id(
                self._translated_and_files_dirs()[0],
                self._current_wrap_hit_id,
                files_dir=self._translated_and_files_dirs()[1],
                extra_dirs=self._wrap_search_extra_dirs(),
            )
            self._current_wrap_path = path
            self._current_wrap_doc = doc
            if line is not None:
                text = str(line.get("text") or "")
                self._current_wrap_text = text
                self._sync_wrap_font_controls(text)
            if font is None:
                msg = (
                    f"Manual wrap at width {width} (fonts unchanged)."
                    if changed
                    else "Already matches Manual wrap (width only)."
                )
            else:
                msg = (
                    f"Manual wrap at width {width}, body \\f[{font}]."
                    if changed
                    else "Already matches Manual wrap (width + font)."
                )
            self._wrap_status_label.setText(
                msg + " Apply all translations from Step 7 when ready."
            )
            self._log(f"{'✅' if changed else 'ℹ'}  {msg}")
            self._update_wrap_preview()
            return

        # Relayout mode: single-line dazedwrap at cell width (names group uses wolf).
        width = self._wrap_width_spin.value()
        if width <= 0:
            QMessageBox.information(
                self,
                "Fix wrapping",
                "Set Cell width to a positive value before wrapping a single line.\n"
                "For names Relayout, use Wrap all in group (0 = JP auto).",
            )
            return
        max_lines = self._wrap_max_lines_value()
        changed = wolf_ws.wrap_hit_in_file(
            self._current_wrap_path,
            self._current_wrap_doc,
            self._current_wrap_hit_id,
            width,
            max_lines=max_lines or None,
        )
        if self._current_wrap_hit:
            self._remember_sheet_width(
                self._current_wrap_hit.sheet_name,
                width,
                self._current_wrap_hit.json_file,
                max_lines=max_lines or None,
                kind=self._current_wrap_hit.kind,
            )
        path, doc, line = wolf_ws.load_hit_from_id(
            self._translated_and_files_dirs()[0],
            self._current_wrap_hit_id,
            files_dir=self._translated_and_files_dirs()[1],
            extra_dirs=self._wrap_search_extra_dirs(),
        )
        self._current_wrap_path = path
        self._current_wrap_doc = doc
        if line is not None:
            self._current_wrap_text = str(line.get("text") or "")
        if changed:
            if max_lines > 0:
                msg = (
                    f"Relayout at width {width}, max {max_lines} line(s) "
                    f"(shrink \\f if needed)."
                )
            else:
                msg = f"Wrapped line at width {width}."
        else:
            msg = (
                f"Already fits width {width}"
                + (f" / {max_lines} line(s)." if max_lines > 0 else ".")
            )
        self._wrap_status_label.setText(
            msg + " Apply all translations from Step 7 when ready."
        )
        self._log(f"{'✅' if changed else 'ℹ'}  {msg}")
        self._update_wrap_preview()

    def _wrap_current_group(self):
        hit = self._current_wrap_hit
        if not hit or not self._current_wrap_path or not self._current_wrap_doc:
            QMessageBox.information(self, "Fix wrapping", "Select a search result first.")
            return

        if self._wrap_mode() == "manual":
            width = self._active_wrap_width()
            font = self._wrap_font_value()
            tdir = self._translated_and_files_dirs()[0]
            count = wolf_ws.wrap_overflow_manual_in_scope(
                self._current_wrap_path,
                self._current_wrap_doc,
                hit,
                width,
                font=font,
                translated_dir=tdir if hit.kind in ("map", "common") else None,
            )
            self._remember_sheet_width(
                hit.sheet_name, width, hit.json_file, font=font, kind=hit.kind
            )
            if hit.kind == "names":
                roles_path = wolf_names.roles_json_path_for_names(self._current_wrap_path)
                wolf_names.upsert_name_wrap_role(
                    roles_path,
                    hit.sheet_name,
                    width=width,
                    font=font,
                )
            scope = wolf_ws.scope_label(hit, self._current_wrap_doc)
            font_note = (
                "fonts unchanged"
                if font is None
                else f"body \\f[{font}]"
            )
            msg = (
                f"Manual-wrapped {count} line(s) in {scope} "
                f"(width {width}, {font_note})."
            )
            self._wrap_status_label.setText(
                msg + " Apply all translations from Step 7 when ready."
            )
            self._log(f"✅ {msg}")
            self._reload_wrap_hit_editor(hit, width)
            return

        if hit.kind == "names":
            width = self._wrap_width_spin.value()
            max_lines = self._wrap_max_lines_value()
            self._run_names_wrap_on_path(
                self._current_wrap_path,
                note=hit.sheet_name,
                hit=hit,
                width=width if width > 0 else None,
                lines=max_lines or None,
                quiet=False,
            )
            return

        width = self._wrap_width_spin.value()
        if width <= 0:
            QMessageBox.information(
                self,
                "Fix wrapping",
                "Set Cell width to a positive value (halfwidth cells) before wrapping.",
            )
            return
        max_lines = self._wrap_max_lines_value()
        tdir = self._translated_and_files_dirs()[0]
        count = wolf_ws.wrap_overflow_in_scope(
            self._current_wrap_path,
            self._current_wrap_doc,
            hit,
            width,
            max_lines=max_lines or None,
            translated_dir=tdir if hit.kind in ("map", "common") else None,
        )
        self._remember_sheet_width(
            hit.sheet_name,
            width,
            hit.json_file,
            max_lines=max_lines or None,
            kind=hit.kind,
        )
        scope = wolf_ws.scope_label(hit, self._current_wrap_doc)
        if max_lines > 0:
            msg = (
                f"Relayout {count} line(s) in {scope} "
                f"(width {width}, max {max_lines} lines)."
            )
        else:
            msg = f"Wrapped {count} line(s) in {scope} at width {width}."
        self._wrap_status_label.setText(
            msg + " Apply all translations from Step 7 when ready."
        )
        self._log(f"✅ {msg}")
        self._reload_wrap_hit_editor(hit, width)

    def _reload_wrap_hit_editor(self, hit: wolf_ws.WrapHit, width: int):
        path, doc, line = wolf_ws.load_hit_from_id(
            self._translated_and_files_dirs()[0],
            hit.hit_id,
            files_dir=self._translated_and_files_dirs()[1],
            extra_dirs=self._wrap_search_extra_dirs(),
        )
        self._current_wrap_path = path
        self._current_wrap_doc = doc
        if line is not None:
            text = str(line.get("text") or "")
            self._current_wrap_text = text
            self._sync_wrap_font_controls(text)
        if doc is not None:
            self._wrap_detail_label.setText(
                self._format_wrap_detail(
                    hit, doc, self._current_wrap_line_text(), width
                )
            )
        self._update_wrap_preview()

    def _run_names_wrap_on_path(
        self,
        names_path: Path,
        *,
        note: str | None,
        hit: wolf_ws.WrapHit | None = None,
        width: int | None = None,
        lines: int | None = None,
        quiet: bool = False,
    ):
        persist_note = note
        persist_width = width
        persist_lines = lines

        def task(log, progress=None):
            if persist_note and (
                (persist_width is not None and int(persist_width) > 0)
                or (persist_lines is not None and int(persist_lines) > 0)
            ):
                roles_path = wolf_names.roles_json_path_for_names(names_path)
                wolf_names.upsert_name_wrap_role(
                    roles_path,
                    persist_note,
                    width=persist_width,
                    max_lines=persist_lines,
                )
                log(
                    f"Saved nameWraps rule for {persist_note} → {roles_path.name}"
                    + (f" width={persist_width}" if persist_width else "")
                    + (f" maxLines={persist_lines}" if persist_lines else "")
                )
                work = self._wolf_json_work_dir()
                if work is not None and persist_width and int(persist_width) > 0:
                    wolf_ws.set_sheet_width(
                        work,
                        persist_note,
                        int(persist_width),
                        json_file=NAMES_JSON,
                        max_lines=persist_lines,
                    )
            ok, summary = wolf_names.apply_names_wrap(
                names_path,
                note=note,
                width=width,
                lines=lines,
                dry_run=False,
                log_fn=log,
            )
            if not ok:
                return False, summary
            self._sync_translated_json_to_wolf_json(NAMES_JSON, self._work_dir())
            roles_src = wolf_names.roles_json_path_for_names(names_path)
            if roles_src.is_file():
                work = self._work_dir()
                if work.is_dir():
                    dest = work / roles_src.name
                    try:
                        if roles_src.resolve() != dest.resolve():
                            shutil.copy2(roles_src, dest)
                    except Exception:
                        pass
            return True, summary

        def _after(ok: bool, summary: str):
            if not ok:
                return
            if hit is not None:
                self._reload_wrap_hit_editor(hit, self._active_wrap_width())
            if not quiet and hasattr(self, "_wrap_status_label"):
                self._wrap_status_label.setText(
                    summary + " Apply all translations from Step 7 when ready."
                )

        self._run_task(task, on_done=_after)

    def _tool_root(self) -> Path:
        """DazedTL project root (``files/``, ``translated/``, etc.)."""
        return Path(__file__).resolve().parent.parent

    def _translated_path(self, json_name: str) -> Path | None:
        """Absolute path to ``translated/<json_name>`` when it exists."""
        p = self._tool_root() / "translated" / json_name
        return p if p.is_file() else None

    def _translated_or_source(self, json_name: str) -> Path | None:
        """Prefer translated/<name>; fall back to files/<name>."""
        root = self._tool_root()
        for sub in ("translated", "files"):
            p = root / sub / json_name
            if p.is_file():
                return p
        return None

    def _injectable_filenames(self, source_dir: Path | None = None) -> list[str]:
        """JSON files in *source_dir* (default translated/) the manifest can inject."""
        from util.wolfdawn import inject as wolf_inject

        manifest = self._read_manifest()
        if not manifest:
            return []
        root = source_dir if source_dir is not None else self._tool_root() / "translated"
        return wolf_inject.list_injectable(root, manifest.get("entries", []))

    def _sync_translated_json_to_wolf_json(
        self, json_name: str, game_json_dir: Path
    ) -> tuple[bool, str | None]:
        """Copy one translated/ (or files/) JSON into the game's wolf_json/ folder."""
        src = self._translated_or_source(json_name)
        if src is None:
            return False, "no translated copy"
        dest = game_json_dir / json_name
        try:
            if src.resolve() == dest.resolve():
                return True, None
        except Exception:
            pass
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            return True, None
        except Exception as exc:
            return False, str(exc)

    def _sync_json_to_dir(
        self, json_name: str, source_dir: Path, dest_dir: Path
    ) -> tuple[bool, str | None]:
        """Copy one JSON from *source_dir* into *dest_dir* (e.g. files/ or translated/)."""
        src = source_dir / json_name
        if not src.is_file():
            return False, "source missing"
        dest = dest_dir / json_name
        try:
            if src.resolve() == dest.resolve():
                return True, None
        except Exception:
            pass
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            return True, None
        except Exception as exc:
            return False, str(exc)

    def _inject(
        self,
        selected: set[str],
        *,
        source_dir: Path | None = None,
        sync_to_wolf_json: bool = True,
        sync_to_files: bool = False,
        sync_to_translated: bool = False,
    ):
        """Inject the selected JSON files into live Data/.

        *source_dir* defaults to ``translated/``. When injecting from the game's
        ``wolf_json/``, pass that path and set *sync_to_wolf_json* False (the
        source already is wolf_json/). Set *sync_to_files* / *sync_to_translated*
        to also copy the injected JSON into the tool's ``files/`` and/or
        ``translated/`` folders.
        """
        if not self._require_manifest():
            return
        manifest = self._read_manifest()
        en_punct = self._inject_flag_en_punct()
        game_json_dir = self._work_dir()
        tool_root = self._tool_root()
        files_dir = tool_root / "files"
        translated_dir = tool_root / "translated"
        inject_dir = (
            Path(source_dir)
            if source_dir is not None
            else translated_dir
        )

        def task(log, progress=None):
            from util.wolfdawn import inject as wolf_inject

            entries = manifest["entries"]
            data_dir_path = Path(manifest["data_dir"])
            game_root = Path(manifest.get("root") or self._game_root)
            originals_dir = game_root / WORK_DIR_NAME / "originals"

            self._ensure_originals(manifest, log, progress, quiet=True)

            log(f"Inject source: {inject_dir}")
            # allow_code_drift=False: inject still auto-passes it for \\f shrink.
            report = wolf_inject.inject_selected(
                sorted(selected),
                manifest_entries=entries,
                data_dir=data_dir_path,
                originals_dir=originals_dir,
                translated_dir=inject_dir,
                game_root=game_root,
                allow_code_drift=False,
                en_punct=en_punct,
                log_fn=log,
            )

            if sync_to_wolf_json and game_json_dir is not None:
                for json_name in sorted(selected):
                    ok, err = self._sync_translated_json_to_wolf_json(
                        json_name, game_json_dir
                    )
                    if not ok:
                        report.sync_failures.append(
                            (json_name, err or "unknown error")
                        )
                        log(f"  ✗ sync {json_name}: {err}")

            for label, enabled, dest in (
                ("files/", sync_to_files, files_dir),
                ("translated/", sync_to_translated, translated_dir),
            ):
                if not enabled:
                    continue
                synced = 0
                for json_name in sorted(selected):
                    ok, err = self._sync_json_to_dir(
                        json_name, inject_dir, dest
                    )
                    if not ok:
                        report.sync_failures.append(
                            (json_name, f"{label}: {err or 'unknown error'}")
                        )
                        log(f"  ✗ sync {label}{json_name}: {err}")
                    else:
                        synced += 1
                if synced:
                    log(f"Synced {synced} file(s) → {label}")

            dialog = wolf_inject.format_report_dialog(report)
            status = wolf_inject.format_report_status(report)
            inject_state["dialog"] = dialog
            inject_state["report"] = report
            inject_state["selected"] = set(selected)
            log(status)
            return report.ok, status

        def _after_inject(ok: bool, msg: str):
            dialog = inject_state.get("dialog")
            report = inject_state.get("report")
            if dialog:
                title, body = dialog
                QMessageBox.warning(self, title, body)
            elif report is not None and not report.succeeded and not (
                report.failed or report.sync_failures
            ):
                QMessageBox.information(self, "Inject", msg or "Nothing was injected.")
            # Full success: no popup (per-file detail is already in the log).

        inject_state: dict = {}
        self._run_task(task, on_done=_after_inject)

    def _step_strip_label(self, idx: int, *, done: bool) -> str:
        """Compact strip text: number + short name, optional checkmark for done."""
        short_names = (
            "Project",
            "Prep",
            "Setup",
            "Names",
            "Database",
            "Maps",
            "Precheck",
            "Inject",
            "Package",
            "Wrap",
        )
        name = short_names[idx] if 0 <= idx < len(short_names) else str(idx)
        mark = "✓" if done else ""
        return f"{mark}{idx}\n{name}"

    def _refresh_step_strip(self, current: int | None = None):
        if current is None:
            current = self._step_tabs.currentIndex() if hasattr(self, "_step_tabs") else 0
        if hasattr(self, "_step_rail"):
            self._step_rail.set_done(set(self._step_done))
            self._step_rail.set_current(current)
            return
        for i, btn in enumerate(getattr(self, "_step_buttons", [])):
            done = i in self._step_done
            btn.setText(self._step_strip_label(i, done=done))
            btn.setProperty("done", "true" if done else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            if i == current and not btn.isChecked():
                btn.blockSignals(True)
                btn.setChecked(True)
                btn.blockSignals(False)
            elif i != current and btn.isChecked():
                btn.blockSignals(True)
                btn.setChecked(False)
                btn.blockSignals(False)

    def _goto_step(self, idx: int):
        if not hasattr(self, "_step_tabs"):
            return
        idx = max(0, min(idx, self._step_tabs.count() - 1))
        if self._step_tabs.currentIndex() != idx:
            self._step_tabs.setCurrentIndex(idx)
        else:
            # Re-selecting the current step still runs enter hooks (e.g. Step 4
            # discovery refresh) so the strip click always feels live.
            self._on_step_changed(idx)

    def _advance_step(self, from_idx: int):
        """Mark *from_idx* done and move to the next step."""
        self._step_done.add(from_idx)
        self._goto_step(from_idx + 1)

    def _on_step_changed(self, idx: int):
        previous = self._current_step_index
        self._current_step_index = idx
        self._refresh_step_strip(idx)
        if previous == 0 and idx != 0:
            self._auto_import_if_needed()
        self._enter_step(idx)

    def _enter_step(self, idx: int):
        """Refresh step-local data whenever a step is shown or re-selected."""
        # Index 3 == Names: refresh the per-name safety summary.
        if idx == 3:
            self._refresh_names_summary()
        # Index 4 == Database: refresh discovery report and sheet list.
        elif idx == 4:
            self._refresh_db_discovery()
        # Index 6 == Precheck: keep the file list in sync with translated/.
        elif idx == 6:
            self._refresh_precheck_list()
        # Index 7 == Inject: keep the file list in sync with translated/.
        elif idx == 7:
            self._refresh_inject_list()

    def _fill_injectable_checklist(self, list_widget: QListWidget):
        """Populate a checkable file list from translated/ + manifest (precheck)."""
        list_widget.clear()
        if not self._read_manifest():
            item = QListWidgetItem("Run Step 0 (extract) first - no manifest found.")
            item.setFlags(Qt.ItemIsEnabled)
            list_widget.addItem(item)
            return
        files = self._injectable_filenames()
        if not files:
            item = QListWidgetItem("No injectable files in translated/ yet.")
            item.setFlags(Qt.ItemIsEnabled)
            list_widget.addItem(item)
            return
        for json_name in files:
            item = QListWidgetItem(json_name)
            item.setData(Qt.UserRole, json_name)
            item.setFlags(
                Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable
            )
            item.setCheckState(Qt.Unchecked)
            list_widget.addItem(item)

    def _refresh_precheck_list(self):
        if not hasattr(self, "precheck_list"):
            return
        self._fill_injectable_checklist(self.precheck_list)

    def _refresh_inject_list(self):
        """Show every injectable file (read-only). Inject always uses the full set."""
        if not hasattr(self, "inject_list"):
            return
        self.inject_list.clear()
        if hasattr(self, "_inject_count_label"):
            self._inject_count_label.setText("")
        if not self._read_manifest():
            item = QListWidgetItem("Run Step 0 (extract) first - no manifest found.")
            item.setFlags(Qt.ItemIsEnabled)
            self.inject_list.addItem(item)
            return
        files = self._injectable_filenames()
        if not files:
            item = QListWidgetItem("No injectable files in translated/ yet.")
            item.setFlags(Qt.ItemIsEnabled)
            self.inject_list.addItem(item)
            return
        for json_name in files:
            item = QListWidgetItem(json_name)
            item.setFlags(Qt.ItemIsEnabled)
            self.inject_list.addItem(item)
        if hasattr(self, "_inject_count_label"):
            self._inject_count_label.setText(
                f"{len(files)} file(s) will be injected together."
            )

    def _selected_checklist_files(self, list_widget: QListWidget) -> set[str]:
        selected: set[str] = set()
        for i in range(list_widget.count()):
            it = list_widget.item(i)
            if (it.flags() & Qt.ItemIsUserCheckable) and it.checkState() == Qt.Checked:
                name = it.data(Qt.UserRole)
                if name:
                    selected.add(name)
        return selected

    def _selected_precheck_files(self) -> set[str]:
        return self._selected_checklist_files(self.precheck_list)

    def _set_checklist_checks(self, list_widget: QListWidget, checked: bool):
        state = Qt.Checked if checked else Qt.Unchecked
        for i in range(list_widget.count()):
            it = list_widget.item(i)
            if it.flags() & Qt.ItemIsUserCheckable:
                it.setCheckState(state)

    def _precheck_inject_selected(self):
        if not self._require_manifest():
            return
        selected = self._selected_precheck_files()
        if not selected:
            QMessageBox.information(
                self,
                "Nothing selected",
                "Select one or more files, then click Preview selected injection.",
            )
            return
        self._run_inject_precheck(selected)

    def _precheck_inject_all(self):
        if not self._require_manifest():
            return
        files = self._injectable_filenames()
        if not files:
            QMessageBox.information(
                self,
                "Nothing to precheck",
                "No injectable files found in translated/.",
            )
            return
        self._run_inject_precheck(set(files))

    def _inject_flag_en_punct(self) -> bool:
        if hasattr(self, "en_punct_cb"):
            return self.en_punct_cb.isChecked()
        return self._setting("en_punct", "true") == "true"

    def _run_inject_precheck(self, selected: set[str]):
        manifest = self._read_manifest()
        en_punct = self._inject_flag_en_punct()
        state: dict = {}

        def task(log, progress=None):
            from util import wolfdawn
            from util.wolfdawn import inject_precheck as wolf_pre
            from util.wolfdawn import names as wolf_names

            translated = self._tool_root() / "translated"
            name_notes: list[str] = []

            # Name hygiene first (same work the old Step 7 buttons did).
            if (translated / "names.json").is_file():
                report_names = wolf_names.reconcile_translated_dir(
                    translated, dry_run=False
                )
                reconcile_msg = wolf_names.format_reconcile_summary(report_names)
                log(reconcile_msg)
                for change in report_names.changes[:40]:
                    log(
                        f"  {change.json_file}: {change.source!r} "
                        f"{change.old_text!r} → {change.new_text!r} ({change.reason})"
                    )
                if len(report_names.changes) > 40:
                    log(f"  … and {len(report_names.changes) - 40} more")
                name_notes.append(reconcile_msg)
            else:
                log("Name reconcile skipped (no translated/names.json).")

            json_files = []
            for entry in manifest["entries"]:
                p = self._translated_or_source(entry["json"])
                if p:
                    json_files.append(str(p))
            if json_files:
                check = wolfdawn.names_check(json_files, log_fn=log)
                if check.returncode == 0:
                    name_notes.append("Name usage is consistent across files.")
                else:
                    name_notes.append(
                        "names-check reported inconsistencies (see log)."
                    )
            else:
                name_notes.append("names-check skipped (no JSON found).")

            entries = manifest["entries"]
            data_dir_path = Path(manifest["data_dir"])
            game_root = Path(manifest.get("root") or self._game_root)
            originals_dir = game_root / WORK_DIR_NAME / "originals"
            self._ensure_originals(manifest, log, progress, quiet=True)
            # Font-size drift from wrap/names-wrap is auto-allowed inside precheck.
            report = wolf_pre.precheck_selected(
                sorted(selected),
                manifest_entries=entries,
                data_dir=data_dir_path,
                originals_dir=originals_dir,
                translated_dir=translated,
                allow_code_drift=False,
                en_punct=en_punct,
                log_fn=log,
            )
            state["report"] = report
            state["name_notes"] = name_notes
            summary = wolf_pre.format_precheck_summary(report)
            if name_notes:
                summary = " · ".join(name_notes) + "\n" + summary
            return True, summary

        def _after(ok: bool, msg: str):
            from util.wolfdawn import inject_precheck as wolf_pre

            report = state.get("report")
            if not report:
                self._inject_precheck_label.setText(msg or "Precheck failed.")
                return
            self._populate_inject_precheck(report)
            label = wolf_pre.format_precheck_summary(report)
            notes = state.get("name_notes") or []
            if notes:
                label = " · ".join(notes) + "\n" + label
            self._inject_precheck_label.setText(label)
            if report.safety_issues:
                QMessageBox.warning(
                    self,
                    "Inject precheck",
                    (msg or label)
                    + "\n\nSelect a safety row below, fix the text, Save line, then re-run precheck.",
                )
            else:
                QMessageBox.information(self, "Inject precheck", msg)

        self._run_task(task, on_done=_after)

    def _populate_inject_precheck(self, report):
        from util.wolfdawn import inject_precheck as wolf_pre

        self._inject_issue_list.clear()
        self._inject_issue_edit.clear()
        self._inject_issue_meta.setText("")
        issues = wolf_pre.issues_for_ui(report)
        self._inject_precheck_issues = issues
        for issue in issues:
            item = QListWidgetItem(issue.summary())
            item.setData(Qt.UserRole, issue)
            item.setForeground(QColor("#f48771"))
            self._inject_issue_list.addItem(item)
            fm = self._inject_issue_list.fontMetrics()
            item.setSizeHint(
                QSize(
                    self._inject_issue_list.viewport().width(),
                    max(fm.height() * 3 + 10, 48),
                )
            )

    def _on_inject_issue_selected(self, current, _previous):
        if current is None:
            self._inject_issue_edit.clear()
            self._inject_issue_meta.setText("")
            return
        issue = current.data(Qt.UserRole)
        if issue is None:
            return
        meta_parts = [issue.json_file, issue.locator, issue.message]
        self._inject_issue_meta.setText(" · ".join(p for p in meta_parts if p))
        self._inject_issue_edit.setPlainText(issue.text or issue.source or "")

    def _save_inject_issue_line(self):
        item = self._inject_issue_list.currentItem()
        if item is None:
            QMessageBox.information(self, "Save line", "Select a precheck row first.")
            return
        issue = item.data(Qt.UserRole)
        if issue is None:
            return
        from util.wolfdawn import inject_precheck as wolf_pre

        new_text = self._inject_issue_edit.toPlainText()
        ok, err = wolf_pre.apply_issue_text(
            self._tool_root() / "translated", issue, new_text
        )
        if not ok:
            QMessageBox.warning(self, "Save line", err or "Could not save.")
            return
        item.setText(issue.summary())
        self._log(f"Saved precheck edit: {issue.json_file} · {issue.locator}")
        QMessageBox.information(
            self,
            "Save line",
            "Saved. Re-run Precheck to confirm the safety skip is gone.",
        )

    def _inject_all(self):
        if not self._require_manifest():
            return
        files = self._injectable_filenames()
        if not files:
            QMessageBox.information(
                self, "Nothing to inject",
                "No injectable files found in translated/. Translate something first.",
            )
            return
        self._inject(set(files))

    def _inject_all_from_wolf_json(self):
        """Inject every injectable JSON from the game's wolf_json/ folder."""
        if not self._require_manifest():
            return
        if not self._game_root:
            QMessageBox.information(
                self,
                "Apply from wolf_json",
                "No game folder selected. Detect a project in Step 0 first.",
            )
            return
        work = self._work_dir()
        if not work.is_dir():
            QMessageBox.information(
                self,
                "Apply from wolf_json",
                f"No wolf_json/ folder at {work}.",
            )
            return
        files = self._injectable_filenames(work)
        if not files:
            QMessageBox.information(
                self,
                "Nothing to inject",
                f"No injectable JSON found in {work}.",
            )
            return
        reply = QMessageBox.question(
            self,
            "Apply from wolf_json",
            f"About to inject {len(files)} file(s) from wolf_json/.\n\n"
            "Also copy those JSON into files/ and translated/ so the tool "
            "keeps the same progress (overwrites matching names)?\n\n"
            "Yes = inject and sync to files/ + translated/\n"
            "No = inject only, leave files/ and translated/ as-is\n"
            "Cancel = do nothing",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            QMessageBox.Yes,
        )
        if reply == QMessageBox.Cancel:
            self._log("Apply from wolf_json cancelled.")
            return
        sync_tool_dirs = reply == QMessageBox.Yes
        if sync_tool_dirs:
            self._log(
                f"Will sync {len(files)} wolf_json/ file(s) → files/ and "
                "translated/ after inject."
            )
        else:
            self._log(
                "Skipping wolf_json/ → files/ + translated/ sync; "
                "leaving those folders as-is."
            )
        self._inject(
            set(files),
            source_dir=work,
            sync_to_wolf_json=False,
            sync_to_files=sync_tool_dirs,
            sync_to_translated=sync_tool_dirs,
        )

    def _layout_restore_all(self):
        """Re-run wolf layout-restore on every injectable translated JSON."""
        files = self._injectable_filenames()
        if not files:
            QMessageBox.information(
                self,
                "Layout-restore",
                "No injectable files found in translated/.",
            )
            return
        translated = self._tool_root() / "translated"
        paths = [translated / name for name in files if (translated / name).is_file()]
        if not paths:
            QMessageBox.information(
                self,
                "Layout-restore",
                "None of the injectable files exist under translated/.",
            )
            return

        def task(log, progress=None):
            from util import wolfdawn

            log(f"layout-restore: {len(paths)} file(s)…")
            res = wolfdawn.layout_restore(paths, log_fn=log)
            for line in (res.stdout or "").splitlines():
                if line.strip():
                    log(line)
            fixed = wolfdawn.parse_layout_restore_counts(res.stdout, res.stderr)
            if not res.ok:
                err = (res.stderr or res.stdout or "").strip() or f"exit {res.returncode}"
                return False, f"layout-restore failed: {err}"
            n = fixed if fixed is not None else 0
            return True, f"layout-restore fixed {n} line(s) across {len(paths)} file(s)."

        def _after(ok: bool, msg: str):
            if ok:
                QMessageBox.information(self, "Layout-restore", msg)
            else:
                QMessageBox.warning(self, "Layout-restore", msg or "layout-restore failed.")

        self._run_task(task, on_done=_after)

    # ── Step 8: Package (+ optional saves) ─────────────────────────────────────

    def _build_step8_package(self, layout: QVBoxLayout):
        layout.addWidget(self._page_header(
            8, "Build Playable Game", "Package translated data and apply optional save compatibility fixes."
        ))
        layout.addWidget(self._desc(
            "Make the injected build playable so you can spot overflow in-game, then "
            "fix wrapping in Step 9. A loose Data/ folder is simplest for playtesting; "
            "repacking rebuilds a single Data.wolf archive for distribution."
        ))

        loose_btn = self._register(_make_btn("Use loose Data folder", "#007acc"))
        loose_btn.clicked.connect(self._package_loose)
        layout.addWidget(loose_btn)
        layout.addWidget(self._desc(
            "Renames Data.wolf (and any split .wolf archives) to .bak so the WOLF engine loads "
            "the loose, translated Data/ folder next to Game.exe."
        ))

        layout.addWidget(_make_hr())

        repack_btn = self._register(_make_btn("Build Data.wolf", "#00a86b"))
        repack_btn.clicked.connect(self._package_repack)
        layout.addWidget(repack_btn)
        layout.addWidget(self._desc(
            "Rebuilds Data.wolf from the translated Data/ folder, inheriting the original "
            "archive's encryption where possible (--like the backed-up original)."
        ))

        layout.addWidget(_make_hr())
        layout.addWidget(self._subheading("Public release"))
        layout.addWidget(self._desc(
            "Create a player-ready ZIP of the complete game. Translator workspaces, version "
            "control, documentation, backups, saves, and other tool artifacts are omitted; "
            "GameUpdate files remain available to players. The game folder is not modified."
        ))
        self._release_zip_btn = self._register(
            _make_btn("Build public release ZIP", "#007acc")
        )
        self._release_zip_btn.clicked.connect(self._create_public_release)
        layout.addWidget(self._release_zip_btn)

        layout.addWidget(_make_hr())
        layout.addWidget(self._subheading("Update existing saves (optional)"))
        layout.addWidget(self._desc(
            "WOLF .sav files bake in the game title and some strings at save time. Rewrite "
            "them so old Japanese saves load cleanly in the translated build. Only needed "
            "for players who already have saves, or to test against one. A timestamped "
            "backup is made automatically."
        ))

        row = QHBoxLayout()
        self.save_edit = QLineEdit()
        self.save_edit.setPlaceholderText("Save folder or .sav file…")
        row.addWidget(self.save_edit, 1)
        browse_btn = self._register(_make_btn("Choose…", "#3a3a3a"))
        browse_btn.clicked.connect(self._browse_saves)
        row.addWidget(browse_btn)
        layout.addLayout(row)

        run_btn = self._register(_make_btn("Update existing saves", "#007acc"))
        run_btn.clicked.connect(self._update_saves)
        layout.addWidget(run_btn)

    def _package_loose(self):
        if not self._require_root():
            return
        from util.project_scanner import find_wolf_archives

        archives = find_wolf_archives(self._game_root)
        if not archives:
            QMessageBox.information(self, "Package", "No .wolf archives to back up — already loose.")
            return

        def task(log, progress=None):
            renamed = 0
            for arc in archives:
                bak = arc.with_suffix(arc.suffix + ".bak")
                if bak.exists():
                    log(f"  {bak.name} already exists — leaving {arc.name} in place")
                    continue
                arc.rename(bak)
                log(f"  {arc.name} → {bak.name}")
                renamed += 1
            return True, f"Backed up {renamed} archive(s); the game now runs from the loose Data/ folder."

        self._run_task(task)

    def _package_repack(self):
        if not self._require_root():
            return
        info = detect_wolf_layout(self._game_root)
        data_dir = info.get("data_dir")
        if not data_dir:
            QMessageBox.warning(self, "Repack", "No loose Data/ folder found to repack.")
            return
        root = Path(self._game_root)
        output = root / "Data.wolf"
        like = None
        for cand in (root / "Data.wolf.bak", root / "Data.wolf"):
            if cand.is_file():
                like = cand
                break

        def task(log, progress=None):
            from util import wolfdawn

            log(f"Repacking {data_dir} → {output} …")
            res = wolfdawn.pack(str(data_dir), str(output), like=str(like) if like else None, log_fn=log)
            if not res.ok:
                return False, f"pack exited {res.returncode}"
            return True, f"Wrote {output.name}."

        self._run_task(task)

    def _create_public_release(self):
        if not self._require_root():
            return

        from util.release_package import default_release_zip_path

        suggested = str(default_release_zip_path(self._game_root))
        output, _ = QFileDialog.getSaveFileName(
            self,
            "Create Public Release ZIP",
            suggested,
            "ZIP archives (*.zip)",
        )
        if not output:
            return

        game_root = self._game_root

        def task(log, progress=None):
            from util.release_package import create_release_zip

            log(f"Creating public release ZIP from {game_root} …")
            result = create_release_zip(game_root, output, progress=progress)
            size_mb = result.output_path.stat().st_size / (1024 * 1024)
            log(
                f"  Added {result.files_added} file(s), omitted "
                f"{result.excluded_entries} tool/private item(s)."
            )
            return True, (
                f"Created {result.output_path.name} ({size_mb:.1f} MB) at "
                f"{result.output_path}."
            )

        self._run_task(task)

    def _browse_saves(self):
        start = self.save_edit.text() or (str(Path(self._game_root) / "Save") if self._game_root else str(Path.home()))
        folder = QFileDialog.getExistingDirectory(self, "Select Save Folder", start)
        if folder:
            self.save_edit.setText(folder)

    def _update_saves(self):
        save_path = self.save_edit.text().strip()
        if not save_path or not Path(save_path).exists():
            QMessageBox.warning(self, "Saves", "Pick a valid Save folder or .sav file.")
            return
        info = detect_wolf_layout(self._game_root) if self._game_root else {}
        basic = info.get("basic_data")
        game_dat = Path(basic) / "Game.dat" if basic else None

        def task(log, progress=None):
            from util import wolfdawn

            if not game_dat or not game_dat.is_file():
                return False, "Game.dat not found — extract/unpack the game first."
            translations = Path("translated")
            tl_arg = [str(translations)] if translations.is_dir() else None
            log(f"Updating saves in {save_path} …")
            res = wolfdawn.save_update(
                save_path, game=str(game_dat), translations=tl_arg, log_fn=log,
            )
            if not res.ok:
                return False, f"save-update exited {res.returncode}"
            return True, "Saves updated (originals backed up)."

        self._run_task(task)

    # ── shared guards ──────────────────────────────────────────────────────────

    def _require_root(self) -> bool:
        if not self._game_root or not Path(self._game_root).is_dir():
            QMessageBox.warning(self, "No game folder", "Select and detect a game folder in Step 0 first.")
            return False
        return True

    def _require_manifest(self) -> bool:
        if not self._require_root():
            return False
        if self._read_manifest() is None:
            QMessageBox.warning(
                self, "Not extracted",
                "No extraction manifest found. Run Step 0 (Extract text) first.",
            )
            return False
        return True
