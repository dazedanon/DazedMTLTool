"""
RPGMaker Workflow Tab - Automation hub for the full translation pipeline.

Provides a guided, step-by-step interface:

  Step 0  – Select game project folder and import data files into files/
  Step 1  – (Optional) Pre-process game files
  Step 2  – Auto-detect speaker format and apply to module settings
  Step 3  – Build glossary: parse speakers, then enrich with AI prompt
  Step 4  – Actor variable substitution  (\\n[X] ↔ names)
  Step 5  – Phase 1 (safe dialogue codes) and Phase 2 (risky codes) translation
  Step 6  – Export translated/ back to the game folder
"""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

from PyQt5.QtCore import Qt, QSettings, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStyle,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# ---------------------------------------------------------------------------
# Phase profiles applied to rpgmakermvmz.py before each translation run
# ---------------------------------------------------------------------------

PHASE1_CONFIG = {
    # Safe dialogue / choices
    "CODE101": False,
    "CODE401": True,
    "CODE405": True,
    "CODE102": True,
    "CODE408": True,
    # Risky codes OFF
    "CODE122": False,
    "CODE355655": False,
    "CODE357": False,
    "CODE657": False,
    "CODE356": False,
    "CODE320": False,
    "CODE324": False,
    "CODE325": False,
    "CODE111": False,
    "CODE108": False,
}

PHASE2_CONFIG = {
    # Dialogue OFF (already handled by Phase 1)
    "CODE101": False,
    "CODE401": False,
    "CODE405": False,
    "CODE102": False,
    "CODE408": False,
    # Risky codes ON
    "CODE122": True,
    "CODE357": True,
    "CODE111": True,
    "CODE356": False,   # plugin cmd — user can enable manually if needed
    "CODE108": False,   # comment — rarely needed
}


# ─────────────────────────────────────────────────────────────────────────────
# Background workers
# ─────────────────────────────────────────────────────────────────────────────

class _ScanWorker(QThread):
    """Run project_scanner.list_data_files in a thread."""
    done = pyqtSignal(object)  # list[dict]
    error = pyqtSignal(str)

    def __init__(self, data_path: str, engine: str):
        super().__init__()
        self.data_path = data_path
        self.engine = engine

    def run(self):
        try:
            from util.project_scanner import list_data_files
            result = list_data_files(self.data_path, self.engine)
            self.done.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))


class _ImportWorker(QThread):
    """Copy selected files into files/ directory."""
    done = pyqtSignal(int, list)   # count_copied, errors
    log  = pyqtSignal(str)

    def __init__(self, file_items: list[dict], dest_dir: str):
        super().__init__()
        self.file_items = file_items
        self.dest_dir = dest_dir

    def run(self):
        try:
            from util.project_scanner import import_to_files
            self.log.emit(f"Importing {len(self.file_items)} file(s) into files/ …")
            count, errors = import_to_files(self.file_items, self.dest_dir)
            self.done.emit(count, errors)
        except Exception as exc:
            self.done.emit(0, [str(exc)])


class _ActorSubstituteWorker(QThread):
    done = pyqtSignal(dict)
    log  = pyqtSignal(str)

    def __init__(self, mode: str):  # "substitute" or "restore"
        super().__init__()
        self.mode = mode

    def run(self):
        try:
            from util.actor_substitutor import (
                load_actor_map,
                substitute_in_files,
                restore_in_translated,
            )
            actor_map = load_actor_map()
            if not actor_map:
                self.done.emit({"error": "No actor map found. Make sure files/Actors.json exists."})
                return
            if self.mode == "substitute":
                self.log.emit("Substituting \\n[X] → actor names in files/ …")
                stats = substitute_in_files(actor_map=actor_map)
            else:
                self.log.emit("Restoring actor names → \\n[X] in translated/ …")
                stats = restore_in_translated(actor_map=actor_map)
            self.done.emit(stats)
        except Exception as exc:
            self.done.emit({"error": str(exc)})


class _SpeakerDetectWorker(QThread):
    done = pyqtSignal(dict)
    log  = pyqtSignal(str)

    def run(self):
        try:
            from util.speaker_detector import detect_speaker_format
            self.log.emit("Scanning files/ for speaker patterns …")
            result = detect_speaker_format()
            self.done.emit(result)
        except Exception as exc:
            self.done.emit({"error": str(exc)})


class _ExportWorker(QThread):
    done = pyqtSignal(int, list)
    log  = pyqtSignal(str)

    def __init__(self, game_data_path: str):
        super().__init__()
        self.game_data_path = game_data_path

    def run(self):
        try:
            from util.project_scanner import export_to_game
            self.log.emit(f"Exporting translated/ → {self.game_data_path} …")
            count, errors = export_to_game("translated", self.game_data_path)
            self.done.emit(count, errors)
        except Exception as exc:
            self.done.emit(0, [str(exc)])


class _SubprocessWorker(QThread):
    """Run an arbitrary shell command in a given working directory, streaming output."""
    done = pyqtSignal(bool, str)   # success, final message
    log  = pyqtSignal(str)

    def __init__(self, cmd: list, cwd: str, label: str = ""):
        super().__init__()
        self.cmd   = cmd
        self.cwd   = cwd
        self.label = label or cmd[0]

    def run(self):
        import subprocess
        import shutil as _shutil
        try:
            exe = _shutil.which(self.cmd[0])
            if exe is None:
                self.done.emit(
                    False,
                    f"'{self.cmd[0]}' not found on PATH. "
                    "Make sure it is installed and accessible from the terminal.",
                )
                return
            self.log.emit(f"$ {' '.join(str(c) for c in self.cmd)}  —  cwd: {self.cwd}")
            proc = subprocess.Popen(
                self.cmd,
                cwd=self.cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            for line in proc.stdout:
                stripped = line.rstrip("\n")
                if stripped:
                    self.log.emit(stripped)
            proc.wait()
            if proc.returncode == 0:
                self.done.emit(True, f"{self.label}: finished successfully.")
            else:
                self.done.emit(False, f"{self.label}: exited with code {proc.returncode}.")
        except Exception as exc:
            self.done.emit(False, f"{self.label}: {exc}")


class _FileCopyWorker(QThread):
    """Recursively copy a source folder into a destination folder."""
    done = pyqtSignal(int, list)   # count_copied, errors
    log  = pyqtSignal(str)

    def __init__(self, src: str, dst: str):
        super().__init__()
        self.src = src
        self.dst = dst

    def run(self):
        import shutil
        src = Path(self.src)
        dst = Path(self.dst)
        if not src.is_dir():
            self.done.emit(0, [f"Source folder not found: {src}"])
            return
        dst.mkdir(parents=True, exist_ok=True)
        copied = 0
        errors: list[str] = []
        self.log.emit(f"Copying {src} → {dst} …")
        for fp in src.rglob("*"):
            if not fp.is_file():
                continue
            rel = fp.relative_to(src)
            target = dst / rel
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(fp, target)
                copied += 1
                self.log.emit(f"  copied {rel}")
            except Exception as exc:
                errors.append(f"{rel}: {exc}")
        self.done.emit(copied, errors)


class _JsFormatWorker(QThread):
    """Format a JavaScript file using jsbeautifier (pure Python, no Node required)."""
    done = pyqtSignal(bool, str)
    log  = pyqtSignal(str)

    def __init__(self, js_path: str):
        super().__init__()
        self.js_path = js_path

    def run(self):
        import subprocess as _sp
        import sys
        try:
            import jsbeautifier
        except ImportError:
            self.log.emit("jsbeautifier not installed — installing via pip…")
            r = _sp.run(
                [sys.executable, "-m", "pip", "install", "jsbeautifier"],
                capture_output=True, text=True,
            )
            if r.returncode != 0:
                self.done.emit(False, f"pip install failed: {r.stderr.strip()}")
                return
            self.log.emit("jsbeautifier installed.")
            try:
                import jsbeautifier
            except ImportError:
                self.done.emit(False, "jsbeautifier could not be imported after install.")
                return
        try:
            p = Path(self.js_path)
            self.log.emit(f"Formatting {p.name} …")
            original = p.read_text(encoding="utf-8")
            opts = jsbeautifier.default_options()
            opts.indent_size = 2
            opts.indent_char = " "
            opts.max_preserve_newlines = 2
            opts.preserve_newlines = True
            opts.end_with_newline = True
            formatted = jsbeautifier.beautify(original, opts)
            p.write_text(formatted, encoding="utf-8")
            self.done.emit(True, f"plugins.js formatted successfully ({len(formatted):,} chars).")
        except Exception as exc:
            self.done.emit(False, f"Format error: {exc}")


def _make_section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        "font-size:13px; font-weight:bold; color:#007acc; "
        "padding:8px 0 4px 0; background:transparent;"
    )
    return lbl


