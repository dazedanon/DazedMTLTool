"""
Wolf RPG (WolfDawn) Workflow Tab - guided pipeline for WOLF RPG Editor games.

Mirrors the RPGMaker WorkflowTab, driven by the vendored WolfDawn ``wolf`` CLI
(see util/wolfdawn):

  Step 0  Project   - select game folder, unpack .wolf archives, extract text
                      (strings-extract per file + names-extract) into files/
  Step 1  Glossary  - translate the project-wide name glossary first
  Step 2  Translate - run the "Wolf RPG (WolfDawn)" module over files/
  Step 3  Inject    - inject translations + names back into the Data/ binaries
  Step 4  Package   - run from a loose Data/ folder, or repack Data.wolf
  Step 5  Saves     - fix baked strings in existing .sav files (optional)

The extracted JSON is staged in ``<game_root>/wolf_json/`` (a manifest maps each
file back to its base binary), then imported into ``files/`` for the shared
translation pipeline, mirroring how the Ace workflow uses ``ace_json/``.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from PyQt5.QtCore import Qt, QSettings, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from gui.workflow_tab import _make_btn, _make_hr, _make_section_label
from util.project_scanner import detect_wolf_layout

MANIFEST_NAME = "manifest.json"
NAMES_JSON = "names.json"
WORK_DIR_NAME = "wolf_json"


class _WolfTaskWorker(QThread):
    """Run a blocking WolfDawn task callable off the UI thread.

    The task receives a ``log`` callable and returns ``(success, message)``.
    """

    done = pyqtSignal(bool, str)
    log = pyqtSignal(str)

    def __init__(self, task):
        super().__init__()
        self._task = task

    def run(self):
        try:
            ok, msg = self._task(self.log.emit)
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
            self.settings = QSettings("DazedTranslations", "DazedMTLTool")
        except Exception:
            self.settings = None

        # State
        self._game_root: str = ""
        self._layout: dict = {}
        self._worker: _WolfTaskWorker | None = None
        self._buttons: list[QPushButton] = []

        self._init_ui()

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

    # ───────────────────────────────── UI setup ──────────────────────────────

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(1)
        splitter.setStyleSheet("QSplitter::handle{background:#3a3a3a;}")

        _SCROLL_STYLE = (
            "QScrollArea{border:none;background-color:transparent;}"
            "QScrollBar:vertical{background:#252526;width:10px;border:none;}"
            "QScrollBar::handle:vertical{background:#555555;border-radius:5px;min-height:20px;}"
            "QScrollBar::handle:vertical:hover{background:#007acc;}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}"
        )

        self._step_tabs = QTabWidget()
        self._step_tabs.setStyleSheet("""
            QTabWidget::pane { border: none; background-color: #1e1e1e; }
            QTabWidget::tab-bar { alignment: left; }
            QTabBar { background-color: #252526; }
            QTabBar::tab {
                background-color: #252526; color: #7a7a7a;
                padding: 9px 18px; border: none;
                border-right: 1px solid #3a3a3a; font-size: 12px; min-width: 90px;
            }
            QTabBar::tab:selected {
                background-color: #1e1e1e; color: #e0e0e0;
                font-weight: bold; border-top: 2px solid #007acc;
            }
            QTabBar::tab:hover:!selected { background-color: #2d2d30; color: #cccccc; }
        """)

        _tab_defs = [
            ("0  Project", self._build_step0),
            ("1  Glossary", self._build_step1_glossary),
            ("2  Translate", self._build_step2_translate),
            ("3  Inject", self._build_step3_inject),
            ("4  Package", self._build_step4_package),
            ("5  Saves", self._build_step5_saves),
        ]

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
            vbox.setContentsMargins(24, 18, 24, 12)
            vbox.setSpacing(10)
            builder(vbox)
            vbox.addStretch()

            scroll.setWidget(inner)
            page_layout.addWidget(scroll, 1)

            # Navigation footer
            nav = QWidget()
            nav.setStyleSheet("QWidget{background-color:#252526;border-top:1px solid #3a3a3a;}")
            nav_layout = QHBoxLayout(nav)
            nav_layout.setContentsMargins(16, 6, 16, 6)
            nav_layout.setSpacing(8)

            tab_idx = len(self._step_tabs)
            if tab_idx > 0:
                back_btn = _make_btn("← Back", "#3a3a3a")
                back_btn.setFixedWidth(100)
                back_btn.clicked.connect(
                    lambda _c, i=tab_idx: self._step_tabs.setCurrentIndex(i - 1)
                )
                nav_layout.addWidget(back_btn)
            nav_layout.addStretch()
            if tab_idx < len(_tab_defs) - 1:
                next_btn = _make_btn("Next →", "#007acc")
                next_btn.setFixedWidth(100)
                next_btn.clicked.connect(
                    lambda _c, i=tab_idx, lbl=tab_label: (
                        self._step_tabs.setTabText(i, "✓  " + lbl),
                        self._step_tabs.setCurrentIndex(i + 1),
                    )
                )
                nav_layout.addWidget(next_btn)

            page_layout.addWidget(nav)
            self._step_tabs.addTab(page, tab_label)

        splitter.addWidget(self._step_tabs)

        # Right: log panel
        log_panel = QWidget()
        lp_layout = QVBoxLayout(log_panel)
        lp_layout.setContentsMargins(0, 0, 0, 0)
        lp_layout.setSpacing(0)

        log_header = QLabel("  ▸  Wolf Workflow Log")
        log_header.setStyleSheet(
            "background-color:#252526;color:#9d9d9d;font-size:11px;font-weight:bold;"
            "padding:7px 10px;border-bottom:1px solid #3a3a3a;letter-spacing:0.5px;"
        )
        lp_layout.addWidget(log_header)

        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setFont(QFont("Consolas", 9))
        self.log_area.setStyleSheet(
            "QTextEdit{background-color:#1e1e1e;color:#c8c8c8;border:none;padding:10px;"
            "selection-background-color:#264f78;}"
        )
        lp_layout.addWidget(self.log_area)

        clear_btn = _make_btn("Clear Log", "#3a3a3a")
        clear_btn.setStyleSheet(
            "QPushButton{background-color:#252526;color:#6a6a6a;border:none;"
            "border-top:1px solid #3a3a3a;padding:5px 12px;font-size:11px;font-weight:normal;}"
            "QPushButton:hover{background-color:#2d2d30;color:#9d9d9d;}"
        )
        clear_btn.clicked.connect(self.log_area.clear)
        lp_layout.addWidget(clear_btn)

        splitter.addWidget(log_panel)
        splitter.setSizes([900, 240])

        root.addWidget(splitter)
        self.setLayout(root)
        self._apply_theme()

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

    def _register(self, btn: QPushButton) -> QPushButton:
        self._buttons.append(btn)
        return btn

    def _log(self, message: str):
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

    def _run_task(self, task, on_done=None):
        """Run *task* in a worker thread; disables buttons until it finishes."""
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, "Busy", "A task is already running. Please wait.")
            return
        self._set_busy(True)
        worker = _WolfTaskWorker(task)
        self._worker = worker
        worker.log.connect(self._log)

        def _finished(ok: bool, msg: str):
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
        layout.addWidget(_make_section_label("Step 0 · Select Game & Extract Text"))
        layout.addWidget(self._desc(
            "Pick the WOLF game's root folder (the one containing Game.exe and Data.wolf, "
            "or a loose Data/ folder). The tool unpacks the .wolf archives with WolfDawn, "
            "extracts all translatable text, and stages it in files/ ready to translate.\n\n"
            "A prebuilt WolfDawn 'wolf' CLI ships with the tool, so no setup is needed. "
            "(If no prebuilt binary exists for your platform, it is compiled once from "
            "source with cargo, which requires Rust.)"
        ))

        row = QHBoxLayout()
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("Path to the WOLF game folder…")
        self.folder_edit.setText(self._setting("last_game_folder", "") or "")
        row.addWidget(self.folder_edit, 1)
        browse_btn = self._register(_make_btn("Browse…", "#3a3a3a"))
        browse_btn.clicked.connect(self._browse_folder)
        row.addWidget(browse_btn)
        detect_btn = self._register(_make_btn("Detect", "#007acc"))
        detect_btn.clicked.connect(self._detect_folder)
        row.addWidget(detect_btn)
        layout.addLayout(row)

        self.status_label = QLabel("No game folder selected.")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color:#c8c8c8;font-size:12px;padding:6px 0px;")
        layout.addWidget(self.status_label)

        layout.addWidget(_make_hr())

        unpack_btn = self._register(_make_btn("① Unpack .wolf archives", "#007acc"))
        unpack_btn.clicked.connect(self._unpack)
        layout.addWidget(unpack_btn)
        layout.addWidget(self._desc(
            "Unpacks every .wolf archive into a loose Data/ folder. Skip this if the game "
            "already has an unpacked Data/ folder."
        ))

        extract_btn = self._register(_make_btn("② Extract text & import into files/", "#00a86b"))
        extract_btn.clicked.connect(self._extract_and_import)
        layout.addWidget(extract_btn)
        layout.addWidget(self._desc(
            "Extracts maps, common events, databases, Game.dat, external event text, and the "
            "project-wide name glossary, then imports them into files/ for translation."
        ))

    def _browse_folder(self):
        start = self.folder_edit.text() or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Select WOLF Game Folder", start)
        if folder:
            self.folder_edit.setText(folder)
            self._detect_folder()

    def _detect_folder(self):
        root = self.folder_edit.text().strip()
        if not root or not Path(root).is_dir():
            self.status_label.setText("❌ Folder not found. Pick a valid game directory.")
            return
        self._game_root = root
        self._save_setting("last_game_folder", root)
        info = detect_wolf_layout(root)
        self._layout = info

        if info["engine"] != "WOLF":
            self.status_label.setText(
                "⚠ This does not look like a WOLF game (no .wolf archives or loose Data/ "
                "with maps/CommonEvent.dat were found)."
            )
            self._log(f"Detect: no WOLF layout found in {root}")
            return

        archives = info["archives"]
        parts = [f"✅ WOLF game detected at {root}"]
        if info["unpacked"]:
            parts.append(f"Unpacked Data/ folder: {info['data_dir']}")
        if archives:
            parts.append(f"{len(archives)} .wolf archive(s): " + ", ".join(a.name for a in archives))
        if not info["unpacked"] and archives:
            parts.append("Run ① Unpack to extract the archives before extracting text.")
        self.status_label.setText("\n".join(parts))
        self._log("Detect: " + " | ".join(parts))

    def _unpack(self):
        if not self._require_root():
            return
        root = Path(self._game_root)
        info = detect_wolf_layout(root)
        archives = info["archives"]
        if not archives:
            self._log("Unpack: no .wolf archives found (already unpacked?).")
            QMessageBox.information(self, "Unpack", "No .wolf archives found to unpack.")
            return
        out_dir = root / "Data"

        def task(log):
            from util import wolfdawn
            log(f"Unpacking {len(archives)} archive(s) into {out_dir} …")
            res = wolfdawn.unpack_all([str(a) for a in archives], str(out_dir), log_fn=log)
            if not res.ok:
                return False, f"unpack-all exited {res.returncode}"
            return True, "Unpacked archives. Now run ② Extract text."

        self._run_task(task, on_done=lambda ok, _m: self._detect_folder())

    def _extract_and_import(self):
        if not self._require_root():
            return
        info = detect_wolf_layout(self._game_root)
        self._layout = info
        data_dir = info.get("data_dir")
        if not data_dir:
            QMessageBox.warning(
                self, "Extract",
                "No unpacked Data/ folder found. Run ① Unpack first.",
            )
            return

        work_dir = self._work_dir()
        game_root = self._game_root

        def task(log):
            from util import wolfdawn

            basic = Path(info["basic_data"]) if info.get("basic_data") else Path(data_dir)
            maps_dir = Path(info["map_data"]) if info.get("map_data") else Path(data_dir)
            work_dir.mkdir(parents=True, exist_ok=True)

            manifest_entries: list[dict] = []

            def _extract_one(base: Path, out_name: str, kind: str):
                out = work_dir / out_name
                log(f"Extracting {base.name} …")
                res = wolfdawn.strings_extract(str(base), str(out), log_fn=log)
                if res.ok and out.is_file():
                    manifest_entries.append({"json": out_name, "base": str(base), "kind": kind})
                else:
                    log(f"  ⚠ skipped {base.name} (exit {res.returncode})")

            # Common events
            ce = basic / "CommonEvent.dat"
            if ce.is_file():
                _extract_one(ce, "CommonEvent.dat.json", "common")
            # Databases
            for stem in ("DataBase", "CDataBase", "SysDatabase"):
                proj = basic / f"{stem}.project"
                if proj.is_file():
                    _extract_one(proj, f"{stem}.project.json", "db")
            # Game.dat
            gd = basic / "Game.dat"
            if gd.is_file():
                _extract_one(gd, "Game.dat.json", "gamedat")
            # Maps
            for mps in sorted(maps_dir.glob("*.mps")):
                _extract_one(mps, f"{mps.name}.json", "map")
            # External event text (optional)
            evtext = Path(data_dir) / "Evtext"
            if evtext.is_dir() and any(evtext.glob("*.txt")):
                out = work_dir / "Evtext.json"
                log("Extracting Evtext/ …")
                res = wolfdawn.strings_extract(str(evtext), str(out), log_fn=log)
                if res.ok and out.is_file():
                    manifest_entries.append({"json": "Evtext.json", "base": str(evtext), "kind": "txt-dir"})

            # Project-wide name glossary
            log("Extracting name glossary …")
            names_out = work_dir / NAMES_JSON
            res = wolfdawn.names_extract(str(data_dir), str(names_out), log_fn=log)
            if res.ok and names_out.is_file():
                manifest_entries.append({"json": NAMES_JSON, "base": str(data_dir), "kind": "names"})

            if not manifest_entries:
                return False, "Nothing was extracted. Check the Data/ folder layout."

            manifest = {
                "root": game_root,
                "data_dir": str(data_dir),
                "entries": manifest_entries,
            }
            (work_dir / MANIFEST_NAME).write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            # Import all extracted JSON (except the manifest) into files/.
            files_dir = Path("files")
            files_dir.mkdir(exist_ok=True)
            removed = 0
            for fp in files_dir.iterdir():
                if fp.name == ".gitkeep":
                    continue
                try:
                    if fp.is_file():
                        fp.unlink()
                        removed += 1
                    elif fp.is_dir():
                        shutil.rmtree(fp)
                        removed += 1
                except Exception as e:
                    log(f"  ⚠ could not clear {fp.name}: {e}")
            if removed:
                log(f"Cleared {removed} existing file(s) from files/")

            copied = 0
            for entry in manifest_entries:
                src = work_dir / entry["json"]
                if src.is_file():
                    shutil.copy2(src, files_dir / entry["json"])
                    copied += 1

            return True, (
                f"Extracted {len(manifest_entries)} document(s) and imported {copied} into files/. "
                "Go to Step 2 to translate."
            )

        self._run_task(task)

    # ── Step 1: Glossary / names ───────────────────────────────────────────────

    def _build_step1_glossary(self, layout: QVBoxLayout):
        layout.addWidget(_make_section_label("Step 1 · Name Glossary (recommended first)"))
        layout.addWidget(self._desc(
            "WOLF databases reference item/skill/enemy names by value across many files, so "
            "translating the glossary first keeps them consistent. This translates only "
            f"{NAMES_JSON} using the Wolf RPG (WolfDawn) module, then you can inject it in Step 3."
        ))
        btn = self._register(_make_btn("Translate name glossary now", "#007acc"))
        btn.clicked.connect(lambda: self._navigate_to_translation(only=NAMES_JSON, auto_start=True))
        layout.addWidget(btn)
        layout.addWidget(_make_hr())
        layout.addWidget(self._desc(
            "Optional: you can also open the glossary in Step 2 together with everything else. "
            "Doing names first is just the higher-quality path."
        ))

    # ── Step 2: Translate ──────────────────────────────────────────────────────

    def _build_step2_translate(self, layout: QVBoxLayout):
        layout.addWidget(_make_section_label("Step 2 · Translate"))
        layout.addWidget(self._desc(
            "Sends the extracted files in files/ to the Translation tab using the "
            "Wolf RPG (WolfDawn) module and starts translating. Only the 'text' fields are "
            "filled in; 'source' is preserved so injection can verify each line."
        ))
        btn = self._register(_make_btn("Translate all files now", "#00a86b"))
        btn.clicked.connect(lambda: self._navigate_to_translation(auto_start=True))
        layout.addWidget(btn)

        open_btn = self._register(_make_btn("Open Translation tab (no auto-start)", "#3a3a3a"))
        open_btn.clicked.connect(lambda: self._navigate_to_translation(auto_start=False))
        layout.addWidget(open_btn)

    def _navigate_to_translation(self, only: str | None = None, auto_start: bool = False):
        """Switch to the Translation tab, select the WolfDawn module, and check files."""
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

        try:
            tt.refresh_file_lists()
            fl = tt.file_list
            for idx in range(fl.count()):
                item = fl.item(idx)
                name = item.text()
                check = (only is None) or (name == only)
                item.setCheckState(Qt.Checked if check else Qt.Unchecked)
        except Exception:
            pass

        if pw and hasattr(pw, "content_stack"):
            pw.content_stack.setCurrentIndex(0)
            if hasattr(pw, "nav_buttons"):
                for i, btn in enumerate(pw.nav_buttons):
                    btn.setChecked(i == 0)

        if auto_start:
            QTimer.singleShot(
                150,
                lambda: tt.start_translation(skip_confirm=True) if tt is not None else None,
            )

    # ── Step 3: Inject ─────────────────────────────────────────────────────────

    def _build_step3_inject(self, layout: QVBoxLayout):
        layout.addWidget(_make_section_label("Step 3 · Inject Translations"))
        layout.addWidget(self._desc(
            "Writes the translated text back into the game's Data/ binaries with WolfDawn, "
            "byte-exact. The name glossary is applied consistently across every file. "
            "Lines whose inline codes changed are skipped and reported (unless you allow drift)."
        ))

        self.en_punct_cb = QCheckBox("Convert Japanese punctuation to ASCII (--en-punct)")
        self.en_punct_cb.setChecked(self._setting("en_punct", "true") == "true")
        self.en_punct_cb.stateChanged.connect(
            lambda: self._save_setting("en_punct", "true" if self.en_punct_cb.isChecked() else "false")
        )
        layout.addWidget(self.en_punct_cb)

        self.drift_cb = QCheckBox("Allow inline-code drift (--allow-code-drift, riskier)")
        self.drift_cb.setChecked(self._setting("allow_code_drift", "false") == "true")
        self.drift_cb.stateChanged.connect(
            lambda: self._save_setting(
                "allow_code_drift", "true" if self.drift_cb.isChecked() else "false"
            )
        )
        layout.addWidget(self.drift_cb)

        check_btn = self._register(_make_btn("Check name consistency", "#3a3a3a"))
        check_btn.clicked.connect(self._names_check)
        layout.addWidget(check_btn)

        inject_btn = self._register(_make_btn("Inject all translations", "#00a86b"))
        inject_btn.clicked.connect(self._inject)
        layout.addWidget(inject_btn)

    def _translated_or_source(self, json_name: str) -> Path | None:
        """Prefer translated/<name>; fall back to files/<name>."""
        for base in ("translated", "files"):
            p = Path(base) / json_name
            if p.is_file():
                return p
        return None

    def _names_check(self):
        if not self._require_manifest():
            return
        manifest = self._read_manifest()

        def task(log):
            from util import wolfdawn

            json_files = []
            for entry in manifest["entries"]:
                p = self._translated_or_source(entry["json"])
                if p:
                    json_files.append(str(p))
            if not json_files:
                return False, "No translated JSON found. Run Step 2 first."
            res = wolfdawn.names_check(json_files, log_fn=log)
            if res.returncode == 0:
                return True, "Name usage is consistent across files."
            return True, "names-check reported inconsistencies (see log above)."

        self._run_task(task)

    def _inject(self):
        if not self._require_manifest():
            return
        manifest = self._read_manifest()
        en_punct = self.en_punct_cb.isChecked()
        allow_drift = self.drift_cb.isChecked()

        def task(log):
            from util import wolfdawn

            entries = manifest["entries"]
            data_dir = manifest["data_dir"]
            applied = 0
            failed = 0

            # Non-name documents: inject each back onto its base binary.
            for entry in entries:
                if entry["kind"] == "names":
                    continue
                src = self._translated_or_source(entry["json"])
                if src is None:
                    log(f"  ⚠ no JSON for {entry['json']} — skipped")
                    continue
                base = entry["base"]
                out = base  # in-place (txt-dir writes each file under this dir)
                log(f"Injecting {entry['json']} → {Path(base).name} …")
                res = wolfdawn.strings_inject(
                    str(src), base, out,
                    allow_code_drift=allow_drift, en_punct=en_punct, log_fn=log,
                )
                if res.ok:
                    applied += 1
                else:
                    failed += 1
                    log(f"  ⚠ inject exit {res.returncode} for {entry['json']}")

            # Name glossary: apply across the whole data dir.
            names_entry = next((e for e in entries if e["kind"] == "names"), None)
            if names_entry:
                src = self._translated_or_source(names_entry["json"])
                if src is not None:
                    log("Applying name glossary across Data/ …")
                    res = wolfdawn.names_inject(
                        str(src), data_dir,
                        allow_code_drift=allow_drift, en_punct=en_punct, log_fn=log,
                    )
                    if res.ok:
                        applied += 1
                    else:
                        failed += 1
                        log(f"  ⚠ names-inject exit {res.returncode}")

            msg = f"Injected {applied} document(s)"
            if failed:
                msg += f", {failed} had guard/errors (see log)"
            msg += ". Continue to Step 4 to package."
            return failed == 0, msg

        self._run_task(task)

    # ── Step 4: Package ────────────────────────────────────────────────────────

    def _build_step4_package(self, layout: QVBoxLayout):
        layout.addWidget(_make_section_label("Step 4 · Package the Translated Game"))
        layout.addWidget(self._desc(
            "Choose how the translated build runs. A loose Data/ folder is simplest for "
            "playtesting; repacking rebuilds a single Data.wolf archive for distribution."
        ))

        loose_btn = self._register(_make_btn("Use loose Data/ folder (back up archives)", "#007acc"))
        loose_btn.clicked.connect(self._package_loose)
        layout.addWidget(loose_btn)
        layout.addWidget(self._desc(
            "Renames Data.wolf (and any split .wolf archives) to .bak so the WOLF engine loads "
            "the loose, translated Data/ folder next to Game.exe."
        ))

        layout.addWidget(_make_hr())

        repack_btn = self._register(_make_btn("Repack Data.wolf", "#00a86b"))
        repack_btn.clicked.connect(self._package_repack)
        layout.addWidget(repack_btn)
        layout.addWidget(self._desc(
            "Rebuilds Data.wolf from the translated Data/ folder, inheriting the original "
            "archive's encryption where possible (--like the backed-up original)."
        ))

    def _package_loose(self):
        if not self._require_root():
            return
        from util.project_scanner import find_wolf_archives

        archives = find_wolf_archives(self._game_root)
        if not archives:
            QMessageBox.information(self, "Package", "No .wolf archives to back up — already loose.")
            return

        def task(log):
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

        def task(log):
            from util import wolfdawn

            log(f"Repacking {data_dir} → {output} …")
            res = wolfdawn.pack(str(data_dir), str(output), like=str(like) if like else None, log_fn=log)
            if not res.ok:
                return False, f"pack exited {res.returncode}"
            return True, f"Wrote {output.name}."

        self._run_task(task)

    # ── Step 5: Saves ──────────────────────────────────────────────────────────

    def _build_step5_saves(self, layout: QVBoxLayout):
        layout.addWidget(_make_section_label("Step 5 · Update Existing Saves (optional)"))
        layout.addWidget(self._desc(
            "WOLF .sav files bake in the game title and some strings at save time. This rewrites "
            "them so old Japanese saves load cleanly in the translated build. It is only needed "
            "for players who already have saves, or to test against one. A timestamped backup is "
            "made automatically."
        ))

        row = QHBoxLayout()
        self.save_edit = QLineEdit()
        self.save_edit.setPlaceholderText("Save folder or .sav file…")
        row.addWidget(self.save_edit, 1)
        browse_btn = self._register(_make_btn("Browse…", "#3a3a3a"))
        browse_btn.clicked.connect(self._browse_saves)
        row.addWidget(browse_btn)
        layout.addLayout(row)

        run_btn = self._register(_make_btn("Update saves", "#007acc"))
        run_btn.clicked.connect(self._update_saves)
        layout.addWidget(run_btn)

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

        def task(log):
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
