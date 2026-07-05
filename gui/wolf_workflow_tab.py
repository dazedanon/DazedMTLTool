"""
Wolf RPG (WolfDawn) Workflow Tab - guided pipeline for WOLF RPG Editor games.

Mirrors the RPGMaker WorkflowTab, driven by the vendored WolfDawn ``wolf`` CLI
(see util/wolfdawn):

  Step 0  Project     - select game folder; import wolf_json/ into files/ (like RPGMaker)
  Step 1  Pre-process - optional dazedformat + gameupdate/ copy before translating
  Step 2  Glossary    - build vocab.txt (characters / worldbuilding terms) before
                        translating so the AI keeps names and voice consistent
  Step 3  Names       - translate names.json (Phase 0). WolfDawn safe/refs entries
                        are translated per-name; verify names are skipped. Harvests
                        short name terms into vocab.txt.
  Step 4  Translate   - WolfDawn module over files/ in two phases (after Step 3):
                          Phase 1  Database  - item/skill/state descriptions and system
                                               messages (DataBase/CDataBase.project)
                          Phase 2  Maps / events - .mps maps, CommonEvent, Game.dat,
                                               Evtext; speaker handling and text-wrap
                                               settings live under this phase
  Step 5  Inject      - inject translations + translated names back into the Data/ binaries
                        and refresh the git-tracked wolf_json/ with the translated
                        JSON; quick-inject picks just a few translated files for
                        fast in-game / git iteration, or inject everything at once
  Step 6  Package     - run from a loose Data/ folder, or repack Data.wolf
  Step 7  Saves       - fix baked strings in existing .sav files (optional)

names.json is staged into files/ but is NOT translated in the bulk phases - WolfDawn
tags each name safe / refs / verify and Phase 0 translates only safe+refs entries
(per-name, not per-category), harvests them into vocab.txt, and Step 5 injects the
result.

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

from PyQt5.QtCore import Qt, QSettings, QThread, QTimer, pyqtSignal, QEvent
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
    QVBoxLayout,
    QWidget,
)

from gui.translation_tab import (
    BATCH_COLLECT_LIVE_CHARGE_NOTE,
    BATCH_MODE_BENEFIT_NOTE,
    BATCH_MODE_LABEL,
)
from gui.workflow_tab import (
    _FileCopyWorker,
    _ImportWorker,
    _make_btn,
    _make_hr,
    _make_icon_btn,
    _make_section_label,
)
from util import wolf_names
from util.paths import PROJECT_ROOT
from util.project_scanner import (
    detect_wolf_layout,
    find_wolf_text_archives,
    list_wolf_json_files,
    wolf_has_maps,
    wolf_maps_dir,
    wolf_maps_packed,
)
from util.vocab import read_game_vocab, write_game_vocab

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
    "  - names.json — item/skill/enemy value names (translated separately in Step 3; do NOT list them).\n"
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
    "- Exclude: skill names, item names, weapon/armour names (translated via names.json in "
    "Step 3). Skip generic RPG words. Do not repeat character names here.\n"
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


# Speaker-format prompt for a repo-aware AI. WolfDawn already detects and tags who
# speaks on each line, so the only decision left is whether its LOW-confidence
# first-line guesses are really speaker names for this game. The AI inspects the
# extracted text and returns a single ENABLE/DISABLE recommendation.
_WOLF_SPEAKER_PROMPT = (
    "You are an expert Japanese WOLF RPG Editor translator helping configure a translation tool.\n"
    "\n"
    "<background>\n"
    "WolfDawn extracts each line with a 'speaker' and a 'speaker_src' tag describing how it "
    "detected the speaker. Two tags carry the speaker name baked into the FIRST line of the "
    "'source' text (the rest is the dialogue body):\n"
    "  - literal_line1          : HIGH confidence - a face/name window precedes the line, so the "
    "first line really is a nameplate. The tool always reshapes these; nothing to decide.\n"
    "  - literal_line1_lowconf  : LOW confidence - a short first line with NO preceding face "
    "window. WolfDawn guesses it is a speaker name, but it might actually be the start of the "
    "dialogue or narration.\n"
    "When a first-line format is trusted, the tool reshapes 'Name\\nbody' into '[Name]: body' for "
    "translation, then restores 'Name\\nbody' on inject (byte-safe either way).\n"
    "</background>\n"
    "\n"
    "--- attach the extracted JSON in files/ here (maps / CommonEvent) before continuing ---\n"
    "\n"
    "<task>\n"
    "Decide whether the LOW-confidence first-line guesses (speaker_src = literal_line1_lowconf) "
    "should be treated as speaker names for THIS game. Inspect a good sample of those entries in "
    "files/: look at the first line of each such 'source' and judge whether it is genuinely a "
    "character/speaker label as opposed to real dialogue or narration.\n"
    "  - ENABLE  if the low-confidence first lines are overwhelmingly real speaker names.\n"
    "  - DISABLE if many are actually dialogue/narration (reshaping them would mislabel lines).\n"
    "(The high-confidence nameplates are always handled; you are only ruling on the guesses.)\n"
    "</task>\n"
    "\n"
    "<output_format>\n"
    "Return ONLY a fenced code block containing the recommendation and a one-line reason, e.g.\n"
    "```\n"
    "LOWCONF_FIRSTLINE: ENABLE - low-confidence first lines are short character names (市民, 兵士...).\n"
    "```\n"
    "Use exactly ENABLE or DISABLE after the colon.\n"
    "</output_format>\n"
)


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
            self.settings = QSettings("DazedTranslations", "DazedMTLTool")
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

        self._init_ui()

    def showEvent(self, event):
        """Auto-detect the saved game folder when the tab is first shown."""
        super().showEvent(event)
        if not self._detected_on_show and self._setting("last_game_folder", ""):
            self._detected_on_show = True
            if self.folder_edit.text().strip():
                QTimer.singleShot(100, self._detect_folder)

    def eventFilter(self, obj, event):
        """Toggle workflow file checks when clicking a row outside the checkbox."""
        try:
            if (
                hasattr(self, "file_list")
                and obj is self.file_list.viewport()
                and event.type() == QEvent.MouseButtonRelease
                and event.button() == Qt.LeftButton
            ):
                item = self.file_list.itemAt(event.pos())
                if item is None:
                    return False
                item_rect = self.file_list.visualItemRect(item)
                if event.pos().x() <= item_rect.left() + 26:
                    return False
                item.setCheckState(
                    Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked
                )
                return False
        except Exception:
            pass
        return super().eventFilter(obj, event)

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

    def _snapshot_originals(self, entries: list[dict], data_dir: Path, log) -> None:
        """Copy the pristine base binaries into originals/ (only when missing, so a
        good snapshot is never clobbered by a later extract of injected data)."""
        for entry in entries:
            if entry.get("kind") == "names":
                continue
            src = Path(entry["base"])
            dst = self._orig_base_for(entry, data_dir)
            if dst.exists():
                continue
            try:
                if src.is_dir():
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                elif src.is_file():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
            except Exception as exc:
                log(f"  ⚠ could not snapshot original {src.name}: {exc}")

    def _ensure_originals(self, manifest: dict, log, progress=None) -> None:
        """Make sure a pristine snapshot exists; if entries are missing it and the
        game still has its .wolf archives (packaging renames them to .wolf.bak),
        rebuild the snapshot by unpacking those archives into originals/."""
        from util import wolfdawn

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
            log(
                "  ⚠ No pristine originals and no .wolf archives to rebuild them from. "
                "Re-run Step 0 (Unpack + Extract) on the untranslated game so injection "
                "has an original to work from."
            )
            return

        originals = self._originals_dir()
        originals.mkdir(parents=True, exist_ok=True)
        log("Rebuilding pristine originals from the game's .wolf archives …")
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
                log_fn=log,
                progress_fn=progress,
                progress_total=len(inputs),
            )
            if not res.ok:
                log(f"  ⚠ could not rebuild originals (unpack exit {res.returncode}).")

    def _restore_live_from_originals(
        self, entries: list[dict], data_dir: Path, log
    ) -> None:
        """Copy pristine originals onto live Data/ binaries before names-inject.

        ``names-inject`` rewrites every DB pair, CommonEvent.dat, and every map.
        Resetting from ``wolf_json/originals/`` first keeps them on one baseline.
        """
        restored = 0
        for entry in entries:
            if entry.get("kind") == "names":
                continue
            orig = self._orig_base_for(entry, data_dir)
            live = Path(entry["base"])
            if not orig.exists():
                log(f"  ⚠ no pristine original for {entry['json']} — live file left as-is")
                continue
            try:
                if orig.is_dir():
                    if live.exists():
                        shutil.rmtree(live)
                    shutil.copytree(orig, live)
                else:
                    live.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(orig, live)
                restored += 1
            except Exception as exc:
                log(f"  ⚠ could not restore {live.name} from originals: {exc}")
        if restored:
            log(
                f"Restored {restored} live binary file(s) from {WORK_DIR_NAME}/originals/."
            )

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

        # Names curation comes before Translate so Phase 0 can seed vocab.txt.
        _tab_defs = [
            ("0  Project", self._build_step0),
            ("1  Pre-process", self._build_step1_preprocess),
            ("2  Glossary", self._build_step1_glossary),
            ("3  Names", self._build_step3_names),
            ("4  Translate", self._build_step2_translate),
            ("5  Inject", self._build_step4_inject),
            ("6  Package", self._build_step5_package),
            ("7  Saves", self._build_step6_saves),
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

        self.task_progress_row = QWidget()
        progress_layout = QVBoxLayout(self.task_progress_row)
        progress_layout.setContentsMargins(10, 8, 10, 4)
        progress_layout.setSpacing(4)
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
        lp_layout.addWidget(self.task_progress_row)

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
        layout.addWidget(_make_section_label("Step 0 — Project Folder"))
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

        self.file_list = QListWidget()
        self.file_list.setMinimumHeight(320)
        self.file_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.file_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.file_list.itemChanged.connect(self._sync_selected_file_checks)
        self.file_list.viewport().installEventFilter(self)
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
        select_all_btn = _make_icon_btn("✓", "Select all importable files")
        select_all_btn.clicked.connect(self._select_all_files)
        row1.addWidget(select_all_btn)
        deselect_all_btn = _make_icon_btn("✗", "Deselect all files")
        deselect_all_btn.clicked.connect(self._deselect_all_files)
        row1.addWidget(deselect_all_btn)
        sel_core = _make_icon_btn("◆", "Core only: databases, common events, names")
        sel_core.setToolTip("Select core JSON files; deselect map scripts")
        sel_core.clicked.connect(self._select_core_only)
        row1.addWidget(sel_core)
        import_btn = _make_icon_btn("📥", "Import selected files into files/")
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
        layout.addWidget(_make_section_label("Step 1 — Pre-process (optional)"))

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
        run_dazed = _make_btn("►  Run dazedformat", "#555")
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
            "overwriting existing files (updater scripts, patch scripts, .gitignore)."
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
        run_gu = _make_btn("►  Copy gameupdate/", "#555")
        run_gu.setFixedWidth(180)
        run_gu.clicked.connect(self._run_gameupdate)
        tc_btn_row.addWidget(run_gu)
        run_all_btn = _make_btn("►►  Run Both Tasks", "#007acc")
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

        info = self._layout or detect_wolf_layout(self._game_root)
        self._layout = info
        if info.get("archives") and not info.get("unpacked"):
            self._log("Auto-setup: unpacking .wolf archives …")
            self._unpack(on_done=self._on_auto_unpack_done, interactive=False)
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
        for item in items:
            cat = item["category"]
            icon = "📄" if cat == "core" else ("🗺" if cat == "map" else "❓")
            lw = QListWidgetItem(f"{icon}  {item['name']}  ({item['size_kb']:.1f} KB)")
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

    def _sync_selected_file_checks(self, changed_item: QListWidgetItem):
        if self._syncing_file_checks:
            return
        selected = self.file_list.selectedItems()
        if len(selected) <= 1 or changed_item not in selected:
            return
        self._syncing_file_checks = True
        try:
            new_state = changed_item.checkState()
            for item in selected:
                if item is not changed_item:
                    item.setCheckState(new_state)
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
        w = _FileCopyWorker(src, dst)
        w.log.connect(self._log)
        w.done.connect(self._on_gameupdate_done)
        self._import_worker = w  # reuse slot; not WolfTaskWorker
        w.start()

    def _on_gameupdate_done(self, count: int, errors: list):
        self._log(f"✅ gameupdate: copied {count} file(s).")
        for e in errors:
            self._log(f"   ⚠  {e}")

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
                    rel = fp.relative_to(src)
                    target = Path(dst) / rel
                    try:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(fp, target)
                        copied += 1
                    except Exception as exc:
                        errors.append(f"{rel}: {exc}")
                log(f"  Copied {copied} gameupdate file(s).")
            if errors:
                return False, "Pre-process finished with errors (see log)."
            return True, "Pre-process: dazedformat and gameupdate copy finished."

        self._run_task(task)

    def _unpack(self, on_done=None, *, interactive: bool = True):
        if not self._require_root():
            return
        root = Path(self._game_root)
        info = detect_wolf_layout(root)
        archives = info["archives"]
        if not archives:
            self._log("Unpack: no .wolf archives found (already unpacked?).")
            if interactive:
                QMessageBox.information(self, "Unpack", "No .wolf archives found to unpack.")
            return
        out_dir = root / "Data"

        def task(log, progress=None):
            from util import wolfdawn
            log(f"Unpacking {len(archives)} archive(s) into {out_dir} …")
            res = wolfdawn.unpack_all(
                [str(a) for a in archives],
                str(out_dir),
                log_fn=log,
                progress_fn=progress,
                progress_total=len(archives),
            )
            if not res.ok:
                return False, f"unpack-all exited {res.returncode}"
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

                log("Extracting name glossary …")
                names_out = work_dir / NAMES_JSON
                res = wolfdawn.names_extract(str(data_dir), str(names_out), log_fn=log)
                if res.ok and names_out.is_file():
                    manifest_entries.append({"json": NAMES_JSON, "base": str(data_dir), "kind": "names"})
            elif any(e.get("kind") == "map" for e in manifest_entries):
                log("Refreshing name glossary (maps were added) …")
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

    # ── Step 2: Glossary ───────────────────────────────────────────────────────

    def _build_step1_glossary(self, layout: QVBoxLayout):
        layout.addWidget(_make_section_label("Step 2 · Glossary (build before translating)"))
        layout.addWidget(self._desc(
            "vocab.txt is the project-wide glossary used by every translation batch to keep "
            "character names, speech register, honorifics, and lore terms consistent. Build it "
            "before translating (Step 4) so the AI already knows every character and term. "
            "Copy the prompt below into Cursor or Copilot Chat with the extracted files/ JSON "
            "open, let it analyse the game, then paste its output into the editor and save."
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

        note = self._desc(
            "You don't need to add item / skill / enemy value names here: Phase 0 translates "
            "WolfDawn safe/refs entries from names.json and harvests them into vocab.txt "
            "Focus this glossary on characters and worldbuilding terms."
        )
        layout.addWidget(note)

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

    # ── Step 3: Translate (phased) ─────────────────────────────────────────────

    def _build_step2_translate(self, layout: QVBoxLayout):
        layout.addWidget(_make_section_label("Step 4 · Translate (phased)"))
        layout.addWidget(self._desc(
            "Sends the extracted files in files/ to the Translation tab using the Wolf RPG "
            "(WolfDawn) module. Only the 'text' fields are filled in; 'source' is preserved so "
            "injection can verify each line. Run Step 3 (names) first so vocab.txt is seeded, "
            "then Phase 1 (database text) and Phase 2 (maps / events) in order."
        ))

        self._add_phase_buttons(layout)

    def _add_phase_buttons(self, layout: QVBoxLayout):
        """Two translation phases (names are handled in Step 3)."""
        layout.addWidget(_make_hr())
        layout.addWidget(self._subheading("Phase 1 · Database text"))
        layout.addWidget(self._desc(
            "Item / skill / state descriptions and system messages from DataBase.project and "
            "CDataBase.project. Run after Step 3 (names) so vocab.txt stays consistent."
        ))
        p1 = self._register(_make_btn("▶ Phase 1 · Translate database text", "#00a86b"))
        p1.clicked.connect(
            lambda: self._navigate_to_translation(kinds=PHASE_DB_KINDS, auto_start=True)
        )
        layout.addWidget(p1)

        layout.addWidget(_make_hr())
        layout.addWidget(self._subheading("Phase 2 · Maps / events"))
        layout.addWidget(self._desc(
            "Map scripts (.mps), common events (CommonEvent.dat), Game.dat, and Evtext - story "
            "dialogue, UI/objective strings, and other event text. Run after Phase 1 so it "
            "benefits from the names and terms already in vocab.txt. Speaker handling and text "
            "wrap below apply to the dialogue-like lines in this phase."
        ))
        self._add_speaker_options(layout)
        self._add_wrap_options(layout)
        p2 = self._register(_make_btn("▶ Phase 2 · Translate maps / events", "#00a86b"))
        p2.clicked.connect(
            lambda: self._navigate_to_translation(kinds=PHASE_MAPS_EVENTS_KINDS, auto_start=True)
        )
        layout.addWidget(p2)

        layout.addWidget(_make_hr())
        open_btn = self._register(_make_btn("Open Translation tab (no auto-start)", "#3a3a3a"))
        open_btn.clicked.connect(lambda: self._navigate_to_translation(auto_start=False))
        layout.addWidget(open_btn)

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

        prompt_btn = _make_btn("📋 Copy speaker-format prompt for Copilot / Cursor", "#5a3a7a")
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
            QApplication.clipboard().setText(_WOLF_SPEAKER_PROMPT)
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

    def _add_wrap_options(self, layout: QVBoxLayout):
        """Dialogue text-wrap width (like the RPGMaker workflow, via dazedwrap)."""
        layout.addWidget(_make_hr())
        layout.addWidget(self._subheading("Text wrap width"))
        layout.addWidget(self._desc(
            "Re-wraps the translated English dialogue so it fits WOLF's message box. "
            "Only the dialogue body is wrapped - a speaker's name line (the line break "
            "right after a nameplate) is always kept separate. Lower the width if lines "
            "overflow in-game; raise it if text wraps too early. Applies on the next run."
        ))

        wrap_env = self._read_env_values(["wolfWrap", "wolfWidth"])

        self._wrap_enable_cb = QCheckBox("Wrap translated dialogue")
        enabled = str(wrap_env.get("wolfWrap", "true")).strip().lower() != "false"
        self._wrap_enable_cb.setChecked(enabled)
        self._wrap_enable_cb.stateChanged.connect(self._apply_wrap_config)
        layout.addWidget(self._wrap_enable_cb)

        row = QHBoxLayout()
        width_lbl = QLabel("Width (characters):")
        width_lbl.setStyleSheet("color:#cccccc;font-size:12px;background:transparent;")
        self._wrap_width_spin = QSpinBox()
        self._wrap_width_spin.setRange(20, 300)
        try:
            self._wrap_width_spin.setValue(int(wrap_env.get("wolfWidth") or 55))
        except ValueError:
            self._wrap_width_spin.setValue(55)
        self._wrap_width_spin.setFixedWidth(70)
        self._wrap_width_spin.valueChanged.connect(self._apply_wrap_config)
        row.addWidget(width_lbl)
        row.addWidget(self._wrap_width_spin)
        row.addStretch()
        layout.addLayout(row)

    def _apply_wrap_config(self, *args):
        """Persist wolfWrap / wolfWidth to .env so the next translation run uses them."""
        updates = {
            "wolfWrap": "true" if self._wrap_enable_cb.isChecked() else "false",
            "wolfWidth": str(self._wrap_width_spin.value()),
        }
        if self._write_env_values(updates):
            self._log(
                "Text wrap updated: "
                + ", ".join(f"{k}={v}" for k, v in updates.items())
            )

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
        self._tl_mode_combo.addItem(_TL_NORMAL_LABEL)
        self._tl_mode_combo.addItem(BATCH_MODE_LABEL)
        self._tl_mode_combo.setFixedWidth(220)
        self._tl_mode_combo.setToolTip(
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

    def _navigate_to_translation(
        self,
        only: str | None = None,
        kinds: set[str] | None = None,
        auto_start: bool = False,
    ):
        """Switch to the Translation tab, select the WolfDawn module, and check files.

        Selection precedence: ``only`` (a single filename) > ``kinds`` (a phase's
        manifest kinds, e.g. ``{"db"}``) > legacy bulk (everything except
        names.json).
        """
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

    # ── Step 2: Names ──────────────────────────────────────────────────────────

    def _build_step3_names(self, layout: QVBoxLayout):
        layout.addWidget(_make_section_label("Step 3 · Translate Name Values (names.json)"))
        layout.addWidget(self._desc(
            "names.json is WolfDawn's project-wide name glossary. Each entry has a safety badge: "
            "safe (display-only), refs (referenced by name but rewritten on inject), or verify "
            "(also in indirect literals - skipped). Phase 0 translates every safe and refs entry "
            "individually, regardless of category, and harvests them into vocab.txt."
        ))

        self.names_summary_label = QLabel("Open this step after extraction to see name counts.")
        self.names_summary_label.setWordWrap(True)
        self.names_summary_label.setStyleSheet(
            "color:#9cdcfe;font-size:13px;padding:8px 10px;"
            "background-color:#1a2430;border:1px solid #2a4a6a;border-radius:4px;"
        )
        layout.addWidget(self.names_summary_label)

        refresh_btn = _make_btn("↻ Refresh name counts", "#555")
        refresh_btn.clicked.connect(self._refresh_names_summary)
        layout.addWidget(refresh_btn)

        layout.addWidget(_make_hr())
        layout.addWidget(self._subheading("Translate names (Phase 0)"))
        layout.addWidget(self._desc(
            "Pick Normal or Batch below, then run Phase 0. Only safe and refs entries are sent to "
            "the model; verify names stay identical to source so inject skips them."
        ))
        self._add_tl_mode_selector(layout)
        tl_btn = self._register(_make_btn("Translate safe names now (Phase 0)", "#00a86b"))
        tl_btn.clicked.connect(
            lambda: self._navigate_to_translation(kinds=PHASE_NAMES_KINDS, auto_start=True)
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
        where = src.parent.name if src else WORK_DIR_NAME
        self.names_summary_label.setText(f"{summary}\nSource: {where}/{NAMES_JSON}")

    def _names_json_path(self) -> Path | None:
        """Locate names.json for reading its note categories (files/ then wolf_json/)."""
        for base in (Path("files"), self._work_dir()):
            p = base / NAMES_JSON
            if p.is_file():
                return p
        return None

    # ── Step 4: Inject ─────────────────────────────────────────────────────────

    def _build_step4_inject(self, layout: QVBoxLayout):
        layout.addWidget(_make_section_label("Step 5 · Inject Translations"))
        layout.addWidget(self._desc(
            "Writes the translated text back into the game's Data/ binaries with WolfDawn, "
            "byte-exact. Translated safe/refs name values from names.json are applied across Data/ "
            "(only the entries you translated change). Lines whose inline codes changed are skipped and "
            "reported (unless you allow drift). Full inject and any inject that includes "
            f"{NAMES_JSON} reset live Data/ from {WORK_DIR_NAME}/originals/ first."
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
            f"{NAMES_JSON} appears here once Phase 0 has translated it (checked by default). "
            "Name injection resets live Data/ from wolf_json/originals/ first, then applies "
            "every safe/refs name across all binaries."
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
            "Injects every extracted document and applies translated name values from names.json "
            "across Data/. Use this once translation is complete before packaging in Step 6."
        ))
        inject_btn = self._register(_make_btn("Inject all translations", "#00a86b"))
        inject_btn.clicked.connect(lambda: self._inject())
        layout.addWidget(inject_btn)

    def _translated_or_source(self, json_name: str) -> Path | None:
        """Prefer translated/<name>; fall back to files/<name>."""
        for base in ("translated", "files"):
            p = Path(base) / json_name
            if p.is_file():
                return p
        return None

    def _on_step_changed(self, idx: int):
        previous = self._current_step_index
        self._current_step_index = idx
        if previous == 0 and idx != 0:
            self._auto_import_if_needed()
        # Index 3 == Names: refresh the per-name safety summary.
        if idx == 3:
            self._refresh_names_summary()
        # Index 5 == Inject: keep the quick-inject picker in sync with translated/.
        elif idx == 5:
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
            default_checked = json_name == NAMES_JSON
            item.setCheckState(Qt.Checked if default_checked else Qt.Unchecked)
            self.inject_list.addItem(item)
            listed += 1
        if listed == 0:
            item = QListWidgetItem("No translated files in translated/ yet — run Step 4.")
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

        def task(log, progress=None):
            from util import wolfdawn

            json_files = []
            for entry in manifest["entries"]:
                p = self._translated_or_source(entry["json"])
                if p:
                    json_files.append(str(p))
            if not json_files:
                return False, "No translated JSON found. Run Step 4 first."
            res = wolfdawn.names_check(json_files, log_fn=log)
            if res.returncode == 0:
                return True, "Name usage is consistent across files."
            return True, "names-check reported inconsistencies (see log above)."

        self._run_task(task)

    def _inject(self, only_json: set[str] | None = None):
        """Inject translations into the game's Data/ binaries.

        only_json:
            None      — full inject: every document + translated name values across Data/.
            set(names)— quick inject: only those JSON files; name values from names.json
                        are applied across Data/ only when NAMES_JSON is included.

        Name values are applied only when translated/names.json exists (i.e. Phase 0
        has run); otherwise names are left untouched.
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

        def task(log, progress=None):
            from util import wolfdawn

            # Guarantee a pristine snapshot to inject from (rebuild from archives if
            # an older extraction predates snapshotting).
            self._ensure_originals(manifest, log, progress)

            entries = manifest["entries"]
            data_dir = manifest["data_dir"]
            data_dir_path = Path(data_dir)
            applied = 0
            failed = 0

            names_entry = next((e for e in entries if e["kind"] == "names"), None)
            names_src = (
                self._translated_or_source(names_entry["json"])
                if names_entry
                else None
            )
            will_names = bool(
                names_entry
                and names_src is not None
                and (only_json is None or names_entry["json"] in only_json)
            )

            if only_json is None or will_names:
                log(f"Resetting live Data/ from {WORK_DIR_NAME}/originals/ …")
                self._restore_live_from_originals(entries, data_dir_path, log)

            names_restored = only_json is None or will_names

            if only_json is None:
                strings_targets = {
                    e["json"] for e in entries if e.get("kind") != "names"
                }
            elif will_names:
                strings_targets = {
                    e["json"]
                    for e in entries
                    if e.get("kind") != "names"
                    and (Path("translated") / e["json"]).is_file()
                }
                strings_targets |= {j for j in only_json if j != NAMES_JSON}
            else:
                strings_targets = set(only_json or ())

            # Non-name documents: inject each pristine original onto its live binary.
            for entry in entries:
                if entry["kind"] == "names":
                    continue
                if entry["json"] not in strings_targets:
                    continue
                src = self._translated_or_source(entry["json"])
                if src is None:
                    log(f"  ⚠ no JSON for {entry['json']} — skipped")
                    continue
                out = entry["base"]  # live game binary (or txt-dir) we write into
                orig = self._orig_base_for(entry, data_dir_path)
                base = str(orig) if orig.exists() else out
                if not orig.exists():
                    log(
                        f"  ⚠ no pristine original for {entry['json']}; injecting against the "
                        "live binary, which fails if it was already translated."
                    )
                log(f"Injecting {entry['json']} → {Path(out).name} …")
                res = wolfdawn.strings_inject(
                    str(src), base, out,
                    allow_code_drift=allow_drift, en_punct=en_punct, log_fn=log,
                )
                a, d = wolfdawn.parse_strings_inject_counts(res.stdout)
                strings_ok = wolfdawn.inject_had_applied(a) or (
                    res.ok and not (a == 0 and (d or 0) > 0)
                )
                if strings_ok:
                    applied += 1
                    _sync_json(entry["json"], src, log)
                    if not res.ok and wolfdawn.inject_had_applied(a):
                        log(
                            f"  ⚠ {entry['json']}: wolf exited {res.returncode} "
                            f"after applying {a} change(s) — see warnings above"
                        )
                elif res.ok:
                    # Exit 0 but nothing applied and lines drifted = stale/injected base.
                    failed += 1
                    log(
                        f"  ⚠ {entry['json']}: 0 applied, {d} skipped as drift — the base "
                        "looks already translated. Restore the pristine original (re-run "
                        "Step 0 Unpack on the untranslated game) and inject again."
                    )
                else:
                    failed += 1
                    log(f"  ⚠ inject exit {res.returncode} for {entry['json']}")

            # Name values: apply across the whole data dir when translated/names.json
            # exists. For a quick inject, only include NAMES_JSON when you want names
            # applied (it rewrites many binaries).
            if will_names and names_entry and names_src is not None:
                if not names_restored:
                    log(
                        f"Resetting live Data/ from {WORK_DIR_NAME}/originals/ "
                        "before name injection …"
                    )
                    self._restore_live_from_originals(entries, data_dir_path, log)
                log("Applying translated name values across Data/ …")
                res = wolfdawn.names_inject(
                    str(names_src), data_dir,
                    allow_code_drift=allow_drift, en_punct=en_punct, log_fn=log,
                )
                out = (res.stdout or "") + (res.stderr or "")
                a, d = wolfdawn.parse_names_inject_counts(out)
                # Keep wolf_json/names.json aligned with translated/ even when the
                # binary pass is a no-op (stale base) or exits 2 after partial guards.
                _sync_json(names_entry["json"], names_src, log)
                if wolfdawn.inject_had_applied(a):
                    applied += 1
                    if not res.ok:
                        log(
                            f"  ⚠ names: wolf exited {res.returncode} after applying "
                            f"{a} name change(s) — see warnings above"
                        )
                elif res.ok and a == 0:
                    failed += 1
                    log(
                        f"  ⚠ names: 0 applied — the live Data/ binaries no longer contain "
                        "the Japanese 'source' strings in names.json (often because a prior "
                        "inject already translated them without resetting from originals). "
                        "Use “Inject all translations”, or tick names.json in quick inject "
                        f"(which resets from {WORK_DIR_NAME}/originals/ first)."
                    )
                elif res.ok and (d or 0) > 0:
                    failed += 1
                    log(
                        f"  ⚠ names: 0 applied, {d} skipped as drift — sources in "
                        f"{NAMES_JSON} no longer match the live binaries. Re-run Step 0 "
                        "extract on the untranslated game, translate again, and inject."
                    )
                else:
                    failed += 1
                    log(f"  ⚠ names-inject exit {res.returncode}")

            msg = f"Injected {applied} document(s)"
            if failed:
                msg += f", {failed} had guard/errors (see log)"
            if quick:
                msg += ". Review the git diff in the game project and test in-game."
            else:
                msg += ". Continue to Step 6 to package."
            return failed == 0, msg

        self._run_task(task)

    # ── Step 5: Package ────────────────────────────────────────────────────────

    def _build_step5_package(self, layout: QVBoxLayout):
        layout.addWidget(_make_section_label("Step 6 · Package the Translated Game"))
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

    # ── Step 6: Saves ──────────────────────────────────────────────────────────

    def _build_step6_saves(self, layout: QVBoxLayout):
        layout.addWidget(_make_section_label("Step 7 · Update Existing Saves (optional)"))
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