def _make_hr() -> QFrame:
    hr = QFrame()
    hr.setFrameShape(QFrame.HLine)
    hr.setFrameShadow(QFrame.Sunken)
    hr.setStyleSheet("QFrame{color:#444;margin:8px 0;}")
    return hr


def _make_btn(text: str, color: str = "#007acc") -> QPushButton:
    btn = QPushButton(text)
    # Derive a slightly lighter hover colour by blending toward white
    try:
        r = int(color[1:3], 16)
        g = int(color[3:5], 16)
        b = int(color[5:7], 16)
        rh = min(255, r + 30)
        gh = min(255, g + 30)
        bh = min(255, b + 30)
        hover_color = f"#{rh:02x}{gh:02x}{bh:02x}"
        rp = max(0, r - 30)
        gp = max(0, g - 30)
        bp = max(0, b - 30)
        press_color = f"#{rp:02x}{gp:02x}{bp:02x}"
    except Exception:
        hover_color = color
        press_color = color
    btn.setStyleSheet(
        f"QPushButton{{background:{color};color:#fff;border:none;"
        f"padding:6px 14px;border-radius:3px;font-size:11px;"
        f"icon-size:16px;"
        f"font-family:'Segoe UI Emoji','Segoe UI','Apple Color Emoji',sans-serif;}}"
        f"QPushButton:hover{{background:{hover_color};}}"
        f"QPushButton:pressed{{background:{press_color};padding:7px 13px 5px 15px;}}"
        f"QPushButton:disabled{{background:#555;color:#999;}}"
    )
    return btn


# ─────────────────────────────────────────────────────────────────────────────
# Main widget
# ─────────────────────────────────────────────────────────────────────────────

