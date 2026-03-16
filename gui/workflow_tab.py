"""
RPGMaker Workflow Tab - Automation hub for the full translation pipeline.

Provides a guided, step-by-step interface:

  Step 0  – Select game project folder and import data files into files/
  Step 1  – (Optional) Pre-process game files
  Step 2  – Auto-detect speaker format and apply to module settings
  Step 3  – Build glossary: parse speakers, then enrich with AI prompt
  Step 4  – Translation: Phase 0 (DB), Phase 1 (dialogue), Phase 1b (111 cache), Phase 2 (risky)
  Step 5  – Translate visible strings in js/plugins.js
  Step 6  – Export translated/ back to the game folder
"""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

import jsbeautifier

from PyQt5.QtCore import Qt, QSettings, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFrame,
    QGridLayout,
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

# Core database files — translated first (names/descriptions)
_DB_FILES = {
    "Actors.json", "Armors.json", "Classes.json", "Enemies.json",
    "Items.json",  "MapInfos.json", "Skills.json",  "States.json",
    "System.json", "Weapons.json",
}

# Event files — translated in phases 1 / 1b / 2
_EVENT_FILES_EXACT = {"CommonEvents.json", "Troops.json"}
# Any Map????.json is also an event file (matched by prefix below)

PHASE0_CONFIG = {
    # All event codes OFF — DB files use top-level name/description fields
    "CODE101": False, "CODE401": False, "CODE405": False,
    "CODE102": False, "CODE408": False,
    "CODE111": False, "CODE122": False, "CODE357": False,
    "CODE355655": False, "CODE657": False, "CODE356": False,
    "CODE320": False, "CODE324": False, "CODE325": False,
    "CODE108": False,
}

