"""
Wolf RPG (WolfDawn) Workflow Tab - guided pipeline for WOLF RPG Editor games.

Mirrors the RPGMaker WorkflowTab, driven by the vendored WolfDawn ``wolf`` CLI
(see util/wolfdawn):

  Step 0  Project   - select game folder, unpack .wolf archives, extract text
                      (strings-extract per file + names-extract) into files/, copy
                      the gameupdate/ patch files (incl. .gitignore) for git tracking,
                      and format the extracted JSON to the canonical layout so injects
                      produce clean git diffs
  Step 1  Glossary  - build vocab.txt (characters/terms) and translate the
                      project-wide name-value glossary first
  Step 2  Translate - run the "Wolf RPG (WolfDawn)" module over files/
  Step 3  Inject    - inject translations + names back into the Data/ binaries
                      and refresh the git-tracked wolf_json/ with the translated
                      JSON; quick-inject picks just a few translated files for
                      fast in-game / git iteration, or inject everything at once
  Step 4  Package   - run from a loose Data/ folder, or repack Data.wolf
  Step 5  Saves     - fix baked strings in existing .sav files (optional)

The extracted JSON is staged in ``<game_root>/wolf_json/`` (a manifest maps each
file back to its base binary), then imported into ``files/`` for the shared
translation pipeline, mirroring how the Ace workflow uses ``ace_json/``. On
inject, the translated JSON is copied back into ``wolf_json/`` so the game
project's git history tracks both the JSON source and the updated binaries.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from PyQt5.QtCore import Qt, QSettings, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from gui.translation_tab import (
    BATCH_COLLECT_LIVE_CHARGE_NOTE,
    BATCH_MODE_BENEFIT_NOTE,
    BATCH_MODE_LABEL,
)
from gui.workflow_tab import _make_btn, _make_hr, _make_section_label
from util.project_scanner import detect_wolf_layout
from util.vocab import read_game_vocab, write_game_vocab

# Workflow-level label for the non-batch (live) translation path. The Translation
# tab's own mode is called "Translate"; _workflow_mode_text() maps to that.
_TL_NORMAL_LABEL = "Normal Translate"

MANIFEST_NAME = "manifest.json"
NAMES_JSON = "names.json"
WORK_DIR_NAME = "wolf_json"

# Glossary-discovery prompt for Copilot / Cursor, tailored to WolfDawn's extracted
# JSON (source/text pairs staged in files/). Produces the same two-section format
# the shared vocab.txt expects, so the AI output pastes straight into the editor.
_WOLF_GLOSSARY_PROMPT = (
    "You are an expert Japanese WOLF RPG Editor game analyst building a translation glossary.\n"
    "\n"
    "<task>\n"
    "Extract named characters and lore-specific worldbuilding terms from this game's extracted "
    "text. Produce a structured glossary in the exact format specified below. It will be loaded "
    "directly into a translation tool, so strict format compliance is required.\n"
    "</task>\n"
    "\n"
    "--- attach the extracted JSON in files/ here before continuing ---\n"
    "\n"
    "<data_format>\n"
    "The files/ folder holds WolfDawn extractions as JSON. Each file is a list of entries with a\n"
    "'source' field (the original Japanese) and a 'text' field (initially empty/identical).\n"
    "Analyse the 'source' fields only. The files are:\n"
    "  - DataBase.project.json, CDataBase.project.json, SysDatabase.project.json — databases:\n"
    "    richest, small source of character/actor names, classes, factions, and lore titles.\n"
    "  - CommonEvent.dat.json — common events: dialogue and system text.\n"
    "  - Game.dat.json — game/system strings (title, terms).\n"
    "  - <Map>.mps.json — per-map events: the main story dialogue (can be large).\n"
    "  - Evtext.json — external event text, when present.\n"
    "  - names.json — item/skill/enemy value names (the tool handles these; do NOT list them).\n"
    "</data_format>\n"
    "\n"
    "<file_strategy>\n"
    "Map files can be extremely large. Do NOT read them sequentially — you will hit context "
    "limits. Instead:\n"
    "1. Read the DataBase.project.json files IN FULL first — small and the best source of names.\n"
    "2. For large map files, SEARCH (grep) the 'source' fields instead of reading sequentially. "
    "Prioritise dialogue because it is the best evidence for character voice:\n"
    "   - Speaker patterns such as 【Name】, [Name], Name「…」, Name：, and <Name> at the start of a line\n"
    "   - Katakana clusters or kanji compound proper nouns that recur across dialogue\n"
    "   Scan the lowest-numbered maps first — early maps have the most story content.\n"
    "3. Stop once you stop finding new names or terms. Do not pad the output.\n"
    "</file_strategy>\n"
    "\n"
    "<rules>\n"
    "Apply to both sections:\n"
    "- Separator: use a plain hyphen-minus (-). Never use an em dash or en dash. "
    "The translation tool only recognises the plain hyphen.\n"
    "- Descriptions must be entirely in English. Refer to other characters by English name only.\n"
    "- Never give two spelling options (e.g. 'Sylfia / Sylphia' is wrong). Commit to one translation.\n"
    "\n"
    "# Game Characters — rules:\n"
    "- Discover named characters from the databases and dialogue. Skip unnamed NPCs, generic "
    "enemies, and narration-only entries.\n"
    "- For each character include: gender, role, speech register, and personality. Note if the "
    "name is player-chosen (a hero/actor whose name comes from a variable or input prompt).\n"
    "\n"
    "# Worldbuilding Terms — rules:\n"
    "- Include: faction/organisation names, locations mentioned in dialogue but not on maps, "
    "unique magic systems, lore titles, recurring in-universe concepts.\n"
    "- Exclude: skill names, item names, weapon/armour names (the tool handles those via "
    "names.json). Skip generic RPG words. Do not repeat character names here.\n"
    "</rules>\n"
    "\n"
    "<output_format>\n"
    "Return the ENTIRE glossary inside ONE fenced code block (a ``` block), with nothing before "
    "or after it, so it can be copied in a single click and pasted straight into the tool.\n"
    "Inside the code block, output EXACTLY two sections with these headers. Do not add any "
    "preamble, explanation, or text outside the entries.\n"
    "\n"
    "# Game Characters\n"
    "# Worldbuilding Terms\n"
    "\n"
    "Entry format:  Japanese (English) - description\n"
    "\n"
    "<example>\n"
    "# Game Characters\n"
    "シロ (Shiro) - Female; protagonist; player-named; speaks in a flustered, cute register "
    "with feminine speech markers\n"
    "ゼクス (Zex) - Male; antagonist; cold and commanding; uses an archaic formal register\n"
    "カナエ (Kanae) - Female; NPC shopkeeper; warm and motherly; ends sentences with わね\n"
    "\n"
    "# Worldbuilding Terms\n"
    "虚無の穴 (Void Rift) - Dimensional tear referenced repeatedly in late-game dialogue; "
    "not a named map location\n"
    "裁定者 (Arbiter) - Title held by the ruling council; lore-specific rank with no "
    "real-world equivalent\n"
    "</example>\n"
    "</output_format>\n"
)


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

        self._step_tabs.currentChanged.connect(self._on_step_changed)

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
            "A prebuilt WolfDawn 'wolf' CLI ships with the tool (Windows and Linux), so no "
            "setup is needed. If your platform's binary is missing, it's downloaded once "
            "from the WolfDawn release page and cached for offline use."
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

        gu_btn = self._register(_make_btn("③ Set up git tracking (copy gameupdate/ files)", "#3a3a3a"))
        gu_btn.clicked.connect(self._apply_gameupdate)
        layout.addWidget(gu_btn)
        layout.addWidget(self._desc(
            "Copies the tool's gameupdate/ folder into the game's root folder: the updater "
            "scripts (GameUpdate.bat / GameUpdate_linux.sh), the patch scripts (patch.sh / "
            "patch.ps1), and a .gitignore that excludes the original game files. Do this early so "
            "you can track the translation project with git and later ship it as a git-based patch "
            "players apply themselves. Existing files are overwritten."
        ))

        fmt_btn = self._register(_make_btn("④ Format extracted JSON (dazedformat)", "#3a3a3a"))
        fmt_btn.clicked.connect(self._format_json)
        layout.addWidget(fmt_btn)
        layout.addWidget(self._desc(
            "Normalises the extracted JSON in wolf_json/ and files/ to a consistent layout "
            "(json.dump, indent 4) — the same format the translator writes back. Run this once "
            "after extracting and commit it as your baseline, so later injects produce clean, "
            "line-level git diffs instead of reformatting the whole file."
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

    def _format_json(self):
        if not self._require_root():
            return
        work_dir = self._work_dir()
        files_dir = Path("files")
        if not work_dir.is_dir() and not files_dir.is_dir():
            QMessageBox.information(
                self, "Format JSON",
                "Nothing to format yet. Run ② Extract text first.",
            )
            return

        def task(log):
            from util.dazedformat import format_json_files

            total = 0
            errors: list[str] = []
            for label, d in (("wolf_json/", work_dir), ("files/", files_dir)):
                if not Path(d).is_dir():
                    continue
                log(f"Formatting JSON in {label} …")
                count, errs = format_json_files(d, log=log)
                total += count
                errors.extend(errs)
            if errors:
                return False, f"Formatted {total} file(s), {len(errors)} error(s) — see log."
            return True, (
                f"Formatted {total} JSON file(s). Commit this as your baseline before "
                "translating so injects give clean git diffs."
            )

        self._run_task(task)

    # ── Step 1: Glossary / names ───────────────────────────────────────────────

    def _build_step1_glossary(self, layout: QVBoxLayout):
        layout.addWidget(_make_section_label("Step 1 · Glossary (build before translating)"))
        layout.addWidget(self._desc(
            "Two glossaries keep the translation consistent. Build them before Step 2 so the AI "
            "already knows every character and term while translating."
        ))

        # ── 1a: Character & worldbuilding glossary (vocab.txt) ──
        layout.addWidget(self._subheading("1a · Character & Worldbuilding Glossary (vocab.txt)"))
        layout.addWidget(self._desc(
            "vocab.txt is the project-wide glossary used by every translation batch to keep "
            "character names, speech register, honorifics, and lore terms consistent. Copy the "
            "prompt below into Cursor or Copilot Chat with the extracted files/ JSON open, let it "
            "analyse the game, then paste its output into the editor and save."
        ))
        prompt_btn = _make_btn("📋 Copy glossary prompt for Copilot / Cursor", "#5a3a7a")
        prompt_btn.clicked.connect(self._copy_wolf_glossary_prompt)
        layout.addWidget(prompt_btn)

        fmt = QLabel(
            "Format:  Japanese (English) - description\n"
            "Example: シロ (Shiro) - Female; protagonist; flustered, cute register"
        )
        fmt.setFont(QFont("Consolas", 9))
        fmt.setWordWrap(True)
        fmt.setStyleSheet(
            "color:#569cd6;background-color:#1a1e2a;border:1px solid #2a3a5a;"
            "padding:5px 10px;border-radius:4px;font-size:12px;border-left:3px solid #2a6a9a;"
        )
        layout.addWidget(fmt)

        self.vocab_editor = QTextEdit()
        self.vocab_editor.setMinimumHeight(120)
        self.vocab_editor.setFont(QFont("Consolas", 9))
        self.vocab_editor.setStyleSheet(
            "QTextEdit{background-color:#252526;color:#d4d4d4;border:1px solid #3c3c3c;"
            "border-radius:4px;padding:8px;selection-background-color:#264f78;}"
        )
        self._reload_vocab()
        layout.addWidget(self.vocab_editor, 1)

        vrow = QHBoxLayout()
        save_btn = _make_btn("💾 Save vocab.txt", "#3a7a3a")
        save_btn.clicked.connect(self._save_vocab)
        vrow.addWidget(save_btn)
        reload_btn = _make_btn("↺ Reload", "#555")
        reload_btn.clicked.connect(self._reload_vocab)
        vrow.addWidget(reload_btn)
        vrow.addStretch()
        layout.addLayout(vrow)

        layout.addWidget(_make_hr())

        # ── 1b: Name-value glossary (names.json) ──
        layout.addWidget(self._subheading("1b · Name Value Glossary (item / skill / enemy names)"))
        layout.addWidget(self._desc(
            "WOLF databases reference item/skill/enemy names by value across many files, so "
            f"translating {NAMES_JSON} first keeps those consistent. This translates only "
            f"{NAMES_JSON} using the Wolf RPG (WolfDawn) module; it is injected in Step 3. "
            "You can also translate it together with everything else in Step 2, but doing it "
            "first is the higher-quality path. It uses the translation mode (Normal / Batch) "
            "selected in Step 2."
        ))
        btn = self._register(_make_btn("Translate name glossary now", "#007acc"))
        btn.clicked.connect(lambda: self._navigate_to_translation(only=NAMES_JSON, auto_start=True))
        layout.addWidget(btn)

    def _copy_wolf_glossary_prompt(self):
        try:
            QApplication.clipboard().setText(_WOLF_GLOSSARY_PROMPT)
            self._log("📋 Glossary prompt copied. Paste it into Cursor/Copilot with files/ open.")
        except Exception as exc:
            self._log(f"❌ Could not copy glossary prompt: {exc}")

    def _reload_vocab(self):
        try:
            self.vocab_editor.setPlainText(read_game_vocab())
        except Exception as exc:
            self._log(f"❌ Could not load vocab.txt: {exc}")

    def _save_vocab(self):
        try:
            write_game_vocab(self.vocab_editor.toPlainText())
            self._log("✅ vocab.txt saved (base terms from vocab_base.txt appended).")
        except Exception as exc:
            self._log(f"❌ Could not save vocab.txt: {exc}")

    # ── Step 2: Translate ──────────────────────────────────────────────────────

    def _build_step2_translate(self, layout: QVBoxLayout):
        layout.addWidget(_make_section_label("Step 2 · Translate"))
        layout.addWidget(self._desc(
            "Sends the extracted files in files/ to the Translation tab using the "
            "Wolf RPG (WolfDawn) module and starts translating. Only the 'text' fields are "
            "filled in; 'source' is preserved so injection can verify each line."
        ))

        self._add_tl_mode_selector(layout)
        self._add_speaker_options(layout)

        btn = self._register(_make_btn("Translate all files now", "#00a86b"))
        btn.clicked.connect(lambda: self._navigate_to_translation(auto_start=True))
        layout.addWidget(btn)

        open_btn = self._register(_make_btn("Open Translation tab (no auto-start)", "#3a3a3a"))
        open_btn.clicked.connect(lambda: self._navigate_to_translation(auto_start=False))
        layout.addWidget(open_btn)

    def _add_speaker_options(self, layout: QVBoxLayout):
        """Toggles for which speaker formats are reshaped into '[Speaker]: line'."""
        from util import speakers as wolf_speakers

        layout.addWidget(_make_hr())
        layout.addWidget(self._subheading("Speaker handling"))
        layout.addWidget(self._desc(
            "WolfDawn tags who is speaking on each line. For lines where the name is baked "
            "into the first line (a nameplate), the translator reshapes them into the "
            "\"[Speaker]: line\" format the prompt understands, translates the speaker tag, then "
            "restores WOLF's native \"Speaker⏎line\" layout on inject. Turn the formats off if a "
            "game's first lines are not really speaker names."
        ))

        cfg = wolf_speakers.load_config()

        self._speaker_hi_cb = QCheckBox(
            "High-confidence nameplates (a face window precedes the line)"
        )
        self._speaker_hi_cb.setChecked(bool(cfg.get("literal_line1", True)))
        self._speaker_hi_cb.stateChanged.connect(self._save_speaker_options)
        layout.addWidget(self._speaker_hi_cb)

        self._speaker_lo_cb = QCheckBox(
            "Low-confidence first-line guesses (short first line, no preceding face window)"
        )
        self._speaker_lo_cb.setChecked(bool(cfg.get("literal_line1_lowconf", True)))
        self._speaker_lo_cb.stateChanged.connect(self._save_speaker_options)
        layout.addWidget(self._speaker_lo_cb)

    def _save_speaker_options(self):
        from util import speakers as wolf_speakers

        try:
            wolf_speakers.save_config({
                "literal_line1": self._speaker_hi_cb.isChecked(),
                "literal_line1_lowconf": self._speaker_lo_cb.isChecked(),
            })
        except Exception as exc:
            self._log(f"❌ Could not save speaker options: {exc}")

    def _add_tl_mode_selector(self, layout: QVBoxLayout):
        """Normal vs Batch selector; applies to the name glossary (1b) and full runs."""
        row = QHBoxLayout()
        lbl = QLabel("Translation mode:")
        lbl.setStyleSheet("color:#cccccc;font-size:12px;font-weight:bold;background:transparent;")
        self._tl_mode_combo = QComboBox()
        self._tl_mode_combo.addItem(_TL_NORMAL_LABEL)
        self._tl_mode_combo.addItem(BATCH_MODE_LABEL)
        self._tl_mode_combo.setFixedWidth(220)
        self._tl_mode_combo.setToolTip(
            "Applies to both the Step 1 name glossary and the full run here.\n"
            "Normal translates live; Batch uses the Anthropic Batches API (~50% cheaper, Claude only)."
        )
        saved = self._setting("tl_mode", BATCH_MODE_LABEL) or BATCH_MODE_LABEL
        idx = self._tl_mode_combo.findText(str(saved))
        if idx >= 0:
            self._tl_mode_combo.setCurrentIndex(idx)
        self._tl_mode_combo.currentTextChanged.connect(self._on_tl_mode_changed)
        row.addWidget(lbl)
        row.addWidget(self._tl_mode_combo)
        row.addStretch()
        layout.addLayout(row)

        self._batch_note = QLabel(BATCH_MODE_BENEFIT_NOTE + "\n" + BATCH_COLLECT_LIVE_CHARGE_NOTE)
        self._batch_note.setWordWrap(True)
        self._batch_note.setStyleSheet("color:#8fbc8f;font-size:11px;background:transparent;")
        layout.addWidget(self._batch_note)
        self._on_tl_mode_changed(self._tl_mode_combo.currentText())

    def _on_tl_mode_changed(self, mode_text: str):
        is_batch = mode_text == BATCH_MODE_LABEL
        if hasattr(self, "_batch_note"):
            self._batch_note.setVisible(is_batch)
        self._save_setting("tl_mode", mode_text)

    def _workflow_mode_text(self) -> str:
        """Map the selector to the Translation tab's own mode label."""
        combo = getattr(self, "_tl_mode_combo", None)
        if combo is not None and combo.currentText() == BATCH_MODE_LABEL:
            return BATCH_MODE_LABEL
        return "Translate"

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

        # Apply the chosen translation mode (after the module, since changing the
        # module can refresh the mode list).
        try:
            mode_combo = tt.mode_combo
            mode_idx = mode_combo.findText(self._workflow_mode_text())
            if mode_idx >= 0:
                mode_combo.setCurrentIndex(mode_idx)
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

        layout.addWidget(_make_hr())
        layout.addWidget(self._subheading("Quick inject — write only specific files into the game"))
        layout.addWidget(self._desc(
            "For iterating: after translating a few files, tick just those here and inject them "
            "straight into the game's Data/ so you can review the git diff in the game project and "
            "test in-game. Only files that already have a translation in translated/ are listed. "
            f"Tick {NAMES_JSON} to also re-apply the name glossary across Data/."
        ))

        self.inject_list = QListWidget()
        self.inject_list.setMaximumHeight(220)
        self.inject_list.setStyleSheet(
            "QListWidget{background-color:#252526;border:1px solid #3a3a3a;border-radius:4px;"
            "color:#cccccc;font-size:12px;padding:2px;}"
            "QListWidget::item{padding:3px 4px;}"
            "QListWidget::item:selected{background:#264f78;color:#ffffff;}"
        )
        layout.addWidget(self.inject_list)

        list_row = QHBoxLayout()
        refresh_btn = self._register(_make_btn("↻ Refresh list", "#3a3a3a"))
        refresh_btn.clicked.connect(self._refresh_inject_list)
        sel_all_btn = self._register(_make_btn("Select all", "#3a3a3a"))
        sel_all_btn.clicked.connect(lambda: self._set_inject_checks(True))
        sel_none_btn = self._register(_make_btn("Select none", "#3a3a3a"))
        sel_none_btn.clicked.connect(lambda: self._set_inject_checks(False))
        list_row.addWidget(refresh_btn)
        list_row.addWidget(sel_all_btn)
        list_row.addWidget(sel_none_btn)
        list_row.addStretch()
        layout.addLayout(list_row)

        quick_btn = self._register(_make_btn("Inject selected files", "#00a86b"))
        quick_btn.clicked.connect(self._inject_selected)
        layout.addWidget(quick_btn)

        layout.addWidget(_make_hr())
        layout.addWidget(self._subheading("Full inject"))
        layout.addWidget(self._desc(
            "Injects every extracted document and applies the name glossary across Data/. "
            "Use this once translation is complete before packaging in Step 4."
        ))
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

    def _on_step_changed(self, idx: int):
        # Index 3 == Inject: keep the quick-inject picker in sync with translated/.
        if idx == 3:
            self._refresh_inject_list()

    def _refresh_inject_list(self):
        if not hasattr(self, "inject_list"):
            return
        self.inject_list.clear()
        manifest = self._read_manifest()
        if not manifest:
            item = QListWidgetItem("Run Step 0 (extract) first — no manifest found.")
            item.setFlags(Qt.ItemIsEnabled)
            self.inject_list.addItem(item)
            return
        listed = 0
        for entry in manifest.get("entries", []):
            json_name = entry.get("json")
            if not json_name:
                continue
            if not (Path("translated") / json_name).is_file():
                continue
            item = QListWidgetItem(json_name)
            item.setData(Qt.UserRole, json_name)
            item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            item.setCheckState(Qt.Unchecked)
            self.inject_list.addItem(item)
            listed += 1
        if listed == 0:
            item = QListWidgetItem("No translated files in translated/ yet — run Step 2.")
            item.setFlags(Qt.ItemIsEnabled)
            self.inject_list.addItem(item)

    def _set_inject_checks(self, checked: bool):
        if not hasattr(self, "inject_list"):
            return
        state = Qt.Checked if checked else Qt.Unchecked
        for i in range(self.inject_list.count()):
            it = self.inject_list.item(i)
            if it.flags() & Qt.ItemIsUserCheckable:
                it.setCheckState(state)

    def _inject_selected(self):
        if not self._require_manifest():
            return
        selected = set()
        for i in range(self.inject_list.count()):
            it = self.inject_list.item(i)
            if (it.flags() & Qt.ItemIsUserCheckable) and it.checkState() == Qt.Checked:
                name = it.data(Qt.UserRole)
                if name:
                    selected.add(name)
        if not selected:
            QMessageBox.information(
                self, "Nothing selected",
                "Tick the files you want to inject, then try again. "
                "Use “↻ Refresh list” if you just translated something.",
            )
            return
        self._inject(only_json=selected)

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

    def _inject(self, only_json: set[str] | None = None):
        """Inject translations into the game's Data/ binaries.

        only_json:
            None      — full inject: every document + name glossary across Data/.
            set(names)— quick inject: only those JSON files; the name glossary is
                        re-applied across Data/ only when NAMES_JSON is included.
        """
        if not self._require_manifest():
            return
        manifest = self._read_manifest()
        en_punct = self.en_punct_cb.isChecked()
        allow_drift = self.drift_cb.isChecked()
        quick = only_json is not None
        game_json_dir = self._work_dir()

        def _sync_json(json_name: str, src: Path, log):
            """Copy the translated JSON into the game's git-tracked wolf_json/ so the
            diff shows both the updated JSON source and the injected binary."""
            dest = game_json_dir / json_name
            try:
                if src.resolve() == dest.resolve():
                    return
            except Exception:
                pass
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
            except Exception as e:
                log(f"  ⚠ could not update {json_name} in {WORK_DIR_NAME}/: {e}")

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
                if only_json is not None and entry["json"] not in only_json:
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
                    _sync_json(entry["json"], src, log)
                else:
                    failed += 1
                    log(f"  ⚠ inject exit {res.returncode} for {entry['json']}")

            # Name glossary: apply across the whole data dir. For a quick inject,
            # only do this if the user explicitly selected the names file, since it
            # rewrites many binaries and would add noise to the git diff otherwise.
            names_entry = next((e for e in entries if e["kind"] == "names"), None)
            if names_entry and (only_json is None or names_entry["json"] in only_json):
                src = self._translated_or_source(names_entry["json"])
                if src is not None:
                    log("Applying name glossary across Data/ …")
                    res = wolfdawn.names_inject(
                        str(src), data_dir,
                        allow_code_drift=allow_drift, en_punct=en_punct, log_fn=log,
                    )
                    if res.ok:
                        applied += 1
                        _sync_json(names_entry["json"], src, log)
                    else:
                        failed += 1
                        log(f"  ⚠ names-inject exit {res.returncode}")

            msg = f"Injected {applied} document(s)"
            if failed:
                msg += f", {failed} had guard/errors (see log)"
            if quick:
                msg += ". Review the git diff in the game project and test in-game."
            else:
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

    def _apply_gameupdate(self):
        if not self._require_root():
            return
        from util.paths import PROJECT_ROOT

        src = PROJECT_ROOT / "gameupdate"
        dst = Path(self._game_root)
        if not src.is_dir():
            QMessageBox.warning(
                self, "gameupdate",
                f"The tool's gameupdate/ folder was not found at {src}.",
            )
            return

        def task(log):
            import shutil

            copied = 0
            errors: list[str] = []
            log(f"Copying gameupdate patch files: {src} → {dst} …")
            for fp in sorted(src.rglob("*")):
                if not fp.is_file():
                    continue
                rel = fp.relative_to(src)
                target = dst / rel
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(fp, target)
                    copied += 1
                    log(f"  copied {rel}")
                except Exception as exc:
                    errors.append(f"{rel}: {exc}")
            for e in errors:
                log(f"  ⚠ {e}")
            if errors:
                return False, f"Copied {copied} file(s); {len(errors)} failed (see log)."
            return True, f"Copied {copied} gameupdate file(s) into {dst.name}."

        self._run_task(task)

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
