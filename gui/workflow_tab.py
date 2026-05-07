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

from PyQt5.QtCore import Qt, QEvent, QSettings, QThread, QTimer, pyqtSignal
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
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QAbstractItemView,
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
            import shutil
            from util.project_scanner import import_to_files

            # Clear existing files/ contents before importing so stale files
            # from a previous game don't linger. translated/ is intentionally
            # left untouched.
            dest = Path(self.dest_dir)
            if dest.exists():
                removed = 0
                for fp in dest.iterdir():
                    if fp.name == ".gitkeep":
                        continue
                    if fp.is_file():
                        try:
                            fp.unlink()
                            removed += 1
                        except Exception as e:
                            self.log.emit(f"  ⚠ Could not remove {fp.name}: {e}")
                    elif fp.is_dir():
                        try:
                            shutil.rmtree(fp)
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
        "font-size: 14px; font-weight: bold; color: #e0e0e0;"
        "padding: 7px 0px 6px 10px; background-color: transparent;"
        "border-left: 3px solid #007acc; margin-top: 6px;"
    )
    return lbl


def _make_hr() -> QFrame:
    hr = QFrame()
    hr.setFrameShape(QFrame.HLine)
    hr.setFrameShadow(QFrame.Plain)
    hr.setStyleSheet("QFrame { color: #333333; margin: 10px 0px 4px 0px; }")
    return hr