PHASE1_CONFIG = {
    # Safe dialogue / choices
    "CODE101": True,
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

PHASE1B_CONFIG = {
    # Dialogue OFF (handled by Phase 1)
    "CODE101": False,
    "CODE401": False,
    "CODE405": False,
    "CODE102": False,
    "CODE408": False,
    # Only 111 ON — build the var-translation cache from string comparisons
    "CODE111": True,
    "CODE122": False,
    "CODE357": False,
    "CODE355655": False,
    "CODE657": False,
    "CODE356": False,
    "CODE320": False,
    "CODE324": False,
    "CODE325": False,
    "CODE108": False,
}

PHASE2_CONFIG = {
    # Dialogue OFF (already handled by Phase 1)
    "CODE101": False,
    "CODE401": False,
    "CODE405": False,
    "CODE102": False,
    "CODE408": False,
    # Risky codes ON (111 OFF — cache already built by Phase 1b)
    "CODE122": True,
    "CODE357": True,
    "CODE111": False,
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

            # Clear existing files/ contents before importing so stale files
            # from a previous game don't linger. translated/ is intentionally
            # left untouched.
            dest = Path(self.dest_dir)
            if dest.exists():
                removed = 0
                for fp in dest.iterdir():
                    if fp.is_file() and fp.name != ".gitkeep":
                        try:
                            fp.unlink()
                            removed += 1
                        except Exception as e:
                            self.log.emit(f"  ⚠ Could not remove {fp.name}: {e}")
                if removed:
                    self.log.emit(f"Cleared {removed} existing file(s) from {dest.name}/")

            self.log.emit(f"Importing {len(self.file_items)} file(s) into files/ …")
            count, errors = import_to_files(self.file_items, self.dest_dir)
            self.done.emit(count, errors)
        except Exception as exc:
            self.done.emit(0, [str(exc)])


class _ExportWorker(QThread):
    done = pyqtSignal(int, list)
    log  = pyqtSignal(str)

    def __init__(self, game_data_path: str, filter_names: list[str] | None = None):
        super().__init__()
        self.game_data_path = game_data_path
        self.filter_names = filter_names  # if set, only export these filenames

    def run(self):
        try:
            from util.project_scanner import export_to_game
            if self.filter_names:
                self.log.emit(
                    f"Exporting {len(self.filter_names)} active file(s) → {self.game_data_path} …"
                )
            else:
                self.log.emit(f"Exporting translated/ → {self.game_data_path} …")
            count, errors = export_to_game(
                "translated", self.game_data_path, filenames=self.filter_names
            )
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


class _JsonFormatWorker(QThread):
    """Format all JSON files in a directory using the bundled dazedformat utility."""
    done = pyqtSignal(bool, str)
    log  = pyqtSignal(str)

    def __init__(self, data_path: str):
        super().__init__()
        self.data_path = data_path

    def run(self):
        try:
            from util.dazedformat import format_json_files
            self.log.emit(f"Formatting JSON files in {self.data_path} …")
            count, errors = format_json_files(self.data_path, log=self.log.emit)
            for e in errors:
                self.log.emit(f"  ⚠  {e}")
            if errors:
                self.done.emit(False, f"dazedformat: {count} formatted, {len(errors)} error(s).")
            else:
                self.done.emit(True, f"dazedformat: {count} file(s) formatted successfully.")
        except Exception as exc:
            self.done.emit(False, f"dazedformat error: {exc}")


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
        "font-size: 13px; font-weight: bold; color: #007acc;"
        "padding: 8px 0px 5px 0px; background-color: transparent;"
    )
    return lbl


def _make_hr() -> QFrame:
    hr = QFrame()
    hr.setFrameShape(QFrame.HLine)
    hr.setFrameShadow(QFrame.Sunken)
    hr.setStyleSheet("QFrame { color: #555555; margin: 5px 0px; }")
    return hr


def _make_btn(text: str, color: str = "#007acc") -> QPushButton:
    """Button styled to match the translation tab.

    Dark utility colours (max channel < 115) use the flat sidebar style
    (dark background, border, blue left-accent on hover).
    True action colours use a filled coloured button.
    """
    btn = QPushButton(text)
    try:
        c = color.lstrip("#")
        if len(c) == 3:
            c = c[0] * 2 + c[1] * 2 + c[2] * 2
        r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
        is_flat = max(r, g, b) < 115
    except Exception:
        r = g = b = 0
        is_flat = False
    _PAD = "padding:6px 14px;"
    if is_flat:
        btn.setStyleSheet(
            f"QPushButton{{background-color:#2d2d30;color:#cccccc;"
            f"border:1px solid #555555;{_PAD}"
            f"border-radius:4px;font-size:12px;font-weight:bold;"
            f"font-family:'Segoe UI Emoji','Segoe UI','Apple Color Emoji',sans-serif;}}"
            f"QPushButton:hover{{background-color:#3e3e42;}}"
            f"QPushButton:pressed{{background-color:#007acc;color:white;}}"
            f"QPushButton:disabled{{background-color:#404040;color:#666666;border-color:#444444;}}"
        )
    else:
        try:
            rh = min(255, r + 25)
            gh = min(255, g + 25)
            bh = min(255, b + 25)
            hover_color = f"#{rh:02x}{gh:02x}{bh:02x}"
            rp = max(0, r - 20)
            gp = max(0, g - 20)
            bp = max(0, b - 20)
            press_color = f"#{rp:02x}{gp:02x}{bp:02x}"
        except Exception:
            hover_color = press_color = color
        btn.setStyleSheet(
            f"QPushButton{{background-color:{color};color:white;border:none;"
            f"{_PAD}border-radius:4px;font-size:12px;font-weight:bold;"
            f"font-family:'Segoe UI Emoji','Segoe UI','Apple Color Emoji',sans-serif;}}"
            f"QPushButton:hover{{background-color:{hover_color};}}"
            f"QPushButton:pressed{{background-color:{press_color};}}"
            f"QPushButton:disabled{{background-color:#404040;color:#666666;}}"
        )
    return btn


def _make_toggle_btn(text: str) -> QPushButton:
    """Checkable Select All / Deselect All button, styled to match the rest of the workflow UI."""
    btn = QPushButton(text)
    btn.setCheckable(True)
    btn.setStyleSheet(
        "QPushButton{background-color:#2d2d30;color:#aaaaaa;"
        "border:1px solid #555555;padding:4px 12px;"
        "border-radius:4px;font-size:12px;"
        "font-family:'Segoe UI Emoji','Segoe UI','Apple Color Emoji',sans-serif;}"
        "QPushButton:hover{background-color:#3e3e42;color:#cccccc;}"
        "QPushButton:checked{background-color:#1a3a5a;color:#7ab8d4;border-color:#2a6a9a;}"
        "QPushButton:checked:hover{background-color:#1e4268;}"
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
        splitter.setHandleWidth(2)
        splitter.setStyleSheet("QSplitter::handle{background:#555555;}")

        # ---- Left: scrollable step panels ----
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea{border:none;}")
        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(18, 14, 18, 14)
        vbox.setSpacing(4)

        self._build_step0(vbox)
        vbox.addWidget(_make_hr())
        self._build_step1_preprocess(vbox)
        vbox.addWidget(_make_hr())
        self._build_step2_speaker(vbox)
        vbox.addWidget(_make_hr())
        self._build_step3_glossary(vbox)
        vbox.addWidget(_make_hr())
        self._build_step4_translation(vbox)
        vbox.addWidget(_make_hr())
        self._build_step5_plugins_js(vbox)
        vbox.addWidget(_make_hr())
        self._build_step6_export(vbox)
        vbox.addStretch()

        scroll.setWidget(container)
        splitter.addWidget(scroll)

        # ---- Right: log area ----
        log_panel = QWidget()
        lp_layout = QVBoxLayout(log_panel)
        lp_layout.setContentsMargins(0, 0, 0, 0)
        lp_layout.setSpacing(0)

        log_header = QLabel("  Log")
        log_header.setStyleSheet(
            "background-color:#2d2d30;color:#cccccc;font-size:11px;font-weight:bold;"
            "padding:6px 8px;border-bottom:1px solid #555555;"
        )
        lp_layout.addWidget(log_header)

        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setFont(QFont("Consolas", 9))
        self.log_area.setStyleSheet(
            "QTextEdit{background-color:#252526;color:#d4d4d4;"
            "border:none;padding:8px;}"
        )
        lp_layout.addWidget(self.log_area)

        clear_btn = _make_btn("Clear Log", "#444")
        clear_btn.clicked.connect(self.log_area.clear)
        lp_layout.addWidget(clear_btn)

        splitter.addWidget(log_panel)
        splitter.setSizes([900, 200])

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
        saved = self._setting("last_game_folder", "")
        if saved:
            self.folder_edit.setText(saved)
        row0.addWidget(self.folder_edit, 1)
        self.folder_edit.returnPressed.connect(self._detect_folder)

        browse_btn = _make_btn(" Browse…")
        browse_btn.setIcon(browse_btn.style().standardIcon(QStyle.SP_DirOpenIcon))
        browse_btn.clicked.connect(self._browse_folder)
        row0.addWidget(browse_btn)

        layout.addLayout(row0)

        # Detected info
        self.detected_label = QLabel("No folder detected yet.")
        self.detected_label.setStyleSheet("color:#888;font-size:13px;padding:2px 0;")
        layout.addWidget(self.detected_label)

        # File list
        self.file_list = QListWidget()
        self.file_list.setMaximumHeight(180)
        self.file_list.setStyleSheet(
            "QListWidget{outline:none;border:1px solid #555555;}"
            "QListWidget::item{border:none;outline:none;}"
            "QListWidget::item:hover{background-color:#3e3e42;}"
        )
        layout.addWidget(self.file_list)

        # Action row
        row1 = QHBoxLayout()
        self.sel_all_btn = _make_btn("Select All", "#555")
        self.sel_all_btn.clicked.connect(self._select_all_files)
        row1.addWidget(self.sel_all_btn)

        sel_core = _make_btn("Core Only", "#555")
        sel_core.setToolTip("Select only core database files; deselect map files")
        sel_core.clicked.connect(self._select_core_only)
        row1.addWidget(sel_core)

        row1.addStretch()
        layout.addLayout(row1)

    # ── Step 3: Vocab / Glossary ────────────────────────────────────────────

    # ── Copilot prompt templates ────────────────────────────────────────────

    _SPEAKER_PROMPT = (
        "You are helping me configure a Japanese RPGMaker MV/MZ translation tool.\n"
        "\n"
        "Look at a sample of the game's event files (Map*.json, CommonEvents.json, "
        "Troops.json) and determine which speaker name format the game uses.\n"
        "\n"
        "## How dialogue commands work\n"
        "\n"
        "Code 101 opens the text window. Code 401 is a dialogue line. "
        "Multiple 401s in a row form one message box.\n"
        "\n"
        "## The formats to identify\n"
        "\n"
        "### Format A — 101 name in param[4]  (NO FLAG NEEDED, handled automatically)\n"
        "The 101 code has a non-empty string at parameters[4].\n"
        "Example:\n"
        "  { \"code\": 101, \"parameters\": [\"\", 0, 2, 2, \"るな\"] }\n"
        "  { \"code\": 401, \"parameters\": [\"「おはよう！\"] }\n"
        "→ No flag needed. Do not set anything.\n"
        "\n"
        "### Format B — INLINE401SPEAKERS\n"
        "The speaker name is embedded at the start of the 401 text directly before 「.\n"
        "Example:\n"
        "  { \"code\": 401, \"parameters\": [\"エレナ「今日は晴れですね。\"] }\n"
        "→ Set INLINE401SPEAKERS = True\n"
        "\n"
        "### Format C — FIRSTLINESPEAKERS\n"
        "The first 401 in a group is a short name (<40 chars), and the next 401 "
        "starts with 「 \" ( （ * [.\n"
        "Example:\n"
        "  { \"code\": 401, \"parameters\": [\"アリス\"] }\n"
        "  { \"code\": 401, \"parameters\": [\"「こんにちは。\"] }\n"
        "→ Set FIRSTLINESPEAKERS = True\n"
        "\n"
        "### Format D — FACENAME101\n"
        "The 101 code has a face image filename in parameters[0] and parameters[4] is empty "
        "or missing. The speaker name must be inferred from the face filename.\n"
        "Example:\n"
        "  { \"code\": 101, \"parameters\": [\"face_alice\", 0, 0, 2, \"\"] }\n"
        "→ Set FACENAME101 = True\n"
        "\n"
        "### Format E — Color-wrapped speaker  (NO FLAG NEEDED, handled automatically)\n"
        "A 401 line consists solely of a color-code-wrapped name: \\\\c[N]Name\\\\c[0].\n"
        "Example:\n"
        "  { \"code\": 401, \"parameters\": [\"\\\\c[2]アリス\\\\c[0]\"] }\n"
        "  { \"code\": 401, \"parameters\": [\"「こんにちは。\"] }\n"
        "→ No flag needed. Do not set anything.\n"
        "\n"
        "### Format F — Full-width colon  (NO FLAG NEEDED, handled automatically)\n"
        "A 401 line ends with a full-width colon ： marking it as a speaker line.\n"
        "Example:\n"
        "  { \"code\": 401, \"parameters\": [\"アリス：\"] }\n"
        "  { \"code\": 401, \"parameters\": [\"「こんにちは。\"] }\n"
        "→ No flag needed. Do not set anything.\n"
        "\n"
        "### Always-on (NO FLAG NEEDED, handled automatically)\n"
        "  - \\\\n<Name> or \\\\k<Name> codes embedded in 401 text\n"
        "  - 【Name】 alone on a line or 【Name】dialogue on the same line\n"
        "  - \\\\c[N]Name\\\\c[0] color-wrapped name on its own 401 line\n"
        "  - Name： line ending with a full-width colon\n"
        "\n"
        "---\n"
        "\n"
        "Please examine a sample of the event commands in the game files attached and tell me:\n"
        "  1. Which format(s) are present\n"
        "  2. Exactly which flags to set True (only list flags that should be True):\n"
        "     INLINE401SPEAKERS, FIRSTLINESPEAKERS, FACENAME101\n"
        "  3. A short concrete example from the files confirming the pattern\n"
    )

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
        "⚠️ IMPORTANT: In all descriptions, ALWAYS refer to other characters by their "
        "ENGLISH name, never their Japanese name. "
        "For example, write \"her sister Ruin was kidnapped\" not "
        "\"her sister ルイン was kidnapped\". "
        "The description text must be entirely in English with no Japanese characters "
        "except inside the leading Japanese (English) name tag.\n"
        "\n"
        "Format — the header line, then one entry per line:\n"
        "# Game Characters\n"
        "\u30b7\u30ed (Shiro) - Female; protagonist; player-controlled (Actors.json ID 1); "
        "speaks in a flustered, cute register with feminine speech markers; "
        "her partner is Kurone\n"
        "\u30af\u30ed\u30cd (Kurone) - Female; antagonist; cold and terse; speaks in short cutting sentences; "
        "pursues Shiro throughout the story\n"
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

    _WRAP_PROMPT = (
        "You are helping me configure text-wrap widths for a Japanese RPGMaker MV/MZ translation tool.\n"
        "\n"
        "The tool wraps translated English text using a character-count limit (not pixels).\n"
        "I need three values:\n"
        "\n"
        "  width      — main dialogue / message box (Show Text)\n"
        "  listWidth  — item / skill / help description windows\n"
        "  noteWidth  — database note fields (item, weapon, armour, skill descriptions)\n"
        "\n"
        "To calculate them:\n"
        "  1. Read screenWidth and fontSize from System.json.\n"
        "     Check js/plugins.js for any MessageCore or Window plugin that overrides these.\n"
        "  2. For each window type, estimate its pixel width, subtract ~48px padding, then:\n"
        "       chars = floor(content_px / (font_size × 0.58))\n"
        "     listWidth window is usually full or half screen width.\n"
        "     noteWidth window is usually the narrowest description pane (~40–50% screen width).\n"
        "  3. If the font size is above 26px and reducing it would meaningfully increase\n"
        "     characters per line, note where to change it (System.json or plugin parameter).\n"
        "\n"
        "Do not show calculations. Just give me the final answer in this exact format:\n"
        "\n"
        "```\n"
        "width=<N>\n"
        "listWidth=<N>\n"
        "noteWidth=<N>\n"
        "fontSize=<N>   # or: no change needed\n"
        "```\n"
        "\n"
        "Followed by one sentence of assumptions if anything was estimated.\n"
    )

    _PLUGINS_JS_TRANSLATE_PROMPT = (
        "You are helping me translate a Japanese RPGMaker MV/MZ game.\n"
        "I need you to translate visible Japanese strings inside js/plugins.js\n"
        "without breaking any game logic or plugin functionality.\n"
        "\n"
        "A vocab.txt glossary file has been attached. Use it as your primary reference\n"
        "for character names, worldbuilding terms, and their approved English translations.\n"
        "Any Japanese name or term that appears in the glossary must be translated\n"
        "exactly as specified there — do not invent alternative spellings.\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "## WHAT TO TRANSLATE\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "\n"
        "Only translate string values that are directly shown to the player at runtime.\n"
        "These are typically plugin parameters with Japanese text such as:\n"
        "  - Menu/button labels displayed in-game UI (e.g. \"決定\", \"キャンセル\")\n"
        "  - Scene/window title text (e.g. \"アイテム\", \"スキル\", \"装備\")\n"
        "  - In-game popup, tooltip, or notification messages\n"
        "  - Default NPC names or pronouns used in UI display\n"
        "  - Help or description text shown in help windows\n"
        "  - Battle log messages or status effect messages\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "## WHAT MUST NOT BE TRANSLATED\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "\n"
        "CRITICAL — translating the following will break the game:\n"
        "\n"
        "  1. Plugin parameter KEYS (object property names).\n"
        "     Example: { \"CommandName\": \"セーブ\" }\n"
        "     → translate \"セーブ\" but NOT \"CommandName\"\n"
        "\n"
        "  2. Strings used as internal identifiers or lookup keys:\n"
        "     - Switch/variable names that match System.json entries\n"
        "     - Actor, skill, item, weapon, armour names if they are used\n"
        "       as keys inside other plugin parameters (e.g. skill filtering lists)\n"
        "     - Strings passed as plugin command arguments that the engine looks up\n"
        "\n"
        "  3. File paths, filenames, URLs, colour codes, font names, icon indices.\n"
        "     Example: \"img/faces/Actor1\" or \"#ffffff\" — do NOT translate.\n"
        "\n"
        "  4. Plugin names and script identifiers:\n"
        "     - The \"name\" property at the top of each plugin block\n"
        "       (e.g. { \"name\": \"YEP_CoreEngine\" }) — never translate\n"
        "     - Function identifiers, class names, JS event names\n"
        "\n"
        "  5. Any string that also appears in the game data files (Actors.json,\n"
        "     Skills.json, Items.json, etc.) AND is used as a lookup key in the\n"
        "     plugin — changing it here would desync it from the data file.\n"
        "\n"
        "  6. Boolean strings, numeric strings, regex patterns.\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "## HOW TO IDENTIFY SAFE STRINGS\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "\n"
        "Before translating a string, ask yourself:\n"
        "  ✔ Is this value ever displayed directly to the player as text?\n"
        "  ✔ Is it purely a UI label, not a key used anywhere else?\n"
        "  ✔ Does nothing in the codebase compare this exact string to another value?\n"
        "\n"
        "If all three are YES, it is safe to translate.\n"
        "When in doubt, SKIP IT — untranslated Japanese is better than a broken game.\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "## OUTPUT FORMAT\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "\n"
        "Provide the translated file as a complete replacement of js/plugins.js.\n"
        "Only change the string values identified above.\n"
        "Preserve all original formatting, indentation, comments, and structure.\n"
        "\n"
        "After the file, output a translation summary:\n"
        "\n"
        "### Translations Made\n"
        "List each change in this format:\n"
        "  Plugin: <plugin name>\n"
        "  Parameter: <parameter key>\n"
        "  Before: <original Japanese>\n"
        "  After:  <English translation>\n"
        "\n"
        "### Skipped (Ambiguous or Internal)\n"
        "List any Japanese strings you detected but chose NOT to translate, with a one-line reason.\n"
    )

    _PLUGIN_PROMPT = (
        "You are helping me safely translate a Japanese RPGMaker MV/MZ game.\n"
        "Before I run Phase 2, I need you to audit several optional code types and tell me\n"
        "(a) which ones contain player-visible Japanese text that needs translation, and\n"
        "(b) for code 122, exactly which variable ID ranges carry display text vs internal keys.\n"
        "\n"
        "Attach the game's event files (CommonEvents.json, Troops.json, Map*.json)\n"
        "and js/plugins.js before running this prompt.\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "## AUDIT 1 — Code 122 (Control Variables) — which variable IDs carry display text\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "\n"
        "A code 122 entry looks like:\n"
        "  { \"code\": 122, \"parameters\": [startVarId, endVarId, 0, 4, \"\\\"some string\\\"\"] }\n"
        "parameters[0] is the variable ID being set; parameters[4] is the string value\n"
        "(only present when parameters[3] == 4, direct string assignment).\n"
        "\n"
        "Collect every code 122 where parameters[3] == 4. For each variable ID found:\n"
        "  1. Is the string also tested in a code 111 $gameVariables comparison?\n"
        "     → DO NOT TRANSLATE (would break game logic)\n"
        "  2. Is the string used as an internal ID / plugin key / script argument?\n"
        "     → DO NOT TRANSLATE\n"
        "  3. Is the string purely player-visible display text?\n"
        "     → SAFE TO TRANSLATE\n"
        "\n"
        "Summarise translatable variable IDs as compact numeric ranges,\n"
        "e.g. 'Translate IDs: 5, 10-18, 42'. Separately list any DO NOT TRANSLATE IDs\n"
        "with the reason. The ranges will be entered as min/max in the translation tool.\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "## AUDIT 2 — Plugin codes with visible text (357 / 356 / 355-655 / 657 / 320 / 324 / 325 / 108)\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "\n"
        "For EACH of the following code types, scan all events and report whether any\n"
        "instance contains Japanese text that is visible to the player at runtime.\n"
        "\n"
        "--- Code 357 (MZ Plugin Commands) ---\n"
        "parameters[0] = plugin header; parameters[3] = data dict.\n"
        "Look up each unique header in js/plugins.js.\n"
        "Does any key in parameters[3] hold Japanese text shown on screen?\n"
        "The module already handles: AdvExtentionllk, VisuMZ_4_ProximityMessages, LL_GalgeChoiceWindow\n"
        "For other headers with visible text, check the commented-out headerMappings list:\n"
        "  \"LL_InfoPopupWIndow\": ([\"messageText\"], None),\n"
        "  \"QuestSystem\": ([\"DetailNote\"], None),\n"
        "  \"BalloonInBattle\": ([\"text\"], None),\n"
        "  \"MNKR_CommonPopupCoreMZ\": ([\"text\"], None),\n"
        "  \"DestinationWindow\": ([\"destination\"], None),\n"
        "  \"_TMLogWindowMZ\": ([\"text\"], None),\n"
        "  \"TorigoyaMZ_NotifyMessage\": ([\"message\"], None),\n"
        "  \"SoR_GabWindow\": ([\"arg1\"], None),\n"
        "  \"DarkPlasma_CharacterText\": ([\"text\"], None),\n"
        "  \"DTextPicture\": ([\"text\"], None),\n"
        "  \"TextPicture\": ([\"text\"], None),\n"
        "  \"TRP_SkitMZ\": ([\"name\"], None),\n"
        "  \"LogWindow\": ([\"text\"], None),\n"
        "  \"BattleLogOutput\": ([\"message\"], None),\n"
        "  \"TorigoyaMZ_NotifyMessage_CommandMessage\": ([\"message\"], None),\n"
        "  \"NUUN_SaveScreen\": ([\"AnyName\"], None),\n"
        "  \"build/ARPG_Core\": ([\"Text\", \"SkillByName\"], None),\n"
        "Output: EXACT uncomment line, or describe parameters[3] if header is new.\n"
        "\n"
        "--- Code 356 (MV Plugin Commands) ---\n"
        "parameters[0] is a space-delimited string, e.g. 'D_TEXT テキスト 24'.\n"
        "The module already handles: D_TEXT, ShowInfo, PushGab, addLog, DW_*, CommonPopup, AddCustomChoice.\n"
        "Does any 356 line have Japanese that is shown on screen?\n"
        "If yes: ENABLE CODE356 and list the command keywords found.\n"
        "If no:  SKIP CODE356.\n"
        "\n"
        "--- Code 355/655 (Inline Scripts) ---\n"
        "Code 355 starts a script block; code 655 continues it.\n"
        "parameters[0] is the raw JS/script text.\n"
        "For each block with Japanese in a string passed to a message/popup/log function:\n"
        "  • The leading keyword/pattern that identifies the block\n"
        "  • A regex capturing only the display substring, e.g. テキスト-(.+)\n"
        "  • Whether it is single-line (355 only) or multi-line (355 + 655)\n"
        "  • The exact entry to add to the patterns dict:\n"
        "      \"<keyword>\": (r\"<regex>\", <True|False>),\n"
        "\n"
        "--- Code 657 (Picture Text) ---\n"
        "parameters[0] is a plain string drawn onto a picture.\n"
        "Does any 657 entry contain Japanese text visible on screen (not a filename)?\n"
        "If yes: ENABLE CODE657. If no: SKIP CODE657.\n"
        "\n"
        "--- Codes 320 / 324 / 325 (Actor Name / Nickname / Profile) ---\n"
        "parameters[1] is the new name/nickname/profile string.\n"
        "Do any of these codes set Japanese strings visible to the player\n"
        "(not just internal IDs or filenames)?\n"
        "If yes: ENABLE the respective code. If no: SKIP.\n"
        "\n"
        "--- Code 108 (Comment / Notetag) ---\n"
        "parameters[0] is a comment string used as a plugin notetag.\n"
        "The module only translates 108 lines that match specific patterns:\n"
        "  info:, ActiveMessage:, event_text, Menu Name, text_indicator\n"
        "Do any 108 entries matching those patterns have Japanese visible to the player?\n"
        "If yes: ENABLE CODE108 and list the patterns found. If no: SKIP CODE108.\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "## Required output format\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "\n"
        "Reply with these exact sections:\n"
        "\n"
        "### Code 122 — Variable Translation Ranges\n"
        "  Translate IDs  : <compact ranges, e.g. 5, 10-18, 42>\n"
        "  Do NOT translate: <ID — reason>\n"
        "If none: 'No display-text string assignments found.'\n"
        "\n"
        "### Code 357 — Plugin Handlers to Enable\n"
        "  • Already handled  : <header> — no action needed\n"
        "  • Enable in module : uncomment → \"<header>\": ([\"<key>\"], None),\n"
        "  • New entry needed : <header> — parameters[3] structure: <description>\n"
        "  • No visible text  : <header> — internal only, skip\n"
        "If none: 'No code 357 visible text found.'\n"
        "\n"
        "### Code 356 — Enable or Skip\n"
        "  ENABLE / SKIP — keywords found: <list>\n"
        "\n"
        "### Code 355/655 — Script Patterns to Add\n"
        "  • Pattern key : <keyword>\n"
        "  • Regex       : <capture regex>\n"
        "  • Multiline   : <true/false>\n"
        "  • Module line : \"<keyword>\": (r\"<regex>\", <True|False>),\n"
        "If none: 'No translatable 355/655 scripts found.'\n"
        "\n"
        "### Code 657 — Enable or Skip\n"
        "  ENABLE / SKIP — <brief reason>\n"
        "\n"
        "### Codes 320 / 324 / 325 — Enable or Skip\n"
        "  320: ENABLE / SKIP   324: ENABLE / SKIP   325: ENABLE / SKIP\n"
        "\n"
        "### Code 108 — Enable or Skip\n"
        "  ENABLE / SKIP — patterns found: <list>\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "## GUI Action Summary\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "\n"
        "After all audit sections above, output this final block so I can configure the GUI:\n"
        "\n"
        "ENABLE CODES     : <comma-separated CODE* keys to check, e.g. CODE357, CODE356>\n"
        "SKIP CODES       : <codes that have no visible text>\n"
        "357 PLUGINS      : <comma-separated HEADER_MAPPINGS_357 keys to enable>\n"
        "355/655 PATTERNS : <comma-separated PATTERNS_355655 keys to enable>\n"
        "122 VAR RANGE    : min=<N>, max=<M>\n"
        "\n"
        "If a field has nothing to fill in, write NONE.\n"
    )

    # ── Step 1 (Optional): Pre-process ────────────────────────────────

    def _build_step1_preprocess(self, layout: QVBoxLayout):
        header_row = QHBoxLayout()
        header_row.addWidget(_make_section_label("Step 1 (Optional) — Pre-process"))
        opt_badge = QLabel("personal / optional")
        opt_badge.setStyleSheet(
            "color:#888;font-size:12px;border:1px solid #555;"
            "padding:1px 6px;border-radius:8px;margin-left:6px;"
        )
        header_row.addWidget(opt_badge)
        header_row.addStretch()
        # Collapse/expand toggle
        toggle_btn = QPushButton("▼")
        toggle_btn.setCheckable(True)
        toggle_btn.setChecked(True)
        toggle_btn.setFixedSize(22, 22)
        toggle_btn.setStyleSheet(
            "QPushButton{background:transparent;color:#888;border:none;font-size:11px;}"
            "QPushButton:hover{color:#ccc;}"
        )
        header_row.addWidget(toggle_btn)
        layout.addLayout(header_row)

        # Collapsible container — wraps hint + tasks_box + run-all row
        collapse_widget = QWidget()
        collapse_layout = QVBoxLayout(collapse_widget)
        collapse_layout.setContentsMargins(0, 0, 0, 0)
        collapse_layout.setSpacing(4)

        hint = QLabel(
            "Three optional preparation tasks to run against the game folder before "
            "importing files. Paths are auto-filled when a project folder is detected."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#999;font-size:13px;padding-bottom:6px;")
        collapse_layout.addWidget(hint)

        tasks_box = QGroupBox()
        tasks_box.setStyleSheet("QGroupBox{border:none;margin:0;padding:0;}")
        tb = QVBoxLayout(tasks_box)
        tb.setSpacing(10)
        collapse_layout.addWidget(tasks_box)

        # ---- Task A: dazedformat -----------------------------------------
        ta = QGroupBox("A — Format JSON files (dazedformat)")
        ta.setStyleSheet(self._task_box_style())
        ta_inner = QVBoxLayout(ta)
        ta_inner.setSpacing(4)
        ta_desc = QLabel(
            "Normalises all JSON files in the game's data folder by round-tripping them "
            "through <code>json.load / json.dump</code>. "
            "Bundled — no external install required."
        )
        ta_desc.setTextFormat(Qt.RichText)
        ta_desc.setWordWrap(True)
        ta_desc.setStyleSheet("color:#aaa;font-size:13px;")
        ta_inner.addWidget(ta_desc)
        ta_path_row = QHBoxLayout()
        ta_path_row.addWidget(QLabel("Data folder:"))
        self.pp_data_path_label = QLabel("(detect a project folder first)")
        self.pp_data_path_label.setStyleSheet("color:#888;font-size:13px;")
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
        tb_desc.setStyleSheet("color:#aaa;font-size:13px;")
        tb_inner.addWidget(tb_desc)
        tb_path_row = QHBoxLayout()
        tb_path_lbl = QLabel("plugins.js:")
        tb_path_row.addWidget(tb_path_lbl)
        self.pp_plugins_edit = QLineEdit()
        self.pp_plugins_edit.setPlaceholderText("Path to plugins.js…")
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
        tc_desc.setStyleSheet("color:#aaa;font-size:13px;")
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
        self.pp_gameupdate_dst_label.setStyleSheet("color:#888;font-size:13px;")
        tc_dst_row.addWidget(self.pp_gameupdate_dst_label, 1)
        tc_inner.addLayout(tc_dst_row)

        tc_btn_row = QHBoxLayout()
        run_gu = _make_btn("▶  Copy gameupdate/", "#555")
        run_gu.clicked.connect(self._run_gameupdate)
        tc_btn_row.addWidget(run_gu)
        tc_btn_row.addStretch()
        tc_inner.addLayout(tc_btn_row)
        tb.addWidget(tc)

        # ---- Run All button row --------------------------------
        bottom_row = QWidget()
        bottom_row_layout = QHBoxLayout(bottom_row)
        bottom_row_layout.setContentsMargins(0, 0, 0, 0)
        bottom_row_layout.addStretch()
        run_all_btn = _make_btn("▶▶  Run All 3 Tasks", "#3a4a6a")
        run_all_btn.setToolTip("Run dazedformat, prettier, and gameupdate copy in sequence")
        run_all_btn.clicked.connect(self._run_all_preprocess)
        bottom_row_layout.addWidget(run_all_btn)
        collapse_layout.addWidget(bottom_row)

        layout.addWidget(collapse_widget)

        def _toggle_preprocess(expanded: bool):
            toggle_btn.setText("▼" if expanded else "▶")
            collapse_widget.setVisible(expanded)
        toggle_btn.toggled.connect(_toggle_preprocess)

    @staticmethod
    def _task_box_style() -> str:
        return (
            "QGroupBox{border:none;margin-top:14px;padding-top:4px;}"
            "QGroupBox::title{subcontrol-origin:margin;subcontrol-position:top left;"
            "padding:0;color:#007acc;font-weight:bold;font-size:13px;"
            "font-family:'Segoe UI Emoji','Segoe UI','Apple Color Emoji',sans-serif;}"
        )

    @staticmethod
    def _checkbox_box_style() -> str:
        """Bordered style for sections that contain scrollable checkbox lists."""
        return (
            "QGroupBox{border:1px solid #3a3a3a;border-radius:4px;margin-top:10px;padding-top:4px;}"
            "QGroupBox::title{subcontrol-origin:margin;subcontrol-position:top left;"
            "left:8px;padding:0 4px;top:-1px;"
            "background-color:#1e1e1e;color:#888888;font-size:12px;"
            "font-family:'Segoe UI Emoji','Segoe UI','Apple Color Emoji',sans-serif;}"
        )

    def _build_step3_glossary(self, layout: QVBoxLayout):
        layout.addWidget(_make_section_label("Step 3 — Glossary (vocab.txt)"))
        hint = QLabel(
            "Edit your glossary below. Character names, genders, and worldbuilding terms "
            "here are injected into every AI prompt for consistent terminology."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#999;font-size:13px;padding-bottom:4px;")
        layout.addWidget(hint)

        # ---- Parse Speakers -------------------------------------------------
        spk_box = QGroupBox("3a — Parse Speakers (Auto-detect Names)")
        spk_box.setStyleSheet(self._task_box_style())
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
        spk_hint.setStyleSheet("color:#999;font-size:13px;")
        spk_inner.addWidget(spk_hint)

        spk_btn_row = QHBoxLayout()
        self._parse_speakers_btn = _make_btn("🔍  Parse Speakers", "#007acc")
        self._parse_speakers_btn.setMinimumWidth(180)
        self._parse_speakers_btn.setToolTip(
            "Scan all game files for speaker names and write them to vocab.txt"
        )
        self._parse_speakers_btn.clicked.connect(self._run_parse_speakers)
        spk_btn_row.addWidget(self._parse_speakers_btn)
        spk_btn_row.addStretch()
        spk_inner.addLayout(spk_btn_row)
        self._parse_speakers_status = QLabel("")
        self._parse_speakers_status.setStyleSheet("color:#aaa;font-size:13px;")
        spk_inner.addWidget(self._parse_speakers_status)

        layout.addWidget(spk_box)

        # ---- Copilot / Cursor prompt helpers --------------------------------
        prompt_box = QGroupBox("3b — AI Prompt Helpers (Copilot / Cursor)")
        prompt_box.setStyleSheet(self._task_box_style())
        pb_inner = QVBoxLayout(prompt_box)
        pb_inner.setSpacing(6)

        prompt_hint = QLabel(
            "After parsing speakers above, copy the prompt below and paste it into "
            "GitHub Copilot Chat or Cursor with your game files open. "
            "The AI will enrich the speaker list with gender, role, and speech register "
            "and add worldbuilding terms. Paste the AI's output back into vocab.txt."
        )
        prompt_hint.setWordWrap(True)
        prompt_hint.setStyleSheet("color:#999;font-size:13px;")
        pb_inner.addWidget(prompt_hint)

        # Combined glossary prompt
        glossary_desc = QLabel(
            "👥🌍  <b>Full Glossary</b> — named characters (with gender &amp; role) "
            "and unique worldbuilding terms in one pass."
        )
        glossary_desc.setTextFormat(Qt.RichText)
        glossary_desc.setWordWrap(True)
        glossary_desc.setStyleSheet("color:#ccc;font-size:13px;")
        pb_inner.addWidget(glossary_desc)
        glossary_row = QHBoxLayout()
        copy_glossary_btn = _make_btn("📋  Copy Prompt for Copilot", "#555")
        copy_glossary_btn.setMinimumWidth(220)
        copy_glossary_btn.setToolTip("Copy the full glossary discovery prompt to clipboard")
        copy_glossary_btn.clicked.connect(self._copy_glossary_prompt)
        glossary_row.addWidget(copy_glossary_btn)
        glossary_row.addStretch()
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
            "color:#569cd6;border:1px solid #444444;"
            "padding:5px 8px;border-radius:3px;font-size:13px;"
        )
        layout.addWidget(format_hint)

        self.vocab_editor = QTextEdit()
        self.vocab_editor.setMinimumHeight(160)
        self.vocab_editor.setFont(QFont("Consolas", 9))
        self.vocab_editor.setStyleSheet(
            "QTextEdit{background-color:#252526;color:#d4d4d4;"
            "border:1px solid #555555;padding:6px;}"
        )
        self._reload_vocab()
        layout.addWidget(self.vocab_editor)

        _VOC_W = 180
        row = QHBoxLayout()
        save_vocab = _make_btn("💾  Save vocab.txt", "#3a7a3a")
        save_vocab.setMinimumWidth(_VOC_W)
        save_vocab.clicked.connect(self._save_vocab)
        row.addWidget(save_vocab)

        reload_vocab = _make_btn("↺  Reload", "#555")
        reload_vocab.setMinimumWidth(_VOC_W)
        reload_vocab.clicked.connect(self._reload_vocab)
        row.addWidget(reload_vocab)
        row.addStretch()
        layout.addLayout(row)

    # ── Step 2: Speaker Detection ───────────────────────────────────────────

    def _build_step2_speaker(self, layout: QVBoxLayout):
        layout.addWidget(_make_section_label("Step 2 — Speaker Format Detection"))

        # Import button row
        _IMP_W = 230
        import_row = QHBoxLayout()
        self.import_btn = _make_btn("⬇  Import Selected → files/", "#007acc")
        self.import_btn.setMinimumWidth(_IMP_W)
        self.import_btn.setEnabled(False)
        self.import_btn.clicked.connect(self._import_files)
        import_row.addWidget(self.import_btn)
        clear_translated_btn = _make_btn("🗑  Clear translated/", "#8b0000")
        clear_translated_btn.setMinimumWidth(_IMP_W)
        clear_translated_btn.setToolTip("Delete all files inside the translated/ folder")
        clear_translated_btn.clicked.connect(self._clear_translated)
        import_row.addWidget(clear_translated_btn)
        import_row.addStretch()
        layout.addLayout(import_row)

        hint = QLabel(
            "Copy the prompt below, open Copilot (or any AI), attach a few of the game's "
            "Map*.json / CommonEvents.json files, paste the prompt, and ask it which "
            "speaker flags to enable. Then tick the matching boxes and click Apply."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#999;font-size:13px;padding-bottom:6px;")
        layout.addWidget(hint)

        copy_row = QHBoxLayout()
        copy_btn = _make_btn("📋  Copy Prompt for Copilot", "#555")
        copy_btn.setToolTip("Copies a prompt explaining all speaker formats — paste into Copilot with game files")
        copy_btn.clicked.connect(self._copy_speaker_prompt)
        copy_row.addWidget(copy_btn)
        copy_row.addStretch()
        layout.addLayout(copy_row)

        # ---- Flag checkboxes ------------------------------------------------
        cb_box = QGroupBox("Speaker flags")
        cb_box.setStyleSheet(self._task_box_style())
        cb_inner = QVBoxLayout(cb_box)
        cb_inner.setSpacing(3)

        self.spk_inline_cb = QCheckBox("INLINE401SPEAKERS  —  speaker name inline before 「 in the 401 text")
        self.spk_inline_cb.stateChanged.connect(self._apply_speaker_flags)
        cb_inner.addWidget(self.spk_inline_cb)

        self.spk_firstline_cb = QCheckBox("FIRSTLINESPEAKERS  —  first 401 line is a short speaker name")
        self.spk_firstline_cb.stateChanged.connect(self._apply_speaker_flags)
        cb_inner.addWidget(self.spk_firstline_cb)

        self.spk_face_cb = QCheckBox("FACENAME101  —  speaker inferred from 101 face-image filename")
        self.spk_face_cb.stateChanged.connect(self._apply_speaker_flags)
        cb_inner.addWidget(self.spk_face_cb)

        layout.addWidget(cb_box)

        self._populate_speaker_flags()

    # ── Step 4: Translation ─────────────────────────────────────────────────

    def _build_step4_translation(self, layout: QVBoxLayout):
        layout.addWidget(_make_section_label("Step 4 — Translation"))

        # ---- Pre-flight: text wrap configuration ----------------------------
        wrap_box = QGroupBox("Pre-flight — Text Wrap Width")
        wrap_box.setStyleSheet(self._task_box_style())
        wrap_inner = QVBoxLayout(wrap_box)
        wrap_inner.setSpacing(6)

        wrap_hint = QLabel(
            "Start with the default values (60 / 70 / 60) and run a test translation. "
            "If lines overflow or wrap too early in-game, adjust the values here and re-translate. "
            "Click Apply to write the values to .env."
        )
        wrap_hint.setWordWrap(True)
        wrap_hint.setStyleSheet("color:#999;font-size:13px;")
        wrap_inner.addWidget(wrap_hint)

        def _spin_pair(label_text: str, default: int):
            lbl = QLabel(label_text)
            sp = QSpinBox()
            sp.setRange(20, 300)
            sp.setValue(default)
            sp.setFixedWidth(68)
            return lbl, sp

        lbl_w,  self.wrap_width_spin = _spin_pair("Dialogue (width)", 60)
        lbl_lw, self.wrap_list_spin  = _spin_pair("List/Help (listWidth)", 70)
        lbl_nw, self.wrap_note_spin  = _spin_pair("Notes (noteWidth)", 60)

        for lbl, sp in [(lbl_w, self.wrap_width_spin),
                        (lbl_lw, self.wrap_list_spin),
                        (lbl_nw, self.wrap_note_spin)]:
            row = QHBoxLayout()
            row.setSpacing(6)
            lbl.setFixedWidth(160)
            row.addWidget(lbl)
            row.addWidget(sp)
            row.addStretch()
            wrap_inner.addLayout(row)

        apply_wrap_row = QHBoxLayout()
        apply_wrap_btn = _make_btn("✔  Apply to .env", "#3a7a3a")
        apply_wrap_btn.setToolTip("Write width / listWidth / noteWidth into .env")
        apply_wrap_btn.clicked.connect(self._apply_wrap_config)
        apply_wrap_row.addWidget(apply_wrap_btn)
        apply_wrap_row.addStretch()
        wrap_inner.addLayout(apply_wrap_row)

        layout.addWidget(wrap_box)

        p0_box = QGroupBox("Phase 0  –  Core Database Files")
        p0_box.setStyleSheet(self._task_box_style())
        p0_inner = QVBoxLayout(p0_box)
        p0_desc = QLabel(
            "Files: Actors, Armors, Weapons, Items, Skills, States, Classes, Enemies, System, MapInfos\n"
            "Translates names, descriptions, and notes in the core database. "
            "Run this first before any event-code phases."
        )
        p0_desc.setStyleSheet("color:#999;font-size:13px;")
        p0_desc.setWordWrap(True)
        p0_inner.addWidget(p0_desc)
        p0_row = QHBoxLayout()
        self._run_p0_btn = _make_btn("▶  Run Phase 0", "#4a7a4a")
        self._run_p0_btn.setToolTip(
            "Sets engine to RPG Maker MV/MZ, selects only DB files "
            "(Actors, Armors … etc.), all event codes OFF — then starts translation."
        )
        self._run_p0_btn.clicked.connect(lambda: self._run_phase(0))
        p0_row.addWidget(self._run_p0_btn)
        self._p0_status_lbl = QLabel("")
        self._p0_status_lbl.setStyleSheet("color:#6a9a6a;font-size:13px;")
        p0_row.addWidget(self._p0_status_lbl)
        p0_row.addStretch()
        p0_inner.addLayout(p0_row)
        layout.addWidget(p0_box)

        p1_box = QGroupBox("Phase 1  –  Safe Codes (dialogue + choices)")
        p1_box.setStyleSheet(self._task_box_style())
        p1_inner = QVBoxLayout(p1_box)
        p1_desc = QLabel(
            "Codes ON: 101 (Name), 401 (Show Text), 405 (continued), 102 (Choices), 408 (extra lines)\n"
            "Clicking the button below applies these codes, then takes you to the Translation tab.\n"
            "While translating, watch the log — speaker lines should look like  [Speaker]: Dialogue."
        )
        p1_desc.setStyleSheet("color:#999;font-size:13px;")
        p1_desc.setWordWrap(True)
        p1_inner.addWidget(p1_desc)
        p1_row = QHBoxLayout()
        self._run_p1_btn = _make_btn("▶  Run Phase 1", "#007acc")
        self._run_p1_btn.setToolTip("Applies Phase 1 code settings and starts translation")
        self._run_p1_btn.clicked.connect(lambda: self._run_phase(1))
        p1_row.addWidget(self._run_p1_btn)
        self._p1_status_lbl = QLabel("")
        self._p1_status_lbl.setStyleSheet("color:#6ab4d4;font-size:13px;")
        p1_row.addWidget(self._p1_status_lbl)
        p1_row.addStretch()
        p1_inner.addLayout(p1_row)
        layout.addWidget(p1_box)

        p1b_box = QGroupBox("Phase 1b  –  Build Variable Cache (code 111)")
        p1b_box.setStyleSheet(self._task_box_style())
        p1b_inner = QVBoxLayout(p1b_box)
        p1b_desc = QLabel(
            "Code ON: 111 (Conditional Branch string comparisons)\n"
            "Scans all 111 branches that compare \u2018$gameVariables\u2019 against string values and "
            "builds the var_translation_map cache.\n"
            "Run this before Phase 2 so that code 122 translated strings are automatically "
            "matched when those same strings appear in 111 comparisons."
        )
        p1b_desc.setStyleSheet("color:#999;font-size:13px;")
        p1b_desc.setWordWrap(True)
        p1b_inner.addWidget(p1b_desc)
        p1b_row = QHBoxLayout()
        self._run_p1b_btn = _make_btn("▶  Run Phase 1b", "#2a5a7a")
        self._run_p1b_btn.setToolTip("Applies Phase 1b code settings (111 only) and starts translation")
        self._run_p1b_btn.clicked.connect(lambda: self._run_phase("1b"))
        p1b_row.addWidget(self._run_p1b_btn)
        self._p1b_status_lbl = QLabel("")
        self._p1b_status_lbl.setStyleSheet("color:#6aaac4;font-size:13px;")
        p1b_row.addWidget(self._p1b_status_lbl)
        p1b_row.addStretch()
        p1b_inner.addLayout(p1b_row)
        layout.addWidget(p1b_box)

        p2_box = QGroupBox("Phase 2  –  Risky Codes (variables + conditionals)")
        p2_box.setStyleSheet(self._task_box_style())
        p2_inner = QVBoxLayout(p2_box)
        p2_desc = QLabel(
            "Phase 2 targets script/variable strings and plugin text.\n"
            "Use the Plugin Prompt to audit the game first, then enable only the codes and "
            "plugins that contain visible text."
        )
        p2_desc.setStyleSheet("color:#999;font-size:13px;")
        p2_desc.setWordWrap(True)
        p2_inner.addWidget(p2_desc)

        copy_risky_row = QHBoxLayout()
        copy_risky_btn = _make_btn("📋  Copy Plugin Prompt", "#555")
        copy_risky_btn.setToolTip(
            "Copy a Copilot prompt that audits code 122 variable ranges and all optional "
            "plugin/script codes (357, 356, 355/655, 657, 320, 324, 325, 108) for visible text."
        )
        copy_risky_btn.clicked.connect(self._copy_plugin_prompt)
        copy_risky_row.addWidget(copy_risky_btn)
        copy_risky_row.addStretch()
        p2_inner.addLayout(copy_risky_row)

        # Code 122 variable ID range
        var_range_row = QHBoxLayout()
        var_range_lbl = QLabel("Code 122 var range:")
        var_range_row.addWidget(var_range_lbl)
        from PyQt5.QtGui import QIntValidator
        self._p2_var_min = QLineEdit("0")
        self._p2_var_min.setValidator(QIntValidator(0, 99999))
        self._p2_var_min.setFixedWidth(55)
        self._p2_var_min.setAlignment(Qt.AlignCenter)
        self._p2_var_min.setToolTip("Minimum variable ID to translate (inclusive)")
        var_range_row.addWidget(self._p2_var_min)
        dash = QLabel("–")
        var_range_row.addWidget(dash)
        self._p2_var_max = QLineEdit("2000")
        self._p2_var_max.setValidator(QIntValidator(1, 99999))
        self._p2_var_max.setFixedWidth(55)
        self._p2_var_max.setAlignment(Qt.AlignCenter)
        self._p2_var_max.setToolTip("Maximum variable ID to translate (exclusive)")
        var_range_row.addWidget(self._p2_var_max)
        apply_range_btn = _make_btn("Apply", "#3a3a3a")
        apply_range_btn.setToolTip("Write CODE122_VAR_MIN / CODE122_VAR_MAX to the module")
        apply_range_btn.clicked.connect(self._apply_var_range)
        var_range_row.addWidget(apply_range_btn)
        var_range_row.addStretch()
        p2_inner.addLayout(var_range_row)

        # Pre-populate range from current module values
        try:
            from gui.config_integration import ConfigIntegration
            cur = ConfigIntegration().read_current_config()
            if "CODE122_VAR_MIN" in cur:
                self._p2_var_min.setText(str(cur["CODE122_VAR_MIN"]))
            if "CODE122_VAR_MAX" in cur:
                self._p2_var_max.setText(str(cur["CODE122_VAR_MAX"]))
        except Exception:
            pass

        # ─── Code Toggles ───────────────────────────────────────────────────────────────────
        toggle_box = QGroupBox()
        toggle_box.setStyleSheet(self._checkbox_box_style())
        toggle_box_layout = QVBoxLayout(toggle_box)
        toggle_box_layout.setContentsMargins(6, 8, 6, 6)
        toggle_box_layout.setSpacing(4)

        codes_sa_row = QHBoxLayout()
        codes_title_lbl = QLabel("Enable Codes")
        codes_title_lbl.setStyleSheet("color:#888888;font-size:12px;")
        codes_sa_row.addWidget(codes_title_lbl)
        codes_sa_row.addStretch()
        codes_select_all_btn = _make_toggle_btn("Select All")
        codes_sa_row.addWidget(codes_select_all_btn)
        toggle_box_layout.addLayout(codes_sa_row)

        toggle_grid_container = QWidget()
        toggle_grid = QGridLayout(toggle_grid_container)
        toggle_grid.setContentsMargins(0, 0, 0, 0)
        toggle_grid.setHorizontalSpacing(16)
        toggle_grid.setVerticalSpacing(4)

        _P2_CODE_DEFS = [
            ("CODE122",    "122 – Variables",     "Control Variables (code 122)"),
            ("CODE357",    "357 – Plugins (MZ)",  "MZ Plugin Command text (code 357)"),
            ("CODE355655", "355/655 – Scripts",   "Inline script text (codes 355/655)"),
            ("CODE356",    "356 – Plugins (MV)",  "MV Plugin Command text (code 356)"),
            ("CODE657",    "657 – Picture Text",  "Extended picture text (code 657)"),
            ("CODE320",    "320 – Actor Name",    "Change Actor Name (code 320)"),
            ("CODE324",    "324 – Nickname",      "Change Nickname (code 324)"),
            ("CODE325",    "325 – Profile",       "Change Profile (code 325)"),
            ("CODE108",    "108 – Comments",      "Comment notetags (code 108)"),
        ]
        self._p2_code_checks: dict = {}
        for idx, (code_key, label, tip) in enumerate(_P2_CODE_DEFS):
            cb = QCheckBox(label)
            cb.setToolTip(tip)
            cb.setStyleSheet("color:#cccccc;font-size:13px;")
            toggle_grid.addWidget(cb, idx // 3, idx % 3)
            self._p2_code_checks[code_key] = cb
        toggle_box_layout.addWidget(toggle_grid_container)

        def _toggle_codes(checked):
            codes_select_all_btn.setText("Deselect All" if checked else "Select All")
            for cb in self._p2_code_checks.values():
                cb.setChecked(checked)
        codes_select_all_btn.toggled.connect(_toggle_codes)
        p2_inner.addWidget(toggle_box)

        # ─── Code 357 Plugin Handlers ───────────────────────────────────────────────────
        plugin357_box = QGroupBox()
        plugin357_box.setStyleSheet(self._checkbox_box_style())
        plugin357_inner = QVBoxLayout(plugin357_box)
        plugin357_inner.setContentsMargins(4, 8, 4, 4)

        plugin357_container = QWidget()
        plugin357_grid = QGridLayout(plugin357_container)
        plugin357_grid.setContentsMargins(4, 2, 4, 2)
        plugin357_grid.setHorizontalSpacing(12)
        plugin357_grid.setVerticalSpacing(2)
        self._p2_plugin_checks: dict = {}
        try:
            from modules.rpgmakermvmz import HEADER_MAPPINGS_357 as _HM357
            for idx, key in enumerate(sorted(_HM357.keys())):
                cb = QCheckBox(key)
                cb.setStyleSheet("color:#cccccc;font-size:13px;")
                plugin357_grid.addWidget(cb, idx // 2, idx % 2)
                self._p2_plugin_checks[key] = cb
        except Exception:
            pass

        plugin357_scroll = QScrollArea()
        plugin357_scroll.setMaximumHeight(120)
        plugin357_scroll.setWidgetResizable(True)
        plugin357_scroll.setWidget(plugin357_container)
        plugin357_scroll.setStyleSheet("QScrollArea{border:none;}")
        plugin357_sa_row = QHBoxLayout()
        plugin357_title_lbl = QLabel("Code 357 – Plugin Handlers (MZ)")
        plugin357_title_lbl.setStyleSheet("color:#888888;font-size:12px;")
        plugin357_sa_row.addWidget(plugin357_title_lbl)
        plugin357_sa_row.addStretch()
        plugin357_select_all_btn = _make_toggle_btn("Select All")
        plugin357_sa_row.addWidget(plugin357_select_all_btn)
        plugin357_inner.addLayout(plugin357_sa_row)
        plugin357_inner.addWidget(plugin357_scroll)

        def _toggle_plugins357(checked):
            plugin357_select_all_btn.setText("Deselect All" if checked else "Select All")
            for cb in self._p2_plugin_checks.values():
                cb.setChecked(checked)
        plugin357_select_all_btn.toggled.connect(_toggle_plugins357)
        p2_inner.addWidget(plugin357_box)

        # ─── Code 355/655 Script Patterns ───────────────────────────────────────────
        patterns_box = QGroupBox()
        patterns_box.setStyleSheet(self._checkbox_box_style())
        patterns_inner_layout = QVBoxLayout(patterns_box)
        patterns_inner_layout.setContentsMargins(4, 8, 4, 4)

        patterns_container = QWidget()
        patterns_grid = QGridLayout(patterns_container)
        patterns_grid.setContentsMargins(4, 2, 4, 2)
        patterns_grid.setHorizontalSpacing(12)
        patterns_grid.setVerticalSpacing(2)
        self._p2_pattern_checks: dict = {}
        try:
            from modules.rpgmakermvmz import PATTERNS_355655 as _PAT
            for idx, key in enumerate(sorted(_PAT.keys())):
                cb = QCheckBox(key)
                cb.setStyleSheet("color:#cccccc;font-size:13px;")
                patterns_grid.addWidget(cb, idx // 2, idx % 2)
                self._p2_pattern_checks[key] = cb
        except Exception:
            pass

        patterns_scroll = QScrollArea()
        patterns_scroll.setMaximumHeight(110)
        patterns_scroll.setWidgetResizable(True)
        patterns_scroll.setWidget(patterns_container)
        patterns_scroll.setStyleSheet("QScrollArea{border:none;}")
        patterns_sa_row = QHBoxLayout()
        patterns_title_lbl = QLabel("Code 355/655 – Script Patterns")
        patterns_title_lbl.setStyleSheet("color:#888888;font-size:12px;")
        patterns_sa_row.addWidget(patterns_title_lbl)
        patterns_sa_row.addStretch()
        patterns_select_all_btn = _make_toggle_btn("Select All")
        patterns_sa_row.addWidget(patterns_select_all_btn)
        patterns_inner_layout.addLayout(patterns_sa_row)
        patterns_inner_layout.addWidget(patterns_scroll)

        def _toggle_patterns(checked):
            patterns_select_all_btn.setText("Deselect All" if checked else "Select All")
            for cb in self._p2_pattern_checks.values():
                cb.setChecked(checked)
        patterns_select_all_btn.toggled.connect(_toggle_patterns)
        p2_inner.addWidget(patterns_box)

        _P2_BTN_WIDTH = 220

        # Apply Plugin Settings button
        apply_plugins_row = QHBoxLayout()
        apply_plugins_btn = _make_btn("✔  Apply Plugin Settings", "#2a4a6a")
        apply_plugins_btn.setFixedWidth(_P2_BTN_WIDTH)
        apply_plugins_btn.setToolTip(
            "Save the checked plugin handlers and script patterns to the module file.\n"
            "Updates ENABLED_PLUGINS_357 and ENABLED_PATTERNS_355655 in rpgmakermvmz.py."
        )
        apply_plugins_btn.clicked.connect(self._apply_plugin_settings)
        apply_plugins_row.addWidget(apply_plugins_btn)
        apply_plugins_row.addStretch()
        p2_inner.addLayout(apply_plugins_row)

        p2_row = QHBoxLayout()
        self._run_p2_btn = _make_btn("▶  Run Phase 2", "#7a4a00")
        self._run_p2_btn.setFixedWidth(_P2_BTN_WIDTH)
        self._run_p2_btn.setToolTip(
            "Applies Phase 2 code settings (from the checkboxes above) and starts translation "
            "with event files pre-selected."
        )
        self._run_p2_btn.clicked.connect(lambda: self._run_phase(2))
        p2_row.addWidget(self._run_p2_btn)
        self._p2_status_lbl = QLabel("")
        self._p2_status_lbl.setStyleSheet("color:#d4aa68;font-size:13px;")
        p2_row.addWidget(self._p2_status_lbl)
        p2_row.addStretch()
        p2_inner.addLayout(p2_row)
        layout.addWidget(p2_box)

        # Pre-populate all Phase 2 checkboxes from current module state
        self._populate_p2_checkboxes()

    # ── Step 5: plugins.js Translation ─────────────────────────────────────

    def _build_step5_plugins_js(self, layout: QVBoxLayout):
        layout.addWidget(_make_section_label("Step 5 — Translate plugins.js"))

        hint = QLabel(
            "Translate the visible Japanese strings in js/plugins.js without breaking "
            "game logic. First copy vocab.txt into the game folder so the AI can use it "
            "as a glossary, then copy the prompt and paste it into Copilot or Cursor with "
            "plugins.js, vocab.txt, and optionally System.json attached."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#999;font-size:13px;padding-bottom:6px;")
        layout.addWidget(hint)

        _BTN_WIDTH = 300

        vocab_btn = _make_btn("1.  📄  Copy vocab.txt → Game Folder", "#555")
        vocab_btn.setFixedWidth(_BTN_WIDTH)
        vocab_btn.setToolTip(
            "Copy vocab.txt to <game root>/vocab.txt so you can attach it "
            "alongside plugins.js when running the AI prompt."
        )
        vocab_btn.clicked.connect(self._copy_vocab_to_game)

        copy_btn = _make_btn("2.  📋  Copy Prompt for Copilot", "#555")
        copy_btn.setFixedWidth(_BTN_WIDTH)
        copy_btn.setToolTip(
            "Copy a prompt that instructs Copilot/Cursor to translate only "
            "visible player-facing strings in plugins.js, using vocab.txt as a glossary."
        )
        copy_btn.clicked.connect(self._copy_plugins_js_translate_prompt)

        for btn in (vocab_btn, copy_btn):
            row = QHBoxLayout()
            row.addWidget(btn)
            row.addStretch()
            layout.addLayout(row)

        self._s5_vocab_status = QLabel("")
        self._s5_vocab_status.setStyleSheet("color:#aaa;font-size:13px;padding-left:4px;")
        layout.addWidget(self._s5_vocab_status)

    # ── Step 6: Export ──────────────────────────────────────────────────────

    def _build_step6_export(self, layout: QVBoxLayout):
        layout.addWidget(_make_section_label("Step 6 — Export to Game"))
        hint = QLabel(
            "Copy translated files back into the game's data folder to patch the game in-place."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#999;font-size:13px;padding-bottom:4px;")
        layout.addWidget(hint)

        _EXP_W = 280
        row = QHBoxLayout()
        export_active_btn = _make_btn("📤  Export Active Files → Game Folder", "#3a7a3a")
        export_active_btn.setMinimumWidth(_EXP_W)
        export_active_btn.setToolTip(
            "Only export files whose names match those currently in files/\n"
            "(i.e. the files you imported for this project)"
        )
        export_active_btn.clicked.connect(self._export_active_files)
        row.addWidget(export_active_btn)

        export_all_btn = _make_btn("📤  Export ALL translated/ → Game Folder", "#555")
        export_all_btn.setMinimumWidth(_EXP_W)
        export_all_btn.setToolTip("Export every file in translated/ regardless of what is in files/")
        export_all_btn.clicked.connect(self._export_to_game)
        row.addWidget(export_all_btn)
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
        self.sel_all_btn.setText("Select All")
        self._log(f"Found {len(items)} importable file(s). Auto-importing…")
        self._populate_preprocess_paths()
        # Automatically import the selected files so the user doesn't need
        # to scroll down and click Import as a separate step.
        self._import_files()

    def _select_all_files(self):
        count = self.file_list.count()
        if not count:
            return
        all_checked = all(
            self.file_list.item(i).checkState() == Qt.Checked
            for i in range(count)
        )
        new_state = Qt.Unchecked if all_checked else Qt.Checked
        for i in range(count):
            self.file_list.item(i).setCheckState(new_state)
        if new_state == Qt.Checked:
            self.sel_all_btn.setText("Deselect All")
            self._log(f"✔  Selected all {count} file(s).")
        else:
            self.sel_all_btn.setText("Select All")
            self._log(f"✔  Deselected all {count} file(s).")

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

    def _clear_translated(self):
        translated_dir = Path("translated")
        items_to_delete = [
            item for item in translated_dir.iterdir()
            if item.name != ".gitkeep"
        ] if translated_dir.exists() else []
        if not items_to_delete:
            self._log("ℹ  translated/ is already empty — nothing to clear.")
            return
        reply = QMessageBox.warning(
            self,
            "Clear translated/ folder",
            "This will permanently delete all files inside the translated/ folder.\n\nAre you sure?",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if reply != QMessageBox.Yes:
            return
        deleted = 0
        errors = []
        for item in items_to_delete:
            try:
                if item.is_file():
                    item.unlink()
                    deleted += 1
                elif item.is_dir():
                    import shutil
                    shutil.rmtree(item)
                    deleted += 1
            except Exception as exc:
                errors.append(f"{item.name}: {exc}")
        if errors:
            self._log(f"⚠  {len(errors)} error(s) while clearing translated/:")
            for e in errors[:10]:
                self._log(f"   {e}")
        self._log(f"✅ Cleared {deleted} item(s) from translated/")

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

    def _copy_glossary_prompt(self):
        """Build the glossary prompt, injecting any already-parsed speakers."""
        prompt = self._PROMPT_GLOSSARY

        # Extract # Speakers entries from current vocab.txt
        speakers = []
        try:
            vocab_text = Path("vocab.txt").read_text(encoding="utf-8")
            in_speakers = False
            for line in vocab_text.splitlines():
                stripped = line.strip()
                if stripped == "# Speakers":
                    in_speakers = True
                    continue
                if in_speakers:
                    if stripped.startswith("#"):
                        break  # next section
                    if stripped:
                        speakers.append(stripped)
        except Exception:
            pass

        if speakers:
            speaker_block = (
                "\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "ALREADY-IDENTIFIED SPEAKERS\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "The speaker parser has already found these names in the game files.\n"
                "For genuine named characters in this list, add them to # Game Characters\n"
                "with gender, role, and speech register.\n"
                "Skip entries that are clearly NOT real characters — generic labels (e.g. 男, 女),\n"
                "placeholders (e.g. ＊＊＊, ???), or system strings.\n"
                "```\n"
                + "\n".join(speakers)
                + "\n```"
            )
            prompt = prompt + speaker_block

        self._copy_to_clipboard(prompt, "Glossary prompt copied."
            + (f" ({len(speakers)} speaker(s) included.)" if speakers else ""))

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

    # ─────────────────────────────────────────────────────────────────────────
    # Step 3 – Speaker detection
    # ─────────────────────────────────────────────────────────────────────────

    def _copy_speaker_prompt(self):
        QApplication.clipboard().setText(self._SPEAKER_PROMPT)
        self._log("Speaker format prompt copied to clipboard.")

    def _copy_wrap_prompt(self):
        QApplication.clipboard().setText(self._WRAP_PROMPT)
        self._log("Text-wrap analysis prompt copied to clipboard.")

    def _apply_var_range(self):
        """Write CODE122_VAR_MIN / CODE122_VAR_MAX to the module file."""
        try:
            var_min = int(self._p2_var_min.text() or 0)
            var_max = int(self._p2_var_max.text() or 2000)
        except ValueError:
            self._log("❌ Var range: invalid numbers")
            return
        cfg = {"CODE122_VAR_MIN": var_min, "CODE122_VAR_MAX": var_max}
        try:
            from gui.config_integration import ConfigIntegration
            ConfigIntegration().update_rpgmaker_config(cfg)
            self._log(f"✅ Code 122 var range set: {var_min}–{var_max}")
            # Sync to the Settings tab if open
            try:
                if self.parent_window and hasattr(self.parent_window, "config_tab"):
                    ct = self.parent_window.config_tab
                    if hasattr(ct, "rpgmaker_tab") and ct.rpgmaker_tab:
                        rt = ct.rpgmaker_tab
                        if hasattr(rt, "code122_var_min_spin"):
                            rt.code122_var_min_spin.setText(str(var_min))
                        if hasattr(rt, "code122_var_max_spin"):
                            rt.code122_var_max_spin.setText(str(var_max))
            except Exception:
                pass
        except Exception as exc:
            self._log(f"❌ Could not apply var range: {exc}")

    def _populate_p2_checkboxes(self):
        """Read current module config and pre-tick Phase 2 checkboxes."""
        try:
            from gui.config_integration import ConfigIntegration
            ci = ConfigIntegration()
            # Code toggle checkboxes
            cur = ci.read_current_config()
            for code_key, cb in getattr(self, "_p2_code_checks", {}).items():
                if code_key in cur:
                    cb.setChecked(cur[code_key])
            # Plugin / pattern checkboxes
            plugin_cfg = ci.read_plugin_config()
            enabled_357 = plugin_cfg.get("ENABLED_PLUGINS_357", set())
            enabled_355655 = plugin_cfg.get("ENABLED_PATTERNS_355655", set())
            for key, cb in getattr(self, "_p2_plugin_checks", {}).items():
                cb.setChecked(key in enabled_357)
            for key, cb in getattr(self, "_p2_pattern_checks", {}).items():
                cb.setChecked(key in enabled_355655)
        except Exception:
            pass

    def _apply_plugin_settings(self):
        """Write the checked plugin handlers and script patterns back to rpgmakermvmz.py."""
        try:
            from gui.config_integration import ConfigIntegration
            ci = ConfigIntegration()
            enabled_357 = {
                k for k, cb in getattr(self, "_p2_plugin_checks", {}).items()
                if cb.isChecked()
            }
            enabled_355655 = {
                k for k, cb in getattr(self, "_p2_pattern_checks", {}).items()
                if cb.isChecked()
            }
            ci.update_plugin_config(enabled_357, enabled_355655)
            self._log(
                f"✅ Plugin settings saved — "
                f"357: {len(enabled_357)} handler(s), "
                f"355/655: {len(enabled_355655)} pattern(s) enabled"
            )
            if enabled_357:
                self._log("   357  : " + ", ".join(sorted(enabled_357)))
            if enabled_355655:
                self._log("   355/655: " + ", ".join(sorted(enabled_355655)))
        except Exception as exc:
            self._log(f"❌ Could not save plugin settings: {exc}")

    def _copy_vocab_to_game(self):
        """Copy vocab.txt into the game root folder so it can be attached to the AI prompt."""
        game_root = self.folder_edit.text().strip()
        if not game_root:
            self._log("⚠  No game folder set. Complete Step 0 first.")
            try:
                self._s5_vocab_status.setText("⚠ No game folder set.")
            except Exception:
                pass
            return

        src = Path("vocab.txt")
        if not src.exists():
            self._log("⚠  vocab.txt not found — save it in Step 3 first.")
            try:
                self._s5_vocab_status.setText("⚠ vocab.txt not found.")
            except Exception:
                pass
            return

        import shutil
        dst = Path(game_root) / "vocab.txt"
        try:
            shutil.copy2(src, dst)
            self._log(f"✅ vocab.txt copied to {dst}")
            try:
                self._s5_vocab_status.setText(f"✅ Copied to {dst}")
            except Exception:
                pass
        except Exception as exc:
            self._log(f"❌ Could not copy vocab.txt: {exc}")
            try:
                self._s5_vocab_status.setText(f"❌ {exc}")
            except Exception:
                pass

    def _copy_plugins_js_translate_prompt(self):
        QApplication.clipboard().setText(self._PLUGINS_JS_TRANSLATE_PROMPT)
        self._log("plugins.js translation prompt copied to clipboard.")

    def _copy_plugin_prompt(self):
        QApplication.clipboard().setText(self._PLUGIN_PROMPT)
        self._log("Risky codes analysis prompt copied to clipboard.")

    def _apply_wrap_config(self):
        """Write width / listWidth / noteWidth back into .env."""
        import re as _re
        updates = {
            "width":     str(self.wrap_width_spin.value()),
            "listWidth": str(self.wrap_list_spin.value()),
            "noteWidth": str(self.wrap_note_spin.value()),
        }
        env_path = Path(".env")
        try:
            text = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
            for key, val in updates.items():
                text, n = _re.subn(
                    rf"^({_re.escape(key)}\s*=\s*')[^']*(')",
                    rf"\g<1>{val}\2",
                    text,
                    flags=_re.MULTILINE,
                )
                if n == 0:
                    text = text.rstrip("\n") + f"\n{key}='{val}'\n"
            env_path.write_text(text, encoding="utf-8")
            self._log(
                "✅ .env updated — "
                + ", ".join(f"{k}={v}" for k, v in updates.items())
            )
        except Exception as exc:
            self._log(f"❌ Could not update .env: {exc}")

    def _populate_speaker_flags(self):
        """Read current module config and pre-tick speaker flag checkboxes."""
        try:
            from gui.config_integration import ConfigIntegration
            cur = ConfigIntegration().read_current_config()
            flag_map = {
                "INLINE401SPEAKERS": self.spk_inline_cb,
                "FIRSTLINESPEAKERS": self.spk_firstline_cb,
                "FACENAME101":       self.spk_face_cb,
            }
            for key, cb in flag_map.items():
                if key in cur:
                    cb.blockSignals(True)
                    cb.setChecked(bool(cur[key]))
                    cb.blockSignals(False)
        except Exception:
            pass

    def _apply_speaker_flags(self):
        cfg = {
            "INLINE401SPEAKERS": self.spk_inline_cb.isChecked(),
            "FIRSTLINESPEAKERS": self.spk_firstline_cb.isChecked(),
            "FACENAME101":       self.spk_face_cb.isChecked(),
        }
        try:
            from gui.config_integration import ConfigIntegration
            ConfigIntegration().update_rpgmaker_config(cfg)
            self._log(
                "✅ Speaker flags applied: "
                + ", ".join(f"{k}={v}" for k, v in cfg.items())
            )
            try:
                if self.parent_window and hasattr(self.parent_window, "config_tab"):
                    ct = self.parent_window.config_tab
                    if hasattr(ct, "rpgmaker_tab") and ct.rpgmaker_tab:
                        ct.rpgmaker_tab.set_config(cfg)
            except Exception:
                pass
        except Exception as exc:
            self._log(f"❌ Could not apply speaker flags: {exc}")

    # ─────────────────────────────────────────────────────────────────────────
    # Step 4 – Translation phases
    # ─────────────────────────────────────────────────────────────────────────

    def _run_phase(self, phase):
        # Ask user if they want to sync translated/ → files/ before running this phase
        from PyQt5.QtWidgets import QMessageBox
        transl_dir = Path("translated")
        files_dir  = Path("files")
        if transl_dir.exists() and any(transl_dir.glob("*.json")):
            active = {fp.name for fp in files_dir.glob("*.json")} if files_dir.exists() else set()
            overlap = [fp for fp in transl_dir.glob("*.json") if not active or fp.name in active]
            if overlap:
                reply = QMessageBox.question(
                    None,
                    "Sync before phase?",
                    f"translated/ contains {len(overlap)} file(s) that match files/.\n\n"
                    "Sync translated/ → files/ before running this phase?\n"
                    "Yes = overwrite files/ with translated versions\n"
                    "No = use existing files/ as-is",
                    QMessageBox.Yes | QMessageBox.No,
                )
                if reply == QMessageBox.Yes:
                    self._do_copy_translated_to_files()

        if phase == 0:
            config = PHASE0_CONFIG
            label = "Phase 0 (core DB files)"
            file_preset = "db"
        elif phase == 1:
            config = PHASE1_CONFIG
            label = "Phase 1 (safe codes)"
            file_preset = "events"
        elif phase == "1b":
            config = PHASE1B_CONFIG
            label = "Phase 1b (code 111 cache)"
            file_preset = "events"
        else:
            # Build Phase 2 config: start from PHASE2_CONFIG defaults, then overlay checkbox states
            config = dict(PHASE2_CONFIG)
            for code_key, cb in getattr(self, "_p2_code_checks", {}).items():
                config[code_key] = cb.isChecked()
            label = "Phase 2 (risky codes)"
            file_preset = "events"

        # Apply config profile so the Translation tab uses the right codes
        try:
            from gui.config_integration import ConfigIntegration
            ci = ConfigIntegration()
            ci.update_rpgmaker_config(config)
            # Sync the live Settings tab if it is open
            try:
                if self.parent_window and hasattr(self.parent_window, "config_tab"):
                    ct = self.parent_window.config_tab
                    if hasattr(ct, "rpgmaker_tab"):
                        ct.rpgmaker_tab.set_config(
                            ct.rpgmaker_tab.get_config() | config
                        )
            except Exception:
                pass
            self._log(f"✅ {label} config applied — codes set:")
            on  = [k for k, v in config.items() if v]
            off = [k for k, v in config.items() if not v]
            if on:
                self._log("   ON :  " + "  ".join(on))
            if off:
                self._log("   OFF:  " + "  ".join(off))
        except Exception as exc:
            self._log(f"❌ Could not apply phase config: {exc}")
            return

        # Visual feedback on the phase run button
        _btn_map = {0: "_run_p0_btn", 1: "_run_p1_btn", "1b": "_run_p1b_btn", 2: "_run_p2_btn"}
        _lbl_map = {0: "_p0_status_lbl", 1: "_p1_status_lbl", "1b": "_p1b_status_lbl", 2: "_p2_status_lbl"}
        _phlbl = getattr(self, _lbl_map.get(phase, ""), None)
        _phbtn = getattr(self, _btn_map.get(phase, ""), None)
        if _phlbl:
            _phlbl.setText("✅ Applied")
        if _phbtn:
            _orig = _phbtn.text()
            _phbtn.setText("⚙  Starting…")
            _phbtn.setEnabled(False)
            QTimer.singleShot(2500, lambda b=_phbtn, t=_orig: (b.setText(t), b.setEnabled(True)))

        # Phase-specific guidance
        if phase == 0:
            self._log("")
            self._log("─" * 54)
            self._log("👉  Switch to the Translation tab and start the run.")
            self._log("   Phase 0 translates core DB file fields (names,")
            self._log("   descriptions, notes). Event codes are all OFF.")
            self._log("─" * 54)
        elif phase == 1:
            self._log("")
            self._log("─" * 54)
            self._log("👉  Switch to the Translation tab and start the run.")
            self._log("")
            self._log("⚠  While translating, watch the log for speaker lines.")
            self._log("   They should look like:  [Speaker]: Dialogue text")
            self._log("   If names are missing or garbled, stop the run and")
            self._log("   revisit Step 2 (speaker flags) before continuing.")
            self._log("─" * 54)
        elif phase == "1b":
            self._log("")
            self._log("─" * 54)
            self._log("👉  Switch to the Translation tab and start the run.")
            self._log("   Phase 1b translates code 111 string comparisons and")
            self._log("   writes a var_translation_map cache to log/.")
            self._log("   Run Phase 2 afterwards — code 122 strings that match")
            self._log("   a cached 111 comparison will reuse the same translation.")
            self._log("─" * 54)
        else:
            self._log("")
            self._log("─" * 54)
            self._log("👉  Switch to the Translation tab and start the run.")
            self._log("   Phase 2 targets script/variable strings — make sure")
            self._log("   Phase 1b has been run first to build the 111 cache.")
            self._log("─" * 54)

        # Navigate to Translation tab, configure it, and auto-start
        self._navigate_to_translation(file_preset, auto_start=True)

    def _navigate_to_translation(self, file_preset: str, auto_start: bool = False):
        """Switch to Translation tab, set engine to MVMZ, and check/uncheck files.

        file_preset:
            'db'     — check only core DB files, uncheck event files
            'events' — check CommonEvents, Troops, and Map*.json; uncheck DB files
        """
        try:
            pw = self.parent_window
            if not pw:
                return
            tt = getattr(pw, "translation_tab", None)
            if tt is None:
                return

            # 1. Set engine to RPG Maker MV/MZ
            try:
                combo = tt.module_combo
                for i in range(combo.count()):
                    if "RPG Maker MV/MZ" in combo.itemText(i):
                        combo.setCurrentIndex(i)
                        break
            except Exception:
                pass

            # 2. Determine which files belong to each preset
            files_dir = getattr(tt, "files_dir", None)
            if files_dir is None:
                files_dir = __import__("pathlib").Path("files")

            def _is_event(name: str) -> bool:
                return (
                    name in _EVENT_FILES_EXACT
                    or (name.startswith("Map") and name.endswith(".json") and name not in _DB_FILES)
                )

            def _is_db(name: str) -> bool:
                return name in _DB_FILES

            if file_preset == "db":
                should_check = _is_db
            else:  # "events"
                should_check = _is_event

            # 3. Apply check states to the file list
            try:
                tt.refresh_file_lists()
                fl = tt.file_list
                from PyQt5.QtCore import Qt as _Qt
                for idx in range(fl.count()):
                    item = fl.item(idx)
                    name = item.text()
                    item.setCheckState(
                        _Qt.Checked if should_check(name) else _Qt.Unchecked
                    )
            except Exception:
                pass

            # 4. Navigate
            if hasattr(pw, "content_stack"):
                pw.content_stack.setCurrentIndex(0)
                if hasattr(pw, "nav_buttons"):
                    for i, btn in enumerate(pw.nav_buttons):
                        btn.setChecked(i == 0)

            # 5. Auto-start translation so the user doesn't need an extra click
            if auto_start:
                from PyQt5.QtCore import QTimer as _QTimer
                _QTimer.singleShot(100, lambda: (
                    tt.start_translation(skip_confirm=True)
                    if tt is not None else None
                ))
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # Step 6 – Export to game
    # ─────────────────────────────────────────────────────────────────────────

    def _do_copy_translated_to_files(self):
        """Silently copy translated/ files back into files/ (only matching names). Returns count copied."""
        import shutil
        files_dir  = Path("files")
        transl_dir = Path("translated")

        if not transl_dir.exists():
            self._log("⚠  translated/ folder not found — nothing to sync.")
            return 0

        active = {fp.name for fp in files_dir.glob("*.json")} if files_dir.exists() else set()
        to_copy = [fp for fp in transl_dir.glob("*.json") if not active or fp.name in active]

        if not to_copy:
            self._log("⚠  No matching files found in translated/ to sync.")
            return 0

        files_dir.mkdir(exist_ok=True)
        copied = 0
        for src in to_copy:
            dst = files_dir / src.name
            shutil.copy2(src, dst)
            copied += 1

        self._log(f"✅  Synced {copied} file(s) from translated/ → files/")
        return copied

    def _copy_translated_to_files(self):
        """Prompt user then copy translated/ files back into files/ (only matching names)."""
        from PyQt5.QtWidgets import QMessageBox
        files_dir  = Path("files")
        transl_dir = Path("translated")

        if not transl_dir.exists():
            self._log("⚠  translated/ folder not found — nothing to sync.")
            return

        active = {fp.name for fp in files_dir.glob("*.json")} if files_dir.exists() else set()
        to_copy = [fp for fp in transl_dir.glob("*.json") if not active or fp.name in active]

        if not to_copy:
            self._log("⚠  No matching files found in translated/ to sync.")
            return

        reply = QMessageBox.question(
            None,
            "Sync translated/ → files/",
            f"This will overwrite {len(to_copy)} file(s) in files/ with their translated versions.\n\n"
            "Choose Yes to sync, or No to keep files/ as-is.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            self._log("⏭  Sync skipped — using existing files/ as-is.")
            return

        self._do_copy_translated_to_files()

    def _export_active_files(self):
        """Export only translated files whose names match what is in files/."""
        files_dir = Path("files")
        active = sorted(
            fp.name for fp in files_dir.glob("*.json") if fp.name != ".gitkeep"
        ) if files_dir.exists() else []

        if not active:
            self._log("⚠  No files found in files/ — run Step 0 (Import) first.")
            return

        game_data = self._resolve_export_path()
        if not game_data:
            return

        translated_dir = Path("translated")
        active_set = set(active)
        exportable = [
            fp for fp in translated_dir.glob("*.json")
            if fp.name in active_set and fp.name != ".gitkeep"
        ] if translated_dir.exists() else []

        reply = QMessageBox.question(
            self,
            "Export Active Files to Game",
            f"Export {len(exportable)} file(s) into:\n{game_data}\n\n"
            "Make a backup first if needed. Continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        w = _ExportWorker(game_data, filter_names=active)
        w.log.connect(self._log)
        w.done.connect(self._on_export_done)
        self._worker = w
        w.start()

    def _export_to_game(self):
        game_data = self._resolve_export_path()
        if not game_data:
            return

        reply = QMessageBox.question(
            self,
            "Export to Game",
            f"This will overwrite ALL translated files in:\n{game_data}\n\n"
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

    def _resolve_export_path(self) -> str | None:
        """Return the game data path, prompting if not yet set."""
        game_data = self._data_path
        if not game_data:
            game_data = QFileDialog.getExistingDirectory(
                self, "Select Game Data Folder to Export Into"
            )
            if not game_data:
                return None
            self._data_path = game_data
        return game_data

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
        w = _JsonFormatWorker(data_path)
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
        """Launch all three pre-process tasks in sequence, chaining via signals."""
        data_path      = self._data_path
        plugins_js     = self.pp_plugins_edit.text().strip()
        gameupdate_src = self.pp_gameupdate_edit.text().strip()
        game_root_dst  = self.folder_edit.text().strip()

        # Build the queue of (label, worker_or_None) pairs
        queue: list[tuple[str, object]] = []

        if data_path:
            queue.append(("[A] dazedformat", _JsonFormatWorker(data_path)))
        else:
            self._log("  ⏭  Skipped: A (dazedformat): data folder missing")

        if plugins_js and Path(plugins_js).is_file():
            queue.append(("[B] format plugins.js", _JsFormatWorker(plugins_js)))
        else:
            self._log(f"  ⏭  Skipped: B (format plugins.js): not found ({plugins_js or 'not set'})")

        if gameupdate_src and Path(gameupdate_src).is_dir() and game_root_dst:
            queue.append(("[C] gameupdate copy", _FileCopyWorker(gameupdate_src, game_root_dst)))
        else:
            reason = (f"source not found ({gameupdate_src or 'not set'})"
                      if not gameupdate_src or not Path(gameupdate_src).is_dir()
                      else "game root folder missing")
            self._log(f"  ⏭  Skipped: C (gameupdate): {reason}")

        if not queue:
            self._log("⚠  Nothing to run — check prerequisites.")
            return

        # Keep strong references to all workers so they aren't GC'd mid-run
        self._preprocess_workers = [w for _, w in queue]

        def run_next(remaining):
            if not remaining:
                self._log("✅  All pre-process tasks finished.")
                return
            label, worker = remaining[0]
            self._log(f"▶ {label} …")
            worker.log.connect(self._log)

            def on_done(ok, msg, rest=remaining[1:]):
                self._log(("✅ " if ok else "❌ ") + msg)
                run_next(rest)

            # _FileCopyWorker emits done(int, list) — wrap it
            if isinstance(worker, _FileCopyWorker):
                def on_copy_done(count, errors, rest=remaining[1:]):
                    self._log(f"✅ gameupdate: copied {count} file(s).")
                    for e in errors:
                        self._log(f"   ⚠  {e}")
                    run_next(rest)
                worker.done.connect(on_copy_done)
            else:
                worker.done.connect(on_done)

            worker.start()

        run_next(queue)

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