class WorkflowTab(QWidget):
    """Guided automation tab for the full RPGMaker translation workflow."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        try:
            self.settings = QSettings("DazedTranslations", "DazedMTLTool")
        except Exception:
            self.settings = None

        # State
        self._data_path: str | None = None
        self._engine: str = "MVMZ"
        self._file_items: list[dict] = []
        self._detect_result: dict | None = None
        self._worker = None  # active background QThread
        # Pre-process paths (auto-populated after folder detection)
        self._plugins_js_path: str = ""
        self._gameupdate_path: str = ""

        self._init_ui()

    # ───────────────────────────────── UI setup ──────────────────────────────

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Splitter: left=steps, right=log
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(4)
        splitter.setStyleSheet("QSplitter::handle{background:#333;}")

        # ---- Left: scrollable step panels ----
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea{border:none;}")
        container = QWidget()
        container.setStyleSheet("background:#1e1e1e;")
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(18, 14, 18, 14)
        vbox.setSpacing(4)

        self._build_step0(vbox)
        vbox.addWidget(_make_hr())
        self._build_preprocess(vbox)
        vbox.addWidget(_make_hr())
        self._build_step3(vbox)
        vbox.addWidget(_make_hr())
        self._build_step1(vbox)
        vbox.addWidget(_make_hr())
        self._build_step2(vbox)
        vbox.addWidget(_make_hr())
        self._build_step4(vbox)
        vbox.addWidget(_make_hr())
        self._build_step6(vbox)
        vbox.addStretch()

        scroll.setWidget(container)
        splitter.addWidget(scroll)

        # ---- Right: log area ----
        log_panel = QWidget()
        log_panel.setStyleSheet("background:#1e1e1e;")
        lp_layout = QVBoxLayout(log_panel)
        lp_layout.setContentsMargins(0, 0, 0, 0)
        lp_layout.setSpacing(0)

        log_header = QLabel("  Log")
        log_header.setStyleSheet(
            "background:#252526;color:#ccc;font-size:11px;"
            "padding:6px 8px;border-bottom:1px solid #333;"
        )
        lp_layout.addWidget(log_header)

        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setFont(QFont("Consolas", 9))
        self.log_area.setStyleSheet(
            "QTextEdit{background:#1e1e1e;color:#d4d4d4;"
            "border:none;padding:8px;}"
        )
        lp_layout.addWidget(self.log_area)

        clear_btn = QPushButton("Clear Log")
        clear_btn.setStyleSheet(
            "QPushButton{background:#252526;color:#888;border:none;"
            "font-size:10px;padding:4px;}QPushButton:hover{color:#ccc;}"
        )
        clear_btn.clicked.connect(self.log_area.clear)
        lp_layout.addWidget(clear_btn)

        splitter.addWidget(log_panel)
        splitter.setSizes([640, 380])

        root.addWidget(splitter)
        self.setLayout(root)

        # Auto-detect on first start if a folder was previously saved
        if self._setting("last_game_folder", ""):
            QTimer.singleShot(100, self._detect_folder)

    # ── Step 0: Project Folder ──────────────────────────────────────────────

    def _build_step0(self, layout: QVBoxLayout):
        layout.addWidget(_make_section_label("Step 0 — Project Folder"))

        # Folder picker row
        row0 = QHBoxLayout()
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("Path to game root folder…")
        self.folder_edit.setStyleSheet(
            "QLineEdit{background:#2d2d30;color:#ccc;border:1px solid #555;"
            "padding:5px;font-size:11px;border-radius:2px;}"
        )
        saved = self._setting("last_game_folder", "")
        if saved:
            self.folder_edit.setText(saved)
        row0.addWidget(self.folder_edit, 1)

        browse_btn = _make_btn(" Browse…")
        browse_btn.setIcon(browse_btn.style().standardIcon(QStyle.SP_DirOpenIcon))
        browse_btn.clicked.connect(self._browse_folder)
        row0.addWidget(browse_btn)

        detect_btn = _make_btn("🔍  Detect", "#3a7a3a")
        detect_btn.setToolTip("Scan the folder to find the data/ directory and list files")
        detect_btn.clicked.connect(self._detect_folder)
        row0.addWidget(detect_btn)
        layout.addLayout(row0)

        # Detected info
        self.detected_label = QLabel("No folder detected yet.")
        self.detected_label.setStyleSheet("color:#888;font-size:10px;padding:2px 0;")
        layout.addWidget(self.detected_label)

        # File list
        self.file_list = QListWidget()
        self.file_list.setMaximumHeight(180)
        self.file_list.setStyleSheet(
            "QListWidget{background:#252526;color:#ccc;border:1px solid #444;"
            "font-size:10px;}"
            "QListWidget::item:selected{background:#37373d;}"
            "QListWidget::item:hover{background:#2a2d2e;}"
        )
        layout.addWidget(self.file_list)

        # Action row
        row1 = QHBoxLayout()
        sel_all = _make_btn("Select All", "#555")
        sel_all.clicked.connect(self._select_all_files)
        row1.addWidget(sel_all)

        sel_core = _make_btn("Core Only", "#555")
        sel_core.setToolTip("Select only core database files; deselect map files")
        sel_core.clicked.connect(self._select_core_only)
        row1.addWidget(sel_core)

        row1.addStretch()

        self.import_btn = _make_btn("⬇  Import Selected → files/", "#007acc")
        self.import_btn.setEnabled(False)
        self.import_btn.clicked.connect(self._import_files)
        row1.addWidget(self.import_btn)
        layout.addLayout(row1)

    # ── Step 1: Vocab / Glossary ────────────────────────────────────────────

    # ── Copilot prompt templates ────────────────────────────────────────────

    _PROMPT_GLOSSARY = (
        "You are helping me build a complete translation glossary for a Japanese RPGMaker game.\n"
        "\n"
        "⚠️ FILE SIZE WARNING: Map files and CommonEvents.json can be extremely large "
        "(hundreds of thousands of lines). Do NOT attempt to read them in full — you will "
        "hit context limits and miss content. Instead, use this strategy:\n"
        "\n"
        "  1. Read the small structured DB files IN FULL first — these are the richest "
        "source of names and are always small:\n"
        "     Actors.json, Classes.json, Troops.json, Skills.json, Items.json, "
        "Armors.json, Weapons.json, States.json, System.json\n"
        "\n"
        "  2. For large files (CommonEvents.json, Map*.json), do NOT read sequentially. "
        "Instead, SEARCH (grep) for:\n"
        "     - Named character patterns: 【, \\\\n<, \\\\k< at the start of dialogue lines\n"
        "     - Unique proper nouns: capitalised katakana clusters or kanji compound nouns "
        "in \"message\" or \"parameters\" fields\n"
        "     Scan Map001.json through Map010.json at most — early maps have the most "
        "story-critical dialogue.\n"
        "\n"
        "  3. Stop adding entries once you stop finding new names/terms — do not pad.\n"
        "\n"
        "Produce TWO sections of output.\n"
        "\n"
        "Output the results EXACTLY in the format shown below, including the category headers "
        "starting with #. Do not add any other text, preamble, or explanation outside the entries.\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "# Game Characters\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Identify every NAMED CHARACTER that appears in dialogue or descriptions.\n"
        "For each character provide:\n"
        "  - Japanese name (katakana/kanji as it appears in-game)\n"
        "  - English transliteration or translation\n"
        "  - Gender (Male / Female / Unknown) — infer from speech patterns or pronouns\n"
        "  - Role (protagonist, antagonist, NPC, etc.)\n"
        "  - Speech register and personality notes — how they speak, their tone, any nicknames, "
        "whether their name is player-chosen, etc.\n"
        "\n"
        "Format — the header line, then one entry per line:\n"
        "# Game Characters\n"
        "\u30b7\u30ed (Shiro) - Female; protagonist; player-controlled (Actors.json ID 1); "
        "speaks in a flustered, cute register with feminine speech markers; nickname \u30d0\u30ab\u732b\u3002\n"
        "\u30af\u30ed\u30cd (Kurone) - Female; antagonist; cold and terse; speaks in short cutting sentences\n"
        "\n"
        "Rules:\n"
        "  - Named characters only — no generic enemy types or unnamed NPCs.\n"
        "  - If a character has a player-chosen name (e.g. Actors.json id 1), note it explicitly.\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "# Worldbuilding Terms\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Identify lore-specific terms that appear in dialogue, descriptions, or narration "
        "but do NOT have a dedicated database file — i.e. terms the translation tool will NOT "
        "auto-populate from Skills.json, Items.json, Armors.json, Weapons.json, etc.\n"
        "\n"
        "Target specifically:\n"
        "  - Faction / organisation names (kingdoms, guilds, cults, nations)\n"
        "  - Location names mentioned in dialogue but not map titles\n"
        "  - Unique magic systems, schools of magic, or power classifications\n"
        "  - Lore titles and honorifics unique to this setting\n"
        "  - Recurring in-universe concepts or proper nouns with no English equivalent\n"
        "\n"
        "Format — the header line, then one entry per line:\n"
        "# Worldbuilding Terms\n"
        "\u9b54\u4e16\u754c (Demon World) - The demonic realm referenced in NPC dialogue; not a named map\n"
        "\u8056\u5263\u6559\u56e3 (Holy Blade Order) - Antagonist faction controlling the eastern territories\n"
        "\n"
        "Rules:\n"
        "  - Do NOT list skill names, item names, weapon names, armour names — the tool handles those.\n"
        "  - Skip generic RPG words (\u30dd\u30fc\u30b7\u30e7\u30f3, \u30ec\u30d9\u30eb, \u30b9\u30c6\u30fc\u30bf\u30b9, etc.).\n"
        "  - Do NOT repeat character names here.\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "COMPLETE EXAMPLE OUTPUT\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Below is what a correct, well-formed response looks like.\n"
        "Your output should follow this structure exactly:\n"
        "\n"
        "```\n"
        "# Game Characters\n"
        "アリア (Aria) - Female; protagonist; player-chosen name (Actors.json ID 1); "
        "speaks cheerfully in casual feminine speech; nicknamed アリアちゃん by her sister\n"
        "ゼクス (Zex) - Male; antagonist; cold and commanding; addresses others with contempt; "
        "uses archaic formal register\n"
        "カナエ (Kanae) - Female; NPC shopkeeper; warm and motherly; ends sentences with わね\n"
        "\n"
        "# Worldbuilding Terms\n"
        "虚無の穴 (Void Rift) - Dimensional tear referenced repeatedly in Act 2 NPC dialogue; "
        "not a named map location\n"
        "鋼の誓約 (Iron Vow) - Sacred oath-binding ritual unique to the knightly order; "
        "appears in story cutscenes\n"
        "裁定者 (Arbiter) - Title held by the ruling council; lore-specific rank with no "
        "real-world equivalent\n"
        "```\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "GLOBAL RULES (apply to both sections)\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "  - NEVER give two options for any term (e.g. 'Sylfia / Sylphia' is wrong). "
        "Always commit to a single best translation. If multiple transliterations exist, "
        "pick the most etymologically accurate or natural-sounding one and use only that.\n"
        "  - Use a plain hyphen-minus (-) as the separator between the Japanese entry and "
        "its description. Never use an em dash (\u2014) or en dash (\u2013) \u2014 the "
        "translation tool only recognises the plain hyphen."
    )

    # ── Step 1 (Optional): Pre-process ────────────────────────────────

    def _build_preprocess(self, layout: QVBoxLayout):
        header_row = QHBoxLayout()
        header_row.addWidget(_make_section_label("Step 1 (Optional) — Pre-process"))
        opt_badge = QLabel("personal / optional")
        opt_badge.setStyleSheet(
            "color:#888;font-size:9px;border:1px solid #555;"
            "padding:1px 6px;border-radius:8px;margin-left:6px;"
        )
        header_row.addWidget(opt_badge)
        header_row.addStretch()
        layout.addLayout(header_row)

        hint = QLabel(
            "Three optional preparation tasks to run against the game folder before "
            "importing files. Paths are auto-filled when a project folder is detected."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#888;font-size:10px;padding-bottom:6px;")
        layout.addWidget(hint)

        tasks_box = QGroupBox()
        tasks_box.setStyleSheet(
            "QGroupBox{border:1px solid #3a3a3a;border-radius:3px;margin-top:4px;"
            "padding:6px;background:#1a1a1a;}"
        )
        tb = QVBoxLayout(tasks_box)
        tb.setSpacing(10)

        # ---- Task A: dazedformat -----------------------------------------
        ta = QGroupBox("A — Format JSON files with dazedformat")
        ta.setStyleSheet(self._task_box_style())
        ta_inner = QVBoxLayout(ta)
        ta_inner.setSpacing(4)
        ta_desc = QLabel(
            "Runs  <code>dazedformat .</code>  in the game\'s data folder to "
            "normalise all JSON files before importing."
        )
        ta_desc.setTextFormat(Qt.RichText)
        ta_desc.setWordWrap(True)
        ta_desc.setStyleSheet("color:#aaa;font-size:10px;")
        ta_inner.addWidget(ta_desc)
        ta_path_row = QHBoxLayout()
        ta_path_row.addWidget(QLabel("Data folder:"))
        self.pp_data_path_label = QLabel("(detect a project folder first)")
        self.pp_data_path_label.setStyleSheet("color:#888;font-size:10px;")
        ta_path_row.addWidget(self.pp_data_path_label, 1)
        ta_inner.addLayout(ta_path_row)
        ta_btn_row = QHBoxLayout()
        run_dazed = _make_btn("▶  Run dazedformat", "#555")
        run_dazed.clicked.connect(self._run_dazedformat)
        ta_btn_row.addWidget(run_dazed)
        ta_btn_row.addStretch()
        ta_inner.addLayout(ta_btn_row)
        tb.addWidget(ta)

        # ---- Task B: prettier on plugins.js -----------------------------
        tb_box = QGroupBox("B — Format plugins.js with Prettier")
        tb_box.setStyleSheet(self._task_box_style())
        tb_inner = QVBoxLayout(tb_box)
        tb_inner.setSpacing(4)
        tb_desc = QLabel(
            "Formats plugins.js using <code>jsbeautifier</code> (pure Python — no Node.js required) "
            "so it is human-readable before editing or inspection."
        )
        tb_desc.setTextFormat(Qt.RichText)
        tb_desc.setWordWrap(True)
        tb_desc.setStyleSheet("color:#aaa;font-size:10px;")
        tb_inner.addWidget(tb_desc)
        tb_path_row = QHBoxLayout()
        tb_path_lbl = QLabel("plugins.js:")
        tb_path_row.addWidget(tb_path_lbl)
        self.pp_plugins_edit = QLineEdit()
        self.pp_plugins_edit.setPlaceholderText("Path to plugins.js…")
        self.pp_plugins_edit.setStyleSheet(
            "QLineEdit{background:#2d2d30;color:#ccc;border:1px solid #555;"
            "padding:3px;font-size:10px;border-radius:2px;}"
        )
        tb_path_row.addWidget(self.pp_plugins_edit, 1)
        browse_plugins = _make_btn("", "#444")
        browse_plugins.setIcon(browse_plugins.style().standardIcon(QStyle.SP_DirOpenIcon))
        browse_plugins.setFixedWidth(34)
        browse_plugins.clicked.connect(self._browse_plugins_js)
        tb_path_row.addWidget(browse_plugins)
        tb_inner.addLayout(tb_path_row)
        tb_btn_row = QHBoxLayout()
        run_prettier = _make_btn("▶  Format plugins.js", "#555")
        run_prettier.clicked.connect(self._run_prettier)
        tb_btn_row.addWidget(run_prettier)
        tb_btn_row.addStretch()
        tb_inner.addLayout(tb_btn_row)
        tb.addWidget(tb_box)

        # ---- Task C: copy gameupdate/ -----------------------------------
        tc = QGroupBox("C — Apply gameupdate/ patch files")
        tc.setStyleSheet(self._task_box_style())
        tc_inner = QVBoxLayout(tc)
        tc_inner.setSpacing(4)
        tc_desc = QLabel(
            "Copies everything from the <code>gameupdate/</code> folder "
            "into the game\'s root folder, overwriting existing files."
        )
        tc_desc.setTextFormat(Qt.RichText)
        tc_desc.setWordWrap(True)
        tc_desc.setStyleSheet("color:#aaa;font-size:10px;")
        tc_inner.addWidget(tc_desc)

        tc_src_row = QHBoxLayout()
        tc_src_row.addWidget(QLabel("Source:"))
        self.pp_gameupdate_edit = QLineEdit()
        self.pp_gameupdate_edit.setPlaceholderText("Path to gameupdate/ folder…")
        self.pp_gameupdate_edit.setStyleSheet(
            "QLineEdit{background:#2d2d30;color:#ccc;border:1px solid #555;"
            "padding:3px;font-size:10px;border-radius:2px;}"
        )
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
        self.pp_gameupdate_dst_label.setStyleSheet("color:#888;font-size:10px;")
        tc_dst_row.addWidget(self.pp_gameupdate_dst_label, 1)
        tc_inner.addLayout(tc_dst_row)

        tc_btn_row = QHBoxLayout()
        run_gu = _make_btn("▶  Copy gameupdate/", "#555")
        run_gu.clicked.connect(self._run_gameupdate)
        tc_btn_row.addWidget(run_gu)
        tc_btn_row.addStretch()
        tc_inner.addLayout(tc_btn_row)
        tb.addWidget(tc)

        layout.addWidget(tasks_box)

        # ---- Run All button ------------------------------------------
        run_all_row = QHBoxLayout()
        run_all_btn = _make_btn("▶▶  Run All 3 Tasks", "#007acc")
        run_all_btn.setToolTip("Run dazedformat, prettier, and gameupdate copy in sequence")
        run_all_btn.clicked.connect(self._run_all_preprocess)
        run_all_row.addStretch()
        run_all_row.addWidget(run_all_btn)
        layout.addLayout(run_all_row)

    @staticmethod
    def _task_box_style() -> str:
        return (
            "QGroupBox{color:#bbb;border:1px solid #444;border-radius:2px;"
            "margin-top:6px;font-size:10px;padding:4px;}"
            "QGroupBox::title{padding:0 4px;}"
        )

    def _build_step1(self, layout: QVBoxLayout):
        layout.addWidget(_make_section_label("Step 3 — Glossary (vocab.txt)"))
        hint = QLabel(
            "Edit your glossary below. Character names, genders, and worldbuilding terms "
            "here are injected into every AI prompt for consistent terminology."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#888;font-size:10px;padding-bottom:4px;")
        layout.addWidget(hint)

        # ---- Parse Speakers -------------------------------------------------
        spk_box = QGroupBox("2a — Parse Speakers (Auto-detect Names)")
        spk_box.setStyleSheet(
            "QGroupBox{color:#ccc;border:1px solid #444;border-radius:3px;"
            "margin-top:8px;font-size:11px;}"
            "QGroupBox::title{padding:0 6px;}"
        )
        spk_inner = QVBoxLayout(spk_box)
        spk_inner.setSpacing(6)

        spk_hint = QLabel(
            "Scans every file in <b>files/</b> and extracts all detected speaker names "
            "into a <b># Speakers</b> section of vocab.txt. "
            "Run this first — the AI prompt below will then work from the pre-populated "
            "list and can enrich entries with gender, role, and speech register."
        )
        spk_hint.setTextFormat(Qt.RichText)
        spk_hint.setWordWrap(True)
        spk_hint.setStyleSheet("color:#888;font-size:10px;")
        spk_inner.addWidget(spk_hint)

        spk_row = QHBoxLayout()
        self._parse_speakers_status = QLabel("")
        self._parse_speakers_status.setStyleSheet("color:#aaa;font-size:10px;")
        spk_row.addWidget(self._parse_speakers_status, 1)
        self._parse_speakers_btn = _make_btn("🔍  Parse Speakers", "#007acc")
        self._parse_speakers_btn.setToolTip(
            "Scan all game files for speaker names and write them to vocab.txt"
        )
        self._parse_speakers_btn.clicked.connect(self._run_parse_speakers)
        spk_row.addWidget(self._parse_speakers_btn)
        spk_inner.addLayout(spk_row)

        layout.addWidget(spk_box)

        # ---- Copilot / Cursor prompt helpers --------------------------------
        prompt_box = QGroupBox("2b — AI Prompt Helpers (Copilot / Cursor)")
        prompt_box.setStyleSheet(
            "QGroupBox{color:#ccc;border:1px solid #444;border-radius:3px;"
            "margin-top:8px;font-size:11px;}"
            "QGroupBox::title{padding:0 6px;}"
        )
        pb_inner = QVBoxLayout(prompt_box)
        pb_inner.setSpacing(6)

        prompt_hint = QLabel(
            "After parsing speakers above, copy the prompt below and paste it into "
            "GitHub Copilot Chat or Cursor with your game files open. "
            "The AI will enrich the speaker list with gender, role, and speech register "
            "and add worldbuilding terms. Paste the AI's output back into vocab.txt."
        )
        prompt_hint.setWordWrap(True)
        prompt_hint.setStyleSheet("color:#888;font-size:10px;")
        pb_inner.addWidget(prompt_hint)

        # Combined glossary prompt
        glossary_row = QHBoxLayout()
        glossary_label = QLabel(
            "👥🌍  <b>Full Glossary</b> — named characters (with gender &amp; role) "
            "and unique worldbuilding terms in one pass."
        )
        glossary_label.setTextFormat(Qt.RichText)
        glossary_label.setWordWrap(True)
        glossary_label.setStyleSheet("color:#ccc;font-size:10px;")
        glossary_row.addWidget(glossary_label, 1)
        copy_glossary_btn = _make_btn("📋  Copy Prompt", "#555")
        copy_glossary_btn.setToolTip("Copy the full glossary discovery prompt to clipboard")
        copy_glossary_btn.clicked.connect(lambda: self._copy_to_clipboard(self._PROMPT_GLOSSARY, "Glossary prompt copied."))
        glossary_row.addWidget(copy_glossary_btn)
        pb_inner.addLayout(glossary_row)

        layout.addWidget(prompt_box)

        # ---- vocab.txt editor -----------------------------------------------
        layout.addWidget(_make_section_label("vocab.txt editor"))
        format_hint = QLabel(
            "Put character entries under  # Game Characters  — they are always sent to the AI.\n"
            "Format:  Japanese (English) - Gender; role; speech register / personality notes\n"
            "Example:  シロ (Shiro) - Female; protagonist; speaks in a flustered, cute register with feminine speech markers\n"
            "Universal terms (honorifics, elements, etc.) live in vocab_base.txt and are auto-appended on every save."
        )
        format_hint.setFont(QFont("Consolas", 9))
        format_hint.setStyleSheet(
            "color:#569cd6;background:#252526;border:1px solid #3a3a3a;"
            "padding:5px 8px;border-radius:2px;font-size:10px;"
        )
        layout.addWidget(format_hint)

        self.vocab_editor = QTextEdit()
        self.vocab_editor.setMinimumHeight(160)
        self.vocab_editor.setFont(QFont("Consolas", 9))
        self.vocab_editor.setStyleSheet(
            "QTextEdit{background:#252526;color:#d4d4d4;border:1px solid #444;"
            "padding:6px;}"
        )
        self._reload_vocab()
        layout.addWidget(self.vocab_editor)

        row = QHBoxLayout()
        save_vocab = _make_btn("💾  Save vocab.txt", "#3a7a3a")
        save_vocab.clicked.connect(self._save_vocab)
        row.addWidget(save_vocab)

        reload_vocab = _make_btn("↺  Reload", "#555")
        reload_vocab.clicked.connect(self._reload_vocab)
        row.addWidget(reload_vocab)
        row.addStretch()
        layout.addLayout(row)

    # ── Step 2: Actor Variables ─────────────────────────────────────────────

    def _build_step2(self, layout: QVBoxLayout):
        layout.addWidget(_make_section_label("Step 4 — Actor Variable Substitution"))
        hint = QLabel(
            "Replaces  \\n[X]  RPGMaker name variables with actual actor names "
            "so the AI has proper context. After translation the variables are "
            "restored — rename-able protagonists continue to work at runtime."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#888;font-size:10px;padding-bottom:4px;")
        layout.addWidget(hint)

        self.actor_status = QLabel("Click Scan to preview substitutions.")
        self.actor_status.setWordWrap(True)
        self.actor_status.setStyleSheet("color:#aaa;font-size:10px;padding:4px 0;")
        layout.addWidget(self.actor_status)

        row = QHBoxLayout()
        scan_actors = _make_btn("🔍  Scan \\n[X] usage", "#555")
        scan_actors.setToolTip("Scan files/ and show which actor IDs are referenced")
        scan_actors.clicked.connect(self._scan_actor_vars)
        row.addWidget(scan_actors)
        row.addStretch()
        layout.addLayout(row)

        row2 = QHBoxLayout()
        self.sub_btn = _make_btn("▶  Substitute \\n[X] → Names  (pre-translation)", "#007acc")
        self.sub_btn.setToolTip("Modifies files/ in-place. Run before translating.")
        self.sub_btn.clicked.connect(self._substitute_actors)
        row2.addWidget(self.sub_btn)

        self.restore_btn = _make_btn("↩  Restore Names → \\n[X]  (post-translation)", "#7a4a7a")
        self.restore_btn.setToolTip("Modifies translated/ in-place. Run after translating.")
        self.restore_btn.clicked.connect(self._restore_actors)
        row2.addWidget(self.restore_btn)
        layout.addLayout(row2)

    # ── Step 3: Speaker Detection ───────────────────────────────────────────

    def _build_step3(self, layout: QVBoxLayout):
        layout.addWidget(_make_section_label("Step 2 — Speaker Format Detection"))
        hint = QLabel(
            "Scans map files to determine how speaker names are embedded in dialogue "
            "and automatically sets the correct INLINE401SPEAKERS / FIRSTLINESPEAKERS "
            "/ FACENAME101 flags."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#888;font-size:10px;padding-bottom:4px;")
        layout.addWidget(hint)

        self.speaker_result = QLabel("Run the scan to auto-detect speaker format.")
        self.speaker_result.setWordWrap(True)
        self.speaker_result.setStyleSheet(
            "color:#aaa;font-size:10px;padding:4px 0;"
            "background:#252526;border:1px solid #444;padding:6px;border-radius:2px;"
        )
        layout.addWidget(self.speaker_result)

        row = QHBoxLayout()
        scan_spk = _make_btn("🔍  Scan Speaker Format", "#555")
        scan_spk.clicked.connect(self._detect_speakers)
        row.addWidget(scan_spk)

        self.apply_speaker_btn = _make_btn("✔  Apply to RPGMaker Settings", "#3a7a3a")
        self.apply_speaker_btn.setEnabled(False)
        self.apply_speaker_btn.clicked.connect(self._apply_speaker_settings)
        row.addWidget(self.apply_speaker_btn)
        row.addStretch()
        layout.addLayout(row)

    # ── Step 4: Translation ─────────────────────────────────────────────────

    def _build_step4(self, layout: QVBoxLayout):
        layout.addWidget(_make_section_label("Step 5 — Translation"))

        p1_box = QGroupBox("Phase 1  –  Safe Codes (dialogue + choices)")
        p1_box.setStyleSheet(
            "QGroupBox{color:#ccc;border:1px solid #444;border-radius:3px;"
            "margin-top:8px;font-size:11px;}"
            "QGroupBox::title{padding:0 6px;}"
        )
        p1_inner = QVBoxLayout(p1_box)
        p1_desc = QLabel("Codes: 401 (Show Text), 405 (continued), 102 (Choices), 408 (extra lines)\n"
                          "These rarely break game logic — safe to translate first.")
        p1_desc.setStyleSheet("color:#888;font-size:10px;")
        p1_desc.setWordWrap(True)
        p1_inner.addWidget(p1_desc)
        p1_row = QHBoxLayout()
        run_p1 = _make_btn("▶  Run Phase 1", "#007acc")
        run_p1.clicked.connect(lambda: self._run_phase(1))
        p1_row.addWidget(run_p1)
        p1_row.addStretch()
        p1_inner.addLayout(p1_row)
        layout.addWidget(p1_box)

        p2_box = QGroupBox("Phase 2  –  Risky Codes (variables + conditionals)")
        p2_box.setStyleSheet(
            "QGroupBox{color:#ccc;border:1px solid #444;border-radius:3px;"
            "margin-top:8px;font-size:11px;}"
            "QGroupBox::title{padding:0 6px;}"
        )
        p2_inner = QVBoxLayout(p2_box)
        p2_desc = QLabel(
            "Codes: 122 (Control Variables), 357 (Plugin Commands), 111 (Conditional Branch)\n"
            "Strings in these codes are often used in script comparisons — mistranslations "
            "can break game logic. Scan first, then translate carefully."
        )
        p2_desc.setStyleSheet("color:#888;font-size:10px;")
        p2_desc.setWordWrap(True)
        p2_inner.addWidget(p2_desc)

        p2_row = QHBoxLayout()
        scan_p2 = _make_btn("🔍  Scan Risky Strings", "#555")
        scan_p2.setToolTip(
            "Preview all unique string values in codes 122 / 357 / 111 "
            "before deciding what to translate."
        )
        scan_p2.clicked.connect(self._scan_risky_strings)
        p2_row.addWidget(scan_p2)

        run_p2 = _make_btn("▶  Run Phase 2", "#7a4a00")
        run_p2.clicked.connect(lambda: self._run_phase(2))
        p2_row.addWidget(run_p2)
        p2_row.addStretch()
        p2_inner.addLayout(p2_row)
        layout.addWidget(p2_box)

    # ── Step 6: Export ──────────────────────────────────────────────────────

    def _build_step6(self, layout: QVBoxLayout):
        layout.addWidget(_make_section_label("Step 6 — Export to Game"))
        hint = QLabel(
            "Copy all files from translated/ back into the game's data folder "
            "to patch the game in-place."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#888;font-size:10px;padding-bottom:4px;")
        layout.addWidget(hint)

        row = QHBoxLayout()
        export_btn = _make_btn("📤  Export translated/ → Game Folder", "#3a7a3a")
        export_btn.clicked.connect(self._export_to_game)
        row.addWidget(export_btn)
        row.addStretch()
        layout.addLayout(row)

    # ─────────────────────────────────────────────────────────────────────────
    # Step 0 – Project Folder logic
    # ─────────────────────────────────────────────────────────────────────────

    def _browse_folder(self):
        start = self.folder_edit.text() or self._setting("last_game_folder", "")
        folder = QFileDialog.getExistingDirectory(self, "Select Game Root Folder", start)
        if folder:
            self.folder_edit.setText(folder)
            self._save_setting("last_game_folder", folder)
            self._detect_folder()

    def _detect_folder(self):
        folder = self.folder_edit.text().strip()
        if not folder:
            self._log("⚠  No folder path entered.")
            return

        self._save_setting("last_game_folder", folder)
        self.detected_label.setText("Scanning…")
        self.file_list.clear()
        self.import_btn.setEnabled(False)

        try:
            from util.project_scanner import find_data_folder
            data_path, engine = find_data_folder(folder)
        except Exception as exc:
            self.detected_label.setText(f"Error: {exc}")
            return

        if data_path is None:
            self.detected_label.setText(
                "⚠  No recognised data folder found. "
                "Make sure this is a valid RPGMaker game directory."
            )
            return

        self._data_path = str(data_path)
        self._engine = engine
        self.detected_label.setText(
            f"Engine: {engine}   ·   Data folder: {data_path}"
        )
        self._log(f"Detected data folder: {data_path}  (engine: {engine})")

        worker = _ScanWorker(self._data_path, self._engine)
        worker.done.connect(self._on_scan_done)
        worker.error.connect(lambda e: self._log(f"❌ Scan error: {e}"))
        self._worker = worker
        worker.start()

    def _on_scan_done(self, items: list):
        self._file_items = items
        self.file_list.clear()

        for item in items:
            cat = item["category"]
            icon = "📄" if cat == "core" else ("🗺" if cat == "map" else "❓")
            lw = QListWidgetItem(f"{icon}  {item['name']}  ({item['size_kb']:.1f} KB)")
            lw.setData(Qt.UserRole, item)
            lw.setCheckState(Qt.Checked if item["default"] else Qt.Unchecked)
            if cat == "core":
                lw.setForeground(__import__("PyQt5.QtGui", fromlist=["QColor"]).QColor("#9cdcfe"))
            elif cat == "map":
                lw.setForeground(__import__("PyQt5.QtGui", fromlist=["QColor"]).QColor("#c5c5c0"))
            self.file_list.addItem(lw)

        self.import_btn.setEnabled(len(items) > 0)
        self._log(f"Found {len(items)} importable file(s).")
        self._populate_preprocess_paths()

    def _select_all_files(self):
        count = self.file_list.count()
        for i in range(count):
            self.file_list.item(i).setCheckState(Qt.Checked)
        if count:
            self._log(f"✔  Selected all {count} file(s).")

    def _select_core_only(self):
        core = other = 0
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            data = item.data(Qt.UserRole)
            is_core = bool(data and data.get("category") == "core")
            item.setCheckState(Qt.Checked if is_core else Qt.Unchecked)
            if is_core:
                core += 1
            else:
                other += 1
        if self.file_list.count():
            self._log(f"✔  Selected {core} core file(s); deselected {other} other(s).")

    def _import_files(self):
        selected = []
        for i in range(self.file_list.count()):
            lw = self.file_list.item(i)
            if lw.checkState() == Qt.Checked:
                selected.append(lw.data(Qt.UserRole))

        if not selected:
            self._log("⚠  No files selected.")
            return

        self.import_btn.setEnabled(False)
        worker = _ImportWorker(selected, "files")
        worker.log.connect(self._log)
        worker.done.connect(self._on_import_done)
        self._worker = worker
        worker.start()

    def _on_import_done(self, count: int, errors: list):
        self.import_btn.setEnabled(True)
        if errors:
            self._log(f"⚠  {len(errors)} error(s) during import:")
            for e in errors[:10]:
                self._log(f"   {e}")
        self._log(f"✅ Imported {count} file(s) into files/")

    # ─────────────────────────────────────────────────────────────────────────
    # Step 1 – Vocab
    # ─────────────────────────────────────────────────────────────────────────

    def _run_parse_speakers(self):
        """Launch a speaker-parse pass over files/ and write results to vocab.txt."""
        try:
            from gui.translation_tab import TranslationWorker
        except Exception as exc:
            self._log(f"Could not import TranslationWorker: {exc}")
            return

        project_root = Path(__file__).parent.parent
        files_dir = project_root / "files"
        all_json = sorted(
            p.name for p in files_dir.glob("*.json") if p.name != ".gitkeep"
        ) if files_dir.exists() else []

        if not all_json:
            self._log("No JSON files found in files/. Run Step 1 (import) first.")
            self._parse_speakers_status.setText("No files found in files/.")
            return

        self._log(f"Parsing speakers from {len(all_json)} file(s)...")
        self._parse_speakers_btn.setEnabled(False)
        self._parse_speakers_status.setText("Running...")

        module_info = ["RPG Maker MV/MZ", [".json"], None]
        worker = TranslationWorker(
            project_root, module_info, estimate_only=False,
            selected_files=all_json,
            parse_speakers=True,
        )
        worker.log_signal.connect(self._log)
        worker.progress_signal.connect(
            lambda cur, tot, fn: self._parse_speakers_status.setText(
                f"[{cur}/{tot}] {Path(fn).name}"
            )
        )
        worker.finished_signal.connect(self._on_parse_speakers_done)
        self._worker = worker
        worker.start()

    def _on_parse_speakers_done(self, ok: bool, msg: str):
        self._parse_speakers_btn.setEnabled(True)
        if ok:
            self._parse_speakers_status.setText(
                "Done — # Speakers section written to vocab.txt"
            )
            self._reload_vocab()
            self._log("Speaker parse complete. vocab.txt updated with # Speakers.")
        else:
            self._parse_speakers_status.setText(f"Failed: {msg}")
            self._log(f"Speaker parse failed: {msg}")

    _BASE_SEPARATOR = "# ── Base Vocabulary (auto-appended from vocab_base.txt — do not edit below) ──\n"

    def _reload_vocab(self):
        vocab_path = Path("vocab.txt")
        try:
            if vocab_path.exists():
                text = vocab_path.read_text(encoding="utf-8")
                # Strip the auto-appended base section so editor shows only game-specific content
                sep_idx = text.find(self._BASE_SEPARATOR)
                if sep_idx != -1:
                    text = text[:sep_idx].rstrip("\n")
                self.vocab_editor.setPlainText(text)
            else:
                self.vocab_editor.setPlainText("# Add character glossary entries here\n")
        except Exception as exc:
            self._log(f"❌ Could not load vocab.txt: {exc}")

    def _save_vocab(self):
        try:
            game_text = self.vocab_editor.toPlainText().rstrip("\n")
            base_path = Path("vocab_base.txt")
            base_text = base_path.read_text(encoding="utf-8") if base_path.exists() else ""
            combined = game_text + "\n\n" + self._BASE_SEPARATOR + base_text
            Path("vocab.txt").write_text(combined, encoding="utf-8")
            self._log("✅ vocab.txt saved (base terms from vocab_base.txt appended).")
        except Exception as exc:
            self._log(f"❌ Could not save vocab.txt: {exc}")

    # ─────────────────────────────────────────────────────────────────────────
    # Step 2 – Actor substitution
    # ─────────────────────────────────────────────────────────────────────────

    def _scan_actor_vars(self):
        try:
            from util.actor_substitutor import scan_variables, load_actor_map
            counts = scan_variables("files")
            actor_map = load_actor_map()
            if not counts:
                self.actor_status.setText("No \\n[X] variables found in files/")
                return
            lines = []
            for aid, cnt in sorted(counts.items()):
                name = actor_map.get(aid, "???")
                lines.append(f"  \\n[{aid}] → {name}  ({cnt} occurrence(s))")
            self.actor_status.setText("\n".join(lines))
            self._log("Actor variable scan complete.")
        except Exception as exc:
            self._log(f"❌ Scan error: {exc}")

    def _substitute_actors(self):
        reply = QMessageBox.question(
            self,
            "Substitute Actor Variables",
            "This will modify files/ in-place, replacing \\n[X] codes with actor names.\n\n"
            "Back up files/ first if needed. Continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return
        self.sub_btn.setEnabled(False)
        w = _ActorSubstituteWorker("substitute")
        w.log.connect(self._log)
        w.done.connect(self._on_actor_done)
        self._worker = w
        w.start()

    def _restore_actors(self):
        reply = QMessageBox.question(
            self,
            "Restore Actor Variables",
            "This will modify translated/ in-place, replacing actor names back with \\n[X] codes.\n\n"
            "Continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return
        self.restore_btn.setEnabled(False)
        w = _ActorSubstituteWorker("restore")
        w.log.connect(self._log)
        w.done.connect(self._on_actor_done)
        self._worker = w
        w.start()

    def _on_actor_done(self, stats: dict):
        self.sub_btn.setEnabled(True)
        self.restore_btn.setEnabled(True)
        if "error" in stats:
            self._log(f"❌ {stats['error']}")
            return
        mods = stats.get("files_modified", 0)
        total = stats.get("total_substitutions", 0)
        found = stats.get("variables_found", {})
        errors = stats.get("errors", [])
        self._log(
            f"✅ {total} substitution(s) across {mods} file(s). "
            f"Actors: {', '.join(f'ID {k}={v}' for k, v in found.items()) or 'none'}"
        )
        for e in errors:
            self._log(f"   ⚠  {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # Step 3 – Speaker detection
    # ─────────────────────────────────────────────────────────────────────────

    def _detect_speakers(self):
        self.apply_speaker_btn.setEnabled(False)
        self.speaker_result.setText("Scanning…")
        w = _SpeakerDetectWorker()
        w.log.connect(self._log)
        w.done.connect(self._on_speaker_done)
        self._worker = w
        w.start()

    def _on_speaker_done(self, result: dict):
        if "error" in result:
            self.speaker_result.setText(f"❌ Error: {result['error']}")
            self._log(f"❌ Speaker detection error: {result['error']}")
            return

        self._detect_result = result
        scores = result.get("scores", {})
        best = result.get("best_mode", "NONE")
        conf = result.get("confidence", "low")
        note = result.get("note", "")

        conf_color = {"high": "#4ec9b0", "medium": "#dcdcaa", "low": "#f48771"}.get(conf, "#ccc")
        score_str = "  |  ".join(f"{k}: {v}" for k, v in scores.items())
        self.speaker_result.setText(
            f"Best mode: {best}  ({conf} confidence)\n"
            f"Scores — {score_str}\n"
            f"{note}"
        )
        self._log(f"Speaker detection: {best} ({conf}) — {note}")

        if best != "NONE":
            self.apply_speaker_btn.setEnabled(True)

    def _apply_speaker_settings(self):
        if not self._detect_result:
            return
        cfg = self._detect_result.get("recommended_config", {})
        try:
            from gui.config_integration import ConfigIntegration
            ci = ConfigIntegration()
            ci.update_rpgmaker_config(cfg)
            self._log(
                f"✅ Applied speaker settings: "
                + ", ".join(f"{k}={v}" for k, v in cfg.items())
            )
            # Refresh the RPGMaker tab if accessible
            self._refresh_rpgmaker_tab(cfg)
        except Exception as exc:
            self._log(f"❌ Could not apply settings: {exc}")

    def _refresh_rpgmaker_tab(self, cfg: dict):
        """Push the new config to the RPGMaker tab widget so it refreshes live."""
        try:
            if self.parent_window and hasattr(self.parent_window, "config_tab"):
                ct = self.parent_window.config_tab
                if hasattr(ct, "rpgmaker_tab") and ct.rpgmaker_tab:
                    ct.rpgmaker_tab.set_config(cfg)
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # Step 4 – Translation phases
    # ─────────────────────────────────────────────────────────────────────────

    def _run_phase(self, phase: int):
        config = PHASE1_CONFIG if phase == 1 else PHASE2_CONFIG
        label = "Phase 1 (safe codes)" if phase == 1 else "Phase 2 (risky codes)"

        # Apply config profile
        try:
            from gui.config_integration import ConfigIntegration
            ci = ConfigIntegration()
            ci.update_rpgmaker_config(config)
            self._log(f"Applied {label} config profile.")
        except Exception as exc:
            self._log(f"❌ Could not apply phase config: {exc}")
            return

        # Launch translation worker
        try:
            from gui.translation_tab import TranslationWorker
        except Exception as exc:
            self._log(f"❌ Could not import TranslationWorker: {exc}")
            return

        project_root = Path(__file__).parent.parent
        module_info = ["RPG Maker MV/MZ", [".json"], None]

        # Build file order: core DB files first (they populate the glossary),
        # then map files.  Within each group, sort alphabetically.
        files_dir = project_root / "files"
        all_json = sorted(
            p.name for p in files_dir.glob("*.json") if p.name != ".gitkeep"
        ) if files_dir.exists() else []
        core_files = [f for f in all_json if not f.lower().startswith("map")]
        map_files  = [f for f in all_json if f.lower().startswith("map")]
        ordered_files = core_files + map_files
        if ordered_files:
            self._log(
                f"File order: {len(core_files)} core file(s) first, "
                f"then {len(map_files)} map file(s)."
            )

        self._log(f"Starting {label} translation…")
        worker = TranslationWorker(
            project_root, module_info, estimate_only=False,
            selected_files=ordered_files if ordered_files else None,
        )
        worker.log_signal.connect(self._log)
        worker.progress_signal.connect(
            lambda cur, tot, fn: self._log(f"  [{cur}/{tot}] {fn}")
        )
        worker.finished_signal.connect(
            lambda ok, msg: self._log(
                f"{'✅' if ok else '❌'} {label} finished: {msg}"
            )
        )
        self._worker = worker
        worker.start()

    # ─────────────────────────────────────────────────────────────────────────
    # Risky string scanner (preview mode)
    # ─────────────────────────────────────────────────────────────────────────

    def _scan_risky_strings(self):
        risky_codes = {122, 357, 111}
        collected: dict[int, list[str]] = {c: [] for c in risky_codes}
        files_dir = Path("files")

        try:
            for fp in sorted(files_dir.glob("*.json")):
                data = json.loads(fp.read_text(encoding="utf-8-sig"))
                self._collect_risky(data, risky_codes, collected)

            self._log("=" * 50)
            self._log("Risky Code String Scan (preview — nothing modified):")
            total = 0
            for code in sorted(risky_codes):
                strings = sorted(set(collected[code]))
                total += len(strings)
                self._log(f"\n  CODE {code} — {len(strings)} unique string(s):")
                for s in strings[:50]:
                    self._log(f"    {repr(s)}")
                if len(strings) > 50:
                    self._log(f"    … ({len(strings) - 50} more)")
            self._log(f"\n  Total unique strings: {total}")
            self._log("=" * 50)
        except Exception as exc:
            self._log(f"❌ Scan error: {exc}")

    def _collect_risky(self, obj, risky_codes: set, collected: dict):
        if isinstance(obj, list):
            for item in obj:
                self._collect_risky(item, risky_codes, collected)
        elif isinstance(obj, dict):
            code = obj.get("code")
            if code in risky_codes:
                params = obj.get("parameters") or []
                for p in params:
                    if isinstance(p, str) and p.strip():
                        collected[code].append(p)
            for v in obj.values():
                self._collect_risky(v, risky_codes, collected)

    # ─────────────────────────────────────────────────────────────────────────
    # Step 5 – Export to game
    # ─────────────────────────────────────────────────────────────────────────

    def _export_to_game(self):
        game_data = self._data_path
        if not game_data:
            # Prompt the user
            game_data = QFileDialog.getExistingDirectory(
                self, "Select Game Data Folder to Export Into"
            )
            if not game_data:
                return
            self._data_path = game_data

        reply = QMessageBox.question(
            self,
            "Export to Game",
            f"This will overwrite files in:\n{game_data}\n\n"
            "Make a backup first if needed. Continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        w = _ExportWorker(game_data)
        w.log.connect(self._log)
        w.done.connect(self._on_export_done)
        self._worker = w
        w.start()

    def _on_export_done(self, count: int, errors: list):
        if errors:
            self._log(f"⚠  {len(errors)} error(s) during export:")
            for e in errors[:10]:
                self._log(f"   {e}")
        self._log(f"✅ Exported {count} file(s) to game folder.")

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────────

    # ─────────────────────────────────────────────────────────────────────────────
    # Step 1 (Optional) – Pre-process handlers
    # ─────────────────────────────────────────────────────────────────────────────

    def _populate_preprocess_paths(self):
        """Auto-fill pre-process paths from the detected game root and data path."""
        game_root = self.folder_edit.text().strip()
        data_path = self._data_path or ""

        # Update dazedformat label
        try:
            self.pp_data_path_label.setText(data_path or "(no data folder detected)")
        except Exception:
            pass

        # Find plugins.js
        if game_root:
            for candidate in (
                Path(game_root) / "js" / "plugins.js",
                Path(game_root) / "www" / "js" / "plugins.js",
            ):
                if candidate.is_file():
                    self._plugins_js_path = str(candidate)
                    break
            else:
                self._plugins_js_path = str(Path(game_root) / "js" / "plugins.js")
        try:
            self.pp_plugins_edit.setText(self._plugins_js_path)
        except Exception:
            pass

        # Gameupdate path — default to the tool's own gameupdate/ folder
        tool_gameupdate = Path(__file__).parent.parent / "gameupdate"
        self._gameupdate_path = str(tool_gameupdate)
        try:
            self.pp_gameupdate_edit.setText(self._gameupdate_path)
        except Exception:
            pass
        try:
            self.pp_gameupdate_dst_label.setText(game_root or "(no game folder detected)")
        except Exception:
            pass

    def _browse_plugins_js(self):
        start = self.pp_plugins_edit.text() or self.folder_edit.text()
        path, _ = QFileDialog.getOpenFileName(
            self, "Select plugins.js", start, "JavaScript files (*.js);;All files (*)"
        )
        if path:
            self.pp_plugins_edit.setText(path)

    def _browse_gameupdate(self):
        start = self.pp_gameupdate_edit.text() or self.folder_edit.text()
        folder = QFileDialog.getExistingDirectory(self, "Select gameupdate folder", start)
        if folder:
            self.pp_gameupdate_edit.setText(folder)

    def _run_dazedformat(self):
        data_path = self._data_path
        if not data_path:
            self._log("⚠  No data folder detected. Complete Step 0 first.")
            return
        w = _SubprocessWorker(["dazedformat", "."], cwd=data_path, label="dazedformat")
        w.log.connect(self._log)
        w.done.connect(lambda ok, msg: self._log(("✅ " if ok else "❌ ") + msg))
        self._worker = w
        w.start()

    def _run_prettier(self):
        plugins_js = self.pp_plugins_edit.text().strip()
        if not plugins_js:
            self._log("⚠  No plugins.js path set.")
            return
        p = Path(plugins_js)
        if not p.is_file():
            self._log(f"⚠  plugins.js not found: {p}")
            return
        w = _JsFormatWorker(str(p))
        w.log.connect(self._log)
        w.done.connect(lambda ok, msg: self._log(("✅ " if ok else "❌ ") + msg))
        self._worker = w
        w.start()

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
        self._worker = w
        w.start()

    def _on_gameupdate_done(self, count: int, errors: list):
        self._log(f"✅ gameupdate: copied {count} file(s).")
        for e in errors:
            self._log(f"   ⚠  {e}")

    def _run_all_preprocess(self):
        """Launch all three pre-process tasks, skipping any whose prerequisites are missing."""
        import shutil as _shutil
        data_path      = self._data_path
        plugins_js     = self.pp_plugins_edit.text().strip()
        gameupdate_src = self.pp_gameupdate_edit.text().strip()
        skipped: list[str] = []

        # A — dazedformat
        if data_path and _shutil.which("dazedformat"):
            self._log("▶ [A] dazedformat …")
            self._run_dazedformat()
        else:
            reason = "data folder missing" if not data_path else "dazedformat not on PATH"
            skipped.append(f"A (dazedformat): {reason}")

        # B — jsbeautifier (pure Python, no Node required)
        if plugins_js and Path(plugins_js).is_file():
            self._log("▶ [B] formatting plugins.js …")
            self._run_prettier()
        else:
            reason = f"plugins.js not found ({plugins_js or 'not set'})"
            skipped.append(f"B (format plugins.js): {reason}")

        # C — gameupdate copy
        game_root_dst = self.folder_edit.text().strip()
        if gameupdate_src and Path(gameupdate_src).is_dir() and game_root_dst:
            self._log("▶ [C] gameupdate copy …")
            self._run_gameupdate()
        else:
            if not gameupdate_src or not Path(gameupdate_src).is_dir():
                reason = f"source not found ({gameupdate_src or 'not set'})"
            else:
                reason = "game root folder missing"
            skipped.append(f"C (gameupdate): {reason}")

        for msg in skipped:
            self._log(f"  ⏭  Skipped: {msg}")

    def _copy_to_clipboard(self, text: str, confirmation: str = "Copied."):
        try:
            QApplication.clipboard().setText(text)
            self._log(f"📋 {confirmation}")
        except Exception as exc:
            self._log(f"❌ Could not copy to clipboard: {exc}")

    def _log(self, message: str):
        self.log_area.append(message)
        sb = self.log_area.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _setting(self, key: str, default=None):
        if self.settings:
            return self.settings.value(f"workflow/{key}", default)
        return default

    def _save_setting(self, key: str, value):
        if self.settings:
            self.settings.setValue(f"workflow/{key}", value)