def _make_btn(text: str, color: str = "#007acc") -> QPushButton:
    """Button styled to match the translation tab.

    Dark utility colours (max channel < 115) use the flat sidebar style.
    Action colours use flat dark bg + coloured outline + coloured text.
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
            f"font-family:'Segoe UI','Segoe UI Emoji','Apple Color Emoji',sans-serif;}}"
            f"QPushButton:hover{{background-color:#3e3e42;}}"
            f"QPushButton:pressed{{background-color:#007acc;color:white;}}"
            f"QPushButton:disabled{{background-color:#404040;color:#666666;border-color:#444444;}}"
        )
    else:
        # Flat dark bg + coloured outline + lightened text
        rt = min(255, r + 80)
        gt = min(255, g + 80)
        bt = min(255, b + 80)
        text_color = f"#{rt:02x}{gt:02x}{bt:02x}"
        base = 0x2d
        rh = min(255, int(base + (r - base) * 0.18))
        gh = min(255, int(base + (g - base) * 0.18))
        bh = min(255, int(base + (b - base) * 0.18))
        hover_bg = f"#{rh:02x}{gh:02x}{bh:02x}"
        rb = min(255, r + 35)
        gb = min(255, g + 35)
        bb = min(255, b + 35)
        hover_accent = f"#{rb:02x}{gb:02x}{bb:02x}"
        btn.setStyleSheet(
            f"QPushButton{{background-color:#2d2d30;color:{text_color};"
            f"border:1px solid {color};{_PAD}"
            f"border-radius:4px;font-size:12px;font-weight:bold;"
            f"font-family:'Segoe UI','Segoe UI Emoji','Apple Color Emoji',sans-serif;}}"
            f"QPushButton:hover{{background-color:{hover_bg};border-color:{hover_accent};color:{hover_accent};}}"
            f"QPushButton:pressed{{background-color:#1a1a1a;}}"
            f"QPushButton:disabled{{background-color:#2d2d30;color:#555555;border-color:#444444;}}"
        )
    return btn


def _make_icon_btn(icon_text: str, tooltip: str = "") -> QPushButton:
    """Compact icon-only button matching the Translation tab action buttons."""
    btn = QPushButton(icon_text)
    btn.setToolTip(tooltip)
    btn.setFont(QFont("Segoe UI", 12))
    btn.setFixedSize(40, 36)
    btn.setStyleSheet(
        "QPushButton{background-color:#2d2d30;color:white;"
        "font-weight:bold;font-size:16px;border:1px solid #555555;"
        "border-radius:4px;min-width:40px;max-width:40px;"
        "min-height:36px;max-height:36px;}"
        "QPushButton:hover{background-color:#3e3e42;border-left-color:#007acc;}"
        "QPushButton:pressed{background-color:#007acc;}"
        "QPushButton:disabled{background-color:#2d2d30;color:#555555;border-color:#444444;}"
    )
    return btn


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

class _PlainPasteTextEdit(QTextEdit):
    """QTextEdit that always pastes as plain text to avoid spurious newlines."""

    def insertFromMimeData(self, source):  # noqa: N802
        self.insertPlainText(source.text())


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
        # RPGMaker Ace state
        self._ace_encrypted: bool = False
        self._ace_json_dir: str = ""     # <game_root>/JSON/ — used as _data_path for Ace
        self._ace_rvdata_dir: str = ""   # <game_root>/Data/ with rvdata2 files
        self._p2_loading_config: bool = False
        self._p2_auto_apply_timer: QTimer | None = None
        self._syncing_file_checks: bool = False
        self._import_buttons: list[QPushButton] = []
        self._current_step_index: int = 0
        self._last_import_signature: tuple[str, ...] | None = None
        self._pending_import_signature: tuple[str, ...] | None = None

        self._init_ui()

    # ───────────────────────────────── UI setup ──────────────────────────────

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Splitter: left=steps, right=log
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(1)
        splitter.setStyleSheet("QSplitter::handle{background:#3a3a3a;}")

        # ---- Left: tabbed step panels ----
        _SCROLL_STYLE = (
            "QScrollArea{border:none;background-color:transparent;}"
            "QScrollBar:vertical{background:#252526;width:10px;border:none;}"
            "QScrollBar::handle:vertical{background:#555555;border-radius:5px;min-height:20px;}"
            "QScrollBar::handle:vertical:hover{background:#007acc;}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}"
        )

        self._step_tabs = QTabWidget()
        self._step_tabs.setStyleSheet("""
            QTabWidget::pane {
                border: none;
                background-color: #1e1e1e;
            }
            QTabWidget::tab-bar {
                alignment: left;
            }
            QTabBar {
                background-color: #252526;
            }
            QTabBar::tab {
                background-color: #252526;
                color: #7a7a7a;
                padding: 9px 18px;
                border: none;
                border-right: 1px solid #3a3a3a;
                font-size: 12px;
                min-width: 90px;
            }
            QTabBar::tab:selected {
                background-color: #1e1e1e;
                color: #e0e0e0;
                font-weight: bold;
                border-top: 2px solid #007acc;
            }
            QTabBar::tab:hover:!selected {
                background-color: #2d2d30;
                color: #cccccc;
            }
        """)

        _tab_defs = [
            ("0  Project",      self._build_step0),
            ("1  Pre-process",  self._build_step1_preprocess),
            ("2  Speaker",      self._build_step2_speaker),
            ("3  Glossary",     self._build_step3_glossary),
            ("4  TL Phase 1",   self._build_step4_translation),
            ("5  TL Phase 2",   self._build_step5_tl_phase2),
            ("6  Plugins.js",   self._build_step6_plugins_js),
            ("7  Export",       self._build_step7_export),
        ]

        for tab_label, builder in _tab_defs:
            # Each tab: outer page → scroll area → inner content widget
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

            # ── Navigation footer ──────────────────────────────────────────
            nav = QWidget()
            nav.setStyleSheet(
                "QWidget{background-color:#252526;"
                "border-top:1px solid #3a3a3a;}"
            )
            nav_layout = QHBoxLayout(nav)
            nav_layout.setContentsMargins(16, 6, 16, 6)
            nav_layout.setSpacing(8)

            tab_idx = len(self._step_tabs)  # current tab index (before addTab)

            if tab_idx > 0:
                back_btn = _make_btn("← Back", "#3a3a3a")
                back_btn.setFixedWidth(100)
                _idx = tab_idx  # capture for lambda
                back_btn.clicked.connect(
                    lambda _checked, i=_idx: self._step_tabs.setCurrentIndex(i - 1)
                )
                nav_layout.addWidget(back_btn)

            nav_layout.addStretch()

            if tab_idx < len(_tab_defs) - 1:
                next_btn = _make_btn("Next →", "#007acc")
                next_btn.setFixedWidth(100)
                _idx = tab_idx  # capture for lambda
                _lbl = tab_label  # original label without checkmark
                next_btn.clicked.connect(
                    lambda _checked, i=_idx, lbl=_lbl: (
                        self._step_tabs.setTabText(i, "✓  " + lbl),
                        self._step_tabs.setCurrentIndex(i + 1),
                    )
                )
                nav_layout.addWidget(next_btn)

            page_layout.addWidget(nav)
            self._step_tabs.addTab(page, tab_label)

        self._step_tabs.currentChanged.connect(self._on_step_tab_changed)
        splitter.addWidget(self._step_tabs)

        # ---- Right: log area ----
        log_panel = QWidget()
        lp_layout = QVBoxLayout(log_panel)
        lp_layout.setContentsMargins(0, 0, 0, 0)
        lp_layout.setSpacing(0)

        log_header = QLabel("  ▸  Workflow Log")
        log_header.setStyleSheet(
            "background-color:#252526;color:#9d9d9d;font-size:11px;font-weight:bold;"
            "padding:7px 10px;border-bottom:1px solid #3a3a3a;"
            "letter-spacing:0.5px;"
        )
        lp_layout.addWidget(log_header)

        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setFont(QFont("Consolas", 9))
        self.log_area.setStyleSheet(
            "QTextEdit{background-color:#1e1e1e;color:#c8c8c8;"
            "border:none;padding:10px;"
            "selection-background-color:#264f78;}"
        )
        lp_layout.addWidget(self.log_area)

        clear_btn = _make_btn("Clear Log", "#3a3a3a")
        clear_btn.setStyleSheet(
            "QPushButton{background-color:#252526;color:#6a6a6a;"
            "border:none;border-top:1px solid #3a3a3a;"
            "padding:5px 12px;font-size:11px;font-weight:normal;"
            "font-family:'Segoe UI','Arial',sans-serif;}"
            "QPushButton:hover{background-color:#2d2d30;color:#9d9d9d;}"
            "QPushButton:pressed{color:#cccccc;}"
        )
        clear_btn.clicked.connect(self.log_area.clear)
        lp_layout.addWidget(clear_btn)

        splitter.addWidget(log_panel)
        splitter.setSizes([900, 200])

        root.addWidget(splitter)
        self.setLayout(root)
        self._apply_theme()
        self._detected_on_show: bool = False  # guard: only auto-detect once per new folder

    # ── Tab visibility ──────────────────────────────────────────────────────

    def showEvent(self, event):
        """Trigger folder detection the first time this tab is shown (or after a new folder is set)."""
        super().showEvent(event)
        if not self._detected_on_show and self._setting("last_game_folder", ""):
            self._detected_on_show = True
            QTimer.singleShot(100, self._detect_folder)

    def eventFilter(self, obj, event):
        """Toggle workflow file checks when clicking a row outside the checkbox."""
        try:
            if (
                obj is self.file_list.viewport()
                and event.type() == QEvent.MouseButtonRelease
                and event.button() == Qt.LeftButton
            ):
                item = self.file_list.itemAt(event.pos())
                if item is None:
                    return False

                # Let native checkbox clicks handle their own checked state.
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

    def _on_step_tab_changed(self, index: int):
        """Refresh config-backed controls when their workflow page is shown."""
        previous_index = self._current_step_index
        self._current_step_index = index

        if previous_index == 0 and index != 0:
            self._auto_import_if_needed()

        if index == 5:
            self._populate_p2_checkboxes()

    def _register_import_button(self, button: QPushButton) -> None:
        self._import_buttons.append(button)

    def _set_import_buttons_enabled(self, enabled: bool) -> None:
        for button in self._import_buttons:
            button.setEnabled(enabled)

    def _apply_theme(self):
        """Apply a unified dark-theme stylesheet to all standard controls."""
        self.setStyleSheet("""
            QLineEdit {
                background-color: #3c3c3c;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 4px 8px;
                color: #cccccc;
                font-size: 13px;
            }
            QLineEdit:focus {
                border-color: #007acc;
            }
            QLineEdit:disabled {
                background-color: #2d2d30;
                color: #666666;
            }
            QLineEdit::placeholder {
                color: #606060;
            }
            QSpinBox {
                background-color: #3c3c3c;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 3px 6px;
                color: #cccccc;
                font-size: 13px;
            }
            QSpinBox:focus {
                border-color: #007acc;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                background-color: #2d2d30;
                border: none;
                width: 18px;
            }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                background-color: #007acc;
            }
            QCheckBox {
                color: #cccccc;
                font-size: 13px;
                spacing: 7px;
            }
            QCheckBox::indicator {
                width: 14px;
                height: 14px;
                border: 1px solid #555555;
                border-radius: 3px;
                background-color: #3c3c3c;
            }
            QCheckBox::indicator:checked {
                background-color: #007acc;
                border-color: #007acc;
            }
            QCheckBox::indicator:hover {
                border-color: #007acc;
            }
            QCheckBox::indicator:disabled {
                background-color: #2d2d30;
                border-color: #444444;
            }
        """)

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

        browse_btn = _make_icon_btn("📁", "Browse for a game project folder")
        browse_btn.clicked.connect(self._browse_folder)
        row0.addWidget(browse_btn)

        layout.addLayout(row0)

        # Detected info
        self.detected_label = QLabel("No folder detected yet.")
        self.detected_label.setStyleSheet(
            "color:#6a9a6a;font-size:13px;padding:4px 8px;"
            "background-color:#1f2b1f;border:1px solid #2a4a2a;"
            "border-radius:4px;margin:4px 0;"
        )
        layout.addWidget(self.detected_label)

        # File list
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

        # Action row
        row1 = QHBoxLayout()
        row1.setSpacing(6)
        select_all_btn = _make_icon_btn("✓", "Select all importable files")
        select_all_btn.clicked.connect(self._select_all_files)
        row1.addWidget(select_all_btn)

        deselect_all_btn = _make_icon_btn("✗", "Deselect all files")
        deselect_all_btn.clicked.connect(self._deselect_all_files)
        row1.addWidget(deselect_all_btn)

        sel_core = _make_icon_btn("◆", "Core Only: select database files and deselect maps")
        sel_core.setToolTip("Select only core database files; deselect map files")
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

    # ── Step 3: Vocab / Glossary ────────────────────────────────────────────

    # ── Copilot prompt templates ────────────────────────────────────────────

    _SPEAKER_PROMPT = (
        "You are an expert RPGMaker MV/MZ analyst helping configure a Japanese game translation tool.\n"
        "\n"
        "<task>\n"
        "Examine the game's event files (Map*.json, CommonEvents.json, Troops.json) and determine "
        "which speaker name format(s) the game uses. Output flag recommendations based on what you find.\n"
        "</task>\n"
        "\n"
        "<context>\n"
        "Code 101 opens the text window. Code 401 is a dialogue line. Multiple 401s in a row form "
        "one message box. The translation tool needs to know how character names appear in the event "
        "data so it can extract and translate them correctly.\n"
        "</context>\n"
        "\n"
        "--- attach your game files here before continuing ---\n"
        "\n"
        "<always_on_formats>\n"
        "The following formats are detected and translated automatically — no flag is needed. "
        "If the game uses any of these, do NOT enable a flag for lines matching that exact pattern. "
        "However, continue scanning to check whether other speakers use a flag-requiring pattern.\n"
        "\n"
        "## How dialogue commands work\n"
        "\n"
        "Code 101 opens the text window. Code 401 is a dialogue line. "
        "Multiple 401s in a row form one message box.\n"
        "\n"
        "## IMPORTANT — Always-on formats (NO FLAG NEEDED, never enable any flag for these)\n"
        "\n"
        "The following formats are detected and translated automatically. "
        "If the game uses ANY of these, do NOT enable any flag for lines matching that pattern. "
        "However, **DO NOT STOP** — continue checking whether other speakers in the same game "
        "use a different format that requires a flag.\n"
        "\n"
        "\n"
        "  101 param[4] name       { \"code\": 101, \"parameters\": [\"\", 0, 2, 2, \"るな\"] }\n"
        "  \\\\n<Name> or \\\\k<Name>   escape code with ANGLE BRACKETS anywhere inside a 401 line\n"
        "  【Name】                  alone on a line, or 【Name】dialogue on the same line\n"
        "  [Name]                  alone on a line, or [Name]dialogue on the same line\n"
        "  \\\\c[N]Name\\\\c[0]       color-wrapped name on its own 401 line\n"
        "  Name：                   line ending with a full-width colon\n"
        "\n"
        "## CRITICAL — \\\\N[X] / \\\\n[X] (square bracket + number) is NOT a speaker format\n"
        "\n"
        "  \\\\N[ActorID] and \\\\n[ActorID] (e.g. \\\\N[1], \\\\n[2]) are RPGMaker actor variable\n"
        "  substitution codes. They expand to an actor's name at runtime, but the translation tool\n"
        "  handles them purely as text substitution during translation — they are NEVER treated as\n"
        "  a speaker name tag.\n"
        "\n"
        "  A 401 line containing ONLY \\\\N[X], or narration text that embeds \\\\N[X] (e.g.\n"
        "  \"ローターが\\\\N[1]の乳首に装着される！\"), does NOT match any always-on speaker format.\n"
        "  Do NOT count \\\\N[X] / \\\\n[X] codes as always-on speaker detection hits.\n"
        "\n"
        "  If a game's ONLY speaker indicator is a standalone \\\\N[X] line followed by dialogue,\n"
        "  check whether FIRSTLINESPEAKERS would catch it (the standalone line must be < 40 chars\n"
        "  AND contain at least one Japanese character — a bare \\\\N[1] with no Japanese text does\n"
        "  NOT qualify for FIRSTLINESPEAKERS either).\n"
        "</always_on_formats>\n"
        "\n"
        "<flags>\n"
        "Only enable these when at least some speakers do NOT use an always-on format.\n"
        "\n"
        "<flag name=\"INLINE401SPEAKERS\">\n"
        "The speaker name is embedded at the start of a 401 line directly before 「, "
        "with no intervening markup or brackets.\n"
        "<example>\n"
        "{ \"code\": 401, \"parameters\": [\"エレナ「今日は晴れですね。\"] }\n"
        "</example>\n"
        "Enable if the game has dialogue lines matching this pattern.\n"
        "</flag>\n"
        "\n"
        "<flag name=\"FIRSTLINESPEAKERS\">\n"
        "The very first 401 in a message group is a short standalone name (under 40 chars), "
        "and the following 401 starts with 「 \" ( （ * [. This commonly appears for NPCs even "
        "in games where the protagonist uses an always-on format. The 101 command for these "
        "lines typically has an empty face image (parameters[0] == \"\").\n"
        "<example>\n"
        "{ \"code\": 101, \"parameters\": [\"\", 0, 0, 2] }\n"
        "{ \"code\": 401, \"parameters\": [\"衛兵さん\"] }        ← plain name, no color or brackets\n"
        "{ \"code\": 401, \"parameters\": [\"「……起きたか」\"] }\n"
        "</example>\n"
        "Enable if ANY speakers in the game use this pattern, even if others use an always-on format.\n"
        "</flag>\n"
        "\n"
        "<flag name=\"FACENAME101\" priority=\"last_resort\">\n"
        "Enable ONLY when: (a) the game has no always-on format, AND (b) neither INLINE401SPEAKERS "
        "nor FIRSTLINESPEAKERS applies, AND (c) the 101 code has a face image filename in "
        "parameters[0] while parameters[4] is empty.\n"
        "<example>\n"
        "{ \"code\": 101, \"parameters\": [\"face_alice\", 0, 0, 2, \"\"] }\n"
        "</example>\n"
        "If you recommend this, you MUST list every unique face filename found in parameters[0] "
        "of code 101 across all attached files.\n"
        "</flag>\n"
        "</flags>\n"
        "\n"
        "<instructions>\n"
        "Follow these steps in order:\n"
        "\n"
        "1. Scan ALL 101→401 blocks across the sample files.\n"
        "   (a) List every always-on pattern found — these need no flag.\n"
        "   (b) List every flag-requiring pattern found separately.\n"
        "   A game may use both simultaneously (e.g. protagonist via \\\\c[N]Name\\\\c[0], "
        "NPCs via plain standalone name lines). Do not stop after finding one pattern.\n"
        "\n"
        "2. For each flag-requiring pattern from step 1:\n"
        "   - INLINE401SPEAKERS → ENABLE if name「 inline pattern exists\n"
        "   - FIRSTLINESPEAKERS → ENABLE if plain standalone name line exists\n"
        "   Both may be enabled together if both patterns exist.\n"
        "\n"
        "3. Only if steps 1–2 found no flag-requiring patterns AND no always-on format "
        "→ consider FACENAME101.\n"
        "</instructions>\n"
        "\n"
        "<output_format>\n"
        "Provide exactly four sections:\n"
        "\n"
        "1. Patterns detected — one entry per speaker type (protagonist, NPCs, signs/narration)\n"
        "2. Flag decisions:\n"
        "     INLINE401SPEAKERS : ENABLE / SKIP — <one-line reason>\n"
        "     FIRSTLINESPEAKERS : ENABLE / SKIP — <one-line reason>\n"
        "     FACENAME101       : ENABLE / SKIP — <one-line reason>\n"
        "3. A short concrete example from the actual files for each detected pattern\n"
        "4. (Only if FACENAME101 is ENABLE) Every unique face filename from parameters[0] of code 101\n"
        "</output_format>\n"
    )

    _PROMPT_GLOSSARY = (
        "You are an expert Japanese RPGMaker game analyst building a translation glossary.\n"
        "\n"
        "<task>\n"
        "Extract named characters and lore-specific worldbuilding terms from this game's data files. "
        "Produce a structured glossary in the exact format specified below. It will be loaded directly "
        "into a translation tool, so strict format compliance is required.\n"
        "</task>\n"
        "\n"
        "--- attach your game data files here before continuing ---\n"
        "\n"
        "<file_strategy>\n"
        "Map files and CommonEvents.json can be extremely large. Do NOT read them sequentially — "
        "you will hit context limits. Use this strategy:\n"
        "\n"
        "1. Read these small DB files IN FULL first — richest source of names, always small:\n"
        "   Actors.json is mandatory for major character vocab. Use it as the canonical source "
        "for actor IDs, Japanese names, nicknames, profiles, and \\N[n] name mappings.\n"
        "   Then read Classes.json, Troops.json, Skills.json, Items.json,\n"
        "   Armors.json, Weapons.json, States.json, System.json\n"
        "\n"
        "2. For large files (CommonEvents.json, Map*.json), SEARCH (grep) instead of reading "
        "sequentially. Prioritise dialogue commands because they are the best evidence for "
        "character voice:\n"
        "   - Code 401 dialogue lines, plus nearby code 101 speaker/name parameters\n"
        "   - Code 405 scrolling text when present\n"
        "   - Speaker patterns such as 【Name】, [Name], Name：, \\\\n<Name>, and \\\\k<Name>\n"
        "   - Capitalised katakana clusters or kanji compound proper nouns in dialogue/parameters fields\n"
        "   Scan Map001.json through Map010.json at most — early maps have the most story content.\n"
        "\n"
        "3. Stop once you stop finding new names or terms. Do not pad the output.\n"
        "</file_strategy>\n"
        "\n"
        "<rules>\n"
        "Apply to both sections:\n"
        "- Separator: use a plain hyphen-minus (-). Never use — or –. "
        "The translation tool only recognises the plain hyphen.\n"
        "- Descriptions must be entirely in English. Refer to other characters by English name only "
        "(write 'her sister Ruin was kidnapped', not 'her sister ルイン was kidnapped').\n"
        "- Never give two spelling options (e.g. 'Sylfia / Sylphia' is wrong). Commit to one translation.\n"
        "\n"
        "# Game Characters — rules:\n"
        "- If a <known_speakers> list was provided, output entries for those names, then cross-check "
        "Actors.json for major named actors that should also be included. Skip unnamed NPCs, generic "
        "enemies, and narration-only entries.\n"
        "- If no list was provided, discover named characters from the files, but still skip "
        "unnamed NPCs and generic enemy types.\n"
        "- For each character include: gender, role, speech register, personality, and whether "
        "the name is player-chosen (check Actors.json ID 1).\n"
        "- Any actor in Actors.json with a real name should get a full # Game Characters entry, "
        "not only a \\N[n] placeholder mapping. If events reference \\N[3] or [EnglishName], "
        "resolve it through Actors.json ID 3 and preserve the full character context.\n"
        "- Event references are supporting evidence for personality/speech, but they must not "
        "replace actor-database discovery. Do not miss major characters just because they appear "
        "primarily in Actors.json.\n"
        "\n"
        "# Worldbuilding Terms — rules:\n"
        "- Include: faction/organisation names, locations mentioned in dialogue but not on maps, "
        "unique magic systems, lore titles, recurring in-universe concepts.\n"
        "- Exclude: skill names, item names, weapon names, armour names (the tool handles those). "
        "Skip generic RPG words (\u30dd\u30fc\u30b7\u30e7\u30f3, \u30ec\u30d9\u30eb, \u30b9\u30c6\u30fc\u30bf\u30b9, etc.). "
        "Do not repeat character names here.\n"
        "</rules>\n"
        "\n"
        "<output_format>\n"
        "Output EXACTLY two sections with these headers. Do not add any preamble, explanation, "
        "or text outside the entries.\n"
        "\n"
        "# Game Characters\n"
        "# Worldbuilding Terms\n"
        "\n"
        "Entry format:  Japanese (English) - description\n"
        "\n"
        "<example>\n"
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
        "</example>\n"
        "</output_format>\n"
    )

    _WRAP_PROMPT = (
        "You are an expert RPGMaker MV/MZ configuration analyst.\n"
        "\n"
        "<task>\n"
        "Calculate the correct text-wrap width settings for a Japanese-to-English RPGMaker MV/MZ "
        "translation tool. The tool wraps translated English using character-count limits (not pixels). "
        "I need three values: width, listWidth, and noteWidth.\n"
        "</task>\n"
        "\n"
        "--- attach System.json and js/plugins.js here before continuing ---\n"
        "\n"
        "<instructions>\n"
        "1. Read screenWidth and fontSize from System.json.\n"
        "   Check js/plugins.js for any MessageCore or Window plugin that overrides these values.\n"
        "2. For each window type, estimate its pixel width, subtract ~48px padding, then calculate:\n"
        "   chars = floor(content_px / (font_size × 0.58))\n"
        "   - width:      main dialogue/message box (Show Text) — typically full screen width\n"
        "   - listWidth:  item/skill/help description windows — typically full or half screen width\n"
        "   - noteWidth:  database note fields — typically the narrowest pane (~40–50% screen width)\n"
        "3. If font size is above 26px and reducing it would meaningfully increase characters per line, "
        "note where to change it (System.json or the relevant plugin parameter).\n"
        "</instructions>\n"
        "\n"
        "<output_format>\n"
        "Output only the final values — do not show calculations:\n"
        "\n"
        "```\n"
        "width=<N>\n"
        "listWidth=<N>\n"
        "noteWidth=<N>\n"
        "fontSize=<N>   # or: no change needed\n"
        "```\n"
        "\n"
        "Followed by one sentence of assumptions if anything was estimated.\n"
        "</output_format>\n"
    )

    _PLUGINS_JS_TRANSLATE_PROMPT = (
        "You are an expert RPGMaker MV/MZ localisation engineer.\n"
        "\n"
        "<task>\n"
        "Translate visible Japanese strings inside js/plugins.js without breaking any game logic "
        "or plugin functionality. A vocab.txt glossary is attached — use it as your primary reference. "
        "Any name or term that appears in the glossary must be translated exactly as shown there.\n"
        "</task>\n"
        "\n"
        "--- attach js/plugins.js and vocab.txt here before continuing ---\n"
        "\n"
        "\n"
        "<translate>\n"
        "Only translate string values directly shown to the player at runtime:\n"
        "- Menu/button labels in-game UI (e.g. 決定, キャンセル)\n"
        "- Scene/window title text (e.g. アイテム, スキル, 装備)\n"
        "- In-game popup, tooltip, or notification messages\n"
        "- Default NPC names or pronouns used in UI display\n"
        "- Help or description text shown in help windows\n"
        "- Battle log messages or status effect messages\n"
        "</translate>\n"
        "\n"
        "<do_not_translate>\n"
        "Translating the following WILL BREAK THE GAME:\n"
        "\n"
        "1. Plugin parameter keys (object property names).\n"
        "   { \"CommandName\": \"セーブ\" } → translate セーブ but NOT CommandName\n"
        "\n"
        "2. Strings used as internal identifiers or lookup keys:\n"
        "   - Switch/variable names matching System.json entries\n"
        "   - Actor, skill, item, weapon, armour names used as keys inside other plugin parameters\n"
        "   - Strings passed as plugin command arguments that the engine looks up\n"
        "\n"
        "3. File paths, filenames, URLs, colour codes, font names, icon indices.\n"
        "   (e.g. img/faces/Actor1 or #ffffff)\n"
        "\n"
        "4. Plugin names and script identifiers:\n"
        "   - The \"name\" property at the top of each plugin block (e.g. { \"name\": \"YEP_CoreEngine\" })\n"
        "   - Function identifiers, class names, JS event names\n"
        "\n"
        "5. Any string in the game data files (Actors.json, Skills.json, Items.json, etc.) that is "
        "also used as a lookup key in the plugin — changing it here would desync it from the data file.\n"
        "\n"
        "6. Boolean strings, numeric strings, regex patterns.\n"
        "</do_not_translate>\n"
        "\n"
        "<safety_check>\n"
        "Before translating any string, confirm all three are true:\n"
        "- It is displayed directly to the player as visible text\n"
        "- It is purely a UI label, not used as a key anywhere else\n"
        "- Nothing in the codebase compares this exact string to another value\n"
        "When in doubt, skip it — untranslated Japanese is better than a broken game.\n"
        "</safety_check>\n"
        "\n"
        "<output_format>\n"
        "Provide the translated file as a complete replacement of js/plugins.js. Only change the "
        "string values identified above. Preserve all original formatting, indentation, comments, and structure.\n"
        "\n"
        "After the file, output a summary:\n"
        "\n"
        "### Translations Made\n"
        "  Plugin: <plugin name>\n"
        "  Parameter: <parameter key>\n"
        "  Before: <original Japanese>\n"
        "  After:  <English translation>\n"
        "\n"
        "### Skipped (Ambiguous or Internal)\n"
        "List any Japanese strings you detected but did not translate, with a one-line reason.\n"
        "</output_format>\n"
    )

    _ACE_SCRIPTS_TRANSLATE_PROMPT = (
        "You are an expert RPGMaker VX Ace (Ruby) localisation engineer.\n"
        "\n"
        "<task>\n"
        "Translate visible Japanese strings inside the game's Ruby scripts (ace_json/scripts/*.rb) "
        "without breaking any game logic or script functionality. A vocab.txt glossary is attached — "
        "use it as your primary reference. Any name or term in the glossary must be translated exactly as shown.\n"
        "</task>\n"
        "\n"
        "--- attach the .rb script files and vocab.txt here before continuing ---\n"
        "\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "## WHAT TO TRANSLATE\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "\n"
        "Only translate string literals that are directly shown to the player at runtime.\n"
        "These typically appear as:\n"
        "  - Strings passed to msgbox, msgbox_p, print, p\n"
        "  - Labels and text in Window or Scene classes rendered to screen\n"
        "  - draw_text / draw_item calls with a Japanese string literal\n"
        "  - Default UI label text (menu names, button labels, status window text)\n"
        "  - Battle log messages, notifications, popup strings\n"
        "  - Help or description text shown in help windows\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "## WHAT MUST NOT BE TRANSLATED\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "\n"
        "CRITICAL — translating the following will break the game:\n"
        "\n"
        "  1. Strings used as hash keys, method names, or symbol equivalents.\n"
        "     Example: vocab[\"HP\"] = \"体力\"  \u2192  translate \"体力\" but NOT the key \"HP\"\n"
        "\n"
        "  2. Strings used as internal identifiers compared with == or used in case/when:\n"
        "     - Actor/class/skill/item names used as lookup strings\n"
        "     - Script-internal state names or flag strings\n"
        "     Example: if type == \"スキル\"  \u2192  do NOT translate \"スキル\"\n"
        "\n"
        "  3. File paths, filenames, font names, colour strings, URLs.\n"
        "\n"
        "  4. Regular expressions, format strings used with sprintf or % operator\n"
        "     where the placeholders must stay in the same position.\n"
        "     (You may translate the human-readable parts but keep %s / %d / %1 etc intact.)\n"
        "\n"
        "  5. Script class names, module names, method names, constants.\n"
        "\n"
        "  6. Any string that is read back elsewhere in the scripts with an exact match.\n"
        "\n"
        "<safety_check>\n"
        "Before translating any string, confirm all three are true:\n"
        "- It is displayed directly to the player as visible text\n"
        "- It is purely a display string, not compared or looked up anywhere\n"
        "- Changing it would break no conditional logic or data lookup\n"
        "When in doubt, skip it — untranslated Japanese is better than a broken game.\n"
        "</safety_check>\n"
        "\n"
        "<output_format>\n"
        "For each .rb file that needed changes, provide the full translated file content. "
        "Only change string values identified as safe. "
        "Preserve all Ruby syntax, indentation, comments, and structure exactly.\n"
        "\n"
        "After all files, output a summary:\n"
        "\n"
        "### Translations Made\n"
        "  File:   <script filename.rb>\n"
        "  Before: <original Japanese>\n"
        "  After:  <English translation>\n"
        "\n"
        "### Skipped (Ambiguous or Internal)\n"
        "List any Japanese strings you detected but did not translate, with a one-line reason.\n"
        "</output_format>\n"
    )

    _PLUGIN_PROMPT = (
        "You are an expert RPGMaker MV/MZ event system analyst.\n"
        "\n"
        "<task>\n"
        "Audit several optional event code types and report: (a) which contain player-visible "
        "Japanese text that needs translation, and (b) for code 122, exactly which variable ID "
        "ranges carry display text versus internal keys.\n"
        "</task>\n"
        "\n"
        "--- attach Actors.json, CommonEvents.json, Troops.json, Map*.json, and js/plugins.js here ---\n"
        "\n"
        "<actor_context>\n"
        "Read Actors.json in full before auditing event commands. Use it to resolve actor IDs, "
        "\\N[n] references, and code 320/324/325 targets. If you see an event reference to a "
        "major actor whose full character vocab is missing or only appears as a placeholder "
        "mapping like \\N[3] (Keimi), report that Actors.json should be included in the glossary "
        "build and that a full # Game Characters entry is needed.\n"
        "</actor_context>\n"
        "\n"
        "<audit_1 code=\"122\">\n"
        "Code 122 — Control Variables — which variable IDs carry display text\n"
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
        "</audit_1>\n"
        "\n"
        "<audit_2>\n"
        "Plugin codes with visible text — 357 / 356 / 355-655 / 657 / 320 / 324 / 325 / 108\n"
        "For each code type below, scan all events and report whether any instance contains "
        "Japanese text visible to the player at runtime.\n"
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
        "  info:, ActiveMessage:, event_text, Menu Name, text_indicator, NW名前指定\n"
        "Do any 108 entries matching those patterns have Japanese visible to the player?\n"
        "If yes: ENABLE CODE108 and list the patterns found. If no: SKIP CODE108.\n"
        "</audit_2>\n"
        "\n"
        "<output_format>\n"
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
        "### GUI Action Summary\n"
        "\n"
        "After all audit sections above, output this final block to configure the GUI:\n"
        "\n"
        "ENABLE CODES     : <comma-separated CODE* keys to check, e.g. CODE357, CODE356>\n"
        "SKIP CODES       : <codes that have no visible text>\n"
        "357 PLUGINS      : <comma-separated HEADER_MAPPINGS_357 keys to enable>\n"
        "355/655 PATTERNS : <comma-separated PATTERNS_355655 keys to enable>\n"
        "122 VAR RANGE    : min=<N>, max=<M>\n"
        "\n"
        "If a field has nothing to fill in, write NONE.\n"
        "</output_format>\n"
    )

    # ── Step 1 (Optional): Pre-process ────────────────────────────────

    def _build_step1_preprocess(self, layout: QVBoxLayout):
        header_row = QHBoxLayout()
        header_row.addWidget(_make_section_label("Step 1 (Optional) — Pre-process"))
        opt_badge = QLabel("optional")
        opt_badge.setStyleSheet(
            "color:#7a7a7a;font-size:11px;border:1px solid #3c3c3c;"
            "padding:1px 8px;border-radius:8px;margin-left:8px;"
            "background-color:#252526;"
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
        hint.setStyleSheet("color:#9d9d9d;font-size:13px;padding-bottom:6px;")
        collapse_layout.addWidget(hint)

        tasks_box = QGroupBox()
        tasks_box.setStyleSheet("QGroupBox{border:none;margin:0;padding:4px 0;}")
        tb = QVBoxLayout(tasks_box)
        tb.setSpacing(10)
        collapse_layout.addWidget(tasks_box)

        # ---- Task A: dazedformat -----------------------------------------
        ta_title = QLabel("A — Format JSON files (dazedformat)")
        ta_title.setStyleSheet("color:#4ec9b0;font-size:13px;font-weight:bold;")
        tb.addWidget(ta_title)
        self._pp_dazedformat_title = ta_title
        ta = QWidget()
        ta.setObjectName("tbox")
        ta.setStyleSheet(self._task_box_style())
        ta_inner = QVBoxLayout(ta)
        ta_inner.setContentsMargins(10, 8, 10, 8)
        ta_inner.setSpacing(4)
        ta_desc = QLabel(
            "Normalises all JSON files in the game's data folder by round-tripping them "
            "through <code>json.load / json.dump</code>. "
            "Bundled — no external install required."
        )
        ta_desc.setTextFormat(Qt.RichText)
        ta_desc.setWordWrap(True)
        ta_desc.setStyleSheet("color:#9d9d9d;font-size:13px;")
        ta_inner.addWidget(ta_desc)
        ta_path_row = QHBoxLayout()
        ta_path_row.addWidget(QLabel("Data folder:"))
        self.pp_data_path_label = QLabel("(detect a project folder first)")
        self.pp_data_path_label.setStyleSheet("color:#7a7a7a;font-size:13px;")
        ta_path_row.addWidget(self.pp_data_path_label, 1)
        ta_inner.addLayout(ta_path_row)
        ta_btn_row = QHBoxLayout()
        run_dazed = _make_btn("►  Run dazedformat", "#555")
        run_dazed.setFixedWidth(180)
        run_dazed.clicked.connect(self._run_dazedformat)
        ta_btn_row.addWidget(run_dazed)
        ta_btn_row.addStretch()
        ta_inner.addLayout(ta_btn_row)
        tb.addWidget(ta)
        self._pp_dazedformat_box = ta

        # ---- Task B: prettier on plugins.js
        tb_box_title = QLabel("B — Format plugins.js with Prettier")
        tb_box_title.setStyleSheet("color:#4ec9b0;font-size:13px;font-weight:bold;")
        tb.addWidget(tb_box_title)
        self._pp_plugins_js_title = tb_box_title
        tb_box = QWidget()
        tb_box.setObjectName("tbox")
        tb_box.setStyleSheet(self._task_box_style())
        tb_inner = QVBoxLayout(tb_box)
        tb_inner.setContentsMargins(10, 8, 10, 8)
        tb_inner.setSpacing(4)
        tb_desc = QLabel(
            "Formats plugins.js using <code>jsbeautifier</code> (pure Python — no Node.js required) "
            "so it is human-readable before editing or inspection."
        )
        tb_desc.setTextFormat(Qt.RichText)
        tb_desc.setWordWrap(True)
        tb_desc.setStyleSheet("color:#9d9d9d;font-size:13px;")
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
        run_prettier = _make_btn("►  Format plugins.js", "#555")
        run_prettier.setFixedWidth(180)
        run_prettier.clicked.connect(self._run_prettier)
        tb_btn_row.addWidget(run_prettier)
        tb_btn_row.addStretch()
        tb_inner.addLayout(tb_btn_row)
        tb.addWidget(tb_box)
        self._pp_plugins_js_box = tb_box

        # ---- Task C: copy gameupdate/ -----------------------------------
        tc_title = QLabel("C — Apply gameupdate/ patch files")
        tc_title.setStyleSheet("color:#4ec9b0;font-size:13px;font-weight:bold;")
        tb.addWidget(tc_title)
        tc = QWidget()
        tc.setObjectName("tbox")
        tc.setStyleSheet(self._task_box_style())
        tc_inner = QVBoxLayout(tc)
        tc_inner.setContentsMargins(10, 8, 10, 8)
        tc_inner.setSpacing(4)
        tc_desc = QLabel(
            "Copies everything from the <code>gameupdate/</code> folder "
            "into the game\'s root folder, overwriting existing files."
        )
        tc_desc.setTextFormat(Qt.RichText)
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
        run_all_btn = _make_btn("►►  Run All 3 Tasks", "#007acc")
        run_all_btn.setFixedWidth(180)
        run_all_btn.setToolTip("Run dazedformat, prettier, and gameupdate copy in sequence")
        run_all_btn.clicked.connect(self._run_all_preprocess)
        tc_btn_row.addWidget(run_all_btn)
        tc_btn_row.addStretch()
        tc_inner.addLayout(tc_btn_row)
        tb.addWidget(tc)

        layout.addWidget(collapse_widget)

        def _toggle_preprocess(expanded: bool):
            toggle_btn.setText("▼" if expanded else "►")
            collapse_widget.setVisible(expanded)
        toggle_btn.toggled.connect(_toggle_preprocess)

    @staticmethod
    def _task_box_style() -> str:
        return (
            "QWidget#tbox{"
            "background-color:#252526;"
            "border:1px solid #3c3c3c;"
            "border-radius:6px;}"
        )

    @staticmethod
    def _checkbox_box_style() -> str:
        """Style for checkbox list container widgets."""
        return (
            "QWidget#cbbox{"
            "background-color:#252526;"
            "border:1px solid #3c3c3c;"
            "border-radius:6px;}"
            "QWidget{"
            "background-color:#252526;"
            "border:none;}"
            "QCheckBox{border:none;background-color:transparent;}"
        )

    def _build_step3_glossary(self, layout: QVBoxLayout):

        layout.addWidget(_make_section_label("Step 3 — Vocab / Glossary"))

        # ---- 3a: Parse Speakers ---------------------------------------------
        parse_title = QLabel("3a — Parse Speakers")
        parse_title.setStyleSheet("color:#4ec9b0;font-size:13px;font-weight:bold;")
        layout.addWidget(parse_title)

        parse_box = QWidget()
        parse_box.setObjectName("tbox")
        parse_box.setStyleSheet(self._task_box_style())
        parse_inner = QVBoxLayout(parse_box)
        parse_inner.setContentsMargins(10, 8, 10, 8)
        parse_inner.setSpacing(4)

        parse_hint = QLabel(
            "Scan all event files (Maps, CommonEvents, Troops) for speaker names and "
            "batch-translate them, then write them into the # Speakers section of vocab.txt.\n"
            "Run this before the full translation so the AI already knows every character name."
        )
        parse_hint.setWordWrap(True)
        parse_hint.setStyleSheet("color:#9d9d9d;font-size:13px;")
        parse_inner.addWidget(parse_hint)

        parse_row = QHBoxLayout()
        parse_speakers_btn = _make_btn("🔍  Parse Speakers", "#5a3a7a")
        parse_speakers_btn.setFixedWidth(180)
        parse_speakers_btn.setToolTip(
            "Sets mode to 'Parse Speakers', selects all event files, and starts the run.\n"
            "No text is translated — only speaker names are collected and written to vocab.txt."
        )
        parse_speakers_btn.clicked.connect(self._run_parse_speakers)
        parse_row.addWidget(parse_speakers_btn)
        parse_row.addStretch()
        parse_inner.addLayout(parse_row)

        layout.addWidget(parse_box)

        # ---- Copilot / Cursor prompt helpers --------------------------------
        prompt_box_title = QLabel("3b — AI Prompt Helpers (Copilot / Cursor)")
        prompt_box_title.setStyleSheet("color:#4ec9b0;font-size:13px;font-weight:bold;")
        layout.addWidget(prompt_box_title)
        prompt_box = QWidget()
        prompt_box.setObjectName("tbox")
        prompt_box.setStyleSheet(self._task_box_style())
        pb_inner = QVBoxLayout(prompt_box)
        pb_inner.setContentsMargins(10, 8, 10, 8)
        pb_inner.setSpacing(4)

        prompt_hint = QLabel(
            "Copy the prompt and paste it into Copilot Chat or Cursor with your game files open. "
            "Paste the AI's output back into vocab.txt."
        )
        prompt_hint.setWordWrap(True)
        prompt_hint.setStyleSheet("color:#9d9d9d;font-size:13px;")
        pb_inner.addWidget(prompt_hint)

        glossary_row = QHBoxLayout()
        copy_glossary_btn = _make_btn("📋  Copy Prompt for Copilot", "#555")
        copy_glossary_btn.setFixedWidth(220)
        copy_glossary_btn.setToolTip("Copy the full glossary discovery prompt to clipboard")
        copy_glossary_btn.clicked.connect(self._copy_glossary_prompt)
        glossary_row.addWidget(copy_glossary_btn)
        glossary_row.addStretch()
        pb_inner.addLayout(glossary_row)

        layout.addWidget(prompt_box)

        # ---- vocab.txt editor -----------------------------------------------
        vocab_title = QLabel("3c — vocab.txt editor")
        vocab_title.setStyleSheet("color:#4ec9b0;font-size:13px;font-weight:bold;")
        layout.addWidget(vocab_title)
        format_hint = QLabel(
            "Format:  Japanese (English) - Gender; role; speech register / personality notes\n"
            "Example:  シロ (Shiro) - Female; protagonist; speaks in a flustered, cute register with feminine speech markers"
        )
        format_hint.setFont(QFont("Consolas", 9))
        format_hint.setStyleSheet(
            "color:#569cd6;background-color:#1a1e2a;border:1px solid #2a3a5a;"
            "padding:5px 10px;border-radius:4px;font-size:13px;"
            "border-left:3px solid #2a6a9a;"
        )
        layout.addWidget(format_hint)

        self.vocab_editor = _PlainPasteTextEdit()
        self.vocab_editor.setMinimumHeight(80)
        self.vocab_editor.setMaximumHeight(160)
        self.vocab_editor.setFont(QFont("Consolas", 9))
        self.vocab_editor.setStyleSheet(
            "QTextEdit{background-color:#252526;color:#d4d4d4;"
            "border:1px solid #3c3c3c;border-radius:4px;padding:8px;"
            "selection-background-color:#264f78;}"
        )
        self._reload_vocab()
        layout.addWidget(self.vocab_editor, 1)

        row = QHBoxLayout()
        row.setSpacing(8)
        save_vocab = _make_btn("💾  Save vocab.txt", "#3a7a3a")
        save_vocab.setFixedWidth(180)
        save_vocab.clicked.connect(self._save_vocab)
        row.addWidget(save_vocab)

        reload_vocab = _make_btn("↺  Reload", "#555")
        reload_vocab.setFixedWidth(110)
        reload_vocab.clicked.connect(self._reload_vocab)
        row.addWidget(reload_vocab)
        row.addStretch()
        layout.addLayout(row)

    def _run_parse_speakers(self):
        """Configure Translation tab for Parse Speakers mode and auto-start."""
        try:
            pw = self.parent_window
            tt = getattr(pw, "translation_tab", None) if pw else None
            if tt is None:
                self._log("❌ Translation tab not found.")
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

            # 2. Set mode to Parse Speakers
            try:
                mc = tt.mode_combo
                idx = mc.findText("Parse Speakers")
                if idx >= 0:
                    mc.setCurrentIndex(idx)
                else:
                    self._log("❌ 'Parse Speakers' mode not available — make sure RPG Maker MV/MZ is selected.")
                    return
            except Exception as exc:
                self._log(f"❌ Could not set Parse Speakers mode: {exc}")
                return

            self._log("")
            self._log("─" * 54)
            self._log("🔍  Switching to Parse Speakers mode…")
            self._log("   Event files selected. Speaker names will be")
            self._log("   collected and written to vocab.txt # Speakers.")
            self._log("─" * 54)

        except Exception as exc:
            self._log(f"❌ _run_parse_speakers error: {exc}")
            return

        # 3. Select event files and auto-start
        self._navigate_to_translation("events", auto_start=True)

    # ── Step 2: Speaker Detection ───────────────────────────────────────────

    def _build_step2_speaker(self, layout: QVBoxLayout):
        layout.addWidget(_make_section_label("Step 2 — Speaker Format Detection"))

        # Import button row
        _IMP_W = 220
        _IMP_H = 36
        _IMP_SS = (
            "QPushButton{{"
            "background-color:{bg};color:white;border:none;"
            "padding:0px;border-radius:4px;font-size:12px;font-weight:bold;"
            "font-family:'Segoe UI',sans-serif;}}"
            "QPushButton:hover{{background-color:{hover};}}"
            "QPushButton:pressed{{background-color:{press};}}"
            "QPushButton:disabled{{background-color:#404040;color:#666666;}}"
        )
        import_row = QHBoxLayout()
        import_row.setSpacing(8)
        import_row.setAlignment(Qt.AlignVCenter)
        import_btn = QPushButton("↓  Import Selected → files/")
        import_btn.setStyleSheet(
            "QPushButton{background-color:#2d2d30;color:#4da8f0;border:1px solid #007acc;"
            "padding:0px;border-radius:4px;font-size:12px;font-weight:bold;"
            "font-family:'Segoe UI',sans-serif;}"
            "QPushButton:hover{background-color:#1a2d3a;border-color:#1a9aff;color:#7ac8ff;}"
            "QPushButton:pressed{background-color:#0a1a2a;}"
            "QPushButton:disabled{background-color:#2d2d30;color:#555555;border-color:#444444;}"
        )
        import_btn.setFixedSize(_IMP_W, _IMP_H)
        import_btn.setEnabled(False)
        import_btn.clicked.connect(lambda _checked=False: self._import_files())
        self._register_import_button(import_btn)
        import_row.addWidget(import_btn)
        clear_translated_btn = QPushButton("✕  Clear translated/")
        clear_translated_btn.setStyleSheet(
            "QPushButton{background-color:#2d2d30;color:#cc4444;border:1px solid #8b0000;"
            "padding:0px;border-radius:4px;font-size:12px;font-weight:bold;"
            "font-family:'Segoe UI',sans-serif;}"
            "QPushButton:hover{background-color:#3a2020;border-color:#cc2222;color:#ff6666;}"
            "QPushButton:pressed{background-color:#4a1010;}"
        )
        clear_translated_btn.setFixedSize(_IMP_W, _IMP_H)
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
        hint.setStyleSheet("color:#9d9d9d;font-size:13px;padding-bottom:6px;")
        layout.addWidget(hint)

        copy_row = QHBoxLayout()
        copy_btn = _make_btn("📋  Copy Prompt for Copilot", "#555")
        copy_btn.setFixedWidth(220)
        copy_btn.setToolTip("Copies a prompt explaining all speaker formats — paste into Copilot with game files")
        copy_btn.clicked.connect(self._copy_speaker_prompt)
        copy_row.addWidget(copy_btn)
        copy_row.addStretch()
        layout.addLayout(copy_row)

        # ---- Flag checkboxes ------------------------------------------------
        cb_box_title = QLabel("Speaker flags")
        cb_box_title.setStyleSheet("color:#4ec9b0;font-size:13px;font-weight:bold;")
        layout.addWidget(cb_box_title)
        cb_box = QWidget()
        cb_box.setObjectName("tbox")
        cb_box.setStyleSheet(self._task_box_style())
        cb_inner = QVBoxLayout(cb_box)
        cb_inner.setContentsMargins(10, 8, 10, 8)
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

        layout.addWidget(_make_section_label("Step 4 — TL Phase 1"))

        # ---- Pre-flight: text wrap configuration ----------------------------
        wrap_box_title = QLabel("Pre-flight — Text Wrap Width")
        wrap_box_title.setStyleSheet("color:#4ec9b0;font-size:13px;font-weight:bold;")
        layout.addWidget(wrap_box_title)
        wrap_box = QWidget()
        wrap_box.setObjectName("tbox")
        wrap_box.setStyleSheet(self._task_box_style())
        wrap_inner = QVBoxLayout(wrap_box)
        wrap_inner.setContentsMargins(10, 8, 10, 8)
        wrap_inner.setSpacing(4)

        wrap_hint = QLabel(
            "Adjust if lines overflow or wrap too early in-game, then click Apply to write to .env."
        )
        wrap_hint.setWordWrap(True)
        wrap_hint.setStyleSheet("color:#9d9d9d;font-size:13px;")
        wrap_inner.addWidget(wrap_hint)

        # All three spinboxes on one row
        spins_row = QHBoxLayout()
        spins_row.setSpacing(16)

        def _spin_pair(label_text: str, default: int):
            lbl = QLabel(label_text)
            lbl.setStyleSheet("color:#cccccc;font-size:13px;")
            sp = QSpinBox()
            sp.setRange(20, 300)
            sp.setValue(default)
            sp.setFixedWidth(60)
            return lbl, sp

        lbl_w,  self.wrap_width_spin = _spin_pair("Dialogue", 60)
        lbl_lw, self.wrap_list_spin  = _spin_pair("List/Help", 70)
        lbl_nw, self.wrap_note_spin  = _spin_pair("Notes", 60)

        for lbl, sp in [(lbl_w, self.wrap_width_spin),
                        (lbl_lw, self.wrap_list_spin),
                        (lbl_nw, self.wrap_note_spin)]:
            spins_row.addWidget(lbl)
            spins_row.addWidget(sp)
        spins_row.addStretch()

        apply_wrap_btn = _make_btn("✔  Apply to .env", "#3a7a3a")
        apply_wrap_btn.setFixedWidth(140)
        apply_wrap_btn.setToolTip("Write width / listWidth / noteWidth into .env")
        apply_wrap_btn.clicked.connect(self._apply_wrap_config)
        spins_row.addWidget(apply_wrap_btn)

        wrap_inner.addLayout(spins_row)
        layout.addWidget(wrap_box)

        # ---- Phase 0 --------------------------------------------------------
        p0_box_title = QLabel("Phase 0  –  Core Database Files")
        p0_box_title.setStyleSheet("color:#4ec9b0;font-size:13px;font-weight:bold;")
        layout.addWidget(p0_box_title)
        p0_box = QWidget()
        p0_box.setObjectName("tbox")
        p0_box.setStyleSheet(self._task_box_style())
        p0_inner = QVBoxLayout(p0_box)
        p0_inner.setContentsMargins(10, 8, 10, 8)
        p0_inner.setSpacing(4)
        p0_desc = QLabel(
            "Actors, Armors, Weapons, Items, Skills, States, Classes, Enemies, System, MapInfos — "
            "run first before any event-code phases."
        )
        p0_desc.setStyleSheet("color:#9d9d9d;font-size:13px;")
        p0_desc.setWordWrap(True)
        p0_inner.addWidget(p0_desc)
        p0_row = QHBoxLayout()
        p0_row.setSpacing(10)
        self._run_p0_btn = _make_btn("►  Run Phase 0", "#4a7a4a")
        self._run_p0_btn.setFixedWidth(200)
        self._run_p0_btn.setToolTip(
            "Sets engine to RPG Maker MV/MZ, selects only DB files, all event codes OFF."
        )
        self._run_p0_btn.clicked.connect(lambda: self._run_phase(0))
        p0_row.addWidget(self._run_p0_btn)
        self._p0_status_lbl = QLabel("")
        self._p0_status_lbl.setStyleSheet("color:#6a9a6a;font-size:13px;padding-left:4px;")
        p0_row.addWidget(self._p0_status_lbl)
        p0_row.addStretch()
        p0_inner.addLayout(p0_row)
        layout.addWidget(p0_box)

        # ---- Phase 1 --------------------------------------------------------
        p1_box_title = QLabel("Phase 1  –  Safe Codes (dialogue + choices)")
        p1_box_title.setStyleSheet("color:#4ec9b0;font-size:13px;font-weight:bold;")
        layout.addWidget(p1_box_title)
        p1_box = QWidget()
        p1_box.setObjectName("tbox")
        p1_box.setStyleSheet(self._task_box_style())
        p1_inner = QVBoxLayout(p1_box)
        p1_inner.setContentsMargins(10, 8, 10, 8)
        p1_inner.setSpacing(4)
        p1_desc = QLabel(
            "Codes ON: 101 (Name), 401 (Show Text), 405 (continued), 102 (Choices), 408 (extra lines). "
            "Speaker lines in the log should look like  [Speaker]: Dialogue."
        )
        p1_desc.setStyleSheet("color:#9d9d9d;font-size:13px;")
        p1_desc.setWordWrap(True)
        p1_inner.addWidget(p1_desc)
        p1_row = QHBoxLayout()
        p1_row.setSpacing(10)
        self._run_p1_btn = _make_btn("►  Run Phase 1", "#007acc")
        self._run_p1_btn.setFixedWidth(200)
        self._run_p1_btn.setToolTip("Applies Phase 1 code settings and starts translation")
        self._run_p1_btn.clicked.connect(lambda: self._run_phase(1))
        p1_row.addWidget(self._run_p1_btn)
        self._p1_status_lbl = QLabel("")
        self._p1_status_lbl.setStyleSheet("color:#6ab4d4;font-size:13px;padding-left:4px;")
        p1_row.addWidget(self._p1_status_lbl)
        p1_row.addStretch()
        p1_inner.addLayout(p1_row)
        layout.addWidget(p1_box)

        # ---- Phase 1b -------------------------------------------------------
        p1b_box_title = QLabel("Phase 1b  –  Build Variable Cache (code 111)")
        p1b_box_title.setStyleSheet("color:#4ec9b0;font-size:13px;font-weight:bold;")
        layout.addWidget(p1b_box_title)
        p1b_box = QWidget()
        p1b_box.setObjectName("tbox")
        p1b_box.setStyleSheet(self._task_box_style())
        p1b_inner = QVBoxLayout(p1b_box)
        p1b_inner.setContentsMargins(10, 8, 10, 8)
        p1b_inner.setSpacing(4)
        p1b_desc = QLabel(
            "Scans code 111 branches that compare \u2018$gameVariables\u2019 and builds the var_translation_map cache. "
            "Run before Phase 2 so code 122 strings are automatically matched."
        )
        p1b_desc.setStyleSheet("color:#9d9d9d;font-size:13px;")
        p1b_desc.setWordWrap(True)
        p1b_inner.addWidget(p1b_desc)
        p1b_row = QHBoxLayout()
        p1b_row.setSpacing(10)
        self._run_p1b_btn = _make_btn("►  Run Phase 1b", "#2a5a7a")
        self._run_p1b_btn.setFixedWidth(200)
        self._run_p1b_btn.setToolTip("Applies Phase 1b code settings (111 only) and starts translation")
        self._run_p1b_btn.clicked.connect(lambda: self._run_phase("1b"))
        p1b_row.addWidget(self._run_p1b_btn)
        self._p1b_status_lbl = QLabel("")
        self._p1b_status_lbl.setStyleSheet("color:#6aaac4;font-size:13px;padding-left:4px;")
        p1b_row.addWidget(self._p1b_status_lbl)
        p1b_row.addStretch()
        p1b_inner.addLayout(p1b_row)
        layout.addWidget(p1b_box)

    def _build_step5_tl_phase2(self, layout: QVBoxLayout):

        layout.addWidget(_make_section_label("Step 5 — TL Phase 2"))

        # ── Pre-flight card: description + prompt + var range ──────────────
        pre_box_title = QLabel("Pre-flight \u2014 Audit & Configure")
        pre_box_title.setStyleSheet("color:#4ec9b0;font-size:13px;font-weight:bold;")
        layout.addWidget(pre_box_title)
        pre_box = QWidget()
        pre_box.setObjectName("tbox")
        pre_box.setStyleSheet(self._task_box_style())
        pre_inner = QVBoxLayout(pre_box)
        pre_inner.setContentsMargins(10, 8, 10, 8)
        pre_inner.setSpacing(6)

        pre_top = QHBoxLayout()
        pre_top.setSpacing(12)
        desc_lbl = QLabel(
            "Targets script/variable strings and plugin text. "
            "Use the Plugin Prompt to audit the game first, then enable only the codes with visible text."
        )
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet("color:#9d9d9d;font-size:13px;")
        pre_top.addWidget(desc_lbl, 1)
        copy_risky_btn = _make_btn("📋  Copy Plugin Prompt", "#555")
        copy_risky_btn.setFixedWidth(200)
        copy_risky_btn.setToolTip(
            "Copy a Copilot prompt that audits code 122 variable ranges and all optional "
            "plugin/script codes for visible text."
        )
        copy_risky_btn.clicked.connect(self._copy_plugin_prompt)
        pre_top.addWidget(copy_risky_btn)
        pre_inner.addLayout(pre_top)

        # Divider line
        div = QFrame()
        div.setFrameShape(QFrame.HLine)
        div.setStyleSheet("QFrame{background-color:#3a3a3a;border:none;max-height:1px;}")
        pre_inner.addWidget(div)

        # Code 122 var range row
        var_row = QHBoxLayout()
        var_row.setSpacing(6)
        var_lbl = QLabel("Code 122 var range:")
        var_lbl.setStyleSheet("color:#cccccc;font-size:13px;")
        var_row.addWidget(var_lbl)
        from PyQt5.QtGui import QIntValidator
        self._p2_var_min = QLineEdit("0")
        self._p2_var_min.setValidator(QIntValidator(0, 99999))
        self._p2_var_min.setFixedWidth(55)
        self._p2_var_min.setAlignment(Qt.AlignCenter)
        self._p2_var_min.setToolTip("Minimum variable ID to translate (inclusive)")
        var_row.addWidget(self._p2_var_min)
        dash_lbl = QLabel("–")
        dash_lbl.setStyleSheet("color:#9d9d9d;")
        var_row.addWidget(dash_lbl)
        self._p2_var_max = QLineEdit("2000")
        self._p2_var_max.setValidator(QIntValidator(1, 99999))
        self._p2_var_max.setFixedWidth(55)
        self._p2_var_max.setAlignment(Qt.AlignCenter)
        self._p2_var_max.setToolTip("Maximum variable ID to translate (exclusive)")
        var_row.addWidget(self._p2_var_max)
        apply_range_btn = _make_btn("Apply", "#3a3a3a")
        apply_range_btn.setFixedWidth(80)
        apply_range_btn.setToolTip("Write CODE122_VAR_MIN / CODE122_VAR_MAX to the module")
        apply_range_btn.clicked.connect(self._apply_var_range)
        var_row.addWidget(apply_range_btn)
        self._p2_var_min.editingFinished.connect(self._schedule_p2_config_apply)
        self._p2_var_max.editingFinished.connect(self._schedule_p2_config_apply)
        var_row.addStretch()
        pre_inner.addLayout(var_row)
        layout.addWidget(pre_box)

        # Pre-populate range
        try:
            from gui.config_integration import ConfigIntegration
            cur = ConfigIntegration().read_current_config()
            if "CODE122_VAR_MIN" in cur:
                self._p2_var_min.setText(str(cur["CODE122_VAR_MIN"]))
            if "CODE122_VAR_MAX" in cur:
                self._p2_var_max.setText(str(cur["CODE122_VAR_MAX"]))
        except Exception:
            pass

        # ── Code toggles ───────────────────────────────────────────────────
        codes_hdr = QHBoxLayout()
        codes_title_lbl = QLabel("Enable Codes")
        codes_title_lbl.setStyleSheet("color:#4ec9b0;font-size:13px;font-weight:bold;")
        codes_hdr.addWidget(codes_title_lbl)
        codes_hdr.addStretch()
        codes_select_all_btn = QPushButton("☑")
        codes_select_all_btn.setCheckable(True)
        codes_select_all_btn.setFixedSize(28, 28)
        codes_select_all_btn.setStyleSheet(
            "QPushButton{background:transparent;color:#888888;border:none;"
            "font-size:18px;padding:0 2px;}"
            "QPushButton:hover{color:#cccccc;}"
            "QPushButton:checked{color:#007acc;}"
        )
        codes_select_all_btn.setToolTip("Select / Deselect All")
        codes_hdr.addWidget(codes_select_all_btn)
        layout.addLayout(codes_hdr)

        toggle_box = QWidget()
        toggle_box.setObjectName("cbbox")
        toggle_box.setStyleSheet(self._checkbox_box_style())
        toggle_box_layout = QVBoxLayout(toggle_box)
        toggle_box_layout.setContentsMargins(8, 8, 10, 6)
        toggle_box_layout.setSpacing(3)

        toggle_grid_container = QWidget()
        toggle_grid = QGridLayout(toggle_grid_container)
        toggle_grid.setContentsMargins(0, 0, 0, 0)
        toggle_grid.setHorizontalSpacing(24)
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
            cb.stateChanged.connect(self._schedule_p2_config_apply)
            self._p2_code_checks[code_key] = cb
        toggle_box_layout.addWidget(toggle_grid_container)

        def _toggle_codes(checked):
            codes_select_all_btn.setText("☑" if checked else "☐")
            for cb in self._p2_code_checks.values():
                cb.setChecked(checked)
        codes_select_all_btn.toggled.connect(_toggle_codes)
        layout.addWidget(toggle_box)

        # ── 357 plugins + 355/655 patterns — side by side ──────────────────
        lists_row = QHBoxLayout()
        lists_row.setSpacing(8)

        _icon_btn_style = (
            "QPushButton{background:transparent;color:#888888;border:none;"
            "font-size:18px;padding:0 2px;}"
            "QPushButton:hover{color:#cccccc;}"
            "QPushButton:checked{color:#007acc;}"
        )

        # Left column: header row + group box
        left_col = QVBoxLayout()
        left_col.setSpacing(3)

        plugin357_hdr = QHBoxLayout()
        plugin357_title_lbl = QLabel("Code 357 — Plugin Handlers (MZ)")
        plugin357_title_lbl.setStyleSheet("color:#4ec9b0;font-size:13px;font-weight:bold;")
        plugin357_hdr.addWidget(plugin357_title_lbl)
        plugin357_hdr.addStretch()
        plugin357_select_all_btn = QPushButton("☑")
        plugin357_select_all_btn.setCheckable(True)
        plugin357_select_all_btn.setFixedSize(28, 28)
        plugin357_select_all_btn.setStyleSheet(_icon_btn_style)
        plugin357_select_all_btn.setToolTip("Select / Deselect All")
        plugin357_hdr.addWidget(plugin357_select_all_btn)
        left_col.addLayout(plugin357_hdr)

        plugin357_box = QWidget()
        plugin357_box.setObjectName("cbbox")
        plugin357_box.setStyleSheet(self._checkbox_box_style())
        plugin357_inner = QVBoxLayout(plugin357_box)
        plugin357_inner.setContentsMargins(8, 8, 10, 6)
        plugin357_inner.setSpacing(3)

        plugin357_container = QWidget()
        plugin357_vbox = QVBoxLayout(plugin357_container)
        plugin357_vbox.setContentsMargins(4, 2, 4, 2)
        plugin357_vbox.setSpacing(2)
        self._p2_plugin_checks: dict = {}
        try:
            from modules.rpgmakermvmz import HEADER_MAPPINGS_357 as _HM357
            for key in sorted(_HM357.keys(), key=str.casefold):
                cb = QCheckBox(key)
                cb.setStyleSheet("color:#cccccc;font-size:13px;")
                cb.stateChanged.connect(self._schedule_p2_config_apply)
                plugin357_vbox.addWidget(cb)
                self._p2_plugin_checks[key] = cb
        except Exception:
            pass
        plugin357_vbox.addStretch()

        plugin357_scroll = QScrollArea()
        plugin357_scroll.setWidgetResizable(True)
        plugin357_scroll.setWidget(plugin357_container)
        plugin357_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        plugin357_scroll.setStyleSheet("QScrollArea{border:none;}")
        plugin357_inner.addWidget(plugin357_scroll, 1)
        plugin357_box.setMaximumHeight(260)

        def _toggle_plugins357(checked):
            plugin357_select_all_btn.setText("☑" if checked else "☐")
            for cb in self._p2_plugin_checks.values():
                cb.setChecked(checked)
        plugin357_select_all_btn.toggled.connect(_toggle_plugins357)

        left_col.addWidget(plugin357_box, 1)
        lists_row.addLayout(left_col, 1)

        # Right column: header row + group box
        right_col = QVBoxLayout()
        right_col.setSpacing(3)

        patterns_hdr = QHBoxLayout()
        patterns_title_lbl = QLabel("Code 355/655 — Script Patterns")
        patterns_title_lbl.setStyleSheet("color:#4ec9b0;font-size:13px;font-weight:bold;")
        patterns_hdr.addWidget(patterns_title_lbl)
        patterns_hdr.addStretch()
        patterns_select_all_btn = QPushButton("☑")
        patterns_select_all_btn.setCheckable(True)
        patterns_select_all_btn.setFixedSize(28, 28)
        patterns_select_all_btn.setStyleSheet(_icon_btn_style)
        patterns_select_all_btn.setToolTip("Select / Deselect All")
        patterns_hdr.addWidget(patterns_select_all_btn)
        right_col.addLayout(patterns_hdr)

        patterns_box = QWidget()
        patterns_box.setObjectName("cbbox")
        patterns_box.setStyleSheet(self._checkbox_box_style())
        patterns_inner_layout = QVBoxLayout(patterns_box)
        patterns_inner_layout.setContentsMargins(8, 8, 10, 6)
        patterns_inner_layout.setSpacing(3)

        patterns_container = QWidget()
        patterns_vbox = QVBoxLayout(patterns_container)
        patterns_vbox.setContentsMargins(4, 2, 4, 2)
        patterns_vbox.setSpacing(2)
        self._p2_pattern_checks: dict = {}
        try:
            from modules.rpgmakermvmz import PATTERNS_355655 as _PAT
            for key in sorted(_PAT.keys(), key=str.casefold):
                cb = QCheckBox(key)
                cb.setStyleSheet("color:#cccccc;font-size:13px;")
                cb.stateChanged.connect(self._schedule_p2_config_apply)
                patterns_vbox.addWidget(cb)
                self._p2_pattern_checks[key] = cb
        except Exception:
            pass
        patterns_vbox.addStretch()

        patterns_scroll = QScrollArea()
        patterns_scroll.setWidgetResizable(True)
        patterns_scroll.setWidget(patterns_container)
        patterns_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        patterns_scroll.setStyleSheet("QScrollArea{border:none;}")
        patterns_inner_layout.addWidget(patterns_scroll, 1)
        patterns_box.setMaximumHeight(260)

        def _toggle_patterns(checked):
            patterns_select_all_btn.setText("☑" if checked else "☐")
            for cb in self._p2_pattern_checks.values():
                cb.setChecked(checked)
        patterns_select_all_btn.toggled.connect(_toggle_patterns)

        right_col.addWidget(patterns_box, 1)
        lists_row.addLayout(right_col, 1)

        layout.addLayout(lists_row)

        # ── Bottom row: Run ────────────────────────────────────────────────
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(10)
        _P2_BTN_WIDTH = 200
        _P2_BTN_HEIGHT = 36
        self._run_p2_btn = _make_btn("►  Run Phase 2", "#7a4a00")
        self._run_p2_btn.setFixedSize(_P2_BTN_WIDTH, _P2_BTN_HEIGHT)
        self._run_p2_btn.setToolTip(
            "Applies Phase 2 code settings and starts translation with event files pre-selected."
        )
        self._run_p2_btn.clicked.connect(lambda: self._run_phase(2))
        bottom_row.addWidget(self._run_p2_btn)

        self._p2_status_lbl = QLabel("")
        self._p2_status_lbl.setStyleSheet("color:#d4aa68;font-size:13px;padding-left:4px;")
        bottom_row.addWidget(self._p2_status_lbl)
        bottom_row.addStretch()
        layout.addLayout(bottom_row)

        self._p2_auto_apply_timer = QTimer(self)
        self._p2_auto_apply_timer.setSingleShot(True)
        self._p2_auto_apply_timer.timeout.connect(self._apply_p2_config)

        # Pre-populate all Phase 2 checkboxes from current module state
        self._populate_p2_checkboxes()

    # ── Step 5: plugins.js / Ace scripts Translation ───────────────────────

    def _build_step6_plugins_js(self, layout: QVBoxLayout):
        self._step6_section_label = _make_section_label("Step 6 — Translate plugins.js")
        layout.addWidget(self._step6_section_label)

        self._step6_hint = QLabel(
            "Translate the visible Japanese strings in js/plugins.js without breaking "
            "game logic. First copy vocab.txt into the game folder so the AI can use it "
            "as a glossary, then copy the prompt and paste it into Copilot or Cursor with "
            "plugins.js, vocab.txt, and optionally System.json attached."
        )
        self._step6_hint.setWordWrap(True)
        self._step6_hint.setStyleSheet("color:#9d9d9d;font-size:13px;padding-bottom:6px;")
        layout.addWidget(self._step6_hint)

        _BTN_WIDTH = 240

        vocab_btn = _make_btn("📄  Copy vocab.txt → Game Folder", "#555")
        vocab_btn.setFixedWidth(_BTN_WIDTH)
        vocab_btn.setToolTip(
            "Copy vocab.txt to <game root>/vocab.txt so you can attach it "
            "alongside plugins.js when running the AI prompt."
        )
        vocab_btn.clicked.connect(self._copy_vocab_to_game)

        self._step6_copy_btn = _make_btn("📋  Copy Prompt for Copilot", "#555")
        self._step6_copy_btn.setFixedWidth(_BTN_WIDTH)
        self._step6_copy_btn.setToolTip(
            "Copy a prompt that instructs Copilot/Cursor to translate only "
            "visible player-facing strings in plugins.js, using vocab.txt as a glossary."
        )
        self._step6_copy_btn.clicked.connect(self._copy_plugins_js_translate_prompt)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addWidget(vocab_btn)
        btn_row.addWidget(self._step6_copy_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    # ── Step 6: Export ──────────────────────────────────────────────────────

    def _build_step7_export(self, layout: QVBoxLayout):
        layout.addWidget(_make_section_label("Step 7 — Export to Game"))
        hint = QLabel(
            "Copy translated files back into the game's data folder to patch the game in-place."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#9d9d9d;font-size:13px;padding-bottom:4px;")
        layout.addWidget(hint)

        _EXP_W = 260
        row = QHBoxLayout()
        row.setSpacing(8)
        export_active_btn = _make_btn("📤  Export Active Files", "#3a7a3a")
        export_active_btn.setFixedWidth(_EXP_W)
        export_active_btn.setToolTip(
            "Only export files whose names match those currently in files/\n"
            "(i.e. the files you imported for this project)"
        )
        export_active_btn.clicked.connect(self._export_active_files)
        row.addWidget(export_active_btn)

        export_all_btn = _make_btn("📤  Export ALL translated/", "#555")
        export_all_btn.setFixedWidth(_EXP_W)
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
            self._detected_on_show = True  # new folder chosen — treat as already-shown
            self._ask_clear_old_files()
            self._detect_folder()

    def _ask_clear_old_files(self):
        """Prompt the user to clear /files and /translated to avoid stale data conflicts."""
        import shutil

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
        result = msg.exec_()

        if result != QMessageBox.Yes:
            return

        base = Path(__file__).resolve().parent.parent
        cleared = []
        errors = []
        for folder_name in ("files", "translated"):
            target = base / folder_name
            if target.is_dir():
                for child in target.iterdir():
                    if child.name == ".gitkeep":
                        continue
                    try:
                        if child.is_dir():
                            shutil.rmtree(child)
                        else:
                            child.unlink()
                        cleared.append(child.name)
                    except Exception as exc:  # noqa: BLE001
                        errors.append(f"{child.name}: {exc}")

        if cleared:
            self._log(f"🗑  Cleared {len(cleared)} item(s) from files/ and translated/.")
        else:
            self._log("ℹ  files/ and translated/ were already empty.")
        for err in errors:
            self._log(f"⚠  Could not remove {err}")

    def _update_step6_for_engine(self, is_ace: bool) -> None:
        """Adapt the Step 6 tab label and content for MV/MZ (plugins.js) vs Ace (.rb scripts)."""
        # Step 1 prettier section — only relevant for MV/MZ
        for attr in ("_pp_dazedformat_title", "_pp_dazedformat_box",
                     "_pp_plugins_js_title", "_pp_plugins_js_box"):
            w = getattr(self, attr, None)
            if w is not None:
                w.setVisible(not is_ace)
        # Tab label
        self._step_tabs.setTabText(6, "6  Scripts" if is_ace else "6  Plugins.js")
        # Step 6 section header
        lbl = getattr(self, "_step6_section_label", None)
        if lbl is not None:
            lbl.setText("Step 6 — Translate Ace Scripts (.rb)" if is_ace
                        else "Step 6 — Translate plugins.js")
        # Hint text
        hint = getattr(self, "_step6_hint", None)
        if hint is not None:
            if is_ace:
                hint.setText(
                    "Translate visible Japanese strings in the Ace script files "
                    "(ace_json/scripts/*.rb) without breaking game logic. "
                    "Attach the .rb files and vocab.txt to Copilot or Cursor, "
                    "then paste the copied prompt."
                )
            else:
                hint.setText(
                    "Translate the visible Japanese strings in js/plugins.js without breaking "
                    "game logic. First copy vocab.txt into the game folder so the AI can use it "
                    "as a glossary, then copy the prompt and paste it into Copilot or Cursor with "
                    "plugins.js, vocab.txt, and optionally System.json attached."
                )
        # Prompt button tooltip
        btn = getattr(self, "_step6_copy_btn", None)
        if btn is not None:
            if is_ace:
                btn.setToolTip(
                    "Copy a prompt that instructs Copilot/Cursor to translate only "
                    "visible player-facing strings in the Ace .rb script files."
                )
            else:
                btn.setToolTip(
                    "Copy a prompt that instructs Copilot/Cursor to translate only "
                    "visible player-facing strings in plugins.js, using vocab.txt as a glossary."
                )

    def _detect_folder(self):
        folder = self.folder_edit.text().strip()
        if not folder:
            self._log("⚠  No folder path entered.")
            return

        self._save_setting("last_game_folder", folder)
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

        # Reset ACE state from any previous detection
        self._ace_encrypted = False
        self._ace_json_dir = ""
        self._ace_rvdata_dir = ""
        self._update_step6_for_engine(False)

        root_path = Path(folder)

        # ── RPGMaker Ace encrypted: Game.rgss* present (no Data/ yet) ────────
        # Must be checked BEFORE find_data_folder, which returns UNKNOWN for
        # encrypted games (no rvdata2 files exist until the archive is extracted).
        rgss_files = list(root_path.glob("Game.rgss*"))
        if rgss_files:
            self._ace_encrypted = True
            rgss_name = rgss_files[0].name
            self.detected_label.setText(
                f"⚠  RPGMaker Ace — Encrypted ({rgss_name}). Decrypt before importing."
            )
            self.detected_label.setStyleSheet(
                "color:#e9a12a;font-size:13px;padding:4px 8px;"
                "background-color:#2b2010;border:1px solid #5a4010;"
                "border-radius:4px;margin:4px 0;"
            )
            self._log(f"⚠  RPGMaker Ace (encrypted) detected — found: {rgss_name}")
            self._update_step6_for_engine(True)
            self._show_ace_decrypt_notice(folder, str(rgss_files[0]))
            return
        # ─────────────────────────────────────────────────────────────────────

        try:
            from util.project_scanner import find_data_folder
            data_path, engine = find_data_folder(folder)
        except Exception as exc:
            self.detected_label.setText(f"Error: {exc}")
            self.detected_label.setStyleSheet(
                "color:#f48771;font-size:13px;padding:4px 8px;"
                "background-color:#2b1a1a;border:1px solid #5a2a2a;"
                "border-radius:4px;margin:4px 0;"
            )
            return

        if data_path is None:
            self.detected_label.setText(
                "⚠  No recognised data folder found. "
                "Make sure this is a valid RPGMaker game directory."
            )
            self.detected_label.setStyleSheet(
                "color:#e9a12a;font-size:13px;padding:4px 8px;"
                "background-color:#2b2010;border:1px solid #5a4010;"
                "border-radius:4px;margin:4px 0;"
            )
            return

        self._data_path = str(data_path)
        self._engine = engine

        # ── RPGMaker Ace decrypted: rvdata2 present, no rgss archive ─────────
        if engine == "ACE":
            self._ace_encrypted = False
            self._ace_rvdata_dir = str(data_path)
            self._engine = "MVMZ"  # scan JSON files like MVMZ
            self._update_step6_for_engine(True)
            self._log("RPGMaker Ace (decrypted) detected.")
            self._log(f"  rvdata2 dir : {data_path}")

            ace_json = root_path / "ace_json"
            if ace_json.is_dir() and any(ace_json.glob("*.json")):
                self._ace_json_dir = str(ace_json)
                self._data_path = str(ace_json)
                self._log(f"  ace_json dir: {ace_json} (existing — skipping RV2JSON -c)")
                self.detected_label.setText(
                    f"Engine: Ace (via RV2JSON)   ·   ace_json: {ace_json}"
                )
                self.detected_label.setStyleSheet(
                    "color:#6a9a6a;font-size:13px;padding:4px 8px;"
                    "background-color:#1f2b1f;border:1px solid #2a4a2a;"
                    "border-radius:4px;margin:4px 0;"
                )
                worker = _ScanWorker(self._data_path, "MVMZ")
                worker.done.connect(self._on_scan_done)
                worker.error.connect(lambda e: self._log(f"❌ Scan error: {e}"))
                self._worker = worker
                worker.start()
            else:
                self._ace_json_dir = str(ace_json)
                self._data_path = str(ace_json)
                self.detected_label.setText(
                    "RPGMaker Ace (decrypted)  ·  Creating JSON files with RV2JSON…"
                )
                self.detected_label.setStyleSheet(
                    "color:#9d9d9d;font-size:13px;padding:4px 8px;"
                    "background-color:#252526;border:1px solid #3c3c3c;"
                    "border-radius:4px;margin:4px 0;"
                )
                self._run_rv2json_create()
            return  # scan continues above or in _on_rv2json_create_done
        # ─────────────────────────────────────────────────────────────────────

        self.detected_label.setText(
            f"Engine: {engine}   ·   Data folder: {data_path}"
        )
        self.detected_label.setStyleSheet(
            "color:#6a9a6a;font-size:13px;padding:4px 8px;"
            "background-color:#1f2b1f;border:1px solid #2a4a2a;"
            "border-radius:4px;margin:4px 0;"
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
            lw.setFlags(lw.flags() | Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
            lw.setCheckState(Qt.Checked if item["default"] else Qt.Unchecked)
            if cat == "core":
                lw.setForeground(__import__("PyQt5.QtGui", fromlist=["QColor"]).QColor("#9cdcfe"))
            elif cat == "map":
                lw.setForeground(__import__("PyQt5.QtGui", fromlist=["QColor"]).QColor("#c5c5c0"))
            self.file_list.addItem(lw)

        self._set_import_buttons_enabled(len(items) > 0)
        self._log(f"Found {len(items)} importable file(s).")
        self._populate_preprocess_paths()
        if items:
            self._log("Choose files to import, then click 📥 to copy them into files/.")

    def _select_all_files(self):
        count = self.file_list.count()
        if not count:
            return
        self._syncing_file_checks = True
        try:
            for i in range(count):
                self.file_list.item(i).setCheckState(Qt.Checked)
        finally:
            self._syncing_file_checks = False
        self._log(f"✔  Selected all {count} file(s).")

    def _deselect_all_files(self):
        count = self.file_list.count()
        if not count:
            return
        self._syncing_file_checks = True
        try:
            for i in range(count):
                self.file_list.item(i).setCheckState(Qt.Unchecked)
        finally:
            self._syncing_file_checks = False
        self._log(f"✔  Deselected all {count} file(s).")

    def _select_core_only(self):
        core = other = 0
        self._syncing_file_checks = True
        try:
            for i in range(self.file_list.count()):
                item = self.file_list.item(i)
                data = item.data(Qt.UserRole)
                is_core = bool(data and data.get("category") == "core")
                item.setCheckState(Qt.Checked if is_core else Qt.Unchecked)
                if is_core:
                    core += 1
                else:
                    other += 1
        finally:
            self._syncing_file_checks = False
        if self.file_list.count():
            self._log(f"✔  Selected {core} core file(s); deselected {other} other(s).")

    def _sync_selected_file_checks(self, changed_item: QListWidgetItem):
        """Apply a checkbox change to the current Ctrl/Shift-selected file rows."""
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
        self._worker = worker
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
        self._set_import_buttons_enabled(bool(self.file_list.count()))
        if errors:
            self._log(f"⚠  {len(errors)} error(s) during import:")
            for e in errors[:10]:
                self._log(f"   {e}")
        else:
            self._last_import_signature = self._pending_import_signature
        self._pending_import_signature = None
        self._log(f"✅ Imported {count} file(s) into files/")

    # ─────────────────────────────────────────────────────────────────────────
    # Step 1 – Vocab
    # ─────────────────────────────────────────────────────────────────────────

    _BASE_SEPARATOR = "# ── Base Vocabulary (auto-appended from vocab_base.txt — do not edit below) ──\n"

    def _copy_glossary_prompt(self):
        """Copy the glossary prompt to clipboard, injecting known speakers from vocab.txt."""
        speakers = self._read_vocab_speakers()
        if speakers:
            speaker_lines = "\n".join(f"  {orig} ({tl})" for orig, tl in speakers)
            known_block = (
                "<known_speakers>\n"
                "These character names were extracted from the game files by the Parse Speakers tool.\n"
                "For the '# Game Characters' section, output entries for ONLY these names.\n"
                "Skip any unnamed NPCs, generic enemies, or narration-only entries.\n"
                "\n"
                + speaker_lines
                + "\n</known_speakers>\n\n"
            )
            final_prompt = known_block + self._PROMPT_GLOSSARY
        else:
            final_prompt = self._PROMPT_GLOSSARY
        self._copy_to_clipboard(final_prompt, "Glossary prompt copied.")

    def _read_vocab_speakers(self) -> list[tuple[str, str]]:
        """Parse the '# Speakers' section from vocab.txt and return (orig, tl) pairs."""
        vocab_path = Path("vocab.txt")
        if not vocab_path.exists():
            return []
        try:
            content = vocab_path.read_text(encoding="utf-8")
        except Exception:
            return []

        import re as _re
        # Find the # Speakers block (ends at next # header or EOF)
        m = _re.search(
            r"^[\t ]*#\s*Speakers\s*$\r?\n(.*?)(?=^[\t ]*#|\Z)",
            content,
            _re.MULTILINE | _re.DOTALL,
        )
        if not m:
            return []

        results = []
        for line in m.group(1).splitlines():
            line = line.strip()
            if not line:
                continue
            # Expected format: "日本語 (English)"
            pm = _re.match(r"^(.+?)\s+\((.+?)\)\s*$", line)
            if pm:
                results.append((pm.group(1), pm.group(2)))
        return results

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
        self._p2_loading_config = True
        try:
            from gui.config_integration import ConfigIntegration
            ci = ConfigIntegration()
            # Code toggle checkboxes
            cur = ci.read_current_config()
            if "CODE122_VAR_MIN" in cur:
                self._p2_var_min.setText(str(cur["CODE122_VAR_MIN"]))
            if "CODE122_VAR_MAX" in cur:
                self._p2_var_max.setText(str(cur["CODE122_VAR_MAX"]))
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
        finally:
            self._p2_loading_config = False

    def _schedule_p2_config_apply(self, *_args):
        """Debounce auto-saving Phase 2 settings while the user changes controls."""
        if self._p2_loading_config:
            return
        timer = getattr(self, "_p2_auto_apply_timer", None)
        if timer is not None:
            timer.start(300)
        else:
            self._apply_p2_config()

    def _apply_p2_config(self):
        """Write Phase 2 code and plugin settings when controls change."""
        try:
            var_min = int(self._p2_var_min.text() or 0)
            var_max = int(self._p2_var_max.text() or 2000)
        except ValueError:
            self._p2_status_lbl.setText("Invalid Code 122 range")
            self._log("❌ Phase 2 config not saved: invalid Code 122 range")
            return

        try:
            from gui.config_integration import ConfigIntegration
            ci = ConfigIntegration()

            code_cfg = {
                code_key: cb.isChecked()
                for code_key, cb in getattr(self, "_p2_code_checks", {}).items()
            }
            code_cfg.update({
                "CODE122_VAR_MIN": var_min,
                "CODE122_VAR_MAX": var_max,
            })
            ci.update_rpgmaker_config(code_cfg)

            enabled_357 = {
                k for k, cb in getattr(self, "_p2_plugin_checks", {}).items()
                if cb.isChecked()
            }
            enabled_355655 = {
                k for k, cb in getattr(self, "_p2_pattern_checks", {}).items()
                if cb.isChecked()
            }
            ci.update_plugin_config(enabled_357, enabled_355655)

            self._p2_status_lbl.setText(
                f"Auto-saved ({len(enabled_357)} handlers, {len(enabled_355655)} patterns)"
            )

            try:
                if self.parent_window and hasattr(self.parent_window, "config_tab"):
                    ct = self.parent_window.config_tab
                    if hasattr(ct, "mvmz_tab") and ct.mvmz_tab:
                        ct.mvmz_tab.refresh_from_module()
            except Exception:
                pass
        except Exception as exc:
            self._p2_status_lbl.setText("Auto-save failed")
            self._log(f"❌ Could not save Phase 2 settings: {exc}")

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
            return

        src = Path("vocab.txt")
        if not src.exists():
            self._log("⚠  vocab.txt not found — save it in Step 3 first.")
            return

        import shutil
        dst = Path(game_root) / "vocab.txt"
        try:
            shutil.copy2(src, dst)
            self._log(f"✅ vocab.txt copied to {dst}")
        except Exception as exc:
            self._log(f"❌ Could not copy vocab.txt: {exc}")

    def _copy_plugins_js_translate_prompt(self):
        is_ace = bool(getattr(self, "_ace_rvdata_dir", "") or getattr(self, "_ace_json_dir", ""))
        if is_ace:
            QApplication.clipboard().setText(self._ACE_SCRIPTS_TRANSLATE_PROMPT)
            self._log("Ace scripts translation prompt copied to clipboard.")
        else:
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
        self._navigate_to_translation(file_preset, auto_start=True, mode_text="Translate")

    def _navigate_to_translation(self, file_preset: str, auto_start: bool = False, mode_text: str | None = None):
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

            # 2. Set requested mode after selecting the engine, since the engine
            # change refreshes the mode list.
            if mode_text:
                try:
                    mode_combo = tt.mode_combo
                    mode_idx = mode_combo.findText(mode_text)
                    if mode_idx >= 0:
                        mode_combo.setCurrentIndex(mode_idx)
                except Exception:
                    pass

            # 3. Determine which files belong to each preset
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

            # 4. Apply check states to the file list
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

            # 5. Navigate
            if hasattr(pw, "content_stack"):
                pw.content_stack.setCurrentIndex(0)
                if hasattr(pw, "nav_buttons"):
                    for i, btn in enumerate(pw.nav_buttons):
                        btn.setChecked(i == 0)

            # 6. Auto-start translation so the user doesn't need an extra click
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

    # ─────────────────────────────────────────────────────────────────────────
    # RPGMaker Ace helpers
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _ace_tool_path(name: str) -> Path:
        return Path(__file__).resolve().parent.parent / "util" / "ace" / name

    def _show_ace_decrypt_notice(self, game_root: str, rgss_path: str):
        """Show a dialog explaining how to decrypt the encrypted Ace archive."""
        rgss_name = Path(rgss_path).name
        msg = QMessageBox(self)
        msg.setWindowTitle("RPGMaker Ace — Encrypted Game")
        msg.setIcon(QMessageBox.Warning)
        msg.setTextFormat(Qt.RichText)
        msg.setText(
            f"<b>This game is encrypted.</b><br><br>"
            f"Found: <code>{rgss_name}</code><br><br>"
            "To use this game with the translation tool:<br>"
            "<ol>"
            "<li>Run <b>RPGMakerDecrypter.exe</b> (button below) to extract the game files</li>"
            "<li>Back up the <code>.rgss</code> archive to a safe location</li>"
            f"<li>Delete <code>{rgss_name}</code> from the game folder</li>"
            "<li>Re-scan the folder in this tool (press Enter in the path box)</li>"
            "</ol>"
        )
        run_btn = msg.addButton("Run RPGMakerDecrypter.exe", QMessageBox.ActionRole)
        msg.addButton(QMessageBox.Ok)
        msg.exec_()
        if msg.clickedButton() == run_btn:
            self._run_ace_decrypter(game_root)

    def _run_ace_decrypter(self, game_root: str):
        decrypter = self._ace_tool_path("RPGMakerDecrypter.exe")
        if not decrypter.is_file():
            self._log(f"❌ RPGMakerDecrypter.exe not found at {decrypter}")
            return
        self._log(f"Running RPGMakerDecrypter.exe in {game_root} …")
        w = _SubprocessWorker([str(decrypter)], cwd=game_root, label="RPGMakerDecrypter")
        w.log.connect(self._log)
        w.done.connect(lambda ok, msg: self._log(("✅ " if ok else "❌ ") + msg))
        self._worker = w
        w.start()

    def _run_rv2json_create(self):
        """Run RV2JSON.exe -c to convert rvdata2 → JSON files (run from game root)."""
        rv2json = self._ace_tool_path("RV2JSON.exe")
        if not rv2json.is_file():
            self._log(f"❌ RV2JSON.exe not found at {rv2json}")
            return
        game_root = self.folder_edit.text().strip()
        # -c takes no path flags — must be run from the game root so it can
        # find the Data/ folder automatically and creates JSON/ alongside it.
        cmd = [str(rv2json), "-c"]
        self._log(f"$ {' '.join(cmd)}  (cwd: {game_root})")
        w = _SubprocessWorker(cmd, cwd=game_root, label="RV2JSON -c")
        w.log.connect(self._log)
        w.done.connect(self._on_rv2json_create_done)
        self._worker = w
        w.start()

    def _on_rv2json_create_done(self, ok: bool, msg: str):
        self._log(("✅ " if ok else "❌ ") + msg)
        if not ok:
            self.detected_label.setText("❌ RV2JSON -c failed — check log for details.")
            self.detected_label.setStyleSheet(
                "color:#f48771;font-size:13px;padding:4px 8px;"
                "background-color:#2b1a1a;border:1px solid #5a2a2a;"
                "border-radius:4px;margin:4px 0;"
            )
            return

        ace_json = Path(self._ace_json_dir)
        if not ace_json.is_dir() or not any(ace_json.glob("*.json")):
            self._log(f"⚠  RV2JSON ran but ace_json folder has no JSON files: {ace_json}")
            self.detected_label.setText("⚠  ace_json not populated after RV2JSON -c. Check log.")
            self.detected_label.setStyleSheet(
                "color:#e9a12a;font-size:13px;padding:4px 8px;"
                "background-color:#2b2010;border:1px solid #5a4010;"
                "border-radius:4px;margin:4px 0;"
            )
            return

        self._log(f"JSON files ready in: {ace_json}")
        self.detected_label.setText(
            f"Engine: Ace (via RV2JSON)   ·   ace_json: {ace_json}"
        )
        self.detected_label.setStyleSheet(
            "color:#6a9a6a;font-size:13px;padding:4px 8px;"
            "background-color:#1f2b1f;border:1px solid #2a4a2a;"
            "border-radius:4px;margin:4px 0;"
        )
        worker = _ScanWorker(self._data_path, "MVMZ")
        worker.done.connect(self._on_scan_done)
        worker.error.connect(lambda e: self._log(f"❌ Scan error: {e}"))
        self._worker = worker
        worker.start()

    def _run_rv2json_update(self):
        """Run RV2JSON.exe -u to write translated JSON back to rvdata2 files."""
        rv2json = self._ace_tool_path("RV2JSON.exe")
        if not rv2json.is_file():
            self._log(f"❌ RV2JSON.exe not found at {rv2json}")
            return
        game_root = self.folder_edit.text().strip()
        if not game_root:
            self._log("❌ RV2JSON -u: game root folder not set.")
            return
        # Run without path flags (same as -c): tool finds Data/ and ace_json/
        # relative to the game root automatically.
        cmd = [str(rv2json), "-u"]
        self._log("RV2JSON: updating rvdata2 files…")
        self._log(f"$ {' '.join(cmd)}  (cwd: {game_root})")
        w = _SubprocessWorker(cmd, cwd=game_root, label="RV2JSON -u")
        w.log.connect(self._log)
        w.done.connect(lambda ok, msg: self._log(("✅ " if ok else "❌ ") + msg))
        self._worker = w
        w.start()

    def _on_export_done(self, count: int, errors: list):
        if errors:
            self._log(f"⚠  {len(errors)} error(s) during export:")
            for e in errors[:10]:
                self._log(f"   {e}")
        self._log(f"✅ Exported {count} file(s) to game folder.")
        # For RPGMaker Ace: convert the exported JSON files back to rvdata2
        if self._ace_json_dir and self._ace_rvdata_dir:
            self._run_rv2json_update()

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
            self._log(f"► {label} …")
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
